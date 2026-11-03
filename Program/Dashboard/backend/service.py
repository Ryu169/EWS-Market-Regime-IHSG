"""Muat model sekali, impor dataset lokal, simpan prediksi secara atomik.

Riwayat memakai prediksi out-of-fold validation yang sudah tersimpan. Inferensi
baru untuk lima tanggal ujung tanpa target tersedia. Simulasi pada data pelatihan
disimpan terpisah dari evaluasi. Final test diimpor dari hasil evaluasi model beku;
server tidak membaca CSV target final test atau melatih model.
"""
import csv
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics
import threading
import uuid
from zoneinfo import ZoneInfo
import joblib
import numpy as np
from sqlalchemy import func, select, update
from .db import HistoricalReplay, MarketData, ModelRun, PipelineRun, Prediction, Snapshot, SourceRegistry
from .domain import CLASSES, CORE, RAW, ews, explanation, probabilities, regime

PROGRAM = Path(__file__).resolve().parents[2]
RUN = PROGRAM / 'Training/runs/inflation_change_rebuilt_20261028/dashboard_models'
FEATURES = PROGRAM / 'Future-Enginering/output/inflation_change_rebuilt_20261028/ihsg_preprocessing_features_all.csv'
DOMESTIC_FEATURES = [*CORE, 'bi_rate_change', 'inflation_change_release']
TEST_EVALUATION = RUN.parent / 'dashboard_final_test_20261028'
TRIAL = 'depth_2_regularized_100'
DISCLAIMER = 'Sistem ini merupakan alat bantu analisis kondisi pasar dan bukan rekomendasi langsung untuk melakukan transaksi jual atau beli saham.'
SOURCES = {
    'Close': ('IHSG', 'Poin indeks', 'BEI dan arsip dataset penelitian', 'https://www.idx.co.id/id/data-pasar/laporan-statistik/digital-statistic/'),
    'Volume': ('Volume', 'Miliar lembar saham', 'Dataset penelitian; cakupan historis masih memiliki catatan audit', None),
    'Foreign': ('Foreign Net Flow', 'Miliar rupiah', 'BEI, nilai beli asing dikurangi jual asing', 'https://www.idx.co.id/'),
    'USD_IDR': ('USD/IDR', 'Rupiah per USD', 'Kurs silang ECB IDR/EUR ÷ USD/EUR, diselaraskan oleh preprocessing', 'https://data.ecb.europa.eu/'),
    'Brent': ('Brent Oil', 'USD per barel', 'FRED DCOILBRENTEU / EIA', 'https://fred.stlouisfed.org/series/DCOILBRENTEU'),
    'US10Y': ('US Treasury 10Y', 'Persen', 'FRED DGS10 / Federal Reserve', 'https://fred.stlouisfed.org/series/DGS10'),
    'BI_Rate': ('BI-Rate', 'Persen', 'Bank Indonesia; sumber perhitungan BI-Rate Change', 'https://www.bi.go.id/id/statistik/indikator/bi-rate.aspx'),
    'Inflation_YoY': ('Inflasi IHK YoY', 'Persen YoY', 'BPS; sumber perhitungan Inflation Change antarrilis', 'https://www.bps.go.id/'),
    'bi_rate_change': ('BI-Rate Change', 'Poin persentase (pp)', 'Perubahan BI-Rate pada rezim kebijakan yang sama', 'https://www.bi.go.id/id/statistik/indikator/bi-rate.aspx'),
    'inflation_change_release': ('Inflation Change', 'Poin persentase (pp)', 'Selisih inflasi YoY antarrilis; dipertahankan hingga rilis berikutnya', 'https://www.bps.go.id/'),
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def csv_rows(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle))


def now():
    return datetime.now(timezone.utc).isoformat()


