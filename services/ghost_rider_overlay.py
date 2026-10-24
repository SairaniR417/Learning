"""Ghost rider v.2 overlay, ported from the user's Pine v6 source.

No stop-based resets, score thresholds for entries, or positive-price target
clamping: those are absent from the supplied script.
"""
from bisect import bisect_right
from datetime import timedelta
from math import isfinite

from scanner.strategies.ghost_rider import atr14, ema
from services.option_chain import INDIA

GREEN, RED, TURQUOISE = '#4caf50', '#f23645', '#40e0d0'
BLACK, GRAY, BLUE = '#363a45', '#787b86', '#2196f3'


def rma(values, period):
    result, seed, previous = [], [], None
    for value in values:
        if value is not None:
            if previous is None:
                seed.append(value)
                if len(seed) == period:
                    previous = sum(seed) / period
            else:
                previous += (value - previous) / period
        result.append(previous)
    return result


def rsi(values, period=14):
    changes = [None] + [values[i] - values[i-1] for i in range(1, len(values))]
    gains = rma([None if v is None else max(v, 0) for v in changes], period)
    losses = rma([None if v is None else max(-v, 0) for v in changes], period)
    # Pine: a zero loss returns 100; a zero gain returns 0.
    return [None if g is None or l is None else 100.0 if l == 0 else 0.0 if g == 0 else 100 - 100 / (1 + g / l)
            for g, l in zip(gains, losses)]


def adx14(rows):
    tr, plus, minus = [None], [None], [None]
    for i in range(1, len(rows)):
        a, b = rows[i], rows[i-1]
        up, down = a['high'] - b['high'], b['low'] - a['low']
        plus.append(up if up > down and up > 0 else 0.0)
        minus.append(down if down > up and down > 0 else 0.0)
        tr.append(max(a['high'] - a['low'], abs(a['high'] - b['close']), abs(a['low'] - b['close'])))
    smooth_tr, p, m = rma(tr, 14), rma(plus, 14), rma(minus, 14)
    dx = []
    for t, a, b in zip(smooth_tr, p, m):
        if t is None or a is None or b is None or t == 0:
            dx.append(None)
        else:
            total = a + b
            dx.append(abs(a - b) / (total if total else 1))
    return [None if value is None else value * 100 for value in rma(dx, 14)]


