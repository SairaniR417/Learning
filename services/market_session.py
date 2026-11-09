"""NSE session context and opening ranges from actual completed five-minute bars."""
from datetime import datetime, timedelta, timezone
from math import isfinite
from services.market_sync import INDIA


def clean(row):
    try:
        o, h, l, c, v = (float(row[k]) for k in ('open', 'high', 'low', 'close', 'volume'))
        return all(isfinite(x) for x in (o, h, l, c, v)) and 0 < l <= min(o, c) <= max(o, c) <= h and v >= 0
    except (TypeError, ValueError, KeyError):
        return False


def utc(ts):
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)


def session_context(rows, interval):
    empty = dict(sessionDate=None, dayOpen=None, dayHigh=None, dayLow=None, fromOpenPct=None,
                 dayHighPct=None, dayLowPct=None, dayRangePosition=None)
    if not rows:
        return empty
    day = utc(rows[-1]['timestamp']).astimezone(INDIA).date()
    session = [r for r in rows if utc(r['timestamp']).astimezone(INDIA).date() == day]
    if not session or not all(clean(r) for r in session):
        return dict(empty, sessionDate=day.isoformat())
    first = utc(session[0]['timestamp']).astimezone(INDIA)
    # Never pass off the first available midday candle as the day's open.
    if interval != 1440 and (interval >= 1440 or (first.hour, first.minute) != (9, 15)):
        return dict(empty, sessionDate=day.isoformat())
    opening, price = session[0]['open'], session[-1]['close']
    high, low = max(r['high'] for r in session), min(r['low'] for r in session)
    return dict(sessionDate=day.isoformat(), dayOpen=opening, dayHigh=high, dayLow=low,
                fromOpenPct=(price / opening - 1) * 100, dayHighPct=(high / opening - 1) * 100,
                dayLowPct=(low / opening - 1) * 100,
                dayRangePosition=(price - low) / (high - low) * 100 if high > low else 50.)


def opening_range(rows, minutes=15, hold_bars=2, now=None):
    if minutes not in (15, 30, 60) or type(hold_bars) is not int or not 1 <= hold_bars <= 6:
        raise ValueError('Opening range must be 15, 30 or 60 minutes; hold bars must be 1–6.')
    now = now or datetime.now(timezone.utc)
    # An unfinished candle may not confirm a range or a breakout.
    rows = sorted((dict(r, timestamp=utc(r['timestamp'])) for r in rows
                   if utc(r['timestamp']) + timedelta(minutes=5, seconds=5) <= now), key=lambda r: r['timestamp'])
    result = dict(orbState='NO_HISTORY', orbHigh=None, orbLow=None, orbMinutes=minutes,
                  orbHeldBars=0, orbBreakoutAt=None, orbAsOf=None, orbGapPct=None,
                  orbReason='No completed 5m candles.', **session_context([], 5))
    if not rows:
        return result
    day = rows[-1]['timestamp'].astimezone(INDIA).date()
    start = datetime.combine(day, datetime.min.time(), INDIA).replace(hour=9, minute=15)
    end = start + timedelta(minutes=minutes)
    close = start.replace(hour=15, minute=30)
    session = {r['timestamp'].astimezone(INDIA): r for r in rows
               if start <= r['timestamp'].astimezone(INDIA) < close}
    ordered = [r for _, r in sorted(session.items())]
    result.update(session_context(ordered, 5))
    result['sessionDate'] = day.isoformat()
    if not ordered:
        return result
    result['orbAsOf'] = ordered[-1]['timestamp'].isoformat()
    slots = [start + timedelta(minutes=5 * i) for i in range(minutes // 5)]
    if now < end + timedelta(seconds=5):
        return dict(result, orbState='BUILDING', orbReason='Opening range is still forming.')
    if any(ts not in session or not clean(session[ts]) for ts in slots):
        return dict(result, orbState='INCOMPLETE', orbReason='Missing or invalid opening 5m bars; range is not estimated.')
    high = max(session[ts]['high'] for ts in slots)
    low = min(session[ts]['low'] for ts in slots)
    result.update(orbHigh=high, orbLow=low)
    after = [(ts, r) for ts, r in sorted(session.items()) if ts >= end]
    if not after:
        return dict(result, orbState='WAIT', orbReason='Range complete; waiting for post-range closes.')
    if not clean(after[-1][1]):
        return dict(result, orbState='INCOMPLETE', orbReason='Latest 5m candle is invalid; a hold cannot be verified.')
    # Break a hold on gaps, invalid data, a close inside the range or a direction change.
    direction, count, breakout_at, previous = None, 0, None, end - timedelta(minutes=5)
    for ts, row in after:
        side = ('BULLISH' if row['close'] > high else 'BEARISH' if row['close'] < low else None) if clean(row) and (ts - start).total_seconds() % 300 == 0 else None
        if ts != previous + timedelta(minutes=5) or side != direction:
            count, breakout_at = 0, None
        if side:
            if count == 0:
                breakout_at = ts
            count += 1
        else:
            count, breakout_at = 0, None
        direction, previous = side, ts
    price = after[-1][1]['close']
    boundary = high if direction == 'BULLISH' else low if direction == 'BEARISH' else None
    confirmed = direction is not None and count >= hold_bars
    return dict(result, orbState=direction if confirmed else 'WATCH' if direction else 'INSIDE',
                orbHeldBars=count, orbBreakoutAt=breakout_at.isoformat() if breakout_at else None,
                orbGapPct=(price / boundary - 1) * 100 if boundary else None,
                orbReason=f'{count} consecutive completed 5m closes outside the range; {hold_bars} required.' if direction else 'Latest close is inside the opening range.')
