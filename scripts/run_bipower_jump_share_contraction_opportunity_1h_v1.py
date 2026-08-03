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

from gpt_quant.okx_1h import fetch_okx_one_hour_candles

FAMILY_ID = "causal-own-price-bipower-jump-share-contraction-opportunity-1h-v1"
TARGETS = ("NEAR-USDT", "APT-USDT")
START = pd.Timestamp("2023-04-01T00:00:00Z")
END = pd.Timestamp("2025-12-31T23:00:00Z")
EXPECTED_ROWS = 24_144
TRAIN_START = 2_208
TRAIN_END = 10_800
SEALED_OOS_START = 10_800
SEALED_OOS_END = 23_760
UNREAD_SUFFIX_START = 23_760
E2160_HOURS = 2_160
DECISION_STEP = 24
LABEL_HORIZON = 24
RECENT_RETURNS = 168
BASELINE_RETURNS = 720
FEE_ONE_WAY = 0.0005
BOOTSTRAP_DRAWS = 5_000
BOOTSTRAP_BLOCK = 7
SEEDS = {"NEAR-USDT": 2026080311, "APT-USDT": 2026080312}
NEXT_EXPERIMENT = "causal-own-price-multiscale-variance-ratio-curvature-opportunity-1h-v1"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def _float(value: float | np.floating[Any]) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("non-finite statistic")
    return result


def _spearman(x: np.ndarray, y: np.ndarray) -> float:
    x_rank = pd.Series(x).rank(method="average").to_numpy(dtype=float)
    y_rank = pd.Series(y).rank(method="average").to_numpy(dtype=float)
    if x_rank.std(ddof=0) == 0 or y_rank.std(ddof=0) == 0:
        return 0.0
    return _float(np.corrcoef(x_rank, y_rank)[0, 1])


def _standardized_slope(x: np.ndarray, y: np.ndarray) -> float:
    scale = x.std(ddof=0)
    if scale == 0:
        return 0.0
    standardized = (x - x.mean()) / scale
    return _float(np.mean(standardized * (y - y.mean())))


def _tercile_effect(x: np.ndarray, y: np.ndarray) -> dict[str, Any]:
    lower_cut = _float(np.quantile(x, 1.0 / 3.0))
    upper_cut = _float(np.quantile(x, 2.0 / 3.0))
    lower = x <= lower_cut
    upper = x >= upper_cut
    return {
        "lower_cut": lower_cut,
        "upper_cut": upper_cut,
        "lower_count": int(lower.sum()),
        "upper_count": int(upper.sum()),
        "lower_mean": _float(y[lower].mean()),
        "upper_mean": _float(y[upper].mean()),
        "upper_minus_lower": _float(y[upper].mean() - y[lower].mean()),
    }


def _statistics(x: np.ndarray, net: np.ndarray, adverse: np.ndarray) -> dict[str, Any]:
    return {
        "net_return": {
            "spearman": _spearman(x, net),
            "standardized_ols_slope": _standardized_slope(x, net),
            "terciles": _tercile_effect(x, net),
        },
        "adverse_excursion": {
            "spearman": _spearman(x, adverse),
            "standardized_ols_slope": _standardized_slope(x, adverse),
            "terciles": _tercile_effect(x, adverse),
        },
    }


def _moving_block_indices(
    rng: np.random.Generator,
    observations: int,
    block: int,
) -> np.ndarray:
    if observations < block:
        raise ValueError("moving-block bootstrap requires at least one full block")
    block_count = math.ceil(observations / block)
    starts = rng.integers(0, observations - block + 1, size=block_count)
    offsets = np.arange(block)
    return (starts[:, None] + offsets[None, :]).reshape(-1)[:observations]


