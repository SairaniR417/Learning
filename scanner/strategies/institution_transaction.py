"""Observable price/volume pressure; never identifies or confirms institutions."""
from datetime import datetime, timedelta, timezone
from statistics import mean

from scanner.strategies.base import BaseStrategy, StrategyMetadata, StrategyParameter
from services.ghost_scanner import completed_rows
from services.market_session import clean, utc
from services.market_sync import INDIA


def finished(rows, frame, now):
    if frame == '1d': return completed_rows(rows, frame, now)
    result = []
    for row in rows:
        stamp = utc(row['timestamp'])
        local = stamp.astimezone(INDIA)
        opening = local.replace(hour=9, minute=15, second=0, microsecond=0)
        closing = local.replace(hour=15, minute=30, second=0, microsecond=0)
        if opening <= local < closing and min(local + timedelta(hours=1), closing) + timedelta(seconds=5) <= now:
            result.append(dict(row, timestamp=stamp))
    return result[-1000:]


def pressure_view(rows, frame, lookback=20, volume_multiple=1.5, now=None):
    now = now or datetime.now(timezone.utc)
    # Deduplicate timestamps before forming comparisons or volume baselines.
    rows = sorted({r['timestamp']: r for r in rows}.values(), key=lambda r: r['timestamp'])
    rows = finished(rows, frame, now)
    last = rows[-1] if rows else None
    result = dict(state='UNAVAILABLE', asOf=last['timestamp'].isoformat() if last else None,
                  close=float(last['close']) if last and clean(last) else None,
                  relativeVolume=None, volumePressure=None, support=None, resistance=None,
                  vwap=None, structure='Unconfirmed', volumeBasis='', reason='', oldData=False)
    if len(rows) < lookback + 1:
        return dict(result, reason=f'Need {lookback + 1} completed {frame} candles; have {len(rows)}.')
    window = rows[-lookback-1:]
    if not all(clean(r) for r in window):
        return dict(result, reason='Invalid OHLCV in the analysis window; pressure is unavailable.')
    prior, recent = window[:-1], window[1:]
    last = rows[-1]
    support, resistance = min(r['low'] for r in prior), max(r['high'] for r in prior)
    baseline = prior
    if frame == '1h':
        local = last['timestamp'].astimezone(INDIA)
        baseline = [r for r in rows[:-1] if clean(r) and
                    r['timestamp'].astimezone(INDIA).date() < local.date() and
                    r['timestamp'].astimezone(INDIA).time() == local.time()][-lookback:]
        result['volumeBasis'] = f'Same hourly start time across {len(baseline)} prior sessions (minimum 5).'
        if len(baseline) < 5:
            return dict(result, support=support, resistance=resistance,
                        reason='Need at least 5 prior sessions at the same hourly start time to compare volume.')
    else:
        result['volumeBasis'] = f'Prior {lookback} completed daily candles, excluding the latest candle.'
    average = mean(float(r['volume']) for r in baseline)
    total = sum(float(r['volume']) for r in recent)
    if average <= 0 or total <= 0:
        return dict(result, reason='Volume history is zero; pressure cannot be evaluated.')
    ratio = float(last['volume']) / average
    # Close location weighted by volume (CMF), not signed buyer/seller order flow.
    flow = sum(((2*r['close']-r['high']-r['low'])/(r['high']-r['low']) if r['high'] > r['low'] else 0)
               * float(r['volume']) for r in recent) / total
    location = (last['close']-last['low'])/(last['high']-last['low']) if last['high'] > last['low'] else .5
    sma = mean(float(r['close']) for r in recent)
    highs, lows = [], []
    for i in range(2, len(rows)-2):
        if not all(clean(r) for r in rows[i-2:i+3]):
            continue
        others = rows[i-2:i] + rows[i+1:i+3]
        if all(rows[i]['high'] > r['high'] for r in others): highs.append(rows[i]['high'])
        if all(rows[i]['low'] < r['low'] for r in others): lows.append(rows[i]['low'])
    structure = 'Unconfirmed'
    if len(highs) >= 2 and len(lows) >= 2:
        structure = 'HH / HL' if highs[-1] > highs[-2] and lows[-1] > lows[-2] else 'LH / LL' if highs[-1] < highs[-2] and lows[-1] < lows[-2] else 'Mixed swings'
    vwap = None
    session_complete = False
    if frame == '1h':
        session = [r for r in rows if r['timestamp'].astimezone(INDIA).date() == local.date()]
        start = local.replace(hour=9, minute=15, second=0, microsecond=0)
        session_complete = all(clean(r) for r in session) and [r['timestamp'].astimezone(INDIA) for r in session] == [start + timedelta(hours=i) for i in range(len(session))]
        volume = sum(float(r['volume']) for r in session)
        if session_complete and volume > 0:
            vwap = sum((r['high']+r['low']+r['close'])/3 * float(r['volume']) for r in session)/volume
    above = last['close'] > sma and (frame != '1h' or vwap is not None and last['close'] > vwap)
    below = last['close'] < sma and (frame != '1h' or vwap is not None and last['close'] < vwap)
    buying = ratio >= volume_multiple and flow >= .1 and location >= 2/3 and last['close'] > last['open'] and above
    selling = ratio >= volume_multiple and flow <= -.1 and location <= 1/3 and last['close'] < last['open'] and below
    state = 'BUYING' if buying else 'SELLING' if selling else 'NEUTRAL'
    # A conservative age warning; the app does not have a holiday calendar here.
    old = now - last['timestamp'] > timedelta(days=4)
    if frame == '1h' and now.astimezone(INDIA).date() == local.date() and 10 <= now.astimezone(INDIA).hour < 16:
        old |= now - last['timestamp'] > timedelta(hours=2, minutes=5)
    reason = f'RVOL {ratio:.2f}x; close-location volume pressure {flow:+.2f}; close {last["close"]:.2f} versus SMA {lookback} {sma:.2f}.'
    if frame == '1h' and not session_complete:
        reason += ' Session bars are missing or misaligned; session VWAP is unavailable and hourly pressure is unconfirmed.'
        state = 'UNAVAILABLE'
    if old: reason += ' Old stored history; this is a historical observation.'
    return dict(result, state=state, relativeVolume=round(ratio, 3), volumePressure=round(flow, 3),
                support=float(support), resistance=float(resistance), vwap=vwap, structure=structure,
                oldData=old, reason=reason, breakout=last['close'] > resistance, breakdown=last['close'] < support)