class ModelStore:
    def __init__(self, run=RUN):
        self.run = Path(run)
        self.summary = read_json(self.run / 'summary.json')
        self.protocol = read_json(self.run / 'protocol.json')
        self.entries = {}
        packaged = self.summary['status'] == 'completed_exploratory_dashboard_package'
        if not packaged and self.summary['status'] != 'completed_exploratory_complexity_comparison':
            raise ValueError('Artefak penelitian belum selesai.')
        # Kontrak mengikuti paket model; model lama tetap bisa dibuka untuk rollback.
        self.feature_names = self.summary['features'] if packaged else CORE
        if self.feature_names != (DOMESTIC_FEATURES if packaged else CORE):
            raise ValueError('Kontrak fitur paket dashboard tidak cocok.')
        self.feature_file = Path(self.summary['feature_file']) if packaged else PROGRAM / 'Future-Enginering/output/ihsg_preprocessing_features_all.csv'
        self.training_file = Path(self.summary['training_file']) if packaged else self.feature_file.parent / 'targets/splits/development_train.csv'
        self.training_sha = self.summary['training_file_sha256'] if packaged else self.summary['input_hashes']['splits/development_train.csv']
        for name in ['xgboost', 'lightgbm']:
            folder = self.run / 'selected_models' / name / 'development_model'
            meta = read_json(folder / 'model_metadata.json')
            if meta['features'] != self.feature_names or meta['classes'] != [0, 1, 2]:
                raise ValueError('Urutan fitur/kelas artefak berbeda dari kontrak.')
            if meta['input_hashes'] != self.summary['input_hashes']:
                raise ValueError('Versi masukan artefak berbeda dari evaluasi.')
            if packaged:
                manifest = self.summary['model_artifacts'][name]
                if sha(folder / 'model.joblib') != manifest['model_sha256'] or sha(folder / 'model_metadata.json') != manifest['metadata_sha256']:
                    raise ValueError('Checksum model berbeda dari paket dashboard.')
                if meta['training_file_sha256'] != self.training_sha:
                    raise ValueError('Data refit berbeda dari paket dashboard.')
            model = joblib.load(folder / 'model.joblib')
            if sorted(map(int, model.classes_)) != [0, 1, 2] or model.n_features_in_ != len(self.feature_names):
                raise ValueError('Dimensi model atau kelas tidak valid.')
            evaluation = self.summary['results'][name] if packaged else self.summary['results'][name][TRIAL]
            if evaluation['parameters'] != meta['parameters']:
                raise ValueError('Parameter model tersimpan berbeda dari evaluasi.')
            validation_file = self.run / 'validation' / name / 'validation_predictions.csv' if packaged else self.run / 'trials' / name / TRIAL / 'validation_predictions.csv'
            self.entries[name] = {'model': model, 'metadata': meta, 'evaluation': evaluation,
                                  'validation_file': validation_file,
                                  'id': digest([sha(folder / 'model.joblib'), sha(folder / 'model_metadata.json')])}
        # Pilih referensi tampilan dari Macro F1 validation, bukan final test.
        best = max(e['evaluation']['summary']['macro_f1']['mean'] for e in self.entries.values())
        near = [name for name, e in self.entries.items()
                if best - e['evaluation']['summary']['macro_f1']['mean'] <= .001]
        self.default_model = min(near, key=lambda name: (
            self.entries[name]['evaluation']['summary']['macro_f1']['std'],
            -self.entries[name]['evaluation']['summary']['accuracy']['mean'], name))
        # Test sudah dievaluasi sekali oleh skrip terpisah, tanpa fit atau tuning.
        # Checksum mengikat hasil test ke model yang persis sama dengan validation.
        self.test_report = read_json(TEST_EVALUATION / 'summary.json')
        if self.test_report['status'] != 'completed_frozen_model_test' or self.test_report['fit_count'] != 0:
            raise ValueError('Hasil test model beku tidak valid.')
        if self.test_report['features'] != self.feature_names or self.test_report['split_metadata_sha256'] != self.summary['input_hashes']['split_metadata.json']:
            raise ValueError('Versi fitur test berbeda dari model.')
        for name, entry in self.entries.items():
            if self.test_report['models'][name]['model_id'] != entry['id']:
                raise ValueError('Hasil test bukan berasal dari model yang sedang dimuat.')
            path = TEST_EVALUATION / f'{name}_test_predictions.csv'
            if sha(path) != self.test_report['prediction_sha256'][name]:
                raise ValueError('Checksum hasil prediksi test berbeda.')
            entry['test_file'] = path


