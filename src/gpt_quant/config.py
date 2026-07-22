from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, replace
from numbers import Integral, Number
from typing import Any


def _validated_integer(value: object, *, label: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise ValueError(f"{label} must be an integer")
    parsed = int(value)
    if parsed < minimum:
        raise ValueError(f"{label} must be at least {minimum}")
    return parsed


def _validated_real(
    value: object,
    *,
    error_message: str,
    minimum: Number | None = None,
    maximum: Number | None = None,
    minimum_inclusive: bool = True,
    maximum_inclusive: bool = True,
) -> float:
    if isinstance(value, bool) or not isinstance(value, Number) or isinstance(value, complex):
        raise ValueError(error_message)
    try:
        if not math.isfinite(value):
            raise ValueError(error_message)
        if minimum is not None:
            below_minimum = value < minimum if minimum_inclusive else value <= minimum
            if bool(below_minimum):
                raise ValueError(error_message)
        if maximum is not None:
            above_maximum = value > maximum if maximum_inclusive else value >= maximum
            if bool(above_maximum):
                raise ValueError(error_message)
        parsed = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError(error_message) from exc
    if not math.isfinite(parsed):
        raise ValueError(error_message)
    return parsed


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
        momentum_lookback = _validated_integer(
            self.momentum_lookback,
            label="momentum_lookback",
            minimum=2,
        )
        reversal_lookback = _validated_integer(
            self.reversal_lookback,
            label="reversal_lookback",
            minimum=1,
        )
        volatility_lookback = _validated_integer(
            self.volatility_lookback,
            label="volatility_lookback",
            minimum=2,
        )
        annualization = _validated_integer(
            self.annualization,
            label="annualization",
            minimum=2,
        )
        target_volatility = _validated_real(
            self.target_volatility,
            error_message="target_volatility must be in (0, 2]",
            minimum=0,
            maximum=2,
            minimum_inclusive=False,
        )
        max_abs_position_input = self.max_abs_position
        max_abs_position = _validated_real(
            max_abs_position_input,
            error_message="max_abs_position must be in (0, 10]",
            minimum=0,
            maximum=10,
            minimum_inclusive=False,
        )
        trend_weight = _validated_real(
            self.trend_weight,
            error_message="signal weights must be finite",
            minimum=0,
        )
        reversal_weight = _validated_real(
            self.reversal_weight,
            error_message="signal weights must be finite",
            minimum=0,
        )
        transaction_cost_bps = _validated_real(
            self.transaction_cost_bps,
            error_message="transaction_cost_bps must be finite and non-negative",
            minimum=0,
        )

        object.__setattr__(self, "momentum_lookback", momentum_lookback)
        object.__setattr__(self, "reversal_lookback", reversal_lookback)
        object.__setattr__(self, "volatility_lookback", volatility_lookback)
        object.__setattr__(self, "annualization", annualization)
        object.__setattr__(self, "target_volatility", target_volatility)
        object.__setattr__(self, "max_abs_position", max_abs_position)
        object.__setattr__(self, "trend_weight", trend_weight)
        object.__setattr__(self, "reversal_weight", reversal_weight)
        object.__setattr__(self, "transaction_cost_bps", transaction_cost_bps)

        minimum_is_implicit = (
            self.min_position is None
            if self._min_position_implicit is None
            else self._min_position_implicit
        )
        minimum = (
            -max_abs_position
            if self.min_position is None
            else _validated_real(
                self.min_position,
                error_message="min_position must lie within the absolute position limit",
                minimum=-max_abs_position_input,
                maximum=max_abs_position_input,
            )
        )
        object.__setattr__(self, "min_position", minimum)
        object.__setattr__(self, "_min_position_implicit", minimum_is_implicit)
        if not -max_abs_position <= minimum <= max_abs_position:
            raise ValueError("min_position must lie within the absolute position limit")
        if trend_weight + reversal_weight <= 0:
            raise ValueError("at least one signal weight must be positive")

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
