"""Explicit heuristic candle shapes, with prior context and close-based follow-through.

Definitions: https://chartschool.stockcharts.com/table-of-contents/chart-analysis/candlestick-charts/candlestick-pattern-dictionary
Thresholds below are this app's documented implementation, not performance estimates.
"""
from services.market_sync import INDIA


def geometry(row):
    span = row['high'] - row['low']
    body = abs(row['close'] - row['open'])
    return span, body, row['high']-max(row['open'], row['close']), min(row['open'], row['close'])-row['low']


def prior_trend(rows):
    if len(rows) < 5:
        return 'unknown'
    prior = rows[-5:]
    average = sum(r['high']-r['low'] for r in prior)/5
    change = prior[-1]['close']-prior[0]['close']
    return 'rising' if change > average*.5 else 'falling' if change < -average*.5 else 'mixed'


def adjacent(a, b, frame):
    gap = (b['timestamp']-a['timestamp']).total_seconds()
    if frame == '1d':
        return 0 < gap <= 5*24*3600
    first, second = a['timestamp'].astimezone(INDIA), b['timestamp'].astimezone(INDIA)
    if first.date() == second.date():
        return 0 < gap <= 3600
    return 0 < gap <= 96*3600 and (first.hour, first.minute) >= (14, 15) and (second.hour, second.minute) == (9, 15)


def shapes(rows, i):
    """One result per candle, preferring three/two-candle shapes over single ones."""
    row = rows[i]
    span, body, upper, lower = geometry(row)
    if span <= 0:
        return None
    # Star patterns require a body gap; gapless approximations are not called stars.
    if i >= 2:
        a, b = rows[i-2:i]
        ar, ab, _, _ = geometry(a)
        _, bb, _, _ = geometry(b)
        trend = prior_trend(rows[:i-2])
        if ar > 0 and ab/ar >= .5 and bb <= ab*.3 and body/span >= .5:
            if trend == 'falling' and a['close'] < a['open'] and max(b['open'], b['close']) < a['close'] and row['close'] > row['open'] and row['close'] > (a['open']+a['close'])/2:
                return 'Morning star', 'bullish', 3, 'A large falling body, a gapped-down small body, then a rising close above the first body’s midpoint.'
            if trend == 'rising' and a['close'] > a['open'] and min(b['open'], b['close']) > a['close'] and row['close'] < row['open'] and row['close'] < (a['open']+a['close'])/2:
                return 'Evening star', 'bearish', 3, 'A large rising body, a gapped-up small body, then a falling close below the first body’s midpoint.'
    if i >= 1:
        previous = rows[i-1]
        pr, pb, _, _ = geometry(previous)
        trend = prior_trend(rows[:i-1])
        if pr > 0 and pb/pr > .1 and body > pb and body/span >= .5:
            if trend == 'falling' and previous['close'] < previous['open'] and row['close'] > row['open'] and row['open'] <= previous['close'] and row['close'] >= previous['open']:
                return 'Bullish engulfing', 'bullish', 2, 'The rising real body covers the preceding falling body after a prior decline.'
            if trend == 'rising' and previous['close'] > previous['open'] and row['close'] < row['open'] and row['open'] >= previous['close'] and row['close'] <= previous['open']:
                return 'Bearish engulfing', 'bearish', 2, 'The falling real body covers the preceding rising body after a prior advance.'
    trend = prior_trend(rows[:i])
    if .1 < body/span <= .35:
        if lower >= 2*body and upper <= body*.5:
            if trend == 'falling':
                return 'Hammer', 'bullish', 1, 'A small body near the top and a lower shadow at least twice its size, after a decline.'
            if trend == 'rising':
                return 'Hanging man', 'bearish', 1, 'A small body near the top and a long lower shadow, after an advance.'
        if upper >= 2*body and lower <= body*.5:
            if trend == 'rising':
                return 'Shooting star', 'bearish', 1, 'A small body near the bottom and an upper shadow at least twice its size, after an advance.'
            if trend == 'falling':
                return 'Inverted hammer', 'bullish', 1, 'A small body near the bottom and a long upper shadow, after a decline.'
    if body/span <= .1:
        return 'Doji', 'neutral', 1, 'Open and close are within 10% of the candle range: indecision, without a directional signal on its own.'
    if i >= 1 and row['high'] < rows[i-1]['high'] and row['low'] > rows[i-1]['low']:
        return 'Inside bar', 'neutral', 2, 'The entire latest range sits inside the preceding candle: compression, with direction unresolved.'
    return None


