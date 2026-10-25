"""Daily NSE confluence from every registered strategy, sharing one DB snapshot."""
from scanner.universe import universe_version
import asyncio
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import math
import logging
from uuid import uuid4
from typing import Any

import polars as pl
from fastapi import APIRouter, Query, HTTPException

from database.candle_repo import (get_all_active_instruments, get_candle_revision,
    get_cached_strategy_result, load_recent_candles_polars, save_strategy_result_cache)
from scanner.strategies.registry import strategy_registry
from scanner.strategies.ghost_rider import atr14
from services.market_sync import INDIA, nse_daily_closed
from services.market_cap import attach_market_caps

router = APIRouter(prefix="/api/focused", tags=["Focused"])
_scan_lock = asyncio.Lock()
_jobs: dict[str, dict[str, Any]] = {}
_active_job: str | None = None
_active_task: asyncio.Task | None = None
CACHE_VERSION = "golden-v2-focused:v3-pine-rsi"
FAMILY_CAPS = {"trend": 3, "crossover": 3, "momentum": 3}


def focus_window(strategy, params):
    # Focus only needs recent cross setups. Five hundred candles cover SMA 200,
    # the 250-bar warm-up, and the entire 30-bar cross confirmation window.
    if strategy.metadata.id in {"golden_death_cross", "ghost_rider"}:
        return 500
    return strategy.candle_window(params)


def evidence(strategy_id: str, row: dict[str, Any], name: str) -> dict[str, Any] | None:
    """Interpret actual strategy output; absence of a bullish match is not bearish."""
    status, state = row.get("status", ""), row.get("state", "")
    direction, weight, family, reason = None, 0, "trend", ""
    if strategy_id == "ema_sma_alignment" and status in {"ALIGNED", "NEWLY_ALIGNED"}:
        direction, weight = "BULLISH", 2
        reason = "Close above EMA 9, EMA 20, SMA 50 and SMA 200"
    elif strategy_id == "multi_ma_bullish":
        if status.startswith(("STRONG_BULLISH", "CONFIRMED_BULLISH")):
            direction, weight = "BULLISH", 3
            reason = "Bullish MA order, rising long-term trend, RSI and volume confirmed"
            if status.startswith("STRONG_BULLISH"):
                reason += "; closing breakout above prior 20-bar high"
        elif status == "BEARISH_WARNING":
            direction, weight = "BEARISH", 1
            reason = "EMA 9 crossed below EMA 20; warning only"
        elif status == "EARLY_BULLISH":
            direction, weight = "BULLISH", 1
            reason = "Fresh bullish EMA crossover with RSI above 50; early signal"
    elif strategy_id == "golden_death_cross":
        if state in {"CONFIRMED", "CONFIRMED_ACTIVE"} and row.get("signal") in {"BUY", "SELL"} and row.get("barsSinceCross", 999) <= 30:
            direction = "BULLISH" if row["signal"] == "BUY" else "BEARISH"
            weight, family = 3, "crossover"
            reason = ("Golden" if direction == "BULLISH" else "Death") + " cross with all six current confirmations passing"
    elif strategy_id == "ghost_rider":
        if row.get("signal") in {"BUY", "SELL"} and row.get("ageBars", 999) <= 5 and not row.get("stopTouched", True) and not row.get("tp5Hit", False):
            direction = "BULLISH" if row["signal"] == "BUY" else "BEARISH"
            weight, family = 2, "crossover"
            reason = f"EMA 9/21 {row['signal'].lower()} setup, {row.get('ageBars', 0)} bars old; original stop untouched"
    elif strategy_id == "rsi_reversal" and status == "OVERSOLD_REVERSAL":
        direction, weight, family = "BULLISH", 2, "momentum"
        reason = f"RSI recovered from below 30 to {row['rsi']:.1f}"
    elif strategy_id == "rsi_divergence" and state == "DETECTED":
        if row.get("direction") in {"BULLISH", "BEARISH"}:
            direction, weight, family = row["direction"], 3, "momentum"
            reason = row.get("divergenceType", "RSI divergence").replace("_", " ").title() + "; RSI pivot confirmed after five right-side bars"
    if direction is None:
        return None
    return dict(strategyId=strategy_id, strategy=name, direction=direction, weight=weight,
                family=family, reason=reason, state=state or status)


