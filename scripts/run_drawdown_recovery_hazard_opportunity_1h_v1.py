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

FAMILY_ID = "causal-own-price-drawdown-recovery-hazard-opportunity-1h-v1"
TARGETS = ("AVAX-USDT", "DOT-USDT")
START = pd.Timestamp("2023-04-01T00:00:00Z")
END = pd.Timestamp("2025-12-31T23:00:00Z")
EXPECTED_ROWS = 24_144
TRAIN_START = 2_208
TRAIN_END = 10_800
SEALED_OOS_START = 10_800
SEALED_OOS_END = 23_760
UNREAD_SUFFIX_START = 23_760
PEAK_LOOKBACK = 168
E2160_HOURS = 2_160
DECISION_STEP = 24
RECOVERY_HORIZON = 24
MIN_PRIOR_EPISODES = 20
MIN_RISK_SET = 10
FEE_ONE_WAY = 0.0005
BOOTSTRAP_DRAWS = 5_000
BOOTSTRAP_BLOCK = 7
SEEDS = {"AVAX-USDT": 2026080307, "DOT-USDT": 2026080308}


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
    z = (x - x.mean()) / scale
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
    rng: np.random.Generator,
    observations: int,
    block: int,
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


def _parse_episodes(
    close_values: np.ndarray,
) -> tuple[list[dict[str, Any]], list[dict[str, Any] | None]]:
    closes = np.asarray(close_values, dtype=float)
    if closes.ndim != 1 or len(closes) < PEAK_LOOKBACK + 1:
        raise ValueError("episode parser requires a finite one-dimensional close series")
    if not np.isfinite(closes).all() or not (closes > 0).all():
        raise ValueError("episode parser received invalid closes")

    completed: list[dict[str, Any]] = []
    active_state: list[dict[str, Any] | None] = [None] * len(closes)
    active: dict[str, Any] | None = None

    for hour in range(PEAK_LOOKBACK, len(closes)):
        close = closes[hour]
        if active is None:
            peak = _float(closes[hour - PEAK_LOOKBACK : hour].max())
            if close < peak:
                active = {
                    "start": hour,
                    "peak": peak,
                }
        else:
            if close >= active["peak"]:
                episode = {
                    "start": int(active["start"]),
                    "end": hour,
                    "duration": hour - int(active["start"]) + 1,
                    "peak": _float(active["peak"]),
                }
                completed.append(episode)
                active = None
        if active is not None:
            active_state[hour] = {
                "start": int(active["start"]),
                "peak": _float(active["peak"]),
                "age": hour - int(active["start"]) + 1,
            }

    return completed, active_state


def _episode_structural_checks(
    close_values: np.ndarray,
    completed: list[dict[str, Any]],
    active_state: list[dict[str, Any] | None],
) -> dict[str, Any]:
    closes = np.asarray(close_values, dtype=float)
    no_overlap = all(
        int(completed[index]["start"]) > int(completed[index - 1]["end"])
        for index in range(1, len(completed))
    )
    peak_excludes_current = True
    frozen_peak = True
    first_crossing = True
    duration_exact = True

    for episode in completed:
        start = int(episode["start"])
        end = int(episode["end"])
        peak = float(episode["peak"])
        expected_peak = float(closes[start - PEAK_LOOKBACK : start].max())
        peak_excludes_current &= peak == expected_peak and closes[start] < peak
        frozen_peak &= all(
            state is None
            or int(state["start"]) != start
            or float(state["peak"]) == peak
            for state in active_state[start : end + 1]
        )
        first_crossing &= bool(np.all(closes[start:end] < peak) and closes[end] >= peak)
        duration_exact &= int(episode["duration"]) == end - start + 1

    active_starts = {
        int(state["start"])
        for state in active_state
        if state is not None
    }
    active_peak_consistency = all(
        len(
            {
                float(state["peak"])
                for state in active_state
                if state is not None and int(state["start"]) == start
            }
        )
        == 1
        for start in active_starts
    )
    passed = all(
        (
            no_overlap,
            peak_excludes_current,
            frozen_peak,
            first_crossing,
            duration_exact,
            active_peak_consistency,
        )
    )
    return {
        "episodes_do_not_overlap": bool(no_overlap),
        "peak_excludes_current_close": bool(peak_excludes_current),
        "peak_frozen_inside_episode": bool(frozen_peak),
        "completion_is_first_qualifying_crossing": bool(first_crossing),
        "duration_arithmetic_exact": bool(duration_exact),
        "active_peak_consistency": bool(active_peak_consistency),
        "passed": bool(passed),
    }