def detect(rows, frame):
    """Review the last three closed bars and optional newest developing bar."""
    completed = [r for r in rows if not r.get('developing')]
    report = dict(patterns=[], checkedThrough=rows[-1]['timestamp'].isoformat() if rows else None,
                  note='')
    if len(completed) < 7:
        report['note'] = 'Insufficient history: need at least seven completed bars for this pattern review.'
        return report
    # A malformed gap must not be bridged into a multi-candle pattern. Daily
    # weekends/holidays are permitted, but unusually large gaps remain excluded.
    for i in range(max(0, len(completed)-3), len(rows)):
        match = shapes(rows, i)
        if not match:
            continue
        name, bias, length, explanation = match
        start = i-length+1
        if any(not adjacent(rows[j-1], rows[j], frame) for j in range(max(1, start-5), i+1)):
            continue
        segment = rows[start:i+1]
        high, low = max(r['high'] for r in segment), min(r['low'] for r in segment)
        forming = bool(rows[i].get('developing'))
        state = 'Forming · candle still open' if forming else 'Awaiting confirmation' if bias != 'neutral' else 'Indecision / watch range'
        follow_up = None
        for j, later in enumerate(rows[i+1:], start=i+1):
            if later.get('developing'):
                continue
            if not adjacent(rows[j-1], later, frame):
                state = 'Follow-through unavailable · history gap'
                break
            if bias == 'neutral':
                if later['close'] > high or later['close'] < low:
                    state = 'Range broken upward' if later['close'] > high else 'Range broken downward'
                    follow_up = later['timestamp'].isoformat()
                    break
            else:
                failed = later['close'] < low if bias == 'bullish' else later['close'] > high
                confirmed = later['close'] > high if bias == 'bullish' else later['close'] < low
                if failed:
                    state = 'Invalidated by later close'
                    follow_up = later['timestamp'].isoformat()
                    break
                if confirmed and state == 'Awaiting confirmation':
                    state = 'Confirmed by later close'
                    follow_up = later['timestamp'].isoformat()
        before = rows[:start]
        context = f"Prior five-bar context: {prior_trend(before)}."
        if len(before) >= 5:
            prior = before[-20:]
            range_low, range_high = min(r['low'] for r in prior), max(r['high'] for r in prior)
            tolerance = max(rows[i]['close']*.003, sum(r['high']-r['low'] for r in prior)/len(prior)*.5)
            if abs(low-range_low) <= tolerance:
                context += f' Near the preceding {len(prior)}-bar range low ₹{range_low:,.2f}.'
            if abs(high-range_high) <= tolerance:
                context += f' Near the preceding {len(prior)}-bar range high ₹{range_high:,.2f}.'
        ratio = None
        if forming:
            volume = 'Volume is partial while this candle is open; no full-bar volume confirmation yet.'
        elif i >= 20 and sum(r['volume'] for r in rows[i-20:i]) > 0:
            ratio = rows[i]['volume']/(sum(r['volume'] for r in rows[i-20:i])/20)
            volume = f'Pattern-ending candle volume: {ratio:.2f}× the preceding 20-bar average.'
        else:
            volume = 'Not enough nonzero prior volume history for a 20-bar comparison.'
        if frame == '1h':
            volume += ' Hourly volume is not adjusted for time of day; the final session bar may be shorter.'
        confirmation = (f'Watch a later completed close above ₹{high:,.2f}; a close below ₹{low:,.2f} invalidates the bullish interpretation.' if bias == 'bullish' else
                        f'Watch a later completed close below ₹{low:,.2f}; a close above ₹{high:,.2f} invalidates the bearish interpretation.' if bias == 'bearish' else
                        f'Watch a completed close outside ₹{low:,.2f}–₹{high:,.2f} to resolve the range; the shape alone gives no direction.')
        if state.startswith('Confirmed'):
            confirmation = 'A subsequent completed close crossed the pattern range in the indicated direction. This records follow-through, not a forecast.'
        elif state.startswith('Invalidated'):
            confirmation = 'A subsequent completed close crossed the opposite boundary. The original directional interpretation no longer holds.'
        elif state.startswith('Range broken'):
            confirmation = 'A subsequent completed close left the pattern range. The indecision range is resolved; continuation is not guaranteed.'
        if forming:
            confirmation = 'First wait for this candle to close: its shape and boundaries can still change. ' + confirmation
        report['patterns'].append(dict(name=name, bias=bias, state=state, forming=forming,
                                      at=rows[i]['timestamp'].isoformat(), startAt=segment[0]['timestamp'].isoformat(),
                                      high=high, low=low, explanation=explanation, context=context,
                                      confirmation=confirmation, followUpAt=follow_up, volume=volume, volumeRatio=round(ratio, 2) if ratio is not None else None))
    report['patterns'].reverse()
    report['note'] = ('Latest three completed bars plus any available developing bar reviewed. Open-candle patterns are provisional; closed shapes still need follow-through.' if report['patterns'] else
                      'No supported candlestick pattern detected in the latest three completed bars or available developing bar. This is not an exhaustive pattern scan.')
    return report
