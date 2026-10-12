import json
from decimal import Decimal
from pathlib import Path
import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from database.connection import Base
from services import trade_journal as service


class JournalTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine=create_async_engine('sqlite+aiosqlite:///:memory:')
        async with self.engine.begin() as c:
            await c.run_sync(Base.metadata.create_all)
        self.factory=async_sessionmaker(self.engine,expire_on_commit=False)
        self.patcher=patch.object(service,'async_session_factory',self.factory)
        self.patcher.start()

    async def asyncTearDown(self):
        self.patcher.stop()
        await self.engine.dispose()

    def body(self, **values):
        return {'symbol':'TEST','direction':'LONG','entryAt':'2026-05-05T09:30:00+05:30','exitAt':'2026-05-05T10:30:00+05:30','entryPrice':100,'exitPrice':110,'quantity':100,'charges':30,'stopPrice':95,'targetPrice':110,'capital':100000,'riskPercent':1,'lotSize':25,**values}

    def test_long_and_short_pnl_costs_and_risk(self):
        long=service.calculated(service.TradeInput(**self.body()))
        self.assertEqual(long['grossPnl'],1000)
        self.assertEqual(long['netPnl'],970)
        self.assertEqual(long['plannedRisk'],500)
        self.assertEqual(long['maxRisk'],1000)
        self.assertEqual(long['recommendedLots'],8)
        self.assertEqual(long['plannedRR'],2)
        self.assertEqual(long['rMultiple'],1.94)
        self.assertEqual(long['durationMinutes'],60)
        short=service.calculated(service.TradeInput(**self.body(direction='SHORT',stopPrice=105,targetPrice=90,exitPrice=90)))
        self.assertEqual(short['netPnl'],970)
        self.assertEqual(short['points'],10)

    def test_open_and_breakeven_are_distinct(self):
        open_trade=service.calculated(service.TradeInput(**self.body(exitAt=None,exitPrice=None)))
        self.assertIsNone(open_trade['netPnl'])
        self.assertEqual(open_trade['result'],'OPEN')
        flat=service.calculated(service.TradeInput(**self.body(exitPrice=100,charges=0)))
        self.assertEqual(flat['result'],'BREAKEVEN')

    def test_decimal_arithmetic(self):
        t=service.TradeInput(**self.body(entryPrice='0.1',exitPrice='0.3',stopPrice='0.05',targetPrice='0.4',quantity=3,charges='0.1'))
        self.assertEqual(service.calculated(t)['netPnl'],0.5)

    def test_validation_rejects_broken_times_and_levels(self):
        for changes in [{'entryAt':'2026-05-05T09:30:00'}, {'exitAt':'2026-05-05T08:30:00+05:30'}, {'exitPrice':None}, {'stopPrice':100}, {'targetPrice':90}, {'quantity':0}, {'charges':-1}, {'rsi':101}, {'confidence':11}, {'chartLink':'javascript:alert(1)'}, {'entryPrice':'NaN'}, {'symbol':'   '}]:
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                service.TradeInput(**self.body(**changes))

    async def test_crud_persists_reflection_and_recalculates(self):
        created=await service.create_trade(service.TradeInput(**self.body(learned='Wait for confirmation',emotionDuring='Anxious',entryFollowed=False)))
        rows=(await service.trades())['trades']
        self.assertEqual(rows[0]['learned'],'Wait for confirmation')
        self.assertFalse(rows[0]['entryFollowed'])
        updated=await service.update_trade(created['id'],service.TradeInput(**self.body(exitPrice=90,charges=45)))
        self.assertEqual(updated['netPnl'],-1045)
        self.assertEqual(updated['result'],'LOSS')
        await service.delete_trade(created['id'])
        self.assertEqual((await service.trades())['trades'],[])

    async def test_provided_workbook_import_is_idempotent_and_corrected(self):
        first=await service.import_provided()
        second=await service.import_provided()
        self.assertEqual(first['added'],1)
        self.assertEqual(second['added'],0)
        self.assertEqual(second['duplicates'],1)
        row=(await service.trades())['trades'][0]
        self.assertEqual(row['netPnl'],-4300)
        self.assertEqual(row['quantity'],100)
        self.assertTrue(row['imported'])
        self.assertIn('3225',row['notes'])
        self.assertEqual(row['learned'],'Trust the Plan')
        self.assertEqual(row['durationMinutes'],93)
        self.assertTrue(first['warnings'])

    async def test_http_routes_and_errors(self):
        app=FastAPI();app.include_router(service.router)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            invalid=await client.post('/api/journal/trades',json=self.body(exitPrice=None))
            self.assertEqual(invalid.status_code,422)
            created=await client.post('/api/journal/trades',json=self.body())
            self.assertEqual(created.status_code,200)
            identifier=created.json()['id']
            self.assertEqual((await client.get('/api/journal/trades')).json()['trades'][0]['netPnl'],970)
            self.assertEqual((await client.delete(f'/api/journal/trades/{identifier}')).status_code,200)
            self.assertEqual((await client.delete(f'/api/journal/trades/{identifier}')).status_code,404)
            self.assertEqual((await client.get('/api/journal/provided-workbooks')).status_code,200)


if __name__=='__main__':
    unittest.main()
