import unittest
import httpx
from unittest.mock import AsyncMock, patch
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from pydantic import ValidationError
from fastapi import HTTPException
from database.connection import Base
from database.models import PriceAlert, AlertNotification
from services import watchlists as service


class WatchlistTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine('sqlite+aiosqlite:///:memory:')
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.factory = async_sessionmaker(self.engine, expire_on_commit=False)
        self.patches = [patch.object(service, 'async_session_factory', self.factory)]
        for item in self.patches:
            item.start()

    async def asyncTearDown(self):
        for item in self.patches:
            item.stop()
        await self.engine.dispose()

    def entry(self):
        return {'key': 'NSE_EQ|INE123A01012', 'symbol': 'TEST', 'name': 'Test Ltd', 'exchange': 'NSE', 'section': 'Stocks'}

    async def add_alert(self, condition='above', target=100):
        entry = self.entry()
        return await service.create_alert(service.AlertInput(**{k: v for k, v in entry.items() if k != 'section'}, condition=condition, target=target))

    async def test_lists_persist_sections_symbols_and_flags(self):
        body = service.WatchlistInput(name='My list', sections=['Stocks', 'Banks'], entries=[self.entry()])
        created = await service.create_list(body)
        self.assertEqual((await service.get_lists())['lists'][0]['entries'][0]['key'], self.entry()['key'])
        entry = {**self.entry(), 'section': 'Banks', 'flag': 'red'}
        saved = await service.save_list(created['id'], service.WatchlistInput(name='Renamed', sections=['Stocks', 'Banks'], entries=[entry]))
        self.assertEqual(saved['entries'][0]['flag'], 'red')
        self.assertEqual(saved['name'], 'Renamed')
        await service.delete_list(created['id'])
        self.assertEqual((await service.get_lists())['lists'], [])

    def test_rejects_duplicate_symbols_and_invalid_sections(self):
        with self.assertRaises(ValidationError):
            service.WatchlistInput(name='Test', entries=[self.entry(), self.entry()])
        with self.assertRaises(ValidationError):
            service.WatchlistInput(name='Test', sections=['Other'], entries=[self.entry()])
        with self.assertRaises(ValidationError):
            service.WatchlistInput(name='   ')

    async def test_level_alert_triggers_exactly_once_and_persists_inbox(self):
        alert = await self.add_alert()
        quotes = AsyncMock(return_value={self.entry()['key']: {'price': 105}})
        monitor = service.AlertMonitor(quotes)
        await monitor.check()
        await monitor.check()
        async with self.factory() as session:
            self.assertEqual(await session.scalar(select(func.count()).select_from(AlertNotification)), 1)
            row = await session.get(PriceAlert, alert['id'])
            self.assertFalse(row.active)
            self.assertIsNotNone(row.triggered_at)
        inbox = await service.notifications()
        self.assertEqual(inbox['unread'], 1)
        self.assertEqual(inbox['notifications'][0]['price'], 105)
        self.assertTrue(inbox['notifications'][0]['createdAt'].endswith('+00:00'))
        await service.mark_one_read(inbox['notifications'][0]['id'])
        self.assertEqual((await service.notifications())['unread'], 0)

    async def test_crossing_waits_for_baseline_then_triggers_after_monitor_restart(self):
        await self.add_alert('cross_up')
        quotes = AsyncMock(return_value={self.entry()['key']: {'price': 99}})
        await service.AlertMonitor(quotes).check()
        self.assertEqual((await service.notifications())['unread'], 0)
        quotes.return_value = {self.entry()['key']: {'price': 102}}
        await service.AlertMonitor(quotes).check()
        self.assertEqual((await service.notifications())['unread'], 1)

    async def test_crossing_does_not_trigger_on_first_matching_sample(self):
        await self.add_alert('cross_up')
        quotes = AsyncMock(return_value={self.entry()['key']: {'price': 120}})
        await service.AlertMonitor(quotes).check()
        self.assertEqual((await service.notifications())['unread'], 0)

    async def test_missing_quote_does_not_trigger_or_disable_alert(self):
        alert = await self.add_alert('below')
        with self.assertRaises(HTTPException):
            await service.AlertMonitor(AsyncMock(return_value={})).check()
        async with self.factory() as session:
            self.assertTrue((await session.get(PriceAlert, alert['id'])).active)
        self.assertEqual((await service.notifications())['unread'], 0)

    async def test_cancel_prevents_notification(self):
        alert = await self.add_alert()
        await service.cancel_alert(alert['id'])
        fetch = AsyncMock(return_value={self.entry()['key']: {'price': 120}})
        await service.AlertMonitor(fetch).check()
        fetch.assert_not_called()
        self.assertEqual((await service.notifications())['unread'], 0)

    def test_above_below_and_crossing_boundaries(self):
        self.assertTrue(service.condition_met('above', 100, 100, None))
        self.assertTrue(service.condition_met('below', 100, 100, None))
        self.assertFalse(service.condition_met('cross_up', 100, 100, 90))
        self.assertTrue(service.condition_met('cross_down', 99, 100, 100))

    def test_invalid_alert_target_rejected(self):
        for target in [0, -1, float('nan'), float('inf')]:
            with self.assertRaises(ValidationError):
                service.AlertInput(**{k: v for k, v in self.entry().items() if k != 'section'}, condition='above', target=target)

    async def test_http_routes_save_lists_and_validate_alerts(self):
        from main import app
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            created = await client.post('/api/watchlists', json={'name': 'Route test', 'entries': [self.entry()]})
            self.assertEqual(created.status_code, 200)
            list_id = created.json()['id']
            self.assertEqual((await client.get('/api/watchlists')).json()['lists'][0]['id'], list_id)
            saved = await client.put(f'/api/watchlists/{list_id}', json={'name': 'Saved', 'entries': []})
            self.assertEqual(saved.json()['name'], 'Saved')
            self.assertEqual((await client.get('/api/watchlists/alerts')).status_code, 200)
            self.assertEqual((await client.get('/api/watchlists/notifications')).status_code, 200)
            self.assertEqual((await client.get('/api/watchlists/quotes', params={'keys': 'invalid'})).status_code, 400)
            invalid = {k: v for k, v in self.entry().items() if k != 'section'}
            invalid.update(condition='above', target=-1)
            self.assertEqual((await client.post('/api/watchlists/alerts', json=invalid)).status_code, 422)
            await client.delete(f'/api/watchlists/{list_id}')
            self.assertEqual((await client.get('/api/watchlists')).json()['lists'], [])
