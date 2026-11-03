"""Penyimpanan snapshot berversi; job gagal tidak mengganti snapshot aktif."""
import getpass
import os
from datetime import datetime, timezone
from urllib.parse import quote
from sqlalchemy import Boolean, Integer, JSON, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

DEFAULT_URL = f'postgresql+psycopg://{quote(getpass.getuser())}@127.0.0.1:55432/ihsg_ews'


class Base(DeclarativeBase):
    pass


class Snapshot(Base):
    __tablename__ = 'dataset_snapshots'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    payload: Mapped[dict] = mapped_column(JSON)


class MarketData(Base):
    __tablename__ = 'market_data'
    snapshot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    date: Mapped[str] = mapped_column(String(10), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)


class ModelRun(Base):
    __tablename__ = 'model_runs'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)


class Prediction(Base):
    __tablename__ = 'predictions'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(String(64), index=True)
    date: Mapped[str] = mapped_column(String(10), index=True)
    model: Mapped[str] = mapped_column(String(16), index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    origin: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict] = mapped_column(JSON)


class SourceRegistry(Base):
    __tablename__ = 'raw_data_registry'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)


class PipelineRun(Base):
    __tablename__ = 'pipeline_runs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[str] = mapped_column(String(40), default=lambda: datetime.now(timezone.utc).isoformat())
    payload: Mapped[dict] = mapped_column(JSON)


class LiveMarketState(Base):
    """Cache intraday terpisah; tidak mengubah snapshot data penelitian."""
    __tablename__ = 'live_market_state'
    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)


class PublishedIndicatorState(Base):
    """Cache publikasi domestik, dengan periode referensi terpisah dari waktu cek."""
    __tablename__ = 'published_indicator_state'
    key: Mapped[str] = mapped_column(String(24), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)


class HistoricalReplay(Base):
    """Simulasi pada data pelatihan, terpisah dari riwayat evaluasi OOF."""
    __tablename__ = 'historical_replays'
    snapshot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    model: Mapped[str] = mapped_column(String(16), primary_key=True)
    date: Mapped[str] = mapped_column(String(10), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)


class SurveyResponse(Base):
    """Jawaban UAT untuk kuesioner skala Likert; kontak investor bersifat opsional."""
    __tablename__ = 'uat_survey_responses'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[str] = mapped_column(String(40), index=True)
    respondent_type: Mapped[str] = mapped_column(String(32), index=True)
    answers: Mapped[dict] = mapped_column(JSON)
    comment: Mapped[str] = mapped_column(String(1200), default='')
    # Kolom kontak khusus investor (nullable untuk tipe responden lain)
    respondent_name: Mapped[str | None] = mapped_column(String(120), nullable=True, default=None)
    respondent_email: Mapped[str | None] = mapped_column(String(254), nullable=True, default=None)
    respondent_phone: Mapped[str | None] = mapped_column(String(20), nullable=True, default=None)
    respondent_age: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)


def database(url=None):
    url = url or os.environ.get('DATABASE_URL', DEFAULT_URL)
    options = {'connect_args': {'check_same_thread': False}} if url.startswith('sqlite') else {}
    if url in {'sqlite://', 'sqlite:///:memory:'}:
        options['poolclass'] = StaticPool
    engine = create_engine(url, pool_pre_ping=True, **options)
    Base.metadata.create_all(engine)
    return engine, sessionmaker(engine, expire_on_commit=False)
