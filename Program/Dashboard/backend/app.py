"""API baca dashboard; sinkronisasi hanya melalui tindakan POST eksplisit."""
from contextlib import asynccontextmanager
import csv
from datetime import date, datetime, timezone
import hmac
import io
import json
import os
from pathlib import Path
import secrets
from typing import Literal
from uuid import uuid4
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select, text
from .db import Snapshot, SurveyResponse, database
from .domain import CLASSES, ews
from .service import PROGRAM, SOURCES, Service, csv_rows
from .live import LiveMarket
from .live_indicators import IndicatorFeeds
from .domestic import DomesticIndicators

FRONTEND = Path(__file__).resolve().parents[1] / 'frontend/dist'
COMPOUNDLY = Path(__file__).resolve().parents[1] / 'compoundly/dist'
DASHBOARD_DIR = Path(__file__).resolve().parents[1]
Model = Literal['xgboost', 'lightgbm']
Period = Literal['1M', '3M', '6M', '1Y', 'YTD', 'ALL']

SURVEY_SECTIONS = [
    {'id': 'usability', 'title': 'Kemudahan penggunaan', 'items': [
        {'id': 'q01', 'text': 'Navigasi pada sistem EWS IHSG mudah saya pahami.'},
        {'id': 'q02', 'text': 'Saya dapat menemukan halaman dan informasi yang saya perlukan.'},
        {'id': 'q03', 'text': 'Pemilihan tanggal penelitian mudah digunakan.'},
    ]},
    {'id': 'clarity', 'title': 'Kejelasan informasi', 'items': [
        {'id': 'q04', 'text': 'Perbedaan kondisi pasar saat ini dan prediksi lima hari ke depan dijelaskan dengan jelas.'},
        {'id': 'q05', 'text': 'Arti kelas Bearish, Sideways, dan Bullish mudah dipahami.'},
        {'id': 'q06', 'text': 'Grafik, indikator, dan tanggal data disajikan dengan jelas.'},
    ]},
    {'id': 'presentation', 'title': 'Penyajian dan fitur', 'items': [
        {'id': 'q07', 'text': 'Grafik pergerakan IHSG membantu saya memahami perubahan pasar.'},
        {'id': 'q08', 'text': 'Perbandingan kinerja XGBoost dan LightGBM mudah dipahami.'},
        {'id': 'q09', 'text': 'Riwayat prediksi dan filter yang tersedia membantu penelusuran data.'},
    ]},
    {'id': 'usefulness', 'title': 'Manfaat informasi', 'items': [
        {'id': 'q10', 'text': 'Informasi status early warning membantu saya mengenali potensi risiko penurunan pasar.'},
        {'id': 'q11', 'text': 'Informasi pada dashboard bermanfaat untuk memahami kondisi IHSG.'},
        {'id': 'q12', 'text': 'Probabilitas prediksi dan indikator memberikan konteks yang berguna.'},
    ]},
    {'id': 'trust', 'title': 'Kepercayaan dan batasan sistem', 'items': [
        {'id': 'q13', 'text': 'Penjelasan hasil membantu saya memahami dasar informasi yang ditampilkan.'},
        {'id': 'q14', 'text': 'Pembedaan data historis dan informasi live disampaikan dengan jelas.'},
        {'id': 'q15', 'text': 'Keterangan bahwa sistem bukan rekomendasi jual atau beli disampaikan dengan jelas.'},
    ]},
]
LIKERT_OPTIONS = [
    {'value': 1, 'label': 'Sangat tidak setuju'},
    {'value': 2, 'label': 'Tidak setuju'},
    {'value': 3, 'label': 'Netral'},
    {'value': 4, 'label': 'Setuju'},
    {'value': 5, 'label': 'Sangat setuju'},
]
RESPONDENT_TYPES = ['Investor', 'Sekuritas / analis', 'Akademisi / mahasiswa', 'Lainnya']


