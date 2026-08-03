from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from gpt_quant.okx import _canonical_csv_bytes, _canonical_json_bytes
from gpt_quant.okx_1h import (
    fetch_okx_one_hour_candles,
    replay_persisted_okx_one_hour_snapshot,
)

FAMILY_ID = "causal-own-price-return-sign-mixture-eprocess-shift-opportunity-1h-v1"
REJECT_VERDICT = (
    "reject_causal_own_price_return_sign_mixture_eprocess_shift_information_premise_1h_v1"
)
ACCEPT_VERDICT = (
    "accept_causal_own_price_return_sign_mixture_eprocess_shift_information_premise_"
    "1h_v1_for_separate_candidate_predeclaration"
)
TARGETS = ("XLM-USDT", "ICP-USDT")
SOURCE_START = pd.Timestamp("2023-04-01T00:00:00Z")
SOURCE_END = pd.Timestamp("2025-12-31T23:00:00Z")
EXPECTED_ROWS = 24_144
TRAIN_START = 2_160
TRAIN_END = 10_800
SEALED_OOS_START = 10_800
SEALED_OOS_END = 23_760
UNREAD_SUFFIX_START = 23_760
UNREAD_SUFFIX_END = 24_144
DECISION_STEP = 24
FEATURE_LAG = 25
RECENT_RETURNS = 168
BASELINE_RETURNS = 720
TREND_HOURS = 2_160
HORIZON_HOURS = 24
FEE_ONE_WAY = 0.0005
ROUND_TRIP_HURDLE = 2.0 * FEE_ONE_WAY
MIXTURE_LAMBDAS = np.array([0.10, 0.25, 0.50, 0.75], dtype=float)
MIN_RETAINED_FRACTION = 0.95
MIN_OPPORTUNITIES = 180
MIN_DISTINCT_FEATURES = 100
MIN_TERCILE_SIZE = 50
BOOTSTRAP_DRAWS = 5_000
BOOTSTRAP_BLOCK = 7
BOOTSTRAP_SEED = 2026080402
FOLD_COUNT = 4
MAX_POSITIVE_FOLD_CONCENTRATION = 0.60


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"


def _finite(value: float | np.floating[Any]) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("non-finite numeric result")
    return result


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _serializable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _serializable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serializable(item) for item in value]
    if isinstance(value, np.ndarray):
        return [_serializable(item) for item in value.tolist()]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        number = float(value)
        return None if not math.isfinite(number) else number
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def _validate_frame(frame: pd.DataFrame, instrument: str) -> None:
    expected_index = pd.date_range(SOURCE_START, SOURCE_END, freq="h")
    if len(frame) != EXPECTED_ROWS or not frame.index.equals(expected_index):
        raise ValueError(f"{instrument} source does not match the frozen hourly grid")
    if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise ValueError(f"{instrument} source chronology is invalid")
    required = ["open", "high", "low", "close"]
    values = frame[required].to_numpy(dtype=float)
    if not np.isfinite(values).all() or np.any(values <= 0.0):
        raise ValueError(f"{instrument} contains non-positive or non-finite OHLC")
    high_floor = frame[["open", "close"]].max(axis=1).to_numpy(dtype=float)
    low_ceiling = frame[["open", "close"]].min(axis=1).to_numpy(dtype=float)
    if np.any(frame["high"].to_numpy(dtype=float) < high_floor):
        raise ValueError(f"{instrument} contains invalid high values")
    if np.any(frame["low"].to_numpy(dtype=float) > low_ceiling):
        raise ValueError(f"{instrument} contains invalid low values")


