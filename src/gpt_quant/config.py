from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import Any


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    """Parameters for the baseline single-asset ensemble strategy."""

    momentum_lookback: int = 63
    reversal_lookback: int = 5
    volatility_lookback: int = 20
    target_volatility: float = 0.12
    max_abs_position: float = 1.0
    min_position: float | None = None
    trend_weight: float = 0.70
    reversal_weight: float = 0.30
    transaction_cost_bps: float = 2.0
    annualization: int = 252
    _min_position_implicit: bool | None = field(default=None, repr=False, compare=False)

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

        minimum_is_implicit = (
            self.min_position is None
            if self._min_position_implicit is None
            else self._min_position_implicit
        )
        minimum = (
            -self.max_abs_position
            if self.min_position is None
            else float(self.min_position)
        )
        object.__setattr__(self, "min_position", minimum)
        object.__setattr__(self, "_min_position_implicit", minimum_is_implicit)
        if not -self.max_abs_position <= minimum <= self.max_abs_position:
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
        values = asdict(self)
        values.pop("_min_position_implicit")
        return values

    def with_overrides(self, **kwargs: Any) -> StrategyConfig:
        if "min_position" in kwargs:
            kwargs["_min_position_implicit"] = kwargs["min_position"] is None
        elif "max_abs_position" in kwargs and self._min_position_implicit:
            kwargs["min_position"] = None
        return replace(self, **kwargs)
