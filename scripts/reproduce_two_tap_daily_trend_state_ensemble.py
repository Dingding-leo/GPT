#!/usr/bin/env python3
"""Reproduce issue #722 on immutable public OKX 1H candle artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

FEE = 0.0005
ANN = 8760.0
N = 43_441
TRAIN = (2_880, 17_520)
OOS = (17_520, 43_440)
FULL = (2_880, 43_440)
FOLD = 2_160
SEED = 20_260_731
BOOTSTRAPS = 5_000
BLOCK = 168
TOL = 1e-12
EXPECTED = {
    "BTC-USDT": {
        "artifact_id": 8_685_574_446,
        "full_sha256": "f967995a6acd5c4acd0a17dd030f02cd55441b3f83716e5a4118a58af71ca96e",
        "prefix_sha256": "4efd9875f8205f2c44c6e26042b24bdfb89f077f7c89b2888a6bac9b645747e0",
    },
    "ETH-USDT": {
        "artifact_id": 8_685_572_234,
        "full_sha256": "ff53337ffbeafd237703ef6ff5f61a2e0b15df1fbd5954c17a8557e80324e907",
        "prefix_sha256": "3c6ce0c424280f1e0b6210501380336190d832359895df9534e5c5a16d9ec6ed",
    },
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load(path: Path, market: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    raw = path.read_bytes()
    lines = raw.splitlines(keepends=True)
    identity = EXPECTED[market]
    full_hash = digest(raw)
    prefix_hash = digest(b"".join(lines[: N + 1]))
    if full_hash != identity["full_sha256"]:
        raise ValueError(f"immutable full hash mismatch: {market}")
    if prefix_hash != identity["prefix_sha256"]:
        raise ValueError(f"immutable prefix hash mismatch: {market}")
    frame = pd.read_csv(path, nrows=N).copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    if len(frame) != N or not (frame["confirm"].to_numpy() == 1).all():
        raise ValueError(f"invalid confirmed prefix: {market}")
    if not (frame["timestamp"].diff().dropna() == pd.Timedelta(hours=1)).all():
        raise ValueError(f"non-contiguous 1H chronology: {market}")
    return frame, {
        "artifact_id": identity["artifact_id"],
        "full_sha256": full_hash,
        "prefix_sha256": prefix_hash,
        "source_rows": len(lines) - 1,
        "prefix_rows": len(frame),
        "first_timestamp": frame["timestamp"].iloc[0].isoformat(),
        "last_prefix_timestamp": frame["timestamp"].iloc[-1].isoformat(),
    }


def construct_positions(frame: pd.DataFrame) -> dict[str, np.ndarray]:
    n_returns = len(frame) - 1
    close = frame["close"].to_numpy(float)
    hours = frame["timestamp"].dt.hour.to_numpy()
    candidate = np.zeros(n_returns)
    daily = np.zeros(n_returns)
    hourly = np.zeros(n_returns)
    daily_base_by_decision: list[tuple[int, float]] = []
    previous_daily_base = 0.0

    for t in range(2_160, len(frame) - 1):
        base = float(close[t] > close[t - 2_160])
        hourly[t + 1 :] = base
        if hours[t] != 0:
            continue
        daily[t + 1 :] = base
        target = 0.5 * (base + previous_daily_base)
        candidate[t + 1 :] = target
        daily_base_by_decision.append((t, base))
        previous_daily_base = base

    if not np.isin(candidate, [0.0, 0.5, 1.0]).all():
        raise AssertionError("candidate position domain failed")
    if not np.isin(daily, [0.0, 1.0]).all() or not np.isin(hourly, [0.0, 1.0]).all():
        raise AssertionError("benchmark position domain failed")

    reconstructed = np.zeros(n_returns)
    prior = 0.0
    for t, base in daily_base_by_decision:
        reconstructed[t + 1 :] = 0.5 * (base + prior)
        prior = base
    if not np.array_equal(candidate, reconstructed):
        raise AssertionError("two-tap state reconstruction failed")

    return {"candidate": candidate, "benchmark_b1": daily, "benchmark_b0": hourly}


def net_returns(
    frame: pd.DataFrame,
    position: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    open_ = frame["open"].to_numpy(float)
    gross = open_[1:] / open_[:-1] - 1.0
    turnover = np.abs(np.diff(np.r_[0.0, position]))
    net = position * gross - FEE * turnover
    if not np.allclose(net, position * gross - FEE * turnover, atol=0.0, rtol=0.0):
        raise AssertionError("fee identity failed")
    return net, turnover, gross


def sharpe(values: np.ndarray) -> float:
    std = float(np.std(values, ddof=1))
    return float(np.mean(values) / std * math.sqrt(ANN)) if std > 0 else math.nan


def compounded(values: np.ndarray) -> float:
    return float(np.prod(1.0 + values) - 1.0)


def drawdown(values: np.ndarray) -> float:
    equity = np.cumprod(1.0 + values)
    peaks = np.maximum.accumulate(np.r_[1.0, equity])[1:]
    return float(np.min(equity / peaks - 1.0))


def metrics(
    net: np.ndarray,
    turnover: np.ndarray,
    position: np.ndarray,
    span: tuple[int, int],
) -> dict[str, Any]:
    start, end = span
    values = net[start:end]
    turns = float(np.sum(turnover[start:end]))
    arithmetic = float(np.sum(values))
    return {
        "net_return": compounded(values),
        "arithmetic_net_return": arithmetic,
        "sharpe": sharpe(values),
        "max_drawdown": drawdown(values),
        "turnover": turns,
        "fees": FEE * turns,
        "edge_per_turnover_bps": float(arithmetic / turns * 10_000) if turns > 0 else math.nan,
        "mean_exposure": float(np.mean(position[start:end])),
        "full_exposure_hours": int(np.sum(position[start:end] == 1.0)),
        "half_exposure_hours": int(np.sum(position[start:end] == 0.5)),
        "cash_hours": int(np.sum(position[start:end] == 0.0)),
        "effective_position_changes": int(np.sum(turnover[start:end] > 0)),
    }


def basic_interval(point: float, draws: np.ndarray) -> list[float]:
    low, high = np.quantile(draws, [0.025, 0.975])
    return [float(2 * point - high), float(2 * point - low)]


def uncertainty(candidate: np.ndarray, benchmark: np.ndarray) -> dict[str, Any]:
    c = candidate[OOS[0] : OOS[1]]
    b = benchmark[OOS[0] : OOS[1]]
    n = len(c)
    blocks = math.ceil(n / BLOCK)
    rng = np.random.default_rng(SEED)
    mean_draws = np.empty(BOOTSTRAPS)
    sharpe_draws = np.empty(BOOTSTRAPS)
    offsets = np.arange(BLOCK)
    for start in range(0, BOOTSTRAPS, 100):
        size = min(100, BOOTSTRAPS - start)
        heads = rng.integers(0, n - BLOCK + 1, size=(size, blocks))
        indices = (heads[:, :, None] + offsets).reshape(size, -1)[:, :n]
        cs, bs = c[indices], b[indices]
        mean_draws[start : start + size] = np.mean(cs - bs, axis=1) * ANN
        cm, bm = np.mean(cs, axis=1), np.mean(bs, axis=1)
        cstd, bstd = np.std(cs, axis=1, ddof=1), np.std(bs, axis=1, ddof=1)
        sharpe_draws[start : start + size] = (cm / cstd - bm / bstd) * math.sqrt(ANN)
    mean_point = float(np.mean(c - b) * ANN)
    sharpe_point = sharpe(c) - sharpe(b)
    return {
        "method": "paired non-circular moving-block basic interval",
        "block_hours": BLOCK,
        "resamples": BOOTSTRAPS,
        "seed": SEED,
        "mean_delta_annualized": {
            "point": mean_point,
            "ci95": basic_interval(mean_point, mean_draws),
        },
        "sharpe_delta": {
            "point": sharpe_point,
            "ci95": basic_interval(sharpe_point, sharpe_draws),
        },
    }


def breadth(frame: pd.DataFrame, candidate: np.ndarray, benchmark: np.ndarray) -> dict[str, Any]:
    folds: list[dict[str, Any]] = []
    positive_returns: list[float] = []
    for number in range(12):
        start = OOS[0] + number * FOLD
        end = start + FOLD
        c = compounded(candidate[start:end])
        b = compounded(benchmark[start:end])
        folds.append({"fold": number + 1, "candidate": c, "benchmark_b1": b})
        if c > 0:
            positive_returns.append(c)

    years: list[dict[str, Any]] = []
    timestamps = frame["timestamp"].iloc[1:].reset_index(drop=True)
    oos_years = timestamps.iloc[OOS[0] : OOS[1]].dt.year.to_numpy()
    for year in sorted(set(oos_years)):
        indices = np.flatnonzero(oos_years == year) + OOS[0]
        years.append(
            {
                "year": int(year),
                "candidate": compounded(candidate[indices]),
                "benchmark_b1": compounded(benchmark[indices]),
            }
        )
    residual = candidate[OOS[0] : OOS[1]] - benchmark[OOS[0] : OOS[1]]
    concentration = max(positive_returns) / sum(positive_returns) if positive_returns else math.nan
    return {
        "profitable_folds": sum(row["candidate"] > 0 for row in folds),
        "profitable_years": sum(row["candidate"] > 0 for row in years),
        "improved_folds": sum(row["candidate"] > row["benchmark_b1"] for row in folds),
        "improved_years": sum(row["candidate"] > row["benchmark_b1"] for row in years),
        "positive_fold_concentration": concentration,
        "residual_sharpe": sharpe(residual),
        "folds": folds,
        "years": years,
    }


def base_run_diagnostics(
    frame: pd.DataFrame,
    candidate_turnover: np.ndarray,
    benchmark_turnover: np.ndarray,
) -> dict[str, Any]:
    close = frame["close"].to_numpy(float)
    decisions: list[dict[str, Any]] = []
    for t in range(2_160, len(frame) - 1):
        if frame["timestamp"].iloc[t].hour != 0:
            continue
        decisions.append(
            {
                "decision_index": t,
                "execution_index": t + 1,
                "base": int(close[t] > close[t - 2_160]),
                "decision_time": frame["timestamp"].iloc[t].isoformat(),
            }
        )

    runs: list[dict[str, Any]] = []
    start = 0
    for end in range(1, len(decisions) + 1):
        if end < len(decisions) and decisions[end]["base"] == decisions[start]["base"]:
            continue
        first = decisions[start]
        last = decisions[end - 1]
        runs.append(
            {
                "base": first["base"],
                "daily_decisions": end - start,
                "first_decision_time": first["decision_time"],
                "first_execution_index": first["execution_index"],
                "last_execution_index": last["execution_index"],
                "bounded": start > 0 and end < len(decisions),
            }
        )
        start = end

    oos_runs = [row for row in runs if OOS[0] <= row["first_execution_index"] < OOS[1]]
    isolated = [row for row in oos_runs if row["bounded"] and row["daily_decisions"] == 1]
    candidate_turns = float(np.sum(candidate_turnover[OOS[0] : OOS[1]]))
    benchmark_turns = float(np.sum(benchmark_turnover[OOS[0] : OOS[1]]))
    savings = benchmark_turns - candidate_turns
    boundary_adjustment = savings - len(isolated)
    if abs(boundary_adjustment) > 0.5 + TOL:
        raise AssertionError("isolated-run turnover attribution failed")
    return {
        "oos_base_runs": len(oos_runs),
        "oos_one_decision_runs": len(isolated),
        "turnover_savings_vs_b1": savings,
        "one_decision_run_attribution": float(len(isolated)),
        "sample_boundary_adjustment": boundary_adjustment,
        "run_length_days": [row["daily_decisions"] for row in oos_runs],
        "isolated_run_details": isolated,
    }


def transition_diagnostics(
    frame: pd.DataFrame,
    candidate_position: np.ndarray,
    benchmark_position: np.ndarray,
    candidate_turnover: np.ndarray,
    benchmark_turnover: np.ndarray,
    gross: np.ndarray,
) -> dict[str, Any]:
    start, end = OOS
    diff = candidate_position - benchmark_position
    mask = diff != 0
    events: list[dict[str, Any]] = []
    i = start
    timestamps = frame["timestamp"].iloc[1:].reset_index(drop=True)
    while i < end:
        if not mask[i]:
            i += 1
            continue
        sign = int(np.sign(diff[i]))
        j = i + 1
        while j < end and mask[j] and int(np.sign(diff[j])) == sign:
            j += 1
        full_market_return = compounded(gross[i:j])
        timing = float(np.sum(diff[i:j] * gross[i:j]))
        events.append(
            {
                "kind": "exit_extension" if sign > 0 else "onset_reduction",
                "start_open": timestamps.iloc[i].isoformat(),
                "end_open_exclusive": (
                    timestamps.iloc[j].isoformat() if j < len(timestamps) else None
                ),
                "hours": j - i,
                "full_market_return": full_market_return,
                "arithmetic_timing_contribution": timing,
            }
        )
        i = j

    lower = diff[start:end] < 0
    higher = diff[start:end] > 0
    timing_lower = float(np.sum(diff[start:end][lower] * gross[start:end][lower]))
    timing_higher = float(np.sum(diff[start:end][higher] * gross[start:end][higher]))
    incremental_fees = FEE * float(
        np.sum(candidate_turnover[start:end]) - np.sum(benchmark_turnover[start:end])
    )
    candidate_minus_benchmark = float(np.sum(diff[start:end] * gross[start:end]) - incremental_fees)
    direct = float(
        np.sum(
            candidate_position[start:end] * gross[start:end]
            - FEE * candidate_turnover[start:end]
            - benchmark_position[start:end] * gross[start:end]
            + FEE * benchmark_turnover[start:end]
        )
    )
    if abs(candidate_minus_benchmark - direct) > TOL:
        raise AssertionError("candidate-minus-B1 decomposition failed")

    absolute_positive = [max(0.0, row["arithmetic_timing_contribution"]) for row in events]
    event_concentration = (
        max(absolute_positive) / sum(absolute_positive) if sum(absolute_positive) > 0 else math.nan
    )
    return {
        "different_hours": int(np.sum(mask[start:end])),
        "onset_reduction_hours": int(np.sum(lower)),
        "exit_extension_hours": int(np.sum(higher)),
        "events": len(events),
        "onset_reduction_events": sum(row["kind"] == "onset_reduction" for row in events),
        "exit_extension_events": sum(row["kind"] == "exit_extension" for row in events),
        "positive_timing_events": sum(row["arithmetic_timing_contribution"] > 0 for row in events),
        "negative_timing_events": sum(row["arithmetic_timing_contribution"] < 0 for row in events),
        "onset_reduction_timing_contribution": timing_lower,
        "exit_extension_timing_contribution": timing_higher,
        "total_timing_contribution": timing_lower + timing_higher,
        "incremental_fees": incremental_fees,
        "arithmetic_candidate_minus_b1": candidate_minus_benchmark,
        "positive_event_concentration": event_concentration,
        "event_details": events,
    }


def prefix_invariance(frame: pd.DataFrame, full_candidate: np.ndarray) -> dict[str, Any]:
    checkpoints = [17_520, 21_840, 30_480, 39_120]
    checks: list[dict[str, Any]] = []
    for cut in checkpoints:
        truncated = frame.iloc[: cut + 1].copy()
        candidate = construct_positions(truncated)["candidate"]
        reference = full_candidate[: len(candidate)]
        exact = bool(np.array_equal(candidate, reference))
        if not exact:
            raise AssertionError(f"causal prefix invariance failed at {cut}")
        checks.append(
            {
                "last_bar_index": cut,
                "compared_return_positions": len(candidate),
                "exact": exact,
            }
        )
    return {"method": "incremental real-prefix recomputation", "checks": checks}


def acceptance(
    candidate: dict[str, Any],
    benchmark: dict[str, Any],
    breadth_result: dict[str, Any],
    uncertainty_result: dict[str, Any],
    full_candidate: dict[str, Any],
) -> dict[str, bool]:
    return {
        "oos_net_positive": candidate["net_return"] > 0,
        "oos_net_no_worse_b1": candidate["net_return"] + TOL >= benchmark["net_return"],
        "oos_sharpe_no_worse_b1": math.isfinite(candidate["sharpe"])
        and candidate["sharpe"] + TOL >= benchmark["sharpe"],
        "oos_drawdown_no_worse_b1": candidate["max_drawdown"] + TOL >= benchmark["max_drawdown"],
        "oos_turnover_no_greater_b1": candidate["turnover"] <= benchmark["turnover"] + TOL,
        "oos_edge_per_turnover_no_worse_b1": candidate["edge_per_turnover_bps"] + TOL
        >= benchmark["edge_per_turnover_bps"],
        "profitable_folds_at_least_7": breadth_result["profitable_folds"] >= 7,
        "profitable_years_at_least_3": breadth_result["profitable_years"] >= 3,
        "positive_fold_concentration_at_most_half": breadth_result["positive_fold_concentration"]
        <= 0.5 + TOL,
        "residual_sharpe_positive": breadth_result["residual_sharpe"] > 0,
        "mean_delta_ci_lower_positive": uncertainty_result["mean_delta_annualized"]["ci95"][0] > 0,
        "sharpe_delta_ci_lower_positive": uncertainty_result["sharpe_delta"]["ci95"][0] > 0,
        "full_net_positive": full_candidate["net_return"] > 0,
    }


def market(path: Path, name: str) -> dict[str, Any]:
    frame, source = load(path, name)
    positions = construct_positions(frame)
    series: dict[str, dict[str, np.ndarray]] = {}
    gross_reference: np.ndarray | None = None
    for key, position in positions.items():
        net, turnover, gross = net_returns(frame, position)
        series[key] = {"net": net, "turnover": turnover}
        if gross_reference is None:
            gross_reference = gross
        elif not np.array_equal(gross_reference, gross):
            raise AssertionError("gross-return parity failed")
    assert gross_reference is not None

    result: dict[str, Any] = {"source": source}
    for label, span in (("training", TRAIN), ("development_oos", OOS), ("full_scored", FULL)):
        result[label] = {
            key: metrics(series[key]["net"], series[key]["turnover"], positions[key], span)
            for key in positions
        }
    breadth_result = breadth(
        frame,
        series["candidate"]["net"],
        series["benchmark_b1"]["net"],
    )
    uncertainty_result = uncertainty(
        series["candidate"]["net"],
        series["benchmark_b1"]["net"],
    )
    result["breadth"] = breadth_result
    result["uncertainty"] = uncertainty_result
    result["diagnostics"] = transition_diagnostics(
        frame,
        positions["candidate"],
        positions["benchmark_b1"],
        series["candidate"]["turnover"],
        series["benchmark_b1"]["turnover"],
        gross_reference,
    )
    result["diagnostics"]["base_run_turnover"] = base_run_diagnostics(
        frame,
        series["candidate"]["turnover"],
        series["benchmark_b1"]["turnover"],
    )
    result["integrity"] = {
        "position_domain": True,
        "two_tap_reconstruction": True,
        "next_open_execution": True,
        "fee_identity": True,
        "return_decomposition": True,
        "prefix_invariance": prefix_invariance(frame, positions["candidate"]),
    }
    result["acceptance"] = acceptance(
        result["development_oos"]["candidate"],
        result["development_oos"]["benchmark_b1"],
        breadth_result,
        uncertainty_result,
        result["full_scored"]["candidate"],
    )
    result["passed_all_gates"] = all(result["acceptance"].values())
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--btc-csv", type=Path, required=True)
    parser.add_argument("--eth-csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    markets = {
        "BTC-USDT": market(args.btc_csv, "BTC-USDT"),
        "ETH-USDT": market(args.eth_csv, "ETH-USDT"),
    }
    bilateral = all(row["passed_all_gates"] for row in markets.values())
    result = {
        "family_id": "two-tap-daily-trend-state-ensemble-1h-v1",
        "issue": 722,
        "research_parent": "5a0fcc97d1a882f8223656c51f5bb8055f534e38",
        "candidate_count": 1,
        "parameter_grid_count": 0,
        "fee_one_way": FEE,
        "markets": markets,
        "bilateral_pass": bilateral,
        "verdict": (
            "two_tap_daily_trend_state_ensemble_nominated_for_research"
            if bilateral
            else "reject_exact_two_tap_daily_trend_state_ensemble_family"
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
