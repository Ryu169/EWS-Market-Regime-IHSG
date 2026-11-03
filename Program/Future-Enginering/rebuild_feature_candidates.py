"""Hitung ulang baseline dan kandidat fitur dari preprocessing tahap 27.

Jalankan dengan Python environment Pre-Processing (memiliki openpyxl/xlrd).
Tidak melakukan training, mengubah target, atau membaca label final test.
Setiap run memakai folder baru; dataset dan model aktif tetap dipertahankan.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
from datetime import date, datetime, timezone
import json
import math
from pathlib import Path
from statistics import mean, stdev
import sys

sys.dont_write_bytecode = True
import feature_engineering as fe
import prepare_domestic15 as domestic
import prepare_inflation_release as inflation

HERE = Path(__file__).resolve().parent
PROGRAM = HERE.parent
PREPROCESSING = PROGRAM / 'Pre-Processing'
sys.path.insert(0, str(PREPROCESSING))
import apply_bi_rate_history as bi_history

REFERENCE = HERE / 'output/inflation_change_rebuilt_20261028'
BASELINE = [*fe.CORE, 'bi_rate_change', 'inflation_change_release']
GROUPS = {
    'relative_trend': ['price_to_ma20', 'ma20_slope_5d'],
    'risk_adjusted_momentum': ['risk_adjusted_return_5d'],
    'foreign_pressure': ['foreign_zscore_20d', 'foreign_net_buy_days_5d'],
    'domestic_policy': ['bi_rate_change_20d', 'bi_rate_change_60d', 'days_since_bi_rate_change'],
    'macro_5d': ['usdidr_return_5d', 'brent_return_5d', 'us10y_change_5d'],
}
EXTRA = [name for names in GROUPS.values() for name in names]
ALL_FEATURES = [*BASELINE, *EXTRA]
RELATIVE = [c for c in BASELINE if c not in {'ma_5', 'ma_20'}] + GROUPS['relative_trend']
VARIANTS = {
    'baseline_15': BASELINE,
    'without_volume_14': [c for c in BASELINE if c != 'volume_change'],
    'relative_trend_15': RELATIVE,
    'risk_adjusted_16': [*BASELINE, *GROUPS['risk_adjusted_momentum']],
    'foreign_pressure_17': [*BASELINE, *GROUPS['foreign_pressure']],
    'domestic_policy_18': [*BASELINE, *GROUPS['domestic_policy']],
    'macro_5d_18': [*BASELINE, *GROUPS['macro_5d']],
    'combined_exploratory_24': [*RELATIVE, *GROUPS['risk_adjusted_momentum'],
                              *GROUPS['foreign_pressure'], *GROUPS['domestic_policy'], *GROUPS['macro_5d']],
}
SPECS = {
    'price_to_ma20': ['Close / MA20 - 1', 'decimal_ratio', 19],
    'ma20_slope_5d': ['MA20[t] / MA20[t-5] - 1', 'decimal_return', 24],
    'risk_adjusted_return_5d': ['Return5D / (Volatility20D * sqrt(5))', 'dimensionless', 20],
    'foreign_zscore_20d': ['(Foreign[t] - mean(Foreign[t-19:t])) / sample_std20; flat window=0', 'dimensionless', 19],
    'foreign_net_buy_days_5d': ['count(Foreign > 0) on t-4..t', 'trading_days', 4],
    'bi_rate_change_20d': ['BI[t] - BI[t-20], only within one instrument regime', 'percentage_points', 20],
    'bi_rate_change_60d': ['BI[t] - BI[t-60], only within one instrument regime', 'percentage_points', 60],
    'days_since_bi_rate_change': ['calendar days since last observed nonzero BI change in the same regime', 'calendar_days', None],
    'usdidr_return_5d': ['USD_IDR[t] / USD_IDR[t-5] - 1', 'decimal_return', 5],
    'brent_return_5d': ['Brent[t] / Brent[t-5] - 1', 'decimal_return', 5],
    'us10y_change_5d': ['US10Y[t] - US10Y[t-5]', 'percentage_points', 5],
}


def write_json(path, value):
    domestic.write_json(path, value)


def write_csv(path, rows, columns):
    path.parent.mkdir(parents=True, exist_ok=True)
    fe.write_csv(path, [{c: r.get(c) for c in columns} for r in rows], columns)


# 1. Rekonstruksi audit dari sumber BI asli ketika CSV audit lama tidak tersedia.
# Setiap nilai wajib cocok dengan preprocessing; tidak ada nilai input yang diubah.
def bi_regimes(rows, observations):
    available = [r['AvailableFrom'] for r in observations]
    regimes, audit = {}, []
    for row in rows:
        position = bisect_right(available, row['Date']) - 1
        if position < 0:
            raise ValueError(f"Riwayat BI tidak tersedia pada {row['Date']}")
        event = observations[position]
        if not math.isclose(event['BI_Rate'], row['BI_Rate'], abs_tol=1e-12, rel_tol=0):
            raise ValueError(f"Nilai BI berbeda dari sumber audit pada {row['Date']}")
        age = (date.fromisoformat(row['Date']) - date.fromisoformat(event['ObservationDate'])).days
        if age > bi_history.MAX_AGE_DAYS:
            raise ValueError('Observasi BI melewati batas umur yang dipakai preprocessing.')
        regimes[row['Date']] = event['UnderlyingRegime']
        audit.append({'Date': row['Date'], 'BI_Rate': row['BI_Rate'],
            'ObservationDate': event['ObservationDate'], 'AvailableFrom': event['AvailableFrom'],
            'UnderlyingRegime': event['UnderlyingRegime'], 'SourceURL': event['SourceURL']})
    return regimes, audit


# 2. Pakai identitas rilis/timestamp tersimpan, lalu HITUNG ULANG change dari YoY.
# Kolom change lama tidak dijadikan input; rilis dengan YoY sama tetap rilis baru.
def inflation_availability(release_audit):
    return [{'Date': r['Date'], 'Variable': 'Inflation_YoY', 'Status': 'available',
             'ReferenceMonth': r['ReferenceMonth'], 'Value': r['InflationYoY'],
             'AvailableAtWIB': r['AvailableAtWIB']} for r in release_audit]


# 3. Semua jendela memakai posisi kalender penuh, tanpa membuang baris sebelumnya.
def window(rows, field, index, size):
    values = [r[field] for r in rows[max(0, index - size + 1):index + 1]]
    return values if len(values) == size and all(v is not None for v in values) else None


def calculate_candidates(rows, baseline, regimes):
    output, missing = [], []
    last_policy_change = None
    for i, (row, base) in enumerate(zip(rows, baseline)):
        feature = dict(base)
        reason = {}
        # Tren relatif: mengubah makna input harga, bukan sekadar StandardScaler.
        feature['price_to_ma20'] = fe.ratio(row['Close'], base['ma_20'])
        feature['ma20_slope_5d'] = fe.ratio(base['ma_20'], baseline[i - 5]['ma_20']) if i >= 5 else None
        volatility = base['volatility_20d']
        feature['risk_adjusted_return_5d'] = (base['ihsg_return_5d'] / (volatility * math.sqrt(5))
            if volatility is not None and volatility > 0 and base['ihsg_return_5d'] is not None else None)

        # Foreign sudah miliar rupiah; normalisasi terhadap sejarah Foreign sendiri.
        # Tidak dibagi Volume saham karena satuan dan cakupan pasarnya berbeda.
        foreign20, foreign5 = window(rows, 'Foreign', i, 20), window(rows, 'Foreign', i, 5)
        deviation = stdev(foreign20) if foreign20 is not None else None
        feature['foreign_zscore_20d'] = ((row['Foreign'] - mean(foreign20)) / deviation
            if deviation is not None and deviation > 0 else 0.0 if deviation == 0 else None)
        feature['foreign_net_buy_days_5d'] = sum(v > 0 for v in foreign5) if foreign5 is not None else None

        # Selisih BI 20/60 hari memakai N+1 titik, tanpa melewati perubahan instrumen.
        for n in [20, 60]:
            column = f'bi_rate_change_{n}d'
            values = window(rows, 'BI_Rate', i, n + 1)
            same = values is not None and all(regimes[r['Date']] == regimes[row['Date']]
                                             for r in rows[i - n:i + 1])
            feature[column] = row['BI_Rate'] - rows[i - n]['BI_Rate'] if same else None
            if values is not None and not same:
                reason[column] = 'policy_instrument_transition_in_window'
        if not i or regimes[row['Date']] != regimes[rows[i - 1]['Date']]:
            last_policy_change = None
        elif base['bi_rate_change'] is not None and base['bi_rate_change'] != 0:
            last_policy_change = row['Date']
        feature['days_since_bi_rate_change'] = ((date.fromisoformat(row['Date'])
            - date.fromisoformat(last_policy_change)).days if last_policy_change else None)
        if last_policy_change is None:
            reason['days_since_bi_rate_change'] = 'no_observed_change_yet_in_current_regime'

        # Makro lima hari memakai seri AS-OF dari preprocessing, bukan tanggal
        # observasi mentah yang pada saat prediksi mungkin belum diumumkan.
        for source, column in [('USD_IDR', 'usdidr_return_5d'), ('Brent', 'brent_return_5d')]:
            values = window(rows, source, i, 6)
            feature[column] = fe.ratio(values[-1], values[0]) if values is not None else None
        values = window(rows, 'US10Y', i, 6)
        feature['us10y_change_5d'] = values[-1] - values[0] if values is not None else None
        for column in EXTRA:
            value = feature[column]
            if value is not None and not math.isfinite(value):
                raise ValueError(f"Fitur tidak finite: {row['Date']} {column}")
            if value is None:
                lookback = SPECS[column][2]
                missing.append({'Date': row['Date'], 'Feature': column,
                    'Reason': reason.get(column, 'insufficient_initial_history' if lookback is not None
                                         and i < lookback else 'missing_or_zero_denominator_in_history')})
        output.append(feature)
    return output, missing


def is_complete(row, names):
    return all(row[c] is not None and math.isfinite(row[c]) for c in names)


def run(out):
    out = Path(out).resolve()
    if out.exists():
        raise ValueError('Gunakan folder output baru; hasil lama tidak ditimpa.')
    reference_report = json.loads((REFERENCE / 'feature_report.json').read_text())
    source = Path(reference_report['input_file'])
    if fe.fingerprint(source) != reference_report['raw_sha256']:
        raise ValueError('Preprocessing berubah dari versi yang sudah dikonfirmasi; periksa sumber dahulu.')
    raw = fe.read(source)
    if list(raw[0]) != fe.SOURCE_COLUMNS or [r['Date'] for r in raw] != sorted({r['Date'] for r in raw}):
        raise ValueError('Kolom/kalender preprocessing berubah.')
    rows = [{c: r[c] if c == 'Date' else None if r[c] == '' else float(r[c])
             for c in fe.SOURCE_COLUMNS} for r in raw]
    if any(r['Close'] is None or r['Close'] <= 0 or any(v is not None and not math.isfinite(v)
           for c, v in r.items() if c != 'Date') for r in rows):
        raise ValueError('Harga atau angka preprocessing tidak valid.')
    protected_paths = [source, REFERENCE / 'feature_report.json',
        REFERENCE / 'ihsg_preprocessing_features_all.csv', REFERENCE / 'inflation_release_audit.csv',
        REFERENCE / 'targets/split_metadata.json', REFERENCE / 'targets/thresholds.json',
        PREPROCESSING / 'inputs/bi_rate_policy_corrections.json', bi_history.INPUT,
        bi_history.CONFIG, bi_history.MANIFEST, Path(__file__), Path(fe.__file__),
        Path(domestic.__file__), Path(inflation.__file__), Path(bi_history.__file__)]
    models = PROGRAM / 'Training/runs/inflation_change_rebuilt_20261028/dashboard_models'
    protected_paths.extend(sorted(models.rglob('model.joblib')))
    protected = {str(p): fe.fingerprint(p) for p in protected_paths}
    out.mkdir(parents=True)
    write_json(out / 'run_status.json', {'status': 'running'})
    try:
        # Rekonstruksi metadata dari sumber yang masih tersimpan; audit lama tidak diubah.
        observations, metadata = bi_history.load_bi_observations()
        protected[str(metadata['bis_path'])] = fe.fingerprint(metadata['bis_path'])
        regimes, bi_audit = bi_regimes(rows, observations)
        release_source = fe.read(REFERENCE / 'inflation_release_audit.csv')
        expected_release_hash = reference_report['outputs']['inflation_release_audit.csv']
        if fe.fingerprint(REFERENCE / 'inflation_release_audit.csv') != expected_release_hash:
            raise ValueError('Versi kalender rilis inflasi sudah berubah.')
        changes, release_audit = inflation.build_change(raw, inflation_availability(release_source))
        calculated = domestic.corrected_domestic(rows, fe.calculate(rows), regimes)
        baseline = [{'Date': r['Date'], **{c: r[c] for c in fe.CORE},
                     'bi_rate_change': r['bi_rate_change'], inflation.CHANGE: changes[r['Date']]}
                    for r in calculated]

        # Baseline yang dihitung ulang wajib sama dengan versi 15 fitur yang sudah dilatih.
        previous = fe.read(REFERENCE / 'ihsg_preprocessing_features_all.csv')
        if [r['Date'] for r in previous] != [r['Date'] for r in raw]:
            raise ValueError('Kalender baseline berbeda.')
        for old, current, original in zip(previous, baseline, raw):
            if any(old[c] != original[c] for c in fe.SOURCE_COLUMNS):
                raise ValueError('Nilai raw berbeda dari baseline.')
            for column in BASELINE:
                value = None if old[column] == '' else float(old[column])
                if (value is None) != (current[column] is None) or value is not None and not math.isclose(
                        value, current[column], abs_tol=1e-12, rel_tol=1e-12):
                    raise ValueError(f"Baseline berubah: {old['Date']} {column}")
        features, missing = calculate_candidates(rows, baseline, regimes)
        combined = [{**r, **{c: f[c] for c in ALL_FEATURES}} for r, f in zip(raw, features)]
        common_dates = {r['Date'] for r in features if is_complete(r, ALL_FEATURES)}
        write_csv(out / 'features_all.csv', features, ['Date', *ALL_FEATURES])
        write_csv(out / 'ihsg_preprocessing_features_all.csv', combined, [*fe.SOURCE_COLUMNS, *ALL_FEATURES])
        write_csv(out / 'ihsg_preprocessing_features_common_complete.csv',
                  [r for r in combined if r['Date'] in common_dates], [*fe.SOURCE_COLUMNS, *ALL_FEATURES])
        counts = {}
        for name, names in VARIANTS.items():
            own = [r for r in features if is_complete(r, names)]
            common = [r for r in features if r['Date'] in common_dates]
            write_csv(out / 'variants' / f'{name}_complete.csv', own, ['Date', *names])
            write_csv(out / 'variants' / f'{name}_common_complete.csv', common, ['Date', *names])
            counts[name] = {'features': len(names), 'own_complete_rows': len(own), 'common_complete_rows': len(common)}
        write_csv(out / 'candidate_missing_details.csv', missing, ['Date', 'Feature', 'Reason'])
        write_csv(out / 'bi_regime_audit.csv', bi_audit, list(bi_audit[0]))
        write_csv(out / 'inflation_release_audit.csv', release_audit, list(release_audit[0]))
        write_csv(out / 'feature_dictionary.csv', [{'Feature': c, 'Formula': SPECS[c][0],
            'Unit': SPECS[c][1], 'LookbackTradingPositions': SPECS[c][2]} for c in EXTRA],
            ['Feature', 'Formula', 'Unit', 'LookbackTradingPositions'])

        # Target/fold tidak dibangun ulang. Hanya catat referensi/hash asal.
        # Tanggal lengkap per varian tidak boleh dipadatkan sebelum horizon dihitung.
        split = json.loads((REFERENCE / 'targets/split_metadata.json').read_text())
        development_end = split['splits_after_purge']['development_train']['end_date']
        validation_start = split['splits_after_purge']['validation']['start_date']
        validation_end = split['splits_after_purge']['validation']['end_date']
        validation_common = [r['Date'] for r in features if validation_start <= r['Date'] <= validation_end
                             and r['Date'] in common_dates]
        if len(validation_common) != split['splits_after_purge']['validation']['rows']:
            raise ValueError('Populasi common mengurangi tanggal validation; rancang perbandingan ulang.')
        contract = {'feature_sets': VARIANTS, 'all_features': ALL_FEATURES,
            'target_source_dir': str(REFERENCE / 'targets'), 'target_column': 'y_t',
            'horizon_trading_days': 5, 'thresholds_sha256': fe.fingerprint(REFERENCE / 'targets/thresholds.json'),
            'split_metadata_sha256': fe.fingerprint(REFERENCE / 'targets/split_metadata.json'),
            'common_complete_file': 'ihsg_preprocessing_features_common_complete.csv',
            'common_validation_dates': validation_common,
            'training_policy': 'Join X baru ke label/fold lama berdasarkan Date. Gunakan common mask yang sama; jangan hitung target dari CSV complete.',
            'forbidden_model_input': [*fe.SOURCE_COLUMNS, 'y_t', 'future_return_5d', 'label_end_date', 'calendar_index'],
            'mandatory_domestic_features': ['bi_rate_change', 'inflation_change_release'],
            'training_executed': False, 'final_test_labels_read': False,
            'final_test_policy': 'Test lama sudah pernah dibuka; tidak digunakan untuk seleksi fitur/parameter.'}
        write_json(out / 'feature_contract.json', contract)
        report = {'created_at_utc': datetime.now(timezone.utc).isoformat(),
            'input_file': str(source), 'raw_sha256': protected[str(source)],
            'reference_feature_dir': str(REFERENCE), 'rows': len(rows), 'baseline_features': 15,
            'added_features': len(EXTRA), 'total_available_features': len(ALL_FEATURES),
            'common_complete_rows': len(common_dates),
            'common_development_rows': sum(r['Date'] in common_dates and r['Date'] <= development_end for r in features),
            'common_validation_rows': len(validation_common), 'variants': counts,
            'missing': {c: sum(r[c] is None for r in features) for c in ALL_FEATURES},
            'baseline_recalculated_and_matches_previous': True, 'raw_columns_preserved': True,
            'targets_thresholds_and_folds_unchanged': True, 'training_executed': False,
            'final_test_labels_read': False, 'dashboard_updated': False,
            'metadata_recovery': 'BI audit direkonstruksi dari workbook, koreksi BI, dan seed BIS; inflasi memakai kalender rilis tersimpan dan change dihitung ulang.',
            'limitations': [*reference_report['limitations'],
                'Days-since-change kosong sebelum perubahan BI pertama yang benar-benar teramati di tiap rezim.',
                'Fitur baru adalah kandidat; peningkatan accuracy belum diuji.'], 'protected_hashes': protected}
        if any(fe.fingerprint(Path(p)) != h for p, h in protected.items()):
            raise ValueError('Berkas sumber/model aktif berubah selama perhitungan.')
        write_json(out / 'feature_report.json', report)
        write_json(out / 'verification.json', {'status': 'passed', 'source_and_active_models_unchanged': True,
            'baseline_all_dates_reproduced': True, 'original_calendar_preserved': True,
            'common_validation_dates': len(validation_common), 'training_executed': False,
            'final_test_labels_read': False})
        write_json(out / 'run_status.json', {'status': 'completed'})
        print(f'Selesai: {out}', flush=True)
        print(f'{len(rows)} tanggal; 15 fitur baseline + {len(EXTRA)} kandidat; {len(common_dates)} common complete.', flush=True)
        for name, count in counts.items():
            print(f"  {name}: {count['features']} fitur, own={count['own_complete_rows']}, common={count['common_complete_rows']}")
        return out
    except BaseException as exc:
        write_json(out / 'run_status.json', {'status': 'failed', 'error': str(exc)})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
    run(args.output_dir or HERE / 'output' / f'feature_candidates_{stamp}')
