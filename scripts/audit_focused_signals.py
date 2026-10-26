r"""Read-only parity audit of Focused against shared engines on stored candles.

Run: .venv\Scripts\python.exe scripts/audit_focused_signals.py
Writes a reproducible JSON report; never fetches broker data or changes the DB.
"""
import asyncio
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database.candle_repo import load_recent_candles_polars
from database.connection import engine
from scanner.universe import get_fno_stocks
from services import focused_plans as focused, golden_cross, suryavanshi
from services.ghost_rider_overlay import calculate as ghost_calculate
from services.rsi_overlay import calculate as rsi_calculate

EXCLUDED = {'INVALIDATED', 'NO_FRESH_SETUP', 'TARGET', 'STOP', 'BOTH', 'EXPIRED', 'CONFIRMED_WEAKENED'}


def visible(check):
    return check.get('signal') if (check.get('signalState') or check['state']) not in EXCLUDED else None


async def main():
    now = datetime.now(timezone.utc)
    meta = {s['key']: s for s in get_fno_stocks()}
    frames = list(focused.TIMEFRAMES)
    tables = await asyncio.gather(*(load_recent_candles_polars(tf, per_instrument=1000) for tf in frames))
    grouped = {}
    for tf, table in zip(frames, tables):
        grouped[tf] = {} if table.is_empty() else {
            g['instrument_key'][0]: focused.completed_rows(g.sort('timestamp').to_dicts(), tf, now)
            for g in table.partition_by('instrument_key')
        }
    report = dict(auditedAt=now.isoformat(), scope='Stored completed candles, default inputs; no live/developing-bar parity claim',
                  universe=len(meta), frames={}, mismatches=[], frontendPlans=[])
    for tf, interval in focused.TIMEFRAMES.items():
        counts = Counter()
        missing = []
        snapshots = []
        for i, (key, stock) in enumerate(meta.items()):
            if i % 40 == 0:
                print(f'{tf}: {i}/{len(meta)}', flush=True)
            rows = grouped[tf].get(key, [])
            daily = grouped['1d'].get(key, [])
            five = grouped['5m'].get(key, [])
            if len(rows) < 60 or len(daily) < 200:
                missing.append(dict(symbol=stock['symbol'], executionBars=len(rows), dailyBars=len(daily)))
                continue
            # Compute expected source outputs independently from Focused's mapping.
            ghost = ghost_calculate(rows, five, interval)
            sury = suryavanshi.calculate(rows)
            cross = golden_cross.calculate(rows)
            rsi = rsi_calculate(rows)
            checks, drivers, levels = focused.evidence(rows, daily, five, interval, now)
            by_id = {c['id']: c for c in checks}
            expected = dict(ghost_rider=ghost['setup']['signal'] if ghost['setup'] else None,
                            suryavanshi=('BUY' if sury['activeTrade']['direction'] == 'long' else 'SELL') if sury['activeTrade'] else None,
                            golden_death_cross=cross['signal'])
            for strategy, direction in expected.items():
                actual = visible(by_id[strategy])
                counts['comparisons'] += 1
                if direction != actual:
                    report['mismatches'].append(dict(symbol=stock['symbol'], timeframe=tf, strategy=strategy,
                                                      expected=direction, actual=actual, state=by_id[strategy].get('signalState')))
            if rsi['events']:
                event = rsi['events'][-1]
                expected_rsi = 'BUY' if event['direction'] == 'BULLISH' else 'SELL'
                actual_rsi = by_id['rsi_divergence'].get('signal')
                if actual_rsi and actual_rsi != expected_rsi:
                    report['mismatches'].append(dict(symbol=stock['symbol'], timeframe=tf, strategy='rsi_divergence', expected=expected_rsi, actual=actual_rsi))
                if not visible(by_id['rsi_divergence']):
                    counts['rsiContextExcludedByEntryPolicy'] += 1
                counts['rsiComparisons'] += 1
            elif by_id['rsi_divergence'].get('signal'):
                report['mismatches'].append(dict(symbol=stock['symbol'], timeframe=tf, strategy='rsi_divergence', expected=None, actual=by_id['rsi_divergence']['signal']))
            if ghost['setup'] and len(rows)-1-ghost['setup']['index'] > 5:
                counts['ghostSignalsPreviouslyHiddenByAge'] += 1
            signals = {visible(c) for c in checks} - {None}
            if len(signals) > 1:
                counts['conflictingStocks'] += 1
            turnover = sum(float(r['close'])*float(r.get('volume') or 0) for r in daily[-20:])/20
            liquid = turnover >= 10_000_000 and rows[-1]['close'] >= 20 and bool(rows[-1].get('volume'))
            if liquid:
                plan = focused.build_plan(rows, daily, five, stock, 'intraday', now, (checks, drivers, levels), timeframe=tf)
                report['frontendPlans'].append(plan)
                counts['focusedCovered'] += 1
                # Closed/stale/session restrictions must remain effective independently of source signals.
                if plan['action'] != 'WAIT' and plan['waitReasons']:
                    report['mismatches'].append(dict(symbol=stock['symbol'], timeframe=tf, strategy='entry_gate', reason='Ready entry has blockers'))
            counts['auditedStocks'] += 1
            snapshots.append(dict(symbol=stock['symbol'], asOf=rows[-1]['timestamp'].isoformat(),
                                  sourceDirections=expected, focusedDirections={k:visible(by_id[k]) for k in expected}))
        report['frames'][tf] = dict(counts, missingHistory=missing, snapshots=snapshots)
        print(f'{tf}: {dict(counts)}, missing history={len(missing)}', flush=True)
    destination = ROOT/'data'/'focused-signal-audit.json'
    destination.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f'Mismatches: {len(report["mismatches"])}; report: {destination}', flush=True)
    await engine.dispose()
    return len(report['mismatches'])


if __name__ == '__main__':
    sys.exit(asyncio.run(main()) > 0)
