from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pandas as pd

from .walk_forward_verify import verify_walk_forward_report as _verify_report_metrics

_ACCOUNTING_TOLERANCE = 1e-12
_METRIC_TOLERANCE = 1e-9
_BASELINE_FEE_BPS = 5.0


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    return value


def _explicit_utc_timestamp(value: object, label: str) -> pd.Timestamp:
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be a valid timestamp with an explicit UTC offset") from exc
    if pd.isna(parsed) or parsed.tzinfo is None:
        raise ValueError(f"{label} must include an explicit UTC offset")
    offset = parsed.utcoffset()
    if offset is None or offset.total_seconds() != 0.0:
        raise ValueError(f"{label} must include an explicit UTC offset")
    return parsed.tz_convert("UTC")


def _numeric(frame: pd.DataFrame, name: str) -> pd.Series:
    try:
        values = pd.to_numeric(frame[name], errors="raise").astype(float)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"walk-forward returns column {name} must be numeric") from exc
    if not np.isfinite(values.to_numpy(copy=False)).all():
        raise ValueError(f"walk-forward returns column {name} must contain finite values")
    return values


def _assert_accounting(label: str, actual: pd.Series, expected: pd.Series) -> None:
    actual_values = actual.to_numpy(dtype=float, copy=False)
    expected_values = expected.to_numpy(dtype=float, copy=False)
    if np.allclose(
        actual_values,
        expected_values,
        rtol=0.0,
        atol=_ACCOUNTING_TOLERANCE,
    ):
        return
    difference = np.abs(actual_values - expected_values)
    row = int(np.argmax(difference))
    raise ValueError(
        f"{label} does not match persisted return accounting at row {row}; "
        f"absolute error={difference[row]:.3g}"
    )


def _validate_explicit_timestamps(payload: Mapping[str, object], persisted: pd.DataFrame) -> None:
    data_summary = _mapping(payload.get("data_summary"), "data_summary")
    _explicit_utc_timestamp(data_summary.get("evaluation_start"), "evaluation_start")
    _explicit_utc_timestamp(data_summary.get("evaluation_end"), "evaluation_end")

    folds = payload.get("folds")
    if not isinstance(folds, list) or not folds:
        raise ValueError("walk-forward report folds must be a non-empty list")
    for ordinal, fold in enumerate(folds, start=1):
        fold_mapping = _mapping(fold, f"fold {ordinal}")
        _explicit_utc_timestamp(fold_mapping.get("test_start"), f"fold {ordinal} test_start")
        _explicit_utc_timestamp(fold_mapping.get("test_end"), f"fold {ordinal} test_end")

    for row, value in enumerate(persisted["timestamp"]):
        _explicit_utc_timestamp(value, f"walk-forward returns timestamp row {row}")


def _validate_accounting(payload: Mapping[str, object], persisted: pd.DataFrame) -> None:
    settings = _mapping(payload.get("settings"), "walk-forward report settings")
    base_config = _mapping(settings.get("base_config"), "walk-forward base_config")
    fee_value = base_config.get("transaction_cost_bps")
    if isinstance(fee_value, bool) or not isinstance(fee_value, int | float):
        raise ValueError("transaction_cost_bps must be numeric")
    fee_bps = float(fee_value)
    if not math.isfinite(fee_bps) or not math.isclose(
        fee_bps,
        _BASELINE_FEE_BPS,
        rel_tol=0.0,
        abs_tol=_ACCOUNTING_TOLERANCE,
    ):
        raise ValueError("walk-forward verification requires the canonical 5 bps baseline")

    position = _numeric(persisted, "position")
    asset_return = _numeric(persisted, "asset_return")
    turnover = _numeric(persisted, "turnover")
    trading_cost = _numeric(persisted, "trading_cost")
    gross_return = _numeric(persisted, "gross_strategy_return")
    strategy_return = _numeric(persisted, "strategy_return")

    previous_position = position.shift(1, fill_value=0.0)
    expected_turnover = (position - previous_position).abs()
    expected_gross = position * asset_return
    expected_fee = expected_turnover * fee_bps / 10_000.0
    expected_net = expected_gross - expected_fee

    _assert_accounting("turnover", turnover, expected_turnover)
    _assert_accounting("gross_strategy_return", gross_return, expected_gross)
    _assert_accounting("exchange fee", trading_cost, expected_fee)
    _assert_accounting("strategy_return", strategy_return, expected_net)


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def verify_walk_forward_report(output_dir: str | Path) -> dict[str, float | int | str]:
    """Fail closed on persisted 5 bps accounting, timestamp, metric, and hash drift."""

    output = Path(output_dir)
    report_path = output / "walk_forward.json"
    returns_path = output / "walk_forward_returns.csv"
    report_bytes = report_path.read_bytes()
    returns_bytes = returns_path.read_bytes()
    try:
        payload = json.loads(report_bytes.decode("utf-8"))
        persisted = pd.read_csv(returns_path)
    except (UnicodeError, json.JSONDecodeError, pd.errors.ParserError) as exc:
        raise ValueError("persisted walk-forward evidence is unreadable") from exc
    payload_mapping = _mapping(payload, "walk-forward report")

    _validate_explicit_timestamps(payload_mapping, persisted)
    _validate_accounting(payload_mapping, persisted)
    verification = _verify_report_metrics(output, tolerance=_METRIC_TOLERANCE)

    if report_bytes != report_path.read_bytes() or returns_bytes != returns_path.read_bytes():
        raise ValueError("persisted walk-forward evidence changed during verification")
    if verification["report_json_sha256"] != _sha256_bytes(report_bytes):
        raise ValueError("walk-forward report hash does not match verified bytes")
    if verification["returns_csv_sha256"] != _sha256_bytes(returns_bytes):
        raise ValueError("walk-forward returns hash does not match verified bytes")

    verification["accounting_tolerance"] = _ACCOUNTING_TOLERANCE
    verification["metric_tolerance"] = _METRIC_TOLERANCE
    return verification
