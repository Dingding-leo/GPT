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

FAMILY_ID = "causal-own-price-horizontal-visibility-path-simplification-opportunity-1h-v1"
TARGETS = ("SOL-USDT", "BNB-USDT")
START = pd.Timestamp("2023-04-01T00:00:00Z")
END = pd.Timestamp("2025-12-31T23:00:00Z")
EXPECTED_ROWS = 24_144
TRAIN_START = 2_208
TRAIN_END = 10_800
SEALED_OOS_START = 10_800
SEALED_OOS_END = 23_760
UNREAD_SUFFIX_START = 23_760
RECENT_HOURS = 168
BASELINE_HOURS = 720
E2160_HOURS = 2_160
DECISION_STEP = 24
FEE_ONE_WAY = 0.0005
BOOTSTRAP_DRAWS = 5_000
BOOTSTRAP_BLOCK = 7
SEEDS = {"SOL-USDT": 2026080305, "BNB-USDT": 2026080306}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def _float(value: float | np.floating[Any]) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("non-finite statistic")
    return result


def _horizontal_visibility_edge_count(values: np.ndarray) -> int:
    x = np.asarray(values, dtype=float)
    if x.ndim != 1 or len(x) < 2 or not np.isfinite(x).all():
        raise ValueError("visibility input must be a finite one-dimensional sequence")
    stack: list[int] = []
    edges = 0
    for index, value in enumerate(x):
        while stack and value > x[stack[-1]]:
            stack.pop()
            edges += 1
        if stack:
            edges += 1
            if value == x[stack[-1]]:
                stack.pop()
        stack.append(index)
    return edges


def _excess_visibility(values: np.ndarray) -> float:
    n = len(values)
    edges = _horizontal_visibility_edge_count(values)
    return 2.0 * (edges - (n - 1)) / n


def _visibility_matrix(values: np.ndarray) -> np.ndarray:
    x = np.asarray(values, dtype=float)
    n = len(x)
    matrix = np.zeros((n, n), dtype=np.uint8)
    for left in range(n - 1):
        maximum_between = -np.inf
        for right in range(left + 1, n):
            if maximum_between < min(x[left], x[right]):
                matrix[left, right] = 1
                matrix[right, left] = 1
            maximum_between = max(maximum_between, x[right])
    return matrix


def _structural_checks(observed: np.ndarray) -> dict[str, Any]:
    matrix = _visibility_matrix(observed)
    degrees = matrix.sum(axis=1)
    edge_count_matrix = int(matrix.sum() // 2)
    edge_count_stack = _horizontal_visibility_edge_count(observed)
    adjacency = bool(np.all(np.diag(matrix, k=1) == 1))
    symmetry = bool(np.array_equal(matrix, matrix.T))
    degree_sum = int(degrees.sum()) == 2 * edge_count_matrix
    stack_identity = edge_count_matrix == edge_count_stack
    increasing = np.sort(observed, kind="mergesort")
    if np.any(np.diff(increasing) <= 0):
        increasing = increasing + np.arange(len(increasing), dtype=float) * np.finfo(float).eps
    decreasing = increasing[::-1].copy()
    monotone_zero = abs(_excess_visibility(increasing)) < 1e-15 and abs(
        _excess_visibility(decreasing)
    ) < 1e-15
    affine_invariance = abs(
        _excess_visibility(observed) - _excess_visibility(observed * 1.7 + 0.3)
    ) < 1e-15
    passed = all(
        (adjacency, symmetry, degree_sum, stack_identity, monotone_zero, affine_invariance)
    )
    return {
        "adjacency_inclusion": adjacency,
        "matrix_symmetry": symmetry,
        "degree_sum_identity": degree_sum,
        "linear_stack_edge_count_identity": stack_identity,
        "strict_monotone_zero_excess": monotone_zero,
        "positive_affine_invariance": affine_invariance,
        "observed_window_nodes": len(observed),
        "observed_window_edges": edge_count_matrix,
        "passed": passed,
    }


def _spearman(x: np.ndarray, y: np.ndarray) -> float:
    x_rank = pd.Series(x).rank(method="average").to_numpy(dtype=float)
    y_rank = pd.Series(y).rank(method="average").to_numpy(dtype=float)
    return _float(np.corrcoef(x_rank, y_rank)[0, 1])


def _standardized_slope(x: np.ndarray, y: np.ndarray) -> float:
    z = (x - x.mean()) / x.std(ddof=0)
    return _float(np.mean(z * (y - y.mean())))


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
    rng: np.random.Generator, observations: int, block: int
) -> np.ndarray:
    blocks = math.ceil(observations / block)
    starts = rng.integers(0, observations - block + 1, size=blocks)
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
        intervals[name] = {"lower_95": _float(lower), "upper_95": _float(upper)}
    return {
        "draws": BOOTSTRAP_DRAWS,
        "block_opportunities": BOOTSTRAP_BLOCK,
        "seed": seed,
        "intervals": intervals,
    }


