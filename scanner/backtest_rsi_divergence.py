"""Read-only, reproducible divergence event study and OHLC trade simulation.

Run: .venv/Scripts/python.exe -m scanner.backtest_rsi_divergence
Never selects defaults from the held-out period. No writes to market tables.
"""
import asyncio
from collections import defaultdict
from dataclasses import replace, asdict
from datetime import date, datetime, timezone
import json
from pathlib import Path
from statistics import mean, median
from time import perf_counter
from zoneinfo import ZoneInfo

from sqlalchemy import text
from database.connection import engine
from scanner.rsi_divergence_legacy import DivergenceConfig, detect_events


def simulate(rows, event, index, horizon=10, cost_pct=.2):
    """Enter next open, 2R target, pivot stop with 0.1% buffer, max 10 bars.

    Stop first when both levels touch. Gaps fill at open, capped target fills
    are conservative. No signal-day fills or retrospective entry pricing.
    """
    start = index + 1
    end = start + horizon - 1
    if end > event['segmentEndIndex']:
        return None
    bullish = event['direction'] == 'BULLISH'
    direction = 1 if bullish else -1
    entry = rows[start]['open']
    stop = event['invalidationPrice'] * (.999 if bullish else 1.001)
    risk = direction * (entry - stop)
    if risk <= 0:
        return None
    target = entry + direction * 2 * risk
    exit_price, exit_index, reason = rows[end]['close'], end, 'TIME'
    for i in range(start, end + 1):
        row = rows[i]
        if direction * (row['open'] - stop) <= 0:
            exit_price, exit_index, reason = row['open'], i, 'GAP_STOP'
            break
        if direction * (row['open'] - target) >= 0:
            exit_price, exit_index, reason = target, i, 'TARGET'
            break
        if row['low'] <= stop if bullish else row['high'] >= stop:
            exit_price, exit_index, reason = stop, i, 'STOP'
            break
        if row['high'] >= target if bullish else row['low'] <= target:
            exit_price, exit_index, reason = target, i, 'TARGET'
            break
    forward = direction * (rows[end]['close'] / entry - 1) * 100
    gross = direction * (exit_price / entry - 1) * 100
    return {'entryIndex': start, 'exitIndex': exit_index, 'grossPct': gross,
            'netPct': gross - cost_pct, 'forward10Pct': forward - cost_pct,
            'reason': reason, 'entryAt': rows[start]['timestamp'].date().isoformat(),
            'exitAt': rows[exit_index]['timestamp'].date().isoformat()}


def summarize(trades):
    if not trades:
        return {'trades': 0}
    net = [t['netPct'] for t in trades]
    gains = sum(v for v in net if v > 0)
    losses = -sum(v for v in net if v < 0)
    return {'trades': len(net), 'winRatePct': round(sum(v > 0 for v in net) / len(net) * 100, 2),
            'meanNetPct': round(mean(net), 4), 'medianNetPct': round(median(net), 4),
            'profitFactor': round(gains / losses, 4) if losses else None,
            'meanNetPctAt50bpsCost': round(mean(net) - .3, 4),
            'meanForward10NetPct': round(mean(t['forward10Pct'] for t in trades), 4),
            'exits': {reason: sum(t['reason'] == reason for t in trades) for reason in ('STOP', 'GAP_STOP', 'TARGET', 'TIME')}}


