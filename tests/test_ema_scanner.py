import unittest
from datetime import date, timedelta

from scanner.ema_scanner import scan_ema_universe


def make_candles(closes):
    start = date(2025, 1, 1)
    return [
        {"timestamp": (start + timedelta(days=index)).isoformat(), "close": close}
        for index, close in enumerate(closes)
    ]


class EmaScannerTests(unittest.IsolatedAsyncioTestCase):
    async def test_matches_close_above_ema_and_sma_values(self):
        candles = make_candles([100] * 200 + [150])

        async def fetch_history(*_args):
            return {"candles": candles}

        response = await scan_ema_universe(
            [{"key": "NSE_EQ|TEST", "symbol": "TEST"}],
            fetch_history,
            unit="days",
            interval=1,
            from_date=date(2025, 1, 1),
            to_date=date(2025, 7, 1),
        )

        self.assertEqual(response["matched"], 1)
        result = response["results"][0]
        self.assertEqual(result["close"], 150)
        self.assertEqual(result["sma50"], 101)
        self.assertEqual(result["sma200"], 100.25)
        self.assertGreater(result["close"], result["ema9"])
        self.assertGreater(result["close"], result["ema20"])
        self.assertEqual(result["status"], "NEWLY_ALIGNED")
        self.assertEqual(result["matchedSince"], candles[-1]["timestamp"])

    async def test_does_not_match_when_close_is_not_above_all_averages(self):
        candles = make_candles([100] * 200 + [99])

        async def fetch_history(*_args):
            return {"candles": candles}

        response = await scan_ema_universe(
            [{"key": "NSE_EQ|TEST", "symbol": "TEST"}],
            fetch_history,
            unit="days",
            interval=1,
            from_date=date(2025, 1, 1),
            to_date=date(2025, 7, 1),
        )

        self.assertEqual(response["matched"], 0)
        self.assertEqual(response["results"], [])


if __name__ == "__main__":
    unittest.main()