class InstitutionTransactionStrategy(BaseStrategy):
    metadata = StrategyMetadata(
        id='institution_transaction', name='Institution Transaction', category='Price and volume',
        default_timeframe='1d', min_candles=21,
        description='Possible buying/selling pressure from completed Daily and 1-hour candles. Uses relative volume, close-location volume pressure, SMA position and hourly session VWAP. This does not identify institutions. Bulk/block disclosures are not connected or checked.',
        parameters=[
            StrategyParameter(name='lookback', display_name='Volume / pressure lookback', type='int', default=20, min_value=10, max_value=60),
            StrategyParameter(name='volume_multiple', display_name='Minimum relative volume', type='float', default=1.5, min_value=1, max_value=10),
            StrategyParameter(name='include_waiting', display_name='Include neutral / missing-history stocks', type='bool', default=True)])

    def candle_window(self, params):
        return 1000

    def run(self, df, instruments_map, params):
        frame = params.get('_timeframe', '1d')
        if frame not in {'1d', '1h'}:
            raise ValueError('Institution Transaction supports Daily and 1-hour candles.')
        primary = {str(g['instrument_key'][0]): g.to_dicts() for g in df.sort('timestamp').partition_by('instrument_key')} if not df.is_empty() else {}
        daily = primary if frame == '1d' else params.get('_daily_rows', {})
        hourly = primary if frame == '1h' else params.get('_hourly_rows', {})
        results = []
        now = datetime.now(timezone.utc)
        for key, meta in instruments_map.items():
            views = {f: pressure_view(source.get(key, []), f, params.get('lookback', 20), params.get('volume_multiple', 1.5), now)
                     for f, source in [('1d', daily), ('1h', hourly)]}
            selected = views[frame]
            a, b = views['1d'], views['1h']
            recent = not a['oldData'] and not b['oldData'] and a['asOf'] and b['asOf'] and abs(datetime.fromisoformat(a['asOf'])-datetime.fromisoformat(b['asOf'])) <= timedelta(days=1)
            status = 'INSUFFICIENT HISTORY' if selected['state'] == 'UNAVAILABLE' else 'NEUTRAL'
            if selected['state'] in {'BUYING', 'SELLING'}:
                confirmed = a['state'] == b['state'] and recent
                status = selected['state'] + (' PRESSURE' if confirmed else ' WATCH')
            if {a['state'], b['state']} == {'BUYING', 'SELLING'}: status = 'MIXED PRESSURE'
            if selected['oldData']: status = 'HISTORICAL'
            if not params.get('include_waiting', True) and status not in {'BUYING PRESSURE','SELLING PRESSURE','BUYING WATCH','SELLING WATCH','MIXED PRESSURE'}:
                continue
            rows = finished(sorted({r['timestamp']:r for r in primary.get(key, [])}.values(), key=lambda r:r['timestamp']), frame, now)
            last = rows[-1] if rows and clean(rows[-1]) else None
            previous = rows[-2] if len(rows)>1 and clean(rows[-2]) else None
            number = lambda value: f'{value:.2f}' if value is not None else 'unavailable'
            explanation = '\n'.join([f'{"Daily" if f == "1d" else "1 Hour"}: {v["state"]}; as of {datetime.fromisoformat(v["asOf"]).astimezone(INDIA).strftime("%d %b %Y, %H:%M IST") if v["asOf"] else "unavailable"}. {v["reason"]} {v["volumeBasis"]} Structure: {v["structure"]}. Support {number(v["support"])}; resistance {number(v["resistance"])}. VWAP {number(v["vwap"])}.' for f,v in views.items()])
            explanation += '\nPressure is a price/volume inference, not institutional identification or a trade entry. Institutional disclosures: NOT CHECKED. Close-location volume pressure = sum(volume × (2×close − high − low)/(high − low)) / sum(volume); flat candles contribute zero. Values above +0.10 / below −0.10 indicate upper/lower range closes weighted by volume. Watch whether support/resistance holds on the next retest; no retest is assumed.'
            results.append(dict(instrumentKey=key,symbol=meta.get('symbol',key),name=meta.get('name',key),exchange=meta.get('exchange','NSE'),
                                strategyId='institution_transaction',status=status,signal='WATCH',state=status,
                                close=float(last['close']) if last else None,volume=float(last['volume']) if last else 0,
                                changePct=(last['close']/previous['close']-1)*100 if last and previous else None,
                                asOf=selected['asOf'],pressureViews=views,pressureExplanation=explanation,
                                institutionalConfirmed=False,disclosureStatus='Not checked',candlesAnalyzed=len(rows)))
        rank = {'BUYING PRESSURE':0,'SELLING PRESSURE':0,'BUYING WATCH':1,'SELLING WATCH':1,'MIXED PRESSURE':2,'NEUTRAL':3,'HISTORICAL':4,'INSUFFICIENT HISTORY':5}
        return sorted(results,key=lambda r:(rank.get(r['status'],6),r['symbol']))
