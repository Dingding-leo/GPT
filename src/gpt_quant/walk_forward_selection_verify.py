from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pandas as pd

from .config import StrategyConfig
from .walk_forward import run_walk_forward_research

_METRIC_TOLERANCE = 1e-9
_HEX_DIGITS = frozenset("0123456789abcdef")


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    return value


def _json_list(value: object, label: str) -> list[object]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} must be a non-empty JSON array")
    return value


def _positive_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _finite_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{label} must be a finite number")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"{label} must be a finite number")
    return parsed


def _sha256_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or set(value) - _HEX_DIGITS:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _utc_timestamp(value: object, label: str) -> pd.Timestamp:
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be a valid timestamp with an explicit UTC offset") from exc
    if pd.isna(parsed) or parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include an explicit UTC offset")
    if parsed.utcoffset().total_seconds() != 0.0:
        raise ValueError(f"{label} must use UTC")
    return parsed.tz_convert("UTC")


def _metric_mapping_matches(
    actual: object,
    expected: Mapping[str, float | int],
    *,
    label: str,
) -> None:
    actual_mapping = _mapping(actual, label)
    if set(actual_mapping) != set(expected):
        raise ValueError(f"{label} keys do not match full 5 bps reselection")
    for key, expected_value in expected.items():
        actual_value = actual_mapping[key]
        if isinstance(expected_value, int):
            if (
                isinstance(actual_value, bool)
                or not isinstance(actual_value, int)
                or actual_value != expected_value
            ):
                raise ValueError(f"{label}.{key} does not match full 5 bps reselection")
            continue
        if not math.isclose(
            _finite_number(actual_value, f"{label}.{key}"),
            float(expected_value),
            rel_tol=0.0,
            abs_tol=_METRIC_TOLERANCE,
        ):
            raise ValueError(f"{label}.{key} does not match full 5 bps reselection")


def _load_json(path: Path, label: str) -> tuple[Mapping[str, object], bytes]:
    if not path.is_file():
        raise ValueError(f"{label} is missing")
    payload = path.read_bytes()
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is unreadable") from exc
    return _mapping(decoded, label), payload


def _load_source_close(
    output: Path,
    report: Mapping[str, object],
) -> tuple[pd.Series, Path, bytes]:
    data_summary = _mapping(report.get("data_summary"), "walk-forward data_summary")
    provenance = _mapping(data_summary.get("provenance"), "walk-forward provenance")
    if provenance.get("provider") != "OKX":
        raise ValueError("full selection verification requires OKX provenance")
    instrument_id = provenance.get("instrument_id")
    bar = provenance.get("bar")
    if not isinstance(instrument_id, str) or not instrument_id:
        raise ValueError("instrument_id must be a non-empty string")
    if not isinstance(bar, str) or not bar:
        raise ValueError("bar must be a non-empty string")
    snapshot_path = output / "snapshot" / f"okx-{instrument_id}-{bar}.csv"
    if not snapshot_path.is_file():
        raise ValueError("normalized OKX snapshot is missing")
    snapshot_bytes = snapshot_path.read_bytes()
    expected_sha256 = _sha256_digest(
        provenance.get("normalized_csv_sha256"),
        "normalized_csv_sha256",
    )
    if hashlib.sha256(snapshot_bytes).hexdigest() != expected_sha256:
        raise ValueError("normalized OKX snapshot hash does not match report provenance")
    try:
        snapshot = pd.read_csv(snapshot_path, float_precision="round_trip")
    except (OSError, UnicodeError, pd.errors.ParserError) as exc:
        raise ValueError("normalized OKX snapshot is unreadable") from exc
    missing = sorted({"timestamp", "close", "confirm"} - set(snapshot.columns))
    if missing:
        raise ValueError(f"normalized OKX snapshot is missing required columns: {missing}")
    if snapshot.empty:
        raise ValueError("normalized OKX snapshot cannot be empty")
    timestamps = pd.DatetimeIndex(
        [
            _utc_timestamp(value, f"snapshot timestamp row {row}")
            for row, value in enumerate(snapshot["timestamp"])
        ],
        name="timestamp",
    )
    if timestamps.has_duplicates or not timestamps.is_monotonic_increasing:
        raise ValueError("normalized OKX snapshot timestamps must be unique and increasing")
    close = pd.to_numeric(snapshot["close"], errors="raise").astype(float)
    if not np.isfinite(close.to_numpy(copy=False)).all() or (close <= 0.0).any():
        raise ValueError("normalized OKX snapshot close must contain finite positive values")
    confirm = pd.to_numeric(snapshot["confirm"], errors="raise")
    if not confirm.eq(1).all():
        raise ValueError("normalized OKX snapshot must contain completed candles only")
    source_close = pd.Series(close.to_numpy(copy=False), index=timestamps, name="close")
    return source_close, snapshot_path, snapshot_bytes


