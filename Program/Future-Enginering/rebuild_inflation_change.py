"""Hitung ulang langsung dari preprocessing: 13 inti + BI Change + Inflation Change.

python rebuild_inflation_change.py
Tidak membaca CSV fitur sebelumnya untuk menghitung nilai fitur baru.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys

sys.dont_write_bytecode = True
import feature_engineering as fe
import build_targets as target
import prepare_domestic15 as domestic
import prepare_inflation_release as inflation

HERE = Path(__file__).resolve().parent
FEATURES = [*fe.CORE, 'bi_rate_change', inflation.CHANGE]


def save_targets(rows, combined_columns, feature_file, out):
    """Bangun label pada kalender penuh sebelum menyaring fitur untuk training."""
    result = target.prepare(rows)
    fields = [*combined_columns, *target.EXTRA_COLUMNS]
    artifacts = {}
    def save(name, records, columns=fields):
        path = out / name
        path.parent.mkdir(parents=True, exist_ok=True)
        fe.write_csv(path, [{key: r.get(key) for key in columns} for r in records], columns)
        artifacts[name] = {'rows': len(records), 'sha256': fe.fingerprint(path)}
    save('ihsg_features_targets_all.csv', result['calendar'])
    save('eligible_labeled.csv', result['eligible'])
    for name in ['train', 'validation', 'test', 'development_train']:
        save(f'splits/{name}.csv', result[name])
    save('purge_audit.csv', result['purge_audit'],
         ['Context', 'Date', 'label_end_date', 'EvaluationStart', 'Reason'])
    folds = []
    for fold in result['folds']:
        number = fold['fold']
        tr, va = f'folds/fold_{number}_train.csv', f'folds/fold_{number}_validation.csv'
        save(tr, fold['train'])
        save(va, fold['validation'])
        folds.append({'fold': number, 'train_file': tr, 'validation_file': va,
                      'train': target.describe(fold['train']),
                      'validation': target.describe(fold['validation'])})
    contract = {'class_order': [0, 1, 2], 'class_names': target.LABELS,
        'target_column': 'y_t', 'horizon_trading_days': 5,
        'feature_sets': {'core': fe.CORE, 'inflation_change_15': FEATURES},
        'forbidden_input_columns': [c for c in fields if c not in FEATURES],
        'complete_training_features': FEATURES, 'model_ready': False}
    metadata = {'input_file': str(feature_file), 'input_sha256': fe.fingerprint(feature_file),
        'calibration': result['calibration'], 'purge_horizon_trading_days': 5,
        'calendar_rows': len(rows), 'eligible_rows': len(result['eligible']),
        'validation_folds': folds, 'splits_after_purge': {name: target.describe(result[name])
            for name in ['train', 'validation', 'test', 'development_train']},
        'artifacts': artifacts, 'model_ready': False,
        'complete_rows_selected_only_after_target_creation': True}
    domestic.write_json(out / 'model_contract.json', contract)
    domestic.write_json(out / 'thresholds.json', result['calibration'])
    domestic.write_json(out / 'split_metadata.json', metadata)
    return metadata


def run(out):
    # 1. Baca preprocessing yang diminta, dan validasi perubahan Volume manual.
    out = Path(out).resolve()
    if out.exists():
        raise ValueError('Folder output sudah ada; gunakan folder baru.')
    protected = [domestic.SOURCE, fe.DEFAULT_SOURCE_REPORT, domestic.BI_AUDIT,
                 inflation.AVAILABILITY, Path(__file__), Path(fe.__file__), Path(target.__file__)]
    hashes = {str(p): fe.fingerprint(p) for p in protected}
    upstream = json.loads(fe.DEFAULT_SOURCE_REPORT.read_text())
    # File lama hanya pembanding otorisasi edit; nilai fitur dihitung ulang dari raw.
    raw = fe.read(domestic.SOURCE)
    edits = domestic.source_changes(raw, fe.read(domestic.PREVIOUS))
    out.mkdir(parents=True)
    snapshot = {**upstream, 'output_sha256': hashes[str(domestic.SOURCE)],
                'authorized_manual_changes': edits}
    domestic.write_json(out / 'source_report_snapshot.json', snapshot)
    raw, rows, _ = fe.load_preprocessing(domestic.SOURCE, out / 'source_report_snapshot.json')

    # 2. Seluruh 13 fitur inti dan BI Change dihitung dari nilai preprocessing.
    regimes = domestic.load_bi_regimes(rows, domestic.BI_AUDIT)
    calculated = domestic.corrected_domestic(rows, fe.calculate(rows), regimes)
    change, release_audit = inflation.build_change(raw, fe.read(inflation.AVAILABILITY))
    features = [{'Date': r['Date'], **{key: r[key] for key in fe.CORE},
                 'bi_rate_change': r['bi_rate_change'], inflation.CHANGE: change[r['Date']]}
                for r in calculated]
    complete = [r for r in features if all(r[c] is not None and math.isfinite(float(r[c]))
                                         for c in FEATURES)]
    dates_complete = {r['Date'] for r in complete}
    combined_columns = [*fe.SOURCE_COLUMNS, *FEATURES]
    combined = [{**r, **{c: f[c] for c in FEATURES}} for r, f in zip(raw, features)]
    assert all({c: r[c] for c in fe.SOURCE_COLUMNS} == original for r, original in zip(combined, raw))
    assert 'inflation_yoy' not in features[0] and len(features[0]) == 16
    outputs = [
        ('features_all.csv', features, ['Date', *FEATURES]),
        ('features_complete.csv', complete, ['Date', *FEATURES]),
        ('ihsg_preprocessing_features_all.csv', combined, combined_columns),
        ('ihsg_preprocessing_features_complete.csv',
         [r for r in combined if r['Date'] in dates_complete], combined_columns),
        ('inflation_release_audit.csv', release_audit, list(release_audit[0])),
    ]
    for name, records, fields in outputs:
        fe.write_csv(out / name, records, fields)

    # 3. Label dibentuk dari Close pada kalender penuh. Kolom YoY mentah hanya audit.
    numeric = [{key: value if key == 'Date' else None if value in ('', None) else float(value)
                for key, value in r.items()} for r in combined]
    metadata = save_targets(numeric, combined_columns, out / 'ihsg_preprocessing_features_all.csv', out / 'targets')
    prior = json.loads((domestic.HERE / 'output/domestic15_20261028_volume1111/targets/split_metadata.json').read_text())
    assert metadata['calibration'] == prior['calibration']
    assert metadata['splits_after_purge'] == prior['splits_after_purge']
    report = {'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'input_file': str(domestic.SOURCE), 'raw_sha256': hashes[str(domestic.SOURCE)],
        'calculated_directly_from_preprocessing': True, 'features': FEATURES,
        'inflation_yoy_used_as_model_feature': False,
        'inflation_change_formula': 'latest_announced_yoy - previous_announced_month_yoy',
        'inflation_change_unit': 'percentage_points', 'calendar_rows': len(rows),
        'complete_feature_rows': len(complete), 'missing_feature_rows': len(rows) - len(complete),
        'authorized_source_changes': edits, 'target_thresholds_and_dates_unchanged': True,
        'outputs': {name: fe.fingerprint(out / name) for name, _, _ in outputs},
        'protected_hashes': hashes, 'source_columns_preserved_exactly': True, 'model_ready': False,
        'limitations': ['Volume tahap 27 digunakan sementara atas instruksi pengguna.',
                       'Asumsi kalender dan waktu tersedia makro tetap mengikuti preprocessing.']}
    domestic.write_json(out / 'feature_report.json', report)
    assert all(fe.fingerprint(Path(p)) == h for p, h in hashes.items())
    print(f'Feature engineering ulang selesai: {out}', flush=True)
    print(f'{len(rows)} tanggal; {len(complete)} baris complete; 15 fitur termasuk Inflation Change.', flush=True)
    return out


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
    run(args.output_dir or HERE / 'output' / f'inflation_change_rebuilt_{stamp}')