def _fold_breadth(records: list[dict[str, float]]) -> dict[str, Any]:
    anchors = np.arange(TRAIN_START, TRAIN_END, DECISION_STEP)
    anchor_folds = np.array_split(anchors, 4)
    fold_results = []
    for fold_number, fold_anchors in enumerate(anchor_folds, start=1):
        anchor_set = set(int(value) for value in fold_anchors)
        subset = [record for record in records if int(record["anchor"]) in anchor_set]
        x = np.array([record["feature"] for record in subset])
        net = np.array([record["net_return"] for record in subset])
        adverse = np.array([record["adverse_excursion"] for record in subset])
        fold_results.append(
            {
                "fold": fold_number,
                "anchor_start": int(fold_anchors[0]),
                "anchor_end_exclusive": int(fold_anchors[-1] + DECISION_STEP),
                "opportunities": len(subset),
                "net_slope": _standardized_slope(x, net),
                "adverse_slope": _standardized_slope(x, adverse),
            }
        )
    net_positive = [max(0.0, fold["net_slope"]) for fold in fold_results]
    positive_sum = sum(net_positive)
    concentration = max(net_positive) / positive_sum if positive_sum > 0 else 1.0
    return {
        "folds": fold_results,
        "positive_net_slope_folds": sum(fold["net_slope"] > 0 for fold in fold_results),
        "positive_adverse_slope_folds": sum(
            fold["adverse_slope"] > 0 for fold in fold_results
        ),
        "largest_positive_net_fold_share": _float(concentration),
    }


def _build_records(frame: pd.DataFrame) -> list[dict[str, float]]:
    open_values = frame["open"].to_numpy(dtype=float)
    low_values = frame["low"].to_numpy(dtype=float)
    close_values = frame["close"].to_numpy(dtype=float)
    log_close = np.log(close_values)
    records: list[dict[str, float]] = []
    for anchor in range(TRAIN_START, TRAIN_END, DECISION_STEP):
        e2160_margin = log_close[anchor - 25] - log_close[anchor - 25 - E2160_HOURS]
        if e2160_margin <= 0:
            continue
        recent_end = anchor - 24
        recent_start = recent_end - RECENT_HOURS
        baseline_end = recent_start
        baseline_start = baseline_end - BASELINE_HOURS
        recent = log_close[recent_start:recent_end]
        baseline = log_close[baseline_start:baseline_end]
        feature = _excess_visibility(baseline) - _excess_visibility(recent)
        entry = open_values[anchor]
        exit_value = open_values[anchor + 24]
        net_return = exit_value / entry - 1.0 - 2.0 * FEE_ONE_WAY
        adverse = low_values[anchor : anchor + 24].min() / entry - 1.0
        delayed_entry = open_values[anchor + 1]
        delayed_exit = open_values[anchor + 25]
        delayed_net = delayed_exit / delayed_entry - 1.0 - 2.0 * FEE_ONE_WAY
        delayed_adverse = low_values[anchor + 1 : anchor + 25].min() / delayed_entry - 1.0
        records.append(
            {
                "anchor": float(anchor),
                "feature": _float(feature),
                "net_return": _float(net_return),
                "adverse_excursion": _float(adverse),
                "delayed_net_return": _float(delayed_net),
                "delayed_adverse_excursion": _float(delayed_adverse),
            }
        )
    return records


