"""Strategy Registry and Execution Orchestrator with Enterprise Result Caching."""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any

from database.candle_repo import (
    get_all_active_instruments,
    get_cached_strategy_result,
    load_candles_polars,
    save_strategy_result_cache,
)
from scanner.strategies.base import BaseStrategy
from scanner.strategies.ema_alignment import EmaAlignmentStrategy
from scanner.strategies.rsi_reversal import RsiStrategy


class StrategyRegistry:
    """Central registry and executor for quantitative scanner strategies."""

    def __init__(self):
        self._strategies: dict[str, BaseStrategy] = {}
        # Register built-in strategies
        self.register(EmaAlignmentStrategy())
        self.register(RsiStrategy())

    def register(self, strategy: BaseStrategy):
        """Register a new strategy instance."""
        self._strategies[strategy.metadata.id] = strategy

    def get(self, strategy_id: str) -> BaseStrategy | None:
        """Lookup strategy by id."""
        return self._strategies.get(strategy_id)

    def list_strategies(self) -> list[dict[str, Any]]:
        """Return descriptors of all registered strategies."""
        return [strat.metadata.model_dump() for strat in self._strategies.values()]

    def _generate_cache_key(self, strategy_id: str, timeframe: str, params: dict[str, Any]) -> str:
        serialized = json.dumps(params, sort_keys=True)
        digest = hashlib.sha256(f"{strategy_id}:{timeframe}:{serialized}".encode("utf-8")).hexdigest()[:16]
        return f"{strategy_id}:{timeframe}:{digest}"

    async def execute_scan(
        self,
        strategy_id: str,
        *,
        timeframe: str = "1d",
        params: dict[str, Any] | None = None,
        bypass_cache: bool = False,
        cache_ttl_minutes: int = 15,
    ) -> dict[str, Any]:
        """
        Execute scan across universe.
        Leverages shared multi-user cache so 100+ users querying get instant results.
        """
        strategy = self.get(strategy_id)
        if not strategy:
            raise ValueError(f"Strategy '{strategy_id}' is not registered.")

        resolved_params = {}
        # Fill defaults
        for param in strategy.metadata.parameters:
            resolved_params[param.name] = param.default
        if params:
            resolved_params.update(params)

        cache_key = self._generate_cache_key(strategy_id, timeframe, resolved_params)

        # 1. Check shared cache
        if not bypass_cache:
            cached = await get_cached_strategy_result(cache_key)
            if cached is not None:
                return cached

        # 2. Load instrument metadata map
        instruments = await get_all_active_instruments()
        instruments_map = {inst["key"]: inst for inst in instruments}

        # 3. Load vectorized candles into Polars DataFrame
        df = await load_candles_polars(timeframe, min_candles=strategy.metadata.min_candles)

        # 4. Run strategy calculation in memory
        results = strategy.run(df, instruments_map, resolved_params)

        # 5. Compute distinct symbols analyzed
        total_scanned = df["instrument_key"].n_unique() if not df.is_empty() else len(instruments)

        # 6. Save to cache
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=cache_ttl_minutes)
        await save_strategy_result_cache(
            cache_key=cache_key,
            strategy_id=strategy_id,
            timeframe=timeframe,
            params=resolved_params,
            results=results,
            total_scanned=total_scanned,
            expires_at=expires_at,
        )

        return {
            "strategy_id": strategy_id,
            "strategy_name": strategy.metadata.name,
            "timeframe": timeframe,
            "total_scanned": total_scanned,
            "total_matched": len(results),
            "scanned_at": datetime.now(timezone.utc).isoformat(),
            "results": results,
            "cached": False,
        }


# Global singleton instance
strategy_registry = StrategyRegistry()