def _bootstrap(
    x: np.ndarray,
    net: np.ndarray,
    adverse: np.ndarray,
    *,
    seed: int,
) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    values = {
        "net_spearman": np.empty(BOOTSTRAP_DRAWS),
        "net_slope": np.empty(BOOTSTRAP_DRAWS),
        "adverse_spearman": np.empty(BOOTSTRAP_DRAWS),
        "adverse_slope": np.empty(BOOTSTRAP_DRAWS),
    }
    for draw in range(BOOTSTRAP_DRAWS):
        indices = _moving_block_indices(rng, len(x), BOOTSTRAP_BLOCK)
        bx = x[indices]
        bnet = net[indices]
        badverse = adverse[indices]
        values["net_spearman"][draw] = _spearman(bx, bnet)
        values["net_slope"][draw] = _standardized_slope(bx, bnet)
        values["adverse_spearman"][draw] = _spearman(bx, badverse)
        values["adverse_slope"][draw] = _standardized_slope(bx, badverse)
    intervals: dict[str, dict[str, float]] = {}
    for name, sample in values.items():
        lower, upper = np.quantile(sample, [0.025, 0.975])
        intervals[name] = {
            "lower_95": _float(lower),
            "upper_95": _float(upper),
        }
    return {
        "draws": BOOTSTRAP_DRAWS,
        "block_opportunities": BOOTSTRAP_BLOCK,
        "seed": seed,
        "intervals": intervals,
    }


def _jump_share_from_components(rv: float, bv: float) -> float:
    if not math.isfinite(rv) or not math.isfinite(bv) or rv <= 0 or bv < 0:
        raise ValueError("invalid realized- or bipower-variation component")
    tolerance = 1e-12 * max(abs(rv), abs(bv), 1e-18)
    numerator = 0.0 if abs(rv - bv) <= tolerance else max(rv - bv, 0.0)
    share = numerator / rv
    if share < -1e-15 or share > 1.0 + 1e-15:
        raise ValueError("jump share outside [0, 1]")
    return _float(min(max(share, 0.0), 1.0))


def _jump_components(returns: np.ndarray) -> dict[str, float]:
    values = np.asarray(returns, dtype=float)
    if values.ndim != 1 or len(values) < 2:
        raise ValueError("jump-share window requires at least two returns")
    if not np.isfinite(values).all():
        raise ValueError("jump-share window contains non-finite returns")
    observations = len(values)
    rv = _float(np.sum(values * values))
    if rv <= 0:
        raise ValueError("jump-share window has non-positive realized variation")
    adjacent_products = np.abs(values[1:]) * np.abs(values[:-1])
    bv = _float((math.pi / 2.0) * observations / (observations - 1) * adjacent_products.sum())
    return {
        "rv": rv,
        "bv": bv,
        "jump_share": _jump_share_from_components(rv, bv),
    }


def _feature_at(close_values: np.ndarray, signal_index: int) -> dict[str, Any]:
    closes = np.asarray(close_values, dtype=float)
    if closes.ndim != 1 or not np.isfinite(closes).all() or not (closes > 0).all():
        raise ValueError("feature builder requires finite positive closes")
    log_returns = np.empty(len(closes), dtype=float)
    log_returns[0] = np.nan
    log_returns[1:] = np.diff(np.log(closes))

    recent_start = signal_index - RECENT_RETURNS + 1
    recent_end = signal_index + 1
    baseline_end = recent_start
    baseline_start = baseline_end - BASELINE_RETURNS
    if baseline_start < 1 or recent_end > len(log_returns):
        raise ValueError("insufficient causal history for frozen jump-share windows")

    baseline_returns = log_returns[baseline_start:baseline_end]
    recent_returns = log_returns[recent_start:recent_end]
    if len(baseline_returns) != BASELINE_RETURNS or len(recent_returns) != RECENT_RETURNS:
        raise ValueError("jump-share window length mismatch")
    if baseline_end != recent_start:
        raise ValueError("baseline and recent return windows are not exactly adjacent")

    baseline = _jump_components(baseline_returns)
    recent = _jump_components(recent_returns)
    return {
        "feature": _float(baseline["jump_share"] - recent["jump_share"]),
        "baseline": baseline,
        "recent": recent,
        "window_indices": {
            "baseline_return_start": baseline_start,
            "baseline_return_end_exclusive": baseline_end,
            "recent_return_start": recent_start,
            "recent_return_end_exclusive": recent_end,
            "signal_close_index": signal_index,
        },
    }


