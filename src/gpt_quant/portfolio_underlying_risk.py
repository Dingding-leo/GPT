from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Mapping
from contextlib import suppress
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

_COLUMNS = {
    "timestamp",
    "position",
    "turnover",
    "gross_strategy_return",
    "trading_cost",
    "strategy_return",
}
_HEX = frozenset("0123456789abcdef")
_ONE_DAY = pd.Timedelta(days=1)
_REPORT = "portfolio_underlying_risk.json"


@dataclass(frozen=True, slots=True)
class UnderlyingSleeveRiskResult:
    payload: dict[str, Any]
    frame: pd.DataFrame
    _sources: dict[str, tuple[str, str]] = field(repr=False, compare=False)
    _weights: dict[str, float] = field(repr=False, compare=False)
    _annualization: int = field(repr=False, compare=False)
    _tolerance: float = field(repr=False, compare=False)

    @property
    def generated_at_utc(self) -> str:
        return str(self.payload["generated_at_utc"])

    @property
    def sleeve_metrics(self) -> dict[str, dict[str, float | int | str]]:
        return self.payload["sleeve_metrics"]

    @property
    def portfolio_metrics(self) -> dict[str, float | int | str]:
        return self.payload["portfolio_metrics"]

    @property
    def cost_attribution(self) -> dict[str, Any]:
        return self.payload["cost_attribution"]

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(self.payload)


