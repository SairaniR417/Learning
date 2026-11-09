"""Completed-bar breadth, volume weighting and crossover boundaries."""
import asyncio
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import AsyncMock, patch

import polars as pl
from fastapi import HTTPException, BackgroundTasks
from services.overview_signals import calculate, overview_signals, repair_history, _repair_jobs

NOW = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)


def candles(closes, start=None, step=None):
    start = start or datetime(2026, 1, 1, tzinfo=timezone.utc)
    step = step or timedelta(days=1)
    return [dict(instrument_key="A", timestamp=start + i * step, open=c, high=c, low=c, close=c, volume=100)
            for i, c in enumerate(closes)]


class OverviewSignalsTests(unittest.TestCase):
    def test_sma_positions_and_rolling_vwap(self):
        rows = candles(list(range(100, 160)))
        result = calculate(rows, "1d", NOW)
        self.assertEqual(result["sma20"], 149.5)
        self.assertEqual(result["sma50"], 134.5)
        self.assertEqual(result["vwap"], 149.5)
        self.assertEqual(result["vwapPosition"], "above")
        self.assertEqual(result["maTrend"], "above")
        self.assertIsNone(result["crossover"])

    def test_bullish_and_bearish_cross_require_previous_bar(self):
        for last, direction in ((110, "bullish"), (90, "bearish")):
            self.assertEqual(calculate(candles([100] * 50 + [last]), "1d", NOW)["crossover"], direction)
        self.assertIsNone(calculate(candles([100] * 51), "1d", NOW)["crossover"])
        self.assertIsNone(calculate(candles([100] * 49 + [110]), "1d", NOW)["crossover"])

    def test_session_vwap_resets_and_is_volume_weighted(self):
        rows = candles([100, 200], datetime(2026, 11, 6, 4, tzinfo=timezone.utc), timedelta(minutes=5))
        today = candles([10, 20], datetime(2026, 11, 9, 4, tzinfo=timezone.utc), timedelta(minutes=5))
        today[1]["volume"] = 300
        result = calculate(rows + today, "5m", NOW)
        self.assertEqual(result["vwap"], 17.5)
        self.assertEqual(result["vwapPosition"], "above")

    def test_vwap_uses_typical_price(self):
        rows = candles([20], datetime(2026, 11, 9, 4, tzinfo=timezone.utc))
        rows[0].update(high=40, low=10)
        self.assertAlmostEqual(calculate(rows, "5m", NOW)["vwap"], 70 / 3)

    def test_zero_volume_and_insufficient_history_are_unknown(self):
        rows = candles([100] * 19)
        for row in rows:
            row["volume"] = 0
        result = calculate(rows, "1d", NOW)
        for key in ("vwap", "sma20", "sma50", "crossover", "maTrend", "vwapPosition"):
            self.assertIsNone(result[key])
        self.assertEqual(result["price"], 100)
        self.assertEqual(calculate([], "1d", NOW)["bars"], 0)
        self.assertIn("No completed stored candles", calculate([], "1d", NOW)["historyNote"])
        self.assertIn("Only 19 completed bars", result["historyNote"])
        self.assertIn("positive traded volume", result["historyNote"])

    def test_developing_candles_excluded_and_short_close_bucket_supported(self):
        rows = candles([100] * 51, datetime(2026, 9, 20, tzinfo=timezone.utc))
        rows += candles([1000], datetime(2026, 11, 9, tzinfo=timezone.utc))
        before_close = datetime(2026, 11, 9, 9, tzinfo=timezone.utc)
        self.assertEqual(calculate(rows, "1d", before_close)["price"], 100)
        intraday_now = datetime(2026, 11, 9, 5, tzinfo=timezone.utc)
        minute = candles([100, 200], intraday_now - timedelta(minutes=10), timedelta(minutes=8))
        self.assertEqual(calculate(minute, "5m", intraday_now)["price"], 100)
        closing = candles([300], datetime(2026, 11, 9, 9, 45, tzinfo=timezone.utc))
        self.assertEqual(calculate(closing, "1h", NOW)["price"], 300)

    def test_invalid_candles_break_history(self):
        rows = candles([100] * 60)
        rows[-2]["close"] = float("nan")
        result = calculate(rows, "1d", NOW)
        self.assertEqual(result["bars"], 1)
        self.assertIsNone(result["sma20"])
        rows[-1]["volume"] = -1
        self.assertIsNone(calculate(rows, "1d", NOW)["price"])

    def test_weekly_aggregates_daily_and_excludes_current_week(self):
        rows = candles([100] * 330)
        result = calculate(rows, "1w", NOW)
        self.assertGreater(result["bars"], 20)
        self.assertEqual(result["sma20"], 100)
        self.assertLess(datetime.fromisoformat(result["asOf"]), NOW - timedelta(days=7))

    def test_endpoint_includes_uncovered_stocks_and_validates_timeframe(self):
        async def run():
            meta = [dict(key="A", symbol="AAA", name="A company", exchange="NSE"),
                    dict(key="B", symbol="BBB", name="B company", exchange="NSE")]
            with patch("services.overview_signals.get_fno_stocks", return_value=meta), patch(
                "services.overview_signals.load_recent_candles_polars", new=AsyncMock(return_value=pl.DataFrame(candles([100] * 60)))) as load:
                result = await overview_signals("1d")
                self.assertEqual(len(result["stocks"]), 2)
                self.assertEqual(result["vwapLabel"], "20-bar VWAP")
                self.assertIsNone(result["stocks"][1]["price"])
                load.assert_awaited_once_with("1d", per_instrument=400)
            with self.assertRaises(HTTPException) as error:
                await overview_signals("garbage")
            self.assertEqual(error.exception.status_code, 400)
        asyncio.run(run())


class HistoryRepairTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _repair_jobs.clear()

    async def test_backfills_short_history_and_limits_to_missing_stocks(self):
        snapshot = {"stocks": [dict(key="A", bars=3), dict(key="B", bars=100)]}
        service = AsyncMock()
        tasks = BackgroundTasks()
        with patch("services.overview_signals.overview_signals", new=AsyncMock(return_value=snapshot)), patch(
            "services.overview_signals.get_fno_stocks", return_value=[dict(key="A"), dict(key="B")]), patch(
            "services.overview_signals.create_ingestion_job", new=AsyncMock(return_value=42)):
            result = await repair_history(service, "5m", tasks)
            self.assertEqual(result["job_id"], 42)
            await tasks()
        service.sync_universe.assert_awaited_once()
        service.sync_candles_for_universe.assert_awaited_once_with(
            unit="minutes", interval=5, lookback_days=28, concurrency=3,
            target_instruments=[dict(key="A")], job_id=42, backfill=True)

    async def test_daily_and_weekly_share_existing_repair(self):
        _repair_jobs["1d"] = 42
        tasks = BackgroundTasks()
        with patch("services.overview_signals.get_ingestion_job", new=AsyncMock(return_value=dict(id=42, status="running"))):
            result = await repair_history(AsyncMock(), "1w", tasks)
        self.assertEqual(result["job_id"], 42)
        self.assertFalse(tasks.tasks)

    async def test_sufficient_history_does_not_start_a_job(self):
        with patch("services.overview_signals.overview_signals", new=AsyncMock(return_value={"stocks": [dict(key="A", bars=51)]})):
            result = await repair_history(AsyncMock(), "1d", BackgroundTasks())
        self.assertIsNone(result["job_id"])

    async def test_failed_job_records_error_instead_of_polling_forever(self):
        service = AsyncMock()
        service.sync_universe.side_effect = RuntimeError("provider failure")
        tasks = BackgroundTasks()
        with patch("services.overview_signals.overview_signals", new=AsyncMock(return_value={"stocks": [dict(key="A", bars=0)]})), patch(
            "services.overview_signals.get_fno_stocks", return_value=[dict(key="A")]), patch(
            "services.overview_signals.create_ingestion_job", new=AsyncMock(return_value=43)), patch(
            "services.overview_signals.update_ingestion_job", new=AsyncMock()) as update, self.assertLogs("services.overview_signals", level="ERROR"):
            await repair_history(service, "1d", tasks)
            await tasks()
            self.assertEqual(update.await_args.args[1], "failed")

    async def test_invalid_timeframe_rejected(self):
        with self.assertRaises(HTTPException):
            await repair_history(AsyncMock(), "bad", BackgroundTasks())


if __name__ == "__main__":
    unittest.main()