def _build_records(frame: pd.DataFrame) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    training = frame.iloc[:TRAIN_END].copy()
    open_values = training["open"].to_numpy(dtype=float)
    close_values = training["close"].to_numpy(dtype=float)
    records: list[dict[str, Any]] = []
    counts = {
        "scheduled_training_anchors": 0,
        "anchors_with_complete_base_and_delay_labels": 0,
        "positive_e2160_anchors": 0,
        "invalid_variation_windows": 0,
        "valid_opportunities": 0,
    }

    for anchor in range(TRAIN_START, TRAIN_END, DECISION_STEP):
        counts["scheduled_training_anchors"] += 1
        if anchor + LABEL_HORIZON + 1 >= TRAIN_END:
            continue
        counts["anchors_with_complete_base_and_delay_labels"] += 1
        signal_index = anchor - 25
        if close_values[signal_index] <= close_values[signal_index - E2160_HOURS]:
            continue
        counts["positive_e2160_anchors"] += 1
        try:
            feature = _feature_at(close_values, signal_index)
        except ValueError as exc:
            if "non-positive realized variation" not in str(exc):
                raise
            counts["invalid_variation_windows"] += 1
            continue

        base_path = open_values[anchor : anchor + LABEL_HORIZON + 1] / open_values[anchor] - 1.0
        delayed_path = (
            open_values[anchor + 1 : anchor + LABEL_HORIZON + 2]
            / open_values[anchor + 1]
            - 1.0
        )
        records.append(
            {
                "anchor": anchor,
                "signal_index": signal_index,
                "feature": feature["feature"],
                "baseline": feature["baseline"],
                "recent": feature["recent"],
                "window_indices": feature["window_indices"],
                "net_return": _float(
                    open_values[anchor + LABEL_HORIZON] / open_values[anchor]
                    - 1.0
                    - 2.0 * FEE_ONE_WAY
                ),
                "adverse_excursion": _float(base_path.min()),
                "delayed_net_return": _float(
                    open_values[anchor + LABEL_HORIZON + 1] / open_values[anchor + 1]
                    - 1.0
                    - 2.0 * FEE_ONE_WAY
                ),
                "delayed_adverse_excursion": _float(delayed_path.min()),
            }
        )

    counts["valid_opportunities"] = len(records)
    return records, counts


def _summary(values: np.ndarray) -> dict[str, float]:
    sample = np.asarray(values, dtype=float)
    if len(sample) == 0 or not np.isfinite(sample).all():
        raise ValueError("summary requires a non-empty finite sample")
    q = np.quantile(sample, [0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0])
    return {
        "minimum": _float(q[0]),
        "q10": _float(q[1]),
        "q25": _float(q[2]),
        "median": _float(q[3]),
        "q75": _float(q[4]),
        "q90": _float(q[5]),
        "maximum": _float(q[6]),
        "mean": _float(sample.mean()),
        "standard_deviation": _float(sample.std(ddof=0)),
    }


def _fold_breadth(records: list[dict[str, Any]]) -> dict[str, Any]:
    folds = np.array_split(np.arange(len(records)), 4)
    results: list[dict[str, Any]] = []
    for fold_number, indices in enumerate(folds, start=1):
        subset = [records[int(index)] for index in indices]
        if not subset:
            raise ValueError("fixed fold contains no opportunities")
        x = np.array([record["feature"] for record in subset], dtype=float)
        net = np.array([record["net_return"] for record in subset], dtype=float)
        adverse = np.array([record["adverse_excursion"] for record in subset], dtype=float)
        results.append(
            {
                "fold": fold_number,
                "anchor_start": int(subset[0]["anchor"]),
                "anchor_end_exclusive": int(subset[-1]["anchor"] + DECISION_STEP),
                "opportunities": len(subset),
                "net_slope": _standardized_slope(x, net),
                "adverse_slope": _standardized_slope(x, adverse),
            }
        )
    positive_net = [result["net_slope"] for result in results if result["net_slope"] > 0]
    positive_total = sum(positive_net)
    concentration = max(positive_net) / positive_total if positive_total > 0 else 1.0
    return {
        "fold_definition": "four fixed contiguous eligible-opportunity blocks",
        "folds": results,
        "positive_net_slope_folds": sum(result["net_slope"] > 0 for result in results),
        "positive_adverse_slope_folds": sum(
            result["adverse_slope"] > 0 for result in results
        ),
        "largest_positive_net_fold_share": _float(concentration),
    }


