"""Baca bukti pelengkapan data; seluruh arsip dan workbook asal hanya dibaca."""
from __future__ import annotations

# 1. Parser sumber tambahan dan pencarian observasi terdahulu memakai kalender
# sumber lengkap, termasuk hari ketika IHSG tidak berdagang.
import csv
import io
import json
import re
import zipfile
from bisect import bisect_right
from datetime import date, datetime
from pathlib import Path

import openpyxl
import xlrd

from preprocess_foreign import sha256


def bis_daily(path, filters):
    """Ambil tepat satu seri BIS, lengkap dengan baris serta metadata definisi."""
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.endswith('.csv')]
        if len(names) != 1:
            raise ValueError('Arsip BIS harus berisi tepat satu CSV')
        with archive.open(names[0]) as handle:
            reader = csv.DictReader(io.TextIOWrapper(handle, encoding='utf-8-sig'))
            matches = [(n, row) for n, row in enumerate(reader, 2)
                       if all(row.get(key) == value for key, value in filters.items())]
    if len(matches) != 1:
        raise ValueError(f'Seri BIS tidak unik/tidak ditemukan: {filters}')
    rownum, row = matches[0]
    observations = {key: float(value) for key, value in row.items()
                    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', key) and value != ''}
    metadata = {key: value for key, value in row.items() if not re.match(r'^\d{4}', key)}
    return observations, rownum, metadata


def load_gap_support(base, spec, records, target_dates, federal_holidays):
    """Verifikasi arsip, siapkan observasi tambahan dan izin pengisian per tanggal."""
    manifest_path = base / spec['sources_manifest']
    manifest = json.loads(manifest_path.read_text())
    sources = {}
    for key, source in manifest['sources'].items():
        path = (base / source['path']).resolve()
        if sha256(path) != source['sha256']:
            raise ValueError(f'Arsip pelengkapan berubah: {path}')
        sources[key] = {**source, 'file': str(path)}
    support = {'sources': sources, 'manifest_file': str(manifest_path),
               'manifest_sha256': sha256(manifest_path), 'supplements': {},
               'verified_gaps': {}, 'checks': {}}

    # 2. EIA mengonfirmasi tanggal tanpa observasi Brent. Nilai pada sumber
    # asli tidak diubah; izin forward-fill hanya dibuat untuk tanggal ini.
    eia_source = sources['eia_brent']
    workbook = xlrd.open_workbook(eia_source['file'])
    sheet = workbook.sheet_by_name('Data 1')
    eia = {xlrd.xldate_as_datetime(sheet.cell_value(i, 0), workbook.datemode).strftime('%Y-%m-%d'):
           sheet.cell_value(i, 1) for i in range(3, sheet.nrows)}
    gaps = {}
    for r in records['Brent']:
        if r['date'] not in target_dates or r['value'] is not None:
            continue
        if not min(eia) <= r['date'] <= max(eia):
            continue
        if isinstance(eia.get(r['date']), (int, float)):
            raise ValueError(f"Brent {r['date']} kosong tetapi EIA memiliki angka; periksa sumber")
        gaps[r['date']] = {'reason': 'no_observation_in_official_eia_archive',
                           'evidence_url': eia_source['url'], 'evidence_file': eia_source['file']}
    support['verified_gaps']['Brent'] = gaps

    # 3. US10Y: bedakan hari libur federal dan dua penutupan luar biasa yang
    # mempunyai bukti pengumuman Federal Reserve. Semua gap cocokkan ke FRED.
    with Path(sources['fred_us10y']['file']).open(encoding='utf-8-sig', newline='') as handle:
        fred = {r['observation_date']: r['DGS10'].strip() for r in csv.DictReader(handle)}
    gaps = {}
    for r in records['US10Y']:
        dt = r['date']
        if dt not in target_dates or r['value'] is not None:
            continue
        if dt not in fred or fred[dt] not in {'', '.'}:
            raise ValueError(f'US10Y {dt}: kosong tidak cocok dengan arsip FRED')
        if date.fromisoformat(dt) in federal_holidays(int(dt[:4])):
            reason, evidence = 'us_federal_holiday', sources['fred_us10y']
        elif dt == '2012-10-30':
            reason, evidence = 'hurricane_sandy_market_closure', sources['fed_h15_announcements']
        elif dt == '2018-12-05':
            reason, evidence = 'national_day_of_mourning_us', sources['fed_dec2018']
        else:
            # Tanggal baru yang belum dibuktikan tetap menjadi missing.
            continue
        gaps[dt] = {'reason': reason, 'evidence_url': evidence['url'], 'evidence_file': evidence['file']}
    support['verified_gaps']['US10Y'] = gaps

    # 4. RIWAYAT BI: BIS menyebut Bank Indonesia sebagai sumber seri D:ID.
    # Baca perubahan 6 Desember 2007 dari arsip, bukan dari keputusan Januari.
    policy_source = sources['bis_policy']
    policy, rownum, metadata = bis_daily(policy_source['file'], {'FREQ': 'D', 'REF_AREA': 'ID'})
    seed_date = spec['bi_initial_observation_date']
    if metadata['SOURCE_REF'].strip() != 'Bank Indonesia' or seed_date >= min(target_dates):
        raise ValueError('Identitas/riwayat awal seri kebijakan BI tidak sesuai')
    support['bi_seed'] = {'date': seed_date, 'value': policy[seed_date], 'source_row': rownum,
                          'source_column': seed_date, 'source_file': policy_source['file'],
                          'instrument': 'BI_rate_legacy', 'evidence_url': policy_source['url'],
                          'source_definition': metadata['COMPILATION'], 'source_series': metadata['Series']}
    support['checks']['bi_initial_values'] = {d: policy.get(d) for d in [seed_date, min(target_dates)]}

    # 5. KURS: periode sebelum JISDOR memakai observasi spot harian BIS hanya
    fx_source = sources['bis_fx']
    bis_fx, fx_rownum, fx_metadata = bis_daily(fx_source['file'],
        {'FREQ': 'D', 'REF_AREA': 'ID', 'CURRENCY': 'IDR', 'COLLECTION': 'A'})
    if fx_metadata['UNIT_MULT'] != '0':
        raise ValueError('Satuan BIS bukan rupiah per satu USD')
    bi_source = sources['bi_jisdor']
    workbook = openpyxl.load_workbook(bi_source['file'], read_only=True)
    try:
        bi = {}
        for n, row in enumerate(workbook.active.iter_rows(min_row=6, values_only=True), 6):
            if row[1] is None:
                continue
            dt = datetime.strptime(row[1], '%m/%d/%Y %I:%M:%S %p').strftime('%Y-%m-%d')
            bi[dt] = {'date': dt, 'value': float(row[2].replace('.', '').replace(',', '.')),
                      'source_row': n, 'source_column': 'C', 'source_file': bi_source['file'],
                      'evidence_url': bi_source['url'], 'source_definition': 'BI JISDOR, IDR per USD',
                      'source_series': 'JISDOR'}
    finally:
        workbook.close()
    support['official_bi_fx'] = bi
    support['verified_gaps']['USD_IDR'] = {
        r['date']: {**r, 'evidence_file': str((base / r['evidence_file']).resolve())}
        for r in spec['verified_bi_nonpublication_dates']}
    fx_original = {r['date']: r for r in records['USD_IDR']}
    supplements = {}
    for dt in sorted(target_dates):
        if fx_original.get(dt, {}).get('value') is not None:
            continue
        if dt < '2013-05-20' and dt in bis_fx:
            supplements[dt] = {'date': dt, 'value': bis_fx[dt], 'source_row': fx_rownum,
                'source_column': dt, 'source_file': fx_source['file'], 'evidence_url': fx_source['url'],
                'source_definition': fx_metadata['TITLE'].strip(), 'source_series': fx_metadata['Series']}
        elif dt in bi:
            supplements[dt] = bi[dt]
    support['supplements']['USD_IDR'] = supplements

    # Pencocokan seluruh overlap hanya membuktikan kesamaan angka pada snapshot,
    # bukan membuktikan provenance atau waktu tersedia historis per observasi.
    with Path(sources['yahoo_fx']['file']).open(encoding='utf-8-sig', newline='') as handle:
        yahoo = {r['Date'][:10]: r['Close'] for r in csv.DictReader(handle)}
    before = [(r['value'], float(yahoo[r['date']])) for r in records['USD_IDR']
              if r['date'] < '2013-05-20' and r['value'] is not None and yahoo.get(r['date'])]
    after = [(r['value'], bi[r['date']]['value']) for r in records['USD_IDR']
             if r['date'] in bi and r['value'] is not None]
    support['checks']['fx_original_matches'] = {
        'yahoo_before_jisdor': {'overlap': len(before), 'exact_matches': sum(a == b for a, b in before)},
        'official_bi_overlap': {'overlap': len(after), 'exact_matches': sum(a == b for a, b in after)}}
    if any(a != b for a, b in after):
        raise ValueError('Kurs asli pada overlap BI berubah; periksa definisi sebelum melengkapi')
    return support


def complete_daily_value(value, record, status, variable, target_date, valid_records,
                         valid_dates, support, max_age):
    """Isi hanya gap yang telah dibuktikan; nilai asli yang ada selalu menang."""
    if value is not None:
        return value, record, status, None
    supplement = support['supplements'].get(variable, {}).get(target_date)
    if supplement:
        return supplement['value'], supplement, 'supplemented_source_date', {
            'reason': 'verified_additional_daily_source', 'evidence_url': supplement['evidence_url'],
            'evidence_file': supplement['source_file']}
    evidence = support['verified_gaps'].get(variable, {}).get(target_date)
    if not evidence:
        return value, record, status, None
    # Untuk hari libur BI gunakan riwayat JISDOR resmi
    if variable == 'USD_IDR':
        by_date = support['official_bi_fx']
        dates = sorted(by_date)
        index = bisect_right(dates, target_date) - 1
        previous = by_date[dates[index]] if index >= 0 else None
    else:
        index = bisect_right(valid_dates, target_date) - 1
        previous = valid_records[index] if index >= 0 else None
    if previous is None:
        return value, record, status, None
    age = (date.fromisoformat(target_date) - date.fromisoformat(previous['date'])).days
    if age < 0 or age > max_age:
        return value, record, 'verified_gap_but_previous_value_too_old', evidence
    return previous['value'], previous, 'forward_filled_verified_no_observation', evidence
