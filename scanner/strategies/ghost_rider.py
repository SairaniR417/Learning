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
        id='ghost_rider', name='Ghost Rider', min_candles=250,
        description='Ghost rider v.2: EMA 9/21 crossover, signal-close entry, ATR 14 stop and TP1–TP5 at 1–5R. Latest setup remains until the opposite cross; NEW means a cross on the latest completed candle. Target hits include the signal candle. Uses up to 1,000 stored candles; the separate 5-minute score dashboard is unavailable.',
        parameters=[StrategyParameter(name='atr_multiplier', display_name='SL ATR multiplier', type='float', default=1.5, min_value=0.1, max_value=20)],
    )

    def candle_window(self, params):
        return 1000

    def run(self, df, instruments_map, params):
        if df.is_empty():
            return []
        multiplier = params.get('atr_multiplier', 1.5)
        if not isinstance(multiplier, (int, float)) or not isfinite(multiplier) or multiplier <= 0:
            raise ValueError('ATR multiplier must be positive and finite')
        now = datetime.now(timezone.utc)
        india = ZoneInfo('Asia/Kolkata')
        results = []
        for group in df.sort(['instrument_key', 'timestamp']).partition_by('instrument_key', maintain_order=True):
            raw = group.to_dicts()
            key = raw[0]['instrument_key']
            instrument = instruments_map.get(key)
            if not instrument:
                continue
            # Daily only: today's bar is eligible after the NSE close buffer.
            rows = [r for r in raw if params.get('_timeframe', '1d') != '1d' or
                    (nse_daily_closed(r['timestamp'], now) if instrument.get('exchange') == 'NSE' else r['timestamp'].astimezone(india).date() < now.astimezone(india).date())]
            if len(rows) < self.metadata.min_candles:
                continue
            if any(not all(isinstance(r[k], (int, float)) and isfinite(r[k]) and r[k] > 0 for k in ('open', 'high', 'low', 'close')) or not r['low'] <= min(r['open'], r['close']) <= max(r['open'], r['close']) <= r['high'] for r in rows):
                continue
            closes = [r['close'] for r in rows]
            fast, slow, atr = ema(closes, 9), ema(closes, 21), atr14(rows)
            setup, state = None, 0
            for i in range(1, len(rows)):
                buy = fast[i] > slow[i] and fast[i-1] <= slow[i-1] and state <= 0
                sell = fast[i] < slow[i] and fast[i-1] >= slow[i-1] and state >= 0
                if buy or sell:
                    state = 1 if buy else -1
                    if atr[i] is None:
                        setup = None
                        continue
                    risk = atr[i] * multiplier
                    setup = dict(entry=closes[i], stopLoss=closes[i] - state * risk, risk=risk,
                                 signal='BUY' if buy else 'SELL', signalAt=rows[i]['timestamp'].isoformat(),
                                 signal_index=i, atrAtSignal=atr[i], stopTouched=False)
                    for n in range(1, 6):
                        setup[f'tp{n}'] = closes[i] + state * risk * n
                        setup[f'tp{n}Hit'] = False
                if setup:
                    setup['stopTouched'] |= rows[i]['low'] <= setup['stopLoss'] if state == 1 else rows[i]['high'] >= setup['stopLoss']
                    for n in range(1, 6):
                        setup[f'tp{n}Hit'] |= rows[i]['high'] >= setup[f'tp{n}'] if state == 1 else rows[i]['low'] <= setup[f'tp{n}']
            if not setup:
                continue
            age = len(rows) - 1 - setup.pop('signal_index')
            results.append(dict(**setup, instrumentKey=key, symbol=instrument.get('symbol', key), name=instrument.get('name', ''),
                                exchange=instrument.get('exchange', 'NSE'), close=closes[-1], volume=rows[-1].get('volume', 0),
                                changePct=(closes[-1] / closes[-2] - 1) * 100, status=setup['signal'], state='NEW' if age == 0 else 'WAIT',
                                ageBars=age, asOf=rows[-1]['timestamp'].isoformat(), ema9=fast[-1], ema21=slow[-1], atr=atr[-1],
                                strategyId='ghost_rider', candlesAnalyzed=len(rows)))
        return sorted(results, key=lambda r: (r['ageBars'], r['symbol']))
