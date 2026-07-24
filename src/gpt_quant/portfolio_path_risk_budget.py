from __future__ import annotations

import hashlib
import json
import math
import os
from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass, field
from numbers import Real
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import numpy as np
import pandas as pd

from .portfolio_underlying_risk import UnderlyingSleeveRiskResult

_REPORT = "portfolio_path_risk_budget.json"
_EXPECTED_SHORTFALL_TAIL_PROBABILITY = 0.05


@dataclass(frozen=True, slots=True)
class PortfolioPathRiskBudgetResult:
    payload: dict[str, Any]
    _underlying: UnderlyingSleeveRiskResult = field(repr=False, compare=False)
    _max_annualized_net_volatility: float = field(repr=False, compare=False)
    _maximum_drawdown_floor: float = field(repr=False, compare=False)
    _max_annualized_weighted_underlying_turnover: float = field(repr=False, compare=False)
    _tolerance: float = field(repr=False, compare=False)

    @property
    def passes(self) -> bool:
        return bool(self.payload["risk_budget"]["passes"])

    @property
    def metrics(self) -> dict[str, Any]:
        return self.payload["metrics"]

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(self.payload)


def _positive_finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{label} must be a positive finite real number")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0.0:
        raise ValueError(f"{label} must be a positive finite real number")
    return parsed


def _nonnegative_finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{label} must be a non-negative finite real number")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0.0:
        raise ValueError(f"{label} must be a non-negative finite real number")
    return parsed


