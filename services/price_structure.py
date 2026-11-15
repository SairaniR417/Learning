"""Selected-stock, descriptive price structure. No orders or strategy votes."""
import asyncio
import calendar
import math
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from scanner.universe import get_fno_stocks, require_fno_key
from services import stock_chart
from services.market_sync import INDIA, nse_daily_closed
from services.candlestick_patterns import detect as detect_candlesticks

router = APIRouter(prefix='/api/focused')


def clean(rows, frame, now, include_developing=False):
    """Validate/deduplicate history; optionally retain labelled developing bars."""
    valid = {}
    invalid = 0
    developing = 0
    for item in rows:
        try:
            ts = datetime.fromisoformat(item['timestamp']) if isinstance(item['timestamp'], str) else item['timestamp']
            ts = ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts
            o, h, l, c, v = (float(item[k]) for k in ('open', 'high', 'low', 'close', 'volume'))
            if not all(math.isfinite(x) for x in (o, h, l, c, v)) or not 0 < l <= min(o, c) <= max(o, c) <= h or v < 0 or ts > now:
                raise ValueError()
            local = ts.astimezone(INDIA)
            session_end = local.replace(hour=15, minute=30, second=0, microsecond=0)
            closed = nse_daily_closed(ts, now) if frame == '1d' else min(ts + timedelta(hours=1), session_end) + timedelta(seconds=5) <= now
            is_developing = bool(item.get('developing')) or not closed
            if is_developing:
                developing += 1
                if not include_developing:
                    continue
            valid[ts] = dict(timestamp=ts, open=o, high=h, low=l, close=c, volume=v)
            if include_developing:
                valid[ts]['developing'] = is_developing
        except (KeyError, ValueError, TypeError, OverflowError):
            invalid += 1
    return sorted(valid.values(), key=lambda r: r['timestamp']), invalid, developing


def weekly(rows, now):
    buckets = {}
    for r in rows:
        day = r['timestamp'].astimezone(INDIA).date()
        monday = day - timedelta(days=day.weekday())
        if monday not in buckets:
            buckets[monday] = dict(r, closeTimestamp=r['timestamp'])
        else:
            b = buckets[monday]
            b.update(high=max(b['high'], r['high']), low=min(b['low'], r['low']), close=r['close'], volume=b['volume'] + r['volume'], closeTimestamp=r['timestamp'])
    # A weekly bar is confirmed only after its Friday session closes.
    today = now.astimezone(INDIA)
    return [r for monday, r in sorted(buckets.items()) if monday + timedelta(days=4) < today.date() or
            (monday + timedelta(days=4) == today.date() and today.hour >= 16)]


def months_before(day, months):
    ordinal = day.year * 12 + day.month - 1 - months
    year, month = divmod(ordinal, 12)
    return day.replace(year=year, month=month + 1, day=min(day.day, calendar.monthrange(year, month + 1)[1]))


def money(value):
    return f'₹{value:,.2f}'