def trade_plan(candles: list[dict[str, Any]], direction: str) -> dict[str, Any] | None:
    """New reference-close plan, distinct from an older strategy entry or target."""
    if len(candles) < 15:
        return None
    entry = float(candles[-1]["close"])
    atr = atr14(candles)[-1]
    if atr is None or not math.isfinite(atr) or atr <= 0 or entry <= 0:
        return None
    bullish = direction == "BULLISH"
    swing = min(float(c["low"]) for c in candles[-10:]) if bullish else max(float(c["high"]) for c in candles[-10:])
    stop = min(swing - 0.25 * atr, entry - 1.5 * atr) if bullish else max(swing + 0.25 * atr, entry + 1.5 * atr)
    risk = abs(entry - stop)
    sign = 1 if bullish else -1
    targets = [round(entry + sign * risk * multiple, 2) for multiple in (2, 3)]
    if stop <= 0 or min(targets) <= 0 or risk / entry > 0.12:
        return None
    rounded_entry, rounded_stop = round(entry, 2), round(stop, 2)
    if (bullish and not rounded_stop < rounded_entry < targets[0] < targets[1]) or (not bullish and not targets[1] < targets[0] < rounded_entry < rounded_stop):
        return None
    return dict(entry=rounded_entry, stopLoss=rounded_stop, target1=targets[0], target2=targets[1],
                riskPct=round(risk / entry * 100, 2), atr14=round(atr, 2),
                rewardRisk=[2, 3], basis="Latest daily close; stop beyond 10-bar swing with 0.25 ATR buffer, at least 1.5 ATR away; targets at 2R / 3R")


def combine(df: pl.DataFrame, instruments: dict[str, dict[str, Any]],
            outputs: dict[str, list[dict[str, Any]]], names: dict[str, str]) -> dict[str, Any]:
    groups = {g["instrument_key"][0]: g.to_dicts() for g in df.partition_by("instrument_key", maintain_order=True)}
    dates = {key: rows[-1]["timestamp"].astimezone(INDIA).date() for key, rows in groups.items()}
    as_of = max(dates.values()) if dates else None
    votes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for strategy_id, rows in outputs.items():
        for row in rows:
            vote = evidence(strategy_id, row, names[strategy_id])
            if vote:
                votes[row["instrumentKey"]].append(vote)
    sides: dict[str, list[dict[str, Any]]] = {"BULLISH": [], "BEARISH": []}
    excluded = dict(stale=0, insufficientHistory=0, liquidity=0, conflicting=0, weakAgreement=0, wideStop=0)
    for key, candles in groups.items():
        if dates[key] != as_of:
            excluded["stale"] += 1
            continue
        if len(candles) < 251:
            excluded["insufficientHistory"] += 1
            continue
        turnover = sum(float(c["close"]) * float(c["volume"] or 0) for c in candles[-20:]) / 20
        if turnover < 10_000_000 or candles[-1]["close"] < 20 or not candles[-1]["volume"]:
            excluded["liquidity"] += 1
            continue
        stock_votes = votes.get(key, [])
        strong_sides = {v["direction"] for v in stock_votes if v["weight"] >= 2}
        if len(strong_sides) > 1:
            excluded["conflicting"] += 1
            continue
        if not strong_sides:
            excluded["weakAgreement"] += 1
            continue
        direction = next(iter(strong_sides))
        agreeing = [v for v in stock_votes if v["direction"] == direction]
        strong = [v for v in agreeing if v["weight"] >= 2]
        families = {v["family"] for v in strong}
        if len(strong) < 2 or len(families) < 2:
            excluded["weakAgreement"] += 1
            continue
        totals: dict[str, int] = defaultdict(int)
        for v in agreeing:
            totals[v["family"]] += v["weight"]
        score = sum(min(points, FAMILY_CAPS[family]) for family, points in totals.items())
        opposing = [v for v in stock_votes if v["direction"] != direction]
        score -= sum(v["weight"] for v in opposing)
        plan = trade_plan(candles, direction)
        if not plan:
            excluded["wideStop"] += 1
            continue
        latest, previous = candles[-1], candles[-2]
        meta = instruments[key]
        super_signal = len(strong) >= 3 and score >= 6 and not opposing
        sides[direction].append(dict(instrumentKey=key, symbol=meta["symbol"], name=meta.get("name") or meta["symbol"], exchange="NSE",
            direction=direction, tier=("SUPER " if super_signal else "") + direction,
            score=score, maxScore=9, strategyCount=len(agreeing), strongStrategyCount=len(strong),
            independentFamilies=len(families), reasons=agreeing, conflicts=opposing,
            asOf=latest["timestamp"].isoformat(), close=round(float(latest["close"]), 2),
            changePct=round((float(latest["close"]) / float(previous["close"]) - 1) * 100, 2) if previous["close"] else None,
            averageTurnover=round(turnover, 2), candlesAnalyzed=len(candles), plan=plan))
    for rows in sides.values():
        rows.sort(key=lambda r: (not r["tier"].startswith("SUPER"), -r["score"], -r["strongStrategyCount"], -r["averageTurnover"], r["symbol"]))
    return dict(bullish=sides["BULLISH"], bearish=sides["BEARISH"], asOf=str(as_of) if as_of else None,
                totalScanned=len(groups), excluded=excluded)


