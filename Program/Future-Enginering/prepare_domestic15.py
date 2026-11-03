"""Bangun fitur 15 variabel dari koreksi manual Volume tahap 27.

python prepare_domestic15.py
Output selalu folder baru; sumber preprocessing dan output lama tetap tersimpan.
"""
from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timezone
import json
import math
from pathlib import Path
import sys

sys.dont_write_bytecode = True
import feature_engineering as fe
import build_targets as targets

HERE = Path(__file__).resolve().parent
SOURCE = fe.DEFAULT_SOURCE
PREVIOUS = HERE / 'output/ihsg_preprocessing_features_all.csv'
BI_AUDIT = HERE.parent / 'Pre-Processing/reports/10_bi_rate_history/bi_rate_daily_audit.csv'
FEATURES = [*fe.CORE, 'bi_rate_change', 'inflation_yoy']
ALLOWED_CHANGE = {'Date': '2016-11-11', 'Field': 'Volume',
                  'Before': '978.82025', 'After': '23.814'}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def source_changes(current, previous):
    """Rekonsiliasi edit manual tanpa menganggap semua perubahan sudah disetujui."""
    if [r['Date'] for r in current] != [r['Date'] for r in previous]:
        raise ValueError('Kalender berbeda dari fitur sebelumnya; periksa perubahan dahulu.')
    changes = [{'Date': new['Date'], 'Field': key, 'Before': old[key], 'After': new[key]}
               for old, new in zip(previous, current) for key in fe.SOURCE_COLUMNS
               if old[key] != new[key]]
    if changes != [ALLOWED_CHANGE]:
        raise ValueError(f'Perubahan input di luar koreksi Volume yang disetujui: {changes[:5]}')
    return changes


def load_bi_regimes(rows, audit_path):
    """Gunakan identitas instrumen yang benar-benar berlaku pada kalender as-of."""
    audit = fe.read(Path(audit_path))
    mapping = {r['Date']: r for r in audit}
    if len(mapping) != len(audit):
        raise ValueError('Tanggal audit BI duplikat.')
    result = {}
    for row in rows:
        item = mapping.get(row['Date'])
        if not item or not item['UnderlyingRegime']:
            raise ValueError(f"Identitas instrumen BI tidak tersedia: {row['Date']}")
        if not math.isclose(float(item['BI_Rate']), row['BI_Rate'], abs_tol=1e-12, rel_tol=0):
            raise ValueError(f"Nilai BI berbeda dari audit: {row['Date']}")
        if item['AvailableFrom'] > row['Date']:
            raise ValueError('Observasi BI digunakan sebelum tersedia.')
        result[row['Date']] = item['UnderlyingRegime']
    return result


def corrected_domestic(rows, features, regimes):
    """Selisih lintas instrumen tetap kosong; inflasi mewarisi jadwal rilis input."""
    output = []
    for i, (row, feature) in enumerate(zip(rows, features)):
        change = None
        if i and regimes[row['Date']] == regimes[rows[i - 1]['Date']]:
            change = row['BI_Rate'] - rows[i - 1]['BI_Rate']
        output.append({**feature, 'bi_rate_change': change, 'inflation_yoy': row['Inflation_YoY']})
    return output


