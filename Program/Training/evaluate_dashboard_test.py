"""Evaluasi final test memakai dua model dashboard yang sudah dibekukan.

Jalankan: python evaluate_dashboard_test.py
Tidak ada fit, tuning, pemilihan fitur, atau perubahan threshold pada skrip ini.
Hasil tersimpan terpisah dari evaluasi validation dan paket model asal.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

import train_models as base
from train_domestic15 import independent_check

HERE = Path(__file__).resolve().parent
PACKAGE = HERE / 'runs/inflation_change_rebuilt_20261028/dashboard_models'
OUTPUT = PACKAGE.parent / 'dashboard_final_test_20261028'


def read_csv(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle))


def model_id(model_sha, metadata_sha):
    return hashlib.sha256(json.dumps([model_sha, metadata_sha], sort_keys=True).encode()).hexdigest()


def evaluate():
    # 1. Tentukan versi data, model, 15 fitur X, dan threshold SEBELUM membuka test.
    # Data berasal dari preprocessing tahap 27, lalu feature engineering terbaru.
    # Model joblib adalah hasil refit development 2008–2022, bukan model baru.
    if OUTPUT.exists():
        raise ValueError('Evaluasi sudah tersimpan. Jangan menimpa hasil final test.')
    summary = base.read_json(PACKAGE / 'summary.json')
    feature_file = Path(summary['feature_file'])
    root = feature_file.parent / 'targets'
    metadata = base.read_json(root / 'split_metadata.json')
    features = summary['features']
    assert features == [*base.CORE, 'bi_rate_change', 'inflation_change_release']
    assert base.sha256(feature_file) == metadata['input_sha256']
    assert base.sha256(root / 'split_metadata.json') == summary['input_hashes']['split_metadata.json']
    modules = base.dependencies(['xgboost', 'lightgbm'])
    models, frozen = {}, {}
    development = read_csv(summary['training_file'])
    assert base.sha256(summary['training_file']) == summary['training_file_sha256']
    test_start = metadata['splits_after_purge']['test']['start_date']
    assert max(r['label_end_date'] for r in development) < test_start
    for name in ['xgboost', 'lightgbm']:
        folder = PACKAGE / 'selected_models' / name / 'development_model'
        recorded = summary['model_artifacts'][name]
        actual = {'model_sha256': base.sha256(folder / 'model.joblib'),
                  'metadata_sha256': base.sha256(folder / 'model_metadata.json')}
        assert actual == recorded
        model_metadata = base.read_json(folder / 'model_metadata.json')
        assert model_metadata['features'] == features
        assert model_metadata['thresholds'] == metadata['calibration']
        models[name] = modules['joblib'].load(folder / 'model.joblib')
        frozen[name] = {**actual, 'model_id': model_id(**{'model_sha': actual['model_sha256'],
                                                       'metadata_sha': actual['metadata_sha256']})}

    # 2. Baru sekarang buka data test. y_t adalah kelas return lima hari ke depan.
    # Date, harga mentah, future_return_5d, dan y_t tidak masuk matriks fitur X.
    # Kalender tidak dipotong sebelum menghitung target, sehingga horizon tetap 5 hari.
    test_path = root / 'splits/test.csv'
    expected = metadata['artifacts']['splits/test.csv']
    assert base.sha256(test_path) == expected['sha256']
    test = read_csv(test_path)
    assert len(test) == expected['rows'] == 895
    calendar = read_csv(feature_file)
    positions = {r['Date']: i for i, r in enumerate(calendar)}
    thresholds = metadata['calibration']
    for row in test:
        index = positions[row['Date']]
        assert calendar[index + 5]['Date'] == row['label_end_date']
        assert all(math.isfinite(float(row[c])) and row[c] == calendar[index][c] for c in features)
        future_return = float(calendar[index + 5]['Close']) / float(calendar[index]['Close']) - 1
        label = 0 if future_return < thresholds['T_B'] else 2 if future_return > thresholds['T_U'] else 1
        assert int(row['y_t']) == label
    assert test[0]['Date'] == test_start

    # 3. predict_proba menggunakan model tetap. Label aktual hanya dipakai SESUDAH
    # prediksi untuk menghitung accuracy, Macro F1, recall, dan false alarm rate.
    x_test = base.matrix(test, features, modules['numpy'])
    actual = [int(r['y_t']) for r in test]
    results, predictions = {}, {}
    for name, model in models.items():
        probability, predicted = base.probabilities(model, x_test, modules['numpy'])
        results[name] = base.metrics(actual, predicted)
        independent_check(actual, predicted, results[name])
        predictions[name] = [{'Date': row['Date'], 'label_end_date': row['label_end_date'],
            'y_true': truth, 'y_pred': estimate,
            **{f'p_{label.lower()}': float(probs[i]) for i, label in enumerate(base.NAMES)}}
            for row, truth, estimate, probs in zip(test, actual, predicted, probability)]

    # 4. Simpan hasil satu kali dalam folder baru; validation dan model asal tetap utuh.
    OUTPUT.mkdir()
    files = {}
    for name, records in predictions.items():
        base.write_csv(OUTPUT / f'{name}_test_predictions.csv', records, list(records[0]))
        files[name] = base.sha256(OUTPUT / f'{name}_test_predictions.csv')
        folder = PACKAGE / 'selected_models' / name / 'development_model'
        assert base.sha256(folder / 'model.joblib') == frozen[name]['model_sha256']
        print(f"{name}: test={len(test)} baris, accuracy={results[name]['accuracy']:.2%}, "
              f"Macro F1={results[name]['macro_f1']:.4f}", flush=True)
    base.write_json(OUTPUT / 'summary.json', {'status': 'completed_frozen_model_test',
        'evaluated_at_utc': datetime.now(timezone.utc).isoformat(), 'model_package': str(PACKAGE),
        'features': features, 'feature_sha256': metadata['input_sha256'],
        'split_metadata_sha256': base.sha256(root / 'split_metadata.json'),
        'test_file': str(test_path), 'test_sha256': expected['sha256'], 'rows': len(test),
        'start_date': test[0]['Date'], 'end_date': test[-1]['Date'],
        'models': frozen, 'prediction_sha256': files, 'results': results,
        'fit_count': 0, 'final_test_evaluated': True,
        'reference_selection': 'Tetap berdasarkan validation; skor test tidak memilih model.',
        'limitations': summary['limitations']})
    print(f'Hasil final test: {OUTPUT}', flush=True)


if __name__ == '__main__':
    evaluate()