def analyze(rows, label, frame, now, scope):
    base = dict(label=label, frame=frame, scope=scope, count=len(rows), asOf=None, firstDate=None,
                trend='Unavailable', narrative=[], supports=[], resistances=[], trendlines=[], events=[],
                watch=[], volume=None, high=None, low=None, close=None, swings=[])
    if not rows:
        base['narrative'] = ['No completed history is available for this view.']
        base['watch'] = ['Load the missing history before assessing structure.']
        return base
    latest = rows[-1]
    close = latest['close']
    high = max(rows, key=lambda r: r['high'])
    low = min(rows, key=lambda r: r['low'])
    base.update(asOf=latest.get('closeTimestamp', latest['timestamp']).isoformat(), firstDate=rows[0]['timestamp'].isoformat(), close=close,
                high=dict(price=high['high'], date=high['timestamp'].isoformat()),
                low=dict(price=low['low'], date=low['timestamp'].isoformat()))
    atr = sum(max(r['high'] - r['low'], abs(r['high'] - rows[i-1]['close']), abs(r['low'] - rows[i-1]['close']))
              for i, r in list(enumerate(rows))[1:][-14:]) / min(14, max(1, len(rows)-1))
    tolerance = max(close * .003, atr * .3)
    # Two candles on each side confirm a swing: the latest two cannot be pivots.
    pivots = []
    for i in range(2, len(rows)-2):
        for kind, field, fn in [('high', 'high', max), ('low', 'low', min)]:
            value = rows[i][field]
            neighbors = [rows[j][field] for j in range(i-2, i+3) if j != i]
            if value == fn([value] + neighbors) and value not in neighbors:
                pivots.append(dict(index=i, kind=kind, price=value, date=rows[i]['timestamp'].isoformat()))
    highs = [p for p in pivots if p['kind'] == 'high']
    lows = [p for p in pivots if p['kind'] == 'low']
    base['swings'] = sorted(pivots, key=lambda p: p['index'])[-8:]
    trend = 'Insufficient confirmed swings'
    if len(highs) >= 2 and len(lows) >= 2:
        hh, hl = highs[-1]['price'] > highs[-2]['price'], lows[-1]['price'] > lows[-2]['price']
        lh, ll = highs[-1]['price'] < highs[-2]['price'], lows[-1]['price'] < lows[-2]['price']
        trend = 'Higher highs / higher lows' if hh and hl else 'Lower highs / lower lows' if lh and ll else 'Mixed / range structure'
        base['narrative'].append(f"Latest confirmed swing highs: {money(highs[-2]['price'])} → {money(highs[-1]['price'])}; swing lows: {money(lows[-2]['price'])} → {money(lows[-1]['price'])}.")
        if hh and hl:
            base['narrative'].append(f"The latest higher low formed on {datetime.fromisoformat(lows[-1]['date']).astimezone(INDIA):%d %b %Y} at {money(lows[-1]['price'])}.")
            if close < lows[-1]['price']:
                trend = 'Rising structure / support lost'
                base['narrative'].append('The latest close is below that higher low, weakening the earlier rising structure.')
        elif lh and ll and close > highs[-1]['price']:
            trend = 'Falling structure / resistance broken'
            base['narrative'].append('The latest close is above the last lower high, weakening the earlier falling structure.')
    base['trend'] = trend
    base['narrative'].insert(0, f"Observed range {money(low['low'])}–{money(high['high'])}; latest completed close {money(close)}.")
    hi_index, lo_index = rows.index(high), rows.index(low)
    if hi_index < lo_index:
        base['narrative'].append(f"Fell from {money(high['high'])} to {money(low['low'])} ({(low['low']/high['high']-1)*100:.1f}%); subsequent move to {money(close)} ({(close/low['low']-1)*100:+.1f}% from that low).")
    elif lo_index < hi_index:
        base['narrative'].append(f"Rose from {money(low['low'])} to {money(high['high'])} ({(high['high']/low['low']-1)*100:+.1f}%); latest close is {(close/high['high']-1)*100:.1f}% from that high.")
    if len(rows) >= 10:
        recent = rows[-10:]
        recent_high, recent_low = max(r['high'] for r in recent), min(r['low'] for r in recent)
        base['narrative'].append(f"The last 10 completed bars traded between {money(recent_low)} and {money(recent_high)} ({(recent_high/recent_low-1)*100:.1f}% range). A break and sustained closes outside this range would change the immediate picture.")
    # Cluster pivot prices into zones; repeated pivots are evidence, not a strength guarantee.
    groups = []
    for p in sorted(pivots, key=lambda p: p['price']):
        if groups and p['price'] - groups[-1][0]['price'] <= tolerance:
            groups[-1].append(p)
        else:
            groups.append([p])
    zones = [dict(price=round(sum(p['price'] for p in group)/len(group), 2),
                  low=min(p['price'] for p in group), high=max(p['price'] for p in group),
                  touches=len(group), lastDate=max(p['date'] for p in group),
                  origin='Confirmed swing zone') for group in groups]
    # Observed extrema remain useful when there are too few confirmed pivots.
    for field, item in [('low', low), ('high', high)]:
        if not any(abs(z['price']-item[field]) <= tolerance for z in zones):
            zones.append(dict(price=item[field], low=item[field], high=item[field], touches=1,
                              lastDate=item['timestamp'].isoformat(), origin='Observed range extreme'))
    for z in zones:
        z['distancePct'] = round((z['price']/close-1)*100, 2)
    base['supports'] = sorted([z for z in zones if z['price'] < close], key=lambda z: -z['price'])[:3]
    base['resistances'] = sorted([z for z in zones if z['price'] >= close], key=lambda z: z['price'])[:3]
    # Evaluate breaks only after a level's confirming candles were known.
    for p in pivots:
        for i in range(max(p['index']+3, len(rows)-5), len(rows)):
            a, b = rows[i-1], rows[i]
            up = p['kind'] == 'high' and a['close'] <= p['price'] < b['close']
            down = p['kind'] == 'low' and a['close'] >= p['price'] > b['close']
            if up or down:
                message = f"{'Closed above prior resistance' if up else 'Closed below prior support'} {money(p['price'])} on {b['timestamp'].astimezone(INDIA):%d %b %Y %H:%M} IST."
                later = rows[i+1:]
                retested = (any(p['price']-tolerance <= r['low'] <= p['price']+tolerance and r['close'] > p['price'] for r in later) if up else
                            any(p['price']-tolerance <= r['high'] <= p['price']+tolerance and r['close'] < p['price'] for r in later))
                if retested:
                    message += ' A later candle revisited the zone and closed on the breakout side; this is a retest observation.'
                if i >= 20:
                    prior_volume = sum(r['volume'] for r in rows[i-20:i])/20
                    if prior_volume:
                        message += f" Break candle volume: {b['volume']/prior_volume:.2f}× its preceding 20-bar average."
                base['events'].append((i, message))
                break
    base['events'] = list(dict.fromkeys(message for _, message in sorted(base['events'])))[-4:]
    for points, kind in [(lows, 'Rising support'), (highs, 'Falling resistance')]:
        if len(points) < 2:
            continue
        a, b = points[-2:]
        slope = (b['price']-a['price'])/(b['index']-a['index'])
        if (kind == 'Rising support' and slope <= 0) or (kind == 'Falling resistance' and slope >= 0):
            continue
        projection = b['price'] + slope * (len(rows)-1-b['index'])
        if projection <= 0:
            continue
        broken = close < projection-tolerance if kind == 'Rising support' else close > projection+tolerance
        base['trendlines'].append(dict(kind=kind, start=a, end=b, current=round(projection, 2),
                                      state='Latest close beyond line' if broken else 'Latest close on expected side',
                                      note='Two-swing candidate; projection uses candle positions and is not a guaranteed level.'))
    if len(rows) >= 21:
        average = sum(r['volume'] for r in rows[-21:-1])/20
        ratio = latest['volume']/average if average else None
        base['volume'] = dict(ratio=round(ratio, 2) if ratio is not None else None, latest=latest['volume'], average=round(average, 2),
                              description=f"Latest completed volume is {ratio:.2f}× the preceding 20-bar average." if ratio is not None else 'Prior average volume is zero; volume confirmation unavailable.')
    else:
        base['volume'] = dict(ratio=None, description='Need 21 completed bars to compare volume against the preceding 20-bar average.')
    if frame == '1h':
        base['volume']['description'] += ' Hourly comparison is not adjusted for time-of-day effects or the shorter closing bar.'
    if base['supports']:
        s = base['supports'][0]
        base['watch'].append(f"On a pullback, watch whether {money(s['price'])} holds on a closing basis. A close below it weakens that support; the next lower zone is a separate test.")
    if base['resistances']:
        r = base['resistances'][0]
        base['watch'].append(f"For continuation, watch for a close above {money(r['price'])}, then whether a later retest holds. Compare breakout volume with the preceding 20 completed bars.")
    else:
        base['watch'].append('No overhead swing resistance is visible in the loaded window. That does not establish an all-time high; watch whether new highs sustain and pullbacks hold.')
    if len(rows) < 7:
        base['watch'].append('Limited history: there are too few completed bars for reliable swing structure.')
    return base


