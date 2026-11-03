"""Refit dua model Inflation Change pada development lengkap untuk dashboard.

python prepare_dashboard_models.py
Skor dashboard tetap validation OOF; tidak menilai model refit pada data latih.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import shutil
import sys
from unittest.mock import patch

sys.dont_write_bytecode = True
import train_models as base
import tune_models as tuning

HERE = Path(__file__).resolve().parent
RUN = HERE / 'runs/inflation_change_rebuilt_20261028'


def prepare():
    # 1. Ambil parameter, urutan 15 fitur, dan evaluasi validation dari run
    # terbaru. Tidak mengubah skor fold yang sudah dihasilkan.
    summary = base.read_json(RUN / 'summary.json')
    protocol = base.read_json(RUN / 'protocol.json')
    if base.read_json(RUN / 'run_status.json')['status'] != 'completed':
        raise ValueError('Training sumber belum selesai.')
    feature_dir = Path(protocol['feature_dir'])
    features = protocol['features']
    if features != [*base.CORE, 'bi_rate_change', 'inflation_change_release']:
        raise ValueError('Kontrak 15 fitur Inflation Change tidak cocok.')
    # 2. Baca development_train.csv hasil split kronologis, termasuk validation
    # untuk refit SETELAH pemilihan parameter selesai. Final test tidak ikut.
    bundle = base.load_bundle({'data_dir': str(feature_dir / 'targets'), 'feature_set': 'core'}, HERE)
    if bundle['input_hashes'] != protocol['target_hashes']:
        raise ValueError('Data sumber berubah sejak evaluasi.')
    # 3. Pilih 3.570 baris development dengan seluruh fitur lengkap.
    # Tanggal transisi BI 22 Agustus 2016 dikeluarkan; kalender label tetap asli.
    development = [r for r in bundle['development'] if all(r[c] != '' for c in features)]
    if len(development) != 3570:
        raise ValueError('Populasi development complete tidak cocok.')
    out = RUN / 'dashboard_models'
    if out.exists():
        raise ValueError('Paket dashboard sudah ada; jangan menimpa model yang aktif.')
    out.mkdir()
    base.write_csv(out / 'development_complete.csv', development, list(development[0]))
    development_sha = base.sha256(out / 'development_complete.csv')
    modules = base.dependencies(tuning.MODELS)
    np, joblib = modules['numpy'], modules['joblib']
    # 4. X berisi 15 fitur; y terpisah berisi label y_t. Harga mentah, tanggal,
    # dan future return tidak menjadi input model, meski ada dalam CSV audit.
    x = base.matrix(development, features, np)
    y = np.asarray([r['y_t'] for r in development], dtype=int)
    assert np.isfinite(x).all()
    saved = {}
    for name in tuning.MODELS:
        params = protocol['parameters'][name]
        model = tuning.classifier(name, params, modules)
        # 5. Refit model untuk inferensi dashboard pada seluruh development
        # complete. Ini bukan evaluasi baru pada data latih.
        model.fit(x, y)
        path = out / 'selected_models' / name / 'development_model'
        path.mkdir(parents=True)
        # 6. Simpan joblib dan buktikan bahwa model yang dimuat ulang memberi
        # probabilitas sama. Metadata menyimpan fitur, parameter, dan checksum.
        joblib.dump(model, path / 'model.joblib')
        restored = joblib.load(path / 'model.joblib')
        original, _ = base.probabilities(model, x[-20:], np)
        replay, _ = base.probabilities(restored, x[-20:], np)
        assert np.allclose(original, replay, atol=1e-12, rtol=0)
        meta = {'features': features, 'classes': [0, 1, 2], 'parameters': params,
            'thresholds': bundle['thresholds'], 'input_hashes': bundle['input_hashes'],
            'training_rows': len(development), 'training_start': development[0]['Date'],
            'training_end': development[-1]['Date'], 'training_file': str(out / 'development_complete.csv'),
            'training_file_sha256': development_sha, 'refit_scope': 'complete_development_only',
            'evaluation_source': str(RUN / name / 'inflation_change_15'),
            'final_test_evaluated': False, 'model_ready': False}
        base.write_json(path / 'model_metadata.json', meta)
        base.write_json(path / 'feature_columns.json', features)
        validation_dir = out / 'validation' / name
        validation_dir.mkdir(parents=True)
        shutil.copy2(RUN / name / 'inflation_change_15/validation_predictions.csv',
                     validation_dir / 'validation_predictions.csv')
        saved[name] = {'model_sha256': base.sha256(path / 'model.joblib'),
                       'metadata_sha256': base.sha256(path / 'model_metadata.json')}
        print(f'{name}: refit {len(development)} baris, 15 fitur; artefak diverifikasi.', flush=True)
    feature_report = base.read_json(feature_dir / 'feature_report.json')
    # 7. Paket dashboard menyertakan hasil validation OOF asli, terpisah
    # dari prediksi model development. Final test memiliki folder evaluasi sendiri.
    base.write_json(out / 'summary.json', {'status': 'completed_exploratory_dashboard_package',
        'created_at_utc': datetime.now(timezone.utc).isoformat(), 'features': features,
        'feature_file': str(feature_dir / 'ihsg_preprocessing_features_all.csv'),
        'input_hashes': bundle['input_hashes'], 'results': summary['results'],
        'training_file': str(out / 'development_complete.csv'), 'training_file_sha256': development_sha,
        'evaluation_source_run': str(RUN), 'limitations': feature_report['limitations'],
        'model_artifacts': saved, 'final_test_evaluated': False})
    base.write_json(out / 'protocol.json', {'features': features,
        'feature_dir': str(feature_dir), 'parameters': protocol['parameters'],
        'training_rows': len(development), 'input_hashes': bundle['input_hashes'],
        'evaluation_policy': 'Display saved validation OOF metrics; never display refit training accuracy.',
        'final_test_evaluated': False})
    assert all(base.sha256(bundle['root'] / p) == h for p, h in bundle['input_hashes'].items())
    base.write_json(out / 'verification.json', {'status': 'passed', 'models_refitted_and_reloaded': 2,
        'training_rows': len(development), 'features': 15, 'final_test_csv_read': False})
    print(f'Paket dashboard: {out}', flush=True)


if __name__ == '__main__':
    blocked = {'test.csv', 'eligible_labeled.csv', 'ihsg_features_targets_all.csv'}
    original_open, original_bytes = Path.open, Path.read_bytes
    def safe_open(p, *a, **kw):
        if p.name in blocked:
            raise ValueError('Final test tidak boleh dibuka untuk refit dashboard.')
        return original_open(p, *a, **kw)
    def safe_bytes(p, *a, **kw):
        if p.name in blocked:
            raise ValueError('Final test tidak boleh dibuka untuk refit dashboard.')
        return original_bytes(p, *a, **kw)
    with patch.object(Path, 'open', safe_open), patch.object(Path, 'read_bytes', safe_bytes):
        prepare()