def _sha256(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a SHA-256 hexadecimal string")
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(character not in _HEX for character in normalized):
        raise ValueError(f"{label} must be a 64-character SHA-256 hexadecimal string")
    return normalized


def _nonnegative(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{label} must be a non-negative finite real number")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0.0:
        raise ValueError(f"{label} must be a non-negative finite real number")
    return parsed


def _utc_index(values: pd.Series) -> pd.DatetimeIndex:
    timestamps: list[pd.Timestamp] = []
    for value in values:
        timestamp = pd.Timestamp(value)
        offset = timestamp.utcoffset() if timestamp.tzinfo is not None else None
        if pd.isna(timestamp) or offset is None:
            raise ValueError("underlying path timestamps require explicit timezone information")
        if offset.total_seconds() != 0.0:
            raise ValueError("underlying path timestamps require an explicit UTC offset")
        timestamps.append(timestamp.tz_convert("UTC"))
    index = pd.DatetimeIndex(timestamps)
    if index.has_duplicates or not index.is_monotonic_increasing:
        raise ValueError("underlying path timestamps must be unique and increasing")
    if not bool((index == index.normalize()).all()):
        raise ValueError("underlying path timestamps must be aligned to midnight UTC")
    if len(index) > 1 and not bool(((index[1:] - index[:-1]) == _ONE_DAY).all()):
        raise ValueError("underlying path timestamps must have exact daily cadence")
    return index


def _load_path(
    path: str | Path,
    expected_hash: str,
    tolerance: float,
) -> pd.DataFrame:
    source = Path(path)
    payload = source.read_bytes()
    actual = hashlib.sha256(payload).hexdigest()
    if actual != _sha256(expected_hash, "expected source hash"):
        raise ValueError("underlying path hash mismatch")
    raw = pd.read_csv(BytesIO(payload))
    missing = _COLUMNS - set(raw)
    if missing:
        raise ValueError(f"underlying path is missing required columns: {sorted(missing)}")

    frame = pd.DataFrame(index=_utc_index(raw["timestamp"]))
    for column in sorted(_COLUMNS - {"timestamp"}):
        values = pd.to_numeric(raw[column], errors="raise").to_numpy(dtype=float)
        if not np.isfinite(values).all():
            raise ValueError(f"{column} must contain finite numeric values")
        frame[column] = values
    if (frame[["turnover", "trading_cost"]] < 0.0).any().any():
        raise ValueError("turnover and trading_cost must be non-negative")
    if (frame[["gross_strategy_return", "strategy_return"]] <= -1.0).any().any():
        raise ValueError("gross and net returns must remain greater than -100%")

    expected_turnover = frame["position"].diff().abs()
    expected_turnover.iloc[0] = abs(float(frame["position"].iloc[0]))
    if not np.allclose(frame["turnover"], expected_turnover, rtol=0.0, atol=tolerance):
        raise ValueError("turnover must equal absolute underlying position changes")
    expected_fee = frame["turnover"] * 0.0005
    if not np.allclose(frame["trading_cost"], expected_fee, rtol=0.0, atol=tolerance):
        raise ValueError("trading_cost must equal turnover times the declared 5 bps fee")
    expected_net = frame["gross_strategy_return"] - frame["trading_cost"]
    if not np.allclose(frame["strategy_return"], expected_net, rtol=0.0, atol=tolerance):
        raise ValueError("net strategy return must equal gross return minus exchange fee")
    frame.attrs.update(source_path=str(source.resolve()), source_sha256=actual)
    return frame


def _weights(names: tuple[str, ...], supplied: Mapping[str, float]) -> pd.Series:
    if set(supplied) != set(names):
        raise ValueError("initial_weights keys must exactly match underlying sleeve names")
    weights = pd.Series({name: float(supplied[name]) for name in names})
    if not np.isfinite(weights).all() or (weights <= 0.0).any():
        raise ValueError("initial weights must be strictly positive finite values")
    if not math.isclose(float(weights.sum()), 1.0, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("initial weights must sum to one")
    return weights


def _total_return(values: pd.Series) -> float:
    return float((1.0 + values).prod() - 1.0)


def build_underlying_sleeve_risk(
    sleeve_paths: Mapping[str, str | Path],
    *,
    expected_sha256: Mapping[str, str],
    initial_weights: Mapping[str, float],
    provenance: Mapping[str, Any],
    annualization: int = 365,
    exchange_fee_bps: float = 5.0,
    adjustment_threshold: float = 1e-12,
    accounting_tolerance: float = 1e-12,
    generated_at_utc: str | None = None,
) -> UnderlyingSleeveRiskResult:
    """Expose verified underlying position-path risk without claiming orders or fills."""

    names = tuple(sorted(sleeve_paths))
    if len(names) < 2 or set(expected_sha256) != set(names):
        raise ValueError("underlying risk requires matching evidence for at least two sleeves")
    if isinstance(annualization, bool) or not isinstance(annualization, int) or annualization < 2:
        raise ValueError("annualization must be an integer of at least 2")
    if not math.isclose(float(exchange_fee_bps), 5.0, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("underlying live-readiness risk requires the declared 5 bps fee baseline")
    threshold = _nonnegative(adjustment_threshold, "adjustment_threshold")
    tolerance = _nonnegative(accounting_tolerance, "accounting_tolerance")
    validated_provenance = deepcopy(dict(provenance))
    recorded_hashes = validated_provenance.get("return_file_sha256")
    if recorded_hashes != dict(expected_sha256):
        raise ValueError("provenance hashes must match underlying path hashes")
    weights = _weights(names, initial_weights)
    paths = {
        name: _load_path(sleeve_paths[name], expected_sha256[name], tolerance) for name in names
    }
    index = paths[names[0]].index
    if any(not paths[name].index.equals(index) for name in names[1:]):
        raise ValueError("underlying sleeve path indexes must match exactly")

    position = pd.DataFrame({name: paths[name]["position"] for name in names})
    turnover = pd.DataFrame({name: paths[name]["turnover"] for name in names})
    gross = pd.DataFrame({name: paths[name]["gross_strategy_return"] for name in names})
    fee = pd.DataFrame({name: paths[name]["trading_cost"] for name in names})
    net = pd.DataFrame({name: paths[name]["strategy_return"] for name in names})

    sleeve_values = (1.0 + net).cumprod().mul(weights, axis=1)
    portfolio_nav = sleeve_values.sum(axis=1)
    end_weight = sleeve_values.div(portfolio_nav, axis=0)
    start_weight = end_weight.shift(1)
    start_weight.iloc[0] = weights
    weighted_gross = start_weight * gross
    weighted_fee = start_weight * fee
    weighted_net = start_weight * net
    portfolio_gross = weighted_gross.sum(axis=1)
    portfolio_fee = weighted_fee.sum(axis=1)
    portfolio_net = weighted_net.sum(axis=1)
    if not np.allclose(
        portfolio_net,
        portfolio_gross - portfolio_fee,
        rtol=0.0,
        atol=tolerance,
    ):
        raise RuntimeError("portfolio gross, fee, and net contributions do not reconcile")

    exposure = start_weight * position.abs()
    weighted_turnover = start_weight * turnover
    portfolio_exposure = exposure.sum(axis=1)
    portfolio_turnover = weighted_turnover.sum(axis=1)
    current_exposure = float((end_weight.iloc[-1] * position.iloc[-1].abs()).sum())

    sleeve_metrics: dict[str, dict[str, float | int | str]] = {}
    for name in names:
        sleeve_metrics[name] = {
            "observations": len(index),
            "evaluation_start": index[0].isoformat(),
            "evaluation_end": index[-1].isoformat(),
            "average_absolute_exposure": float(position[name].abs().mean()),
            "current_absolute_exposure": float(abs(position[name].iloc[-1])),
            "maximum_absolute_exposure": float(position[name].abs().max()),
            "total_absolute_turnover": float(turnover[name].sum()),
            "annualized_underlying_turnover": float(turnover[name].mean() * annualization),
            "position_adjustment_count": int((turnover[name] > threshold).sum()),
            "annualized_position_adjustment_count": float(
                (turnover[name] > threshold).sum() * annualization / len(index)
            ),
            "exchange_fee_sum": float(fee[name].sum()),
            "gross_total_return": _total_return(gross[name]),
            "net_total_return": _total_return(net[name]),
            "compounded_exchange_fee_drag": _total_return(gross[name]) - _total_return(net[name]),
            "source_sha256": paths[name].attrs["source_sha256"],
        }

    portfolio_metrics: dict[str, float | int | str] = {
        "observations": len(index),
        "evaluation_start": index[0].isoformat(),
        "evaluation_end": index[-1].isoformat(),
        "average_start_of_bar_absolute_market_exposure": float(portfolio_exposure.mean()),
        "current_absolute_market_exposure": current_exposure,
        "maximum_start_of_bar_absolute_market_exposure": float(portfolio_exposure.max()),
        "total_weighted_underlying_turnover": float(portfolio_turnover.sum()),
        "annualized_weighted_underlying_turnover": float(portfolio_turnover.mean() * annualization),
        "underlying_adjustment_observation_count": int((turnover.gt(threshold).any(axis=1)).sum()),
        "portfolio_exchange_fee_sum": float(portfolio_fee.sum()),
        "gross_total_return": _total_return(portfolio_gross),
        "net_total_return": _total_return(portfolio_net),
        "compounded_exchange_fee_drag": _total_return(portfolio_gross)
        - _total_return(portfolio_net),
    }

    frame = pd.DataFrame(index=index)
    for name in names:
        frame[f"{name}_position"] = position[name]
        frame[f"{name}_turnover"] = turnover[name]
        frame[f"{name}_start_weight"] = start_weight[name]
        frame[f"{name}_absolute_exposure_contribution"] = exposure[name]
        frame[f"{name}_weighted_turnover"] = weighted_turnover[name]
        frame[f"{name}_weighted_exchange_fee"] = weighted_fee[name]
    frame["portfolio_absolute_market_exposure"] = portfolio_exposure
    frame["portfolio_weighted_underlying_turnover"] = portfolio_turnover
    frame["portfolio_exchange_fee"] = portfolio_fee
    frame["portfolio_gross_return"] = portfolio_gross
    frame["portfolio_net_return"] = portfolio_net

    timestamp = generated_at_utc or datetime.now(UTC).isoformat()
    payload = {
        "schema": "portfolio_underlying_path_risk_v1",
        "generated_at_utc": timestamp,
        "report_only": True,
        "deployment_eligible": False,
        "data_summary": {
            "sleeves": list(names),
            "provenance": validated_provenance,
        },
        "settings": {
            "annualization": annualization,
            "initial_weights": {name: float(weights[name]) for name in names},
            "position_adjustment_threshold": threshold,
            "position_interpretation": "research position; not an exchange order or fill",
            "portfolio_exposure_method": "start-of-bar sleeve weight times absolute position",
            "portfolio_turnover_method": "start-of-bar sleeve weight times absolute turnover",
        },
        "sleeve_metrics": sleeve_metrics,
        "portfolio_metrics": portfolio_metrics,
        "cost_attribution": {
            "exchange_fee": {
                "status": "modeled",
                "one_way_bps": 5.0,
                "method": "absolute underlying position turnover times 5 bps",
            },
            "all_in_fixed_path_sensitivity_bps": [7.5, 10.0, 15.0],
            "all_in_sensitivity_location": "per-sleeve walk-forward reports",
            "spread": {"status": "not_modeled"},
            "slippage": {"status": "not_modeled"},
            "market_impact": {"status": "not_modeled"},
            "latency": {"status": "not_modeled"},
        },
    }
    sources = {
        name: (paths[name].attrs["source_path"], paths[name].attrs["source_sha256"])
        for name in names
    }
    return UnderlyingSleeveRiskResult(
        payload=payload,
        frame=frame,
        _sources=sources,
        _weights={name: float(weights[name]) for name in names},
        _annualization=annualization,
        _tolerance=tolerance,
    )


def write_underlying_sleeve_risk_report(
    result: UnderlyingSleeveRiskResult,
    output_dir: str | Path,
) -> Path:
    if not isinstance(result, UnderlyingSleeveRiskResult):
        raise TypeError("result must be an UnderlyingSleeveRiskResult")
    expected = build_underlying_sleeve_risk(
        {name: source[0] for name, source in result._sources.items()},
        expected_sha256={name: source[1] for name, source in result._sources.items()},
        initial_weights=result._weights,
        provenance=result.payload["data_summary"]["provenance"],
        annualization=result._annualization,
        adjustment_threshold=float(result.payload["settings"]["position_adjustment_threshold"]),
        accounting_tolerance=result._tolerance,
        generated_at_utc=result.generated_at_utc,
    )
    if result.to_dict() != expected.to_dict():
        raise ValueError("underlying risk result does not match verified source inputs")
    pd.testing.assert_frame_equal(
        result.frame,
        expected.frame,
        check_exact=True,
        check_freq=False,
    )

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
