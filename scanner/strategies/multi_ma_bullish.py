"""Multi moving-average bullish confirmation scanner."""

from typing import Any

import polars as pl

from scanner.strategies.base import BaseStrategy, StrategyMetadata, StrategyParameter


class MultiMovingAverageBullishStrategy(BaseStrategy):
    """Classify bullish stages and require confirmation before calling a stock bullish."""

    metadata = StrategyMetadata(
        id="multi_ma_bullish",
        name="Multi-MA Bullish Confirmation",
        category="Trend Following",
        description=(
            "Classifies early momentum, bullish watch, confirmed bullish, strong bullish, "
            "and bearish-warning setups using EMA 9/20, SMA 50/200, price, trend, RSI, and volume."
        ),
        default_timeframe="1d",
        min_candles=250,
        parameters=[
            StrategyParameter(name="ema_fast", display_name="Fast EMA Period", type="int", default=9, min_value=2, max_value=50),
            StrategyParameter(name="ema_slow", display_name="Slow EMA Period", type="int", default=20, min_value=3, max_value=100),
            StrategyParameter(name="sma_medium", display_name="Medium SMA Period", type="int", default=50, min_value=10, max_value=200),
            StrategyParameter(name="sma_long", display_name="Long SMA Period", type="int", default=200, min_value=50, max_value=500),
            StrategyParameter(name="rsi_period", display_name="RSI Period", type="int", default=14, min_value=2, max_value=50),
            StrategyParameter(name="bullish_rsi", display_name="Bullish RSI Minimum", type="float", default=55.0, min_value=0, max_value=100),
            StrategyParameter(name="early_rsi", display_name="Early Bullish RSI Minimum", type="float", default=50.0, min_value=0, max_value=100),
            StrategyParameter(name="volume_lookback", display_name="Volume Average Period", type="int", default=20, min_value=2, max_value=100),
            StrategyParameter(name="volume_multiplier", display_name="Relative Volume Minimum", type="float", default=1.5, min_value=0.1, max_value=10),
            StrategyParameter(name="breakout_lookback", display_name="Breakout Lookback", type="int", default=20, min_value=2, max_value=100),
            StrategyParameter(name="slope_lookback", display_name="Trend Slope Lookback", type="int", default=5, min_value=1, max_value=50),
        ],
    )

    def candle_window(self, params: dict[str, Any]) -> int:
        """Fetch enough bars for indicators and the previous completed signal state."""
        medium = int(params.get("sma_medium", 50))
        long = int(params.get("sma_long", 200))
        slow_ema = int(params.get("ema_slow", 20))
        rsi_period = int(params.get("rsi_period", 14))
        volume_lookback = int(params.get("volume_lookback", 20))
        breakout_lookback = int(params.get("breakout_lookback", 20))
        slope_lookback = int(params.get("slope_lookback", 5))
        return max(
            self.metadata.min_candles,
            long + slope_lookback + 2,
            medium + slope_lookback + 2,
            slow_ema * 5,
            rsi_period * 3,
            volume_lookback + 2,
            breakout_lookback + 2,
        )

    def run(
        self,
        df: pl.DataFrame,
        instruments_map: dict[str, dict[str, Any]],
        params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if df.is_empty():
            return []

        fast = int(params.get("ema_fast", 9))
        slow = int(params.get("ema_slow", 20))
        medium = int(params.get("sma_medium", 50))
        long = int(params.get("sma_long", 200))
        rsi_period = int(params.get("rsi_period", 14))
        bullish_rsi = float(params.get("bullish_rsi", 55))
        early_rsi = float(params.get("early_rsi", 50))
        volume_lookback = int(params.get("volume_lookback", 20))
        volume_multiplier = float(params.get("volume_multiplier", 1.5))
        breakout_lookback = int(params.get("breakout_lookback", 20))
        slope_lookback = int(params.get("slope_lookback", 5))
        if not fast < slow or not medium < long:
            raise ValueError("Fast EMA must be shorter than slow EMA; medium SMA must be shorter than long SMA.")

        key = "instrument_key"
        ordered = df.sort([key, "timestamp"])
        expressions = [
            pl.col("close").ewm_mean(span=fast, adjust=False).over(key).alias("ema9"),
            pl.col("close").ewm_mean(span=slow, adjust=False).over(key).alias("ema20"),
            pl.col("close").rolling_mean(window_size=medium).over(key).alias("sma50"),
            pl.col("close").rolling_mean(window_size=long).over(key).alias("sma200"),
            pl.col("close").shift(1).over(key).alias("previous_close"),
            pl.col("volume").shift(1).rolling_mean(window_size=volume_lookback).over(key).alias("average_volume"),
            pl.col("high").shift(1).rolling_max(window_size=breakout_lookback).over(key).alias("previous_resistance"),
            pl.col("low").shift(1).rolling_min(window_size=breakout_lookback).over(key).alias("previous_support"),
            pl.col("close").diff().over(key).alias("price_delta"),
            pl.len().over(key).alias("candle_count"),
        ]
        calculated = ordered.with_columns(expressions).with_columns(
            [
                pl.when(pl.col("price_delta") > 0).then(pl.col("price_delta")).otherwise(0.0).alias("gain"),
                pl.when(pl.col("price_delta") < 0).then(-pl.col("price_delta")).otherwise(0.0).alias("loss"),
            ]
        ).with_columns(
            [
                pl.col("gain").ewm_mean(span=2 * rsi_period - 1, adjust=False).over(key).alias("average_gain"),
                pl.col("loss").ewm_mean(span=2 * rsi_period - 1, adjust=False).over(key).alias("average_loss"),
                pl.col("ema9").shift(1).over(key).alias("previous_ema9"),
                pl.col("ema20").shift(1).over(key).alias("previous_ema20"),
                pl.col("sma50").shift(1).over(key).alias("previous_sma50"),
                pl.col("sma50").shift(slope_lookback).over(key).alias("sma50_slope_base"),
                pl.col("sma200").shift(slope_lookback).over(key).alias("sma200_slope_base"),
            ]
        ).with_columns(
            (100.0 - 100.0 / (1.0 + pl.col("average_gain") / (pl.col("average_loss") + 1e-12))).alias("rsi")
        ).with_columns(
            [
                (
                    (pl.col("ema9") > pl.col("ema20"))
                    & (pl.col("ema20") > pl.col("sma50"))
                    & (pl.col("sma50") > pl.col("sma200"))
                    & (pl.col("close") > pl.col("ema9"))
                    & (pl.col("close") > pl.col("ema20"))
                    & (pl.col("sma50") > pl.col("sma50").shift(slope_lookback).over(key))
                    & (pl.col("sma200") > pl.col("sma200").shift(slope_lookback).over(key))
                    & (pl.col("rsi") > bullish_rsi)
                    & (pl.col("volume") >= pl.col("average_volume") * volume_multiplier)
                ).alias("bullish_confirmed"),
                (
                    (pl.col("close") > pl.col("high").shift(1).rolling_max(window_size=breakout_lookback).over(key))
                ).alias("breakout_confirmed"),
            ]
        ).with_columns(
            (pl.col("bullish_confirmed") & pl.col("breakout_confirmed")).alias("strong_bullish")
        ).with_columns(
            [
                pl.col("bullish_confirmed").shift(1).over(key).alias("previous_bullish_confirmed"),
                pl.col("strong_bullish").shift(1).over(key).alias("previous_strong_bullish"),
            ]
        ).with_columns(
            [
                pl.when(pl.col("bullish_confirmed") & ~pl.col("previous_bullish_confirmed").fill_null(False))
                .then(pl.col("timestamp")).otherwise(None).alias("bullish_event"),
                pl.when(pl.col("strong_bullish") & ~pl.col("previous_strong_bullish").fill_null(False))
                .then(pl.col("timestamp")).otherwise(None).alias("strong_event"),
            ]
        ).with_columns(
            [
                pl.col("bullish_event").forward_fill().over(key).alias("bullish_event_since"),
                pl.col("strong_event").forward_fill().over(key).alias("strong_event_since"),
            ]
        )

        latest = calculated.group_by(key, maintain_order=True).last()
        results: list[dict[str, Any]] = []
        for row in latest.iter_rows(named=True):
            instrument_key = row[key]
            meta = instruments_map.get(instrument_key, {})
            history = int(row["candle_count"] or 0)
            if history < self.metadata.min_candles:
                classification = "INSUFFICIENT_HISTORY"
                checks: dict[str, bool] = {}
            else:
                close = float(row["close"])
                ema9, ema20 = float(row["ema9"]), float(row["ema20"])
                sma50, sma200 = float(row["sma50"]), float(row["sma200"])
                rsi = float(row["rsi"])
                average_volume = float(row["average_volume"] or 0)
                volume = float(row["volume"] or 0)
                checks = {
                    f"MA alignment · EMA {fast} > EMA {slow} > SMA {medium} > SMA {long}": ema9 > ema20 > sma50 > sma200,
                    f"Price · Close > EMA {fast} and EMA {slow}": close > ema9 and close > ema20,
                    f"Trend · SMA {medium} and SMA {long} rising": row["sma50_slope_base"] is not None and row["sma200_slope_base"] is not None and sma50 > float(row["sma50_slope_base"]) and sma200 > float(row["sma200_slope_base"]),
                    f"RSI {rsi:.1f} > {bullish_rsi:g}": rsi > bullish_rsi,
                    f"Volume · {volume:g} ≥ {volume_multiplier:g}× prior average": average_volume > 0 and volume >= average_volume * volume_multiplier,
                }
                bullish_confirmed = all(checks.values())
                strong_bullish = bullish_confirmed and row["previous_resistance"] is not None and close > float(row["previous_resistance"])
                crossed_up = row["previous_ema9"] is not None and row["previous_ema20"] is not None and float(row["previous_ema9"]) <= float(row["previous_ema20"]) and ema9 > ema20
                crossed_down = row["previous_ema9"] is not None and row["previous_ema20"] is not None and float(row["previous_ema9"]) >= float(row["previous_ema20"]) and ema9 < ema20
                bullish_watch = ema9 > ema20 > sma50 and sma50 < sma200
                if strong_bullish:
                    classification = "STRONG_BULLISH_ACTIVE" if row["previous_strong_bullish"] else "STRONG_BULLISH"
                elif bullish_confirmed:
                    classification = "CONFIRMED_BULLISH_ACTIVE" if row["previous_bullish_confirmed"] else "CONFIRMED_BULLISH"
                elif crossed_up and rsi > early_rsi:
                    classification = "EARLY_BULLISH"
                elif bullish_watch:
                    classification = "BULLISH_WATCH"
                elif crossed_down:
                    classification = "BEARISH_WARNING"
                else:
                    classification = "NEUTRAL"

            previous_close = row["previous_close"]
            close_value = float(row["close"])
            change_pct = (close_value - float(previous_close)) / float(previous_close) * 100 if previous_close else None
            values = {"ema9": row["ema9"], "ema20": row["ema20"], "sma50": row["sma50"], "sma200": row["sma200"], "rsi": row["rsi"]}
            average_volume = float(row["average_volume"] or 0)
            volume = float(row["volume"] or 0)
            results.append({
                "symbol": meta.get("symbol") or instrument_key,
                "name": meta.get("name") or meta.get("symbol") or instrument_key,
                "instrumentKey": instrument_key,
                "exchange": meta.get("exchange") or "NSE",
                "close": round(close_value, 2),
                "previousClose": round(float(previous_close), 2) if previous_close is not None else None,
                "changePct": round(change_pct, 2) if change_pct is not None else None,
                "ema9": round(float(values["ema9"]), 2) if values["ema9"] is not None else None,
                "ema20": round(float(values["ema20"]), 2) if values["ema20"] is not None else None,
                "sma50": round(float(values["sma50"]), 2) if values["sma50"] is not None else None,
                "sma200": round(float(values["sma200"]), 2) if values["sma200"] is not None else None,
                "rsi": round(float(values["rsi"]), 2) if values["rsi"] is not None else None,
                "emaFastPeriod": fast,
                "emaSlowPeriod": slow,
                "smaMediumPeriod": medium,
                "smaLongPeriod": long,
                "volume": int(volume),
                "averageVolume": round(average_volume, 2),
                "volumeRatio": round(volume / average_volume, 2) if average_volume > 0 else None,
                "classification": classification,
                "status": classification,
                "state": "ACTIVE" if classification.endswith("_ACTIVE") else classification,
                "signal": "BUY" if classification.startswith(("CONFIRMED_BULLISH", "STRONG_BULLISH")) else None,
                "confirmationChecks": checks,
                "confirmationCount": sum(checks.values()),
                "confirmationTotal": 5,
                "signalSince": (
                    row["strong_event_since"] if classification.startswith("STRONG_BULLISH")
                    else row["bullish_event_since"] if classification.startswith("CONFIRMED_BULLISH")
                    else None
                ).isoformat() if classification.startswith(("STRONG_BULLISH", "CONFIRMED_BULLISH")) and row["strong_event_since" if classification.startswith("STRONG_BULLISH") else "bullish_event_since"] is not None else None,
                "candlesAnalyzed": history,
                "breakout": row["previous_resistance"] is not None and close_value > float(row["previous_resistance"]),
                "breakoutCheck": bool(row["previous_resistance"] is not None and close_value > float(row["previous_resistance"])),
                "breakoutDescription": f"Breakout · Close > prior {breakout_lookback}-bar high",
                "support": round(float(row["previous_support"]), 2) if row["previous_support"] is not None else None,
                "resistance": round(float(row["previous_resistance"]), 2) if row["previous_resistance"] is not None else None,
                "matchedSince": row["timestamp"].isoformat() if hasattr(row["timestamp"], "isoformat") else str(row["timestamp"]),
            })

        results.sort(key=lambda item: (not item["status"].startswith("STRONG_BULLISH"), not item["status"].startswith("CONFIRMED_BULLISH"), item["status"], item["symbol"]))
        return results
