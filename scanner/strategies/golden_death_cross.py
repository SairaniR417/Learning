"""Golden Cross / Death Cross strategy with delayed confirmation."""

from datetime import datetime
from typing import Any

import polars as pl

from scanner.strategies.base import BaseStrategy, StrategyMetadata, StrategyParameter


class GoldenDeathCrossStrategy(BaseStrategy):
    """Detect SMA 50/200 crosses and require six confirmations."""

    metadata = StrategyMetadata(
        id="golden_death_cross",
        name="Golden Cross / Death Cross",
        category="Trend Following",
        description=(
            "Scans for SMA 50/200 crosses confirmed by EMA alignment, price, "
            "trend slope, RSI, relative volume, and a 20-candle breakout or breakdown."
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
            StrategyParameter(name="bearish_rsi", display_name="Bearish RSI Maximum", type="float", default=45.0, min_value=0, max_value=100),
            StrategyParameter(name="volume_lookback", display_name="Volume Average Period", type="int", default=20, min_value=2, max_value=100),
            StrategyParameter(name="volume_multiplier", display_name="Relative Volume Minimum", type="float", default=1.5, min_value=0.1, max_value=10),
            StrategyParameter(name="breakout_lookback", display_name="Breakout Lookback", type="int", default=20, min_value=2, max_value=100),
            StrategyParameter(name="slope_lookback", display_name="Trend Slope Lookback", type="int", default=5, min_value=1, max_value=50),
            StrategyParameter(name="max_confirmation_bars", display_name="Confirmation Window (bars)", type="int", default=30, min_value=0, max_value=200),
        ],
    )

    @staticmethod
    def _ema(values: list[float], period: int) -> list[float | None]:
        alpha = 2.0 / (period + 1.0)
        result: list[float | None] = [None] * len(values)
        current = values[0] if values else 0.0
        for i, value in enumerate(values):
            current = value if i == 0 else alpha * value + (1.0 - alpha) * current
            if i >= period - 1:
                result[i] = current
        return result

    @staticmethod
    def _sma(values: list[float], period: int) -> list[float | None]:
        result: list[float | None] = [None] * len(values)
        running = 0.0
        for i, value in enumerate(values):
            running += value
            if i >= period:
                running -= values[i - period]
            if i >= period - 1:
                result[i] = running / period
        return result

    @staticmethod
    def _rsi(values: list[float], period: int) -> list[float | None]:
        result: list[float | None] = [None] * len(values)
        if len(values) <= period:
            return result
        gains = [max(values[i] - values[i - 1], 0.0) for i in range(1, len(values))]
        losses = [max(values[i - 1] - values[i], 0.0) for i in range(1, len(values))]
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        def value(gain: float, loss: float) -> float:
            if gain == 0 and loss == 0:
                return 50.0
            if loss == 0:
                return 100.0
            if gain == 0:
                return 0.0
            return 100.0 - 100.0 / (1.0 + gain / loss)

        result[period] = value(avg_gain, avg_loss)
        for i in range(period + 1, len(values)):
            avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
            result[i] = value(avg_gain, avg_loss)
        return result

    @staticmethod
    def _timestamp(value: Any) -> str:
        return value.isoformat() if hasattr(value, "isoformat") else str(value)

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
        bearish_rsi = float(params.get("bearish_rsi", 45))
        volume_lookback = int(params.get("volume_lookback", 20))
        volume_multiplier = float(params.get("volume_multiplier", 1.5))
        breakout_lookback = int(params.get("breakout_lookback", 20))
        slope_lookback = int(params.get("slope_lookback", 5))
        max_confirmation_bars = int(params.get("max_confirmation_bars", 30))
        if fast >= slow or medium >= long:
            raise ValueError("Fast EMA must be shorter than slow EMA; medium SMA must be shorter than long SMA.")

        warmup = max(250, long + slope_lookback, rsi_period + 1, volume_lookback + 1, breakout_lookback + 1)
        matches: list[dict[str, Any]] = []

        for group in df.partition_by("instrument_key", maintain_order=True):
            rows = group.sort("timestamp").iter_rows(named=True)
            candles = list(rows)
            if len(candles) <= warmup:
                continue
            close = [float(row["close"]) for row in candles]
            high = [float(row["high"]) for row in candles]
            low = [float(row["low"]) for row in candles]
            volume = [float(row["volume"] or 0) for row in candles]
            ema_fast = self._ema(close, fast)
            ema_slow = self._ema(close, slow)
            sma_medium = self._sma(close, medium)
            sma_long = self._sma(close, long)
            rsi = self._rsi(close, rsi_period)

            direction: str | None = None
            cross_index: int | None = None
            cross_time: Any = None
            confirmation_time: Any = None
            emitted = False
            current_checks: dict[str, bool] = {}
            current_count = 0
            current_state = "NEUTRAL"
            current_signal: str | None = None
            current_index = len(candles) - 1

            for i in range(warmup, len(candles)):
                s50, s200 = sma_medium[i], sma_long[i]
                prev50, prev200 = sma_medium[i - 1], sma_long[i - 1]
                if s50 is None or s200 is None or prev50 is None or prev200 is None:
                    continue
                golden = prev50 <= prev200 and s50 > s200
                death = prev50 >= prev200 and s50 < s200
                if golden or death:
                    direction = "BUY" if golden else "SELL"
                    cross_index = i
                    cross_time = candles[i]["timestamp"]
                    confirmation_time = None
                    emitted = False

                if direction is None or cross_index is None:
                    current_state = "NEUTRAL"
                    current_signal = None
                    continue

                elapsed = i - cross_index
                if not emitted and elapsed > max_confirmation_bars:
                    current_state = "EXPIRED"
                    current_signal = None
                    direction = None
                    cross_index = None
                    continue

                ef, es, rsi_value = ema_fast[i], ema_slow[i], rsi[i]
                if ef is None or es is None or rsi_value is None:
                    continue
                prev_s50 = sma_medium[i - slope_lookback] if i >= slope_lookback else None
                prev_s200 = sma_long[i - slope_lookback] if i >= slope_lookback else None
                prior_volumes = volume[i - volume_lookback:i]
                average_volume = sum(prior_volumes) / volume_lookback if len(prior_volumes) == volume_lookback else 0.0
                prior_highs = high[i - breakout_lookback:i]
                prior_lows = low[i - breakout_lookback:i]
                resistance = max(prior_highs) if len(prior_highs) == breakout_lookback else None
                support = min(prior_lows) if len(prior_lows) == breakout_lookback else None

                if direction == "BUY":
                    checks = {
                        "MA alignment · EMA 9 > EMA 20 > SMA 50 > SMA 200": ef > es > s50 > s200,
                        "Price · Close > EMA 9 and EMA 20": close[i] > ef and close[i] > es,
                        "Trend · SMA 50 and SMA 200 rising": prev_s50 is not None and prev_s200 is not None and s50 > prev_s50 and s200 > prev_s200,
                        f"RSI {rsi_value:.1f} > {bullish_rsi:g}": rsi_value > bullish_rsi,
                        f"Volume · {volume[i]:g} ≥ {volume_multiplier:g}× prior average": average_volume > 0 and volume[i] >= volume_multiplier * average_volume,
                        f"Breakout · Close > prior {breakout_lookback}-bar high": resistance is not None and close[i] > resistance,
                    }
                else:
                    checks = {
                        "MA alignment · EMA 9 < EMA 20 < SMA 50 < SMA 200": ef < es < s50 < s200,
                        "Price · Close < EMA 9 and EMA 20": close[i] < ef and close[i] < es,
                        "Trend · SMA 50 and SMA 200 falling": prev_s50 is not None and prev_s200 is not None and s50 < prev_s50 and s200 < prev_s200,
                        f"RSI {rsi_value:.1f} < {bearish_rsi:g}": rsi_value < bearish_rsi,
                        f"Volume · {volume[i]:g} ≥ {volume_multiplier:g}× prior average": average_volume > 0 and volume[i] >= volume_multiplier * average_volume,
                        f"Breakdown · Close < prior {breakout_lookback}-bar low": support is not None and close[i] < support,
                    }

                passed = sum(checks.values())
                current_checks = checks
                current_count = passed
                if emitted:
                    current_state = "CONFIRMED_ACTIVE" if passed == len(checks) else "CONFIRMED_WEAKENED"
                    current_signal = direction
                elif passed == len(checks):
                    emitted = True
                    confirmation_time = candles[i]["timestamp"]
                    current_state = "CONFIRMED"
                    current_signal = direction
                else:
                    current_state = "WATCH"
                    current_signal = None

            if current_state not in {"WATCH", "CONFIRMED", "CONFIRMED_ACTIVE", "CONFIRMED_WEAKENED"}:
                continue
            last = candles[current_index]
            key = last["instrument_key"]
            meta = instruments_map.get(key, {})
            prev_close = close[current_index - 1] if current_index > 0 else None
            change_pct = (close[current_index] - prev_close) / prev_close * 100 if prev_close else None
            index = current_index
            metrics = {"ema9": ema_fast[index], "ema20": ema_slow[index], "sma50": sma_medium[index], "sma200": sma_long[index], "rsi": rsi[index]}
            matches.append({
                "symbol": meta.get("symbol") or key,
                "name": meta.get("name") or meta.get("symbol") or key,
                "instrumentKey": key,
                "exchange": meta.get("exchange") or "NSE",
                "close": round(close[index], 2),
                "previousClose": round(prev_close, 2) if prev_close is not None else None,
                "changePct": round(change_pct, 2) if change_pct is not None else None,
                "ema9": round(metrics["ema9"], 2) if metrics["ema9"] is not None else None,
                "ema20": round(metrics["ema20"], 2) if metrics["ema20"] is not None else None,
                "sma50": round(metrics["sma50"], 2) if metrics["sma50"] is not None else None,
                "sma200": round(metrics["sma200"], 2) if metrics["sma200"] is not None else None,
                "rsi": round(metrics["rsi"], 2) if metrics["rsi"] is not None else None,
                "volume": int(volume[index]),
                "status": current_signal or "WATCH",
                "signal": current_signal,
                "state": current_state,
                "crossType": "GOLDEN_CROSS" if direction == "BUY" else "DEATH_CROSS",
                "crossTime": self._timestamp(cross_time) if cross_time is not None else None,
                "confirmationTime": self._timestamp(confirmation_time) if confirmation_time is not None else None,
                "barsSinceCross": current_index - cross_index if cross_index is not None else None,
                "confirmationCount": current_count,
                "confirmationChecks": current_checks,
                "candlesAnalyzed": len(candles),
            })

        matches.sort(key=lambda item: (item["status"] != "BUY", item["status"] != "SELL", item["symbol"]))
        return matches
