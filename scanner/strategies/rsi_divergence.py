"""Causal price-pivot RSI divergences. Detection time is pivot + right bars.

RSI is sampled at price pivots, not independently paired oscillator pivots.
This convention is deliberate and shared by the scanner and event study.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any
from zoneinfo import ZoneInfo

import polars as pl

from scanner.strategies.base import BaseStrategy, StrategyMetadata, StrategyParameter
from scanner.strategies.golden_death_cross import GoldenDeathCrossStrategy
from services.market_sync import nse_daily_closed


@dataclass(frozen=True)
class DivergenceConfig:
    period: int = 14
    pivot_bars: int = 3
    min_gap: int = 5
    max_gap: int = 60
    min_rsi_delta: float = 3.0
    min_price_pct: float = 0.5
    trend_period: int = 50
    max_wait: int = 20
    freshness: int = 5

    @classmethod
    def resolve(cls, params):
        config = cls(**{k: v for k, v in params.items() if k in cls.__dataclass_fields__})
        if config.min_gap > config.max_gap:
            raise ValueError("Minimum pivot separation cannot exceed maximum separation")
        return config


def stamp(value):
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()
    return str(value)


def valid_segments(rows):
    """Reset at bad OHLC, duplicate times, >25% close jumps or >10-day gaps.

    Large changes may be corporate actions or genuine moves: do not guess an
    adjustment. New segments need their own warm-up; never bridge them.
    """
    segment = []
    for index, row in enumerate(rows):
        values = [row.get(k) for k in ('open', 'high', 'low', 'close')]
        valid = all(isinstance(v, (int, float)) and isfinite(v) and v > 0 for v in values)
        if valid:
            o, h, l, c = values
            valid = l <= min(o, c) <= max(o, c) <= h
        if not valid:
            if segment:
                yield segment
            segment = []
            continue
        if segment:
            previous = segment[-1][1]
            delta = row['timestamp'] - previous['timestamp']
            if delta.total_seconds() <= 0 or delta.days > 10 or abs(row['close'] / previous['close'] - 1) > .25:
                yield segment
                segment = []
        segment.append((index, row))
    if segment:
        yield segment


def divergence_kind(first_price, second_price, first_rsi, second_rsi, low, config, trend):
    change = (second_price / first_price - 1) * 100
    delta = second_rsi - first_rsi
    if low and change <= -config.min_price_pct and delta >= config.min_rsi_delta:
        return 'REGULAR_BULLISH'
    if not low and change >= config.min_price_pct and delta <= -config.min_rsi_delta:
        return 'REGULAR_BEARISH'
    if low and change >= config.min_price_pct and delta <= -config.min_rsi_delta and trend == 'UP':
        return 'HIDDEN_BULLISH'
    if not low and change <= -config.min_price_pct and delta >= config.min_rsi_delta and trend == 'DOWN':
        return 'HIDDEN_BEARISH'
    return None


def detect_events(rows, config=DivergenceConfig()):
    """Emit immutable pattern evidence and first causal confirmation/invalidation.

    Strict extrema exclude equal-price plateaus. Compare consecutive price
    pivots only; no picking the best prior pivot retrospectively.
    """
    events = []
    for indexed in valid_segments(rows):
        data = [row for _, row in indexed]
        warmup = max(250, config.period * 5, config.trend_period + 5)
        if len(data) < warmup:
            continue
        close = [r['close'] for r in data]
        rsi = GoldenDeathCrossStrategy._rsi(close, config.period)
        prefix = [0.0]
        for value in close:
            prefix.append(prefix[-1] + value)
        def sma(i):
            return (prefix[i + 1] - prefix[i + 1 - config.trend_period]) / config.trend_period if i >= config.trend_period - 1 else None
        previous_pivot = {True: None, False: None}
        width = config.pivot_bars
        for p2 in range(max(width, warmup), len(data) - width):
            known = p2 + width
            for low in (True, False):
                field = 'low' if low else 'high'
                value = data[p2][field]
                neighbours = [data[j][field] for j in range(p2 - width, p2 + width + 1) if j != p2]
                if not (value < min(neighbours) if low else value > max(neighbours)):
                    continue
                p1 = previous_pivot[low]
                previous_pivot[low] = p2
                if p1 is None or not config.min_gap <= p2 - p1 <= config.max_gap:
                    continue
                ma, old_ma = sma(p2), sma(p2 - 5)
                trend = 'UP' if ma is not None and old_ma is not None and close[p2] > ma > old_ma else 'DOWN' if ma is not None and old_ma is not None and close[p2] < ma < old_ma else 'SIDEWAYS'
                kind = divergence_kind(data[p1][field], value, rsi[p1], rsi[p2], low, config, trend)
                if kind is None:
                    continue
                trigger = max(r['high'] for r in data[p1 + 1:p2]) if low else min(r['low'] for r in data[p1 + 1:p2])
                invalidation = value
                # A pivot may have been exceeded before its confirmation became
                # available; that pattern must never be offered as actionable.
                if any(r['low'] < invalidation if low else r['high'] > invalidation for r in data[p2 + 1:known + 1]):
                    continue
                event = {
                    'divergenceType': kind, 'direction': 'BULLISH' if low else 'BEARISH',
                    'pivot1Index': indexed[p1][0], 'pivot2Index': indexed[p2][0],
                    'detectedIndex': indexed[known][0], 'segmentEndIndex': indexed[-1][0],
                    'pivot1At': stamp(data[p1]['timestamp']), 'pivot2At': stamp(data[p2]['timestamp']),
                    'detectedAt': stamp(data[known]['timestamp']),
                    'pivot1Price': data[p1][field], 'pivot2Price': value,
                    'pivot1Rsi': rsi[p1], 'pivot2Rsi': rsi[p2], 'rsi': rsi[known],
                    'triggerPrice': trigger, 'invalidationPrice': invalidation,
                    'trend': trend, 'extremeContext': min(rsi[p1], rsi[p2]) <= 30 if low else max(rsi[p1], rsi[p2]) >= 70,
                    'confirmedIndex': None, 'invalidatedIndex': None, 'confirmedAt': None,
                }
                for i in range(known, min(len(data), known + config.max_wait + 1)):
                    if (data[i]['low'] < invalidation if low else data[i]['high'] > invalidation):
                        event['invalidatedIndex'] = indexed[i][0]
                        break
                    if event['confirmedIndex'] is None and (close[i] > trigger if low else close[i] < trigger):
                        event['confirmedIndex'] = indexed[i][0]
                        event['confirmedAt'] = stamp(data[i]['timestamp'])
                events.append(event)
    return events


class RsiDivergenceStrategy(BaseStrategy):
    metadata = StrategyMetadata(
        id='rsi_divergence', name='RSI Divergence', category='Momentum', min_candles=250,
        description='Regular and hidden bullish/bearish divergences between confirmed price swings and Wilder RSI. WATCH waits for a close beyond the intervening swing; CONFIRMED records that breakout. Hidden patterns require a matching SMA trend.',
        parameters=[
            StrategyParameter(name=name, display_name=label, type=kind, default=default, min_value=minimum, max_value=maximum)
            for name, label, kind, default, minimum, maximum in [
                ('period', 'RSI period', 'int', 14, 2, 50),
                ('pivot_bars', 'Pivot bars each side', 'int', 3, 2, 10),
                ('min_gap', 'Minimum pivot gap', 'int', 5, 3, 30),
                ('max_gap', 'Maximum pivot gap', 'int', 60, 10, 120),
                ('min_rsi_delta', 'Minimum RSI difference', 'float', 3.0, 0.1, 30),
                ('min_price_pct', 'Minimum price difference %', 'float', 0.5, 0.01, 10),
                ('trend_period', 'Hidden trend SMA period', 'int', 50, 20, 200),
                ('max_wait', 'Breakout wait bars', 'int', 20, 1, 60),
                ('freshness', 'Recent signal bars', 'int', 5, 1, 30),
            ]
        ],
    )

    def candle_window(self, params):
        c = DivergenceConfig.resolve(params)
        return max(250, c.period * 5, c.trend_period + 5) + c.max_gap + c.max_wait + c.freshness + c.pivot_bars * 2

    def run(self, df, instruments_map, params):
        if df.is_empty():
            return []
        config = DivergenceConfig.resolve(params)
        today = datetime.now(ZoneInfo('Asia/Kolkata')).date()
        results = []
        for group in df.sort(['instrument_key', 'timestamp']).partition_by('instrument_key', maintain_order=True):
            raw = group.to_dicts()
            key = raw[0]['instrument_key']
            instrument = instruments_map.get(key)
            if instrument is None:
                continue
            rows = [r for r in raw if params.get('_timeframe', '1d') != '1d' or
                    (nse_daily_closed(r['timestamp']) if instrument.get('exchange') == 'NSE' else r['timestamp'].astimezone(ZoneInfo('Asia/Kolkata')).date() < today)]
            if not rows:
                continue
            key = rows[0]['instrument_key']
            instrument = instruments_map.get(key)
            if instrument is None:
                continue
            latest = len(rows) - 1
            candidates = []
            for event in detect_events(rows, config):
                if event['segmentEndIndex'] != latest:
                    continue
                # Continue checking invalidation after the breakout wait window.
                bullish = event['direction'] == 'BULLISH'
                if any(r['low'] < event['invalidationPrice'] if bullish else r['high'] > event['invalidationPrice'] for r in rows[event['detectedIndex']:]):
                    continue
                confirmed = event['confirmedIndex']
                if confirmed is None and latest - event['detectedIndex'] > config.max_wait:
                    continue
                index = confirmed if confirmed is not None else event['detectedIndex']
                if latest - index >= config.freshness:
                    continue
                candidates.append((index, event))
            if not candidates:
                continue
            _, event = max(candidates, key=lambda pair: (pair[0], pair[1]['detectedIndex']))
            confirmed = event['confirmedIndex'] is not None
            results.append({**{k: v for k, v in event.items() if not k.endswith('Index')},
                'instrumentKey': key, 'symbol': instrument.get('symbol', key), 'name': instrument.get('name', ''), 'exchange': instrument.get('exchange', 'NSE'),
                'close': rows[-1]['close'], 'volume': rows[-1].get('volume', 0),
                'changePct': (rows[-1]['close'] / rows[-2]['close'] - 1) * 100 if len(rows) > 1 else None,
                'rsi': GoldenDeathCrossStrategy._rsi([r['close'] for _, r in list(valid_segments(rows))[-1]], config.period)[-1],
                'state': 'CONFIRMED' if confirmed else 'WATCH',
                'status': f"{event['direction']} {'CONFIRMED' if confirmed else 'WATCH'}",
                'signal': event['direction'], 'ageBars': latest - (event['confirmedIndex'] if confirmed else event['detectedIndex']),
                'asOf': stamp(rows[-1]['timestamp']),
            })
        return sorted(results, key=lambda row: (row['ageBars'], row['symbol']))