def _structural_checks(
    frame: pd.DataFrame,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    closes = frame.iloc[:TRAIN_END]["close"].to_numpy(dtype=float)
    all_nonnegative = all(
        record[section][component] >= 0.0
        for record in records
        for section in ("baseline", "recent")
        for component in ("rv", "bv")
    )
    all_jump_bounded = all(
        0.0 <= record[section]["jump_share"] <= 1.0
        for record in records
        for section in ("baseline", "recent")
    )
    exact_windows = all(
        record["window_indices"]["baseline_return_end_exclusive"]
        - record["window_indices"]["baseline_return_start"]
        == BASELINE_RETURNS
        and record["window_indices"]["recent_return_end_exclusive"]
        - record["window_indices"]["recent_return_start"]
        == RECENT_RETURNS
        and record["window_indices"]["baseline_return_end_exclusive"]
        == record["window_indices"]["recent_return_start"]
        and record["window_indices"]["recent_return_end_exclusive"]
        == record["signal_index"] + 1
        for record in records
    )

    scaled_closes = closes * 7.25
    scale_differences = []
    for record in records:
        scaled = _feature_at(scaled_closes, int(record["signal_index"]))
        scale_differences.append(abs(scaled["feature"] - record["feature"]))
    maximum_scale_difference = max(scale_differences, default=0.0)
    scale_invariant = maximum_scale_difference <= 1e-12

    exact_equal_zero = _jump_share_from_components(1.0, 1.0) == 0.0
    within_tolerance_zero = _jump_share_from_components(1.0, 1.0 - 5e-13) == 0.0
    passed = all(
        (
            all_nonnegative,
            all_jump_bounded,
            exact_windows,
            scale_invariant,
            exact_equal_zero,
            within_tolerance_zero,
        )
    )
    return {
        "realized_and_bipower_variation_nonnegative": bool(all_nonnegative),
        "jump_share_inside_closed_unit_interval": bool(all_jump_bounded),
        "exact_nonoverlapping_adjacent_windows": bool(exact_windows),
        "positive_price_scale_invariance": bool(scale_invariant),
        "maximum_scale_invariance_difference": _float(maximum_scale_difference),
        "zero_jump_share_when_rv_equals_bv": bool(exact_equal_zero),
        "zero_jump_share_within_deterministic_tolerance": bool(within_tolerance_zero),
        "passed": bool(passed),
    }


def _target_evidence(
    instrument: str,
    frame: pd.DataFrame,
) -> dict[str, Any]:
    full_records, support = _build_records(frame)
    sealed_prefix_records, _ = _build_records(frame.iloc[:SEALED_OOS_END])
    training_prefix_records, _ = _build_records(frame.iloc[:TRAIN_END])
    full_identity = _canonical_json(full_records)
    prefix_invariant = (
        full_identity == _canonical_json(sealed_prefix_records)
        and full_identity == _canonical_json(training_prefix_records)
    )
    if not full_records:
        raise ValueError(f"{instrument} produced no valid opportunities")

    x = np.array([record["feature"] for record in full_records], dtype=float)
    net = np.array([record["net_return"] for record in full_records], dtype=float)
    adverse = np.array([record["adverse_excursion"] for record in full_records], dtype=float)
    delayed_net = np.array(
        [record["delayed_net_return"] for record in full_records], dtype=float
    )
    delayed_adverse = np.array(
        [record["delayed_adverse_excursion"] for record in full_records], dtype=float
    )

    statistics = _statistics(x, net, adverse)
    delayed = _statistics(x, delayed_net, delayed_adverse)
    bootstrap = _bootstrap(x, net, adverse, seed=SEEDS[instrument])
    breadth = _fold_breadth(full_records)
    structural = _structural_checks(frame, full_records)

    baseline_rv = np.array([record["baseline"]["rv"] for record in full_records])
    baseline_bv = np.array([record["baseline"]["bv"] for record in full_records])
    baseline_j = np.array([record["baseline"]["jump_share"] for record in full_records])
    recent_rv = np.array([record["recent"]["rv"] for record in full_records])
    recent_bv = np.array([record["recent"]["bv"] for record in full_records])
    recent_j = np.array([record["recent"]["jump_share"] for record in full_records])

    feature_q = np.quantile(x, [0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0])
    feature_evidence = {
        "distinct_values": int(len(np.unique(x))),
        "iqr": _float(np.quantile(x, 0.75) - np.quantile(x, 0.25)),
        "minimum": _float(feature_q[0]),
        "q10": _float(feature_q[1]),
        "q25": _float(feature_q[2]),
        "median": _float(feature_q[3]),
        "q75": _float(feature_q[4]),
        "q90": _float(feature_q[5]),
        "maximum": _float(feature_q[6]),
    }

    gates = {
        "minimum_180_valid_opportunities": len(full_records) >= 180,
        "minimum_120_distinct_and_positive_iqr": (
            feature_evidence["distinct_values"] >= 120 and feature_evidence["iqr"] > 0
        ),
        "tercile_support_at_least_50_each": (
            statistics["net_return"]["terciles"]["lower_count"] >= 50
            and statistics["net_return"]["terciles"]["upper_count"] >= 50
        ),
        "positive_continuous_associations": all(
            statistics[outcome][metric] > 0
            for outcome in ("net_return", "adverse_excursion")
            for metric in ("spearman", "standardized_ols_slope")
        ),
        "positive_tercile_effects": all(
            statistics[outcome]["terciles"]["upper_minus_lower"] > 0
            for outcome in ("net_return", "adverse_excursion")
        ),
        "positive_dependence_lower_bounds": all(
            interval["lower_95"] > 0
            for interval in bootstrap["intervals"].values()
        ),
        "three_of_four_fold_breadth_both_outcomes": (
            breadth["positive_net_slope_folds"] >= 3
            and breadth["positive_adverse_slope_folds"] >= 3
        ),
        "positive_fold_concentration_at_most_60pct": (
            breadth["largest_positive_net_fold_share"] <= 0.60
        ),
        "one_hour_delay_all_positive": all(
            delayed[outcome][metric] > 0
            for outcome in ("net_return", "adverse_excursion")
            for metric in ("spearman", "standardized_ols_slope")
        )
        and all(
            delayed[outcome]["terciles"]["upper_minus_lower"] > 0
            for outcome in ("net_return", "adverse_excursion")
        ),
        "prefix_invariance": prefix_invariant,
        "structural_identities": structural["passed"],
    }

    return {
        "instrument": instrument,
        "opportunity_support": support,
        "feature_evidence": feature_evidence,
        "variation_distributions": {
            "baseline_rv": _summary(baseline_rv),
            "baseline_bv": _summary(baseline_bv),
            "baseline_jump_share": _summary(baseline_j),
            "recent_rv": _summary(recent_rv),
            "recent_bv": _summary(recent_bv),
            "recent_jump_share": _summary(recent_j),
        },
        "statistics": statistics,
        "bootstrap": bootstrap,
        "fold_breadth": breadth,
        "one_hour_delay": delayed,
        "structural_checks": structural,
        "prefix_invariance": {
            "sealed_oos_and_unread_suffix_not_parsed_for_features_or_labels": True,
            "source_membership_features_and_labels_identical": bool(prefix_invariant),
        },
        "gates": gates,
        "passed": all(gates.values()),
    }


def _validate_source(
    instrument: str,
    primary: Any,
    repeat: Any,
) -> dict[str, Any]:
    frame = primary.candles
    repeated = repeat.candles
    if len(frame) != EXPECTED_ROWS or len(repeated) != EXPECTED_ROWS:
        raise ValueError(f"{instrument} source row count mismatch")
    if frame.index[0] != START or frame.index[-1] != END:
        raise ValueError(f"{instrument} source boundaries mismatch")
    if not frame.index.equals(repeated.index):
        raise ValueError(f"{instrument} repeated source index mismatch")
    pd.testing.assert_frame_equal(frame, repeated, check_exact=True)
    if not frame.index.is_monotonic_increasing or not frame.index.is_unique:
        raise ValueError(f"{instrument} source chronology invalid")
    expected_index = pd.date_range(START, END, freq="h")
    if not frame.index.equals(expected_index):
        raise ValueError(f"{instrument} source is not a strict UTC-hour grid")
    for column in ("open", "high", "low", "close"):
        values = frame[column].to_numpy(dtype=float)
        if not np.isfinite(values).all() or not (values > 0).all():
            raise ValueError(f"{instrument} contains invalid {column}")

    primary_hash = str(primary.metadata.get("normalized_csv_sha256"))
    repeat_hash = str(repeat.metadata.get("normalized_csv_sha256"))
    if len(primary_hash) != 64 or primary_hash != repeat_hash:
        raise ValueError(f"{instrument} repeated normalized source hash mismatch")
    if primary.metadata.get("instrument_id") != instrument:
        raise ValueError(f"{instrument} source instrument identity mismatch")
    if primary.metadata.get("bar") != "1H":
        raise ValueError(f"{instrument} source bar mismatch")

    return {
        "provider": "OKX",
        "market": "SPOT",
        "instrument": instrument,
        "bar": "1H",
        "start": START.isoformat(),
        "end": END.isoformat(),
        "rows": len(frame),
        "normalized_csv_sha256": primary_hash,
        "repeat_normalization_identical": True,
        "strict_utc_hour_grid": True,
        "finite_positive_ohlc": True,
        "duplicates": 0,
        "gaps": 0,
    }


def _fetch_source(instrument: str) -> tuple[Any, Any]:
    primary = fetch_okx_one_hour_candles(
        inst_id=instrument,
        start=START,
        end=END,
        pause_seconds=0.12,
        timeout=20.0,
        safety_pages=4,
    )
    repeat = fetch_okx_one_hour_candles(
        inst_id=instrument,
        start=START,
        end=END,
        pause_seconds=0.12,
        timeout=20.0,
        safety_pages=4,
    )
    return primary, repeat


def _fmt(value: float) -> str:
    return f"{value:+.6f}"


def _report(evidence: dict[str, Any]) -> str:
    lines = [
        "# Bipower jump-share contraction opportunity diagnostic",
        "",
        "```text",
        f"Family                 {FAMILY_ID}",
        f"Exact evidence head    {evidence['exact_head']}",
        "Fixed targets          NEAR-USDT and APT-USDT independently",
        "Candidate/grid         0/0",
        "Modeled fee            Exactly 5 bps one way",
        "Sealed OOS accessed    No",
        f"Verdict                {evidence['verdict']}",
        "```",
        "",
        "## Frozen information object",
        "",
        "The sole feature is baseline 720H jump share minus recent 168H jump share,",
        "where jump share is the non-negative realized-variance excess over bipower",
        "variation divided by realized variance. Every input ends at close[t-25].",
        "",
        "## Data",
        "",
        "| Target | Rows | Period | Normalized CSV SHA-256 |",
        "|---|---:|---|---|",
    ]
    for source in evidence["sources"]:
        lines.append(
            f"| {source['instrument']} | {source['rows']} | "
            f"{source['start']} to {source['end']} | "
            f"`{source['normalized_csv_sha256']}` |"
        )
    lines.extend(
        [
            "",
            "## Training-only information results",
            "",
            "| Target | N | Distinct | IQR | Net rho | Net slope | Net effect | "
            "Adverse rho | Adverse slope | Adverse effect |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for target in evidence["targets"]:
        stats = target["statistics"]
        lines.append(
            f"| {target['instrument']} | "
            f"{target['opportunity_support']['valid_opportunities']} | "
            f"{target['feature_evidence']['distinct_values']} | "
            f"{target['feature_evidence']['iqr']:.6f} | "
            f"{_fmt(stats['net_return']['spearman'])} | "
            f"{_fmt(stats['net_return']['standardized_ols_slope'])} | "
            f"{stats['net_return']['terciles']['upper_minus_lower'] * 10000:+.2f} bp | "
            f"{_fmt(stats['adverse_excursion']['spearman'])} | "
            f"{_fmt(stats['adverse_excursion']['standardized_ols_slope'])} | "
            f"{stats['adverse_excursion']['terciles']['upper_minus_lower'] * 10000:+.2f} bp |"
        )
    lines.extend(["", "## Dependence-aware uncertainty", ""])
    for target in evidence["targets"]:
        lines.append(f"### {target['instrument']}")
        lines.append("")
        lines.append("```text")
        for name, interval in target["bootstrap"]["intervals"].items():
            lines.append(
                f"{name:18s} [{interval['lower_95']:+.8f}, {interval['upper_95']:+.8f}]"
            )
        lines.append("```")
        lines.append("")
        breadth = target["fold_breadth"]
        lines.append(
            f"Fold breadth: net {breadth['positive_net_slope_folds']}/4, "
            f"adverse {breadth['positive_adverse_slope_folds']}/4; "
            "largest positive-net-fold share "
            f"{breadth['largest_positive_net_fold_share']:.2%}."
        )
        delayed = target["one_hour_delay"]
        lines.append(
            "One-hour delay: net effect "
            f"{delayed['net_return']['terciles']['upper_minus_lower'] * 10000:+.2f} bp, "
            "adverse effect "
            f"{delayed['adverse_excursion']['terciles']['upper_minus_lower'] * 10000:+.2f} bp."
        )
        lines.append("")
    lines.extend(
        [
            "## Gate vector",
            "",
            "```json",
            json.dumps(evidence["gate_vector"], indent=2, sort_keys=True),
            "```",
            "",
            "## Executable-performance accounting",
            "",
            "No threshold, sizing rule, position path or equity curve was authorised. "
            "Train, OOS and full return/Sharpe, benchmark comparison, turnover, "
            "drawdown, edge per turnover and calendar-year breadth are null rather "
            "than zero.",
            "",
            "## Remaining blocker",
            "",
            evidence["remaining_blocker"],
            "",
            "## Next strategy experiment",
            "",
            f"`{evidence['next_strategy_experiment']}`",
            "",
        ]
    )
    return "\n".join(lines)


def run(output_dir: Path) -> dict[str, Any]:
    exact_head = os.environ.get("GITHUB_SHA", "")
    if len(exact_head) != 40:
        raise ValueError("GITHUB_SHA must bind the exact tested revision")

    sources = []
    targets = []
    for instrument in TARGETS:
        primary, repeat = _fetch_source(instrument)
        sources.append(_validate_source(instrument, primary, repeat))
        targets.append(_target_evidence(instrument, primary.candles))

    bilateral_pass = all(target["passed"] for target in targets)
    verdict = (
        "accept_causal_own_price_bipower_jump_share_contraction_information_premise_"
        "1h_v1_for_separate_candidate_predeclaration"
        if bilateral_pass
        else "reject_causal_own_price_bipower_jump_share_contraction_information_premise_1h_v1"
    )
    gate_vector = {
        target["instrument"]: target["gates"]
        for target in targets
    }
    gate_vector["bilateral_pass"] = bilateral_pass

    remaining_blocker = (
        "The fixed jump-share contraction feature has not yet been translated into an "
        "executable policy; a separately preregistered selector is required."
        if bilateral_pass
        else "The own-history jump-share contraction statistic did not satisfy every "
        "bilateral support, sign, breadth, dependence and delay gate required before "
        "an executable long/cash candidate or OOS access."
    )
    evidence = {
        "family_id": FAMILY_ID,
        "exact_head": exact_head,
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "fixed_targets": list(TARGETS),
        "provider": "anonymous public OKX SPOT",
        "bar": "1H",
        "calendar": {
            "start": START.isoformat(),
            "end": END.isoformat(),
            "expected_rows_per_target": EXPECTED_ROWS,
            "training": [TRAIN_START, TRAIN_END],
            "sealed_oos": [SEALED_OOS_START, SEALED_OOS_END],
            "unread_suffix": [UNREAD_SUFFIX_START, EXPECTED_ROWS],
            "decision_step_hours": DECISION_STEP,
        },
        "canonical_fee_bps_one_way": 5.0,
        "sealed_oos_performance_accessed": False,
        "threshold_or_position_policy_defined": False,
        "canonical_mutation_authorized": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "credentials_used": False,
        "private_endpoints_used": False,
        "cross_sectional_selection": False,
        "synthetic_market_data_used": False,
        "sources": sources,
        "targets": targets,
        "bilateral_pass": bilateral_pass,
        "gate_vector": gate_vector,
        "verdict": verdict,
        "economics": {
            "training_return": None,
            "training_sharpe": None,
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
        "remaining_blocker": remaining_blocker,
        "next_strategy_experiment": NEXT_EXPERIMENT,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    evidence_text = _canonical_json(evidence)
    evidence_hash = hashlib.sha256(evidence_text.encode("utf-8")).hexdigest()
    report_text = _report(evidence)
    (output_dir / "evidence.json").write_text(evidence_text, encoding="utf-8")
    (output_dir / "evidence.sha256").write_text(evidence_hash + "\n", encoding="utf-8")
    (output_dir / "report.md").write_text(report_text, encoding="utf-8")
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    evidence = run(args.output_dir)
    print(_canonical_json(evidence), end="")


if __name__ == "__main__":
    main()
