import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from database.connection import Base
from database.models import Instrument, MarketCandle
from services.stock_details import stock_history, parse_news


class StockDetailsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine('sqlite+aiosqlite:///:memory:')
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.factory = async_sessionmaker(self.engine)
        self.patch = patch('services.stock_details.async_session_factory', self.factory)
        self.patch.start()
        async with self.factory() as session:
            instrument = Instrument(symbol='RELIANCE', exchange='NSE', instrument_key='NSE_EQ|INE002A01018')
            session.add(instrument)
            await session.flush()
            start = datetime(2020, 1, 1, tzinfo=timezone.utc)
            session.add_all([MarketCandle(instrument_id=instrument.id, timeframe='1d', timestamp=start + timedelta(days=i),
                open=100+i, high=102+i, low=99+i, close=101+i, volume=1000) for i in range(55)])
            await session.commit()

    async def asyncTearDown(self):
        self.patch.stop()
        await self.engine.dispose()

    async def test_complete_coverage_and_non_overlapping_pages(self):
        first = await stock_history('NSE_EQ|INE002A01018', page=1, page_size=50)
        second = await stock_history('NSE_EQ|INE002A01018', page=2, page_size=50)
        self.assertEqual(first['total'], 55)
        self.assertEqual(len(first['chart']), 55)
        self.assertEqual(first['chart'][0]['close'], 101)
        self.assertEqual(first['chart'][0]['open'], 100)
        self.assertEqual(first['chart'][0]['high'], 102)
        self.assertEqual(first['chart'][0]['low'], 99)
        self.assertEqual(first['chart'][0]['volume'], 1000)
        self.assertLess(first['chart'][0]['timestamp'], first['chart'][-1]['timestamp'])
        self.assertEqual(first['candles'][0]['close'], 155)
        self.assertEqual(len(second['candles']), 5)
        self.assertEqual(second['candles'][-1]['close'], 101)
        self.assertEqual(second['chart'], [])
        self.assertEqual(first['high'], 156)
        self.assertEqual(first['totalVolume'], 55000)
        self.assertIsNone(first['addedAt'])

    async def test_unknown_instrument_reports_missing_import(self):
        with self.assertRaises(HTTPException) as error:
            await stock_history('NSE_EQ|INE062A01020', page=1, page_size=50)
        self.assertEqual(error.exception.status_code, 404)

    def test_news_preserves_dates_and_rejects_unsafe_links(self):
        items = parse_news(b'<rss><channel><item><title>Company update</title><link>https://news.google.com/rss/articles/abc</link><pubDate>Mon, 12 Oct 2026 12:00:00 GMT</pubDate><source>Publisher</source></item><item><title>Bad link</title><link>javascript:alert(1)</link></item></channel></rss>')
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['source'], 'Publisher')
        self.assertIn('12 Oct 2026', items[0]['publishedAt'])
