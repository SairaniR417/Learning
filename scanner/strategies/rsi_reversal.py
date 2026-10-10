"""RSI Momentum and Oversold/Overbought Reversal Strategy."""

from typing import Any
import polars as pl
from scanner.strategies.base import BaseStrategy, StrategyMetadata, StrategyParameter


class RsiStrategy(BaseStrategy):
    """Scan for RSI oversold recovery or bullish momentum cross."""

    metadata = StrategyMetadata(
        id="rsi_reversal",
        name="RSI Oversold Bounce",
        category="Mean Reversion",
        description="Scans for stocks recovering from oversold RSI levels (e.g. RSI crossing above 30).",
        default_timeframe="1d",
        min_candles=30,
        parameters=[
            StrategyParameter(name="period", display_name="RSI Period", type="int", default=14, min_value=2, max_value=50),
            StrategyParameter(name="oversold", display_name="Oversold Level", type="float", default=30.0, min_value=10.0, max_value=50.0),
        ],
    )

    def run(
        self,
        df: pl.DataFrame,
        instruments_map: dict[str, dict[str, Any]],
        params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if df.is_empty():
            return []

        period = int(params.get("period", 14))
        oversold = float(params.get("oversold", 30.0))

        # Calculate price delta
        delta_df = df.with_columns(
            [
                (pl.col("close") - pl.col("close").shift(1)).over("instrument_key").alias("diff"),
                pl.col("close").shift(1).over("instrument_key").alias("prev_close"),
            ]
        ).with_columns(
            [
                pl.when(pl.col("diff") > 0).then(pl.col("diff")).otherwise(0.0).alias("gain"),
                pl.when(pl.col("diff") < 0).then(-pl.col("diff")).otherwise(0.0).alias("loss"),
            ]
        ).with_columns(
            [
                pl.col("gain").ewm_mean(span=period).over("instrument_key").alias("avg_gain"),
                pl.col("loss").ewm_mean(span=period).over("instrument_key").alias("avg_loss"),
            ]
        ).with_columns(
            [
                (
                    100.0 - (100.0 / (1.0 + (pl.col("avg_gain") / (pl.col("avg_loss") + 1e-10))))
                ).alias("rsi")
            ]
        ).with_columns(
            [
                pl.col("rsi").shift(1).over("instrument_key").alias("prev_rsi"),
                pl.len().over("instrument_key").alias("candle_count"),
            ]
        )

        latest_df = (
            delta_df.group_by("instrument_key")
            .last()
            .filter(
                (pl.col("candle_count") >= self.metadata.min_candles)
                & (pl.col("rsi") >= oversold)
                & (pl.col("prev_rsi") < oversold)
            )
        )

        matches = []
        for row in latest_df.iter_rows(named=True):
            key = row["instrument_key"]
            meta = instruments_map.get(key, {})
            previous_close = row["prev_close"]
            change_pct = ((row["close"] - previous_close) / previous_close * 100) if previous_close else None
            matches.append(
                {
                    "symbol": meta.get("symbol") or key,
                    "name": meta.get("name") or key,
                    "instrumentKey": key,
                    "exchange": meta.get("exchange") or "NSE",
                    "close": round(row["close"], 2),
                    "previousClose": round(previous_close, 2) if previous_close is not None else None,
                    "changePct": round(change_pct, 2) if change_pct is not None else None,
                    "rsi": round(row["rsi"], 2),
                    "prevRsi": round(row["prev_rsi"], 2) if row["prev_rsi"] else None,
                    "volume": row["volume"],
                    "status": "OVERSOLD_REVERSAL",
                    "matchedSince": row["timestamp"].isoformat() if hasattr(row["timestamp"], "isoformat") else str(row["timestamp"]),
                    "candlesAnalyzed": row["candle_count"],
                }
            )

        matches.sort(key=lambda item: item["symbol"])
        return matches
