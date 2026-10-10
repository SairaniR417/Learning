"""EMA / SMA Bullish Alignment Strategy."""

from typing import Any
import polars as pl
from scanner.strategies.base import BaseStrategy, StrategyMetadata, StrategyParameter


class EmaAlignmentStrategy(BaseStrategy):
    """Scan for candle close above EMA 9, EMA 20, SMA 50, and SMA 200."""

    metadata = StrategyMetadata(
        id="ema_sma_alignment",
        name="EMA & SMA Bullish Alignment",
        category="Trend Following",
        description="Identifies stocks where close is trading above EMA 9, EMA 20, SMA 50, and SMA 200.",
        default_timeframe="1d",
        min_candles=200,
        parameters=[
            StrategyParameter(name="ema1", display_name="Fast EMA Period", type="int", default=9, min_value=3, max_value=50),
            StrategyParameter(name="ema2", display_name="Medium EMA Period", type="int", default=20, min_value=5, max_value=100),
            StrategyParameter(name="sma1", display_name="Intermediate SMA Period", type="int", default=50, min_value=20, max_value=200),
            StrategyParameter(name="sma2", display_name="Long Term SMA Period", type="int", default=200, min_value=50, max_value=500),
        ],
    )

    def run(
        self,
        df: pl.DataFrame,
        instruments_map: dict[str, dict[str, Any]],
        params: dict[str, Any],
        include_unmatched: bool = False,
        include_insufficient_history: bool = False,
    ) -> list[dict[str, Any]]:
        if df.is_empty():
            return []

        ema1_period = int(params.get("ema1", 9))
        ema2_period = int(params.get("ema2", 20))
        sma1_period = int(params.get("sma1", 50))
        sma2_period = int(params.get("sma2", 200))

        # Vectorized technical indicator calculations over each stock series
        calc_df = df.with_columns(
            [
                pl.col("close").ewm_mean(span=ema1_period).over("instrument_key").alias("ema_fast"),
                pl.col("close").ewm_mean(span=ema2_period).over("instrument_key").alias("ema_med"),
                pl.col("close").rolling_mean(window_size=sma1_period).over("instrument_key").alias("sma_inter"),
                pl.col("close").rolling_mean(window_size=sma2_period).over("instrument_key").alias("sma_long"),
            ]
        ).with_columns(
            [
                (
                    (pl.col("close") > pl.col("ema_fast"))
                    & (pl.col("close") > pl.col("ema_med"))
                    & (pl.col("close") > pl.col("sma_inter"))
                    & (pl.col("close") > pl.col("sma_long"))
                ).alias("is_match")
            ]
        ).with_columns(
            [
                pl.col("is_match").shift(1).over("instrument_key").alias("prev_match"),
                pl.col("close").shift(1).over("instrument_key").alias("prev_close"),
                pl.len().over("instrument_key").alias("candle_count"),
            ]
        )

        # Filter latest candle for each symbol
        minimum_history = 1 if include_insufficient_history else self.metadata.min_candles
        latest_df = (calc_df.group_by("instrument_key").last().filter(
            (pl.col("candle_count") >= minimum_history) & (pl.lit(include_unmatched) | pl.col("is_match"))))

        matches = []
        for row in latest_df.iter_rows(named=True):
            key = row["instrument_key"]
            meta = instruments_map.get(key, {})
            symbol = meta.get("symbol") or key
            name = meta.get("name") or symbol
            exchange = meta.get("exchange") or "NSE"

            is_new = row["prev_match"] is False
            previous_close = row["prev_close"]
            change_pct = ((row["close"] - previous_close) / previous_close * 100) if previous_close else None
            matches.append(
                {
                    "symbol": symbol,
                    "name": name,
                    "instrumentKey": key,
                    "exchange": exchange,
                    "close": round(row["close"], 2),
                    "previousClose": round(previous_close, 2) if previous_close is not None else None,
                    "changePct": round(change_pct, 2) if change_pct is not None else None,
                    "ema9": round(row["ema_fast"], 2) if row["ema_fast"] is not None else None,
                    "ema20": round(row["ema_med"], 2) if row["ema_med"] is not None else None,
                    "sma50": round(row["sma_inter"], 2) if row["sma_inter"] is not None else None,
                    "sma200": round(row["sma_long"], 2) if row["sma_long"] is not None else None,
                    "volume": row["volume"],
                    "status": ("NEWLY_ALIGNED" if is_new else "ALIGNED") if row["is_match"] else "NOT_ALIGNED",
                    "matchedSince": row["timestamp"].isoformat() if hasattr(row["timestamp"], "isoformat") else str(row["timestamp"]),
                    "candlesAnalyzed": row["candle_count"],
                    "historySufficient": row["candle_count"] >= self.metadata.min_candles,
                }
            )

        matches.sort(key=lambda item: (item["status"] != "NEWLY_ALIGNED", item["symbol"]))
        return matches
