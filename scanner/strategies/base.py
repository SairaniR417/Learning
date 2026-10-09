"""Base Strategy interface and metadata schemas for pluggable scanning engine."""

from abc import ABC, abstractmethod
from typing import Any, Literal
from pydantic import BaseModel, Field
import polars as pl


class StrategyParameter(BaseModel):
    """Configurable parameter definition for a strategy."""

    name: str
    display_name: str
    type: Literal["int", "float", "bool", "str"]
    default: Any
    min_value: float | None = None
    max_value: float | None = None
    description: str = ""


class StrategyMetadata(BaseModel):
    """Descriptor metadata for strategy registry and UI display."""

    id: str
    name: str
    category: str = "Trend Following"  # "Trend Following", "Momentum", "Breakout", "Mean Reversion"
    description: str
    default_timeframe: str = "1d"  # e.g., "1d", "1m", "5m", "15m", "1h"
    min_candles: int = 200
    parameters: list[StrategyParameter] = Field(default_factory=list)


class BaseStrategy(ABC):
    """Abstract Base Class for all custom quantitative scanning strategies."""

    metadata: StrategyMetadata

    @abstractmethod
    def run(
        self,
        df: pl.DataFrame,
        instruments_map: dict[str, dict[str, Any]],
        params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """
        Execute strategy logic against a vectorized multi-symbol Polars DataFrame.

        :param df: Polars DataFrame containing OHLCV records:
                   [instrument_key, timestamp, open, high, low, close, volume]
        :param instruments_map: Lookup map of instrument_key -> instrument metadata (symbol, name, exchange)
        :param params: User-specified or default parameters for the strategy
        :return: List of matched stock dictionaries with signal metrics
        """
        pass