def ensure_survey_admin_credentials():
    """Ambil kredensial dari environment atau buat pasangan lokal sekali saja."""
    env_username = os.environ.get('SURVEY_ADMIN_USERNAME')
    env_password = os.environ.get('SURVEY_ADMIN_PASSWORD')
    if env_username or env_password:
        if not env_username or not env_password:
            raise RuntimeError('Atur SURVEY_ADMIN_USERNAME dan SURVEY_ADMIN_PASSWORD secara bersamaan.')
        return {'username': env_username, 'password': env_password}
    credentials_path = DASHBOARD_DIR / '.local' / 'survey_admin_credentials.json'
    credentials_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(credentials_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        try:
            credentials = json.loads(credentials_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError('File kredensial admin tidak dapat dibaca. Periksa .local/survey_admin_credentials.json.') from error
        if not credentials.get('username') or not credentials.get('password'):
            raise RuntimeError('File kredensial admin harus berisi username dan password.')
        return credentials
    credentials = {'username': 'admin', 'password': secrets.token_urlsafe(32)}
    with os.fdopen(fd, 'w', encoding='utf-8') as handle:
        json.dump(credentials, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    return credentials


def survey_payload(response):
    payload = {
        'id': response.id,
        'submitted_at': response.created_at,
        'respondent_type': response.respondent_type,
        'answers': response.answers,
        'comment': response.comment or '',
    }
    if response.respondent_name:
        payload['respondent_name'] = response.respondent_name
    if response.respondent_email:
        payload['respondent_email'] = response.respondent_email
    if response.respondent_phone:
        payload['respondent_phone'] = response.respondent_phone
    if response.respondent_age is not None:
        payload['respondent_age'] = response.respondent_age
    return payload


def create_app(database_url=None, store=None, features=None, live_enabled=None, live_fetcher=None, indicator_fetchers=None, domestic_fetchers=None):
    @asynccontextmanager
    async def lifespan(app):
        engine, sessions = database(database_url)
        app.state.sessions = sessions
        app.state.survey_admin_credentials = ensure_survey_admin_credentials()
        options = {'store': store}
        if features is not None:
            options['features'] = features
        app.state.service = Service(sessions, **options)
        # Sinkronisasi idempoten juga diperlukan saat paket model berganti.
        # Transaksi refresh mempertahankan snapshot lama dan jawaban UAT.
        app.state.service.refresh()
        app.state.service.prepare_training_replays()
        enabled = live_enabled if live_enabled is not None else os.environ.get('IHSG_LIVE_ENABLED', '1') != '0'
        live = LiveMarket(sessions, fetcher=live_fetcher, enabled=enabled)
        app.state.live = live
        await live.start()
        indicators = IndicatorFeeds(sessions, enabled=enabled, fetchers=indicator_fetchers)
        app.state.live_indicators = indicators
        await indicators.start()
        domestic = DomesticIndicators(sessions, enabled=enabled, fetchers=domestic_fetchers)
        app.state.domestic = domestic
        await domestic.start()
        try:
            yield
        finally:
            await live.stop()
            await indicators.stop()
            await domestic.stop()
            engine.dispose()

    app = FastAPI(title='EWS IHSG', version='1.0.0', lifespan=lifespan)
    survey_admin_basic = HTTPBasic(auto_error=False)

    def service():
        return app.state.service

    def model_name(model):
        return model or service().store.default_model

    @app.get('/api/v1/health')
    def health():
        with service().sessions() as session:
            session.execute(text('SELECT 1'))
        return {'status': 'ok', 'database': 'connected', 'artifacts': 'loaded',
                'model_production_ready': False}

    @app.get('/api/v1/survey/uat/schema')
    def survey_schema():
        return {
            'title': 'Kuesioner UAT Sistem Early Warning IHSG',
            'description': 'Kuesioner anonim untuk menilai kemudahan, kejelasan, dan manfaat sistem EWS IHSG. Tidak meminta nama atau alamat email. Jawaban digunakan untuk evaluasi penelitian.',
            'consent_text': 'Saya telah mencoba sistem EWS IHSG dan bersedia jawaban anonim saya digunakan untuk evaluasi penelitian.',
            'respondent_types': RESPONDENT_TYPES,
            'likert_options': LIKERT_OPTIONS,
            'sections': SURVEY_SECTIONS,
            'question_count': sum(len(section['items']) for section in SURVEY_SECTIONS),
        }

    @app.post('/api/v1/survey/uat', status_code=201)
    async def submit_survey(request: Request):
        try:
            body = await request.json()
        except Exception as error:
            raise HTTPException(400, 'Isi kuesioner tidak terbaca.') from error
        if not isinstance(body, dict) or body.get('consent') is not True:
            raise HTTPException(422, 'Persetujuan penggunaan jawaban anonim wajib diberikan.')
        respondent_type = body.get('respondent_type', 'Umum') or 'Umum'
        if respondent_type not in RESPONDENT_TYPES:
            respondent_type = 'Umum'

        # Validasi dan ambil data kontak responden
        respondent_name = (body.get('respondent_name') or '').strip()
        respondent_email = (body.get('respondent_email') or '').strip()
        respondent_phone = (body.get('respondent_phone') or '').strip()
        respondent_age_raw = body.get('respondent_age')
        respondent_age = int(respondent_age_raw) if respondent_age_raw is not None and str(respondent_age_raw).isdigit() else (int(respondent_age_raw) if isinstance(respondent_age_raw, int) else None)
        if not respondent_name:
            raise HTTPException(422, 'Nama lengkap wajib diisi.')
        if not respondent_email or '@' not in respondent_email:
            raise HTTPException(422, 'Alamat email tidak valid.')
        if len(respondent_name) > 120:
            raise HTTPException(422, 'Nama maksimal 120 karakter.')
        if len(respondent_email) > 254:
            raise HTTPException(422, 'Email maksimal 254 karakter.')
        if len(respondent_phone) > 20:
            raise HTTPException(422, 'Nomor telepon maksimal 20 karakter.')
        if respondent_age is not None and not (10 <= respondent_age <= 99):
            raise HTTPException(422, 'Umur harus antara 10 dan 99 tahun.')

        answers = body.get('answers')
        required_ids = {item['id'] for section in SURVEY_SECTIONS for item in section['items']}
        if not isinstance(answers, dict) or set(answers) != required_ids:
            raise HTTPException(422, 'Semua pernyataan wajib dijawab.')
        if any(type(value) is not int or value not in range(1, 6) for value in answers.values()):
            raise HTTPException(422, 'Jawaban harus menggunakan skala 1 sampai 5.')
        comment = body.get('comment', '')
        if not isinstance(comment, str) or len(comment) > 1200:
            raise HTTPException(422, 'Komentar maksimal 1.200 karakter.')
        row = SurveyResponse(
            id=str(uuid4()),
            created_at=datetime.now(timezone.utc).isoformat(),
            respondent_type=respondent_type,
            answers=answers,
            comment=comment.strip(),
            respondent_name=respondent_name or None,
            respondent_email=respondent_email or None,
            respondent_phone=respondent_phone or None,
            respondent_age=respondent_age,
        )
        with app.state.sessions.begin() as session:
            session.add(row)
        return {'id': row.id, 'message': 'Terima kasih. Jawaban Anda berhasil disimpan.'}

    def require_survey_admin(credentials: HTTPBasicCredentials | None = Depends(survey_admin_basic)):
        expected = getattr(app.state, 'survey_admin_credentials', None)
        if not expected or not credentials:
            raise HTTPException(401, 'Username atau password admin belum dimasukkan.', headers={'WWW-Authenticate': 'Basic'})
        valid_username = hmac.compare_digest(credentials.username, expected['username'])
        valid_password = hmac.compare_digest(credentials.password, expected['password'])
        if not (valid_username and valid_password):
            raise HTTPException(401, 'Username atau password admin salah.', headers={'WWW-Authenticate': 'Basic'})

    def get_survey_summary():
        with app.state.sessions() as session:
            rows = session.scalars(select(SurveyResponse).order_by(SurveyResponse.created_at.asc())).all()
        count = len(rows)
        items = [item for section in SURVEY_SECTIONS for item in section['items']]
        question_summary = {}
        for item in items:
            values = [row.answers[item['id']] for row in rows if item['id'] in row.answers]
            question_summary[item['id']] = {
                'count': len(values),
                'mean': round(sum(values) / len(values), 2) if values else None,
                'distribution': {str(value): sum(answer == value for answer in values) for value in range(1, 6)},
            }
        section_summary = []
        for section in SURVEY_SECTIONS:
            means = [question_summary[item['id']]['mean'] for item in section['items'] if question_summary[item['id']]['mean'] is not None]
            section_summary.append({'id': section['id'], 'title': section['title'],
                'mean': round(sum(means) / len(means), 2) if means else None})
        scores = [value for row in rows for value in row.answers.values()]
        roles = {role: sum(row.respondent_type == role for row in rows) for role in RESPONDENT_TYPES}
        return {'response_count': count, 'overall_mean': round(sum(scores) / len(scores), 2) if scores else None,
            'respondent_types': roles, 'sections': section_summary, 'questions': question_summary,
            'likert_options': LIKERT_OPTIONS}

    def get_survey_responses(limit: int = 500, offset: int = 0):
        with app.state.sessions() as session:
            total = session.scalar(select(func.count()).select_from(SurveyResponse)) or 0
            rows = session.scalars(select(SurveyResponse).order_by(SurveyResponse.created_at.desc()).offset(offset).limit(limit)).all()
        return {'total': total, 'items': [survey_payload(row) for row in rows]}

    def get_survey_csv():
        with app.state.sessions() as session:
            rows = session.scalars(select(SurveyResponse).order_by(SurveyResponse.created_at.asc())).all()
        stream = io.StringIO(newline='')
        writer = csv.writer(stream)
        items = [item for section in SURVEY_SECTIONS for item in section['items']]
        writer.writerow([
            'submitted_at', 'respondent_type',
            'nama', 'email', 'no_telepon', 'umur',
            *[item['id'] for item in items], 'comment',
        ])
        for row in rows:
            writer.writerow([
                row.created_at, row.respondent_type,
                row.respondent_name or '', row.respondent_email or '', row.respondent_phone or '',
                row.respondent_age if row.respondent_age is not None else '',
                *[row.answers.get(item['id'], '') for item in items],
                row.comment or '',
            ])
        return Response('\ufeff' + stream.getvalue(), media_type='text/csv; charset=utf-8',
            headers={'Content-Disposition': 'attachment; filename="ews_ihsg_uat_responses.csv"'})

    @app.get('/api/v1/survey/summary')
    def survey_summary():
        return get_survey_summary()

    @app.get('/api/v1/survey/admin/summary')
    def survey_admin_summary(_=Depends(require_survey_admin)):
        return get_survey_summary()

    @app.get('/api/v1/survey/responses')
    def survey_responses(limit: int = Query(500, ge=1, le=500), offset: int = Query(0, ge=0, le=100000)):
        return get_survey_responses(limit, offset)

    @app.get('/api/v1/survey/admin/responses')
    def survey_admin_responses(
        limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0, le=100000),
        _=Depends(require_survey_admin),
    ):
        return get_survey_responses(limit, offset)

    @app.get('/api/v1/survey/export.csv')
    def survey_export():
        return get_survey_csv()

    @app.get('/api/v1/survey/admin/export.csv')
    def survey_admin_export(_=Depends(require_survey_admin)):
        return get_survey_csv()

    @app.get('/api/v1/meta')
    def metadata():
        return service().overview()

    @app.get('/api/v1/market/latest')
    def market_latest():
        pred = service().latest_prediction(service().store.default_model)
        return {'data_date': pred['data_date'], **pred['market'],
                'return_1d': pred['feature_values']['ihsg_return_1d'],
                'current_return_5d': pred['current_return_5d'], 'current_regime': pred['current_regime']}

    @app.get('/api/v1/market/live')
    def live_market():
        # Membaca cache; jumlah pengunjung tidak menambah request ke Yahoo.
        return app.state.live.snapshot()

    @app.get('/api/v1/market/live/indicators')
    def live_indicators():
        return app.state.live_indicators.snapshot()

    @app.get('/api/v1/market/live/domestic')
    def domestic_indicators():
        return app.state.domestic.snapshot()

    @app.get('/api/v1/market/series')
    def series(period: Period = '3M', end_date: date | None = None):
        return {'items': service().series(period, end_date.isoformat() if end_date else None)}

    @app.get('/api/v1/predictions/latest')
    def prediction(model: Model | None = None, data_date: date | None = None):
        try:
            return service().latest_prediction(model_name(model), data_date.isoformat() if data_date else None)
        except LookupError as error:
            raise HTTPException(404, str(error)) from error

    @app.get('/api/v1/predictions/dates')
    def prediction_dates(model: Model | None = None):
        return service().available_dates(model_name(model))

    @app.get('/api/v1/predictions')
    def history(model: Model | None = None, start_date: date | None = None, end_date: date | None = None,
                status: Literal['Stable', 'Caution', 'Warning'] | None = None,
                origin: Literal['validation', 'test', 'inference'] | None = None,
                limit: int = Query(25, ge=1, le=200), offset: int = Query(0, ge=0, le=10000)):
        if start_date and end_date and start_date > end_date:
            raise HTTPException(422, 'Tanggal awal harus mendahului tanggal akhir.')
        return service().history(model_name(model), start_date.isoformat() if start_date else None,
            end_date.isoformat() if end_date else None, status, origin, limit, offset)

    @app.get('/api/v1/history.csv')
    def export(model: Model | None = None, start_date: date | None = None, end_date: date | None = None,
               status: Literal['Stable', 'Caution', 'Warning'] | None = None,
               origin: Literal['validation', 'test', 'inference'] | None = None):
        if start_date and end_date and start_date > end_date:
            raise HTTPException(422, 'Tanggal awal harus mendahului tanggal akhir.')
        rows = service().history(model_name(model), start_date.isoformat() if start_date else None,
            end_date.isoformat() if end_date else None, status, origin, 10000, 0)['items']
        stream = io.StringIO(newline='')
        writer = csv.writer(stream)
        writer.writerow(['Date','Model','Origin','CurrentRegime','PredictedFutureRegime','EWS',
                         'BearishProbability','SidewaysProbability','BullishProbability','TargetDate','ModelVersion'])
        for r in rows:
            writer.writerow([r['data_date'],r['model_name'],r['origin'],r['current_regime'],
                r['predicted_future_regime'],r['ews_status'],*[r['class_probabilities'][c] for c in CLASSES],
                r['target_date'] or '',r['model_version']])
        return Response('\ufeff' + stream.getvalue(), media_type='text/csv; charset=utf-8',
                        headers={'Content-Disposition': f'attachment; filename="ihsg_predictions_{model_name(model)}.csv"'})

    @app.get('/api/v1/indicators')
    def indicators(period: Period = '3M', end_date: date | None = None):
        rows = service().series(period, end_date.isoformat() if end_date else None)
        return {'items': rows, 'sources': {key: {'label': value[0], 'unit': value[1], 'provider': value[2],
            'url': value[3], 'source_observation_date': None,
            'availability_note': 'Tanggal pada grafik mengikuti penyelarasan preprocessing. Tanggal observasi asal dan jam rilis setiap nilai belum diverifikasi penuh.'}
            for key, value in SOURCES.items()}}

    @app.get('/api/v1/models/performance')
    def performance():
        meta = service().overview()
        return {'stage': 'validation', 'start_date': meta['validation_start'], 'end_date': meta['validation_end'],
            'rows': meta['validation_rows'], 'reference_model': meta['default_model'],
            'models': list(meta['models'].values()), 'final_test': meta['final_test'],
            'reference_selection': 'Macro F1 validation, toleransi 0,001, lalu simpangan baku lebih kecil dan accuracy lebih tinggi; hanya referensi tampilan eksperimen.'}

    @app.get('/api/v1/models/experiments')
    def experiments():
        path = PROGRAM / 'Training/runs/inflation_release_20261028/leaderboard.csv'
        return {'items': csv_rows(path) if path.exists() else [], 'stage': 'validation_inflation_comparison',
                'active_variant': 'change_15'}

    @app.get('/api/v1/ews/rules')
    def rules():
        return {'items': [{'current': c, 'future': f, 'status': ews(c, f)} for c in CLASSES for f in CLASSES]}

    @app.post('/api/v1/pipeline/refresh')
    def refresh():
        try:
            result = service().refresh()
            result['historical_replays'] = service().prepare_training_replays()
            return result
        except RuntimeError as error:
            raise HTTPException(409, str(error)) from error
        except (ValueError, OSError, KeyError) as error:
            raise HTTPException(400, str(error)) from error

    # Aplikasi terpisah menjaga CSS dan komponen Compoundly tetap seperti aslinya.
    if (COMPOUNDLY / 'index.html').exists():
        app.mount('/compoundly-app', StaticFiles(directory=COMPOUNDLY, html=True), name='compoundly')

    if (FRONTEND / 'assets').exists():
        app.mount('/assets', StaticFiles(directory=FRONTEND / 'assets'), name='assets')

    @app.get('/{path:path}', include_in_schema=False)
    def frontend(path: str):
        if path == 'compoundly-app' or path.startswith('compoundly-app/'):
            raise HTTPException(503, 'Compoundly belum dibangun. Jalankan npm run build di folder compoundly, lalu restart dashboard.')
        if path.startswith('api/'):
            raise HTTPException(404, 'Endpoint tidak ditemukan.')
        if path == 'icon.svg' and (FRONTEND / path).exists():
            return FileResponse(FRONTEND / path)
        if not (FRONTEND / 'index.html').exists():
            raise HTTPException(503, 'Frontend belum dibangun. Jalankan npm run build di frontend.')
        return FileResponse(FRONTEND / 'index.html', headers={'Cache-Control': 'no-cache'})

    return app


app = create_app()
