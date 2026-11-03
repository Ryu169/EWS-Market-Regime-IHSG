"""Hitung ulang fitur pada kalender preprocessing terbaru dengan jejak sumber.

Jalankan: python feature_engineering.py
Status kualitas data diwarisi dari preprocessing; perhitungan tidak melatih model.
"""
import argparse
import csv
import json
import hashlib
import math
import shutil
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import mean, stdev

HERE=Path(__file__).resolve().parent
CORE=['ihsg_return_1d','ihsg_return_5d','ma_5','ma_20','ma_ratio','volatility_5d','volatility_20d','rsi_14','volume_change','foreign_net_5d','usdidr_return','brent_return','us10y_change']
CANDIDATES = ['bi_rate_change', 'inflation_yoy']
SOURCE_COLUMNS = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume', 'Foreign',
                  'USD_IDR', 'Brent', 'US10Y', 'BI_Rate', 'Inflation_YoY']
REQUIRED_INPUTS = ['Close', 'Volume', 'Foreign', 'USD_IDR', 'Brent', 'US10Y']
DEFAULT_SOURCE = HERE.parent / 'Pre-Processing/output/27_calendar_adjustments/ihsg_preprocessing_candidate.csv'
DEFAULT_SOURCE_REPORT = HERE.parent / 'Pre-Processing/reports/27_calendar_adjustments/summary.json'
OUTPUT_NAMES = ['features_all.csv', 'features_core_complete.csv',
                'ihsg_preprocessing_features_all.csv', 'ihsg_preprocessing_features_core_complete.csv',
                'feature_missing_details.csv']