def _duration_summary(completed: list[dict[str, Any]]) -> dict[str, Any]:
    durations = np.array([episode["duration"] for episode in completed], dtype=float)
    if len(durations) == 0:
        raise ValueError("no completed episodes")
    quantiles = np.quantile(durations, [0.0, 0.25, 0.5, 0.75, 0.9, 1.0])
    return {
        "completed_episode_count": len(completed),
        "minimum_hours": _float(quantiles[0]),
        "q25_hours": _float(quantiles[1]),
        "median_hours": _float(quantiles[2]),
        "q75_hours": _float(quantiles[3]),
        "q90_hours": _float(quantiles[4]),
        "maximum_hours": _float(quantiles[5]),
        "mean_hours": _float(durations.mean()),
    }


def _build_records(
    frame: pd.DataFrame,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    training = frame.iloc[:TRAIN_END].copy()
    open_values = training["open"].to_numpy(dtype=float)
    close_values = training["close"].to_numpy(dtype=float)
    completed, active_state = _parse_episodes(close_values)
    structural = _episode_structural_checks(close_values, completed, active_state)
    records: list[dict[str, Any]] = []
    counts = {
        "scheduled_training_anchors": 0,
        "positive_e2160_anchors": 0,
        "positive_e2160_active_episode_anchors": 0,
        "skipped_fewer_than_20_prior_episodes": 0,
        "skipped_risk_set_below_10": 0,
        "valid_opportunities": 0,
    }

    for anchor in range(TRAIN_START, TRAIN_END, DECISION_STEP):
        if anchor + RECOVERY_HORIZON + 1 >= TRAIN_END:
            continue
        counts["scheduled_training_anchors"] += 1
        signal_index = anchor - 25
        if close_values[signal_index] <= close_values[signal_index - E2160_HOURS]:
            continue
        counts["positive_e2160_anchors"] += 1
        current = active_state[signal_index]
        if current is None:
            continue
        counts["positive_e2160_active_episode_anchors"] += 1
        current_start = int(current["start"])
        age = int(current["age"])
        prior = [
            episode
            for episode in completed
            if int(episode["end"]) < current_start
        ]
        if len(prior) < MIN_PRIOR_EPISODES:
            counts["skipped_fewer_than_20_prior_episodes"] += 1
            continue
        durations = np.array([episode["duration"] for episode in prior], dtype=int)
        risk_set = int(np.sum(durations > age))
        recoveries = int(
            np.sum((durations > age) & (durations <= age + RECOVERY_HORIZON))
        )
        if risk_set < MIN_RISK_SET:
            counts["skipped_risk_set_below_10"] += 1
            continue
        hazard = (recoveries + 0.5) / (risk_set + 1.0)
        if not 0.0 < hazard < 1.0:
            raise ValueError("Jeffreys-smoothed hazard must lie strictly inside (0, 1)")

        base_path = open_values[anchor : anchor + RECOVERY_HORIZON + 1] / open_values[anchor] - 1.0
        delayed_path = (
            open_values[anchor + 1 : anchor + RECOVERY_HORIZON + 2]
            / open_values[anchor + 1]
            - 1.0
        )
        record = {
            "anchor": anchor,
            "signal_index": signal_index,
            "current_episode_start": current_start,
            "current_episode_age": age,
            "current_episode_peak": _float(current["peak"]),
            "prior_completed_episodes": len(prior),
            "latest_prior_episode_end": int(max(episode["end"] for episode in prior)),
            "risk_set": risk_set,
            "recoveries_next_24h": recoveries,
            "feature": _float(hazard),
            "net_return": _float(
                open_values[anchor + RECOVERY_HORIZON] / open_values[anchor]
                - 1.0
                - 2.0 * FEE_ONE_WAY
            ),
            "adverse_excursion": _float(base_path.min()),
            "delayed_net_return": _float(
                open_values[anchor + RECOVERY_HORIZON + 1] / open_values[anchor + 1]
                - 1.0
                - 2.0 * FEE_ONE_WAY
            ),
            "delayed_adverse_excursion": _float(delayed_path.min()),
        }
        if record["latest_prior_episode_end"] >= current_start:
            raise ValueError("future or current episode entered historical hazard risk set")
        records.append(record)

    counts["valid_opportunities"] = len(records)
    return records, counts, {
        "duration_summary": _duration_summary(completed),
        "structural_checks": structural,
    }


def _fold_breadth(records: list[dict[str, Any]]) -> dict[str, Any]:
    index_folds = np.array_split(np.arange(len(records)), 4)
    fold_results: list[dict[str, Any]] = []
    for fold_number, indices in enumerate(index_folds, start=1):
        subset = [records[int(index)] for index in indices]
        x = np.array([record["feature"] for record in subset], dtype=float)
        net = np.array([record["net_return"] for record in subset], dtype=float)
        adverse = np.array([record["adverse_excursion"] for record in subset], dtype=float)
        fold_results.append(
            {
                "fold": fold_number,
                "anchor_start": int(subset[0]["anchor"]),
                "anchor_end_exclusive": int(subset[-1]["anchor"] + DECISION_STEP),
                "opportunities": len(subset),
                "net_slope": _standardized_slope(x, net),
                "adverse_slope": _standardized_slope(x, adverse),
            }
        )
    positive_net = [max(0.0, fold["net_slope"]) for fold in fold_results]
    positive_sum = sum(positive_net)
    concentration = max(positive_net) / positive_sum if positive_sum > 0 else 1.0
    return {
        "fold_definition": "four fixed contiguous eligible-opportunity blocks",
        "folds": fold_results,
        "positive_net_slope_folds": sum(
            fold["net_slope"] > 0 for fold in fold_results
        ),
        "positive_adverse_slope_folds": sum(
            fold["adverse_slope"] > 0 for fold in fold_results
        ),
        "largest_positive_net_fold_share": _float(concentration),
    }


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
    if first.metadata.get("instrument_id") != instrument:
        raise ValueError(f"{instrument} source identity mismatch")
    if first.metadata.get("bar") != "1H":
        raise ValueError(f"{instrument} source bar mismatch")
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
    records, counts, episode = _build_records(frame)
    prefix_records, prefix_counts, prefix_episode = _build_records(
        frame.iloc[:TRAIN_END].copy()
    )
    if records != prefix_records:
        raise ValueError(f"{instrument} future suffix changed training records")
    if counts != prefix_counts or episode != prefix_episode:
        raise ValueError(f"{instrument} future suffix changed episode evidence")
    if len(records) < 4:
        raise ValueError(f"{instrument} has insufficient records for fixed folds")

    x = np.array([record["feature"] for record in records], dtype=float)
    net = np.array([record["net_return"] for record in records], dtype=float)
    adverse = np.array([record["adverse_excursion"] for record in records], dtype=float)
    delayed_net = np.array(
        [record["delayed_net_return"] for record in records],
        dtype=float,
    )
    delayed_adverse = np.array(
        [record["delayed_adverse_excursion"] for record in records],
        dtype=float,
    )
    ages = np.array([record["current_episode_age"] for record in records], dtype=float)
    risk_sets = np.array([record["risk_set"] for record in records], dtype=float)
    prior_counts = np.array(
        [record["prior_completed_episodes"] for record in records],
        dtype=float,
    )

    statistics = _statistics(x, net, adverse)
    delay = _statistics(x, delayed_net, delayed_adverse)
    bootstrap = _bootstrap(x, net, adverse, seed=SEEDS[instrument])
    breadth = _fold_breadth(records)
    feature_quantiles = np.quantile(x, [0.0, 0.25, 0.5, 0.75, 1.0])
    age_quantiles = np.quantile(ages, [0.0, 0.25, 0.5, 0.75, 1.0])
    risk_quantiles = np.quantile(risk_sets, [0.0, 0.25, 0.5, 0.75, 1.0])
    prior_quantiles = np.quantile(prior_counts, [0.0, 0.5, 1.0])
    distinct = int(np.unique(x).size)
    iqr = _float(feature_quantiles[3] - feature_quantiles[1])
    support = {
        **counts,
        "distinct_feature_values": distinct,
        "feature_iqr": iqr,
        "feature_quantiles": {
            "minimum": _float(feature_quantiles[0]),
            "q25": _float(feature_quantiles[1]),
            "median": _float(feature_quantiles[2]),
            "q75": _float(feature_quantiles[3]),
            "maximum": _float(feature_quantiles[4]),
        },
        "age_quantiles_hours": {
            "minimum": _float(age_quantiles[0]),
            "q25": _float(age_quantiles[1]),
            "median": _float(age_quantiles[2]),
            "q75": _float(age_quantiles[3]),
            "maximum": _float(age_quantiles[4]),
        },
        "risk_set_quantiles": {
            "minimum": _float(risk_quantiles[0]),
            "q25": _float(risk_quantiles[1]),
            "median": _float(risk_quantiles[2]),
            "q75": _float(risk_quantiles[3]),
            "maximum": _float(risk_quantiles[4]),
        },
        "prior_completed_episode_quantiles": {
            "minimum": _float(prior_quantiles[0]),
            "median": _float(prior_quantiles[1]),
            "maximum": _float(prior_quantiles[2]),
        },
    }
    intervals = bootstrap["intervals"]
    gates = {
        "support_at_least_120": len(records) >= 120,
        "historical_support_contract": all(
            record["prior_completed_episodes"] >= MIN_PRIOR_EPISODES
            and record["risk_set"] >= MIN_RISK_SET
            for record in records
        ),
        "feature_active": distinct >= 30 and iqr > 0,
        "tercile_support": all(
            statistics[name]["terciles"]["lower_count"] >= 35
            and statistics[name]["terciles"]["upper_count"] >= 35
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
        "structural_episode_checks": episode["structural_checks"]["passed"],
        "hazard_and_risk_set_causality": all(
            0.0 < record["feature"] < 1.0
            and record["latest_prior_episode_end"] < record["current_episode_start"]
            <= record["signal_index"]
            for record in records
        ),
    }
    return {
        "instrument": instrument,
        "episode_evidence": episode,
        "opportunity_support": support,
        "statistics": statistics,
        "bootstrap": bootstrap,
        "fold_breadth": breadth,
        "one_hour_delay": delay,
        "prefix_invariance": {
            "training_prefix_rows": TRAIN_END,
            "sealed_oos_and_unread_suffix_not_parsed_for_episodes_or_labels": True,
            "episode_risk_sets_features_and_labels_identical": True,
        },
        "gates": gates,
        "passed": all(gates.values()),
    }


def _report(evidence: dict[str, Any]) -> str:
    lines = [
        "# Drawdown-recovery hazard opportunity diagnostic",
        "",
        "```text",
        f"family                 {evidence['family_id']}",
        f"exact head             {evidence['exact_head']}",
        "candidate/grid         0/0",
        "fixed targets          AVAX-USDT / DOT-USDT independently",
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
            "Episode parsing, features, base labels and delayed labels use only "
            "the training prefix. The sealed interval `[10800,23760)` and unread "
            "suffix `[23760,24144)` are not parsed for performance.",
            "",
            "## Training information results",
            "",
            "| Target | N | Episodes | Distinct | IQR | Net rho | Net slope | "
            "Net tercile | Adverse rho | Adverse slope | Adverse tercile |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for target in evidence["targets"]:
        support = target["opportunity_support"]
        stats = target["statistics"]
        episodes = target["episode_evidence"]["duration_summary"]
        lines.append(
            f"| {target['instrument']} | {support['valid_opportunities']} | "
            f"{episodes['completed_episode_count']} | "
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
            f"share {breadth['largest_positive_net_fold_share']:.2%}. Delayed "
            f"net/adverse tercile effects "
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
        "accept_causal_own_price_drawdown_recovery_hazard_information_premise_"
        "1h_v1_for_separate_candidate_predeclaration"
        if bilateral_pass
        else "reject_causal_own_price_drawdown_recovery_hazard_information_premise_1h_v1"
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
            "Age-conditioned peak recovery did not provide bilateral, broad, "
            "dependence-supported continuation and downside information."
            if not bilateral_pass
            else "An executable candidate still requires separate zero-grid preregistration "
            "and untouched OOS evaluation."
        ),
        "next_strategy_experiment": (
            "causal-own-price-barrier-resolution-imbalance-opportunity-1h-v1"
            if not bilateral_pass
            else "causal-own-price-drawdown-recovery-hazard-candidate-1h-v1"
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
