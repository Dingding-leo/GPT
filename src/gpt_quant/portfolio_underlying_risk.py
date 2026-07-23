from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from io import BytesIO
from numbers import Real
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import numpy as np
import pandas as pd

_REQUIRED_COLUMNS = {
    "timestamp",
    "position",
    "turnover",
    "gross_strategy_return",
    "trading_cost",
    "strategy_return",
}
_HEX_DIGITS = frozenset("0123456789abcdef")
_DAILY_INTERVAL = pd.Timedelta(days=1)
_DEFAULT_ADJUSTMENT_THRESHOLD = 1e-12
_DEFAULT_ACCOUNTING_TOLERANCE = 1e-12
_REPORT_FILENAME = "portfolio_underlying_risk.json"


@dataclass(frozen=True, slots=True)
class _SourceBinding:
    name: str
    path: str
    sha256: str


@dataclass(frozen=True, slots=True)
class _BuildSpec:
    generated_at_utc: str
    initial_weights: tuple[tuple[str, float], ...]
    annualization: int
    exchange_fee_bps: float
    adjustment_threshold: float
    accounting_tolerance: float
    provenance_json: str
    sources: tuple[_SourceBinding, ...]


@dataclass(frozen=True, slots=True)
class UnderlyingSleeveRiskResult:
    generated_at_utc: str
    data_summary: dict[str, Any]
    settings: dict[str, Any]
    sleeve_metrics: dict[str, dict[str, float | int | str]]
    portfolio_metrics: dict[str, float | int | str]
    cost_attribution: dict[str, Any]
    frame: pd.DataFrame
    _build_spec: _BuildSpec = field(repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(
            {
                "schema": "portfolio_underlying_path_risk_v1",
                "generated_at_utc": self.generated_at_utc,
                "report_only": True,
                "deployment_eligible": False,
                "data_summary": self.data_summary,
                "settings": self.settings,
                "sleeve_metrics": self.sleeve_metrics,
                "portfolio_metrics": self.portfolio_metrics,
                "cost_attribution": self.cost_attribution,
            }
        )


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _validated_sha256(value: object, *, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a SHA-256 hexadecimal string")
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(character not in _HEX_DIGITS for character in normalized):
        raise ValueError(f"{label} must be a 64-character SHA-256 hexadecimal string")
    return normalized


def _validated_positive_real(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{label} must be a positive finite real number")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0.0:
        raise ValueError(f"{label} must be a positive finite real number")
    return parsed


def _validated_nonnegative_real(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{label} must be a non-negative finite real number")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0.0:
        raise ValueError(f"{label} must be a non-negative finite real number")
    return parsed


def _explicit_utc_index(values: pd.Series, *, label: str) -> pd.DatetimeIndex:
    parsed: list[pd.Timestamp] = []
    for row, value in enumerate(values):
        try:
            timestamp = pd.Timestamp(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{label} timestamp at row {row} is invalid") from exc
        if pd.isna(timestamp) or timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError(f"{label} timestamps must contain explicit timezone information")
        if timestamp.utcoffset().total_seconds() != 0.0:
            raise ValueError(f"{label} timestamps must use an explicit UTC offset")
        parsed.append(timestamp.tz_convert("UTC"))

    index = pd.DatetimeIndex(parsed)
    if index.has_duplicates or not index.is_monotonic_increasing:
        raise ValueError(f"{label} timestamps must be unique and strictly increasing")
    if not bool((index == index.normalize()).all()):
        raise ValueError(f"{label} timestamps must be aligned to midnight UTC")
    if len(index) > 1 and not bool(((index[1:] - index[:-1]) == _DAILY_INTERVAL).all()):
        raise ValueError(f"{label} timestamps must have exact daily cadence")
    return index


def _numeric_column(frame: pd.DataFrame, name: str) -> pd.Series:
    try:
        values = pd.to_numeric(frame[name], errors="raise").astype(float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must contain finite numeric values") from exc
    if not np.isfinite(values.to_numpy(copy=False)).all():
        raise ValueError(f"{name} must contain finite numeric values")
    return values


def _load_verified_path(
    path: str | Path,
    *,
    expected_sha256: str,
    exchange_fee_bps: float,
    accounting_tolerance: float,
) -> pd.DataFrame:
    source = Path(path)
    expected = _validated_sha256(expected_sha256, label="expected source hash")
    payload = source.read_bytes()
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected:
        raise ValueError(f"underlying path hash mismatch: expected {expected}, actual {actual}")

    frame = pd.read_csv(BytesIO(payload))
    missing = _REQUIRED_COLUMNS - set(frame)
    if missing:
        raise ValueError(f"underlying path is missing required columns: {sorted(missing)}")
    index = _explicit_utc_index(frame["timestamp"], label="underlying path")

    validated = pd.DataFrame(index=index)
    for name in sorted(_REQUIRED_COLUMNS - {"timestamp"}):
        validated[name] = _numeric_column(frame, name).to_numpy()
    if (validated["turnover"] < 0.0).any() or (validated["trading_cost"] < 0.0).any():
        raise ValueError("turnover and trading_cost must be non-negative")
    if (validated["strategy_return"] <= -1.0).any() or (
        validated["gross_strategy_return"] <= -1.0
    ).any():
        raise ValueError("gross and net strategy returns must remain greater than -100%")

    expected_turnover = validated["position"].diff().abs()
    expected_turnover.iloc[0] = abs(float(validated["position"].iloc[0]))
    if not np.allclose(
        validated["turnover"].to_numpy(copy=False),
        expected_turnover.to_numpy(copy=False),
        rtol=0.0,
        atol=accounting_tolerance,
    ):
        raise ValueError("turnover must equal absolute underlying position changes")

    fee_rate = exchange_fee_bps / 10_000.0
    expected_fee = validated["turnover"] * fee_rate
    if not np.allclose(
        validated["trading_cost"].to_numpy(copy=False),
        expected_fee.to_numpy(copy=False),
        rtol=0.0,
        atol=accounting_tolerance,
    ):
        raise ValueError("trading_cost must equal turnover times the declared 5 bps exchange fee")

    expected_net = validated["gross_strategy_return"] - validated["trading_cost"]
    if not np.allclose(
        validated["strategy_return"].to_numpy(copy=False),
        expected_net.to_numpy(copy=False),
        rtol=0.0,
        atol=accounting_tolerance,
    ):
        raise ValueError("net strategy return must equal gross return minus exchange fee")

    validated.attrs["source_path"] = str(source.resolve())
    validated.attrs["source_sha256"] = actual
    return validated


def _validate_weights(
    names: tuple[str, ...], initial_weights: Mapping[str, float]
) -> pd.Series:
    if set(initial_weights) != set(names):
        raise ValueError("initial_weights keys must exactly match underlying sleeve names")
    weights = pd.Series({name: float(initial_weights[name]) for name in names}, dtype=float)
    if not np.isfinite(weights.to_numpy()).all() or (weights <= 0.0).any():
        raise ValueError("initial weights must be strictly positive finite values")
    if not math.isclose(float(weights.sum()), 1.0, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("initial weights must sum to one")
    return weights


def _compounded_return(values: pd.Series) -> float:
    return float((1.0 + values).prod() - 1.0)


def build_underlying_sleeve_risk(
    sleeve_paths: Mapping[str, str | Path],
    *,
    expected_sha256: Mapping[str, str],
    initial_weights: Mapping[str, float],
    provenance: Mapping[str, Any],
    annualization: int = 365,
    exchange_fee_bps: float = 5.0,
    adjustment_threshold: float = _DEFAULT_ADJUSTMENT_THRESHOLD,
    accounting_tolerance: float = _DEFAULT_ACCOUNTING_TOLERANCE,
    _generated_at_utc: str | None = None,
) -> UnderlyingSleeveRiskResult:
    """Expose source-bound underlying position, turnover, and fee risk without claiming orders."""

    names = tuple(sorted(str(name) for name in sleeve_paths))
    if len(names) < 2 or set(expected_sha256) != set(names):
        raise ValueError("underlying risk requires matching evidence for at least two sleeves")
    if isinstance(annualization, bool) or not isinstance(annualization, int) or annualization < 2:
        raise ValueError("annualization must be an integer of at least 2")
    fee_bps = _validated_positive_real(exchange_fee_bps, label="exchange_fee_bps")
    if not math.isclose(fee_bps, 5.0, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("underlying live-readiness risk requires the declared 5 bps fee baseline")
    adjustment = _validated_nonnegative_real(
        adjustment_threshold, label="adjustment_threshold"
    )
    tolerance = _validated_nonnegative_real(accounting_tolerance, label="accounting_tolerance")
    weights = _validate_weights(names, initial_weights)

    paths = {
        name: _load_verified_path(
            sleeve_paths[name],
            expected_sha256=expected_sha256[name],
            exchange_fee_bps=fee_bps,
            accounting_tolerance=tolerance,
        )
        for name in names
    }
    reference_index = paths[names[0]].index
    for name in names[1:]:
        if not paths[name].index.equals(reference_index):
            raise ValueError("underlying sleeve path indexes must match exactly")

    net_returns = pd.DataFrame(
        {name: paths[name]["strategy_return"] for name in names}, index=reference_index
    )
    gross_returns = pd.DataFrame(
        {name: paths[name]["gross_strategy_return"] for name in names},
        index=reference_index,
    )
    trading_cost = pd.DataFrame(
        {name: paths[name]["trading_cost"] for name in names}, index=reference_index
    )
    positions = pd.DataFrame(
        {name: paths[name]["position"] for name in names}, index=reference_index
    )
    turnover = pd.DataFrame(
        {name: paths[name]["turnover"] for name in names}, index=reference_index
    )

    sleeve_nav = (1.0 + net_returns).cumprod()
    sleeve_values = sleeve_nav.mul(weights, axis=1)
    portfolio_nav = sleeve_values.sum(axis=1)
    end_weights = sleeve_values.div(portfolio_nav, axis=0)
    start_weights = end_weights.shift(1)
    start_weights.iloc[0] = weights

    weighted_net = start_weights * net_returns
    weighted_gross = start_weights * gross_returns
    weighted_fee = start_weights * trading_cost
    portfolio_net = weighted_net.sum(axis=1)
    portfolio_gross = weighted_gross.sum(axis=1)
    portfolio_fee = weighted_fee.sum(axis=1)
    if not np.allclose(
        portfolio_net.to_numpy(copy=False),
        (portfolio_gross - portfolio_fee).to_numpy(copy=False),
        rtol=0.0,
        atol=tolerance,
    ):
        raise RuntimeError("portfolio gross, fee, and net contributions do not reconcile")
    nav_return = portfolio_nav.pct_change()
    nav_return.iloc[0] = portfolio_nav.iloc[0] - 1.0
    if not np.allclose(
        portfolio_net.to_numpy(copy=False),
        nav_return.to_numpy(copy=False),
        rtol=0.0,
        atol=tolerance,
    ):
        raise RuntimeError("portfolio weighted net returns do not reconcile to sleeve capital")

    absolute_exposure = start_weights * positions.abs()
    portfolio_exposure = absolute_exposure.sum(axis=1)
    weighted_turnover = start_weights * turnover
    portfolio_turnover = weighted_turnover.sum(axis=1)
    current_exposure = float((end_weights.iloc[-1] * positions.iloc[-1].abs()).sum())

    sleeve_metrics: dict[str, dict[str, float | int | str]] = {}
    for name in names:
        sleeve_gross = gross_returns[name]
        sleeve_net = net_returns[name]
        sleeve_fee = trading_cost[name]
        sleeve_turnover = turnover[name]
        sleeve_position = positions[name].abs()
        sleeve_metrics[name] = {
            "observations": len(reference_index),
            "evaluation_start": reference_index[0].isoformat(),
            "evaluation_end": reference_index[-1].isoformat(),
            "average_absolute_exposure": float(sleeve_position.mean()),
            "current_absolute_exposure": float(sleeve_position.iloc[-1]),
            "maximum_absolute_exposure": float(sleeve_position.max()),
            "total_absolute_turnover": float(sleeve_turnover.sum()),
            "annualized_underlying_turnover": float(sleeve_turnover.mean() * annualization),
            "position_adjustment_count": int((sleeve_turnover > adjustment).sum()),
            "annualized_position_adjustment_count": float(
                (sleeve_turnover > adjustment).sum() * annualization / len(reference_index)
            ),
            "exchange_fee_sum": float(sleeve_fee.sum()),
            "gross_total_return": _compounded_return(sleeve_gross),
            "net_total_return": _compounded_return(sleeve_net),
            "compounded_exchange_fee_drag": (
                _compounded_return(sleeve_gross) - _compounded_return(sleeve_net)
            ),
            "source_sha256": paths[name].attrs["source_sha256"],
        }

    portfolio_metrics: dict[str, float | int | str] = {
        "observations": len(reference_index),
        "evaluation_start": reference_index[0].isoformat(),
        "evaluation_end": reference_index[-1].isoformat(),
        "average_start_of_bar_absolute_market_exposure": float(portfolio_exposure.mean()),
        "current_absolute_market_exposure": current_exposure,
        "maximum_start_of_bar_absolute_market_exposure": float(portfolio_exposure.max()),
        "total_weighted_underlying_turnover": float(portfolio_turnover.sum()),
        "annualized_weighted_underlying_turnover": float(
            portfolio_turnover.mean() * annualization
        ),
        "underlying_adjustment_observation_count": int(
            (turnover.gt(adjustment).any(axis=1)).sum()
        ),
        "portfolio_exchange_fee_sum": float(portfolio_fee.sum()),
        "gross_total_return": _compounded_return(portfolio_gross),
        "net_total_return": _compounded_return(portfolio_net),
        "compounded_exchange_fee_drag": (
            _compounded_return(portfolio_gross) - _compounded_return(portfolio_net)
        ),
    }

    output = pd.DataFrame(index=reference_index)
    for name in names:
        output[f"{name}_position"] = positions[name]
        output[f"{name}_turnover"] = turnover[name]
        output[f"{name}_start_weight"] = start_weights[name]
        output[f"{name}_absolute_exposure_contribution"] = absolute_exposure[name]
        output[f"{name}_weighted_turnover"] = weighted_turnover[name]
        output[f"{name}_weighted_exchange_fee"] = weighted_fee[name]
    output["portfolio_absolute_market_exposure"] = portfolio_exposure
    output["portfolio_weighted_underlying_turnover"] = portfolio_turnover
    output["portfolio_exchange_fee"] = portfolio_fee
    output["portfolio_gross_return"] = portfolio_gross
    output["portfolio_net_return"] = portfolio_net

    generated_at = _generated_at_utc or datetime.now(UTC).isoformat()
    provenance_copy = deepcopy(dict(provenance))
    bindings = tuple(
        _SourceBinding(
            name=name,
            path=paths[name].attrs["source_path"],
            sha256=paths[name].attrs["source_sha256"],
        )
        for name in names
    )
    build_spec = _BuildSpec(
        generated_at_utc=generated_at,
        initial_weights=tuple((name, float(weights[name])) for name in names),
        annualization=annualization,
        exchange_fee_bps=fee_bps,
        adjustment_threshold=adjustment,
        accounting_tolerance=tolerance,
        provenance_json=_canonical_json(provenance_copy),
        sources=bindings,
    )

    return UnderlyingSleeveRiskResult(
        generated_at_utc=generated_at,
        data_summary={
            "provider": provenance_copy.get("provider"),
            "market_type": provenance_copy.get("market_type"),
            "timeframe": provenance_copy.get("timeframe"),
            "sleeves": list(names),
            "provenance": provenance_copy,
        },
        settings={
            "annualization": annualization,
            "initial_weights": {name: float(weights[name]) for name in names},
            "position_interpretation": (
                "research position applied to the underlying sleeve; not an exchange order or fill"
            ),
            "portfolio_exposure_method": (
                "start-of-bar buy-and-hold sleeve capital weight times absolute sleeve position"
            ),
            "portfolio_turnover_method": (
                "start-of-bar buy-and-hold sleeve capital weight times sleeve absolute turnover"
            ),
            "position_adjustment_threshold": adjustment,
            "accounting_tolerance": tolerance,
        },
        sleeve_metrics=sleeve_metrics,
        portfolio_metrics=portfolio_metrics,
        cost_attribution={
            "exchange_fee": {
                "status": "modeled",
                "one_way_bps": fee_bps,
                "method": "absolute underlying position turnover times 5 bps",
            },
            "all_in_fixed_path_sensitivity_bps": [7.5, 10.0, 15.0],
            "all_in_sensitivity_location": (
                "per-sleeve walk-forward research reports; not recomputed by this aggregation"
            ),
            "spread": {"status": "not_modeled"},
            "slippage": {"status": "not_modeled"},
            "market_impact": {"status": "not_modeled"},
            "latency": {"status": "not_modeled"},
        },
        frame=output,
        _build_spec=build_spec,
    )


def _validate_against_sources(result: UnderlyingSleeveRiskResult) -> None:
    spec = result._build_spec
    expected = build_underlying_sleeve_risk(
        {binding.name: binding.path for binding in spec.sources},
        expected_sha256={binding.name: binding.sha256 for binding in spec.sources},
        initial_weights=dict(spec.initial_weights),
        provenance=json.loads(spec.provenance_json),
        annualization=spec.annualization,
        exchange_fee_bps=spec.exchange_fee_bps,
        adjustment_threshold=spec.adjustment_threshold,
        accounting_tolerance=spec.accounting_tolerance,
        _generated_at_utc=spec.generated_at_utc,
    )
    if result.to_dict() != expected.to_dict():
        raise ValueError("underlying risk result does not match its verified source inputs")
    try:
        pd.testing.assert_frame_equal(
            result.frame,
            expected.frame,
            check_exact=True,
            check_freq=False,
        )
    except AssertionError as exc:
        raise ValueError(
            "underlying risk frame does not match its verified source inputs"
        ) from exc


def write_underlying_sleeve_risk_report(
    result: UnderlyingSleeveRiskResult,
    output_dir: str | Path,
) -> Path:
    if not isinstance(result, UnderlyingSleeveRiskResult):
        raise TypeError("result must be an UnderlyingSleeveRiskResult")
    _validate_against_sources(result)

    output = Path(output_dir)
    output_preexisted = output.exists()
    output.mkdir(parents=True, exist_ok=True)
    destination = output / _REPORT_FILENAME
    payload = (
        json.dumps(
            result.to_dict(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")

    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="wb",
            prefix=f".{_REPORT_FILENAME}.",
            suffix=".tmp",
            dir=output,
            delete=False,
        ) as temporary:
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, destination)
    except BaseException:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        if not output_preexisted:
            try:
                output.rmdir()
            except OSError:
                pass
        raise
    return destination
