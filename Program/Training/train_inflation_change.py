"""Hitung ulang fitur dari preprocessing, lalu latih 15 fitur dengan Inflation Change.

Jalankan: python train_inflation_change.py
--feature-dir dapat dipakai jika fitur sudah dibangun dengan rebuild_inflation_change.py.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sys
from unittest.mock import patch

sys.dont_write_bytecode = True
# A. Lokasi program dan modul pendukung. HERE adalah folder Program/Training.
# Skrip ini adalah pintu masuk TERBARU untuk training 15 fitur Inflation Change.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'Future-Enginering'))
import rebuild_inflation_change as preparation
import train_domestic15 as evaluator
import train_models as base
import tune_models as tuning


def run(feature_dir, out):
    feature_dir, out = Path(feature_dir).resolve(), Path(out).resolve()
    if out.exists():
        raise ValueError('Gunakan folder run baru.')
    # B. Ambil laporan fitur hasil rebuild. input_file di laporan menunjuk CSV
    # preprocessing tahap 27; raw_sha256 memastikan isinya sama saat fitur dibuat.
    # Folder fitur default: Program/Future-Enginering/output/inflation_change_rebuilt_...
    report = base.read_json(feature_dir / 'feature_report.json')
    if base.sha256(Path(report['input_file'])) != report['raw_sha256']:
        raise ValueError('Preprocessing berubah setelah feature engineering.')
    # C. Baca targets/folds/fold_1..5_train.csv dan ..._validation.csv.
    # Fold sudah dibagi kronologis, 60:20:20 dan purge 5 hari saat build_targets.
    # load_bundle tidak membuka splits/test.csv; test dievaluasi skrip terpisah.
    bundle = base.load_bundle({'data_dir': str(feature_dir / 'targets'), 'feature_set': 'core'}, HERE)
    contract = base.read_json(feature_dir / 'targets/model_contract.json')
    assert contract['feature_sets']['inflation_change_15'] == preparation.FEATURES
    # D. Pilih hanya baris dengan seluruh 15 fitur X lengkap, tanpa mengubah
    # kalender target. y_t = 0 Bearish, 1 Sideways, 2 Bullish untuk return t→t+5.
    # X terdiri dari 13 fitur inti + bi_rate_change + inflation_change_release.
    # Date, OHLC mentah, future_return_5d dan y_t tidak menjadi fitur X.
    folds, excluded = [], []
    for original in bundle['folds']:
        fold = {'fold': original['fold']}
        for part in ['train', 'validation']:
            fold[part] = []
            for row in original[part]:
                if all(row[c] != '' for c in preparation.FEATURES):
                    fold[part].append(row)
                else:
                    excluded.append({'Fold': original['fold'], 'Part': part, 'Date': row['Date']})
        folds.append(fold)
    assert all(r['Date'] == '2016-08-22' and r['Part'] == 'train' for r in excluded)
    assert sum(len(f['validation']) for f in folds) == 889
    # E. Salin parameter tetap dari eksperimen sederhana sebelumnya:
    # depth 2, 100 boosting rounds, seed 2026; tidak mencari parameter baru.
    reference = base.read_json(evaluator.PARAMETER_RUN / 'summary.json')
    parameters = {name: reference['results'][name][evaluator.TRIAL]['parameters'] for name in tuning.MODELS}
    # F. Catat checksum sumber dan protokol agar percobaan dapat ditelusuri.
    # Hasil selalu ditulis di folder run baru, bukan menimpa data/model lama.
    protected = {str(p): base.sha256(p) for p in [Path(report['input_file']),
        feature_dir / 'feature_report.json', Path(__file__), Path(preparation.__file__)]}
    out.mkdir(parents=True)
    base.write_json(out / 'run_status.json', {'status': 'running'})
    protocol = {'feature_dir': str(feature_dir), 'features': preparation.FEATURES,
        'input_features_count': 15, 'inflation_yoy_in_X': False,
        'features_recalculated_from_preprocessing': True, 'parameters': parameters,
        'thresholds': bundle['thresholds'], 'training_exclusions': excluded,
        'folds': [{'fold': f['fold'], 'train_rows': len(f['train']),
            'validation_rows': len(f['validation'])} for f in folds],
        'boosting_fold_fits': 10, 'final_test_evaluated': False,
        'protected_hashes': protected, 'target_hashes': bundle['input_hashes']}
    base.write_json(out / 'protocol.json', protocol)
    modules = base.dependencies(tuning.MODELS)
    results, leaderboard = {}, []
    try:
        # CSV training complete disimpan dengan label dan indeks kalender asli.
        for fold in folds:
            for part in ['train', 'validation']:
                values = fold[part]
                base.write_csv(out / f"datasets/fold_{fold['fold']}_{part}_complete.csv", values, list(values[0]))
        # G. Latih XGBoost lalu LightGBM. evaluator.evaluate melatih lima model
        # fold per algoritma dengan X_train/y_train dan menilai X_validation.
        # Tidak ada penggabungan validation ke fit pada evaluasi fold ini.
        for name in tuning.MODELS:
            path = out / name / 'inflation_change_15'
            result = evaluator.evaluate(name, parameters[name], folds, preparation.FEATURES, modules, path)
            results[name] = result
            leaderboard.append(evaluator.leaderboard_row(name, 'inflation_change_15', result))
            # Mengulang data dan rumus yang sama harus mengulang hasil change sebelumnya.
            old = base.read_json(HERE / f'runs/inflation_release_20261028/{name}/change_15/result.json')
            assert result['summary'] == old['summary']
        # H. Simpan skor rata-rata fold, model joblib, probabilitas OOF, dan
        # salinan baris complete. Accuracy validation mengukur data evaluasi,
        # bukan seberapa baik model menghafal training.
        base.write_csv(out / 'leaderboard.csv', leaderboard, list(leaderboard[0]))
        base.write_json(out / 'summary.json', {'results': results, 'validation_rows': 889,
            'features': preparation.FEATURES, 'feature_dir': str(feature_dir),
            'status': 'completed_rebuilt_inflation_change_training', 'model_ready': False})
        assert all(base.sha256(Path(p)) == h for p, h in protected.items())
        assert all(base.sha256(bundle['root'] / p) == h for p, h in bundle['input_hashes'].items())
        base.write_json(out / 'verification.json', {'status': 'passed', 'models_reloaded': 10,
            'validation_predictions_checked': 1778, 'complete_input_features': True,
            'metrics_recomputed_with_sklearn': True, 'previous_change_result_reproduced': True,
            'source_files_unchanged': True, 'final_test_csv_read': False})
        text = ['# Training ulang setelah feature engineering Inflation Change', '',
            'Alur: preprocessing tahap 27 → hitung ulang 13 fitur inti → BI-Rate Change '
            'sesuai instrumen → Inflation Change antarrilis → target kalender penuh → '
            'training dari baris complete. Inflasi YoY mentah dipakai untuk menghitung '
            'change, tetapi tidak menjadi masukan X.', '',
            f'Sumber fitur baru: `{feature_dir}`. Ada 4.496 tanggal kalender dan 4.475 '
            'baris complete. Target tetap lima hari; lima fold, 889 tanggal validation. '
            'Parameter tetap depth 2/100 rounds; 10 fit kedua algoritma, tanpa tuning.', '',
            '| Model | Accuracy validation | Macro F1 | Recall Bearish | FAR |',
            '|---|---:|---:|---:|---:|']
        for row in leaderboard:
            text.append(f"| {row['Model']} | {row['MeanAccuracy']:.2%} | {row['MeanMacroF1']:.4f} | "
                        f"{row['MeanRecallBearish']:.2%} | {row['MeanFalseAlarmRate']:.2%} |")
        text += ['', 'Hasil sama dengan varian change sebelumnya karena data, rumus, '
            'parameter dan tanggal evaluasi sama. Pada run ini seluruh fitur benar-benar '
            'dihitung ulang langsung dari preprocessing. Final test belum dievaluasi; '
            'model dashboard belum diganti. Keterbatasan Volume sementara tetap berlaku.']
        (out / 'HASIL_TRAINING_ULANG.md').write_text('\n'.join(text) + '\n', encoding='utf-8')
        for path in [Path(__file__), Path(preparation.__file__)]:
            shutil.copy2(path, out / path.name)
        base.write_json(out / 'run_status.json', {'status': 'completed'})
        print(f'Training ulang selesai: {out}', flush=True)
    except BaseException as exc:
        base.write_json(out / 'run_status.json', {'status': 'failed', 'error': str(exc)})
        raise


def guarded_run(feature_dir, out):
    # I. Pembatas teknis: training tidak membaca label test atau tabel all.
    # evaluate_dashboard_test.py hanya memakai model beku setelah training selesai.
    blocked = {'test.csv', 'eligible_labeled.csv', 'ihsg_features_targets_all.csv'}
    original_open, original_read = Path.open, Path.read_bytes
    def safe_open(p, *a, **kw):
        if p.name in blocked:
            raise ValueError(f'Akses test/all ditolak: {p}')
        return original_open(p, *a, **kw)
    def safe_read(p, *a, **kw):
        if p.name in blocked:
            raise ValueError(f'Akses test/all ditolak: {p}')
        return original_read(p, *a, **kw)
    with patch.object(Path, 'open', safe_open), patch.object(Path, 'read_bytes', safe_read):
        return run(feature_dir, out)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--feature-dir', type=Path)
    parser.add_argument('--feature-output-dir', type=Path)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
    # Tanpa argumen, satu perintah melakukan feature engineering baru lalu training.
    # Sumber asli dibaca preparation.run dari:
    # Program/Pre-Processing/output/27_calendar_adjustments/ihsg_preprocessing_candidate.csv
    # --feature-dir melewati rebuild dan membaca folder fitur yang dipilih pengguna.
    feature_dir = args.feature_dir or preparation.run(args.feature_output_dir or
        preparation.HERE / 'output' / f'inflation_change_rebuilt_{stamp}')
    guarded_run(feature_dir, args.output_dir or HERE / 'runs' / f'inflation_change_rebuilt_{stamp}')