def run(out):
    # 1. Validasi edit yang diminta, dan simpan laporan sumber versi ini secara terpisah.
    out = Path(out).resolve()
    if out.exists():
        raise ValueError('Gunakan folder output baru.')
    protected = [SOURCE, PREVIOUS, fe.DEFAULT_SOURCE_REPORT, BI_AUDIT,
                 Path(fe.__file__), Path(targets.__file__), Path(__file__)]
    hashes = {str(p): fe.fingerprint(p) for p in protected}
    raw = fe.read(SOURCE)
    changes = source_changes(raw, fe.read(PREVIOUS))
    previous_report = json.loads(fe.DEFAULT_SOURCE_REPORT.read_text(encoding='utf-8'))
    out.mkdir(parents=True)
    source_report = {**previous_report, 'output_sha256': hashes[str(SOURCE)],
                     'manual_revision': {'changes': changes,
                         'authorization': 'Pengguna meminta memakai tahap 27 setelah koreksi Volume 11 November 2016.',
                         'previous_report_sha256': hashes[str(fe.DEFAULT_SOURCE_REPORT)]}}
    write_json(out / 'source_report_snapshot.json', source_report)
    raw, rows, upstream = fe.load_preprocessing(SOURCE, out / 'source_report_snapshot.json')
    regimes = load_bi_regimes(rows, BI_AUDIT)

    # 2. Seluruh jendela dihitung pada kalender penuh, sebelum memilih baris lengkap.
    features = corrected_domestic(rows, fe.calculate(rows), regimes)
    combined = fe.combine_by_date(raw, features)
    core_complete = [r for r in features if all(r[c] is not None for c in fe.CORE)]
    complete_15 = [r for r in features if all(r[c] is not None for c in FEATURES)]
    core_dates = {r['Date'] for r in core_complete}
    complete_dates = {r['Date'] for r in complete_15}
    assert [r['Date'] for r in raw] == [r['Date'] for r in combined]
    assert all(all(a[c] == b[c] for c in fe.SOURCE_COLUMNS) for a, b in zip(raw, combined))
    missing = fe.missing_details(rows, features)
    transitions = []
    for i, r in enumerate(rows):
        if i and regimes[r['Date']] != regimes[rows[i - 1]['Date']]:
            transitions.append(r['Date'])
    for item in missing:
        if item['Feature'] == 'bi_rate_change' and item['Date'] in transitions:
            item['Reason'] = 'policy_instrument_transition_asof_source'
    outputs = [
        ('features_all.csv', features, ['Date', *FEATURES]),
        ('features_core_complete.csv', core_complete, ['Date', *FEATURES]),
        ('features_domestic15_complete.csv', complete_15, ['Date', *FEATURES]),
        ('ihsg_preprocessing_features_all.csv', combined, [*fe.SOURCE_COLUMNS, *FEATURES]),
        ('ihsg_preprocessing_features_core_complete.csv',
         [r for r in combined if r['Date'] in core_dates], [*fe.SOURCE_COLUMNS, *FEATURES]),
        ('ihsg_preprocessing_features_domestic15_complete.csv',
         [r for r in combined if r['Date'] in complete_dates], [*fe.SOURCE_COLUMNS, *FEATURES]),
        ('feature_missing_details.csv', missing, ['Date', 'Feature', 'Reason']),
    ]
    for name, records, columns in outputs:
        fe.write_csv(out / name, records, columns)
    report = {'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'status': 'exploratory_domestic15_from_authorized_manual_volume_revision',
        'input_file': str(SOURCE), 'raw_sha256': hashes[str(SOURCE)],
        'source_report': str(out / 'source_report_snapshot.json'),
        'source_report_sha256': fe.fingerprint(out / 'source_report_snapshot.json'),
        'input_rows': len(rows), 'calendar_rows': len(rows), 'core_complete_rows': len(core_complete),
        'domestic15_complete_rows': len(complete_15), 'features_core': fe.CORE,
        'features_candidates': FEATURES[-2:], 'features_requested_for_training': FEATURES,
        'source_values_preserved_exactly': True, 'authorized_source_changes': changes,
        'bi_regime_audit': str(BI_AUDIT), 'bi_transition_dates': transitions,
        'bi_change_policy': 'Difference only between consecutive observations of the same as-of UnderlyingRegime.',
        'bi_instrument_transition_is_not_rate_cut': True,
        'missing_by_feature': {c: sum(r[c] is None for r in features) for c in FEATURES},
        'preprocessing_approved_for_feature_engineering': False, 'model_ready': False,
        'limitations': ['Volume masih mencampur cakupan/proxy; digunakan sementara atas instruksi pengguna.',
                       'Kalender dan asumsi waktu tersedia makro mengikuti preprocessing tahap 27.',
                       'Sel BI saat instrumen berganti tidak diisi nol; perbandingan model memakai populasi bersama.'],
        'outputs': {name: fe.fingerprint(out / name) for name, _, _ in outputs}}
    write_json(out / 'feature_report.json', report)

    # 3. Target dihitung dari kalender penuh; hanya input fitur yang berubah.
    metadata = targets.main(out / 'ihsg_preprocessing_features_all.csv', out / 'targets')
    old_meta = json.loads((HERE / 'output/targets/split_metadata.json').read_text())
    for key in ['calibration', 'splits_after_purge', 'validation_folds']:
        if metadata[key] != old_meta[key]:
            raise ValueError(f'Target/split berubah tanpa diminta: {key}')
    if not all(fe.fingerprint(Path(p)) == h for p, h in hashes.items()):
        raise ValueError('Sumber berubah selama proses.')
    write_json(out / 'verification.json', {'status': 'passed', 'input_files_unchanged': True,
        'source_columns_preserved': True, 'same_thresholds_and_split_dates': True,
        'calendar_rows': len(rows), 'protected_hashes': hashes,
        'training_not_started_by_this_script': True})
    (out / 'FITUR_TERBARU.md').write_text(
        '# Fitur terbaru: koreksi Volume dan dua fitur domestik\n\n'
        f'Sumber: `{SOURCE}`. Semua {len(rows)} tanggal dipertahankan. '
        f'{len(core_complete)} baris lengkap untuk 13 fitur inti; {len(complete_15)} lengkap untuk 15 fitur.\n\n'
        'Volume 11 November 2016 memakai 23.814 miliar saham. Volume Change berubah pada '
        '11 dan 14 November 2016. Selisih BI pada 19 Agustus 2016 menjadi 0; '
        '22 Agustus 2016 kosong karena pergantian instrumen, bukan pemotongan bunga.\n\n'
        'Gunakan kalender penuh untuk membentuk target. Subset lengkap hanya tampilan. '
        'Target tetap lima hari; threshold, tanggal split, dan purge sama dengan eksperimen sebelumnya. '
        'Status tetap eksplorasi sesuai instruksi penggunaan sementara Volume.\n', encoding='utf-8')
    print(f'Fitur terbaru: {out}', flush=True)
    return out


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
    run(args.output_dir or HERE / 'output' / f'domestic15_{stamp}')
