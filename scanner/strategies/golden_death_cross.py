"""Classic Golden/Death Cross scan using the shared chart calculation."""

from datetime import datetime
from typing import Any

import polars as pl

from scanner.strategies.base import BaseStrategy, StrategyMetadata, StrategyParameter


class GoldenDeathCrossStrategy(BaseStrategy):
    """Detect SMA crosses, with optional six-filter confirmation."""

    metadata = StrategyMetadata(
        id="golden_death_cross",
        name="Golden Cross / Death Cross",
        category="Trend Following",
        description=(
            "Classic SMA 50/200 Golden and Death crosses. Optional six-filter confirmation; "
            "chart shows both moving averages and historical crosses."
        ),
        default_timeframe="1d",
        min_candles=201,
        parameters=[
            StrategyParameter(name="require_confirmation",display_name="Require six-filter confirmation",type="bool",default=False),
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
            StrategyParameter(name="max_confirmation_bars", display_name="Recent Cross / Confirmation Window (bars)", type="int", default=30, min_value=0, max_value=200),
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

    def candle_window(self,params):
        return 1000

    def run(self,df,instruments_map,params):
        from services.golden_cross import calculate,scan_row
        from services.ghost_scanner import completed_rows,TIMEFRAMES
        if df.is_empty(): return []
        settings={k:v for k,v in params.items() if not k.startswith('_')}
        matches=[]
        for group in df.sort(['instrument_key','timestamp']).partition_by('instrument_key',maintain_order=True):
            key=group['instrument_key'][0]
            rows=group.to_dicts()
            timeframe=params.get('_timeframe')
            if timeframe in TIMEFRAMES: rows=completed_rows(rows,timeframe)
            if not rows: continue
            overlay=calculate(rows,settings)
            match=scan_row(overlay,rows,key,instruments_map.get(key,{}))
            if match: matches.append(match)
        return sorted(matches,key=lambda r:(r['status']!='BUY',r['status']!='SELL',r['symbol']))
