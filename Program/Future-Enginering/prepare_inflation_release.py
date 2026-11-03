"""Tambahkan perubahan inflasi antarrilis dari fitur terbaru yang sudah diperbaiki.

Fitur dihitung pada kalender penuh; tabel complete disimpan setelah perhitungan.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import json
import math
from pathlib import Path
import sys

sys.dont_write_bytecode = True
import feature_engineering as fe
from prepare_domestic15 import FEATURES as FEATURES15, write_json

HERE = Path(__file__).resolve().parent
DEFAULT_FEATURE_DIR = HERE / 'output/domestic15_20261028_volume1111'
AVAILABILITY = HERE.parent / 'Pre-Processing/reports/06_dataset_candidate/availability_audit.csv'
CHANGE = 'inflation_change_release'
COMPLETE_FEATURES = [*FEATURES15, CHANGE]


def build_change(rows, availability_rows):
    """Identifikasi rilis dari ReferenceMonth; rilis bernilai sama tetap dikenali."""
    daily, monthly = {}, {}
    for record in availability_rows:
        if record['Variable'] != 'Inflation_YoY':
            continue
        day, reference = record['Date'], record['ReferenceMonth']
        if day in daily:
            raise ValueError('Audit inflasi memiliki tanggal duplikat.')
        if record['Status'] != 'available' or not reference:
            raise ValueError(f'Audit rilis inflasi belum lengkap pada {day}.')
        value = float(record['Value'])
        available = datetime.fromisoformat(record['AvailableAtWIB'])
        if not math.isfinite(value) or available.tzinfo is None:
            raise ValueError('Nilai/timestamp rilis tidak valid.')
        event = {'reference': reference, 'value': value, 'available': available}
        if reference in monthly and monthly[reference] != event:
            raise ValueError('Satu bulan referensi memiliki nilai atau tanggal tersedia berbeda.')
        monthly[reference] = event
        daily[day] = event

    # Jendela mengikuti urutan bulan rilis, bukan selisih dua baris harian.
    events = sorted(monthly.values(), key=lambda e: e['reference'])
    previous = {}
    for i, event in enumerate(events):
        old = events[i - 1] if i else None
        if old:
            y, m = map(int, old['reference'].split('-'))
            expected = f'{y + (m == 12):04d}-{m % 12 + 1:02d}'
            if event['reference'] != expected or old['available'] >= event['available']:
                raise ValueError('Urutan bulan atau jadwal rilis inflasi tidak berurutan.')
        previous[event['reference']] = old
    changes, audit = {}, []
    for row in rows:
        day = row['Date']
        if day not in daily:
            raise ValueError(f'Tanggal tidak ada pada audit rilis inflasi: {day}')
        event = daily[day]
        if event['available'].date() > date.fromisoformat(day):
            raise ValueError('Inflasi dipakai sebelum tersedia.')
        if not math.isclose(float(row['Inflation_YoY']), event['value'], abs_tol=1e-12, rel_tol=0):
            raise ValueError(f'Nilai inflasi preprocessing berbeda dari audit rilis pada {day}.')
        old = previous[event['reference']]
        change = event['value'] - old['value'] if old else None
        changes[day] = change
        audit.append({'Date': day, 'ReferenceMonth': event['reference'],
            'AvailableAtWIB': event['available'].isoformat(), 'InflationYoY': event['value'],
            'PreviousReferenceMonth': old['reference'] if old else '',
            'PreviousInflationYoY': old['value'] if old else None,
            CHANGE: change, 'Unit': 'percentage_points',
            'Reason': 'previous_announced_month_not_available' if old is None else 'available'})
    return changes, audit


def prepare(feature_dir, out):
    # 1. Pastikan file fitur mengacu ke preprocessing terbaru yang diminta pengguna.
    feature_dir, out = Path(feature_dir).resolve(), Path(out).resolve()
    if out.exists():
        raise ValueError('Gunakan folder output baru.')
    report = json.loads((feature_dir / 'feature_report.json').read_text())
    source = Path(report['input_file'])
    if fe.fingerprint(source) != report['raw_sha256']:
        raise ValueError('Preprocessing berubah; bangun ulang fitur domestik terlebih dahulu.')
    files = [source, feature_dir / 'feature_report.json',
             feature_dir / 'ihsg_preprocessing_features_all.csv', AVAILABILITY, Path(__file__)]
    hashes = {str(p): fe.fingerprint(p) for p in files}
    combined = fe.read(feature_dir / 'ihsg_preprocessing_features_all.csv')
    if hashes[str(feature_dir / 'ihsg_preprocessing_features_all.csv')] != report['outputs']['ihsg_preprocessing_features_all.csv']:
        raise ValueError('Checksum fitur berbeda dari laporan.')

    # 2. Hitung change dengan identitas rilis; kemudian pilih baris lengkap bersama.
    changes, audit = build_change(combined, fe.read(AVAILABILITY))
    expanded = [{**r, CHANGE: changes[r['Date']]} for r in combined]
    complete = [r for r in expanded if all(r[c] not in (None, '') and math.isfinite(float(r[c]))
                                         for c in COMPLETE_FEATURES)]
    out.mkdir(parents=True)
    fields = [*combined[0], CHANGE]
    feature_rows = [{c: r[c] for c in ['Date', *COMPLETE_FEATURES]} for r in expanded]
    complete_dates = {r['Date'] for r in complete}
    outputs = [
        ('ihsg_preprocessing_features_all.csv', expanded, fields),
        ('ihsg_preprocessing_features_complete.csv', complete, fields),
        ('features_all.csv', feature_rows, ['Date', *COMPLETE_FEATURES]),
        ('features_complete.csv', [r for r in feature_rows if r['Date'] in complete_dates],
         ['Date', *COMPLETE_FEATURES]),
        ('inflation_release_audit.csv', audit, list(audit[0])),
    ]
    for name, values, columns in outputs:
        fe.write_csv(out / name, values, columns)
    result = {'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'source_feature_dir': str(feature_dir), 'preprocessing_file': str(source),
        'preprocessing_sha256': report['raw_sha256'], 'protected_hashes': hashes,
        'formula': 'latest_announced_yoy - previous_announced_month_yoy',
        'unit': 'percentage_points', 'calendar_rows': len(expanded),
        'complete_rows': len(complete), 'complete_features': COMPLETE_FEATURES,
        'release_policy': 'Reuse verified release dates and conservative next-calendar-day availability from preprocessing.',
        'feature_plan': {
            'yoy_15': FEATURES15,
            'change_15': [*fe.CORE, 'bi_rate_change', CHANGE],
            'yoy_plus_change_16': COMPLETE_FEATURES},
        'outputs': {name: fe.fingerprint(out / name) for name, _, _ in outputs},
        'source_values_preserved': True, 'model_ready': False,
        'limitations': report['limitations']}
    write_json(out / 'feature_report.json', result)
    if any(fe.fingerprint(Path(p)) != checksum for p, checksum in hashes.items()):
        raise ValueError('Sumber berubah saat menghitung fitur inflasi.')
    return result
