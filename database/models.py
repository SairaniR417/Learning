"""SQLAlchemy mappings for PostgreSQL market data and the scan cache."""
from datetime import datetime, timezone
from sqlalchemy import (
    BigInteger, Boolean, Column, Date, DateTime, ForeignKey, Index, Integer,
    Numeric, PrimaryKeyConstraint, String, Text, UniqueConstraint, Float,
)
from sqlalchemy.orm import synonym
from database.connection import Base

BIGINT_PK = BigInteger().with_variant(Integer, "sqlite")

class Instrument(Base):
    __tablename__ = "instruments"
    id = Column(BIGINT_PK, primary_key=True, autoincrement=True)
    symbol = Column(String(100), nullable=False, index=True)
    exchange = Column(String(20), nullable=False, default="NSE")
    instrument_type = Column(String(30))
    provider_instrument_key = Column(Text)
    instrument_key = synonym("provider_instrument_key")
    expiry_date = Column(Date)
    is_active = Column(Boolean, default=True, nullable=False)
    __table_args__ = (UniqueConstraint("exchange", "provider_instrument_key"),)

class MarketCandle(Base):
    __tablename__ = "candles"
    id = Column(BIGINT_PK, primary_key=True, autoincrement=True)
    instrument_id = Column(BIGINT_PK, ForeignKey("instruments.id"), nullable=False)
    timeframe = Column(String(10), nullable=False)
    candle_time = Column(DateTime(timezone=True), nullable=False)
    timestamp = synonym("candle_time")
    open = Column(Numeric(18, 6), nullable=False)
    high = Column(Numeric(18, 6), nullable=False)
    low = Column(Numeric(18, 6), nullable=False)
    close = Column(Numeric(18, 6), nullable=False)
    volume = Column(BigInteger, default=0, nullable=False)
    open_interest = Column(BigInteger)
    __table_args__ = (
        UniqueConstraint("instrument_id", "timeframe", "candle_time"),
        Index("idx_candles_lookup", "instrument_id", "timeframe", "candle_time"),
    )

class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"
    id = Column(BIGINT_PK, primary_key=True, autoincrement=True)
    instrument_id = Column(BIGINT_PK, ForeignKey("instruments.id"))
    timeframe = Column(String(10), nullable=False)
    start_time = Column(DateTime(timezone=True))
    end_time = Column(DateTime(timezone=True))
    status = Column(String(20), default="pending")
    last_error = Column(Text)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class DataCoverage(Base):
    __tablename__ = "data_coverage"
    id = Column(BIGINT_PK, primary_key=True, autoincrement=True)
    instrument_id = Column(BIGINT_PK, ForeignKey("instruments.id"), nullable=False)
    timeframe = Column(String(10), nullable=False)
    earliest_candle = Column(DateTime(timezone=True))
    latest_candle = Column(DateTime(timezone=True))
    last_checked_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    __table_args__ = (UniqueConstraint("instrument_id", "timeframe"),)

class StrategyCache(Base):
    __tablename__ = "strategy_cache"
    cache_key = Column(String(128), primary_key=True)
    strategy_id = Column(String(64), index=True, nullable=False)
    timeframe = Column(String(16), nullable=False)
    params_json = Column(Text, nullable=False)
    results_json = Column(Text, nullable=False)
    total_scanned = Column(Integer, default=0, nullable=False)
    total_matched = Column(Integer, default=0, nullable=False)
    scanned_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime(timezone=True), nullable=False)

class CandleRevision(Base):
    __tablename__ = "candle_revisions"
    timeframe = Column(String(16), primary_key=True)
    revision = Column(BigInteger, nullable=False, default=0)


class JournalTrade(Base):
    __tablename__ = "journal_trades"
    id = Column(Integer, primary_key=True, autoincrement=True)
    content_json = Column(Text, nullable=False)
    import_key = Column(String(64), unique=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class UserWatchlist(Base):
    __tablename__ = "user_watchlists"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(80), nullable=False)
    content_json = Column(Text, nullable=False, default='{"sections":["Stocks"],"entries":[]}')


class PriceAlert(Base):
    __tablename__ = "price_alerts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    instrument_key = Column(Text, nullable=False)
    symbol = Column(String(100), nullable=False)
    name = Column(String(200), nullable=False)
    exchange = Column(String(30), nullable=False)
    condition = Column(String(20), nullable=False)
    target = Column(Float, nullable=False)
    active = Column(Boolean, nullable=False, default=True)
    last_price = Column(Float)
    triggered_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class AlertNotification(Base):
    __tablename__ = "alert_notifications"
    id = Column(Integer, primary_key=True, autoincrement=True)
    alert_id = Column(Integer, nullable=False, unique=True)
    instrument_key = Column(Text, nullable=False)
    symbol = Column(String(100), nullable=False)
    name = Column(String(200), nullable=False)
    exchange = Column(String(30), nullable=False)
    message = Column(Text, nullable=False)
    price = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    read = Column(Boolean, nullable=False, default=False)
