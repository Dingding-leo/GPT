#!/usr/bin/env python3
"""Deterministic real-data reproducer for issue #617.

Uses immutable public OKX SPOT confirmed 1H CSV artifacts only.
No network, credentials, accounts, private endpoints, orders, leverage,
synthetic data, or 15m data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

CONFIG = {
    "family_id": "weekly-phase-conditioned-trend-carry-1h-v1",
    "issue": 617,
    "research_parent": "5a0fcc97d1a882f8223656c51f5bb8055f534e38",
    "fee_one_way": 0.0005,
    "warmup": [0, 2880],
    "training": [2880, 17520],
    "oos": [17520, 43440],
    "required_rows": 43442,
    "fold_hours": 2160,
    "fold_count": 12,
    "fourier_harmonics": 3,
    "favourable_weekdays": 2,
    "min_hold_hours": 168,
    "bootstrap": {
        "resamples": 5000,
        "block_hours": 168,
        "seed": 20260729,
        "confidence": 0.95,
    },
}
WEEKDAYS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


def load_prefix(path: str, expected_hash: str) -> tuple[pd.DataFrame, str]:
    data = Path(path).read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    assert sha == expected_hash, (sha, expected_hash)

    frame = pd.read_csv(path, nrows=CONFIG["required_rows"])
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    assert len(frame) == CONFIG["required_rows"]
    assert frame["confirm"].eq(1).all()
    assert frame["timestamp"].is_monotonic_increasing
    assert frame["timestamp"].is_unique
    assert frame["timestamp"].diff().dropna().eq(pd.Timedelta(hours=1)).all()

    for column in ["open", "high", "low", "close"]:
        values = frame[column].to_numpy(float)
        assert np.isfinite(values).all()
        assert (values > 0).all()
    return frame, sha


def design_matrix(hours: np.ndarray, harmonics: int = 3) -> np.ndarray:
    phase = np.asarray(hours, dtype=float)
    columns = [np.ones_like(phase)]
    for harmonic in range(1, harmonics + 1):
        angle = 2 * np.pi * harmonic * phase / 168.0
        columns.extend([np.sin(angle), np.cos(angle)])
    return np.column_stack(columns)


def fit_model(frame: pd.DataFrame) -> dict[str, object]:
    start, end = CONFIG["training"]
    indices = np.arange(start, end - 2)
    close = frame["close"].to_numpy(float)
    open_price = frame["open"].to_numpy(float)
    slow_trend = np.log(close[indices] / close[indices - 2160])
    valid = indices[slow_trend > 0]
    target = np.log(open_price[valid + 2] / open_price[valid + 1])

    execution_timestamps = frame["timestamp"].iloc[valid + 1]
    hour_of_week = (
        execution_timestamps.dt.weekday.to_numpy() * 24 + execution_timestamps.dt.hour.to_numpy()
    ).astype(int)
    matrix = design_matrix(hour_of_week, CONFIG["fourier_harmonics"])
    coefficients = np.linalg.lstsq(matrix, target, rcond=None)[0]
    profile = design_matrix(np.arange(168), CONFIG["fourier_harmonics"]) @ coefficients

    weekday_scores = []
    weekday_phase_hours = []
    for weekday in range(7):
        phase_hours = (np.arange(weekday * 24 + 1, weekday * 24 + 25) % 168).astype(int)
        weekday_phase_hours.append(phase_hours.tolist())
        weekday_scores.append(float(profile[phase_hours].sum()))

    ordered_weekdays = sorted(range(7), key=lambda weekday: (-weekday_scores[weekday], weekday))
    favourable = ordered_weekdays[: CONFIG["favourable_weekdays"]]
    return {
        "support": int(len(valid)),
        "coefficients": [float(value) for value in coefficients],
        "profile": [float(value) for value in profile],
        "weekday_scores": [float(value) for value in weekday_scores],
        "weekday_phase_hours": weekday_phase_hours,
        "favourable_weekday_indices": [int(value) for value in favourable],
        "favourable_weekdays": [WEEKDAYS[value] for value in favourable],
        "training_target_mean": float(target.mean()),
        "training_target_std": float(target.std(ddof=1)),
    }


def open_to_open_returns(frame: pd.DataFrame) -> np.ndarray:
    open_price = frame["open"].to_numpy(float)
    return open_price[2:] / open_price[1:-1] - 1


def trend_positions(frame: pd.DataFrame, daily: bool) -> np.ndarray:
    length = len(frame) - 2
    close = frame["close"].to_numpy(float)
    positions = np.zeros(length)
    current = 0
    for index in range(length):
        is_decision = not daily or frame["timestamp"].iloc[index].hour == 0
        if index >= 2160 and is_decision:
            current = int(np.log(close[index] / close[index - 2160]) > 0)
        positions[index] = current
    return positions


def candidate_positions(frame: pd.DataFrame, favourable_weekdays: list[int]) -> np.ndarray:
    length = len(frame) - 2
    close = frame["close"].to_numpy(float)
    positions = np.zeros(length)
    current = 0
    entry_index = None

    for index in range(length):
        if index >= 2160 and frame["timestamp"].iloc[index].hour == 0:
            trend = np.log(close[index] / close[index - 2160])
            weekday = int(frame["timestamp"].iloc[index].weekday())
            if current == 0 and trend > 0 and weekday in favourable_weekdays:
                current = 1
                entry_index = index
            elif (
                current == 1
                and entry_index is not None
                and index - entry_index >= CONFIG["min_hold_hours"]
                and trend <= 0
            ):
                current = 0
                entry_index = None
        positions[index] = current
    return positions


def net_series(positions: np.ndarray, gross_returns: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    changes = np.abs(np.diff(np.r_[0.0, positions]))
    net_returns = positions * gross_returns - CONFIG["fee_one_way"] * changes
    return net_returns, changes


def annualised_sharpe(values: np.ndarray) -> float | None:
    series = np.asarray(values, dtype=float)
    standard_deviation = series.std(ddof=1)
    if len(series) < 2 or standard_deviation == 0 or not np.isfinite(standard_deviation):
        return None
    return float(series.mean() / standard_deviation * np.sqrt(8760))


def segment_metrics(
    net_returns: np.ndarray,
    positions: np.ndarray,
    changes: np.ndarray,
    start: int,
    end: int,
) -> dict[str, float | int | None]:
    segment = net_returns[start:end]
    segment_positions = positions[start:end]
    segment_changes = changes[start:end]
    wealth = np.cumprod(1 + segment)
    peak = np.maximum.accumulate(np.r_[1.0, wealth])
    drawdown = np.r_[1.0, wealth] / peak - 1
    turnover = float(segment_changes.sum())
    transitions = np.diff(np.r_[0.0, positions])
    return {
        "net_return": float(wealth[-1] - 1),
        "sharpe": annualised_sharpe(segment),
        "max_drawdown": float(drawdown.min()),
        "turnover": turnover,
        "fees": float(turnover * CONFIG["fee_one_way"]),
        "edge_per_turnover_bps": (
            float(segment.sum() / turnover * 10000) if turnover > 0 else None
        ),
        "exposure": float(segment_positions.mean()),
        "arithmetic_net_sum": float(segment.sum()),
        "entries": int(((transitions > 0)[start:end]).sum()),
        "exits": int(((transitions < 0)[start:end]).sum()),
    }


def breadth(
    frame: pd.DataFrame,
    net_returns: np.ndarray,
    positions: np.ndarray,
    changes: np.ndarray,
) -> dict[str, object]:
    start, end = CONFIG["oos"]
    fold_returns = []
    for fold_index in range(CONFIG["fold_count"]):
        fold_start = start + fold_index * CONFIG["fold_hours"]
        fold_end = fold_start + CONFIG["fold_hours"]
        metrics = segment_metrics(net_returns, positions, changes, fold_start, fold_end)
        fold_returns.append(metrics["net_return"])

    positive_folds = [value for value in fold_returns if value > 0]
    concentration = max(positive_folds) / sum(positive_folds) if positive_folds else None
    execution_timestamps = frame["timestamp"].iloc[1 : len(net_returns) + 1].reset_index(drop=True)
    years = {}
    all_indices = np.arange(len(net_returns))
    for year in sorted(execution_timestamps.iloc[start:end].dt.year.unique()):
        year_indices = np.flatnonzero(
            (execution_timestamps.dt.year.to_numpy() == year)
            & (all_indices >= start)
            & (all_indices < end)
        )
        if len(year_indices) > 0:
            year_returns = net_returns[year_indices]
            years[str(int(year))] = float(np.prod(1 + year_returns) - 1)

    return {
        "fold_returns": fold_returns,
        "profitable_folds": int(sum(value > 0 for value in fold_returns)),
        "positive_fold_concentration": (
            float(concentration) if concentration is not None else None
        ),
        "year_returns": years,
        "profitable_years": int(sum(value > 0 for value in years.values())),
    }


def residual_sharpe(
    candidate: np.ndarray, comparator: np.ndarray, start: int, end: int
) -> float | None:
    return annualised_sharpe(candidate[start:end] - comparator[start:end])


def paired_bootstrap(candidate: np.ndarray, benchmark: np.ndarray) -> dict[str, list[float]]:
    start, end = CONFIG["oos"]
    candidate_oos = candidate[start:end]
    benchmark_oos = benchmark[start:end]
    sample_size = len(candidate_oos)
    block_size = CONFIG["bootstrap"]["block_hours"]
    block_count = math.ceil(sample_size / block_size)
    rng = np.random.default_rng(CONFIG["bootstrap"]["seed"])
    mean_deltas = np.empty(CONFIG["bootstrap"]["resamples"])
    sharpe_deltas = np.empty_like(mean_deltas)

    for resample_index in range(len(mean_deltas)):
        starts = rng.integers(0, sample_size - block_size + 1, size=block_count)
        indices = np.concatenate([np.arange(value, value + block_size) for value in starts])[
            :sample_size
        ]
        candidate_sample = candidate_oos[indices]
        benchmark_sample = benchmark_oos[indices]
        mean_deltas[resample_index] = (candidate_sample.mean() - benchmark_sample.mean()) * 8760
        candidate_sharpe = annualised_sharpe(candidate_sample)
        benchmark_sharpe = annualised_sharpe(benchmark_sample)
        sharpe_deltas[resample_index] = (0.0 if candidate_sharpe is None else candidate_sharpe) - (
            0.0 if benchmark_sharpe is None else benchmark_sharpe
        )

    quantiles = [0.025, 0.5, 0.975]
    return {
        "annualised_mean_delta_quantiles": [
            float(value) for value in np.quantile(mean_deltas, quantiles)
        ],
        "sharpe_delta_quantiles": [float(value) for value in np.quantile(sharpe_deltas, quantiles)],
    }


def rank_values(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=float)
    ranks[order] = np.arange(len(values))
    return ranks


def phase_persistence(frame: pd.DataFrame, model: dict[str, object]) -> dict[str, object]:
    close = frame["close"].to_numpy(float)
    open_price = frame["open"].to_numpy(float)
    start, end = CONFIG["oos"]
    weekday_values = {weekday: [] for weekday in range(7)}

    for index in range(start, end - 25):
        if frame["timestamp"].iloc[index].hour != 0:
            continue
        if np.log(close[index] / close[index - 2160]) <= 0:
            continue
        weekday = int(frame["timestamp"].iloc[index].weekday())
        realised = np.log(open_price[index + 25] / open_price[index + 1])
        weekday_values[weekday].append(float(realised))

    means = np.array(
        [
            np.mean(weekday_values[weekday]) if weekday_values[weekday] else np.nan
            for weekday in range(7)
        ]
    )
    scores = np.asarray(model["weekday_scores"], dtype=float)
    valid = np.isfinite(means)
    pearson = float(np.corrcoef(scores[valid], means[valid])[0, 1]) if valid.sum() > 1 else None
    spearman = (
        float(np.corrcoef(rank_values(scores[valid]), rank_values(means[valid]))[0, 1])
        if valid.sum() > 1
        else None
    )
    realised_order = sorted(range(7), key=lambda weekday: (-means[weekday], weekday))
    frozen = set(model["favourable_weekday_indices"])
    realised_top = set(realised_order[:2])
    return {
        "oos_positive_trend_daily_support": [len(weekday_values[weekday]) for weekday in range(7)],
        "oos_realised_24h_log_return_mean": [float(value) for value in means],
        "pearson_training_model_vs_oos": pearson,
        "spearman_training_model_vs_oos": spearman,
        "frozen_top2_overlap_with_oos_top2": len(frozen & realised_top),
        "oos_top2_indices": realised_order[:2],
        "oos_top2_weekdays": [WEEKDAYS[value] for value in realised_order[:2]],
        "frozen_selected_mean": float(np.nanmean([means[value] for value in frozen])),
        "unselected_mean": float(
            np.nanmean([means[value] for value in range(7) if value not in frozen])
        ),
    }


def holding_periods(positions: np.ndarray) -> dict[str, float | int | None]:
    transitions = np.diff(np.r_[0.0, positions, 0.0])
    starts = np.flatnonzero(transitions > 0)
    ends = np.flatnonzero(transitions < 0)
    durations = (ends - starts).astype(int)
    return {
        "count": int(len(durations)),
        "mean_hours": float(durations.mean()) if len(durations) else None,
        "median_hours": float(np.median(durations)) if len(durations) else None,
        "min_hours": int(durations.min()) if len(durations) else None,
        "max_hours": int(durations.max()) if len(durations) else None,
    }


def policy_metrics(
    net_returns: np.ndarray,
    positions: np.ndarray,
    changes: np.ndarray,
) -> dict[str, dict[str, float | int | None]]:
    metrics = {
        segment: segment_metrics(net_returns, positions, changes, *CONFIG[segment])
        for segment in ["training", "oos"]
    }
    metrics["full"] = segment_metrics(
        net_returns,
        positions,
        changes,
        CONFIG["training"][0],
        CONFIG["oos"][1],
    )
    return metrics


def acceptance_gates(
    candidate_oos: dict[str, float | int | None],
    benchmark_oos: dict[str, float | int | None],
    breadth_result: dict[str, object],
    residual_b0: float | None,
    residual_b1: float | None,
    bootstrap_result: dict[str, list[float]],
) -> dict[str, bool]:
    candidate_sharpe = candidate_oos["sharpe"]
    benchmark_sharpe = benchmark_oos["sharpe"]
    candidate_edge = candidate_oos["edge_per_turnover_bps"]
    benchmark_edge = benchmark_oos["edge_per_turnover_bps"]
    concentration = breadth_result["positive_fold_concentration"]
    return {
        "positive_net_return": candidate_oos["net_return"] > 0,
        "finite_sharpe_and_exceeds_b1": (
            candidate_sharpe is not None
            and benchmark_sharpe is not None
            and candidate_sharpe > benchmark_sharpe
        ),
        "edge_per_turnover_exceeds_b1": (
            candidate_edge is not None
            and benchmark_edge is not None
            and candidate_edge > benchmark_edge
        ),
        "max_drawdown_no_worse_than_b1": (
            candidate_oos["max_drawdown"] >= benchmark_oos["max_drawdown"]
        ),
        "long_entries_at_least_8": candidate_oos["entries"] >= 8,
        "profitable_folds_at_least_7_of_12": (breadth_result["profitable_folds"] >= 7),
        "profitable_year_segments_at_least_3": (breadth_result["profitable_years"] >= 3),
        "positive_fold_concentration_at_most_50pct": (
            concentration is not None and concentration <= 0.5
        ),
        "positive_residual_sharpe_vs_b0": (residual_b0 is not None and residual_b0 > 0),
        "positive_residual_sharpe_vs_b1": (residual_b1 is not None and residual_b1 > 0),
        "bootstrap_mean_delta_lower_bound_positive": (
            bootstrap_result["annualised_mean_delta_quantiles"][0] > 0
        ),
        "bootstrap_sharpe_delta_lower_bound_positive": (
            bootstrap_result["sharpe_delta_quantiles"][0] > 0
        ),
        "hash_chronology_timing_fee_checks": True,
    }


def run(btc_csv: str, eth_csv: str) -> dict[str, object]:
    sources = {
        "BTC-USDT": (
            btc_csv,
            "92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9",
            8704977298,
        ),
        "ETH-USDT": (
            eth_csv,
            "2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726",
            8704978112,
        ),
    }
    result = {
        "family_id": CONFIG["family_id"],
        "issue": CONFIG["issue"],
        "accepted": True,
        "candidate_count": 1,
        "parameter_grid_count": 0,
        "canonical_fee_one_way": CONFIG["fee_one_way"],
        "markets": {},
        "verdict": None,
    }

    for instrument, (path, expected_hash, artifact_id) in sources.items():
        frame, source_hash = load_prefix(path, expected_hash)
        model = fit_model(frame)
        gross_returns = open_to_open_returns(frame)
        candidate_position = candidate_positions(frame, model["favourable_weekday_indices"])
        b0_position = trend_positions(frame, daily=False)
        b1_position = trend_positions(frame, daily=True)
        candidate_net, candidate_changes = net_series(candidate_position, gross_returns)
        b0_net, b0_changes = net_series(b0_position, gross_returns)
        b1_net, b1_changes = net_series(b1_position, gross_returns)

        policies = {
            "candidate": policy_metrics(candidate_net, candidate_position, candidate_changes),
            "b0_hourly_2160h_trend": policy_metrics(b0_net, b0_position, b0_changes),
            "b1_daily_2160h_trend": policy_metrics(b1_net, b1_position, b1_changes),
        }
        breadth_result = breadth(frame, candidate_net, candidate_position, candidate_changes)
        residual_b0 = residual_sharpe(candidate_net, b0_net, *CONFIG["oos"])
        residual_b1 = residual_sharpe(candidate_net, b1_net, *CONFIG["oos"])
        bootstrap_result = paired_bootstrap(candidate_net, b1_net)
        persistence = phase_persistence(frame, model)
        gates = acceptance_gates(
            policies["candidate"]["oos"],
            policies["b1_daily_2160h_trend"]["oos"],
            breadth_result,
            residual_b0,
            residual_b1,
            bootstrap_result,
        )
        accepted = all(gates.values())
        result["accepted"] = result["accepted"] and accepted
        result["markets"][instrument] = {
            "source": {
                "artifact_id": artifact_id,
                "csv_sha256": source_hash,
                "rows_loaded": len(frame),
                "later_suffix_unread": True,
            },
            "model": model,
            "policies": policies,
            "breadth": breadth_result,
            "residual_sharpe": {"vs_b0": residual_b0, "vs_b1": residual_b1},
            "bootstrap_vs_b1": bootstrap_result,
            "phase_persistence": persistence,
            "holding_periods": holding_periods(candidate_position),
            "acceptance_gates": gates,
            "accepted": accepted,
        }

    result["verdict"] = (
        "accept_weekly_phase_conditioned_trend_carry"
        if result["accepted"]
        else "reject_exact_weekly_phase_conditioned_trend_carry_family"
    )
    result["discrepancy_repair"] = {
        "initial_issue": (
            "The first phase-persistence diagnostic grouped all OOS weekdays, "
            "although the frozen Fourier model was fitted only on hours whose "
            "2160H slow trend was positive."
        ),
        "repair": (
            "Condition the OOS 24H weekday-persistence diagnostic on the "
            "identical positive-2160H-trend state and rerun the complete experiment."
        ),
        "strategy_outputs_changed": False,
        "metrics_changed": False,
        "diagnostic_only": True,
    }
    result["exact_head_gates"] = {
        "status": "not_yet_available",
        "note": "Populate from GitHub after evidence publication.",
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--btc-csv", required=True)
    parser.add_argument("--eth-csv", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    result = run(args.btc_csv, args.eth_csv)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    summary = {
        "verdict": result["verdict"],
        "BTC-USDT": result["markets"]["BTC-USDT"]["policies"]["candidate"]["oos"],
        "ETH-USDT": result["markets"]["ETH-USDT"]["policies"]["candidate"]["oos"],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
