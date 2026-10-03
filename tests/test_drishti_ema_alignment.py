import unittest

from drishti.ema_alignment import AlignmentStatus, analyze_ema_alignment
from drishti.ema import calculate_ema


def candles(closes):
    return [{"timestamp": f"candle-{index}", "close": close} for index, close in enumerate(closes)]


class EmaAlignmentTests(unittest.TestCase):
    def test_insufficient_history(self):
        result = analyze_ema_alignment(candles([10] * 199))
        self.assertEqual(result.status, AlignmentStatus.INSUFFICIENT_HISTORY)
        self.assertIsNone(result.ema.ema200)

    def test_newly_aligned_and_transition_index(self):
        closes = list(range(300, 100, -1)) + [500 + index * 20 for index in range(7)]
        result = analyze_ema_alignment(candles(closes), symbol='TEST')
        self.assertEqual(result.status, AlignmentStatus.NEWLY_ALIGNED)
        self.assertTrue(result.bullishAlignment)
        self.assertEqual(result.transitionIndex, 206)
        self.assertEqual(result.transitionTimestamp, candles(closes)[206]['timestamp'])
        self.assertEqual(result.alignedSince, result.transitionTimestamp)

    def test_aligned_after_transition_candle(self):
        closes = list(range(300, 100, -1)) + [500 + index * 20 for index in range(8)]
        result = analyze_ema_alignment(candles(closes))
        self.assertEqual(result.status, AlignmentStatus.ALIGNED)
        self.assertTrue(result.bullishAlignment)

    def test_price_below_ema_breaks_full_predicate(self):
        closes = list(range(300, 100, -1)) + [1000, 1]
        result = analyze_ema_alignment(candles(closes))
        self.assertEqual(result.status, AlignmentStatus.NOT_ALIGNED)
        self.assertFalse(result.conditions.priceAboveEma9)

    def test_ema_relationships_can_become_true_on_different_candles(self):
        closes = list(range(300, 100, -1)) + [500 + index * 20 for index in range(7)]
        result = analyze_ema_alignment(candles(closes))
        self.assertIn(result.status, (AlignmentStatus.ALIGNED, AlignmentStatus.NEWLY_ALIGNED))
        self.assertTrue(result.conditions.ema9AboveEma20)
        self.assertTrue(result.conditions.ema20AboveEma50)
        self.assertTrue(result.conditions.ema50AboveEma200)
        at_200 = analyze_ema_alignment(candles(closes[:201]))
        self.assertTrue(at_200.conditions.ema9AboveEma20)
        self.assertTrue(at_200.conditions.ema20AboveEma50)
        self.assertFalse(at_200.conditions.ema50AboveEma200)
        self.assertEqual(result.transitionIndex, 206)

    def test_first_valid_ema200_is_not_a_confirmed_new_transition(self):
        closes = list(range(1, 200)) + [1000]
        result = analyze_ema_alignment(candles(closes))
        self.assertEqual(result.status, AlignmentStatus.ALIGNED)
        self.assertIsNone(result.transitionIndex)
        self.assertIsNone(result.transitionTimestamp)

    def test_each_rule_relationship_is_exposed(self):
        closes = list(range(300, 100, -1)) + [500 + index * 20 for index in range(7)]
        result = analyze_ema_alignment(candles(closes))
        self.assertTrue(result.conditions.priceAboveEma9)
        self.assertTrue(result.conditions.priceAboveEma20)
        self.assertTrue(result.conditions.priceAboveEma50)
        self.assertTrue(result.conditions.priceAboveEma200)
        self.assertTrue(result.conditions.ema9AboveEma20)
        self.assertTrue(result.conditions.ema20AboveEma50)
        self.assertTrue(result.conditions.ema50AboveEma200)

    def test_history_values_have_no_lookahead(self):
        closes = list(range(300, 100, -1)) + [500 + index * 20 for index in range(7)]
        longer = closes + [800]
        a = [calculate_ema(closes, period)[-1] for period in (9, 20, 50, 200)]
        b = [calculate_ema(longer, period)[len(closes) - 1] for period in (9, 20, 50, 200)]
        self.assertEqual(a, b)
        self.assertEqual(analyze_ema_alignment(candles(closes)).status, AlignmentStatus.NEWLY_ALIGNED)


if __name__ == '__main__':
    unittest.main()