def _drawdown_floor(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("maximum_drawdown_floor must be a finite real number in (-1, 0)")
    parsed = float(value)
    if not math.isfinite(parsed) or not -1.0 < parsed < 0.0:
        raise ValueError("maximum_drawdown_floor must be a finite real number in (-1, 0)")
    return parsed


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _underwater_durations(
    drawdown: pd.Series,
    *,
    tolerance: float,
) -> tuple[int, int]:
    longest = 0
    current = 0
    for underwater in drawdown.lt(-tolerance):
        current = current + 1 if bool(underwater) else 0
        longest = max(longest, current)
    return current, longest


def evaluate_portfolio_path_risk_budget(
    underlying: UnderlyingSleeveRiskResult,
    *,
    max_annualized_net_volatility: float,
    maximum_drawdown_floor: float,
    max_annualized_weighted_underlying_turnover: float,
    accounting_tolerance: float = 1e-12,
) -> PortfolioPathRiskBudgetResult:
    """Evaluate explicit paper-risk budgets from the verified underlying net path."""

    if not isinstance(underlying, UnderlyingSleeveRiskResult):
        raise TypeError("underlying must be an UnderlyingSleeveRiskResult")
    volatility_limit = _positive_finite(
        max_annualized_net_volatility,
        "max_annualized_net_volatility",
    )
    drawdown_floor = _drawdown_floor(maximum_drawdown_floor)
    turnover_limit = _positive_finite(
        max_annualized_weighted_underlying_turnover,
        "max_annualized_weighted_underlying_turnover",
    )
    tolerance = _nonnegative_finite(accounting_tolerance, "accounting_tolerance")

    frame = underlying.frame
    required = {
        "portfolio_net_return",
        "portfolio_gross_return",
        "portfolio_exchange_fee",
        "portfolio_weighted_underlying_turnover",
    }
    missing = required - set(frame)
    if missing:
        raise ValueError(f"underlying risk frame is missing required columns: {sorted(missing)}")
    net_return = pd.to_numeric(frame["portfolio_net_return"], errors="raise").astype(float)
    if len(net_return) < 2 or not np.isfinite(net_return.to_numpy()).all():
        raise ValueError("portfolio net return requires at least two finite observations")
    if bool((net_return <= -1.0).any()):
        raise ValueError("portfolio net return must remain greater than -100%")

    annualization = int(underlying.payload["settings"]["annualization"])
    annualized_net_volatility = float(net_return.std(ddof=1) * math.sqrt(annualization))
    if not math.isfinite(annualized_net_volatility):
        raise RuntimeError("annualized portfolio net volatility must be finite")
    recorded_volatility = float(underlying.portfolio_metrics["annualized_net_volatility"])
    if not math.isclose(
        annualized_net_volatility,
        recorded_volatility,
        rel_tol=0.0,
        abs_tol=tolerance,
    ):
        raise RuntimeError("portfolio net volatility does not reconcile to underlying risk")

    weighted_turnover = pd.to_numeric(
        frame["portfolio_weighted_underlying_turnover"],
        errors="raise",
    ).astype(float)
    if not np.isfinite(weighted_turnover.to_numpy()).all() or bool((weighted_turnover < 0.0).any()):
        raise ValueError("portfolio weighted underlying turnover must be finite and non-negative")
    annualized_weighted_underlying_turnover = float(weighted_turnover.mean() * annualization)
    recorded_turnover = float(
        underlying.portfolio_metrics["annualized_weighted_underlying_turnover"]
    )
    if not math.isclose(
        annualized_weighted_underlying_turnover,
        recorded_turnover,
        rel_tol=0.0,
        abs_tol=tolerance,
    ):
        raise RuntimeError("portfolio underlying turnover does not reconcile to underlying risk")

    nav = (1.0 + net_return).cumprod().rename("portfolio_net_nav")
    running_peak = pd.Series(
        np.maximum.accumulate(np.concatenate(([1.0], nav.to_numpy())))[1:],
        index=nav.index,
        name="portfolio_running_peak",
    )
    drawdown = (nav / running_peak - 1.0).rename("portfolio_drawdown")
    maximum_drawdown = float(drawdown.min())
    current_drawdown = float(drawdown.iloc[-1])
    current_underwater, longest_underwater = _underwater_durations(
        drawdown,
        tolerance=tolerance,
    )

    values = net_return.to_numpy(dtype=float)
    tail_observations = max(
        1,
        math.ceil(len(values) * _EXPECTED_SHORTFALL_TAIL_PROBABILITY),
    )
    order = np.argsort(values, kind="stable")
    expected_shortfall = float(values[order[:tail_observations]].mean())
    worst_position = int(order[0])
    worst_timestamp = net_return.index[worst_position]
    worst_return = float(values[worst_position])

    volatility_passes = annualized_net_volatility <= volatility_limit + tolerance
    drawdown_passes = maximum_drawdown >= drawdown_floor - tolerance
    turnover_passes = annualized_weighted_underlying_turnover <= turnover_limit + tolerance
    failure_reasons: list[str] = []
    if not volatility_passes:
        failure_reasons.append("annualized net volatility breaches the declared limit")
    if not drawdown_passes:
        failure_reasons.append("maximum drawdown breaches the declared floor")
    if not turnover_passes:
        failure_reasons.append(
            "annualized weighted underlying turnover breaches the declared limit"
        )
    passes = not failure_reasons

    payload = {
        "schema": "portfolio_path_risk_budget_v1",
        "generated_at_utc": underlying.generated_at_utc,
        "report_only": True,
        "deployment_eligible": False,
        "underlying_risk_payload_sha256": _canonical_sha256(underlying.to_dict()),
        "settings": {
            "annualization": annualization,
            "max_annualized_net_volatility": volatility_limit,
            "maximum_drawdown_floor": drawdown_floor,
            "max_annualized_weighted_underlying_turnover": turnover_limit,
            "expected_shortfall_tail_probability": _EXPECTED_SHORTFALL_TAIL_PROBABILITY,
            "expected_shortfall_method": (
                "mean of the worst ceil(observations * 5%) daily net returns"
            ),
            "accounting_tolerance": tolerance,
            "underwater_definition": (
                "portfolio drawdown strictly below negative accounting tolerance"
            ),
            "turnover_definition": (
                "annualization times mean start-of-bar sleeve-weighted absolute "
                "underlying position turnover"
            ),
        },
        "metrics": {
            "observations": len(net_return),
            "evaluation_start": net_return.index[0].isoformat(),
            "evaluation_end": net_return.index[-1].isoformat(),
            "annualized_net_volatility": annualized_net_volatility,
            "annualized_weighted_underlying_turnover": annualized_weighted_underlying_turnover,
            "historical_expected_shortfall_95": expected_shortfall,
            "expected_shortfall_tail_observations": tail_observations,
            "worst_day_timestamp": worst_timestamp.isoformat(),
            "worst_day_net_return": worst_return,
            "current_drawdown": current_drawdown,
            "maximum_drawdown": maximum_drawdown,
            "current_underwater_duration_observations": current_underwater,
            "longest_underwater_duration_observations": longest_underwater,
        },
        "risk_budget": {
            "volatility_budget_passes": volatility_passes,
            "drawdown_budget_passes": drawdown_passes,
            "turnover_budget_passes": turnover_passes,
            "passes": passes,
            "status": "pass" if passes else "reject",
            "failure_reasons": failure_reasons,
        },
        "cost_attribution": deepcopy(underlying.cost_attribution),
    }
    return PortfolioPathRiskBudgetResult(
        payload=payload,
        _underlying=underlying,
        _max_annualized_net_volatility=volatility_limit,
        _maximum_drawdown_floor=drawdown_floor,
        _max_annualized_weighted_underlying_turnover=turnover_limit,
        _tolerance=tolerance,
    )


def write_portfolio_path_risk_budget_report(
    result: PortfolioPathRiskBudgetResult,
    output_dir: str | Path,
) -> Path:
    if not isinstance(result, PortfolioPathRiskBudgetResult):
        raise TypeError("result must be a PortfolioPathRiskBudgetResult")
    expected = evaluate_portfolio_path_risk_budget(
        result._underlying,
        max_annualized_net_volatility=result._max_annualized_net_volatility,
        maximum_drawdown_floor=result._maximum_drawdown_floor,
        max_annualized_weighted_underlying_turnover=(
            result._max_annualized_weighted_underlying_turnover
        ),
        accounting_tolerance=result._tolerance,
    )
    if result.to_dict() != expected.to_dict():
        raise ValueError("portfolio path risk budget does not match verified underlying inputs")

    output = Path(output_dir)
    existed = output.exists()
    output.mkdir(parents=True, exist_ok=True)
    destination = output / _REPORT
    data = (
        json.dumps(
            result.to_dict(),
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(mode="wb", dir=output, delete=False) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        os.replace(temporary, destination)
    except BaseException:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        if not existed:
            with suppress(OSError):
                output.rmdir()
        raise
    return destination