def _source_contract(instrument: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    first = fetch_okx_one_hour_candles(
        inst_id=instrument,
        start=START,
        end=END,
        pause_seconds=0.12,
        safety_pages=100,
    )
    second = fetch_okx_one_hour_candles(
        inst_id=instrument,
        start=START,
        end=END,
        pause_seconds=0.12,
        safety_pages=100,
    )
    frame = first.candles
    expected_index = pd.date_range(START, END, freq="h")
    if len(frame) != EXPECTED_ROWS or not frame.index.equals(expected_index):
        raise ValueError(f"{instrument} does not satisfy the exact frozen calendar")
    if not frame.index.is_unique or frame.index.has_duplicates:
        raise ValueError(f"{instrument} contains duplicate timestamps")
    ohlc = frame[["open", "high", "low", "close"]].to_numpy(dtype=float)
    if not np.isfinite(ohlc).all() or not (ohlc > 0).all():
        raise ValueError(f"{instrument} contains invalid OHLC values")
    if first.metadata.get("instrument_id") != instrument or first.metadata.get("bar") != "1H":
        raise ValueError(f"{instrument} source identity mismatch")
    first_hash = str(first.metadata["normalized_csv_sha256"])
    second_hash = str(second.metadata["normalized_csv_sha256"])
    if first_hash != second_hash or not first.candles.equals(second.candles):
        raise ValueError(f"{instrument} repeated normalized frozen slices differ")
    return frame, {
        "provider": "OKX public SPOT",
        "instrument": instrument,
        "bar": "1H",
        "requested_start": START.isoformat(),
        "requested_end": END.isoformat(),
        "rows": len(frame),
        "normalized_csv_sha256": first_hash,
        "repeat_normalization_identical": True,
        "strict_hour_grid": True,
        "duplicates": 0,
        "gaps": 0,
        "finite_positive_ohlc": True,
        "completed_candles_only": True,
    }


def _analyse_target(instrument: str, frame: pd.DataFrame) -> dict[str, Any]:
    records = _build_records(frame)
    prefix_records = _build_records(frame.iloc[:UNREAD_SUFFIX_START].copy())
    if records != prefix_records:
        raise ValueError(f"{instrument} future suffix changed training records")
    x = np.array([record["feature"] for record in records])
    net = np.array([record["net_return"] for record in records])
    adverse = np.array([record["adverse_excursion"] for record in records])
    delayed_net = np.array([record["delayed_net_return"] for record in records])
    delayed_adverse = np.array(
        [record["delayed_adverse_excursion"] for record in records]
    )
    statistics = _statistics(x, net, adverse)
    delay = _statistics(x, delayed_net, delayed_adverse)
    bootstrap = _bootstrap(x, net, adverse, seed=SEEDS[instrument])
    breadth = _fold_breadth(records)
    observed = np.log(frame["close"].to_numpy(dtype=float)[TRAIN_START - 192 : TRAIN_START - 24])
    structural = _structural_checks(observed)
    q = np.quantile(x, [0.0, 0.25, 0.5, 0.75, 1.0])
    distinct = int(np.unique(x).size)
    iqr = _float(q[3] - q[1])
    support = {
        "scheduled_training_anchors": len(range(TRAIN_START, TRAIN_END, DECISION_STEP)),
        "eligible_valid_opportunities": len(records),
        "distinct_feature_values": distinct,
        "feature_iqr": iqr,
        "feature_quantiles": {
            "minimum": _float(q[0]),
            "q25": _float(q[1]),
            "median": _float(q[2]),
            "q75": _float(q[3]),
            "maximum": _float(q[4]),
        },
    }
    intervals = bootstrap["intervals"]
    gates = {
        "support_at_least_180": len(records) >= 180,
        "feature_active": distinct >= 100 and iqr > 0,
        "tercile_support": all(
            statistics[name]["terciles"]["lower_count"] >= 50
            and statistics[name]["terciles"]["upper_count"] >= 50
            for name in ("net_return", "adverse_excursion")
        ),
        "positive_continuous_statistics": all(
            statistics[name]["spearman"] > 0
            and statistics[name]["standardized_ols_slope"] > 0
            for name in ("net_return", "adverse_excursion")
        ),
        "positive_tercile_effects": all(
            statistics[name]["terciles"]["upper_minus_lower"] > 0
            for name in ("net_return", "adverse_excursion")
        ),
        "positive_bootstrap_lower_bounds": all(
            interval["lower_95"] > 0 for interval in intervals.values()
        ),
        "fold_breadth": breadth["positive_net_slope_folds"] >= 3
        and breadth["positive_adverse_slope_folds"] >= 3,
        "fold_concentration": breadth["largest_positive_net_fold_share"] <= 0.60,
        "one_hour_delay": all(
            delay[name]["spearman"] > 0
            and delay[name]["standardized_ols_slope"] > 0
            and delay[name]["terciles"]["upper_minus_lower"] > 0
            for name in ("net_return", "adverse_excursion")
        ),
        "prefix_invariance": True,
        "structural_graph_checks": structural["passed"],
    }
    return {
        "instrument": instrument,
        "opportunity_support": support,
        "statistics": statistics,
        "bootstrap": bootstrap,
        "fold_breadth": breadth,
        "one_hour_delay": delay,
        "prefix_invariance": {
            "unread_suffix_start": UNREAD_SUFFIX_START,
            "opportunity_membership_feature_and_labels_identical": True,
        },
        "structural_checks": structural,
        "gates": gates,
        "passed": all(gates.values()),
    }


def _report(evidence: dict[str, Any]) -> str:
    lines = [
        "# Horizontal-visibility path-simplification opportunity diagnostic",
        "",
        "```text",
        f"family                 {evidence['family_id']}",
        f"exact head             {evidence['exact_head']}",
        "candidate/grid         0/0",
        "fixed targets          SOL-USDT / BNB-USDT independently",
        "bar                    completed provider-native 1H",
        "fee                    exactly 5 bps one way",
        f"verdict                {evidence['verdict']}",
        "```",
        "",
        "## Frozen data",
        "",
        "| Target | Rows | UTC sample | Normalized CSV SHA-256 |",
        "|---|---:|---|---|",
    ]
    for source in evidence["sources"]:
        lines.append(
            f"| {source['instrument']} | {source['rows']} | "
            f"{source['requested_start']} through {source['requested_end']} | "
            f"`{source['normalized_csv_sha256']}` |"
        )
    lines.extend(
        [
            "",
            "Training anchors are `[2208,10800)` every 24 hours. "
            "The sealed interval `[10800,23760)` was not inspected; "
            "`[23760,24144)` was used only for prefix invariance.",
            "",
            "## Training information results",
            "",
            "| Target | N | Distinct | IQR | Net rho | Net slope | Net tercile | "
            "Adverse rho | Adverse slope | Adverse tercile |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for target in evidence["targets"]:
        support = target["opportunity_support"]
        stats = target["statistics"]
        lines.append(
            f"| {target['instrument']} | {support['eligible_valid_opportunities']} | "
            f"{support['distinct_feature_values']} | {support['feature_iqr']:.6f} | "
            f"{stats['net_return']['spearman']:+.6f} | "
            f"{stats['net_return']['standardized_ols_slope']:+.6f} | "
            f"{stats['net_return']['terciles']['upper_minus_lower'] * 10000:+.2f} bp | "
            f"{stats['adverse_excursion']['spearman']:+.6f} | "
            f"{stats['adverse_excursion']['standardized_ols_slope']:+.6f} | "
            f"{stats['adverse_excursion']['terciles']['upper_minus_lower'] * 10000:+.2f} bp |"
        )
    lines.extend(["", "## Dependence-aware uncertainty", ""])
    for target in evidence["targets"]:
        lines.append(f"### {target['instrument']}")
        lines.append("")
        lines.append("```text")
        for name, interval in target["bootstrap"]["intervals"].items():
            lines.append(
                f"{name:20s} [{interval['lower_95']:+.8f}, "
                f"{interval['upper_95']:+.8f}]"
            )
        lines.append("```")
    lines.extend(["", "## Fold breadth and execution delay", ""])
    for target in evidence["targets"]:
        breadth = target["fold_breadth"]
        delay = target["one_hour_delay"]
        lines.append(
            f"- **{target['instrument']}**: positive net/adverse folds "
            f"{breadth['positive_net_slope_folds']}/4 and "
            f"{breadth['positive_adverse_slope_folds']}/4; largest positive-net-fold "
            f"share {breadth['largest_positive_net_fold_share']:.2%}. Delayed net/adverse "
            f"tercile effects "
            f"{delay['net_return']['terciles']['upper_minus_lower'] * 10000:+.2f} bp / "
            f"{delay['adverse_excursion']['terciles']['upper_minus_lower'] * 10000:+.2f} bp."
        )
    lines.extend(
        [
            "",
            "## Gate vector",
            "",
            "```json",
            json.dumps(evidence["gate_vector"], indent=2, sort_keys=True),
            "```",
            "",
            "No threshold, sizing rule, state machine or equity curve was authorised. "
            "Training/OOS/full return, Sharpe, benchmark comparison, turnover, drawdown, "
            "edge per turnover and calendar-year strategy breadth are null rather than zero.",
            "",
            f"**Remaining blocker:** {evidence['remaining_blocker']}",
            "",
            f"**Next strategy experiment:** `{evidence['next_strategy_experiment']}`",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    exact_head = os.environ.get("GITHUB_SHA", "")
    if len(exact_head) != 40:
        raise ValueError("GITHUB_SHA must bind evidence to an exact commit")
    sources = []
    targets = []
    for instrument in TARGETS:
        frame, source = _source_contract(instrument)
        sources.append(source)
        targets.append(_analyse_target(instrument, frame))
    bilateral_pass = all(target["passed"] for target in targets)
    verdict = (
        "accept_causal_own_price_horizontal_visibility_path_simplification_information_"
        "premise_1h_v1_for_separate_candidate_predeclaration"
        if bilateral_pass
        else "reject_causal_own_price_horizontal_visibility_path_simplification_"
        "information_premise_1h_v1"
    )
    gate_vector = {
        target["instrument"]: target["gates"] | {"all_target_gates": target["passed"]}
        for target in targets
    }
    evidence = {
        "family_id": FAMILY_ID,
        "exact_head": exact_head,
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "fixed_targets": list(TARGETS),
        "bar": "1H",
        "canonical_fee_bps_one_way": 5.0,
        "training": [TRAIN_START, TRAIN_END],
        "sealed_oos": [SEALED_OOS_START, SEALED_OOS_END],
        "unread_suffix": [UNREAD_SUFFIX_START, EXPECTED_ROWS],
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
        "economics": {
            "training_strategy_return": None,
            "training_strategy_sharpe": None,
            "oos_strategy_return": None,
            "oos_strategy_sharpe": None,
            "full_strategy_return": None,
            "full_strategy_sharpe": None,
            "benchmark_comparison": None,
            "turnover": None,
            "fee_drag": None,
            "maximum_drawdown": None,
            "edge_per_turnover": None,
            "calendar_year_breadth": None,
        },
        "verdict": verdict,
        "remaining_blocker": (
            "Horizontal-visibility simplification did not provide bilateral, broad, "
            "dependence-supported continuation and downside information."
            if not bilateral_pass
            else "An executable candidate still requires separate zero-grid preregistration "
            "and untouched OOS evaluation."
        ),
        "next_strategy_experiment": (
            "causal-own-price-drawdown-recovery-hazard-opportunity-1h-v1"
            if not bilateral_pass
            else "causal-own-price-horizontal-visibility-path-simplification-candidate-1h-v1"
        ),
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    evidence_text = _canonical_json(evidence)
    evidence_path = args.output_dir / "evidence.json"
    evidence_path.write_text(evidence_text, encoding="utf-8")
    digest = hashlib.sha256(evidence_text.encode()).hexdigest()
    (args.output_dir / "evidence.sha256").write_text(digest + "\n", encoding="utf-8")
    (args.output_dir / "report.md").write_text(_report(evidence), encoding="utf-8")
    print(_canonical_json({"verdict": verdict, "bilateral_pass": bilateral_pass}))


if __name__ == "__main__":
    main()