def build(daily, hourly, now, pattern_daily=None, pattern_hourly=None):
    anchor = now.astimezone(INDIA).date()
    views = []
    for months in (12, 3, 1):
        start = months_before(anchor, months)
        subset = [r for r in daily if r['timestamp'].astimezone(INDIA).date() >= start]
        view = analyze(subset, f'{months} Months' if months != 1 else '1 Month', '1d', now, f'Trailing {months} calendar months · daily price structure')
        view['limitedCoverage'] = not daily or daily[0]['timestamp'].astimezone(INDIA).date() > start + timedelta(days=7)
        views.append(view)
    views.extend([analyze(weekly(daily, now)[-156:], '1 Week', '1w', now, 'Weekly structure · up to 156 completed weeks'),
                  analyze(daily[-252:], '1 Day', '1d', now, 'Daily structure · up to 252 completed sessions'),
                  analyze(hourly[-500:], '1 Hour', '1h', now, 'Hourly structure · up to 500 completed bars')])
    views[-2]['candlesticks'] = detect_candlesticks(daily if pattern_daily is None else pattern_daily, '1d')
    views[-1]['candlesticks'] = detect_candlesticks(hourly if pattern_hourly is None else pattern_hourly, '1h')
    return views


@router.get('/structure')
async def structure(instrument_key: str):
    require_fno_key(instrument_key)
    metadata = next(s for s in get_fno_stocks() if s['key'] == instrument_key)

    async def load(frame):
        try:
            return await stock_chart.stock_chart(instrument_key, frame)
        except HTTPException as exc:
            return dict(candles=[], warning=f'{frame} history unavailable: {exc.detail}', staleData=True)

    daily_response, hourly_response = await asyncio.gather(load('1d'), load('1h'))
    now = datetime.now(timezone.utc)
    daily, bad_daily, dev_daily = clean(daily_response['candles'], '1d', now)
    hourly, bad_hourly, dev_hourly = clean(hourly_response['candles'], '1h', now)
    pattern_daily, _, _ = clean(daily_response['candles'], '1d', now, include_developing=True)
    pattern_hourly, _, _ = clean(hourly_response['candles'], '1h', now, include_developing=True)
    warnings = list(dict.fromkeys(r[k] for r in (daily_response, hourly_response) for k in ('warning', 'historyWarning') if r.get(k)))
    if bad_daily or bad_hourly:
        warnings.append('Invalid candles were found. Structure is unavailable for affected histories to avoid drawing across corrupt data.')
        if bad_daily:
            daily = []
            pattern_daily = []
        if bad_hourly:
            hourly = []
            pattern_hourly = []
    views = await asyncio.to_thread(build, daily, hourly, now, pattern_daily, pattern_hourly)
    full_history = await asyncio.to_thread(analyze, daily, 'Available daily history', '1d', now, 'Loaded history only')
    for view in views:
        response = hourly_response if view['frame'] == '1h' else daily_response
        view['source'] = response.get('source', 'History unavailable')
        view['staleData'] = response.get('staleData', False)
        view['developingExcluded'] = dev_hourly if view['frame'] == '1h' else dev_daily
        if view['asOf']:
            age = now - datetime.fromisoformat(view['asOf'])
            view['oldHistory'] = age > timedelta(days=10 if view['frame'] == '1w' else 4)
        else:
            view['oldHistory'] = True
    return dict(stock=metadata, views=views, warnings=warnings, receivedAt=now.isoformat(),
                historyContext=dict(firstDate=full_history['firstDate'], asOf=full_history['asOf'], count=len(daily),
                                    narrative=full_history['narrative']),
                methodology='12/3/1 Months are trailing calendar windows of daily history. Weekly, daily and hourly are candle intervals analyzed without displaying candles. Swings require two completed bars on each side. Zones cluster confirmed swings within max(0.3% of close, 0.3 ATR-14); extrema are labelled separately. Trendlines join the last two same-side confirmed swings. Volume compares the last completed bar with the previous 20. Developing bars are excluded from structure, but daily/hourly candlestick observations may show a separately labelled forming shape. Patterns review the last three completed bars and any developing bar. Reversal names require preceding five-bar trend context. Confirmation requires a later completed close beyond the full pattern range; a close beyond the opposite boundary invalidates it. Neutral shapes describe indecision. Pattern dates and source freshness matter. Levels describe observed history; retests and future moves remain conditional.')
