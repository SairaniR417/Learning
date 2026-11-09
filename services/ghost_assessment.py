"""Explain the existing Ghost dashboard and risk levels, without changing Pine entries."""
from datetime import datetime, timedelta, timezone
from services.market_sync import INDIA
from services.market_session import session_context, opening_range, utc, clean


def assess(rows, five, overlay, interval, now=None, developing=False):
    now = now or datetime.now(timezone.utc)
    if not rows:
        return None
    metrics = overlay.get('dashboardMetrics', {})
    latest, setup = rows[-1], overlay.get('setup')
    price = latest['close']
    end = utc(latest['timestamp']) + timedelta(minutes=interval)
    if interval < 1440:
        local = utc(latest['timestamp']).astimezone(INDIA)
        end = min(end, local.replace(hour=15, minute=30, second=0, microsecond=0))
    aligned_five = [r for r in five if utc(r['timestamp']) + timedelta(minutes=5) <= min(end, now)]
    day = utc(latest['timestamp']).astimezone(INDIA).date()
    context = session_context(rows, interval)
    # A complete 5m session is more precise than a partial selected timeframe.
    same_day_five = [r for r in aligned_five if utc(r['timestamp']).astimezone(INDIA).date() == day]
    if interval < 1440 and same_day_five:
        context = session_context(same_day_five, 5)
    if context['dayOpen'] is not None:
        current = [r for r in rows if utc(r['timestamp']).astimezone(INDIA).date() == day and clean(r)]
        high = max([context['dayHigh']] + [r['high'] for r in current])
        low = min([context['dayLow']] + [r['low'] for r in current])
        context.update(dayHigh=high, dayLow=low, fromOpenPct=(price / context['dayOpen'] - 1) * 100,
                       dayHighPct=(high / context['dayOpen'] - 1) * 100,
                       dayLowPct=(low / context['dayOpen'] - 1) * 100,
                       dayRangePosition=(price - low) / (high - low) * 100 if high > low else 50.)
    orb = opening_range(aligned_five, now=min(end + timedelta(seconds=5), now))
    if orb['sessionDate'] != day.isoformat():
        orb = dict(orb, orbState='NO_HISTORY', orbHigh=None, orbLow=None, orbReason='No matching-session 5m history.')
    bull, bear = metrics.get('bull', 0), metrics.get('bear', 0)
    direction = 'BULLISH' if bull > bear else 'BEARISH' if bear > bull else 'NEUTRAL'
    adx = metrics.get('adx')
    strength = 'STRONG' if adx is not None and adx > 25 else 'WEAK' if adx is not None else 'WARMING UP'
    stale = day != now.astimezone(INDIA).date() or (interval < 1440 and now - end > timedelta(minutes=max(15, interval * 2)))
    result = dict(**context, assessmentAsOf=latest['timestamp'].isoformat(), assessmentPrice=price,
                  strength=f'{strength} {direction}', strengthScore=round(max(bull, bear), 1),
                  pullersPct=bull, draggersPct=bear, rsi14=metrics.get('rsi'), adx=adx,
                  macdMain=metrics.get('macd'), macdSignal=metrics.get('macdSignal'),
                  macdHistogram=metrics.get('macd', 0) - metrics.get('macdSignal', 0),
                  relativeVolume=metrics.get('relativeVolume'), volumeStatus='HIGH' if metrics.get('highVol') else 'LOW',
                  vwap=overlay['points'][-1]['vwap'], ema9=overlay['points'][-1]['ema9'], ema21=overlay['points'][-1]['ema21'],
                  rsi5m=metrics.get('rsi5'), atr=metrics.get('atr'),
                  decision='WAIT', decisionReason='', nearestLevel=None, nearestLevelPct=None,
                  stopDistancePct=None, nextTarget=None, nextTargetPct=None, remainingRR=None, rrTarget=None,
                  progressR=None, stopTouched=False, stale=stale, developing=developing,
                  orbState=orb['orbState'], orbReason=orb['orbReason'], orbHigh=orb['orbHigh'], orbLow=orb['orbLow'])
    reasons = []
    if stale:
        reasons.append('Stored/old session; refresh current candles before considering an entry.')
    if developing:
        reasons.append('Developing candle: wait for a completed bar.')
    if context['dayOpen'] is None:
        reasons.append('Session open is missing.')
    if not setup:
        reasons.append('No EMA crossover setup.')
    else:
        sign = 1 if setup['signal'] == 'BUY' else -1
        stop, risk = setup['stopLoss'], setup['risk']
        levels = [(f"TP{t['number']}", t['price']) for t in setup['targets'] if t['price'] is not None and t['price'] > 0]
        if stop is not None and stop > 0:
            levels.append(('SL', stop))
            stopped = any(r['low'] <= stop if sign == 1 else r['high'] >= stop for r in rows[setup['index']:])
            result.update(stopTouched=stopped, stopDistancePct=sign * (price - stop) / price * 100)
            if stopped:
                reasons.append('Stop touched since the signal; the original Pine setup remains on the chart.')
        else:
            reasons.append('No valid positive stop-loss level.')
        if levels:
            name, level = min(levels, key=lambda item: abs(item[1] - price))
            gap = abs(price - level) / price * 100
            near = abs(price - level) <= (metrics.get('atr') or price * .01) * .25
            result.update(nearestLevel=('Near ' if near else 'Closest ') + name, nearestLevelPct=gap)
        ahead = [(f"TP{t['number']}", t['price']) for t in setup['targets']
                 if t['price'] is not None and t['price'] > 0 and sign * (t['price'] - price) > 0 and not t['hit']]
        if ahead:
            target, value = ahead[0]
            distance = sign * (value - price)
            loss = sign * (price - stop) if stop is not None else 0
            result.update(nextTarget=target, nextTargetPct=distance / price * 100)
            # TP1 is a 1R scale-out. Assess an entry against TP2, or the next
            # untouched target beyond TP2; never pick TP5 merely to pass the gate.
            plan = next(((name, value) for name, value in ahead if name != 'TP1'), None)
            if plan:
                result.update(rrTarget=plan[0], remainingRR=sign * (plan[1] - price) / loss if loss > 0 else None)
        else:
            reasons.append('No untouched target remains ahead of price.')
        if risk and risk > 0:
            result['progressR'] = sign * (price - setup['entry']) / risk
        else:
            reasons.append('ATR/risk is warming up.')
        if len(rows) - 1 - setup['index'] > 5:
            reasons.append('Crossover is more than five bars old.')
        five_at = overlay.get('fiveMinuteAsOf')
        five_ok = five_at is not None and datetime.fromisoformat(five_at).astimezone(INDIA).date() == day and metrics.get('rsi5') is not None
        expected_end = min(end, now)
        if interval >= 1440:
            expected_end = min(expected_end, utc(latest['timestamp']).astimezone(INDIA).replace(hour=15, minute=30))
        if five_ok:
            five_ok = timedelta(0) <= expected_end - (datetime.fromisoformat(five_at) + timedelta(minutes=5)) <= timedelta(minutes=10)
        if len(rows) < 35 or metrics.get('rsi') is None or adx is None or not five_ok:
            reasons.append('Indicator warm-up or matching-session 5m RSI is missing.')
        if adx is None or adx <= 25:
            reasons.append('ADX must exceed 25 for trend confirmation; ADX itself has no direction.')
        own, opposing = (bull, bear) if sign == 1 else (bear, bull)
        if own < 5 / 7 * 100 - .01 or own - opposing < 3 / 7 * 100 - .01:
            reasons.append('Needs at least 5 of 7 directional votes and a 3-vote lead.')
        if result['remainingRR'] is None or result['remainingRR'] < 1.5:
            reasons.append('Remaining reward to TP2 (or the next untouched target beyond it) is below 1.5 times stop risk.')
        if orb['orbState'] == ('BEARISH' if sign == 1 else 'BULLISH'):
            reasons.append('Opening-range hold opposes the setup.')
        if not reasons:
            result['decision'] = 'BUY CANDIDATE' if sign == 1 else 'SELL CANDIDATE'
    result['decisionReason'] = ' '.join(reasons) or f"Fresh crossover, indicator confluence and remaining R/R to {result['rrTarget']} meet the screening rules. Candidate only; costs and execution are not modelled."
    return result
