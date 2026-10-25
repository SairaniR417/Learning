import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from database.connection import Base
from database.models import Instrument, MarketCandle
from database import candle_repo
from services import stock_chart as chart
from services.market_sync import INDIA

KEY = 'NSE_EQ|INE002A01018'


class ChartRulesTests(unittest.TestCase):
    def test_session_anchoring_volume_and_short_last_hour(self):
        start = datetime(2026, 10, 23, 9, 15, tzinfo=INDIA)
        rows = [dict(timestamp=start+timedelta(minutes=i), open=100+i, high=102+i,
                     low=99+i, close=101+i, volume=10) for i in range(375)]
        bars = chart.aggregate(rows, '1h', start+timedelta(hours=8))
        self.assertEqual(len(bars), 7)
        self.assertEqual(bars[0]['timestamp'].astimezone(INDIA).strftime('%H:%M'), '09:15')
        self.assertEqual(bars[0]['volume'], 600)
        self.assertEqual(bars[-1]['volume'], 150)
        self.assertFalse(bars[-1]['developing'])
        daily = chart.aggregate(rows[:2], '1d', start+timedelta(minutes=2))
        self.assertTrue(daily[0]['developing'])
        self.assertEqual(daily[0]['open'], 100)
        self.assertEqual(daily[0]['close'], 102)

    def test_invalid_provider_bar_rejected(self):
        with self.assertRaises(ValueError):
            chart.parse_candles([['2026-10-23T09:15:00+05:30', 100, 99, 95, 98, 10]], datetime.now(timezone.utc))


class SelectedChartTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine('sqlite+aiosqlite:///:memory:')
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.factory = async_sessionmaker(self.engine)
        self.patches = [patch.object(chart, 'async_session_factory', self.factory), patch.object(chart, 'get_token', lambda: 'test-token'), patch.object(candle_repo, 'engine', self.engine)]
        for p in self.patches:
            p.start()
        chart._cache.clear()
        async with self.factory() as session:
            stock = Instrument(symbol='RELIANCE', exchange='NSE', instrument_key=KEY)
            session.add(stock)
            await session.flush()
            session.add(MarketCandle(instrument_id=stock.id, timeframe='1d', timestamp=datetime(2026,10,22,tzinfo=INDIA), open=100, high=103, low=99, close=102, volume=500))
            await session.commit()

    async def asyncTearDown(self):
        for p in self.patches:
            p.stop()
        await self.engine.dispose()

    async def test_offline_keeps_db_history(self):
        with patch.object(chart, 'get_token', lambda: None), patch.object(chart, 'provider_rows', AsyncMock()) as provider:
            result = await chart.stock_chart(KEY, '1d')
        self.assertEqual(len(result['candles']), 1)
        self.assertIn('Connect Upstox', result['warning'])
        provider.assert_not_called()

    async def test_selected_only_shared_fetch_and_completed_writes(self):
        now = datetime(2026,10,23,10,0,30,tzinfo=INDIA)
        rows = [dict(timestamp=now.replace(minute=59, hour=9, second=0),open=100,high=103,low=99,close=102,volume=10),
                dict(timestamp=now.replace(second=0),open=102,high=104,low=101,close=103,volume=20)]
        daily = [dict(timestamp=datetime(2026,10,22,tzinfo=INDIA),open=100,high=104,low=99,close=103,volume=600)]
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return now.astimezone(tz or timezone.utc)
        with patch.object(chart, 'datetime', Clock), patch.object(chart, 'provider_rows', AsyncMock(side_effect=[rows,daily])) as provider, patch.object(chart, 'upsert_candles', AsyncMock()) as save:
            result = await chart.stock_chart(KEY, '1d')
            minute = await chart.stock_chart(KEY, '5m')
        self.assertEqual(provider.await_count, 2)
        self.assertTrue(all(c.args[0] == KEY for c in provider.await_args_list))
        self.assertEqual(len(result['candles']), 2)
        self.assertEqual(result['candles'][0]['close'], 102)  # Stored/BHAV daily values win.
        self.assertTrue(result['candles'][-1]['developing'])
        saved = save.await_args.args[0]
        self.assertEqual(len([r for r in saved if r['timeframe']=='1m']), 1)
        self.assertTrue(minute['candles'][-1]['developing'])

    async def test_provider_failure_keeps_db_history(self):
        with patch.object(chart, 'provider_rows', AsyncMock(side_effect=ValueError('bad data'))):
            result = await chart.stock_chart(KEY, '1d')
        self.assertEqual(len(result['candles']), 1)
        self.assertIn('unavailable', result['warning'])
