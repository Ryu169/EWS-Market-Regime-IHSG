"""Bandingkan delapan kandidat fitur pada dua model, tanpa membuka label test.

Pemeriksaan saja: python train_feature_candidates.py --check-data
Training lokal:   python train_feature_candidates.py

Default: 8 kombinasi fitur x 2 algoritma x 5 fold = 80 kali fit.
Data, parameter, dan tanggal evaluasi ditetapkan sebelum model dilatih.
"""
from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timezone
import importlib.metadata
import math
from pathlib import Path
import sys
from unittest.mock import patch

sys.dont_write_bytecode = True
import train_models as base
import train_domestic15 as evaluation
import tune_models as tuning

HERE = Path(__file__).resolve().parent
DEFAULT_FEATURE_DIR = HERE.parent / 'Future-Enginering/output/feature_candidates_20261029'
PARAMETER_PROTOCOL = HERE / 'runs/inflation_change_rebuilt_20261028/protocol.json'
VARIANTS = (
    'baseline_15', 'without_volume_14', 'relative_trend_15', 'risk_adjusted_16',
    'foreign_pressure_17', 'domestic_policy_18', 'macro_5d_18',
    'combined_exploratory_24',
)
RAW_COLUMNS = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume', 'Foreign',
               'USD_IDR', 'Brent', 'US10Y', 'BI_Rate', 'Inflation_YoY']
DOMESTIC = ['bi_rate_change', 'inflation_change_release']
BLOCKED_LABEL_TABLES = {'test.csv', 'eligible_labeled.csv', 'ihsg_features_targets_all.csv'}


def require(condition, message):
    """Validasi tetap aktif meskipun Python dijalankan dengan opsi -O."""
    if not condition:
        raise ValueError(message)


