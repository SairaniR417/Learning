"""Confluence must preserve direction, freshness and executable level ordering."""
from datetime import datetime, timedelta, timezone
import unittest
import asyncio
from unittest.mock import AsyncMock, patch

import polars as pl
from fastapi.testclient import TestClient

from services.focused import combine, evidence, trade_plan


def candles(key="A", bearish=False, offset=0):
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(300):
        close = 400 - i * 0.4 if bearish else 100 + i * 0.4
        rows.append(dict(instrument_key=key, timestamp=start + timedelta(days=i + offset),
                         open=close, high=close + 2, low=close - 2, close=close, volume=1_000_000))
    return rows


class FocusedTests(unittest.TestCase):
    def test_bullish_only_absence_does_not_create_bearish_vote(self):
        self.assertIsNone(evidence("ema_sma_alignment", {"status": "NOT_ALIGNED"}, "EMA"))
        self.assertIsNone(evidence("multi_ma_bullish", {"status": "NEUTRAL"}, "MA"))

    def test_unconfirmed_and_weakened_cross_do_not_qualify(self):
        for state in ("WATCH", "CONFIRMED_WEAKENED", "EXPIRED"):
            self.assertIsNone(evidence("golden_death_cross", dict(state=state, signal="SELL"), "Cross"))
        self.assertIsNone(evidence("rsi_divergence", dict(state="WATCH", direction="BEARISH"), "RSI"))

    def test_ghost_rider_stopped_old_or_exhausted_setup_is_excluded(self):
        row = dict(signal="BUY", ageBars=1, stopTouched=False)
        self.assertIsNotNone(evidence("ghost_rider", row, "Ghost"))
        for changes in (dict(stopTouched=True), dict(ageBars=6), dict(tp5Hit=True)):
            self.assertIsNone(evidence("ghost_rider", dict(row, **changes), "Ghost"))

    def test_targets_and_stops_are_correct_for_both_directions(self):
        long = trade_plan(candles(), "BULLISH")
        short = trade_plan(candles(bearish=True), "BEARISH")
        self.assertLess(long["stopLoss"], long["entry"])
        self.assertLess(long["entry"], long["target1"])
        self.assertLess(long["target1"], long["target2"])
        self.assertGreater(short["stopLoss"], short["entry"])
        self.assertGreater(short["entry"], short["target1"])
        self.assertGreater(short["target1"], short["target2"])
        self.assertAlmostEqual(long["target1"] - long["entry"], 2 * (long["entry"] - long["stopLoss"]), places=1)
        flat = [dict(r, high=100., low=100., close=100.) for r in candles()]
        self.assertIsNone(trade_plan(flat, "BULLISH"))

    def fixture(self):
        df = pl.DataFrame(candles())
        meta = {"A": {"symbol": "TEST", "exchange": "NSE"}}
        outputs = {
            "ema_sma_alignment": [dict(instrumentKey="A", status="ALIGNED")],
            "multi_ma_bullish": [dict(instrumentKey="A", status="STRONG_BULLISH")],
            "ghost_rider": [dict(instrumentKey="A", signal="BUY", ageBars=1, stopTouched=False)],
        }
        names = {k: k for k in outputs}
        return df, meta, outputs, names

    def test_super_requires_confirmed_independent_agreement_and_capped_score(self):
        df, meta, outputs, names = self.fixture()
        result = combine(df, meta, outputs, names)
        self.assertEqual(result["bullish"][0]["tier"], "BULLISH")
        self.assertEqual(result["bullish"][0]["score"], 5)  # related trend votes cap at 3
        outputs["rsi_divergence"] = [dict(instrumentKey="A", state="CONFIRMED", direction="BULLISH")]
        names["rsi_divergence"] = "RSI"
        self.assertEqual(combine(df, meta, outputs, names)["bullish"][0]["tier"], "SUPER BULLISH")

    def test_only_correlated_trend_votes_are_excluded(self):
        df, meta, outputs, names = self.fixture()
        outputs.pop("ghost_rider")
        self.assertEqual(combine(df, meta, outputs, names)["bullish"], [])

    def test_opposing_confirmed_evidence_excludes_stock(self):
        df, meta, outputs, names = self.fixture()
        outputs["rsi_divergence"] = [dict(instrumentKey="A", state="CONFIRMED", direction="BEARISH")]
        names["rsi_divergence"] = "RSI"
        result = combine(df, meta, outputs, names)
        self.assertEqual(result["bullish"], [])
        self.assertEqual(result["excluded"]["conflicting"], 1)

    def test_stale_data_does_not_rank_against_latest_date(self):
        df, meta, outputs, names = self.fixture()
        df = pl.concat([df, pl.DataFrame(candles("B", offset=1))])
        meta["B"] = dict(symbol="NEWER", exchange="NSE")
        result = combine(df, meta, outputs, names)
        self.assertEqual(result["bullish"], [])
        self.assertEqual(result["excluded"]["stale"], 1)

    def test_bearish_confirmed_confluence(self):
        outputs = {"golden_death_cross": [dict(instrumentKey="A", state="CONFIRMED_ACTIVE", signal="SELL", barsSinceCross=2)],
                   "rsi_divergence": [dict(instrumentKey="A", state="CONFIRMED", direction="BEARISH")]}
        result = combine(pl.DataFrame(candles(bearish=True)), {"A": dict(symbol="BEAR")}, outputs, {k:k for k in outputs})
        self.assertEqual(len(result["bearish"]), 1)
        self.assertEqual(result["bearish"][0]["direction"], "BEARISH")

    def test_endpoint_limits_and_response(self):
        from main import app
        with patch("services.focused.focused_scan", new=AsyncMock(return_value={"bullish": [], "bearish": []})) as scan:
            client = TestClient(app)
            self.assertEqual(client.get("/api/focused?limit=3").status_code, 200)
            scan.assert_awaited_once_with(3)
            self.assertEqual(client.get("/api/focused?limit=0").status_code, 422)