def calculate(rows, five_rows, interval=5, multiplier=1.5):
    if not isfinite(multiplier) or multiplier < .1:
        raise ValueError('SL ATR multiplier must be at least 0.1')
    if not rows:
        return dict(points=[], signals=[], levels=[], dashboard=[], setup=None, fiveMinuteAsOf=None)
    closes = [r['close'] for r in rows]
    fast, slow = ema(closes, 9), ema(closes, 21)
    atr, oscillator, adx = atr14(rows), rsi(closes), adx14(rows)
    short, long = ema(closes, 12), ema(closes, 26)
    macd = [a-b for a, b in zip(short, long)]
    macd_signal = ema(macd, 9)
    five_times = [r['timestamp'] + timedelta(minutes=5) for r in five_rows]
    five_rsi = rsi([r['close'] for r in five_rows]) if five_rows else []
    state, setup, points, signals, session = 0, None, [], [], None
    cumulative_pv = cumulative_v = 0.0
    latest = None
    for i, row in enumerate(rows):
        day = row['timestamp'].astimezone(INDIA).date()
        if day != session:
            cumulative_pv = cumulative_v = 0.0
            session = day
        cumulative_pv += (row['high'] + row['low'] + row['close']) / 3 * row['volume']
        cumulative_v += row['volume']
        vwap = cumulative_pv / cumulative_v if cumulative_v else None
        cross_buy = i > 0 and fast[i] > slow[i] and fast[i-1] <= slow[i-1] and state <= 0
        cross_sell = i > 0 and fast[i] < slow[i] and fast[i-1] >= slow[i-1] and state >= 0
        signal = 'BUY' if cross_buy else 'SELL' if cross_sell else None
        if signal:
            state = 1 if cross_buy else -1
            risk = None if atr[i] is None else atr[i] * multiplier
            setup = dict(signal=signal, signalAt=row['timestamp'].isoformat(), index=i, entry=row['close'],
                         stopLoss=None if risk is None else row['close'] - state * risk, risk=risk,
                         targets=[dict(number=n, price=None if risk is None else row['close'] + state * risk * n, hit=False) for n in range(1, 6)])
            signals.append(dict(timestamp=row['timestamp'].isoformat(), label=signal, side=signal))
        if setup:
            for target in setup['targets']:
                if target['price'] is not None:
                    target['hit'] |= row['high'] >= target['price'] if state == 1 else row['low'] <= target['price']
        retest = (state == 1 and row['low'] <= fast[i] and row['low'] > slow[i]) or (state == -1 and row['high'] >= fast[i] and row['high'] < slow[i])
        points.append(dict(timestamp=row['timestamp'].isoformat(), ema9=fast[i], ema21=slow[i], vwap=vwap,
                           vwapColor=GREEN if vwap is not None and row['close'] > vwap else RED,
                           ribbonColor=GREEN if fast[i] > slow[i] else RED,
                           barColor=BLACK if signal else '#ff9800' if retest else None))
        if i == len(rows) - 1:
            index5 = bisect_right(five_times, row['timestamp'] + timedelta(minutes=interval)) - 1
            rsi5 = five_rsi[index5] if index5 >= 0 else None
            average_vol = sum(r['volume'] for r in rows[i-19:i+1]) / 20 if i >= 19 else None
            above = vwap is not None and row['close'] > vwap
            below = vwap is not None and row['close'] < vwap
            rs, power = oscillator[i], adx[i]
            high_vol = average_vol is not None and row['volume'] > average_vol
            bull = sum([above, rs is not None and rs > 50, macd[i] > macd_signal[i], fast[i] > slow[i],
                        power is not None and power > 25 and row['close'] > fast[i],
                        high_vol and row['close'] > row['open'], rsi5 is not None and rsi5 > 50]) / 7 * 100
            bear = sum([below, rs is not None and rs < 50, macd[i] < macd_signal[i], fast[i] < slow[i],
                        power is not None and power > 25 and row['close'] < fast[i],
                        high_vol and row['close'] < row['open'], rsi5 is not None and rsi5 < 50]) / 7 * 100
            bias = 'STRONG BULL' if bull-bear >= 40 else 'STRONG BEAR' if bear-bull >= 40 else 'MILD BULL' if bull > bear else 'MILD BEAR'
            latest = dict(bull=bull, bear=bear, bias=bias, rsi=rs, rsi5=rsi5, adx=power, atr=atr[i],
                          macd=macd[i], macdSignal=macd_signal[i], highVol=high_vol, above=above,
                          emaBull=fast[i] > slow[i], status='NEW' if signal else 'WAIT',
                          fiveAt=five_rows[index5]['timestamp'].isoformat() if index5 >= 0 else None)
    def display(value, digits=1):
        return 'n/a' if value is None else f'{value:.{digits}f}'.rstrip('0').rstrip('.') if digits else str(round(value))
    def row(title, value, color=BLACK, background=None):
        return dict(title=title, value=value, color=color, background=background)
    a = latest
    dashboard = [
        row('Pullers', f"{a['bull']:.0f}%", '#ffffff', GREEN), row('Draggers', f"{a['bear']:.0f}%", '#ffffff', RED),
        row('BIAS', a['bias'], '#ffffff', GREEN if a['bias'] == 'STRONG BULL' else RED if a['bias'] == 'STRONG BEAR' else GRAY),
        row('Price/VWAP', 'ABOVE' if a['above'] else 'BELOW', GREEN if a['above'] else RED),
        row('RSI (14)', display(a['rsi']), GREEN if a['rsi'] is not None and a['rsi'] > 50 else RED),
        row('MACD Trend', 'BULL' if a['macd'] > a['macdSignal'] else 'BEAR', GREEN if a['macd'] > a['macdSignal'] else RED),
        row('ADX Power', display(a['adx']), GREEN if a['adx'] is not None and a['adx'] > 25 else GRAY),
        row('EMA Cross', 'BULL' if a['emaBull'] else 'BEAR', GREEN if a['emaBull'] else RED), row('ATR 14', display(a['atr'], 2)),
        row('Vol Status', 'HIGH' if a['highVol'] else 'LOW', GREEN if a['highVol'] else GRAY),
        row('5m RSI', display(a['rsi5']), GREEN if a['rsi5'] is not None and a['rsi5'] > 50 else RED),
        row('MACD Main', display(a['macd'], 2)), row('MACD Sig', display(a['macdSignal'], 2)),
        row('Trend Str', 'STRONG' if a['adx'] is not None and a['adx'] > 25 else 'WEAK', GREEN if a['adx'] is not None and a['adx'] > 25 else RED),
        row('Status', a['status']), row('Ghostrider', 'Bullet', BLUE)]
    levels = []
    if setup:
        levels = [dict(label='ENTRY', price=setup['entry'], color=BLUE, width=2, dashed=False, icon='')]
        if setup['stopLoss'] is not None:
            levels.append(dict(label='SL', price=setup['stopLoss'], color=RED, width=2, dashed=False, icon=''))
        icons = ['🎯', '⚡', '🚀', '💎', '👑']
        for target in setup['targets']:
            if target['price'] is not None:
                n = target['number']
                levels.append(dict(label=f'TP{n}', price=target['price'], color=TURQUOISE if target['hit'] else GREEN if n <= 3 else '#006400' if n == 4 else '#004600',
                                   labelColor=GREEN if n <= 3 else '#006400' if n == 4 else '#004600', width=1 if n <= 3 else 2 if n == 4 else 3,
                                   dashed=n <= 3, hit=target['hit'], icon=icons[n-1] if target['hit'] else ''))
    return dict(points=points, signals=signals, levels=levels, dashboard=dashboard,
                setup=setup, fiveMinuteAsOf=a['fiveAt'], multiplier=multiplier)


def strategy_card(overlay, count):
    setup=overlay['setup']
    return dict(id='ghost_rider',name='Ghost rider v.2',minimumCandles=2,availableCandles=count,
        status=setup['signal'] if setup else 'NO_SETUP' if count else 'NO_HISTORY',
        bias='bullish' if setup and setup['signal']=='BUY' else 'bearish' if setup else 'neutral',
        signalAt=setup['signalAt'] if setup else None,
        markers=[dict(timestamp=s['timestamp'],label=s['label'],bias='bullish' if s['side']=='BUY' else 'bearish') for s in overlay['signals']],
        levels=[dict(label=l['label'],price=l['price']) for l in overlay['levels']],
        metrics=[dict(label=l['label'],value=l['price']) for l in overlay['levels']],
        checks=[dict(label=f"TP{t['number']} touched",passed=t['hit']) for t in setup['targets']] if setup else [],
        scenario='EMA 9/21 crossovers; entry at signal close; ATR 14 stop and five targets. Only an opposite crossover replaces the setup. Dashboard votes do not filter entries.' if count else 'No candle history available for this timeframe.')
