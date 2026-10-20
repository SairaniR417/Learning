import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from scanner.universe import get_fno_stocks, fno_keys, require_fno_key
from services.watchlists import WatchEntry, AlertInput
from services.trade_journal import TradeInput
from database.connection import Base
from database.models import Instrument, MarketCandle, JournalTrade, UserWatchlist, PriceAlert
from database import candle_repo
from scripts import restrict_to_fno
import main

ALLOWED = "NSE_EQ|INE002A01018"
EXCLUDED = "NSE_EQ|NOT_IN_SAVED_LIST"


class ScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_and_snapshot_use_exact_saved_universe(self):
        expected = fno_keys()
        self.assertEqual(len(expected), 213)
        search = await main.search_instruments(q="", market="cash")
        self.assertEqual({s["key"] for s in search["instruments"]}, expected)
        self.assertEqual((await main.search_instruments(q="not_in_saved_list", market="cash"))["instruments"], [])
        self.assertEqual((await main.search_instruments(q="reliance", market="cash"))["instruments"][0]["key"], ALLOWED)
        requested = []

        async def quotes(url, **kwargs):
            keys = kwargs["params"]["instrument_key"].split(",")
            requested.extend(keys)
            return {"data": {key: {"instrument_token": key, "last_price": 110, "prev_close_price": 100} for key in keys}}

        with patch.object(main, "require_token", return_value="test"), patch.object(main, "api_json_request", side_effect=quotes):
            snapshot = await main.market_snapshot(market="equities")
        self.assertEqual(set(requested), expected)
        self.assertEqual({s["key"] for s in snapshot["assets"]}, expected)
        self.assertIn(snapshot["chartKey"], expected)

    async def test_excluded_requests_and_personal_records_are_rejected(self):
        with self.assertRaises(HTTPException):
            require_fno_key(EXCLUDED)
        with self.assertRaises(HTTPException):
            await main.search_instruments(q="gold", market="commodities")
        entry = dict(key=EXCLUDED, symbol="OUTSIDE", name="Outside", exchange="NSE")
        with self.assertRaises(ValidationError):
            WatchEntry(**entry)
        with self.assertRaises(ValidationError):
            AlertInput(**entry, condition="above", target=100)
        with self.assertRaises(ValidationError):
            TradeInput(symbol="NIFTY", direction="LONG", entryAt="2026-01-01T10:00:00+05:30", entryPrice=100, quantity=1)
        with self.assertRaises(ValueError):
            await candle_repo.upsert_instruments([{"key": EXCLUDED, "symbol": "OUTSIDE"}])
        with self.assertRaises(ValueError):
            await candle_repo.upsert_candles([{"instrument_key": EXCLUDED}])
        # Persist canonical metadata, rather than trusting an imported name/symbol.
        entry = WatchEntry(key=ALLOWED, symbol="WRONG", name="Wrong", exchange="MCX")
        self.assertEqual(entry.symbol, "RELIANCE")
        self.assertEqual(entry.exchange, "NSE")


class CleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_prune_preserves_allowed_history_and_personal_records(self):
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            async with factory() as session:
                for key, symbol in [(ALLOWED, "RELIANCE"), (EXCLUDED, "OUTSIDE")]:
                    instrument = Instrument(provider_instrument_key=key, symbol=symbol, exchange="NSE")
                    session.add(instrument)
                    await session.flush()
                    session.add(MarketCandle(instrument_id=instrument.id, timeframe="1d",
                        candle_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
                        open=100, high=110, low=90, close=105, volume=100))
                    session.add(JournalTrade(content_json=json.dumps({"symbol": symbol, "segment": "Equity"})))
                    session.add(PriceAlert(instrument_key=key, symbol=symbol, name=symbol,
                                           exchange="NSE", condition="above", target=100))
                session.add(UserWatchlist(name="Mixed", content_json=json.dumps({
                    "sections": ["Stocks"], "entries": [{"key": ALLOWED}, {"key": EXCLUDED}]})))
                await session.commit()
            with patch.object(restrict_to_fno, "async_session_factory", factory):
                report = await restrict_to_fno.prune(get_fno_stocks())
                again = await restrict_to_fno.prune(get_fno_stocks())
            self.assertEqual(report["instruments"], 1)
            self.assertEqual(report["candles"], 1)
            self.assertEqual(report["journal_trades"], 1)
            self.assertEqual(report["watchlist_entries"], 1)
            self.assertTrue(all(value == 0 for value in again.values()))
            with patch.object(candle_repo, "async_session_factory", factory):
                self.assertEqual([s["key"] for s in await candle_repo.get_all_active_instruments()], [ALLOWED])
            async with factory() as session:
                for model in (Instrument, MarketCandle, JournalTrade, PriceAlert):
                    self.assertEqual(await session.scalar(select(func.count()).select_from(model)), 1)
                content = json.loads((await session.scalar(select(UserWatchlist))).content_json)
                self.assertEqual(content["entries"], [{"key": ALLOWED}])
        finally:
            await engine.dispose()
