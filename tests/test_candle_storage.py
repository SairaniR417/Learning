import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import httpx
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from database.connection import Base
from database import candle_repo as repo
from services.market_sync import MarketSyncService, candle_closed, history_windows


class StorageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.patches = [patch.object(repo, "engine", self.engine),
                        patch.object(repo, "async_session_factory", async_sessionmaker(self.engine))]
        for item in self.patches:
            item.start()

    async def asyncTearDown(self):
        for item in self.patches:
            item.stop()
        await self.engine.dispose()

    async def test_duplicates_corrections_and_bounded_reads(self):
        records = [{"instrument_key": key, "timeframe": "1m",
                    "timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=i),
                    "open": 10., "high": 12., "low": 9., "close": 11., "volume": 100}
                   for key in ("A", "B") for i in range(120)]
        self.assertEqual(await repo.upsert_candles(records), 240)
        revision = await repo.get_candle_revision("1m")
        await repo.save_strategy_result_cache(
            "test", "ema_sma_alignment", "1m", {}, [], 2,
            datetime.now(timezone.utc) + timedelta(minutes=5))
        self.assertEqual(await repo.upsert_candles(records), 0)
        self.assertEqual(await repo.get_candle_revision("1m"), revision)
        self.assertIsNotNone(await repo.get_cached_strategy_result("test"))
        records[-1]["close"] = 12.
        self.assertEqual(await repo.upsert_candles(records), 1)
        self.assertGreater(await repo.get_candle_revision("1m"), revision)
        self.assertIsNone(await repo.get_cached_strategy_result("test"))
        frame = await repo.load_candles_polars("1m", min_candles=3)
        self.assertEqual(frame.height, 6)
        self.assertEqual(frame["timestamp"].min().minute, 57)

    async def test_same_day_sync_fetches_intraday_and_ignores_open_bar(self):
        now = datetime.now(timezone.utc)
        rows = [[(now - timedelta(minutes=2)).isoformat(), 10, 12, 9, 11, 100],
                [now.isoformat(), 10, 12, 9, 11, 100]]
        urls = []
        def handler(request):
            urls.append(str(request.url))
            return httpx.Response(200, json={"status": "success", "data": {"candles": rows}})
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with patch("services.market_sync.httpx.AsyncClient", return_value=client), \
             patch("services.market_sync.get_latest_candle_timestamps", AsyncMock(return_value={"A": now})), \
             patch("services.market_sync.upsert_candles", AsyncMock(return_value=1)) as save:
            result = await MarketSyncService(lambda: "test").sync_candles_for_universe(
                unit="minutes", target_instruments=[{"key": "A"}])
        self.assertEqual(result["stats"]["failed"], 0)
        self.assertTrue(any("/intraday/" in url for url in urls))
        self.assertTrue(all(len(call.args[0]) == 1 for call in save.await_args_list))

    def test_windows_are_contiguous_and_bounded(self):
        windows = list(history_windows(date(2026, 1, 1), date(2026, 3, 31), "minutes", 1))
        self.assertEqual(windows[-1][1], date(2026, 3, 31))
        for index, (start, end) in enumerate(windows):
            self.assertLessEqual((end - start).days, 27)
            if index:
                self.assertEqual(start, windows[index - 1][1] + timedelta(days=1))

    def test_daily_is_conservative(self):
        now = datetime(2026, 1, 2, 8, tzinfo=timezone.utc)
        self.assertFalse(candle_closed(now, "days", 1, now))
        self.assertTrue(candle_closed(now - timedelta(days=1), "days", 1, now))
