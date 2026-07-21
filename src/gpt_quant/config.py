from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    """Parameters for the baseline single-asset ensemble strategy."""

    momentum_lookback: int = 63
    reversal_lookback: int = 5
    volatility_lookback: int = 20
    target_volatility: float = 0.12
    max_abs_position: float = 1.0
    min_position: float = -1.0
    trend_weight: float = 0.70
    reversal_weight: float = 0.30
    transaction_cost_bps: float = 2.0
    annualization: int = 252

    def __post_init__(self) -> None:
        if self.momentum_lookback < 2:
            raise ValueError("momentum_lookback must be at least 2")
        if self.reversal_lookback < 1:
            raise ValueError("reversal_lookback must be positive")
        if self.volatility_lookback < 2:
            raise ValueError("volatility_lookback must be at least 2")
        if not 0 < self.target_volatility <= 2:
            raise ValueError("target_volatility must be in (0, 2]")
        if not 0 < self.max_abs_position <= 10:
            raise ValueError("max_abs_position must be in (0, 10]")
        if not -self.max_abs_position <= self.min_position <= self.max_abs_position:
            raise ValueError("min_position must lie within the absolute position limit")
        if self.trend_weight < 0 or self.reversal_weight < 0:
            raise ValueError("signal weights cannot be negative")
        if self.trend_weight + self.reversal_weight <= 0:
            raise ValueError("at least one signal weight must be positive")
        if self.transaction_cost_bps < 0:
            raise ValueError("transaction_cost_bps cannot be negative")
        if self.annualization < 2:
            raise ValueError("annualization must be at least 2")

    def normalized_weights(self) -> tuple[float, float]:
        total = self.trend_weight + self.reversal_weight
        return self.trend_weight / total, self.reversal_weight / total

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def with_overrides(self, **kwargs: Any) -> StrategyConfig:
        return replace(self, **kwargs)