def analyze_snapshot(df: pl.DataFrame, instruments: dict[str, dict[str, Any]], progress=None) -> dict[str, Any]:
    # Only completed daily candles participate in any of the six strategies.
    now = datetime.now(timezone.utc)
    df = df.filter(pl.col("timestamp").map_elements(lambda ts: nse_daily_closed(ts, now), return_dtype=pl.Boolean)).sort(["instrument_key", "timestamp"])
    outputs, names, coverage = {}, {}, []
    # Sutradhar supplies intraday reference levels, not a directional signal.
    strategies = [s for s in strategy_registry.list_strategies() if s['id'] not in {'sutradhar','suryavanshi'}]
    for index, metadata in enumerate(strategies):
        if progress:
            progress(f"Checking {metadata['name']} ({index + 1}/{len(strategies)})")
        strategy = strategy_registry.get(metadata["id"])
        params = {p.name: p.default for p in strategy.metadata.parameters}
        if metadata['id']=='golden_death_cross': params['require_confirmation']=True
        window = focus_window(strategy, params)
        strategy_df = df.group_by("instrument_key", maintain_order=True).tail(window)
        outputs[metadata["id"]] = strategy.run(strategy_df, instruments, params)
        names[metadata["id"]] = metadata["name"]
        coverage.append(dict(id=metadata["id"], name=metadata["name"], rows=len(outputs[metadata["id"]]), window=window))
    if progress:
        progress("Ranking agreement and calculating targets / SL")
    result = combine(df, instruments, outputs, names)
    result.update(strategies=coverage, scannedAt=datetime.now(timezone.utc).isoformat(),
        methodology="At least two confirmed strategies from two different signal families. Super requires three confirmed strategies, score >= 6 and no opposing evidence. Trend/crossover/momentum scores capped at 3 each. These families can still be correlated; score is not a probability. Unconfirmed warnings cannot qualify a stock alone.",
        filters="Latest stored completed trading date, >=251 candles, close >= Rs 20, 20-day average turnover >= Rs 1 crore, positive latest volume, stop risk <=12%. Up to 500 recent candles per stock; Golden/Death Cross must be <=30 bars old and Ghost Rider <=5 bars old.",
        planNote="Illustrative swing levels from the reference close, not live executable prices or forecasts. Recalculate if entry changes. Bearish setups do not imply overnight cash-market short availability.")
    return result


async def focused_scan(limit: int | None = 5, progress=None) -> dict[str, Any]:
    async with _scan_lock:
        revision = await get_candle_revision("1d")
        key = f"{CACHE_VERSION}:{universe_version()}:{revision}"
        cached = await get_cached_strategy_result(key)
        if cached and cached["results"]:
            result = dict(cached["results"][0], cached=True)
        else:
            if progress:
                progress("Reading completed daily history from the database")
            instruments = {i["key"]: i for i in await get_all_active_instruments() if i["exchange"] == "NSE"}
            windows = [focus_window(strategy_registry.get(s["id"]), {p["name"]: p["default"] for p in s["parameters"]}) for s in strategy_registry.list_strategies()]
            df = await load_recent_candles_polars("1d", per_instrument=max(windows))
            df = df.filter(pl.col("instrument_key").is_in(list(instruments)))
            result = await asyncio.to_thread(analyze_snapshot, df, instruments, progress)
            result["cached"] = False
            if await get_candle_revision("1d") == revision:
                await save_strategy_result_cache(key, "focused", "1d", {}, [result], result["totalScanned"], datetime.now(timezone.utc) + timedelta(minutes=15))
        result = attach_market_caps(result)
        return dict(result, bullish=result["bullish"][:limit], bearish=result["bearish"][:limit],
                    totalBullish=len(result["bullish"]), totalBearish=len(result["bearish"]))


@router.get("")
async def get_focused(limit: int = Query(default=5, ge=1, le=200)):
    return await focused_scan(limit)


async def _run_job(job_id: str):
    job = _jobs[job_id]
    try:
        def progress(stage):
            job["stage"] = stage
        async with asyncio.timeout(240):
            job["result"] = await focused_scan(None, progress)
        job.update(status="complete", stage="Shortlist ready")
    except Exception:
        logging.getLogger(__name__).exception("Focused scan failed")
        job.update(status="failed", stage="Scan stopped", error="The combined scan could not finish. Check database access and retry.")


@router.post("/jobs")
async def start_focused_job():
    global _active_job, _active_task
    if _active_task is not None and not _active_task.done():
        return {"id": _active_job}
    # Retain only a small number of completed jobs; no unbounded user snapshots.
    while len(_jobs) >= 20:
        _jobs.pop(next(iter(_jobs)))
    job_id = uuid4().hex
    _jobs[job_id] = dict(id=job_id, status="running", stage="Checking latest scan", result=None, error="")
    _active_job = job_id
    _active_task = asyncio.create_task(_run_job(job_id))
    return {"id": job_id}


@router.get("/jobs/{job_id}")
async def focused_job_status(job_id: str):
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "This scan is no longer available. Start a new scan.")
    return job
