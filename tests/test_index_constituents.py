import unittest
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException
from services.index_constituents import parse_nifty_csv, parse_sensex, index_constituents


class IndexConstituentTests(unittest.IsolatedAsyncioTestCase):
    def test_csv_maps_isins_and_deduplicates(self):
        csv = 'Company Name,Industry,Symbol,Series,ISIN Code\n"Company, Limited",Finance,TEST,EQ,INE123A01012\nCompany,Finance,TEST,EQ,INE123A01012\n'
        self.assertEqual(parse_nifty_csv(csv), [{"symbol": "TEST", "isin": "INE123A01012"}])

    def test_sensex_uses_exchange_tokens_and_bse_trading_groups(self):
        rows = [{"SCRIP_CODE": str(500000 + i)} for i in range(30)]
        instruments = [{"segment": "BSE_EQ", "instrument_type": "A", "exchange_token": str(500000+i),
                        "instrument_key": f"BSE_EQ|INE{i:03}A01012", "isin": f"INE{i:03}A01012", "trading_symbol": f"TEST{i}"} for i in range(30)]
        members = parse_sensex({"Table": rows}, instruments)
        self.assertEqual(len(members), 30)
        self.assertEqual(members[0]['isin'], 'INE000A01012')
        with self.assertRaises(ValueError):
            parse_sensex({"Table": rows}, instruments[:-1])

    async def test_cached_membership_does_not_fetch_network(self):
        from datetime import datetime, timedelta, timezone
        value = {"id": "nifty50", "members": [{"isin": "INE123A01012"}]}
        with patch('services.index_constituents._cache', {'nifty50': (datetime.now(timezone.utc) + timedelta(hours=1), value)}), \
             patch('services.index_constituents.httpx.AsyncClient') as client:
            self.assertEqual(await index_constituents('nifty50'), value)
            client.assert_not_called()

    async def test_invalid_csv_returns_retryable_error(self):
        response = unittest.mock.Mock()
        response.text = '<html>Access denied</html>'
        client = AsyncMock()
        client.get.return_value = response
        with patch('services.index_constituents._cache', {}), \
             patch('services.index_constituents.httpx.AsyncClient') as factory:
            factory.return_value.__aenter__.return_value = client
            with self.assertRaises(HTTPException) as exc:
                await index_constituents('nifty50')
        self.assertEqual(exc.exception.status_code, 502)
