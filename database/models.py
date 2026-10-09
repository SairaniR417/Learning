"""SQLAlchemy time-series and strategy models."""

from datetime import datetime, timezone
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
)
from database.connection import Base


class Instrument(Base):
    """NSE equity and market instrument registry."""

    __tablename__ = "instruments"

    instrument_key = Column(String(64), primary_key=True, index=True)
    symbol = Column(String(32), index=True, nullable=False)
    name = Column(String(256), nullable=False)
    exchange = Column(String(16), default="NSE", nullable=False)
    segment = Column(String(16), default="NSE_EQ", nullable=False)
    isin = Column(String(32), nullable=True)
    instrument_type = Column(String(16), default="EQ", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class MarketCandle(Base):
    """Multi-timeframe OHLCV historical and intraday candle store."""

    __tablename__ = "market_candles"

    instrument_key = Column(String(64), nullable=False)
    timeframe = Column(String(16), nullable=False)  # '1d', '1m', '5m', '15m', '1h'
    timestamp = Column(DateTime(timezone=True), nullable=False)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(BigInteger, default=0, nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("instrument_key", "timeframe", "timestamp"),
        Index("idx_candles_lookup", "timeframe", "instrument_key", "timestamp"),
        Index("idx_candles_time_range", "timeframe", "timestamp"),
    )


class StrategyCache(Base):
    """Shared cache for scan results serving 100+ concurrent enterprise users."""

    __tablename__ = "strategy_cache"

    cache_key = Column(String(128), primary_key=True)  # strategy_id:timeframe:hash(params)
    strategy_id = Column(String(64), index=True, nullable=False)
    timeframe = Column(String(16), nullable=False)
    params_json = Column(Text, nullable=False)
    results_json = Column(Text, nullable=False)
    total_scanned = Column(Integer, default=0, nullable=False)
    total_matched = Column(Integer, default=0, nullable=False)
    scanned_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime(timezone=True), nullable=False)


class CandleRevision(Base):
    """Monotonic data version for each stored timeframe."""
    __tablename__ = "candle_revisions"
    timeframe = Column(String(16), primary_key=True)
    revision = Column(BigInteger, nullable=False, default=0)
