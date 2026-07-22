from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from io import BytesIO
from numbers import Real
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .metrics import performance_metrics

_DAILY_INTERVAL = pd.Timedelta(days=1)
_HEX_DIGITS = frozenset("0123456789abcdef")
_VERIFIED_RETURN_SOURCE_ATTR = "_gpt_quant_verified_return_source"
_REQUIRED_PROVENANCE_LITERALS = {
    "provider": "OKX",
    "market_type": "spot",
    "timeframe": "1Dutc",
}


@dataclass(frozen=True, slots=True)
class _VerifiedReturnBinding:
    name: str
    path: str
    sha256: str
    timestamp_column: str
    return_column: str
    selected_timestamps: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _PortfolioBuildSpec:
    generated_at_utc: str
    initial_weights: tuple[tuple[str, float], ...]
    annualization: int
    max_sleeve_weight: float
    provenance_json: str
    return_bindings: tuple[_VerifiedReturnBinding, ...]


@dataclass(frozen=True, slots=True)
class PortfolioRiskResult:
    generated_at_utc: str
    data_summary: dict[str, Any]
    settings: dict[str, Any]
    portfolio_metrics: dict[str, float | int]
    sleeve_metrics: dict[str, dict[str, float | int]]
    dependence: dict[str, Any]
    risk_contributions: dict[str, float]
    concentration: dict[str, Any]
    risk_status: str
    frame: pd.DataFrame
    _build_spec: _PortfolioBuildSpec = field(repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(
            {
                "generated_at_utc": self.generated_at_utc,
                "data_summary": self.data_summary,
                "settings": self.settings,
                "portfolio_metrics": self.portfolio_metrics,
                "sleeve_metrics": self.sleeve_metrics,
                "dependence": self.dependence,
                "risk_contributions": self.risk_contributions,
                "concentration": self.concentration,
                "risk_status": self.risk_status,
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


def _validated_hex_digest(value: object, *, lengths: set[int], label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a hexadecimal string")
    normalized = value.strip().lower()
    if len(normalized) not in lengths or any(
        character not in _HEX_DIGITS for character in normalized
    ):
        expected = " or ".join(str(length) for length in sorted(lengths))
        raise ValueError(f"{label} must be a {expected}-character hexadecimal digest")
    return normalized


def _validated_positive_int(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _validated_sleeve_names(expected_sleeves: Iterable[str]) -> tuple[str, ...]:
    names = tuple(sorted(str(name) for name in expected_sleeves))
    if len(names) < 2 or len(set(names)) != len(names):
        raise ValueError("provenance requires at least two unique sleeve names")
    return names


def validate_portfolio_provenance(
    provenance: Mapping[str, Any],
    *,
    expected_sleeves: Iterable[str],
) -> dict[str, Any]:
    """Validate the evidence required for any portfolio-risk result or report."""

    if not isinstance(provenance, Mapping):
        raise ValueError("portfolio provenance must be a mapping")
    names = _validated_sleeve_names(expected_sleeves)
    required_fields = {
        *_REQUIRED_PROVENANCE_LITERALS,
        "source_workflow_run_id",
        "source_artifact_id",
        "source_artifact_name",
        "source_artifact_sha256",
        "source_head_sha",
        "return_file_sha256",
    }
    missing = required_fields - set(provenance)
    if missing:
        raise ValueError(f"portfolio provenance is missing required fields: {sorted(missing)}")

    validated = dict(provenance)
    for provenance_field, expected in _REQUIRED_PROVENANCE_LITERALS.items():
        if provenance[provenance_field] != expected:
            raise ValueError(f"portfolio provenance {provenance_field} must be {expected!r}")
        validated[provenance_field] = expected

    validated["source_workflow_run_id"] = _validated_positive_int(
        provenance["source_workflow_run_id"],
        label="source_workflow_run_id",
    )
    validated["source_artifact_id"] = _validated_positive_int(
        provenance["source_artifact_id"],
        label="source_artifact_id",
    )

    artifact_name = provenance["source_artifact_name"]
    if not isinstance(artifact_name, str) or not artifact_name.strip():
        raise ValueError("source_artifact_name must be a non-empty string")
    validated["source_artifact_name"] = artifact_name.strip()
    validated["source_artifact_sha256"] = _validated_hex_digest(
        provenance["source_artifact_sha256"],
        lengths={64},
        label="source_artifact_sha256",
    )
    validated["source_head_sha"] = _validated_hex_digest(
        provenance["source_head_sha"],
        lengths={40, 64},
        label="source_head_sha",
    )

    return_hashes = provenance["return_file_sha256"]
    if not isinstance(return_hashes, Mapping):
        raise ValueError("return_file_sha256 must be a mapping")
    if set(return_hashes) != set(names):
        raise ValueError("return_file_sha256 keys must exactly match portfolio sleeves")
    validated["return_file_sha256"] = {
        name: _validated_hex_digest(
            return_hashes[name],
            lengths={64},
            label=f"return_file_sha256[{name}]",
        )
        for name in names
    }
    return validated


def _validate_daily_utc_index(index: pd.DatetimeIndex, *, label: str) -> pd.DatetimeIndex:
    if index.tz is None:
        raise ValueError(f"{label} timestamps must be timezone-aware")
    utc_index = index.tz_convert("UTC")
    if not bool((utc_index == utc_index.normalize()).all()):
        raise ValueError(f"{label} timestamps must be aligned to midnight UTC")
    if utc_index.duplicated().any():
        raise ValueError(f"{label} timestamps must be unique")
    if not utc_index.is_monotonic_increasing:
        raise ValueError(f"{label} timestamps must be strictly increasing")
    if len(utc_index) > 1:
        intervals = utc_index[1:] - utc_index[:-1]
        if not bool((intervals == _DAILY_INTERVAL).all()):
            raise ValueError(f"{label} timestamps must have exact daily cadence")
    return utc_index


def _parse_explicit_timezone_index(values: pd.Series, *, label: str) -> pd.DatetimeIndex:
    parsed_timestamps: list[pd.Timestamp] = []
    for value in values:
        try:
            timestamp = pd.Timestamp(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{label} timestamps must be valid and timezone-aware") from exc
        if pd.isna(timestamp):
            raise ValueError(f"{label} timestamps must be valid and timezone-aware")
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError(f"{label} timestamps must contain explicit timezone information")
        parsed_timestamps.append(timestamp)
    return pd.DatetimeIndex(pd.to_datetime(parsed_timestamps, utc=True))


def _finite_float_or_none(value: object) -> float | None:
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def load_verified_return_csv(
    path: str | Path,
    *,
    expected_sha256: str,
    timestamp_column: str = "timestamp",
    return_column: str = "strategy_return",
) -> pd.Series:
    """Load one immutable real-return series after verifying its exact file hash."""

    source = Path(path)
    expected = expected_sha256.strip().lower()
    if len(expected) != 64 or any(character not in _HEX_DIGITS for character in expected):
        raise ValueError("expected_sha256 must be a 64-character hexadecimal digest")
    payload = source.read_bytes()
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected:
        raise ValueError(f"return file hash mismatch: expected {expected}, actual {actual}")

    frame = pd.read_csv(BytesIO(payload))
    missing = {timestamp_column, return_column} - set(frame.columns)
    if missing:
        raise ValueError(f"return file is missing required columns: {sorted(missing)}")

    timestamps = _parse_explicit_timezone_index(frame[timestamp_column], label="return")
    index = _validate_daily_utc_index(timestamps, label="return")

    values = pd.to_numeric(frame[return_column], errors="coerce").astype(float)
    if values.isna().any() or not np.isfinite(values.to_numpy()).all():
        raise ValueError("returns must be finite numeric values")
    if (values <= -1.0).any():
        raise ValueError("returns must be greater than -100%")

    series = pd.Series(values.to_numpy(), index=index, name=return_column)
    if len(series) < 20:
        raise ValueError("return series must contain at least 20 observations")
    series.attrs[_VERIFIED_RETURN_SOURCE_ATTR] = {
        "path": str(source.resolve()),
        "sha256": actual,
        "timestamp_column": timestamp_column,
        "return_column": return_column,
    }
    return series


def _validated_return_source_binding(
    name: str,
    supplied: pd.Series,
    *,
    expected_sha256: str,
) -> _VerifiedReturnBinding:
    evidence = supplied.attrs.get(_VERIFIED_RETURN_SOURCE_ATTR)
    if not isinstance(evidence, Mapping):
        raise ValueError(
            f"{name} returns must come from load_verified_return_csv before portfolio metrics"
        )

    source_path = evidence.get("path")
    source_sha256 = evidence.get("sha256")
    timestamp_column = evidence.get("timestamp_column")
    return_column = evidence.get("return_column")
    if not all(
        isinstance(value, str) and value
        for value in (source_path, source_sha256, timestamp_column, return_column)
    ):
        raise ValueError(f"{name} verified return source evidence is malformed")

    if source_sha256 != expected_sha256:
        raise ValueError(
            f"{name} provenance hash does not match the hash verified by load_verified_return_csv"
        )

    verified_source = load_verified_return_csv(
        source_path,
        expected_sha256=expected_sha256,
        timestamp_column=timestamp_column,
        return_column=return_column,
    )
    missing_timestamps = supplied.index.difference(verified_source.index)
    if len(missing_timestamps):
        raise ValueError(f"{name} returns contain timestamps absent from the verified source")

    expected_rows = verified_source.loc[supplied.index]
    supplied_values = pd.Series(
        pd.to_numeric(supplied, errors="coerce").to_numpy(dtype=float),
        index=supplied.index,
        name=return_column,
    )
    try:
        pd.testing.assert_series_equal(
            supplied_values,
            expected_rows,
            check_names=True,
            check_freq=False,
            check_exact=True,
        )
    except AssertionError as exc:
        raise ValueError(f"{name} returns do not match verified return source bytes") from exc

    return _VerifiedReturnBinding(
        name=name,
        path=source_path,
        sha256=source_sha256,
        timestamp_column=timestamp_column,
        return_column=return_column,
        selected_timestamps=tuple(
            timestamp.isoformat() for timestamp in supplied.index.tz_convert("UTC")
        ),
    )


def _validate_return_source_bindings(
    sleeve_returns: Mapping[str, pd.Series],
    *,
    expected_sha256: Mapping[str, str],
) -> tuple[_VerifiedReturnBinding, ...]:
    """Bind each in-memory sleeve exactly to rows from its verified source file."""

    return tuple(
        _validated_return_source_binding(
            name,
            sleeve_returns[name],
            expected_sha256=expected_sha256[name],
        )
        for name in sorted(sleeve_returns)
    )


def _validate_sleeves(
    sleeve_returns: Mapping[str, pd.Series],
    initial_weights: Mapping[str, float],
) -> tuple[pd.DataFrame, pd.Series]:
    if len(sleeve_returns) < 2:
        raise ValueError("portfolio risk requires at least two sleeves")
    names = tuple(sorted(str(name) for name in sleeve_returns))
    if set(initial_weights) != set(names):
        raise ValueError("initial_weights keys must exactly match sleeve return keys")

    raw_weights = [initial_weights[name] for name in names]
    if any(isinstance(value, bool) or not isinstance(value, Real) for value in raw_weights):
        raise ValueError("initial weights must be strictly positive real numbers")
    weights = pd.Series({name: float(initial_weights[name]) for name in names}, dtype=float)
    if not np.isfinite(weights.to_numpy()).all() or (weights <= 0.0).any():
        raise ValueError("initial weights must be strictly positive real numbers")
    if not math.isclose(float(weights.sum()), 1.0, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("initial weights must sum to one")

    validated: dict[str, pd.Series] = {}
    reference_index: pd.DatetimeIndex | None = None
    for name in names:
        source = sleeve_returns[name]
        if not isinstance(source.index, pd.DatetimeIndex):
            raise TypeError(f"{name} returns must use a DatetimeIndex")
        index = _validate_daily_utc_index(source.index, label=f"{name} return")
        values = pd.to_numeric(source, errors="coerce").astype(float)
        if values.isna().any() or not np.isfinite(values.to_numpy()).all():
            raise ValueError(f"{name} returns must be finite")
        if (values <= -1.0).any():
            raise ValueError(f"{name} returns must be greater than -100%")
        series = pd.Series(values.to_numpy(), index=index, name=name)
        if reference_index is None:
            reference_index = index
        elif not index.equals(reference_index):
            raise ValueError(
                "sleeve return indexes must match exactly; implicit alignment is forbidden"
            )
        validated[name] = series

    frame = pd.DataFrame(validated)
    if len(frame) < 20:
        raise ValueError("aligned sleeve returns must contain at least 20 observations")
    return frame, weights


def build_buy_and_hold_sleeve_portfolio(
    sleeve_returns: Mapping[str, pd.Series],
    *,
    initial_weights: Mapping[str, float],
    provenance: Mapping[str, Any],
    annualization: int = 365,
    max_sleeve_weight: float = 0.75,
) -> PortfolioRiskResult:
    """Aggregate net sleeve returns without same-sample weight optimisation or rebalancing."""

    validated_provenance = validate_portfolio_provenance(
        provenance,
        expected_sleeves=sleeve_returns,
    )
    if isinstance(annualization, bool) or not isinstance(annualization, int) or annualization < 2:
        raise ValueError("annualization must be an integer of at least 2")
    if (
        isinstance(max_sleeve_weight, bool)
        or not isinstance(max_sleeve_weight, Real)
        or not math.isfinite(float(max_sleeve_weight))
        or not 0.0 < float(max_sleeve_weight) < 1.0
    ):
        raise ValueError("max_sleeve_weight must be a finite real number in (0, 1)")
    max_sleeve_weight = float(max_sleeve_weight)

    returns, weights = _validate_sleeves(sleeve_returns, initial_weights)
    bindings = _validate_return_source_bindings(
        sleeve_returns,
        expected_sha256=validated_provenance["return_file_sha256"],
    )
    sleeve_nav = (1.0 + returns).cumprod()
    sleeve_values = sleeve_nav.mul(weights, axis=1)
    portfolio_nav = sleeve_values.sum(axis=1).rename("nav")
    portfolio_return = portfolio_nav.pct_change()
    portfolio_return.iloc[0] = portfolio_nav.iloc[0] - 1.0
    portfolio_return = portfolio_return.rename("strategy_return")

    end_weights = sleeve_values.div(portfolio_nav, axis=0)
    start_weights = end_weights.shift(1)
    start_weights.iloc[0] = weights
    return_contributions = start_weights * returns
    contribution_error = (return_contributions.sum(axis=1) - portfolio_return).abs().max()
    if float(contribution_error) > 1e-12:
        raise RuntimeError("sleeve return contributions do not reconcile to portfolio return")

    output = pd.DataFrame(index=returns.index)
    for name in returns:
        output[f"{name}_return"] = returns[name]
        output[f"{name}_start_weight"] = start_weights[name]
        output[f"{name}_end_weight"] = end_weights[name]
        output[f"{name}_return_contribution"] = return_contributions[name]
    output["position"] = 1.0
    output["turnover"] = 0.0
    output["trading_cost"] = 0.0
    output["strategy_return"] = portfolio_return
    output["nav"] = portfolio_nav

    portfolio_metrics = performance_metrics(output, annualization=annualization)
    sleeve_metrics: dict[str, dict[str, float | int]] = {}
    for name in returns:
        metrics = performance_metrics(
            pd.DataFrame({"strategy_return": returns[name]}, index=returns.index),
            annualization=annualization,
        )
        for unavailable in (
            "annualized_turnover",
            "average_abs_exposure",
            "cost_drag_sum",
        ):
            metrics.pop(unavailable)
        sleeve_metrics[name] = metrics

    correlation = returns.corr()
    covariance = np.cov(returns.to_numpy(), rowvar=False, ddof=0) * annualization
    weight_vector = weights.to_numpy()
    marginal_variance = covariance @ weight_vector
    portfolio_variance = float(weight_vector @ marginal_variance)
    if portfolio_variance > 0.0:
        contributions = weight_vector * marginal_variance / portfolio_variance
    else:
        contributions = np.zeros_like(weight_vector)
    risk_contributions = {
        name: float(value) for name, value in zip(returns.columns, contributions, strict=True)
    }

    max_weights = end_weights.max().combine(weights, max)
    initial_weight_breach = bool(weights.gt(max_sleeve_weight).any())
    breach_mask = end_weights.gt(max_sleeve_weight).any(axis=1)
    worst_timestamp = portfolio_return.idxmin()
    concentration = {
        "maximum_allowed_sleeve_weight": max_sleeve_weight,
        "maximum_observed_weights": {name: float(max_weights[name]) for name in returns},
        "ending_weights": {name: float(end_weights.iloc[-1][name]) for name in returns},
        "initial_weight_breach": initial_weight_breach,
        "breach_observations": int(breach_mask.sum()),
        "breach_ratio": float(breach_mask.mean()),
        "passes": not initial_weight_breach and not bool(breach_mask.any()),
        "worst_portfolio_day": {
            "timestamp": worst_timestamp.isoformat(),
            "portfolio_return": float(portfolio_return.loc[worst_timestamp]),
            "sleeve_return_contributions": {
                name: float(return_contributions.loc[worst_timestamp, name]) for name in returns
            },
        },
    }
    risk_status = (
        "pass: sleeve weights remain within the declared concentration limit"
        if concentration["passes"]
        else "reject: buy-and-hold sleeve drift breaches the declared concentration limit"
    )
    generated_at_utc = datetime.now(UTC).isoformat()
    build_spec = _PortfolioBuildSpec(
        generated_at_utc=generated_at_utc,
        initial_weights=tuple((name, float(weights[name])) for name in returns),
        annualization=annualization,
        max_sleeve_weight=float(max_sleeve_weight),
        provenance_json=_canonical_json(validated_provenance),
        return_bindings=bindings,
    )

    return PortfolioRiskResult(
        generated_at_utc=generated_at_utc,
        data_summary={
            "observations": len(returns),
            "start": returns.index[0].isoformat(),
            "end": returns.index[-1].isoformat(),
            "sleeves": list(returns.columns),
            "provenance": validated_provenance,
        },
        settings={
            "annualization": annualization,
            "initial_weights": {name: float(weights[name]) for name in returns},
            "allocation_rule": "initial buy-and-hold sleeve allocation; no rebalancing",
            "incremental_portfolio_rebalancing_cost": 0.0,
            "max_sleeve_weight": max_sleeve_weight,
        },
        portfolio_metrics=portfolio_metrics,
        sleeve_metrics=sleeve_metrics,
        dependence={
            "return_correlation": {
                row: {
                    column: _finite_float_or_none(correlation.loc[row, column])
                    for column in correlation
                }
                for row in correlation
            },
            "both_negative_ratio": float((returns < 0.0).all(axis=1).mean()),
            "annualized_covariance": {
                row: {
                    column: float(covariance[row_index, column_index])
                    for column_index, column in enumerate(returns.columns)
                }
                for row_index, row in enumerate(returns.columns)
            },
        },
        risk_contributions=risk_contributions,
        concentration=concentration,
        risk_status=risk_status,
        frame=output,
        _build_spec=build_spec,
    )


def _reload_bound_returns(result: PortfolioRiskResult) -> dict[str, pd.Series]:
    reloaded: dict[str, pd.Series] = {}
    for binding in result._build_spec.return_bindings:
        full_series = load_verified_return_csv(
            binding.path,
            expected_sha256=binding.sha256,
            timestamp_column=binding.timestamp_column,
            return_column=binding.return_column,
        )
        selected_index = pd.DatetimeIndex(pd.to_datetime(binding.selected_timestamps, utc=True))
        missing = selected_index.difference(full_series.index)
        if len(missing):
            raise ValueError(
                f"{binding.name} report evidence references timestamps absent from "
                "the verified source"
            )
        selected = full_series.loc[selected_index].copy()
        selected.attrs = dict(full_series.attrs)
        reloaded[binding.name] = selected
    return reloaded


def _validate_result_against_verified_sources(result: PortfolioRiskResult) -> None:
    spec = result._build_spec
    if result.generated_at_utc != spec.generated_at_utc:
        raise ValueError("portfolio result changed after construction")

    provenance = json.loads(spec.provenance_json)
    expected = build_buy_and_hold_sleeve_portfolio(
        _reload_bound_returns(result),
        initial_weights=dict(spec.initial_weights),
        provenance=provenance,
        annualization=spec.annualization,
        max_sleeve_weight=spec.max_sleeve_weight,
    )
    expected_payload = expected.to_dict()
    expected_payload["generated_at_utc"] = spec.generated_at_utc

    if result.to_dict() != expected_payload:
        raise ValueError("portfolio result does not match its verified source inputs")
    try:
        pd.testing.assert_frame_equal(
            result.frame,
            expected.frame,
            check_exact=True,
            check_freq=False,
        )
    except AssertionError as exc:
        raise ValueError(
            "portfolio result frame does not match its verified source inputs"
        ) from exc


def write_portfolio_risk_report(
    result: PortfolioRiskResult,
    output_dir: str | Path,
) -> dict[str, Path]:
    sleeves = result.data_summary.get("sleeves")
    if not isinstance(sleeves, list):
        raise ValueError("portfolio result must declare its sleeve names")
    validate_portfolio_provenance(
        result.data_summary.get("provenance"),
        expected_sleeves=sleeves,
    )
    _validate_result_against_verified_sources(result)

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / "portfolio_risk.json"
    markdown_path = output / "portfolio_risk.md"
    returns_path = output / "portfolio_returns.csv"

    json_path.write_text(
        json.dumps(
            result.to_dict(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    result.frame.rename_axis("timestamp").reset_index().to_csv(returns_path, index=False)

    lines = [
        "# Two-Sleeve Portfolio Risk Report",
        "",
        f"Generated at: `{result.generated_at_utc}`",
        "",
        f"Risk status: **{result.risk_status}**",
        "",
        "## Evidence boundary",
        "",
        "- The sleeves are development-market strategy returns, not untouched holdouts.",
        "- Initial weights are fixed before aggregation and are not optimized on these returns.",
        (
            "- Sleeve capital is buy-and-hold after initial allocation; "
            "no daily rebalancing is assumed."
        ),
        "- Sleeve returns are already net of their own recorded trading costs.",
        "- No incremental cross-sleeve rebalancing cost is modeled because no rebalancing occurs.",
        "- This is a portfolio-risk diagnostic, not evidence of new alpha.",
        "",
        "## Portfolio metrics",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ]
    lines.extend(
        f"| {name} | {value:.6f} |" if isinstance(value, float) else f"| {name} | {value} |"
        for name, value in result.portfolio_metrics.items()
    )
    lines.extend(["", "## Sleeve concentration", ""])
    lines.append(
        f"- Maximum allowed sleeve weight: "
        f"{result.concentration['maximum_allowed_sleeve_weight']:.2%}"
    )
    for name, value in result.concentration["maximum_observed_weights"].items():
        lines.append(f"- Maximum observed {name} weight: {value:.2%}")
    lines.append(f"- Breach observations: {result.concentration['breach_observations']}")
    lines.extend(["", "## Initial-weight variance contributions", ""])
    for name, value in result.risk_contributions.items():
        lines.append(f"- {name}: {value:.2%}")
    lines.extend(["", "## Return dependence", ""])
    for row, values in result.dependence["return_correlation"].items():
        for column, value in values.items():
            if row < column:
                if value is None:
                    lines.append(f"- {row} / {column} correlation: unavailable (zero variance)")
                else:
                    lines.append(f"- {row} / {column} correlation: {value:.6f}")
    worst = result.concentration["worst_portfolio_day"]
    lines.extend(
        [
            "",
            "## Worst portfolio day",
            "",
            f"- Timestamp: `{worst['timestamp']}`",
            f"- Portfolio return: {worst['portfolio_return']:.6f}",
        ]
    )
    for name, value in worst["sleeve_return_contributions"].items():
        lines.append(f"- {name} contribution: {value:.6f}")
    lines.append("")
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path, "returns": returns_path}
