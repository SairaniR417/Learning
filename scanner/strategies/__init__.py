"""Strategies package."""

from scanner.strategies.base import BaseStrategy, StrategyMetadata, StrategyParameter
from scanner.strategies.ema_alignment import EmaAlignmentStrategy
from scanner.strategies.golden_death_cross import GoldenDeathCrossStrategy
from scanner.strategies.multi_ma_bullish import MultiMovingAverageBullishStrategy
from scanner.strategies.registry import StrategyRegistry, strategy_registry
from scanner.strategies.rsi_reversal import RsiStrategy

__all__ = [
    "BaseStrategy",
    "StrategyMetadata",
    "StrategyParameter",
    "EmaAlignmentStrategy",
    "GoldenDeathCrossStrategy",
    "MultiMovingAverageBullishStrategy",
    "RsiStrategy",
    "StrategyRegistry",
    "strategy_registry",
]
