import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException
from services import chart_quote as quotes


class ChartQuoteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        quotes.option_market.cache.entries.clear()

    async def test_exact_underlying_quote_and_cache(self):
        for key in ('NSE_EQ|INE002A01018','NSE_INDEX|Nifty 50','MCX_FO|123'):
            with self.subTest(key=key), patch.object(quotes.option_market,'require_key',AsyncMock()):
                request=AsyncMock(return_value={'data':{'row':{'instrument_token':key,'last_price':123.5}}})
                first=await quotes.latest(request,'token',key)
                second=await quotes.latest(request,'token',key)
                self.assertEqual(first,second)
                self.assertEqual(first['instrumentKey'],key)
                self.assertEqual(first['price'],123.5)
                self.assertIsNotNone(datetime.fromisoformat(first['receivedAt']).tzinfo)
                request.assert_awaited_once()

    async def test_option_quote_uses_verified_contract_not_underlying_price(self):
        request=AsyncMock(return_value={'data':{'row':{'instrument_token':'NSE_FO|999','last_price':138.4}}})
        with patch.object(quotes.option_analysis,'resolve_contract',AsyncMock(return_value={'instrument_key':'NSE_FO|999'})):
            result=await quotes.latest(request,'token','NSE_INDEX|Nifty 50',datetime.now(timezone.utc).date()+timedelta(days=1),22600,'CE')
        self.assertEqual(request.await_args.kwargs['params']['instrument_key'],'NSE_FO|999')
        self.assertEqual(result['price'],138.4)

    async def test_wrong_instrument_and_invalid_prices_are_rejected(self):
        with patch.object(quotes.option_market,'require_key',AsyncMock()):
            for row in ({'instrument_token':'OTHER','last_price':100}, {'instrument_token':'KEY','last_price':float('nan')}, {'instrument_token':'KEY','last_price':True}):
                with self.subTest(row=row), self.assertRaises(HTTPException):
                    await quotes.latest(AsyncMock(return_value={'data':{'x':row}}),'token','KEY')

    async def test_invalid_option_does_not_request_quote(self):
        request=AsyncMock()
        with self.assertRaises(HTTPException):
            await quotes.latest(request,'token','NSE_INDEX|Nifty 50',strike=100)
        request.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