def _fetch_source(
    *,
    instrument: str,
    output_dir: Path,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    first = fetch_okx_one_hour_candles(
        inst_id=instrument,
        start=SOURCE_START,
        end=SOURCE_END,
        pause_seconds=0.12,
        timeout=20.0,
        safety_pages=4,
    )
    frame = first.candles.copy()
    _validate_frame(frame, instrument)

    second = fetch_okx_one_hour_candles(
        inst_id=instrument,
        start=SOURCE_START,
        end=SOURCE_END,
        pause_seconds=0.12,
        timeout=20.0,
        safety_pages=4,
    )
    second_frame = second.candles.copy()
    _validate_frame(second_frame, instrument)

    csv_bytes = _canonical_csv_bytes(frame)
    second_csv_bytes = _canonical_csv_bytes(second_frame)
    if csv_bytes != second_csv_bytes or not frame.equals(second_frame):
        raise ValueError(f"{instrument} repeated acquisition changed the normalized panel")

    raw_bytes = _canonical_json_bytes(first.raw_pages)
    metadata_bytes = _canonical_json_bytes(first.metadata)
    source_dir = output_dir / "source" / instrument
    source_dir.mkdir(parents=True, exist_ok=True)
    stem = f"okx-{instrument}-1H"
    (source_dir / f"{stem}.csv").write_bytes(csv_bytes)
    (source_dir / f"{stem}.raw.json").write_bytes(raw_bytes)
    (source_dir / f"{stem}.metadata.json").write_bytes(metadata_bytes)

    replay = replay_persisted_okx_one_hour_snapshot(source_dir, inst_id=instrument)
    replay_csv_bytes = _canonical_csv_bytes(replay.candles)
    if replay_csv_bytes != csv_bytes or not replay.candles.equals(frame):
        raise ValueError(f"{instrument} exact-byte replay changed the normalized panel")

    training_prefix = frame.iloc[:TRAIN_END]
    prefix_bytes = _canonical_csv_bytes(training_prefix)
    pages = int(first.metadata.get("pages", len(first.raw_pages)))
    return frame, {
        "provider": "OKX",
        "market_type": "SPOT",
        "instrument": instrument,
        "bar": "1H",
        "requested_start": SOURCE_START.isoformat(),
        "requested_end": SOURCE_END.isoformat(),
        "rows": len(frame),
        "start": frame.index[0].isoformat(),
        "end": frame.index[-1].isoformat(),
        "normalized_csv_sha256": _sha256_bytes(csv_bytes),
        "raw_pages_sha256": _sha256_bytes(raw_bytes),
        "metadata_sha256": _sha256_bytes(metadata_bytes),
        "training_prefix_sha256": _sha256_bytes(prefix_bytes),
        "response_pages": pages,
        "completed_hour_grid": True,
        "gap_count": 0,
        "duplicate_count": 0,
        "exact_byte_replay_identical": True,
        "repeated_acquisition_identical": True,
        "repeated_normalization_identical": bool(
            _canonical_csv_bytes(replay.candles.copy()) == replay_csv_bytes
        ),
        "credentials_used": False,
        "private_endpoints_used": False,
        "synthetic_rows": 0,
        "interpolated_rows": 0,
        "resampled_rows": 0,
    }


def _logsumexp(values: np.ndarray) -> float:
    if values.ndim != 1 or len(values) == 0 or not np.isfinite(values).all():
        raise ValueError("log-sum-exp requires a finite non-empty vector")
    maximum = float(np.max(values))
    return _finite(maximum + math.log(float(np.exp(values - maximum).sum())))


def _mixture_growth(signs: np.ndarray) -> tuple[float, dict[str, Any]]:
    if signs.ndim != 1 or len(signs) == 0:
        raise ValueError("mixture growth requires a non-empty sign sequence")
    if not np.all(np.isin(signs, (-1.0, 1.0))):
        raise ValueError("mixture growth received a non-binary sign")
    factors = 1.0 + MIXTURE_LAMBDAS[:, None] * signs[None, :]
    if np.any(factors <= 0.0):
        raise ValueError("mixture wealth factor is not strictly positive")
    log_components = np.log(factors).sum(axis=1)
    log_mixture = _finite(_logsumexp(log_components) - math.log(len(MIXTURE_LAMBDAS)))
    growth = _finite(log_mixture / len(signs))

    direct_agreement = None
    if float(np.max(np.abs(log_components))) < 650.0:
        direct_components = np.prod(factors, axis=1)
        direct_mixture = _finite(float(np.mean(direct_components)))
        direct_agreement = bool(
            math.isclose(
                direct_mixture,
                math.exp(log_mixture),
                rel_tol=5e-12,
                abs_tol=1e-300,
            )
        )
    return growth, {
        "retained": len(signs),
        "log_components": [_finite(value) for value in log_components],
        "log_mixture": log_mixture,
        "positive_factors": True,
        "equal_weight_count": len(MIXTURE_LAMBDAS),
        "direct_agreement": direct_agreement,
    }


def _feature_for_anchor(
    *,
    log_returns: np.ndarray,
    anchor: int,
) -> tuple[dict[str, Any], bool]:
    latest_input = anchor - FEATURE_LAG
    recent_start = latest_input - RECENT_RETURNS + 1
    recent_end = latest_input
    baseline_end = recent_start - 1
    baseline_start = baseline_end - BASELINE_RETURNS + 1
    if baseline_start < 1:
        raise ValueError("feature history underflow")

    recent_raw = log_returns[recent_start : recent_end + 1]
    baseline_raw = log_returns[baseline_start : baseline_end + 1]
    if len(recent_raw) != RECENT_RETURNS or len(baseline_raw) != BASELINE_RETURNS:
        raise ValueError("feature window length mismatch")
    recent = recent_raw[recent_raw != 0.0]
    baseline = baseline_raw[baseline_raw != 0.0]
    recent_fraction = _finite(len(recent) / RECENT_RETURNS)
    baseline_fraction = _finite(len(baseline) / BASELINE_RETURNS)
    support_pass = bool(
        recent_fraction >= MIN_RETAINED_FRACTION
        and baseline_fraction >= MIN_RETAINED_FRACTION
    )
    result: dict[str, Any] = {
        "latest_input_index": latest_input,
        "recent_start_index": recent_start,
        "recent_end_index": recent_end,
        "baseline_start_index": baseline_start,
        "baseline_end_index": baseline_end,
        "recent_retained": len(recent),
        "baseline_retained": len(baseline),
        "recent_zero_returns": int(RECENT_RETURNS - len(recent)),
        "baseline_zero_returns": int(BASELINE_RETURNS - len(baseline)),
        "recent_retained_fraction": recent_fraction,
        "baseline_retained_fraction": baseline_fraction,
        "support_pass": support_pass,
    }
    if not support_pass:
        result.update(
            {
                "recent_growth": None,
                "baseline_growth": None,
                "feature": None,
                "recent_identity": None,
                "baseline_identity": None,
            }
        )
        return result, False

    recent_growth, recent_identity = _mixture_growth(np.sign(recent))
    baseline_growth, baseline_identity = _mixture_growth(np.sign(baseline))
    result.update(
        {
            "recent_growth": recent_growth,
            "baseline_growth": baseline_growth,
            "feature": _finite(recent_growth - baseline_growth),
            "recent_identity": recent_identity,
            "baseline_identity": baseline_identity,
        }
    )
    return result, True


def _build_training_records(frame: pd.DataFrame) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    opens = frame["open"].to_numpy(dtype=float)
    lows = frame["low"].to_numpy(dtype=float)
    closes = frame["close"].to_numpy(dtype=float)
    log_returns = np.full(len(frame), np.nan, dtype=float)
    log_returns[1:] = np.log(closes[1:] / closes[:-1])

    records: list[dict[str, Any]] = []
    support_failures = 0
    potential_anchors = 0
    e2160_positive_anchors = 0
    first_eligible_anchor = None
    last_eligible_anchor = None
    identity_direct_checks: list[bool] = []

    for anchor in range(TRAIN_START, TRAIN_END, DECISION_STEP):
        if anchor + HORIZON_HOURS + 1 >= TRAIN_END:
            continue
        latest_input = anchor - FEATURE_LAG
        oldest_trend = latest_input - TREND_HOURS
        if oldest_trend < 0:
            continue
        potential_anchors += 1
        if first_eligible_anchor is None:
            first_eligible_anchor = anchor
        last_eligible_anchor = anchor

        feature_record, support_pass = _feature_for_anchor(
            log_returns=log_returns,
            anchor=anchor,
        )
        if not support_pass:
            support_failures += 1

        e2160_margin = _finite(closes[latest_input] / closes[oldest_trend] - 1.0)
        if e2160_margin <= 0.0:
            continue
        e2160_positive_anchors += 1
        if not support_pass:
            continue

        net_return = _finite(
            opens[anchor + HORIZON_HOURS] / opens[anchor]
            - 1.0
            - ROUND_TRIP_HURDLE
        )
        adverse = _finite(
            float(np.min(lows[anchor : anchor + HORIZON_HOURS]))
            / opens[anchor]
            - 1.0
        )
        delayed_net_return = _finite(
            opens[anchor + HORIZON_HOURS + 1] / opens[anchor + 1]
            - 1.0
            - ROUND_TRIP_HURDLE
        )
        delayed_adverse = _finite(
            float(np.min(lows[anchor + 1 : anchor + HORIZON_HOURS + 1]))
            / opens[anchor + 1]
            - 1.0
        )
        for identity_key in ("recent_identity", "baseline_identity"):
            direct = feature_record[identity_key]["direct_agreement"]
            if direct is not None:
                identity_direct_checks.append(bool(direct))

        records.append(
            {
                "anchor": anchor,
                "timestamp": frame.index[anchor].isoformat(),
                "latest_input_index": latest_input,
                "latest_input_timestamp": frame.index[latest_input].isoformat(),
                "oldest_trend_index": oldest_trend,
                "e2160_margin": e2160_margin,
                "feature": feature_record["feature"],
                "recent_growth": feature_record["recent_growth"],
                "baseline_growth": feature_record["baseline_growth"],
                "recent_retained": feature_record["recent_retained"],
                "baseline_retained": feature_record["baseline_retained"],
                "recent_zero_returns": feature_record["recent_zero_returns"],
                "baseline_zero_returns": feature_record["baseline_zero_returns"],
                "recent_retained_fraction": feature_record["recent_retained_fraction"],
                "baseline_retained_fraction": feature_record["baseline_retained_fraction"],
                "net_return": net_return,
                "adverse_excursion": adverse,
                "delayed_net_return": delayed_net_return,
                "delayed_adverse_excursion": delayed_adverse,
            }
        )

    if not records:
        raise ValueError("no positive-E2160 training opportunities were constructed")
    if any(record["latest_input_index"] > record["anchor"] - FEATURE_LAG for record in records):
        raise ValueError("feature chronology violated the frozen lag")
    return records, {
        "potential_daily_anchors": potential_anchors,
        "first_eligible_anchor": first_eligible_anchor,
        "last_eligible_anchor": last_eligible_anchor,
        "e2160_positive_anchors": e2160_positive_anchors,
        "valid_opportunities": len(records),
        "support_failures": support_failures,
        "minimum_recent_retained_fraction": _finite(
            min(record["recent_retained_fraction"] for record in records)
        ),
        "minimum_baseline_retained_fraction": _finite(
            min(record["baseline_retained_fraction"] for record in records)
        ),
        "observed_direct_identity_checks": len(identity_direct_checks),
        "observed_direct_identity_all_pass": bool(identity_direct_checks)
        and all(identity_direct_checks),
        "latest_feature_input_offset_hours": FEATURE_LAG,
    }


def _spearman(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) != len(y) or len(x) < 3:
        raise ValueError("Spearman association requires aligned support")
    x_rank = pd.Series(x).rank(method="average").to_numpy(dtype=float)
    y_rank = pd.Series(y).rank(method="average").to_numpy(dtype=float)
    x_std = float(x_rank.std(ddof=0))
    y_std = float(y_rank.std(ddof=0))
    if x_std == 0.0 or y_std == 0.0:
        raise ValueError("Spearman association is undefined for a constant vector")
    return _finite(float(np.corrcoef(x_rank, y_rank)[0, 1]))


def _standardized_slope(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) != len(y) or len(x) < 3:
        raise ValueError("standardized slope requires aligned support")
    x_std = float(x.std(ddof=0))
    if x_std == 0.0:
        raise ValueError("standardized slope is undefined for a constant feature")
    z = (x - float(x.mean())) / x_std
    y_centered = y - float(y.mean())
    denominator = float(np.dot(z, z))
    if denominator <= 0.0:
        raise ValueError("standardized slope denominator is invalid")
    return _finite(float(np.dot(z, y_centered) / denominator))


def _outer_tercile_effect(
    x: np.ndarray,
    y: np.ndarray,
) -> tuple[float, int, int]:
    if len(x) != len(y) or len(x) < 6:
        raise ValueError("tercile effect requires aligned support")
    order = np.argsort(x, kind="mergesort")
    size = len(x) // 3
    if size == 0:
        raise ValueError("tercile support is empty")
    lower = y[order[:size]]
    upper = y[order[-size:]]
    return _finite(float(upper.mean() - lower.mean())), len(lower), len(upper)


def _metric_bundle(
    x: np.ndarray,
    returns: np.ndarray,
    adverse: np.ndarray,
) -> dict[str, Any]:
    return_effect, lower_size, upper_size = _outer_tercile_effect(x, returns)
    adverse_effect, adverse_lower_size, adverse_upper_size = _outer_tercile_effect(
        x,
        adverse,
    )
    if (lower_size, upper_size) != (adverse_lower_size, adverse_upper_size):
        raise ValueError("return and adverse tercile memberships disagree")
    return {
        "return_spearman": _spearman(x, returns),
        "return_standardized_slope": _standardized_slope(x, returns),
        "return_upper_minus_lower_tercile": return_effect,
        "adverse_spearman": _spearman(x, adverse),
        "adverse_standardized_slope": _standardized_slope(x, adverse),
        "adverse_upper_minus_lower_tercile": adverse_effect,
        "lower_tercile_size": lower_size,
        "upper_tercile_size": upper_size,
    }


def _moving_block_indices(
    *,
    sample_size: int,
    block_size: int,
    rng: np.random.Generator,
) -> np.ndarray:
    if block_size <= 0 or sample_size < block_size:
        raise ValueError("moving-block support is invalid")
    starts = np.arange(0, sample_size - block_size + 1, dtype=int)
    selected: list[int] = []
    while len(selected) < sample_size:
        start = int(rng.choice(starts))
        selected.extend(range(start, start + block_size))
    return np.asarray(selected[:sample_size], dtype=int)


def _bootstrap(
    x: np.ndarray,
    returns: np.ndarray,
    adverse: np.ndarray,
) -> dict[str, Any]:
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    names = (
        "return_spearman",
        "return_standardized_slope",
        "adverse_spearman",
        "adverse_standardized_slope",
    )
    draws: dict[str, list[float]] = {name: [] for name in names}
    attempts = 0
    max_attempts = BOOTSTRAP_DRAWS * 3
    while len(draws["return_spearman"]) < BOOTSTRAP_DRAWS and attempts < max_attempts:
        attempts += 1
        indices = _moving_block_indices(
            sample_size=len(x),
            block_size=BOOTSTRAP_BLOCK,
            rng=rng,
        )
        xb = x[indices]
        rb = returns[indices]
        ab = adverse[indices]
        try:
            values = {
                "return_spearman": _spearman(xb, rb),
                "return_standardized_slope": _standardized_slope(xb, rb),
                "adverse_spearman": _spearman(xb, ab),
                "adverse_standardized_slope": _standardized_slope(xb, ab),
            }
        except ValueError:
            continue
        for name in names:
            draws[name].append(values[name])
    if len(draws["return_spearman"]) != BOOTSTRAP_DRAWS:
        raise ValueError("unable to obtain the frozen number of valid bootstrap draws")

    intervals: dict[str, Any] = {}
    for name in names:
        array = np.asarray(draws[name], dtype=float)
        intervals[name] = {
            "lower_95": _finite(float(np.quantile(array, 0.025))),
            "upper_95": _finite(float(np.quantile(array, 0.975))),
        }
    return {
        "draws": BOOTSTRAP_DRAWS,
        "block_opportunities": BOOTSTRAP_BLOCK,
        "seed": BOOTSTRAP_SEED,
        "non_circular": True,
        "paired": True,
        "attempts": attempts,
        "intervals": intervals,
    }


def _fold_breadth(
    x: np.ndarray,
    returns: np.ndarray,
    adverse: np.ndarray,
) -> dict[str, Any]:
    indices = np.arange(len(x), dtype=int)
    folds: list[dict[str, Any]] = []
    for fold_number, fold_indices in enumerate(np.array_split(indices, FOLD_COUNT), start=1):
        if len(fold_indices) < 3:
            raise ValueError("fold support is too small")
        return_slope = _standardized_slope(x[fold_indices], returns[fold_indices])
        adverse_slope = _standardized_slope(x[fold_indices], adverse[fold_indices])
        folds.append(
            {
                "fold": fold_number,
                "observations": len(fold_indices),
                "return_slope": return_slope,
                "adverse_slope": adverse_slope,
            }
        )
    positive_return_slopes = [
        fold["return_slope"] for fold in folds if fold["return_slope"] > 0.0
    ]
    positive_adverse_slopes = [
        fold["adverse_slope"] for fold in folds if fold["adverse_slope"] > 0.0
    ]
    if positive_return_slopes:
        concentration = _finite(max(positive_return_slopes) / sum(positive_return_slopes))
    else:
        concentration = None
    return {
        "folds": folds,
        "positive_return_slope_folds": len(positive_return_slopes),
        "positive_adverse_slope_folds": len(positive_adverse_slopes),
        "largest_positive_return_fold_contribution": concentration,
    }


def _structural_identities(records: list[dict[str, Any]]) -> dict[str, Any]:
    all_positive = np.ones(20, dtype=float)
    balanced = np.tile(np.array([1.0, -1.0]), 10)
    all_positive_growth, positive_identity = _mixture_growth(all_positive)
    balanced_growth, balanced_identity = _mixture_growth(balanced)
    latest_input_ok = all(
        int(record["latest_input_index"]) <= int(record["anchor"]) - FEATURE_LAG
        for record in records
    )
    return {
        "all_wealth_factors_positive": True,
        "observed_log_direct_agreement": True,
        "equal_weight_mixture_identity": (
            positive_identity["equal_weight_count"] == len(MIXTURE_LAMBDAS)
            and balanced_identity["equal_weight_count"] == len(MIXTURE_LAMBDAS)
        ),
        "all_positive_exceeds_balanced": all_positive_growth > balanced_growth,
        "all_positive_growth": all_positive_growth,
        "balanced_growth": balanced_growth,
        "no_input_later_than_t_minus_25": latest_input_ok,
    }


def _compact_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keys = (
        "anchor",
        "timestamp",
        "latest_input_index",
        "e2160_margin",
        "feature",
        "recent_growth",
        "baseline_growth",
        "recent_retained",
        "baseline_retained",
        "recent_zero_returns",
        "baseline_zero_returns",
        "net_return",
        "adverse_excursion",
        "delayed_net_return",
        "delayed_adverse_excursion",
    )
    return [{key: record[key] for key in keys} for record in records]


def _analyze_target(
    *,
    instrument: str,
    frame: pd.DataFrame,
    source: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    full_records, construction = _build_training_records(frame)
    prefix_records, prefix_construction = _build_training_records(frame.iloc[:TRAIN_END].copy())
    compact_full = _compact_records(full_records)
    compact_prefix = _compact_records(prefix_records)
    prefix_identical = _canonical_json(compact_full) == _canonical_json(compact_prefix)
    construction_identical = _canonical_json(construction) == _canonical_json(prefix_construction)

    x = np.asarray([record["feature"] for record in full_records], dtype=float)
    returns = np.asarray([record["net_return"] for record in full_records], dtype=float)
    adverse = np.asarray(
        [record["adverse_excursion"] for record in full_records],
        dtype=float,
    )
    delayed_returns = np.asarray(
        [record["delayed_net_return"] for record in full_records],
        dtype=float,
    )
    delayed_adverse = np.asarray(
        [record["delayed_adverse_excursion"] for record in full_records],
        dtype=float,
    )
    if not all(
        np.isfinite(array).all()
        for array in (x, returns, adverse, delayed_returns, delayed_adverse)
    ):
        raise ValueError(f"{instrument} produced non-finite training values")

    point = _metric_bundle(x, returns, adverse)
    delayed = _metric_bundle(x, delayed_returns, delayed_adverse)
    bootstrap = _bootstrap(x, returns, adverse)
    breadth = _fold_breadth(x, returns, adverse)
    structural = _structural_identities(full_records)
    structural["observed_log_direct_agreement"] = bool(
        construction["observed_direct_identity_all_pass"]
    )

    distinct_features = int(len(np.unique(x)))
    iqr = _finite(float(np.quantile(x, 0.75) - np.quantile(x, 0.25)))
    lower_bounds = [
        bootstrap["intervals"][name]["lower_95"]
        for name in (
            "return_spearman",
            "return_standardized_slope",
            "adverse_spearman",
            "adverse_standardized_slope",
        )
    ]
    point_values = [
        point[name]
        for name in (
            "return_spearman",
            "return_standardized_slope",
            "return_upper_minus_lower_tercile",
            "adverse_spearman",
            "adverse_standardized_slope",
            "adverse_upper_minus_lower_tercile",
        )
    ]
    delayed_values = [
        delayed[name]
        for name in (
            "return_spearman",
            "return_standardized_slope",
            "return_upper_minus_lower_tercile",
            "adverse_spearman",
            "adverse_standardized_slope",
            "adverse_upper_minus_lower_tercile",
        )
    ]
    concentration = breadth["largest_positive_return_fold_contribution"]
    gates = {
        "source_integrity": all(
            (
                source["rows"] == EXPECTED_ROWS,
                source["completed_hour_grid"],
                source["gap_count"] == 0,
                source["duplicate_count"] == 0,
                source["exact_byte_replay_identical"],
                source["repeated_acquisition_identical"],
                source["repeated_normalization_identical"],
            )
        ),
        "minimum_opportunities": len(full_records) >= MIN_OPPORTUNITIES,
        "nonzero_return_support": construction["support_failures"] == 0,
        "feature_activity": distinct_features >= MIN_DISTINCT_FEATURES and iqr > 0.0,
        "tercile_support": (
            point["lower_tercile_size"] >= MIN_TERCILE_SIZE
            and point["upper_tercile_size"] >= MIN_TERCILE_SIZE
        ),
        "positive_point_information": all(value > 0.0 for value in point_values),
        "positive_dependence_lower_bounds": all(value > 0.0 for value in lower_bounds),
        "fold_breadth": (
            breadth["positive_return_slope_folds"] >= 3
            and breadth["positive_adverse_slope_folds"] >= 3
        ),
        "fold_concentration": (
            concentration is not None
            and concentration <= MAX_POSITIVE_FOLD_CONCENTRATION
        ),
        "one_hour_delay": all(value > 0.0 for value in delayed_values),
        "prefix_invariance": prefix_identical and construction_identical,
        "structural_identities": all(
            bool(value)
            for key, value in structural.items()
            if key
            in {
                "all_wealth_factors_positive",
                "observed_log_direct_agreement",
                "equal_weight_mixture_identity",
                "all_positive_exceeds_balanced",
                "no_input_later_than_t_minus_25",
            }
        ),
    }
    pass_all = all(gates.values())
    target = {
        "instrument": instrument,
        "source": source,
        "construction": construction,
        "feature_distribution": {
            "observations": len(x),
            "distinct_values": distinct_features,
            "minimum": _finite(float(np.min(x))),
            "maximum": _finite(float(np.max(x))),
            "mean": _finite(float(np.mean(x))),
            "standard_deviation": _finite(float(np.std(x, ddof=0))),
            "iqr": iqr,
        },
        "point_information": point,
        "dependence_uncertainty": bootstrap,
        "fold_breadth": breadth,
        "one_hour_delay": delayed,
        "prefix_invariance": {
            "records_identical": prefix_identical,
            "construction_identical": construction_identical,
            "full_training_records_sha256": _sha256_bytes(
                _canonical_json(compact_full).encode("utf-8")
            ),
            "prefix_training_records_sha256": _sha256_bytes(
                _canonical_json(compact_prefix).encode("utf-8")
            ),
        },
        "structural_identities": structural,
        "gates": gates,
        "pass_all_gates": pass_all,
        "strategy_metrics": {
            "train_return": None,
            "train_sharpe": None,
            "oos_return": None,
            "oos_sharpe": None,
            "full_return": None,
            "full_sharpe": None,
            "benchmark_comparison": None,
            "turnover": None,
            "fee_drag": None,
            "maximum_drawdown": None,
            "edge_per_turnover": None,
            "calendar_year_breadth": None,
        },
    }
    return target, compact_full


def _format_bp(value: float) -> str:
    return f"{10_000.0 * value:+.2f} bp"


def _report(evidence: dict[str, Any]) -> str:
    lines = [
        "# Return-sign mixture e-process shift — training-only evidence",
        "",
        "```text",
        f"family                  {evidence['family_id']}",
        f"canonical main          {evidence['canonical_main']}",
        f"exact evidence head     {evidence['exact_head']}",
        f"candidate/grid          {evidence['candidate_count']}/"
        f"{evidence['parameter_grid_count']}",
        "fixed targets           XLM-USDT and ICP-USDT independently",
        "modeled fee             exactly 5 bps one way in each 24H label",
        f"targets passing         {sum(t['pass_all_gates'] for t in evidence['targets'])}/2",
        "sealed OOS accessed     no",
        "canonical mutation     none",
        f"verdict                  {evidence['verdict']}",
        "```",
        "",
        "## Frozen information object",
        "",
        "The statistic compares per-observation log growth of an equal-weight positive-lambda",
        "sign-betting mixture over the latest 168 nonzero hourly returns with the immediately",
        "preceding 720-return baseline. Every input ends at `t-25`; only positive delayed",
        "E2160 opportunities are scored.",
        "",
        "## Data and training sample",
        "",
        "| Target | Rows | CSV SHA-256 | Opportunities | Distinct features | Feature IQR |",
        "|---|---:|---|---:|---:|---:|",
    ]
    for target in evidence["targets"]:
        source = target["source"]
        distribution = target["feature_distribution"]
        lines.append(
            f"| {target['instrument']} | {source['rows']} | "
            f"`{source['normalized_csv_sha256']}` | "
            f"{distribution['observations']} | {distribution['distinct_values']} | "
            f"{distribution['iqr']:.8f} |"
        )
    lines.extend(
        [
            "",
            "## Training information results",
            "",
            "| Target | Net rho | Net slope | Net tercile | Adverse rho | "
            "Adverse slope | Adverse tercile |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for target in evidence["targets"]:
        point = target["point_information"]
        lines.append(
            f"| {target['instrument']} | {point['return_spearman']:+.6f} | "
            f"{point['return_standardized_slope']:+.6f} | "
            f"{_format_bp(point['return_upper_minus_lower_tercile'])} | "
            f"{point['adverse_spearman']:+.6f} | "
            f"{point['adverse_standardized_slope']:+.6f} | "
            f"{_format_bp(point['adverse_upper_minus_lower_tercile'])} |"
        )
    lines.extend(
        [
            "",
            "## Dependence-aware uncertainty",
            "",
            "Five thousand paired, non-circular moving-block draws use seven chronological",
            f"opportunities per block and seed `{BOOTSTRAP_SEED}`.",
            "",
            "| Target | Net-rho 95% | Net-slope 95% | Adverse-rho 95% | "
            "Adverse-slope 95% |",
            "|---|---|---|---|---|",
        ]
    )
    for target in evidence["targets"]:
        intervals = target["dependence_uncertainty"]["intervals"]

        def interval(name: str) -> str:
            item = intervals[name]
            return f"[{item['lower_95']:+.6f}, {item['upper_95']:+.6f}]"

        lines.append(
            f"| {target['instrument']} | {interval('return_spearman')} | "
            f"{interval('return_standardized_slope')} | "
            f"{interval('adverse_spearman')} | "
            f"{interval('adverse_standardized_slope')} |"
        )
    lines.extend(
        [
            "",
            "## Fold breadth and one-hour delay",
            "",
            "| Target | Positive net folds | Positive adverse folds | "
            "Largest positive-net contribution | Delayed net effect | "
            "Delayed adverse effect |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for target in evidence["targets"]:
        breadth = target["fold_breadth"]
        delayed = target["one_hour_delay"]
        concentration = breadth["largest_positive_return_fold_contribution"]
        concentration_text = (
            "null" if concentration is None else f"{100.0 * concentration:.2f}%"
        )
        lines.append(
            f"| {target['instrument']} | "
            f"{breadth['positive_return_slope_folds']}/4 | "
            f"{breadth['positive_adverse_slope_folds']}/4 | "
            f"{concentration_text} | "
            f"{_format_bp(delayed['return_upper_minus_lower_tercile'])} | "
            f"{_format_bp(delayed['adverse_upper_minus_lower_tercile'])} |"
        )
    lines.extend(["", "## Gate vector", ""])
    for target in evidence["targets"]:
        lines.append(f"### {target['instrument']}")
        lines.append("")
        for name, passed in target["gates"].items():
            lines.append(f"- `{name}`: {'PASS' if passed else 'FAIL'}")
        lines.append("")
    lines.extend(
        [
            "## Strategy-performance accounting",
            "",
            "Candidate count is zero. Training/OOS/full strategy return and Sharpe, benchmark",
            "comparison, turnover, fee drag, drawdown, edge per turnover and calendar-year",
            "breadth are null rather than zero. Sealed OOS and the unread suffix were not used",
            "for features, labels, strategy paths or performance.",
            "",
            "## Verdict and remaining blocker",
            "",
            evidence["remaining_blocker"],
            "",
            "## Next strategy experiment",
            "",
            evidence["next_strategy_experiment"],
            "",
        ]
    )
    return "\n".join(lines)


def run(output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    exact_head = os.environ.get("GITHUB_SHA", "").strip()
    if len(exact_head) != 40 or any(
        character not in "0123456789abcdef" for character in exact_head
    ):
        raise ValueError("GITHUB_SHA must bind evidence to an exact lowercase commit")
    canonical_main = "5a0fcc97d1a882f8223656c51f5bb8055f534e38"

    targets: list[dict[str, Any]] = []
    records_by_target: dict[str, Any] = {}
    for instrument in TARGETS:
        frame, source = _fetch_source(instrument=instrument, output_dir=output_dir)
        target, records = _analyze_target(
            instrument=instrument,
            frame=frame,
            source=source,
        )
        targets.append(target)
        records_by_target[instrument] = records

    bilateral_pass = all(target["pass_all_gates"] for target in targets)
    verdict = ACCEPT_VERDICT if bilateral_pass else REJECT_VERDICT
    failing = {
        target["instrument"]: [
            name for name, passed in target["gates"].items() if not passed
        ]
        for target in targets
    }
    remaining_blocker = (
        "The fixed return-sign mixture does not yet establish bilateral, "
        "dependence-supported continuation and downside information."
        if not bilateral_pass
        else "No executable long/cash policy has yet been separately preregistered."
    )
    next_experiment = (
        "Close this information family on rejection and activate exactly one materially "
        "orthogonal own-history architecture from the existing research queue; do not tune "
        "lambdas, windows, sign, lag, targets or gates."
        if not bilateral_pass
        else "Preregister one executable candidate without accessing the sealed OOS in this run."
    )
    evidence = {
        "family_id": FAMILY_ID,
        "canonical_main": canonical_main,
        "exact_head": exact_head,
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "fixed_targets": list(TARGETS),
        "bar": "1H",
        "source_start": SOURCE_START.isoformat(),
        "source_end": SOURCE_END.isoformat(),
        "expected_rows_per_target": EXPECTED_ROWS,
        "training_index_interval": [TRAIN_START, TRAIN_END],
        "sealed_oos_index_interval": [SEALED_OOS_START, SEALED_OOS_END],
        "unread_suffix_index_interval": [UNREAD_SUFFIX_START, UNREAD_SUFFIX_END],
        "decision_step_hours": DECISION_STEP,
        "feature_lag_hours": FEATURE_LAG,
        "recent_returns": RECENT_RETURNS,
        "baseline_returns": BASELINE_RETURNS,
        "trend_hours": TREND_HOURS,
        "horizon_hours": HORIZON_HOURS,
        "canonical_fee_bps_one_way": 5.0,
        "round_trip_label_hurdle_bps": 10.0,
        "mixture_lambdas": MIXTURE_LAMBDAS.tolist(),
        "minimum_retained_fraction": MIN_RETAINED_FRACTION,
        "bootstrap_draws": BOOTSTRAP_DRAWS,
        "bootstrap_block_opportunities": BOOTSTRAP_BLOCK,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "sealed_oos_performance_accessed": False,
        "canonical_mutation": False,
        "paper_authority": False,
        "live_authority": False,
        "controls": {
            "credentials": False,
            "private_endpoints": False,
            "accounts": False,
            "orders": False,
            "leverage": False,
            "enabled_adapters": False,
            "synthetic_data": False,
            "non_1h_input": False,
            "cross_sectional_selection": False,
            "pairs_or_spreads": False,
            "shorting": False,
        },
        "targets": targets,
        "bilateral_information_pass": bilateral_pass,
        "failing_gates": failing,
        "verdict": verdict,
        "remaining_blocker": remaining_blocker,
        "next_strategy_experiment": next_experiment,
        "strategy_metrics": {
            "train_return": None,
            "train_sharpe": None,
            "oos_return": None,
            "oos_sharpe": None,
            "full_return": None,
            "full_sharpe": None,
            "benchmark_comparison": None,
            "turnover": None,
            "fee_drag": None,
            "maximum_drawdown": None,
            "fold_breadth": None,
            "calendar_year_breadth": None,
            "uncertainty": None,
        },
    }
    evidence = _serializable(evidence)
    records_by_target = _serializable(records_by_target)

    evidence_text = _canonical_json(evidence)
    records_text = _canonical_json(records_by_target)
    report_text = _report(evidence)
    evidence_sha = _sha256_bytes(evidence_text.encode("utf-8"))
    records_sha = _sha256_bytes(records_text.encode("utf-8"))
    report_sha = _sha256_bytes(report_text.encode("utf-8"))

    (output_dir / "evidence.json").write_text(evidence_text, encoding="utf-8")
    (output_dir / "evidence.sha256").write_text(evidence_sha + "\n", encoding="utf-8")
    (output_dir / "training-records.json").write_text(records_text, encoding="utf-8")
    (output_dir / "training-records.json.sha256").write_text(
        records_sha + "\n",
        encoding="utf-8",
    )
    (output_dir / "report.md").write_text(report_text, encoding="utf-8")
    (output_dir / "report.md.sha256").write_text(report_sha + "\n", encoding="utf-8")
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    evidence = run(args.output_dir)
    compact = {
        "exact_head": evidence["exact_head"],
        "verdict": evidence["verdict"],
        "bilateral_information_pass": evidence["bilateral_information_pass"],
        "failing_gates": evidence["failing_gates"],
        "targets": [
            {
                "instrument": target["instrument"],
                "opportunities": target["feature_distribution"]["observations"],
                "point_information": target["point_information"],
                "dependence_uncertainty": target["dependence_uncertainty"],
                "fold_breadth": target["fold_breadth"],
                "one_hour_delay": target["one_hour_delay"],
                "pass_all_gates": target["pass_all_gates"],
            }
            for target in evidence["targets"]
        ],
    }
    print("STRATEGY_COMPACT_JSON=" + json.dumps(compact, sort_keys=True))


if __name__ == "__main__":
    main()
