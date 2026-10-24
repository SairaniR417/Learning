"""Port of the supplied Ghost rider v.2 Pine signal/level state machine.

The seven-vote dashboard is separate from entry logic and is not reproduced
without synchronized 5-minute RSI. Target hits include the signal candle,
exactly as in the supplied script; they are observations, not filled trades.
"""
from datetime import datetime, timezone
from math import isfinite
from zoneinfo import ZoneInfo

from scanner.strategies.base import BaseStrategy, StrategyMetadata, StrategyParameter
from services.market_sync import nse_daily_closed


def ema(values, period):
    result = []
    for value in values:
        result.append(value if not result else result[-1] + 2 / (period + 1) * (value - result[-1]))
    return result


def atr14(rows):
    result, seed, previous = [], [], None
    for i, row in enumerate(rows):
        tr = row['high'] - row['low'] if i == 0 else max(row['high'] - row['low'], abs(row['high'] - rows[i-1]['close']), abs(row['low'] - rows[i-1]['close']))
        if previous is None:
            seed.append(tr)
            if len(seed) == 14:
                previous = sum(seed) / 14
        else:
            previous = (previous * 13 + tr) / 14
        result.append(previous)
    return result


class GhostRiderStrategy(BaseStrategy):
    metadata = StrategyMetadata(
        id='ghost_rider', name='Ghost rider v.2', min_candles=2,
        description='Ghost rider v.2: EMA 9/21 crossover, signal-close entry, ATR 14 stop and TP1–TP5 at 1–5R. Latest setup remains until the opposite cross; NEW means a cross on the latest completed candle. Target hits include the signal candle. Uses the shared Pine v2 calculations on stored daily, hourly, 15m or 5m candles. Dashboard 5m RSI is available when matching stored 5m history exists.',
        parameters=[StrategyParameter(name='atr_multiplier', display_name='SL ATR Multiplier', type='float', default=1.5, min_value=0.1)],
    )

    def candle_window(self, params):
        return 1000

    def run(self, df, instruments_map, params):
        from services.ghost_scanner import completed_rows, scan_row, TIMEFRAMES
        if df.is_empty():
            return []
        multiplier = params.get('atr_multiplier', 1.5)
        timeframe = params.get('_timeframe', '1d')
        if timeframe not in TIMEFRAMES:
            raise ValueError('Unsupported Ghost Rider timeframe')
        if isinstance(multiplier, bool) or not isinstance(multiplier, (int, float)) or not isfinite(multiplier) or multiplier < .1:
            raise ValueError('SL ATR Multiplier must be at least 0.1 and finite')
        results = []
        for group in df.sort(['instrument_key', 'timestamp']).partition_by('instrument_key', maintain_order=True):
            key = group['instrument_key'][0]
            metadata = instruments_map.get(key)
            if not metadata:
                continue
            rows = completed_rows(group.to_dicts(), timeframe)
            if len(rows) < 2:
                continue
            if any(not all(isinstance(r[k],(int,float)) and isfinite(r[k]) and r[k]>0 for k in ('open','high','low','close'))
                   or not r['low']<=min(r['open'],r['close'])<=max(r['open'],r['close'])<=r['high'] for r in rows):
                continue
            five = completed_rows(params.get('_five_minute_rows', {}).get(key, []), '5m')
            row = scan_row(rows, five, metadata, timeframe, multiplier)
            if row:
                results.append(row)
        return sorted(results, key=lambda r:(r['ageBars'],r['symbol']))
