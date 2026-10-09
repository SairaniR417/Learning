"""Tests for the pluggable strategy engine, vectorized Polars execution, and caching."""

from datetime import datetime, timezone
import unittest
import polars as pl

from scanner.strategies.base import StrategyMetadata, StrategyParameter
from scanner.strategies.ema_alignment import EmaAlignmentStrategy
from scanner.strategies.registry import StrategyRegistry
from scanner.strategies.rsi_reversal import RsiStrategy


class StrategyEngineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.registry = StrategyRegistry()

    def test_registered_strategies_list(self):
        strategies = self.registry.list_strategies()
        ids = [s["id"] for s in strategies]
        self.assertIn("ema_sma_alignment", ids)
        self.assertIn("rsi_reversal", ids)

    def test_vectorized_ema_alignment(self):
        strat = EmaAlignmentStrategy()
        # Generate 210 ascending candles for INFY
        now = datetime.now(timezone.utc)
        timestamps = [now] * 210
        closes = [float(100 + i) for i in range(210)]
        df = pl.DataFrame({
            "instrument_key": ["NSE_EQ|INE009A01021"] * 210,
            "timestamp": timestamps,
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": [1000] * 210,
        })
        instruments_map = {
            "NSE_EQ|INE009A01021": {"symbol": "INFY", "name": "Infosys Ltd", "exchange": "NSE"}
        }
        results = strat.run(df, instruments_map, {"ema1": 9, "ema2": 20, "sma1": 50, "sma2": 200})
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["symbol"], "INFY")
        self.assertTrue(results[0]["close"] > results[0]["ema9"])
        self.assertTrue(results[0]["ema9"] > results[0]["ema20"])

    def test_vectorized_rsi_reversal(self):
        strat = RsiStrategy()
        # Series dropping and then bouncing back up
        closes = [100.0 - i * 2 for i in range(25)] + [52.0, 56.0, 62.0, 68.0, 75.0]
        timestamps = [datetime.now(timezone.utc)] * len(closes)
        df = pl.DataFrame({
            "instrument_key": ["NSE_EQ|INE002A01018"] * len(closes),
            "timestamp": timestamps,
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [500] * len(closes),
        })
        instruments_map = {
            "NSE_EQ|INE002A01018": {"symbol": "RELIANCE", "name": "Reliance Industries", "exchange": "NSE"}
        }
        results = strat.run(df, instruments_map, {"period": 14, "oversold": 30.0})
        self.assertIsInstance(results, list)


if __name__ == "__main__":
    unittest.main()
