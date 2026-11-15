import unittest
from datetime import datetime, timedelta, timezone

from services.candlestick_patterns import detect
from services.price_structure import build, clean, INDIA

START = datetime(2026, 11, 1, tzinfo=timezone.utc)


def candle(i, o, h, l, c, volume=100, **extra):
    return dict(timestamp=START+timedelta(days=i), open=o, high=h, low=l, close=c, volume=volume, **extra)


def decline():
    return [candle(i, v+.2, v+1, v-1, v) for i, v in enumerate([150, 145, 140, 135, 130, 128])]


def hammer():
    return candle(6, 126, 127.3, 120, 127)


def pattern(rows, name):
    return next(p for p in detect(rows, '1d')['patterns'] if p['name'] == name)


def mirror(rows):
    return [dict(r, open=300-r['open'], high=300-r['low'], low=300-r['high'], close=300-r['close']) for r in rows]


class PatternTests(unittest.TestCase):
    def test_hammer_after_decline_needs_confirmation(self):
        p = pattern(decline()+[hammer()], 'Hammer')
        self.assertEqual(p['bias'], 'bullish')
        self.assertEqual(p['state'], 'Awaiting confirmation')
        self.assertIn('127.30', p['confirmation'])
        self.assertIn('120.00', p['confirmation'])
        self.assertIn('falling', p['context'])

    def test_wick_poke_does_not_confirm_but_later_close_does(self):
        rows = decline()+[hammer(), candle(7, 127, 130, 126, 127.1)]
        self.assertEqual(pattern(rows, 'Hammer')['state'], 'Awaiting confirmation')
        rows[-1]['close'] = 129
        p = pattern(rows, 'Hammer')
        self.assertEqual(p['state'], 'Confirmed by later close')
        self.assertIsNotNone(p['followUpAt'])

    def test_invalidation_after_confirmation_remains_invalidated(self):
        rows = decline()+[hammer(), candle(7, 128, 130, 127, 129), candle(8, 122, 124, 118, 119)]
        self.assertEqual(pattern(rows, 'Hammer')['state'], 'Invalidated by later close')

    def test_unclosed_followthrough_cannot_confirm(self):
        rows = decline()+[hammer(), candle(7, 128, 130, 127, 129, developing=True)]
        self.assertEqual(pattern(rows, 'Hammer')['state'], 'Awaiting confirmation')

    def test_live_shape_is_forming_and_volume_not_full_bar(self):
        rows = decline()+[candle(6, 128, 129, 127, 128), dict(hammer(), timestamp=START+timedelta(days=7), developing=True)]
        p = pattern(rows, 'Hammer')
        self.assertTrue(p['forming'])
        self.assertIn('still open', p['state'])
        self.assertIsNone(p['volumeRatio'])
        self.assertIn('partial', p['volume'])

    def test_bullish_and_bearish_engulfing(self):
        rows = decline()[:5]+[candle(5, 129, 130, 124, 125), candle(6, 124, 132, 123, 131)]
        self.assertEqual(pattern(rows, 'Bullish engulfing')['bias'], 'bullish')
        self.assertEqual(pattern(mirror(rows), 'Bearish engulfing')['bias'], 'bearish')

    def test_engulfing_requires_opposite_bodies_and_prior_context(self):
        rows = decline()[:5]+[candle(5, 125, 130, 124, 129), candle(6, 124, 132, 123, 131)]
        self.assertFalse(any('engulfing' in p['name'] for p in detect(rows, '1d')['patterns']))
        rows = [dict(r, open=128, close=128, high=129, low=127) for r in decline()[:5]]+[candle(5, 129, 130, 124, 125), candle(6, 124, 132, 123, 131)]
        self.assertFalse(any(p['name'] == 'Bullish engulfing' for p in detect(rows, '1d')['patterns']))

    def test_morning_and_evening_star_and_gap_requirement(self):
        rows = decline()[:5]+[candle(5, 128, 129, 119, 120), candle(6, 117, 119, 116, 118), candle(7, 119, 128, 118, 127)]
        self.assertEqual(pattern(rows, 'Morning star')['bias'], 'bullish')
        self.assertEqual(pattern(mirror(rows), 'Evening star')['bias'], 'bearish')
        rows[-2].update(open=121, close=122, high=123, low=120)
        self.assertFalse(any(p['name'] == 'Morning star' for p in detect(rows, '1d')['patterns']))

    def test_hanging_man_shooting_star_and_inverted_hammer_context(self):
        rising = mirror(decline())
        hanging = candle(6, 175, 176.3, 169, 176)
        self.assertEqual(pattern(rising+[hanging], 'Hanging man')['bias'], 'bearish')
        shooting = candle(6, 175, 182, 174.7, 176)
        self.assertEqual(pattern(rising+[shooting], 'Shooting star')['bias'], 'bearish')
        inverted = candle(6, 125, 132, 124.7, 126)
        self.assertEqual(pattern(decline()+[inverted], 'Inverted hammer')['bias'], 'bullish')

    def test_neutral_doji_and_inside_bar_do_not_invent_direction(self):
        rows = decline()+[candle(6, 128, 130, 126, 128.1)]
        self.assertEqual(pattern(rows, 'Doji')['bias'], 'neutral')
        rows[-1] = candle(6, 127.8, 128.6, 127.4, 128.4)
        self.assertEqual(pattern(rows, 'Inside bar')['bias'], 'neutral')

    def test_volume_baseline_excludes_pattern_candle(self):
        prior = [candle(i, 200-i, 201-i, 199-i, 200-i) for i in range(22)]
        ending = candle(22, 176, 177.3, 170, 177, volume=250)
        p = pattern(prior+[ending], 'Hammer')
        self.assertEqual(p['volumeRatio'], 2.5)

    def test_old_patterns_not_presented_as_current_and_flat_bars_ignored(self):
        rows = decline()+[hammer()]+[candle(i, 130+i, 132+i, 129+i, 131+i) for i in range(7, 15)]
        self.assertFalse(any(p['name'] == 'Hammer' for p in detect(rows, '1d')['patterns']))
        flat = [candle(i, 100, 100, 100, 100) for i in range(10)]
        self.assertEqual(detect(flat, '1d')['patterns'], [])

    def test_insufficient_history_is_not_no_pattern_claim(self):
        self.assertIn('Insufficient history', detect([], '1d')['note'])

    def test_only_daily_hourly_views_get_patterns(self):
        rows = decline()+[hammer()]
        now = START+timedelta(days=9)
        hourly = [dict(r, timestamp=START.astimezone(INDIA).replace(hour=9, minute=15)+timedelta(hours=i)) for i, r in enumerate(rows)]
        views = build(rows, hourly, now)
        self.assertTrue(all('candlesticks' not in v for v in views[:4]))
        self.assertEqual(len(views[-2]['candlesticks']['patterns']), len(views[-1]['candlesticks']['patterns']))

    def test_clean_keeps_forming_only_for_pattern_inputs(self):
        rows = decline()+[dict(hammer(), developing=True)]
        now = START+timedelta(days=8)
        completed, _, _ = clean(rows, '1d', now)
        all_rows, _, developing = clean(rows, '1d', now, include_developing=True)
        self.assertEqual((len(completed), len(all_rows), developing), (6, 7, 1))
        self.assertTrue(all_rows[-1]['developing'])

    def test_hourly_pattern_does_not_bridge_missing_intraday_bars(self):
        rows = decline()+[hammer()]
        rows = [dict(r, timestamp=START.astimezone(INDIA).replace(hour=9, minute=15)+timedelta(hours=i)) for i, r in enumerate(rows)]
        rows[-1]['timestamp'] += timedelta(hours=2)
        self.assertFalse(any(p['name'] == 'Hammer' for p in detect(rows, '1h')['patterns']))