def verify_walk_forward_selection(output_dir: str | Path) -> dict[str, int | str | float]:
    """Rerun every 5 bps fold selection from immutable closes and effective config."""

    output = Path(output_dir)
    report_path = output / "walk_forward.json"
    config_path = output / "effective_config.json"
    report, report_bytes = _load_json(report_path, "walk-forward report")
    effective_config, config_bytes = _load_json(config_path, "effective configuration")
    source_close, snapshot_path, snapshot_bytes = _load_source_close(output, report)

    settings = _mapping(report.get("settings"), "walk-forward settings")
    strategy_payload = _mapping(effective_config.get("strategy"), "effective strategy")
    try:
        base_config = StrategyConfig(**dict(strategy_payload))
    except (TypeError, ValueError) as exc:
        raise ValueError("effective strategy is invalid") from exc
    if base_config.to_dict() != dict(_mapping(settings.get("base_config"), "base_config")):
        raise ValueError("effective strategy does not match walk-forward settings")
    if not math.isclose(base_config.transaction_cost_bps, 5.0, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("full selection verification requires the canonical 5 bps baseline")

    search = _mapping(effective_config.get("search"), "effective search")
    momentum_lookbacks = _json_list(search.get("momentum_lookbacks"), "momentum_lookbacks")
    reversal_lookbacks = _json_list(search.get("reversal_lookbacks"), "reversal_lookbacks")
    trend_weights = _json_list(search.get("trend_weights"), "trend_weights")
    selection_bars = search.get("selection_bars")
    test_bars = search.get("test_bars")
    if selection_bars != settings.get("selection_bars") or test_bars != settings.get("test_bars"):
        raise ValueError("effective search windows do not match walk-forward settings")
    robustness = _mapping(effective_config.get("robustness"), "effective robustness")
    cost_multipliers = _json_list(robustness.get("cost_multipliers"), "cost_multipliers")
    if cost_multipliers != settings.get("cost_multipliers"):
        raise ValueError("effective cost sensitivities do not match walk-forward settings")

    recomputed = run_walk_forward_research(
        source_close,
        base_config=base_config,
        momentum_lookbacks=momentum_lookbacks,
        reversal_lookbacks=reversal_lookbacks,
        trend_weights=trend_weights,
        selection_bars=selection_bars,
        test_bars=test_bars,
        cost_multipliers=cost_multipliers,
    )
    candidate_count = _positive_integer(settings.get("candidate_count"), "candidate_count")
    if candidate_count != int(recomputed.settings["candidate_count"]):
        raise ValueError("candidate_count does not match full 5 bps reselection")

    actual_folds = report.get("folds")
    if not isinstance(actual_folds, list) or not actual_folds:
        raise ValueError("walk-forward report folds must be a non-empty list")
    if len(actual_folds) != len(recomputed.folds):
        raise ValueError("walk-forward fold count does not match full 5 bps reselection")

    candidate_evaluations = 0
    for ordinal, (actual_value, expected) in enumerate(
        zip(actual_folds, recomputed.folds, strict=True),
        start=1,
    ):
        actual = _mapping(actual_value, f"fold {ordinal}")
        fold_id = _positive_integer(actual.get("fold"), f"fold {ordinal} identifier")
        if fold_id != int(expected["fold"]):
            raise ValueError(f"fold {ordinal} identifier does not match full 5 bps reselection")
        for boundary in ("selection_start", "selection_end", "test_start", "test_end"):
            if _utc_timestamp(actual.get(boundary), f"fold {fold_id} {boundary}") != _utc_timestamp(
                expected[boundary], f"recomputed fold {fold_id} {boundary}"
            ):
                raise ValueError(f"fold {fold_id} {boundary} does not match full 5 bps reselection")
        tested = _positive_integer(
            actual.get("candidates_tested"),
            f"fold {fold_id} candidates_tested",
        )
        if tested != int(expected["candidates_tested"]):
            raise ValueError(
                f"fold {fold_id} candidates_tested does not match full 5 bps reselection"
            )
        candidate_evaluations += tested
        selected_parameters = _mapping(
            actual.get("selected_parameters"),
            f"fold {fold_id} selected_parameters",
        )
        if dict(selected_parameters) != dict(expected["selected_parameters"]):
            raise ValueError(
                f"fold {fold_id} selected_parameters do not match full 5 bps reselection"
            )
        if not math.isclose(
            _finite_number(actual.get("selection_score"), f"fold {fold_id} selection_score"),
            float(expected["selection_score"]),
            rel_tol=0.0,
            abs_tol=_METRIC_TOLERANCE,
        ):
            raise ValueError(
                f"fold {fold_id} selection_score does not match full 5 bps reselection"
            )
        actual_gap = actual.get("runner_up_score_gap")
        expected_gap = expected["runner_up_score_gap"]
        if expected_gap is None:
            if actual_gap is not None:
                raise ValueError(
                    f"fold {fold_id} runner_up_score_gap does not match full 5 bps reselection"
                )
        elif not math.isclose(
            _finite_number(actual_gap, f"fold {fold_id} runner_up_score_gap"),
            float(expected_gap),
            rel_tol=0.0,
            abs_tol=_METRIC_TOLERANCE,
        ):
            raise ValueError(
                f"fold {fold_id} runner_up_score_gap does not match full 5 bps reselection"
            )
        _metric_mapping_matches(
            actual.get("selection_metrics"),
            expected["selection_metrics"],
            label=f"fold {fold_id} selection_metrics",
        )

    if report_bytes != report_path.read_bytes():
        raise ValueError("walk-forward report changed during selection verification")
    if config_bytes != config_path.read_bytes():
        raise ValueError("effective configuration changed during selection verification")
    if snapshot_bytes != snapshot_path.read_bytes():
        raise ValueError("normalized OKX snapshot changed during selection verification")
    return {
        "selection_folds_verified": len(recomputed.folds),
        "selection_candidates_per_fold": candidate_count,
        "selection_candidate_evaluations_verified": candidate_evaluations,
        "selection_metric_tolerance": _METRIC_TOLERANCE,
        "selection_source": (
            "immutable_normalized_okx_close_and_effective_config_full_5bps_reselection"
        ),
        "effective_config_sha256": hashlib.sha256(config_bytes).hexdigest(),
    }
