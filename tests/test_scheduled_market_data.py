import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from database.connection import Base
from database.models import Instrument, MarketCandle
from database import candle_repo
from scripts import update_market_data as worker, import_nse_bhavcopy as importer
from services.market_sync import INDIA


def archive_for(day):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr(f'pd{day:%d%m%Y}.csv', 'MKT,SERIES,SYMBOL,OPEN_PRICE,HIGH_PRICE,LOW_PRICE,CLOSE_PRICE,NET_TRDQTY\nN,EQ,RELIANCE,100,104,99,103,500\n')
        z.writestr(f'mcap{day:%d%m%Y}.csv', f'Trade Date,Symbol,Series,Market Cap(Rs.)\n{day:%d %b %Y},RELIANCE,EQ,10000000\n')
    return buf.getvalue()


class ScheduledDataTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine('sqlite+aiosqlite:///:memory:')
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.factory = async_sessionmaker(self.engine)
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'data').mkdir()
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026,10,25,12,tzinfo=INDIA)
        self.patches = [patch.object(worker, 'ROOT', self.root), patch.object(importer, 'ROOT', self.root),
                        patch.object(importer, 'SNAPSHOT', self.root/'data'/'caps.json'),
                        patch.object(worker, 'datetime', Clock),
                        patch.object(worker, 'async_session_factory', self.factory),
                        patch.object(importer, 'async_session_factory', self.factory),
                        patch.object(candle_repo, 'async_session_factory', self.factory),
                        patch.object(candle_repo, 'engine', self.engine),
                        patch.object(worker.asyncio, 'sleep', AsyncMock())]
        for p in self.patches:
            p.start()
        async with self.factory() as s:
            stock = Instrument(symbol='RELIANCE', exchange='NSE', instrument_key='NSE_EQ|INE002A01018')
            s.add(stock)
            await s.flush()
            s.add(MarketCandle(instrument_id=stock.id,timeframe='1d',timestamp=datetime(2026,10,22,tzinfo=INDIA).astimezone(timezone.utc),open=100,high=103,low=99,close=102,volume=400))
            await s.commit()

    async def asyncTearDown(self):
        for p in reversed(self.patches):
            p.stop()
        await self.engine.dispose()
        self.temp.cleanup()

    async def test_catchup_corrections_and_idempotent_repeat(self):
        def respond(request):
            day = datetime.strptime(request.url.path.split('/')[-1], 'PR%d%m%y.zip').date()
            return httpx.Response(200, content=archive_for(day))
        client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        with patch.object(worker.httpx, 'AsyncClient', return_value=client):
            self.assertEqual(await worker.run(), 0)
        report = json.loads((self.root/'data'/'scheduled-update.json').read_text())
        self.assertNotIn('intraday', report)
        self.assertTrue(all(r['matched'] == 1 and not r['missing'] for r in report['imported']))
        self.assertEqual([r['date'] for r in report['imported']], ['2026-10-20','2026-10-21','2026-10-22','2026-10-23'])
        async with self.factory() as s:
            bars = (await s.scalars(select(MarketCandle))).all()
            self.assertEqual(len(bars), 4)
            self.assertTrue(all(b.close == 103 for b in bars))
        client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        with patch.object(worker.httpx, 'AsyncClient', return_value=client):
            self.assertEqual(await worker.run(), 0)
        report = json.loads((self.root/'data'/'scheduled-update.json').read_text())
        self.assertTrue(all(r['changed'] == 0 for r in report['imported']))

    async def test_unpublished_archive_is_recorded_without_fake_candles(self):
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(404)))
        with patch.object(worker.httpx, 'AsyncClient', return_value=client):
            self.assertEqual(await worker.run(), 0)
        report = json.loads((self.root/'data'/'scheduled-update.json').read_text())
        self.assertEqual(len(report['unavailable']), 4)
        self.assertFalse(report['imported'])

    async def test_failed_download_exits_nonzero(self):
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(503)))
        with patch.object(worker.httpx, 'AsyncClient', return_value=client):
            self.assertEqual(await worker.run(), 1)


    async def test_oversized_archive_stops_and_removes_partial_download(self):
        client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b'too large')))
        destination = self.root / 'data' / 'oversize.tmp'
        async with client:
            with patch.object(worker, 'MAX_ARCHIVE_BYTES', 4):
                with self.assertRaises(ValueError):
                    await worker.download_archive(client, 'https://example.test/archive', destination)
        self.assertFalse(destination.exists())

    async def test_import_rejects_oversized_uncompressed_archive(self):
        archive = self.root / 'data' / 'oversize.zip'
        archive.write_bytes(archive_for(datetime(2026, 10, 23)))
        with patch.object(importer.zipfile.ZipFile, 'infolist', return_value=[
                type('Member', (), {'file_size': 129 * 1024 * 1024})()]):
            with self.assertRaisesRegex(ValueError, 'decompressed size'):
                await importer.import_archive(archive, apply=True)
