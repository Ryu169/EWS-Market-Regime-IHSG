"""Bandingkan 13 dan 15 fitur pada data terbaru, tanpa tuning atau evaluasi test.

python train_domestic15.py --feature-dir ../Future-Enginering/output/domestic15_...
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.metadata
import math
from pathlib import Path
import statistics
import sys
import time
from unittest.mock import patch

sys.dont_write_bytecode = True
import train_models as base
import tune_models as tuning

HERE = Path(__file__).resolve().parent
FEATURES15 = [*base.CORE, 'bi_rate_change', 'inflation_yoy']
PARAMETER_RUN = HERE / 'runs/simple_retrain_20261026T201243_195442Z'
TRIAL = 'depth_2_regularized_100'


def common_population(folds):
    """Buang sel kandidat kosong pada kedua pembanding; kalender target tidak diubah."""
    common, excluded = [], []
    for fold in folds:
        result = {'fold': fold['fold']}
        for part in ['train', 'validation']:
            result[part] = []
            for row in fold[part]:
                if all(row[c] != '' and math.isfinite(float(row[c])) for c in FEATURES15):
                    result[part].append(row)
                else:
                    excluded.append({'Fold': fold['fold'], 'Part': part, 'Date': row['Date'],
                                     'Reason': 'missing_domestic_feature_in_both_comparators'})
            if not result[part]:
                raise ValueError('Populasi bersama kosong.')
        common.append(result)
    return common, excluded


def independent_check(actual, predicted, recorded):
    """Hitung ulang metrik dari prediksi dengan implementasi sklearn."""
    from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, recall_score
    assert recorded['confusion_matrix'] == confusion_matrix(actual, predicted, labels=base.CLASSES).tolist()
    assert abs(recorded['accuracy'] - accuracy_score(actual, predicted)) < 1e-12
    assert abs(recorded['macro_f1'] - f1_score(actual, predicted, labels=base.CLASSES,
                                            average='macro', zero_division=0)) < 1e-12
    recalls = recall_score(actual, predicted, labels=base.CLASSES, average=None, zero_division=0)
    assert abs(recorded['recall_bearish'] - recalls[0]) < 1e-12
    for name, recall in zip(base.NAMES, recalls):
        assert abs(recorded['per_class'][name]['recall'] - recall) < 1e-12
    cm = recorded['confusion_matrix']
    fp = cm[1][0] + cm[2][0]
    denominator = sum(cm[1]) + sum(cm[2])
    assert abs(recorded['warning']['false_alarm_rate'] - fp / denominator) < 1e-12


# Fungsi ini dipakai juga oleh train_inflation_change.py. Daftar `features`
# diberikan pemanggil, sehingga versi terbaru memakai Inflation Change (15 X).
def evaluate(model_name, params, folds, features, modules, path):
    # 1. X selalu whitelist fitur; target dan return masa depan hanya untuk evaluasi.
    np, joblib = modules['numpy'], modules['joblib']
    scores, training_scores, predictions = [], [], []
    for fold in folds:
        training, validation = fold['train'], fold['validation']
        # Susun matriks: satu baris = satu tanggal, satu kolom = satu fitur.
        # Urutan fitur identik untuk training, validation, dan dashboard.
        x_train = base.matrix(training, features, np)
        x_val = base.matrix(validation, features, np)
        assert np.isfinite(x_train).all() and np.isfinite(x_val).all()
        actual = [r['y_t'] for r in validation]
        model = tuning.classifier(model_name, params, modules)
        started = time.perf_counter()
        # Hanya X_train dan y_train masuk fit. Model mempelajari hubungan
        # fitur historis dengan kelas pergerakan lima hari berikutnya.
        model.fit(x_train, np.asarray([r['y_t'] for r in training], dtype=int))
        # Prediksi validation tanpa memberi label aktual ke model.
        # Label aktual digunakan sesudah prediksi untuk menghitung metrik.
        probabilities, predicted = base.probabilities(model, x_val, np)
        # Skor training dicatat terpisah untuk melihat potensi overfitting.
        # Angka utama evaluasi tetap validation, bukan skor training ini.
        _, pred_train = base.probabilities(model, x_train, np)
        score = base.metrics(actual, predicted)
        training_score = base.metrics([r['y_t'] for r in training], pred_train)
        independent_check(actual, predicted, score)

        # 2. Simpan dan muat setiap model untuk membuktikan artefak dapat digunakan.
        folder = path / f"fold_{fold['fold']}"
        folder.mkdir(parents=True)
        joblib.dump(model, folder / 'model.joblib')
        restored, restored_pred = base.probabilities(joblib.load(folder / 'model.joblib'), x_val, np)
        assert np.allclose(restored, probabilities, atol=1e-12, rtol=0) and restored_pred == predicted
        base.write_json(folder / 'metrics.json', {**score, 'training_metrics': training_score,
            'train_rows': len(training), 'validation_rows': len(validation),
            'fit_and_verification_seconds': time.perf_counter() - started,
            'parameters': params, 'features': features})
        scores.append(score)
        training_scores.append(training_score)
        predictions.extend({'Fold': fold['fold'], 'Date': r['Date'], 'label_end_date': r['label_end_date'],
            'y_true': r['y_t'], 'y_pred': pred,
            **{f'p_{name.lower()}': float(probs[i]) for i, name in enumerate(base.NAMES)}}
            for r, pred, probs in zip(validation, predicted, probabilities))
        print(f"[{model_name} / {len(features)} fitur] fold {fold['fold']}/5: "
              f"accuracy={score['accuracy']:.4f}, Macro F1={score['macro_f1']:.4f}", flush=True)
    # Ringkas mean/std lima fold dan skor gabungan OOF (889 tanggal unik).
    # Kedua bentuk skor dapat berbeda sedikit karena ukuran fold tidak persis sama.
    result = {'summary': base.summarize(scores), 'training_summary': base.summarize(training_scores),
        'fold_metrics': scores, 'features': features, 'parameters': params,
        'validation_rows': len(predictions),
        'pooled_validation': base.metrics([r['y_true'] for r in predictions], [r['y_pred'] for r in predictions])}
    independent_check([r['y_true'] for r in predictions], [r['y_pred'] for r in predictions], result['pooled_validation'])
    base.write_csv(path / 'validation_predictions.csv', predictions, list(predictions[0]))
    base.write_json(path / 'result.json', result)
    return result


def baselines(folds, thresholds):
    """Majority dan persistence dievaluasi pada tanggal yang persis sama."""
    output = {}
    for strategy in ['majority', 'persistence']:
        scores = []
        for fold in folds:
            majority = max(base.CLASSES, key=lambda code: sum(r['y_t'] == code for r in fold['train']))
            predicted = []
            for row in fold['validation']:
                ret = float(row['ihsg_return_5d'])
                past_regime = 0 if ret < thresholds['T_B'] else 2 if ret > thresholds['T_U'] else 1
                predicted.append(majority if strategy == 'majority' else past_regime)
            actual = [r['y_t'] for r in fold['validation']]
            score = base.metrics(actual, predicted)
            independent_check(actual, predicted, score)
            scores.append(score)
        output[strategy] = {'summary': base.summarize(scores), 'fold_metrics': scores}
    return output


def leaderboard_row(name, variant, result):
    score = result['summary']
    return {'Model': name, 'Variant': variant, 'FeatureCount': len(result.get('features', [])),
        'MeanAccuracy': score['accuracy']['mean'], 'StdAccuracy': score['accuracy']['std'],
        'MeanMacroF1': score['macro_f1']['mean'],
        'MeanRecallBearish': score['recall_bearish']['mean'],
        'MeanRecallBullish': statistics.mean(s['per_class']['Bullish']['recall'] for s in result['fold_metrics']),
        'MeanFalseAlarmRate': statistics.mean(s['warning']['false_alarm_rate'] for s in result['fold_metrics']),
        'ValidationRows': sum(sum(s['support'].values()) for s in result['fold_metrics'])
        if 'support' in result['fold_metrics'][0] else result.get('validation_rows', 889)}


def run(feature_dir, out):
    feature_dir, out = Path(feature_dir).resolve(), Path(out).resolve()
    if out.exists():
        raise ValueError('Folder run sudah ada.')
    # 3. Pembaca baseline hanya mengizinkan fold/development, tidak CSV final test.
    bundle = base.load_bundle({'data_dir': str(feature_dir / 'targets'), 'feature_set': 'core'}, HERE)
    feature_report = base.read_json(feature_dir / 'feature_report.json')
    if base.sha256(Path(feature_report['input_file'])) != feature_report['raw_sha256']:
        raise ValueError('Preprocessing berubah sejak fitur dibentuk.')
    if feature_report['bi_transition_dates'] != ['2016-08-22']:
        raise ValueError('Periksa identitas/tanggal transisi BI.')
    folds, excluded = common_population(bundle['folds'])
    assert all(r['Date'] == '2016-08-22' and r['Part'] == 'train' for r in excluded)
    assert sum(len(f['validation']) for f in folds) == 889
    reference = base.read_json(PARAMETER_RUN / 'summary.json')
    parameters = {name: reference['results'][name][TRIAL]['parameters'] for name in tuning.MODELS}
    protected = {str(p): base.sha256(p) for p in [Path(feature_report['input_file']),
        feature_dir / 'feature_report.json', PARAMETER_RUN / 'summary.json', Path(__file__)]}
    out.mkdir(parents=True)
    base.write_json(out / 'run_status.json', {'status': 'running'})
    protocol = {'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'feature_dir': str(feature_dir), 'source_parameters': str(PARAMETER_RUN),
        'feature_plan': {'core_13': base.CORE, 'domestic_15': FEATURES15},
        'parameters_frozen': parameters, 'thresholds': bundle['thresholds'],
        'folds': [{'fold': f['fold'], 'train_rows': len(f['train']), 'validation_rows': len(f['validation']),
            'train_start': f['train'][0]['Date'], 'train_end': f['train'][-1]['Date'],
            'validation_start': f['validation'][0]['Date'], 'validation_end': f['validation'][-1]['Date']}
            for f in folds], 'excluded_from_both_comparators': excluded,
        'boosting_fold_fits': 20, 'tuning': False, 'early_stopping': False,
        'input_hashes': bundle['input_hashes'], 'protected_hashes': protected,
        'final_test_evaluated': False, 'automatic_dashboard_adoption': False,
        'domestic_required_by_examiner': True,
        'package_versions': {p: importlib.metadata.version(p) for p in ['numpy', 'xgboost', 'lightgbm', 'scikit-learn', 'joblib']}}
    base.write_json(out / 'protocol.json', protocol)
    modules = base.dependencies(tuning.MODELS)
    results, rows = {}, []
    try:
        for name in tuning.MODELS:
            results[name] = {}
            for variant, features in protocol['feature_plan'].items():
                result = evaluate(name, parameters[name], folds, features, modules, out / name / variant)
                results[name][variant] = result
                rows.append(leaderboard_row(name, variant, result))
        controls = baselines(folds, bundle['thresholds'])
        for name, result in controls.items():
            rows.append(leaderboard_row(name, 'baseline', result))
        base.write_csv(out / 'leaderboard.csv', rows, list(rows[0]))
        base.write_json(out / 'summary.json', {'status': 'completed_exploratory_domestic15',
            'results': results, 'baselines': controls, 'features_domestic15': FEATURES15,
            'validation_rows': 889, 'boosting_fold_fits': 20, 'final_test_evaluated': False,
            'model_ready': False, 'limitations': feature_report['limitations']})
        assert all(base.sha256(Path(p)) == h for p, h in protected.items())
        assert all(base.sha256(bundle['root'] / p) == h for p, h in bundle['input_hashes'].items())
        base.write_json(out / 'verification.json', {'status': 'passed',
            'all_metrics_recomputed_with_sklearn': True, 'models_reloaded': 20,
            'validation_model_predictions_checked': 3556, 'same_dates_for_13_and_15': True,
            'input_hashes_unchanged': True, 'final_test_csv_read': False})
        text = ['# Hasil training 15 fitur domestik — 28 Oktober 2026', '',
            'Volume menggunakan koreksi manual 11 November 2016 menjadi 23.814 miliar saham. '
            'Dua fitur domestik adalah perubahan BI-Rate 1D yang mengikuti identitas instrumen as-of '
            'dan inflasi YoY terakhir yang tersedia. Semua fitur memakai informasi hingga tanggal t.', '',
            'Kedua algoritma dilatih ulang pada kontrol 13 dan kandidat 15 fitur. Parameter tetap '
            'depth 2/100 rounds serta regularisasi dari run sumber; 20 fit fold tanpa tuning. '
            'Tanggal 22 Agustus 2016 dikeluarkan dari training kedua pembanding karena selisih BI '
            'lintas instrumen tidak didefinisikan. Kalender pembentukan label tetap lengkap. '
            'Validation tetap 889 tanggal pada lima fold. Target, threshold dan purge tetap.', '',
            '| Model | Fitur | Accuracy validation | Macro F1 | Recall Bearish | Recall Bullish | FAR |',
            '|---|---|---:|---:|---:|---:|---:|']
        for r in rows:
            text.append(f"| {r['Model']} | {r['Variant']} | {r['MeanAccuracy']:.2%} | {r['MeanMacroF1']:.4f} | "
                f"{r['MeanRecallBearish']:.2%} | {r['MeanRecallBullish']:.2%} | {r['MeanFalseAlarmRate']:.2%} |")
        text += ['', 'Angka tabel adalah rata-rata lima fold; hasil gabungan tersedia dalam result.json. '
            'FAR adalah proporsi kondisi non-Bearish yang salah diprediksi Bearish.', '',
            'Kandidat 15 fitur tetap disimpan dan dilaporkan sesuai arahan penguji, terlepas dari '
            'apakah mengungguli kontrol. Perbandingan ini mengisolasi tambahan fitur domestik pada '
            'versi data terbaru; jangan membandingkan skor lama tanpa memperhatikan perbedaan populasi.', '',
            'Final test tidak dibaca atau dievaluasi oleh proses training. Model dashboard tidak diganti. '
            'Status hasil tetap eksplorasi karena cakupan Volume, kalender, dan asumsi waktu tersedia '
            'makro masih memiliki keterbatasan yang sudah dicatat.', '',
            f'Sumber fitur: `{feature_dir}`. Protokol sebelum fit: `protocol.json`. '
            'Daftar skor: `leaderboard.csv`; model setiap fold disimpan pada folder algoritma/varian.']
        (out / 'HASIL_TRAINING_15_FITUR.md').write_text('\n'.join(text) + '\n', encoding='utf-8')
        base.write_json(out / 'run_status.json', {'status': 'completed'})
        print(f'Selesai: {out}', flush=True)
    except BaseException as exc:
        base.write_json(out / 'run_status.json', {'status': 'failed', 'error': str(exc)})
        raise


def guarded_run(feature_dir, out):
    """Cegah akses tidak sengaja ke tabel final test/seluruh target saat training."""
    blocked = {'test.csv', 'eligible_labeled.csv', 'ihsg_features_targets_all.csv'}
    original_open, original_bytes = Path.open, Path.read_bytes
    def safe_open(path, *args, **kwargs):
        if path.name in blocked:
            raise ValueError(f'Akses tabel final/all ditolak: {path}')
        return original_open(path, *args, **kwargs)
    def safe_bytes(path, *args, **kwargs):
        if path.name in blocked:
            raise ValueError(f'Akses tabel final/all ditolak: {path}')
        return original_bytes(path, *args, **kwargs)
    with patch.object(Path, 'open', safe_open), patch.object(Path, 'read_bytes', safe_bytes):
        return run(feature_dir, out)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--feature-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
    guarded_run(args.feature_dir, args.output_dir or HERE / 'runs' / f'domestic15_{stamp}')