async def main():
    start = perf_counter()
    configs = {'pivot3': DivergenceConfig(), 'pivot5': replace(DivergenceConfig(), pivot_bars=5)}
    cutoff = date(2024, 1, 1)
    # Completed daily candles only; no current-session or future rows.
    today = datetime.now(ZoneInfo('Asia/Kolkata')).date()
    buckets = defaultdict(list)
    counts = defaultdict(int)
    earliest, latest = None, None
    symbols = 0
    async with engine.connect() as connection:
        instruments = (await connection.execute(text("SELECT id, symbol, provider_instrument_key FROM instruments WHERE is_active = true AND exchange = 'NSE' ORDER BY id"))).all()
        for offset in range(0, len(instruments), 30):
            batch = instruments[offset:offset + 30]
            # Server-side bound avoids downloading the entire 6.8M-row history.
            statement = text("""SELECT i.id, c.candle_time, c.open, c.high, c.low, c.close, c.volume
                FROM instruments i JOIN LATERAL (
                    SELECT candle_time, open, high, low, close, volume FROM candles
                    WHERE instrument_id=i.id AND timeframe='1d' AND candle_time < :today
                    ORDER BY candle_time DESC LIMIT 1500
                ) c ON true WHERE i.id = ANY(:ids) ORDER BY i.id, c.candle_time""")
            records = (await connection.execute(statement, {'ids': [i[0] for i in batch], 'today': datetime.combine(today, datetime.min.time(), tzinfo=ZoneInfo('Asia/Kolkata')).astimezone(timezone.utc)})).all()
            grouped = defaultdict(list)
            for record in records:
                grouped[record[0]].append({'timestamp': record[1], **dict(zip(('open', 'high', 'low', 'close'), map(float, record[2:6]))), 'volume': record[6]})
            for instrument_id, rows in grouped.items():
                symbols += 1
                earliest = min(earliest, rows[0]['timestamp']) if earliest else rows[0]['timestamp']
                latest = max(latest, rows[-1]['timestamp']) if latest else rows[-1]['timestamp']
                for label, config in configs.items():
                    events = detect_events(rows, config)
                    counts[label + ':patterns'] += len(events)
                    for mode in ('detected', 'confirmed'):
                        candidates = [(e['detectedIndex'] if mode == 'detected' else e['confirmedIndex'], e) for e in events]
                        busy_until = -1
                        for index, event in sorted(((i, e) for i, e in candidates if i is not None), key=lambda pair: (pair[0], pair[1]['divergenceType'])):
                            if index + 1 <= busy_until:
                                counts[label + ':' + mode + ':overlapSkipped'] += 1
                                continue
                            trade = simulate(rows, event, index)
                            if trade is None:
                                counts[label + ':' + mode + ':unfillableOrCensored'] += 1
                                continue
                            split = 'development' if rows[index + 1]['timestamp'].date() < cutoff else 'holdout'
                            if split == 'development' and rows[index + 10]['timestamp'].date() >= cutoff:
                                continue
                            busy_until = trade['exitIndex']
                            buckets[(label, mode, split, event['divergenceType'])].append(trade)
            print(f'Backtested {min(offset + 30, len(instruments))}/{len(instruments)} instruments', flush=True)
    report = {'generatedAt': datetime.now(timezone.utc).isoformat(), 'symbols': symbols,
              'from': earliest.isoformat() if earliest else None, 'to': latest.isoformat() if latest else None,
              'holdoutFrom': cutoff.isoformat(), 'configs': {k: asdict(v) for k, v in configs.items()},
              'counts': dict(counts), 'seconds': round(perf_counter() - start, 2),
              'method': 'Last 1500 completed daily candles per currently active NSE instrument; 250-bar warm-up; next-open entry; pivot stop buffered 0.1%; 2R target; 10-bar timeout; stop first on ambiguous bars; 20bps round-trip costs; one position per symbol within each scenario. Bearish trades are hypothetical shorts, not executable cash delivery trades. Current-universe survivorship bias, raw corporate-action prices, gaps, liquidity and historical slippage remain limitations. Segments reset on >25% close jumps, bad OHLC, >10-day gaps. No portfolio equity or annualized return claim.',
              'results': [{'config': key[0], 'entryMode': key[1], 'sample': key[2], 'divergenceType': key[3], **summarize(value)} for key, value in sorted(buckets.items())]}
    output = Path('data/rsi-divergence-backtest.json')
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2), flush=True)
    await engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