class Service:
    def __init__(self, sessions, store=None, features=None):
        self.sessions = sessions
        self.store = store or ModelStore()
        self.features = Path(features or self.store.feature_file)
        self.lock = threading.Lock()
        self.training_dates = set()

    def prepare_training_replays(self):
        """Siapkan penelusuran seluruh kalender sekali, tanpa refit.

        Keanggotaan tanggal mengikuti file development_train yang benar-benar
        dipakai untuk model tersimpan. Tanggal OOF mempertahankan hasil fold asli.
        """
        with self.lock:
            rows, _ = self.prepare_rows()
            split = read_json(self.features.parent / 'targets/split_metadata.json')
            path = self.store.training_file
            expected = self.store.training_sha
            original_sha = self.store.summary['input_hashes']['splits/development_train.csv']
            if sha(path) != expected or original_sha != split['artifacts']['splits/development_train.csv']['sha256']:
                raise ValueError('Versi tanggal development berbeda dari model tersimpan.')
            training = csv_rows(path)
            dates = [r['Date'] for r in training]
            if dates != sorted(set(dates)):
                raise ValueError('Tanggal pelatihan tidak unik atau tidak terurut.')
            by_date = {r['Date']: r for r in rows}
            positions = {r['Date']: i for i, r in enumerate(rows)}
            for row in training:
                if row['Date'] not in by_date or any(float(row[c]) != by_date[row['Date']][c] for c in self.store.feature_names):
                    raise ValueError('Fitur simulasi tidak cocok dengan data yang dilatih.')
            self.training_dates = set(dates)
            with self.sessions() as session:
                snapshot_id = self.active(session).id
            created = 0
            for name, entry in self.store.entries.items():
                meta = entry['metadata']
                if len(dates) != meta['training_rows'] or dates[0] != meta['training_start'] or dates[-1] != meta['training_end']:
                    raise ValueError('Cakupan simulasi berbeda dari metadata pelatihan.')
                with self.sessions() as session:
                    recorded = set(session.scalars(select(Prediction.date).where(
                        Prediction.snapshot_id == snapshot_id, Prediction.model == name)))
                    cached = set(session.scalars(select(HistoricalReplay.date).where(
                        HistoricalReplay.snapshot_id == snapshot_id, HistoricalReplay.model == name)))
                missing = sorted(set(by_date) - recorded - cached)
                if not missing:
                    continue
                complete = [d for d in missing if all(by_date[d][c] is not None for c in self.store.feature_names)]
                matrix = np.asarray([[by_date[d][c] for c in self.store.feature_names] for d in complete], dtype=float)
                output = entry['model'].predict_proba(matrix) if complete else np.empty((0, 3))
                order = [list(entry['model'].classes_).index(c) for c in [0, 1, 2]]
                stamp = now()
                replays = []
                for day, values in zip(complete, output[:, order]):
                    end = positions[day] + 5
                    target_date = rows[end]['Date'] if end < len(rows) else None
                    origin = 'training_replay' if day in self.training_dates else 'purge_gap'
                    pred = self.make_prediction(name, entry, by_date[day], probabilities(values),
                        meta['thresholds']['T_B'], meta['thresholds']['T_U'], stamp,
                        origin, target_date, None)
                    pred.update(evaluation_eligible=False, training_end=meta['training_end'],
                        usage_notice=('Simulasi pada data yang sudah digunakan untuk melatih model. '
                        'Hasil ini bukan prediksi out-of-sample atau bukti accuracy pada tanggal tersebut.'
                        if origin == 'training_replay' else 'Simulasi retrospektif pada jeda purge. '
                        'Tidak digunakan untuk skor validation/test dan bukan evaluasi out-of-sample.'))
                    replays.append(HistoricalReplay(snapshot_id=snapshot_id, model=name, date=day, payload=pred))
                # Data awal dan transisi BI tetap terlihat, tanpa mengarang fitur/prediksi.
                for day in sorted(set(missing) - set(complete)):
                    row = by_date[day]
                    missing_features = [c for c in self.store.feature_names if row[c] is None]
                    payload = {'data_date': day, 'prediction_date': day, 'model_name': name,
                        'model_version': entry['id'], 'origin': 'data_only', 'prediction_available': False,
                        'evaluation_eligible': False, 'generated_at': stamp, 'target_date': None,
                        'horizon_trading_days': 5, 'current_regime': None, 'predicted_future_regime': None,
                        'class_probabilities': {}, 'ews_status': None, 'actual_future_regime': None,
                        'current_return_5d': row['ihsg_return_5d'], 'missing_features': missing_features,
                        'usage_notice': 'Data tersedia, tetapi prediksi belum tersedia karena fitur belum lengkap '
                            '(warm-up indikator atau transisi definisi BI-Rate).',
                        'feature_values': {c: row[c] for c in self.store.feature_names},
                        'market': {c: row[c] for c in RAW if c != 'Date'}}
                    replays.append(HistoricalReplay(snapshot_id=snapshot_id, model=name, date=day, payload=payload))
                with self.sessions.begin() as session:
                    if self.active(session).id != snapshot_id:
                        raise RuntimeError('Snapshot berubah selama simulasi. Jalankan sinkronisasi kembali.')
                    session.add_all(replays)
                created += len(replays)
            return {'created': created, 'training_dates': len(self.training_dates)}

    def available_dates(self, model):
        """Hanya tanggal dengan hasil tersimpan; tidak menjalankan model melalui GET."""
        with self.sessions() as session:
            snapshot = self.active(session)
            items = {day: {'date': day, 'origin': origin, 'in_training_set': day in self.training_dates}
                for day, origin in session.execute(select(Prediction.date, Prediction.origin).where(
                    Prediction.snapshot_id == snapshot.id, Prediction.model == model))}
            for day, payload in session.execute(select(HistoricalReplay.date, HistoricalReplay.payload).where(
                    HistoricalReplay.snapshot_id == snapshot.id, HistoricalReplay.model == model)):
                items.setdefault(day, {'date': day, 'origin': payload['origin'], 'in_training_set': day in self.training_dates})
            meta = self.store.entries[model]['metadata']
            return {'items': [items[d] for d in sorted(items)], 'total': len(items),
                    'default_date': max(items) if items else None, 'snapshot_version': snapshot.id,
                    'date_start': snapshot.payload['date_start'], 'date_end': snapshot.payload['date_end'],
                    'training_start': meta['training_start'], 'training_end': meta['training_end'],
                    'validation_folds': read_json(self.features.parent / 'targets/split_metadata.json')['validation_folds'],
                    'notice': 'Seluruh tanggal dataset tersedia: simulasi data latih, validation OOF, test, '
                              'jeda purge, inferensi terbaru, dan data tanpa prediksi saat fitur belum lengkap.'}

    def active(self, session):
        snapshot = session.scalar(select(Snapshot).where(Snapshot.active.is_(True)))
        if snapshot is None:
            raise LookupError('Dataset belum dimuat. Jalankan pembaruan snapshot.')
        return snapshot

    def prepare_rows(self):
        expected = read_json(self.features.parent / 'targets/split_metadata.json')
        if sha(self.features) != expected['input_sha256']:
            raise ValueError('Checksum fitur berubah; bangun ulang fitur dan model sebelum sinkronisasi.')
        if self.store.summary['input_hashes']['split_metadata.json'] != sha(self.features.parent / 'targets/split_metadata.json'):
            raise ValueError('Model dan versi dataset belum cocok.')
        rows = csv_rows(self.features)
        if not rows or not set([*RAW, *self.store.feature_names]).issubset(rows[0]):
            raise ValueError('Dataset tidak mempunyai kolom yang dibutuhkan.')
        if any(k.startswith('future_') or k in {'y_t', 'label_end_date'} for k in rows[0]):
            raise ValueError('Masukan inferensi mengandung kolom target masa depan.')
        dates = [r['Date'] for r in rows]
        if dates != sorted(set(dates)):
            raise ValueError('Tanggal harus unik dan terurut.')
        converted = []
        for row in rows:
            date.fromisoformat(row['Date'])
            values = {'Date': row['Date']}
            for name, raw in row.items():
                if name == 'Date':
                    continue
                value = None if raw == '' else float(raw)
                if value is not None and not math.isfinite(value):
                    raise ValueError(f'Nilai tidak finite: {name} {row["Date"]}')
                values[name] = value
            if values['Close'] is None or values['Close'] <= 0:
                raise ValueError('Harga penutupan tidak valid.')
            converted.append(values)
        return converted, sha(self.features)

    def refresh(self):
        if not self.lock.acquire(blocking=False):
            raise RuntimeError('Pembaruan sedang berjalan.')
        started, job_id = now(), str(uuid.uuid4())
        try:
            rows, feature_hash = self.prepare_rows()
            if self.store.test_report['feature_sha256'] != feature_hash:
                raise ValueError('Fitur dashboard berbeda dari evaluasi test.')
            by_date = {r['Date']: r for r in rows}
            positions = {r['Date']: i for i, r in enumerate(rows)}
            snapshot_id = digest([feature_hash, [e['id'] for e in self.store.entries.values()],
                                  sha(TEST_EVALUATION / 'summary.json'), 'full_calendar_v1'])
            stamp = now()
            predictions = []
            catalog = {}
            for name, entry in self.store.entries.items():
                meta, evaluation = entry['metadata'], entry['evaluation']
                lower, upper = meta['thresholds']['T_B'], meta['thresholds']['T_U']
                # Riwayat validation selalu memakai probabilitas out-of-fold tersimpan.
                for saved in csv_rows(entry['validation_file']):
                    row = by_date[saved['Date']]
                    end = positions[row['Date']] + 5
                    if end >= len(rows) or rows[end]['Date'] != saved['label_end_date']:
                        raise ValueError('Kalender validation berbeda dari artefak.')
                    probs = probabilities([float(saved['p_' + label.lower()]) for label in CLASSES])
                    if int(saved['y_pred']) != int(np.argmax(list(probs.values()))):
                        raise ValueError('Label validation berbeda dari probabilitas.')
                    predictions.append(self.make_prediction(name, entry, row, probs, lower, upper, stamp,
                        'validation', saved['label_end_date'], CLASSES[int(saved['y_true'])]))
                # Hasil test tetap berasal dari model development beku, bukan model fold.
                for saved in csv_rows(entry['test_file']):
                    row = by_date[saved['Date']]
                    end = positions[row['Date']] + 5
                    if end >= len(rows) or rows[end]['Date'] != saved['label_end_date']:
                        raise ValueError('Kalender test berbeda dari hasil evaluasi.')
                    probs = probabilities([float(saved['p_' + label.lower()]) for label in CLASSES])
                    if int(saved['y_pred']) != int(np.argmax(list(probs.values()))):
                        raise ValueError('Label prediksi test berbeda dari probabilitas.')
                    predictions.append(self.make_prediction(name, entry, row, probs, lower, upper, stamp,
                        'test', saved['label_end_date'], CLASSES[int(saved['y_true'])]))
                # Hanya lima baris ujung yang belum mempunyai target tersedia.
                for row in rows[-5:]:
                    if row['Date'] <= meta['training_end'] or any(row[c] is None for c in self.store.feature_names):
                        raise ValueError('Tanggal inferensi harus sesudah training dan fitur lengkap.')
                matrix = np.asarray([[row[c] for c in self.store.feature_names] for row in rows[-5:]], dtype=float)
                raw_probs = entry['model'].predict_proba(matrix)
                order = [list(entry['model'].classes_).index(c) for c in [0, 1, 2]]
                for row, values in zip(rows[-5:], raw_probs[:, order]):
                    predictions.append(self.make_prediction(name, entry, row, probabilities(values), lower, upper,
                                                           stamp, 'inference', None, None))
                warning = evaluation['pooled_validation']['warning']
                catalog[name] = {'name': name, 'model_version': entry['id'], 'artifact_run': self.store.run.name,
                    'features': self.store.feature_names, 'thresholds': meta['thresholds'], 'parameters': meta['parameters'],
                    'training_start': meta['training_start'], 'training_end': meta['training_end'],
                    'training_rows': meta['training_rows'], 'summary': evaluation['summary'],
                    'fold_metrics': evaluation['fold_metrics'], 'pooled': evaluation['pooled_validation'],
                    'test_metrics': self.store.test_report['results'][name],
                    'warning': warning, 'mean_far': statistics.mean(f['warning']['false_alarm_rate'] for f in evaluation['fold_metrics']),
                    'importance': sorted([{'feature': c, 'value': float(v)} for c, v in zip(self.store.feature_names, entry['model'].feature_importances_)], key=lambda r: -r['value']),
                    'is_reference': name == self.store.default_model, 'production_ready': False}
            payload = {'version': snapshot_id, 'feature_sha256': feature_hash, 'created_at': stamp,
                'date_start': rows[0]['Date'], 'date_end': rows[-1]['Date'], 'rows': len(rows),
                'default_model': self.store.default_model, 'model_ids': {n: e['id'] for n, e in self.store.entries.items()},
                'models': catalog, 'validation_start': '2019-02-19', 'validation_end': '2022-10-11',
                'validation_rows': 889, 'feature_count': len(self.store.feature_names), 'model_ready': False,
                'feature_file': str(self.features), 'model_package': str(self.store.run),
                'limitations': self.store.summary['limitations'], 'disclaimer': DISCLAIMER,
                'inference_policy': 'Kalender penuh; training, validation OOF, test model beku, dan inferensi dipisahkan.',
                'final_test_evaluated': True,
                'final_test': {'status': 'evaluated', 'start_date': self.store.test_report['start_date'],
                    'end_date': self.store.test_report['end_date'], 'rows': self.store.test_report['rows'],
                    'evaluated_at': self.store.test_report['evaluated_at_utc'],
                    'metrics': self.store.test_report['results'], 'fit_count': 0}}
            # Seluruh snapshot diterbitkan dalam satu transaksi. Versi lama dipertahankan.
            with self.sessions.begin() as session:
                existing = session.get(Snapshot, snapshot_id)
                if existing is None:
                    session.add(Snapshot(id=snapshot_id, active=False, payload=payload))
                    session.add_all([MarketData(snapshot_id=snapshot_id, date=r['Date'], payload=r) for r in rows])
                    for name, item in catalog.items():
                        if session.get(ModelRun, item['model_version']) is None:
                            session.add(ModelRun(id=item['model_version'], payload=item))
                    for pred in predictions:
                        session.add(Prediction(id=digest([snapshot_id, pred['model_name'], pred['data_date'], pred['origin']]),
                            snapshot_id=snapshot_id, date=pred['data_date'], model=pred['model_name'],
                            status=pred['ews_status'], origin=pred['origin'], payload=pred))
                    registry = {'feature_file': str(self.features), 'feature_sha256': feature_hash,
                                'dataset_notes': payload['limitations'], 'sources': SOURCES}
                    session.add(SourceRegistry(id=snapshot_id, payload=registry))
                session.execute(update(Snapshot).values(active=False))
                session.flush()
                session.get(Snapshot, snapshot_id).active = True
                session.add(PipelineRun(id=job_id, payload={'status': 'completed', 'started_at': started,
                    'completed_at': stamp, 'snapshot_id': snapshot_id, 'rows': len(rows),
                    'predictions': len(predictions), 'already_imported': existing is not None}))
            return {'status': 'completed', 'snapshot_id': snapshot_id, 'rows': len(rows),
                    'predictions': len(predictions), 'already_imported': existing is not None}
        except Exception as error:
            with self.sessions.begin() as session:
                session.add(PipelineRun(id=job_id, payload={'status': 'failed', 'started_at': started,
                    'completed_at': now(), 'error': str(error)}))
            raise
        finally:
            self.lock.release()

    def make_prediction(self, name, entry, row, probs, lower, upper, stamp, origin, target_date, actual):
        current = regime(row['ihsg_return_5d'], lower, upper)
        future = max(CLASSES, key=lambda c: probs[c])
        status = ews(current, future)
        return {'data_date': row['Date'], 'prediction_date': row['Date'], 'generated_at': stamp,
            'target_date': target_date, 'target_calendar_status': 'known' if target_date else 'future_calendar_unavailable',
            'horizon_trading_days': 5, 'current_regime': current, 'current_return_5d': row['ihsg_return_5d'],
            'predicted_future_regime': future, 'class_probabilities': probs, 'ews_status': status,
            'explanation': explanation(current, future, status), 'model_name': name,
            'model_version': entry['id'], 'origin': origin, 'actual_future_regime': actual,
            'prediction_available': True, 'evaluation_eligible': origin in {'validation', 'test'},
            'thresholds': {'T_B': lower, 'T_U': upper}, 'feature_values': {c: row[c] for c in self.store.feature_names},
            'market': {c: row[c] for c in RAW if c != 'Date'}}

    def overview(self):
        with self.sessions() as session:
            payload = dict(self.active(session).payload)
            age = (datetime.now(ZoneInfo('Asia/Jakarta')).date() - date.fromisoformat(payload['date_end'])).days
            payload.update(freshness_status='historical' if age > 7 else 'current', data_age_days=age)
            return payload

    def latest_prediction(self, model, day=None):
        with self.sessions() as session:
            snapshot = self.active(session)
            query = select(Prediction).where(Prediction.snapshot_id == snapshot.id, Prediction.model == model)
            if day:
                query = query.where(Prediction.date == day)
            item = session.scalar(query.order_by(Prediction.date.desc()).limit(1))
            if item is None and day:
                replay = session.get(HistoricalReplay, (snapshot.id, model, day))
                if replay is not None:
                    return replay.payload
            if item is None:
                raise LookupError('Tanggal ini belum mempunyai hasil model yang dapat ditampilkan. Pilih dari tanggal penelitian yang tersedia.')
            return item.payload

    def series(self, period='3M', end=None):
        with self.sessions() as session:
            snapshot = self.active(session)
            end = min(end or snapshot.payload['date_end'], snapshot.payload['date_end'])
            endpoint = date.fromisoformat(end)
            start = date(endpoint.year, 1, 1) if period == 'YTD' else endpoint - timedelta(days={'1M':31,'3M':93,'6M':186,'1Y':366,'ALL':10000}[period])
            return [row.payload for row in session.scalars(select(MarketData).where(
                MarketData.snapshot_id == snapshot.id, MarketData.date >= start.isoformat(),
                MarketData.date <= end).order_by(MarketData.date))]

    def history(self, model, start=None, end=None, status=None, origin=None, limit=25, offset=0):
        with self.sessions() as session:
            snapshot = self.active(session)
            conditions = [Prediction.snapshot_id == snapshot.id, Prediction.model == model]
            if start:
                conditions.append(Prediction.date >= start)
            if end:
                conditions.append(Prediction.date <= end)
            if status:
                conditions.append(Prediction.status == status)
            if origin:
                conditions.append(Prediction.origin == origin)
            total = session.scalar(select(func.count()).select_from(Prediction).where(*conditions))
            result = session.scalars(select(Prediction).where(*conditions).order_by(Prediction.date.desc()).offset(offset).limit(limit))
            return {'total': total, 'items': [r.payload for r in result], 'limit': limit, 'offset': offset}
