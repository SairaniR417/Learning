import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient

import main
from services import option_chain as service

KEY = "NSE_EQ|INE002A01018"


class OptionChainTests(unittest.IsolatedAsyncioTestCase):
    async def test_expiries_are_sorted_unique_and_current(self):
        today = datetime.now(service.INDIA).date()
        dates = [today + timedelta(days=30), today, today, today - timedelta(days=1)]
        request = AsyncMock(return_value={"status": "success", "data": [
            {"underlying_key": KEY, "expiry": d.isoformat()} for d in dates
        ] + [{"underlying_key": "OTHER", "expiry": today.isoformat()}]})
        result = await service.expiries(request, "test", KEY)
        self.assertEqual(result["expiries"], [today.isoformat(), dates[0].isoformat()])
        self.assertEqual(request.call_args.kwargs["params"], {"instrument_key": KEY})

    async def test_chain_sorts_strikes_preserves_zero_and_handles_missing_leg(self):
        expiry = datetime.now(service.INDIA).date() + timedelta(days=30)
        rows = [{"underlying_key": KEY, "expiry": expiry.isoformat(), "strike_price": strike,
                 "underlying_spot_price": 105,
                 "call_options": {"market_data": {"ltp": 0, "oi": 150}, "option_greeks": {"delta": .5, "gamma": float("nan")}}}
                for strike in [120, 100]]
        result = await service.chain(AsyncMock(return_value={"status": "success", "data": rows}), "test", KEY, expiry)
        self.assertEqual([r["strike"] for r in result["rows"]], [100, 120])
        self.assertEqual(result["atmStrike"], 100)
        self.assertEqual(result["rows"][0]["call"]["ltp"], 0)
        self.assertIsNone(result["rows"][0]["put"]["oi"])
        self.assertIsNone(result["rows"][0]["call"]["gamma"])

    async def test_empty_and_mismatched_responses(self):
        expiry = datetime.now(service.INDIA).date()
        result = await service.chain(AsyncMock(return_value={"status": "success", "data": []}), "test", KEY, expiry)
        self.assertEqual(result["rows"], [])
        self.assertIsNone(result["atmStrike"])
        for payload in [{"status": "success", "data": {}},
                        {"status": "success", "data": [{"underlying_key": "OTHER", "strike_price": 100}]}]:
            with self.assertRaises(HTTPException) as error:
                await service.chain(AsyncMock(return_value=payload), "test", KEY, expiry)
            self.assertEqual(error.exception.status_code, 502)

    async def test_network_failure_and_past_expiry(self):
        with self.assertRaises(HTTPException) as error:
            await service.expiries(AsyncMock(side_effect=httpx.ReadTimeout("timeout")), "test", KEY)
        self.assertEqual(error.exception.status_code, 502)
        request = AsyncMock()
        with self.assertRaises(HTTPException) as error:
            await service.chain(request, "test", KEY, datetime.now(service.INDIA).date() - timedelta(days=1))
        self.assertEqual(error.exception.status_code, 400)
        request.assert_not_called()

    def test_routes_require_allowed_stock_and_authentication(self):
        client = TestClient(main.app)
        with patch.object(main, "require_token", side_effect=HTTPException(401, "Connect Upstox")), \
             patch.object(main, "api_json_request", AsyncMock()) as request:
            self.assertEqual(client.get("/api/stocks/option-expiries", params={"instrument_key": KEY}).status_code, 401)
            self.assertEqual(client.get("/api/stocks/option-expiries", params={"instrument_key": "NSE_EQ|OUTSIDE"}).status_code, 400)
            self.assertEqual(client.get("/api/stocks/option-chain", params={"instrument_key": KEY, "expiry": "bad"}).status_code, 422)
            request.assert_not_called()