def read_table(path, columns):
    """Baca CSV dengan header, struktur baris, dan tanggal yang diperiksa."""
    with path.open(encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        require(reader.fieldnames == columns, f'Urutan/daftar kolom berbeda: {path}')
        rows = list(reader)
    require(bool(rows), f'CSV kosong: {path}')
    for row in rows:
        require(None not in row and all(v is not None for v in row.values()),
                f'Struktur CSV rusak: {path}')
        require(date.fromisoformat(row['Date']).isoformat() == row['Date'],
                f'Tanggal bukan ISO: {path}')
    dates = [r['Date'] for r in rows]
    require(dates == sorted(set(dates)), f'Tanggal tidak unik/urut: {path}')
    return rows


def finite(value):
    return value != '' and math.isfinite(float(value))


def join_rows(rows, common, raw_dates, features):
    """Gabungkan X terbaru ke y lama berdasarkan Date; horizon tidak dihitung ulang.

    Label lima hari dibuat pada kalender IHSG lengkap sebelum baris fitur kosong
    dibuang. Menghitung shift(-5) dari CSV complete akan mengubah horizon saat
    ada tanggal yang dikeluarkan, sehingga cara itu tidak dipakai di sini.
    """
    output = []
    for original in rows:
        source = common.get(original['Date'])
        if source is None:
            continue
        index = original['calendar_index']
        require(0 <= index < len(raw_dates) - 5 and raw_dates[index] == original['Date']
                and raw_dates[index + 5] == original['label_end_date'],
                f'Kalender/horizon label berubah: {original["Date"]}')
        # Fitur inti lama harus cocok dengan hasil hitung ulang dari sumber sama.
        for column in base.CORE:
            require(math.isclose(float(original[column]), float(source[column]),
                                 abs_tol=1e-12, rel_tol=1e-12),
                    f'Fitur inti berbeda dari sumber label: {original["Date"]} {column}')
        # Pertahankan y_t, future_return_5d, label_end_date, dan calendar_index.
        # Hanya kolom fitur yang diganti. Semua fitur wajib bernilai finite.
        output.append({**original, **{c: source[c] for c in features}})
    require(bool(output), 'Tidak ada baris tersisa setelah penyamaan tanggal.')
    return output


def prepare(feature_dir, variants, models):
    """Pemeriksaan data tanpa mengimpor dependency ML atau memanggil fit()."""
    feature_dir = Path(feature_dir).resolve()
    variants = ['baseline_15', *[v for v in variants if v != 'baseline_15']]
    variants, models = list(dict.fromkeys(variants)), list(dict.fromkeys(models))
    require(bool(models) and set(models) <= set(tuning.MODELS), 'Nama model tidak dikenal.')
    require(set(variants) <= set(VARIANTS), 'Nama varian tidak dikenal.')
    inputs = []

    def track(path):
        path = Path(path).resolve()
        inputs.append(path)
        return path

    # 1. Ambil fitur dari hasil feature engineering terbaru, bukan simulasi.
    contract = base.read_json(track(feature_dir / 'feature_contract.json'))
    report = base.read_json(track(feature_dir / 'feature_report.json'))
    status = base.read_json(track(feature_dir / 'run_status.json'))
    require(status['status'] == 'completed', 'Feature engineering belum selesai.')
    require(list(contract['feature_sets']) == list(VARIANTS), 'Rencana delapan varian berubah.')
    all_features = contract['all_features']
    require(len(all_features) == len(set(all_features)) == 26, 'Diperlukan tepat 26 fitur unik.')
    require(contract['feature_sets']['baseline_15'] == [*base.CORE, *DOMESTIC],
            'Daftar baseline 15 fitur berbeda dari protokol.')
    require(contract['target_column'] == 'y_t' and contract['horizon_trading_days'] == 5,
            'Target harus market regime lima hari perdagangan.')
    forbidden = set(RAW_COLUMNS) | {'y_t', 'future_return_5d', 'label_end_date', 'calendar_index'}
    forbidden.update(contract['forbidden_model_input'])
    require(not forbidden.intersection(all_features), 'Kolom mentah/target masuk daftar X.')
    for name, columns in contract['feature_sets'].items():
        require(bool(columns) and len(columns) == len(set(columns))
                and set(columns) <= set(all_features) and set(DOMESTIC) <= set(columns),
                f'Whitelist fitur/domestik tidak valid: {name}')

    raw_path = track(report['input_file'])
    require(base.sha256(raw_path) == report['raw_sha256'],
            'Preprocessing berubah setelah fitur dibuat. Bentuk ulang fitur terlebih dahulu.')
    raw = read_table(raw_path, RAW_COLUMNS)
    full = read_table(track(feature_dir / 'ihsg_preprocessing_features_all.csv'),
                      [*RAW_COLUMNS, *all_features])
    require(len(raw) == len(full) == report['rows'], 'Jumlah/tanggal sumber fitur berubah.')
    require(all({c: row[c] for c in RAW_COLUMNS} == source for row, source in zip(full, raw)),
            'Kolom mentah/tanggal dalam hasil fitur berbeda dari preprocessing.')

    # 2. Gunakan mask complete bersama: seluruh pembanding memakai tanggal sama.
    # CSV ini mencakup periode penelitian penuh, tetapi bukan semuanya data fit.
    common_rows = read_table(track(feature_dir / contract['common_complete_file']),
                             [*RAW_COLUMNS, *all_features])
    expected_common = [r for r in full if all(finite(r[c]) for c in all_features)]
    require(common_rows == expected_common and len(common_rows) == report['common_complete_rows'],
            'Tabel common complete tidak sesuai fitur lengkap atau jumlah pada laporan.')
    common = {r['Date']: r for r in common_rows}
    common_dates = list(common)
    for variant in variants:
        columns = contract['feature_sets'][variant]
        table = read_table(track(feature_dir / f'variants/{variant}_common_complete.csv'),
                           ['Date', *columns])
        require(table == [{c: r[c] for c in ['Date', *columns]} for r in common_rows],
                f'Isi/tanggal CSV varian berbeda dari common complete: {variant}')

    # 3. Baca hanya label development dan lima fold lama yang sudah dipurge.
    # base.load_bundle memeriksa checksum, threshold, urutan waktu, dan kelas.
    target_dir = Path(contract['target_source_dir']).resolve()
    for filename, key in [('thresholds.json', 'thresholds_sha256'),
                          ('split_metadata.json', 'split_metadata_sha256')]:
        require(base.sha256(target_dir / filename) == contract[key],
                f'Metadata target berubah: {filename}')
    bundle = base.load_bundle({'data_dir': str(target_dir), 'feature_set': 'core'}, HERE)
    inputs.extend(target_dir / n for n in bundle['input_hashes'])
    parameters = base.read_json(track(PARAMETER_PROTOCOL))
    require(Path(parameters['feature_dir']).resolve() == Path(report['reference_feature_dir']).resolve(),
            'Referensi parameter dan referensi fitur tidak sama.')
    require(parameters['thresholds'] == bundle['thresholds']
            and parameters['target_hashes'] == bundle['input_hashes'],
            'Label/fold/threshold berbeda dari eksperimen baseline yang dibekukan.')

    raw_dates = [r['Date'] for r in raw]
    folds, excluded = [], []
    previous_train = set()
    for old in bundle['folds']:
        fold = {'fold': old['fold']}
        for part in ['train', 'validation']:
            fold[part] = join_rows(old[part], common, raw_dates, all_features)
            excluded.extend({'Fold': old['fold'], 'Part': part, 'Date': r['Date'],
                             'Reason': 'not_in_common_complete'}
                            for r in old[part] if r['Date'] not in common)
        train_dates = {r['Date'] for r in fold['train']}
        require(previous_train <= train_dates and {r['y_t'] for r in fold['train']} == set(base.CLASSES),
                'Fold training tidak bertambah atau kehilangan kelas.')
        previous_train = train_dates
        base.validate_boundary(fold['train'], fold['validation'],
                               bundle['metadata']['splits_after_purge']['test']['start_date'])
        folds.append(fold)
    validation_dates = [r['Date'] for f in folds for r in f['validation']]
    require(validation_dates == contract['common_validation_dates']
            and len(validation_dates) == report['common_validation_rows'],
            'Tanggal/jumlah validation berbeda dari rencana sebelum training.')
    development = join_rows(bundle['development'], common, raw_dates, all_features)
    require(len(development) == report['common_development_rows'], 'Jumlah development berubah.')

    # Simpan checksum kode dan semua input yang benar-benar dipakai.
    inputs.extend(Path(module.__file__).resolve() for module in [base, evaluation, tuning])
    inputs.append(Path(__file__).resolve())
    hashes = {str(p): base.sha256(p) for p in dict.fromkeys(inputs)}
    fold_info = [{'fold': f['fold'], 'train_rows': len(f['train']),
                  'validation_rows': len(f['validation']),
                  'train_start': f['train'][0]['Date'], 'train_end': f['train'][-1]['Date'],
                  'validation_start': f['validation'][0]['Date'],
                  'validation_end': f['validation'][-1]['Date']} for f in folds]
    protocol = {
        'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'feature_dir': str(feature_dir), 'preprocessing_file': str(raw_path),
        'common_complete_rows': len(common_rows), 'common_development_rows': len(development),
        'common_dates': common_dates, 'validation_dates': validation_dates,
        'validation_rows': len(validation_dates), 'folds': fold_info,
        'feature_plan': {v: contract['feature_sets'][v] for v in variants}, 'models': models,
        'source_parameter_protocol': str(PARAMETER_PROTOCOL),
        'parameters': {m: parameters['parameters'][m] for m in models},
        'target_source_dir': str(target_dir), 'thresholds': bundle['thresholds'],
        'class_order': dict(zip(base.CLASSES, base.NAMES)),
        'boosting_fold_fits': len(variants) * len(models) * len(folds),
        'comparison': 'Mean Macro F1 validation; accuracy dan Recall Bearish dilaporkan bersama.',
        'same_common_mask_for_all_variants': True, 'tuning': False, 'early_stopping': False,
        'final_test_previously_evaluated': True, 'final_test_labels_read': False,
        'automatic_dashboard_adoption': False, 'development_refit': False,
        'input_hashes': hashes, 'limitations': report['limitations'],
    }
    return {'protocol': protocol, 'folds': folds, 'excluded': excluded}


def print_plan(protocol):
    print(f"Sumber fitur: {protocol['feature_dir']}", flush=True)
    print(f"Complete seluruh periode: {protocol['common_complete_rows']:,} baris. "
          f"Development: {protocol['common_development_rows']:,}; "
          f"validation: {protocol['validation_rows']:,} tanggal unik.", flush=True)
    for f in protocol['folds']:
        print(f"  Fold {f['fold']}: train={f['train_rows']}, validation={f['validation_rows']} "
              f"({f['validation_start']} s.d. {f['validation_end']})", flush=True)
    print(f"Rencana: {len(protocol['feature_plan'])} varian x {len(protocol['models'])} model "
          f"x 5 fold = {protocol['boosting_fold_fits']} fit. Target tetap 5 hari.", flush=True)


def result_rows(results, controls, validation_rows):
    """Delta selalu terhadap baseline yang dilatih ulang pada tanggal identik."""
    rows = []
    for model, variants in results.items():
        baseline = variants['baseline_15']['summary']
        for variant, result in variants.items():
            row = evaluation.leaderboard_row(model, variant, result)
            row.update({
                'MeanTrainAccuracy': result['training_summary']['accuracy']['mean'],
                'MeanTrainMacroF1': result['training_summary']['macro_f1']['mean'],
                'DeltaAccuracyVsBaselinePP': 100 * (row['MeanAccuracy'] - baseline['accuracy']['mean']),
                'DeltaMacroF1VsBaseline': row['MeanMacroF1'] - baseline['macro_f1']['mean'],
                'DeltaRecallBearishVsBaselinePP': 100 * (row['MeanRecallBearish']
                                                       - baseline['recall_bearish']['mean']),
            })
            rows.append(row)
    for name, result in controls.items():
        row = evaluation.leaderboard_row(name, 'control', {**result, 'validation_rows': validation_rows})
        row.update({c: None for c in ['MeanTrainAccuracy', 'MeanTrainMacroF1',
                    'DeltaAccuracyVsBaselinePP', 'DeltaMacroF1VsBaseline', 'DeltaRecallBearishVsBaselinePP']})
        rows.append(row)
    return rows


def write_report(out, protocol, rows):
    text = ['# Hasil perbandingan kandidat fitur', '',
        f"{len(protocol['feature_plan'])} varian dibandingkan pada {protocol['validation_rows']} "
        'tanggal validation yang sama. Angka berikut adalah rata-rata lima fold, bukan skor training.', '',
        '| Model | Varian | Fitur | Accuracy | Macro F1 | Recall Bearish | Delta accuracy (pp) |',
        '|---|---|---:|---:|---:|---:|---:|']
    for row in sorted(rows, key=lambda r: (r['Model'], -r['MeanMacroF1'])):
        delta = row['DeltaAccuracyVsBaselinePP']
        text.append(f"| {row['Model']} | {row['Variant']} | {row['FeatureCount']} | "
                    f"{row['MeanAccuracy']:.2%} | {row['MeanMacroF1']:.4f} | "
                    f"{row['MeanRecallBearish']:.2%} | {delta:+.2f} |" if delta is not None else
                    f"| {row['Model']} | {row['Variant']} | — | {row['MeanAccuracy']:.2%} | "
                    f"{row['MeanMacroF1']:.4f} | {row['MeanRecallBearish']:.2%} | — |")
    text += ['', 'Delta dibandingkan dengan baseline_15 dari algoritma yang sama dalam run ini. '
        'Baseline lama tidak menjadi pembanding langsung karena tanggal training berbeda.', '',
        'Majority selalu memilih kelas terbanyak dalam training setiap fold. Persistence '
        'memakai regime return lima hari terakhir sebagai prediksi lima hari berikutnya.', '',
        'Lihat accuracy bersama Macro F1, Recall Bearish, confusion matrix, dan skor per fold. '
        'Kenaikan pada validation berulang ini masih merupakan hasil eksplorasi; final test lama '
        'sudah pernah dilihat dan tidak dibuka lagi oleh skrip ini. Accuracy 70% bukan hasil yang dijamin.', '',
        'Model setiap fold tersimpan pada `<model>/<varian>/fold_<nomor>/model.joblib`. '
        'Prediksi validation dan probabilitasnya ada pada `validation_predictions.csv`. '
        'Model belum direfit pada seluruh development dan dashboard belum diganti.', '',
        '## Keterbatasan data', '', *[f'- {item}' for item in protocol['limitations']]]
    (out / 'HASIL_TRAINING_FITUR_KANDIDAT.md').write_text('\n'.join(text) + '\n', encoding='utf-8')


def train(prepared, out):
    """Latih dan evaluasi; hanya dipanggil saat pengguna tidak memilih --check-data."""
    protocol, folds = prepared['protocol'], prepared['folds']
    out = Path(out).resolve()
    require(not out.exists(), f'Folder hasil sudah ada; pilih folder baru: {out}')
    # 4. Impor ML baru di sini. .fit() berjalan dengan CPU perangkat pengguna.
    modules = base.dependencies(protocol['models'])
    import sklearn  # Verifikasi dependency metrik sebelum membuat folder hasil.
    protocol['package_versions'] = {p: importlib.metadata.version(p)
        for p in ['numpy', 'joblib', 'scikit-learn', *protocol['models']]}
    out.mkdir(parents=True, exist_ok=False)
    base.write_json(out / 'run_status.json', {'status': 'running', 'completed_fold_fits': 0})
    completed = 0
    try:
        # Protokol ditulis sebelum fit agar rencana tidak mengikuti hasil skor.
        base.write_json(out / 'protocol.json', protocol)
        base.write_csv(out / 'excluded_dates.csv', prepared['excluded'], ['Fold', 'Part', 'Date', 'Reason'])
        controls = evaluation.baselines(folds, protocol['thresholds'])
        base.write_json(out / 'controls.json', controls)
        results = {}
        for model in protocol['models']:
            results[model] = {}
            for variant, features in protocol['feature_plan'].items():
                print(f"\n[{model}] {variant} — {len(features)} fitur", flush=True)
                # evaluate membentuk X hanya dari whitelist features dan y dari y_t.
                # Tiap fold: fit data masa lalu -> prediksi validation -> hitung metrik
                # -> simpan model -> muat ulang dan cocokkan probabilitasnya.
                result = evaluation.evaluate(model, protocol['parameters'][model], folds,
                                             features, modules, out / model / variant)
                results[model][variant] = result
                completed += len(folds)
                rows = result_rows(results, controls, protocol['validation_rows'])
                base.write_csv(out / 'leaderboard.csv', rows, list(rows[0]))
                base.write_json(out / 'run_status.json', {'status': 'running',
                    'completed_fold_fits': completed, 'planned_fold_fits': protocol['boosting_fold_fits']})

        # 5. Pastikan input tidak berubah selama run, lalu simpan ringkasan.
        require(all(base.sha256(Path(p)) == h for p, h in protocol['input_hashes'].items()),
                'Input/kode berubah saat training. Hasil belum dapat dianggap terverifikasi.')
        base.write_json(out / 'summary.json', {'status': 'completed_exploratory_feature_comparison',
            'results': results, 'controls': controls, 'validation_rows': protocol['validation_rows'],
            'boosting_fold_fits': completed, 'final_test_labels_read': False,
            'automatic_dashboard_adoption': False, 'development_refit': False})
        write_report(out, protocol, rows)
        base.write_json(out / 'verification.json', {'status': 'passed',
            'input_hashes_unchanged': True, 'same_dates_for_all_variants': True,
            'all_metrics_recomputed_with_sklearn': True, 'models_reloaded': completed,
            'final_test_labels_read': False, 'dashboard_updated': False})
        base.write_json(out / 'run_status.json', {'status': 'completed',
            'completed_fold_fits': completed, 'planned_fold_fits': protocol['boosting_fold_fits']})
        print(f'\nSelesai. Hasil: {out}', flush=True)
        print('Kirim leaderboard.csv atau HASIL_TRAINING_FITUR_KANDIDAT.md untuk dibahas.', flush=True)
    except BaseException as exc:
        base.write_json(out / 'run_status.json', {'status': 'interrupted' if isinstance(exc, KeyboardInterrupt)
            else 'failed', 'completed_fold_fits': completed, 'error': str(exc)})
        raise
    return out


def guarded_call(callback, *args):
    """Tolak pembacaan label test/all; membaca fitur seluruh periode tetap boleh."""
    original_open, original_bytes = Path.open, Path.read_bytes

    def checked_open(path, *positional, **keywords):
        require(path.name not in BLOCKED_LABEL_TABLES, f'Pembacaan label test/all ditolak: {path}')
        return original_open(path, *positional, **keywords)

    def checked_bytes(path, *positional, **keywords):
        require(path.name not in BLOCKED_LABEL_TABLES, f'Pembacaan label test/all ditolak: {path}')
        return original_bytes(path, *positional, **keywords)

    with patch.object(Path, 'open', checked_open), patch.object(Path, 'read_bytes', checked_bytes):
        return callback(*args)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--feature-dir', type=Path, default=DEFAULT_FEATURE_DIR)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--models', nargs='+', choices=tuning.MODELS, default=tuning.MODELS)
    parser.add_argument('--variants', nargs='+', choices=VARIANTS, default=list(VARIANTS),
                        help='baseline_15 selalu disertakan untuk perbandingan yang setara.')
    parser.add_argument('--check-data', action='store_true', help='Periksa input saja; tidak melatih atau menulis hasil.')
    args = parser.parse_args(argv)
    try:
        prepared = guarded_call(prepare, args.feature_dir, args.variants, args.models)
        print_plan(prepared['protocol'])
        if args.check_data:
            print('Pemeriksaan data LOLOS. Training belum dijalankan; tidak ada hasil baru ditulis.')
            return 0
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
        out = args.output_dir or HERE / 'runs' / f'feature_candidates_{stamp}'
        guarded_call(train, prepared, out)
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(1, f'Gagal: {exc}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