class FocusedJobTests(unittest.IsolatedAsyncioTestCase):
    async def test_complete_cached_universe_is_available_for_pagination(self):
        from services import focused
        snapshot = {'asOf': '2026-10-12', 'bullish': [{'symbol': f'TEST{i}'} for i in range(33)], 'bearish': []}
        with patch.object(focused, 'get_candle_revision', new=AsyncMock(return_value=1)), patch.object(
            focused, 'get_cached_strategy_result', new=AsyncMock(return_value={'results': [snapshot]})
        ), patch.object(focused, 'load_recent_candles_polars', new=AsyncMock()) as history:
            all_stocks = await focused.focused_scan(None)
            self.assertEqual(len(all_stocks['bullish']), 33)
            self.assertEqual(all_stocks['totalBullish'], 33)
            limited = await focused.focused_scan(5)
            self.assertEqual(len(limited['bullish']), 5)
            self.assertEqual(limited['totalBullish'], 33)
            history.assert_not_awaited()

    async def test_concurrent_requests_share_one_scan(self):
        from services import focused
        ready = asyncio.Event()
        release = asyncio.Event()

        async def scan(*args):
            ready.set()
            await release.wait()
            return {"bullish": [], "bearish": []}

        with patch.object(focused, "focused_scan", new=AsyncMock(side_effect=scan)) as run:
            first = await focused.start_focused_job()
            await ready.wait()
            second = await focused.start_focused_job()
            self.assertEqual(first, second)
            self.assertEqual((await focused.focused_job_status(first["id"]))["status"], "running")
            release.set()
            await focused._active_task
            self.assertEqual((await focused.focused_job_status(first["id"]))["status"], "complete")
            run.assert_awaited_once()

    async def test_failed_strategy_does_not_publish_partial_shortlist(self):
        from services import focused
        with patch.object(focused, "focused_scan", new=AsyncMock(side_effect=RuntimeError("Strategy failed"))), patch("services.focused.logging.getLogger"):
            job = await focused.start_focused_job()
            await focused._active_task
            status = await focused.focused_job_status(job["id"])
            self.assertEqual(status["status"], "failed")
            self.assertIsNone(status["result"])
            self.assertTrue(status["error"])


if __name__ == "__main__":
    unittest.main()
