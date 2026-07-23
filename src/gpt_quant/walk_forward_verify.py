from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from numbers import Integral, Real
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .metrics import performance_metrics

_REQUIRED_RETURN_COLUMNS = {
    "timestamp",
    "asset_return",
    "target_position",
    "position",
    "turnover",
    "trading_cost",
    "gross_strategy_return",
    "exchange_fee_cost",
    "strategy_return",
    "fold",
}


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    return value


def _positive_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or int(value) <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return int(value)


def _finite_nonnegative(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{label} must be a finite non-negative number")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0.0:
        raise ValueError(f"{label} must be a finite non-negative number")
    return parsed


def _utc_timestamp(value: object, label: str) -> pd.Timestamp:
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be a valid timestamp") from exc
    if pd.isna(parsed):
        raise ValueError(f"{label} must be a valid timestamp")
    parsed = parsed.tz_localize("UTC") if parsed.tzinfo is None else parsed.tz_convert("UTC")
    return parsed


def _numeric_column(frame: pd.DataFrame, name: str) -> pd.Series:
    try:
        values = pd.to_numeric(frame[name], errors="raise").astype(float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"walk-forward returns column {name} must be numeric") from exc
    invalid = np.flatnonzero(~np.isfinite(values.to_numpy(copy=False)))
    if invalid.size:
        raise ValueError(f"walk-forward returns column {name} must contain finite values")
    return values


def _assert_series_close(
    label: str,
    actual: pd.Series,
    expected: pd.Series,
    *,
    tolerance: float,
) -> None:
    if not np.allclose(
        actual.to_numpy(dtype=float, copy=False),
        expected.to_numpy(dtype=float, copy=False),
        rtol=0.0,
        atol=tolerance,
    ):
        difference = np.abs(
            actual.to_numpy(dtype=float) - expected.to_numpy(dtype=float)
        )
        position = int(np.argmax(difference))
        raise ValueError(
            f"{label} does not match persisted return accounting at row {position}; "
            f"absolute error={difference[position]:.3g}"
        )


def _assert_metric_mapping(
    label: str,
    persisted: object,
    recomputed: Mapping[str, float | int],
    *,
    tolerance: float,
) -> None:
    persisted_mapping = _mapping(persisted, label)
    for key, expected in recomputed.items():
        if key not in persisted_mapping:
            raise ValueError(f"{label} is missing recomputable metric {key}")
        actual = persisted_mapping[key]
        if isinstance(expected, int):
            if (
                isinstance(actual, bool)
                or not isinstance(actual, Integral)
                or int(actual) != expected
            ):
                raise ValueError(f"{label}.{key} does not match persisted returns")
            continue
        if isinstance(actual, bool) or not isinstance(actual, Real):
            raise ValueError(f"{label}.{key} must be numeric")
        actual_float = float(actual)
        if not math.isfinite(actual_float) or not math.isclose(
            actual_float,
            float(expected),
            rel_tol=0.0,
            abs_tol=tolerance,
        ):
            raise ValueError(f"{label}.{key} does not match persisted returns")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_walk_forward_report(
    output_dir: str | Path,
    *,
    tolerance: float = 1e-12,
) -> dict[str, float | int | str]:
    """Recompute persisted walk-forward metrics and fail closed on report drift."""

    if not math.isfinite(tolerance) or tolerance <= 0.0:
        raise ValueError("tolerance must be finite and positive")

    output = Path(output_dir)
    report_path = output / "walk_forward.json"
    returns_path = output / "walk_forward_returns.csv"
    if not report_path.is_file() or not returns_path.is_file():
        raise ValueError("walk-forward report verification requires JSON and returns CSV files")

    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("walk-forward JSON report is unreadable") from exc
    payload_mapping = _mapping(payload, "walk-forward report")

    try:
        persisted = pd.read_csv(returns_path)
    except (OSError, UnicodeError, pd.errors.ParserError) as exc:
        raise ValueError("walk-forward returns CSV is unreadable") from exc
    missing_columns = sorted(_REQUIRED_RETURN_COLUMNS - set(persisted.columns))
    if missing_columns:
        raise ValueError(
            f"walk-forward returns CSV is missing required columns: {missing_columns}"
        )
    if persisted.empty:
        raise ValueError("walk-forward returns CSV cannot be empty")

    try:
        timestamps = pd.to_datetime(persisted["timestamp"], utc=True, errors="raise")
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "walk-forward returns timestamps must be valid UTC timestamps"
        ) from exc
    index = pd.DatetimeIndex(timestamps, name="timestamp")
    if index.has_duplicates or not index.is_monotonic_increasing:
        raise ValueError("walk-forward returns timestamps must be unique and increasing")

    numeric_names = sorted(_REQUIRED_RETURN_COLUMNS - {"timestamp"})
    numeric = {name: _numeric_column(persisted, name) for name in numeric_names}
    fold_values = numeric["fold"].to_numpy(copy=False)
    if (
        not np.equal(fold_values, np.floor(fold_values)).all()
        or (fold_values <= 0).any()
    ):
        raise ValueError("walk-forward fold identifiers must be positive integers")
    persisted["fold"] = fold_values.astype(int)
    for name, values in numeric.items():
        if name != "fold":
            persisted[name] = values
    persisted.index = index

    settings = _mapping(payload_mapping.get("settings"), "walk-forward report settings")
    base_config = _mapping(settings.get("base_config"), "walk-forward base_config")
    annualization = _positive_integer(base_config.get("annualization"), "annualization")
    fee_bps = _finite_nonnegative(
        base_config.get("transaction_cost_bps"),
        "transaction_cost_bps",
    )

    previous_position = persisted["position"].shift(1, fill_value=0.0)
    expected_turnover = (persisted["position"] - previous_position).abs()
    _assert_series_close(
        "turnover",
        persisted["turnover"],
        expected_turnover,
        tolerance=tolerance,
    )

    gross = persisted["position"] * persisted["asset_return"]
    fee = expected_turnover * fee_bps / 10_000.0
    net = gross - fee
    _assert_series_close(
        "gross_strategy_return",
        persisted["gross_strategy_return"],
        gross,
        tolerance=tolerance,
    )
    _assert_series_close(
        "exchange_fee_cost",
        persisted["exchange_fee_cost"],
        fee,
        tolerance=tolerance,
    )
    _assert_series_close(
        "trading_cost",
        persisted["trading_cost"],
        persisted["exchange_fee_cost"],
        tolerance=tolerance,
    )
    _assert_series_close(
        "strategy_return",
        persisted["strategy_return"],
        net,
        tolerance=tolerance,
    )

    aggregate = performance_metrics(persisted, annualization=annualization)
    _assert_metric_mapping(
        "aggregate_metrics",
        payload_mapping.get("aggregate_metrics"),
        aggregate,
        tolerance=tolerance,
    )

    folds = payload_mapping.get("folds")
    if not isinstance(folds, list) or not folds:
        raise ValueError("walk-forward report folds must be a non-empty list")
    expected_fold_ids: list[int] = []
    for position, fold_payload in enumerate(folds, start=1):
        fold_mapping = _mapping(fold_payload, f"fold {position}")
        fold_id = _positive_integer(
            fold_mapping.get("fold"),
            f"fold {position} identifier",
        )
        if fold_id in expected_fold_ids:
            raise ValueError(f"walk-forward report contains duplicate fold {fold_id}")
        expected_fold_ids.append(fold_id)
        fold_frame = persisted.loc[persisted["fold"] == fold_id]
        if fold_frame.empty:
            raise ValueError(f"walk-forward returns CSV is missing fold {fold_id}")
        test_start = _utc_timestamp(fold_mapping.get("test_start"), "test_start")
        test_end = _utc_timestamp(fold_mapping.get("test_end"), "test_end")
        if fold_frame.index[0] != test_start:
            raise ValueError(f"fold {fold_id} test_start does not match persisted returns")
        if fold_frame.index[-1] != test_end:
            raise ValueError(f"fold {fold_id} test_end does not match persisted returns")
        if len(fold_frame) > 1:
            expected_position = fold_frame["target_position"].shift(1).iloc[1:]
            _assert_series_close(
                f"fold {fold_id} position",
                fold_frame["position"].iloc[1:],
                expected_position,
                tolerance=tolerance,
            )
        fold_metrics = performance_metrics(fold_frame, annualization=annualization)
        _assert_metric_mapping(
            f"fold {fold_id} test_metrics",
            fold_mapping.get("test_metrics"),
            fold_metrics,
            tolerance=tolerance,
        )

    actual_fold_ids = sorted(int(value) for value in persisted["fold"].unique())
    if actual_fold_ids != sorted(expected_fold_ids):
        raise ValueError("walk-forward report fold identifiers do not match persisted returns")

    data_summary = _mapping(payload_mapping.get("data_summary"), "data_summary")
    evaluation_start = _utc_timestamp(
        data_summary.get("evaluation_start"),
        "evaluation_start",
    )
    evaluation_end = _utc_timestamp(
        data_summary.get("evaluation_end"),
        "evaluation_end",
    )
    if index[0] != evaluation_start:
        raise ValueError("evaluation_start does not match persisted returns")
    if index[-1] != evaluation_end:
        raise ValueError("evaluation_end does not match persisted returns")

    return {
        "status": "passed",
        "report_json_sha256": _sha256(report_path),
        "returns_csv_sha256": _sha256(returns_path),
        "observations": len(persisted),
        "folds": len(folds),
        "annualization": annualization,
        "transaction_cost_bps": fee_bps,
        "metric_tolerance": tolerance,
    }
