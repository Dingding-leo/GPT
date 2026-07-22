#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from gpt_quant.metrics import performance_metrics

_METRIC_COLUMNS = ("strategy_return", "turnover", "position", "trading_cost")
_REQUIRED_RETURN_COLUMNS = ("timestamp", "nav", *_METRIC_COLUMNS)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Recompute aggregate walk-forward metrics and the equity curve from a "
            "persisted returns CSV, then compare them with walk_forward.json."
        )
    )
    parser.add_argument("--report-json", required=True)
    parser.add_argument("--returns-csv", required=True)
    return parser.parse_args()


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a JSON object")
    return value


def _reject_duplicate_object_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"report JSON contains duplicate object key {key!r}")
        result[key] = value
    return result


def _reject_nonstandard_json_constant(value: str) -> None:
    raise ValueError(f"report JSON contains non-standard numeric constant {value!r}")


def _json_integer(value: object, name: str, *, minimum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ValueError(f"{name} must be an integer of at least {minimum}")
    return value


def _utc_timestamp(value: object, name: str) -> pd.Timestamp:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a valid timestamp") from exc
    if timestamp.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return timestamp.tz_convert("UTC")


def _explicit_utc_timestamp_series(values: pd.Series) -> pd.Series:
    parsed: list[pd.Timestamp] = []
    for value in values:
        try:
            timestamp = pd.Timestamp(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("returns CSV contains an invalid timestamp") from exc
        if pd.isna(timestamp):
            raise ValueError("returns CSV contains an invalid timestamp")
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("returns CSV timestamps must contain explicit timezone information")
        parsed.append(timestamp)
    return pd.Series(
        pd.to_datetime(parsed, utc=True),
        index=values.index,
        name=values.name,
    )


def _declared_provenance(data_summary: Mapping[str, Any]) -> Mapping[str, Any] | None:
    provenance_value = data_summary.get("provenance")
    if provenance_value is None:
        return None
    return _mapping(provenance_value, "data_summary.provenance")


def _validate_declared_timestamp_cadence(
    timestamps: pd.Series,
    data_summary: Mapping[str, Any],
) -> None:
    provenance = _declared_provenance(data_summary)
    if provenance is None or provenance.get("bar") != "1Dutc":
        return
    intervals = timestamps.diff().iloc[1:]
    if not intervals.eq(pd.Timedelta(days=1)).all():
        raise ValueError("returns CSV timestamps must have exact 1Dutc cadence")


def _validate_declared_data_coverage(
    timestamps: pd.Series,
    data_summary: Mapping[str, Any],
    settings: Mapping[str, Any],
) -> None:
    provenance = _declared_provenance(data_summary)
    if provenance is None or provenance.get("bar") != "1Dutc":
        return

    selection_bars = _json_integer(
        settings.get("selection_bars"),
        "settings.selection_bars",
        minimum=1,
    )
    observations = _json_integer(
        data_summary.get("observations"),
        "data_summary.observations",
        minimum=1,
    )
    unscored_tail_bars = _json_integer(
        data_summary.get("unscored_tail_bars"),
        "data_summary.unscored_tail_bars",
        minimum=0,
    )
    source_start = _utc_timestamp(data_summary.get("start"), "data_summary.start")
    source_end = _utc_timestamp(data_summary.get("end"), "data_summary.end")

    expected_observations = selection_bars + len(timestamps) + unscored_tail_bars
    if observations != expected_observations:
        raise ValueError(
            "data_summary.observations does not match selection, evaluation, and tail bars"
        )

    step = pd.Timedelta(days=1)
    expected_source_start = timestamps.iloc[0] - selection_bars * step
    expected_source_end = timestamps.iloc[-1] + unscored_tail_bars * step
    if source_start != expected_source_start or source_end != expected_source_end:
        raise ValueError("data_summary source boundaries do not match declared 1Dutc coverage")


def verify_walk_forward_metrics(
    report_json: str | Path,
    returns_csv: str | Path,
) -> dict[str, float | int]:
    report_path = Path(report_json)
    returns_path = Path(returns_csv)
    report = _mapping(
        json.loads(
            report_path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_object_keys,
            parse_constant=_reject_nonstandard_json_constant,
        ),
        "report",
    )
    settings = _mapping(report.get("settings"), "settings")
    base_config = _mapping(settings.get("base_config"), "settings.base_config")
    annualization = base_config.get("annualization")
    if not isinstance(annualization, int) or isinstance(annualization, bool) or annualization < 2:
        raise ValueError("settings.base_config.annualization must be an integer of at least 2")

    expected_metrics = _mapping(report.get("aggregate_metrics"), "aggregate_metrics")
    data_summary = _mapping(report.get("data_summary"), "data_summary")
    frame = pd.read_csv(returns_path)
    missing = sorted(set(_REQUIRED_RETURN_COLUMNS) - set(frame.columns))
    if missing:
        raise ValueError(f"returns CSV is missing required columns: {missing}")
    if frame.empty:
        raise ValueError("returns CSV cannot be empty")

    timestamps = _explicit_utc_timestamp_series(frame["timestamp"])
    if timestamps.duplicated().any():
        raise ValueError("returns CSV timestamps must be unique")
    if not timestamps.is_monotonic_increasing:
        raise ValueError("returns CSV timestamps must be strictly increasing")
    _validate_declared_timestamp_cadence(timestamps, data_summary)

    expected_start = _utc_timestamp(data_summary.get("evaluation_start"), "evaluation_start")
    expected_end = _utc_timestamp(data_summary.get("evaluation_end"), "evaluation_end")
    if timestamps.iloc[0] != expected_start or timestamps.iloc[-1] != expected_end:
        raise ValueError("returns CSV boundaries do not match report evaluation boundaries")
    _validate_declared_data_coverage(timestamps, data_summary, settings)

    numeric = frame.copy()
    for column in ("nav", *_METRIC_COLUMNS):
        try:
            numeric[column] = pd.to_numeric(numeric[column], errors="raise").astype(float)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"returns CSV column {column!r} must be numeric") from exc
        if not np.isfinite(numeric[column].to_numpy()).all():
            raise ValueError(f"returns CSV column {column!r} must contain only finite values")

    recomputed_nav = (1.0 + numeric["strategy_return"]).cumprod().to_numpy()
    persisted_nav = numeric["nav"].to_numpy()
    if not np.allclose(recomputed_nav, persisted_nav, rtol=1e-12, atol=1e-12):
        raise ValueError("persisted nav does not match compounded strategy_return")

    metric_frame = numeric[list(_METRIC_COLUMNS)]
    actual_metrics = performance_metrics(metric_frame, annualization=annualization)
    if set(expected_metrics) != set(actual_metrics):
        missing_metrics = sorted(set(actual_metrics) - set(expected_metrics))
        unexpected_metrics = sorted(set(expected_metrics) - set(actual_metrics))
        raise ValueError(
            "aggregate metric keys do not match recomputed metrics "
            f"(missing={missing_metrics}, unexpected={unexpected_metrics})"
        )

    for name, actual in actual_metrics.items():
        expected = expected_metrics[name]
        if name == "observations":
            if not isinstance(expected, int) or isinstance(expected, bool) or expected != actual:
                raise ValueError(
                    f"aggregate_metrics.{name} mismatch: expected {expected!r}, actual {actual!r}"
                )
            continue
        if not isinstance(expected, (int, float)) or isinstance(expected, bool):
            raise ValueError(f"aggregate_metrics.{name} must be a JSON number")
        expected_float = float(expected)
        actual_float = float(actual)
        if not math.isfinite(expected_float) or not math.isfinite(actual_float):
            raise ValueError(f"aggregate_metrics.{name} must be finite")
        if not math.isclose(expected_float, actual_float, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError(
                f"aggregate_metrics.{name} mismatch: "
                f"expected {expected_float:.17g}, actual {actual_float:.17g}"
            )
    return actual_metrics


def main() -> int:
    args = parse_args()
    try:
        metrics = verify_walk_forward_metrics(args.report_json, args.returns_csv)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"verification_error={exc}", file=sys.stderr)
        return 1
    print(f"report_json={Path(args.report_json)}")
    print(f"returns_csv={Path(args.returns_csv)}")
    print(f"observations={metrics['observations']}")
    print("aggregate_metrics=verified")
    print("equity_curve=verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