def fingerprint(path):
    """Hubungkan setiap keluaran dengan versi persis berkas sumbernya."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def read(path):
    with path.open(encoding='utf-8-sig',newline='') as f:
        return list(csv.DictReader(f))


def load_preprocessing(source, source_report):
    """Baca kandidat terbaru; kalender tidak ditambah dari tahap pemulihan lama."""
    source, source_report = Path(source).resolve(), Path(source_report).resolve()
    metadata = json.loads(source_report.read_text(encoding='utf-8'))
    if fingerprint(source) != metadata.get('output_sha256'):
        raise ValueError('Checksum preprocessing berbeda dari laporan; bangun ulang preprocessing terlebih dahulu.')
    if Path(metadata.get('output_candidate', '')).resolve() != source:
        raise ValueError('Laporan preprocessing merujuk ke berkas kandidat yang berbeda.')
    with source.open(encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != SOURCE_COLUMNS:
            raise ValueError('Urutan kolom preprocessing harus Date, OHLCV, Foreign, dan lima indikator makro.')
        raw = list(reader)
    if not raw or len(raw) != metadata.get('output_rows'):
        raise ValueError('Jumlah baris preprocessing kosong atau berbeda dari laporan.')
    dates = [row['Date'] for row in raw]
    if dates != sorted(set(dates)):
        raise ValueError('Tanggal preprocessing harus unik dan terurut; jangan menambah atau memadatkan kalender.')
    rows = []
    for original in raw:
        day = original['Date']
        if date.fromisoformat(day).isoformat() != day:
            raise ValueError(f'Tanggal bukan format ISO: {day}')
        row = {'Date': day}
        for field in SOURCE_COLUMNS[1:]:
            value = None if original[field] == '' else float(original[field])
            if value is not None and not math.isfinite(value):
                raise ValueError(f'Nilai nonfinite pada {day} {field}')
            if value is not None and field in {'Close', 'Volume', 'USD_IDR', 'Brent'} and value <= 0:
                raise ValueError(f'Nilai nonpositif pada {day} {field}; periksa preprocessing.')
            row[field] = value
        rows.append(row)
    if any(day in set(dates) for day in metadata.get('excluded_dates', [])):
        raise ValueError('Tanggal yang dikecualikan preprocessing masuk kembali ke kalender.')
    return raw, rows, metadata

def ratio(a,b):
    """Pembagi nol atau input kosong menghasilkan missing, bukan infinity."""
    return a/b-1 if a is not None and b is not None and b!=0 else None

def combine_by_date(rows, features):
    """Pasangkan data asal dan fitur menurut Date, tanpa mengandalkan urutan."""
    features_by_date = {r['Date']: r for r in features}
    dates = [r['Date'] for r in rows]
    if len(set(dates)) != len(rows) or len(features_by_date) != len(features):
        raise ValueError('Tanggal duplikat pada data asal atau fitur')
    if set(dates) != set(features_by_date):
        raise ValueError('Tanggal data asal dan fitur tidak sama')
    feature_columns = [*CORE, 'bi_rate_change', 'inflation_yoy']
    if set(rows[0]) & set(feature_columns):
        raise ValueError('Nama kolom fitur bertabrakan dengan kolom data asal')
    return [{**r, **{c: features_by_date[r['Date']][c] for c in feature_columns}}
            for r in rows]

def missing_details(rows, features):
    """Catat kebutuhan riwayat dan data bermasalah untuk setiap fitur kosong."""
    required = dict(zip(CORE, [1,5,4,19,19,5,20,14,1,4,1,1,1]))
    required.update(bi_rate_change=1, inflation_yoy=0)
    details = []
    for i, (r, feature) in enumerate(zip(rows, features)):
        for name, lookback in required.items():
            if feature[name] is not None:
                continue
            reason = 'missing_value_in_required_history'
            if i < lookback:
                reason = 'insufficient_initial_history'
            elif name == 'volume_change':
                values = [r['Volume'], rows[i-1]['Volume']]
                reason = ('missing_volume_current_or_previous' if None in values
                          else 'nonpositive_volume_current_or_previous')
            elif name == 'rsi_14':
                reason = 'close_gap_or_wilder_reinitialization_requires_14_changes'
            elif name == 'bi_rate_change' and (
                (r['Date'] < '2016-08-19') != (rows[i-1]['Date'] < '2016-08-19')
            ):
                reason = 'policy_instrument_transition'
            details.append({'Date': r['Date'], 'Feature': name, 'Reason': reason})
    return details

def calculate(rows):
    """Semua jendela hanya melihat baris saat ini dan sebelumnya."""
    output=[]; returns=[]; gains=[]; losses=[]; ag=al=None
    for i,r in enumerate(rows):
        prev=rows[i-1] if i else {}
        ret=ratio(r['Close'],prev.get('Close')); returns.append(ret)
        f={'Date':r['Date'],'ihsg_return_1d':ret,'ihsg_return_5d':ratio(r['Close'],rows[i-5]['Close']) if i>=5 and all(x['Close'] is not None for x in rows[i-5:i+1]) else None}
        for n in [5,20]:
            closes=[x['Close'] for x in rows[max(0,i-n+1):i+1]]
            rs=returns[max(0,i-n+1):i+1]
            f[f'ma_{n}']=mean(closes) if len(closes)==n and None not in closes else None
            f[f'volatility_{n}d']=stdev(rs) if len(rs)==n and None not in rs else None
        f['ma_ratio']=ratio(f['ma_5'],f['ma_20'])
        # Wilder: seed rata-rata 14 perubahan, reset setelah gap harga.
        delta=r['Close']-prev['Close'] if r['Close'] is not None and prev.get('Close') is not None else None
        if delta is None:
            gains=[]; losses=[]; ag=al=None
        else:
            g,l=max(delta,0),max(-delta,0)
            if ag is None:
                gains.append(g); losses.append(l)
                if len(gains)==14:ag,al=mean(gains),mean(losses)
            else:ag,al=(13*ag+g)/14,(13*al+l)/14
        f['rsi_14']=None if ag is None else (50 if ag==al==0 else 100 if al==0 else 100-100/(1+ag/al))
        # Volume nol yang terindikasi bermasalah tidak menjadi penurunan 100%.
        f['volume_change']=ratio(r['Volume'],prev.get('Volume')) if r['Volume'] is not None and r['Volume']>0 and prev.get('Volume') is not None and prev['Volume']>0 else None
        fnf=[x['Foreign'] for x in rows[max(0,i-4):i+1]]
        f['foreign_net_5d']=sum(fnf) if len(fnf)==5 and None not in fnf else None
        for source,name in [('USD_IDR','usdidr_return'),('Brent','brent_return')]:f[name]=ratio(r[source],prev.get(source))
        f['us10y_change']=r['US10Y']-prev['US10Y'] if r['US10Y'] is not None and prev.get('US10Y') is not None else None
        # Kandidat domestik tidak menghitung selisih melintasi instrumen 2016.
        f['bi_rate_change']=r['BI_Rate']-prev['BI_Rate'] if r['BI_Rate'] is not None and prev.get('BI_Rate') is not None and i and (r['Date']<'2016-08-19')==(prev['Date']<'2016-08-19') else None
        f['inflation_yoy']=r['Inflation_YoY']
        output.append(f)
    return output

def write_csv(path, records, columns):
    """Simpan angka tanpa pembulatan dan missing sebagai sel CSV kosong."""
    with path.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(records)


def run_features(source=DEFAULT_SOURCE, source_report=DEFAULT_SOURCE_REPORT, output_dir=None):
    # 1. Bekukan identitas input dan muat persis kalender preprocessing tahap 27.
    source, source_report = Path(source).resolve(), Path(source_report).resolve()
    out = Path(output_dir or HERE / 'output').resolve()
    hashes = {str(path): fingerprint(path) for path in (source, source_report)}
    if source in {out / name for name in OUTPUT_NAMES}:
        raise ValueError('Output tidak boleh menimpa berkas input.')
    raw, rows, upstream = load_preprocessing(source, source_report)

    # 2. Hitung seluruh jendela sebelum menyaring baris yang belum cukup riwayat.
    features = calculate(rows)
    combined = combine_by_date(raw, features)
    complete = [row for row in features if all(row[column] is not None for column in CORE)]
    complete_dates = {row['Date'] for row in complete}
    combined_complete = [row for row in combined if row['Date'] in complete_dates]
    if [row['Date'] for row in features] != [row['Date'] for row in raw]:
        raise ValueError('Perhitungan fitur mengubah kalender preprocessing.')
    for original, result in zip(raw, combined):
        if any(result[column] != original[column] for column in SOURCE_COLUMNS):
            raise ValueError(f'Nilai preprocessing berubah ketika fitur digabung: {original["Date"]}')
    if any(value is not None and not math.isfinite(value)
           for row in features for name, value in row.items() if name != 'Date'):
        raise ValueError('Perhitungan menghasilkan fitur nonfinite.')

    # 3. Arsipkan keluaran fitur lama ketika identitas sumber berubah.
    out.mkdir(parents=True, exist_ok=True)
    archive = None
    previous_report = out / 'feature_report.json'
    if previous_report.exists():
        previous = json.loads(previous_report.read_text(encoding='utf-8'))
        if previous.get('raw_sha256') != hashes[str(source)]:
            archive = out / 'archive' / datetime.now(timezone.utc).strftime('before_rerun_%Y%m%dT%H%M%S_%fZ')
            archive.mkdir(parents=True)
            for name in [*OUTPUT_NAMES, 'feature_report.json']:
                if (out / name).is_file():
                    shutil.copy2(out / name, archive / name)
    feature_columns = ['Date', *CORE, *CANDIDATES]
    combined_columns = [*SOURCE_COLUMNS, *CORE, *CANDIDATES]
    for name, records, columns in [
        ('features_all.csv', features, feature_columns),
        ('features_core_complete.csv', complete, feature_columns),
        ('ihsg_preprocessing_features_all.csv', combined, combined_columns),
        ('ihsg_preprocessing_features_core_complete.csv', combined_complete, combined_columns),
        ('feature_missing_details.csv', missing_details(rows, features), ['Date', 'Feature', 'Reason']),
    ]:
        write_csv(out / name, records, columns)

    # 4. Tandai target/split lama sebagai versi sebelumnya; tidak dihitung pada tahap ini.
    target_metadata = out / 'targets/split_metadata.json'
    target_status = {'status': 'not_built', 'action': 'Jalankan build_targets.py dari fitur terbaru sebelum training.'}
    if target_metadata.exists():
        old_targets = json.loads(target_metadata.read_text(encoding='utf-8'))
        current_hash = fingerprint(out / 'ihsg_preprocessing_features_all.csv')
        target_status.update(
            status='current' if old_targets.get('input_sha256') == current_hash else 'stale_requires_rebuild',
            previous_feature_sha256=old_targets.get('input_sha256'),
            current_feature_sha256=current_hash,
        )
        if target_status['status'] == 'stale_requires_rebuild':
            (out / 'targets/STATUS_FEATURE_INPUT.md').write_text(
                '# Target dan split perlu dibangun ulang\n\n'
                'Feature engineering sudah memakai preprocessing tahap 27. Target, threshold, '
                'split, dan fold pada folder ini masih berasal dari fitur sebelumnya. '
                'Jangan memakai artefak lama untuk training ulang. Jalankan '
                '`python build_targets.py` sebelum training.\n', encoding='utf-8'
            )

    # 5. Simpan kelengkapan numerik dan status kualitas sebagai dua informasi berbeda.
    incomplete = [i for i, row in enumerate(features) if row['Date'] not in complete_dates]
    report = {
        'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'status': 'exploratory_recomputed_from_latest_preprocessing',
        'feature_computation_complete': True,
        'input_file': str(source), 'source_report': str(source_report),
        'raw_sha256': hashes[str(source)], 'source_report_sha256': hashes[str(source_report)],
        'script_sha256': fingerprint(__file__),
        'input_rows': len(raw), 'calendar_rows': len(rows),
        'date_start': raw[0]['Date'], 'date_end': raw[-1]['Date'],
        'added_calendar_dates': [],
        'excluded_dates_inherited': upstream.get('excluded_dates', []),
        'calendar_augmentation_policy': 'Preserve every date in stage 27 exactly; no old recovery dates reinserted.',
        'features_core': CORE, 'features_candidates': CANDIDATES,
        'core_complete_rows': len(complete), 'core_incomplete_rows': len(incomplete),
        'first_core_complete_date': complete[0]['Date'] if complete else None,
        'incomplete_within_first_20_rows': sum(index < 20 for index in incomplete),
        'incomplete_after_first_20_rows': sum(index >= 20 for index in incomplete),
        'core_inputs_complete_rows': sum(all(row[field] is not None for field in REQUIRED_INPUTS) for row in rows),
        'missing_by_feature': {column: sum(row[column] is None for row in features) for column in [*CORE, *CANDIDATES]},
        'source_missing_by_column': {column: sum(row[column] == '' for row in raw) for column in SOURCE_COLUMNS},
        'combined_columns': combined_columns,
        'source_values_preserved_exactly': True,
        'source_date_macro_join': False,
        'macro_alignment': 'Inherited preprocessing candidate with provisional availability policies; not realigned in feature engineering.',
        'fx_series': 'ECB IDR/EUR divided by USD/EUR, inherited from latest preprocessing.',
        'preprocessing_approved_for_feature_engineering': upstream.get('preprocessing_approved_for_feature_engineering', False),
        'model_ready': False, 'models_trained': False,
        'targets_and_splits': target_status,
        'previous_feature_archive': str(archive) if archive else None,
        'limitations': [
            'Volume historis masih mencampur cakupan/proxy; Volume Change mewarisi keterbatasan tersebut.',
            'Kalender mengikuti keputusan pengecualian pengguna, dengan konflik bukti perdagangan yang tersimpan.',
            'Kebijakan waktu tersedia makro memakai asumsi konservatif preprocessing, belum pembuktian historis seluruh jam rilis.',
            'OHL 21 April 2009 kosong dan empat rentang OHLC perlu ditinjau; OHL tidak dipakai dalam 13 fitur inti.',
            'Subset fitur lengkap hanya tampilan; hitung horizon label dari kalender lengkap sebelum penyaringan.',
            'Target, threshold, split, dan fold perlu dibangun ulang sebelum training dari fitur terbaru.',
        ],
        'outputs': {name: fingerprint(out / name) for name in OUTPUT_NAMES},
    }
    if any(fingerprint(Path(path)) != checksum for path, checksum in hashes.items()):
        raise ValueError('Berkas preprocessing berubah selama perhitungan fitur.')
    report['input_files_unchanged'] = True
    (out / 'feature_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: report[key] for key in [
        'input_file', 'calendar_rows', 'core_complete_rows', 'first_core_complete_date',
        'incomplete_after_first_20_rows', 'status', 'targets_and_splits',
    ]}, ensure_ascii=False, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=DEFAULT_SOURCE)
    parser.add_argument('--source-report', type=Path, default=DEFAULT_SOURCE_REPORT)
    parser.add_argument('--output', type=Path, default=HERE / 'output')
    args = parser.parse_args()
    run_features(args.input, args.source_report, args.output)


if __name__ == '__main__':
    main()
