#!/usr/bin/env python3
"""Frozen path-efficiency hysteresis 1H development experiment.

This script implements issue #593 exactly. It uses only immutable public OKX
1H candles, evaluates BTC-USDT and ETH-USDT independently, models exactly
5 bps one-way fees on actual position changes, and emits deterministic JSON.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ANNUALIZATION = 8760.0
FEE = 0.0005
WARMUP_END = 2880
TRAIN_END_EXCLUSIVE = 17520
OOS_END_EXCLUSIVE = 43440
FOLD_HOURS = 2160
BOOTSTRAP_BLOCK = 168
BOOTSTRAP_RESAMPLES = 5000
BOOTSTRAP_SEED = 20260729

EXPECTED = {
    "BTC-USDT": {
        "zip_sha256": "22d6d0e7f5dbffe4e746f091a5ab2488e3edc7d8440fea393ee2862295cf208c",
        "csv_sha256": "92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9",
        "artifact_id": 8704977298,
    },
    "ETH-USDT": {
        "zip_sha256": "e7107f83a4eb5059ada0bb2097aeb5ded976dc9c037f564538f5cf5b4a7dffe3",
        "csv_sha256": "2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726",
        "artifact_id": 8704978112,
    },
}


@dataclass(frozen=True)
class Paths:
    instrument: str
    zip_path: Path
    csv_path: Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def finite_float(value: float | np.floating[Any]) -> float | None:
    value = float(value)
    return value if math.isfinite(value) else None


def metrics(
    net: np.ndarray,
    gross: np.ndarray,
    turnover: np.ndarray,
    position: np.ndarray,
) -> dict[str, Any]:
    if not (len(net) == len(gross) == len(turnover) == len(position)):
        raise ValueError("metric arrays must have equal length")
    if len(net) == 0:
        raise ValueError("empty metric interval")
    equity = np.cumprod(1.0 + net)
    equity_with_origin = np.concatenate(([1.0], equity))
    peaks = np.maximum.accumulate(equity_with_origin)
    drawdown = equity_with_origin / peaks - 1.0
    std = float(np.std(net, ddof=1)) if len(net) > 1 else 0.0
    sharpe = (
        float(np.mean(net) / std * math.sqrt(ANNUALIZATION))
        if std > 0
        else math.nan
    )
    total_turnover = float(np.sum(turnover))
    return {
        "observations": int(len(net)),
        "gross_total_return": float(np.prod(1.0 + gross) - 1.0),
        "net_total_return": float(equity[-1] - 1.0),
        "annualized_arithmetic_mean": float(np.mean(net) * ANNUALIZATION),
        "annualized_volatility": float(std * math.sqrt(ANNUALIZATION)),
        "sharpe": finite_float(sharpe),
        "max_drawdown": float(np.min(drawdown)),
        "turnover": total_turnover,
        "annualized_turnover": float(np.mean(turnover) * ANNUALIZATION),
        "fee_sum": float(np.sum(turnover) * FEE),
        "average_exposure": float(np.mean(position)),
        "long_hours": int(np.sum(position > 0.5)),
        "net_edge_per_turnover_bps": (
            float(np.sum(net) / total_turnover * 10000.0)
            if total_turnover > 0
            else None
        ),
        "gross_edge_per_turnover_bps": (
            float(np.sum(gross) / total_turnover * 10000.0)
            if total_turnover > 0
            else None
        ),
    }


def residual_sharpe(a: np.ndarray, b: np.ndarray) -> float | None:
    residual = a - b
    std = float(np.std(residual, ddof=1))
    if std <= 0:
        return None
    return float(np.mean(residual) / std * math.sqrt(ANNUALIZATION))


def fold_and_year_breadth(
    timestamps: pd.DatetimeIndex,
    net: np.ndarray,
    fold_hours: int = FOLD_HOURS,
) -> dict[str, Any]:
    folds: list[dict[str, Any]] = []
    for fold_index, start in enumerate(range(0, len(net), fold_hours)):
        stop = min(start + fold_hours, len(net))
        fold_net = net[start:stop]
        fold_return = float(np.prod(1.0 + fold_net) - 1.0)
        folds.append(
            {
                "fold": fold_index,
                "start": timestamps[start].isoformat().replace("+00:00", "Z"),
                "end": timestamps[stop - 1].isoformat().replace("+00:00", "Z"),
                "hours": int(stop - start),
                "net_return": fold_return,
                "sharpe": metrics(
                    fold_net,
                    fold_net,
                    np.zeros_like(fold_net),
                    np.zeros_like(fold_net),
                )["sharpe"],
            }
        )
    positive = [max(0.0, item["net_return"]) for item in folds]
    positive_sum = float(sum(positive))
    concentration = max(positive) / positive_sum if positive_sum > 0 else None

    years: list[dict[str, Any]] = []
    year_values = np.asarray(timestamps.year)
    for year in sorted(set(year_values.tolist())):
        mask = year_values == year
        yr = net[mask]
        years.append(
            {
                "year": int(year),
                "hours": int(mask.sum()),
                "net_return": float(np.prod(1.0 + yr) - 1.0),
                "sharpe": metrics(
                    yr,
                    yr,
                    np.zeros_like(yr),
                    np.zeros_like(yr),
                )["sharpe"],
            }
        )
    return {
        "folds": folds,
        "profitable_fold_count": int(
            sum(item["net_return"] > 0 for item in folds)
        ),
        "fold_count": int(len(folds)),
        "positive_fold_return_concentration": concentration,
        "years": years,
        "profitable_year_count": int(
            sum(item["net_return"] > 0 for item in years)
        ),
        "year_segment_count": int(len(years)),
    }


def prefix_sum(values: np.ndarray) -> np.ndarray:
    return np.concatenate(([0.0], np.cumsum(values, dtype=np.float64)))


def block_stat(prefix: np.ndarray, starts: np.ndarray, lengths: np.ndarray) -> float:
    return float(np.sum(prefix[starts + lengths] - prefix[starts]))


def paired_block_bootstrap(
    candidate: np.ndarray,
    benchmark: np.ndarray,
) -> dict[str, Any]:
    if len(candidate) != len(benchmark):
        raise ValueError("bootstrap series length mismatch")
    n = len(candidate)
    block = BOOTSTRAP_BLOCK
    blocks = math.ceil(n / block)
    lengths = np.full(blocks, block, dtype=np.int64)
    lengths[-1] = n - block * (blocks - 1)
    rng = np.random.default_rng(BOOTSTRAP_SEED)

    prefix_c = prefix_sum(candidate)
    prefix_b = prefix_sum(benchmark)
    prefix_c2 = prefix_sum(candidate * candidate)
    prefix_b2 = prefix_sum(benchmark * benchmark)

    mean_delta = np.empty(BOOTSTRAP_RESAMPLES, dtype=np.float64)
    sharpe_delta = np.empty(BOOTSTRAP_RESAMPLES, dtype=np.float64)
    for i in range(BOOTSTRAP_RESAMPLES):
        max_starts = n - lengths
        starts = np.array(
            [rng.integers(0, int(limit) + 1) for limit in max_starts],
            dtype=np.int64,
        )
        sum_c = block_stat(prefix_c, starts, lengths)
        sum_b = block_stat(prefix_b, starts, lengths)
        sum_c2 = block_stat(prefix_c2, starts, lengths)
        sum_b2 = block_stat(prefix_b2, starts, lengths)
        mean_c = sum_c / n
        mean_b = sum_b / n
        var_c = max(0.0, (sum_c2 - n * mean_c * mean_c) / (n - 1))
        var_b = max(0.0, (sum_b2 - n * mean_b * mean_b) / (n - 1))
        sh_c = (
            mean_c / math.sqrt(var_c) * math.sqrt(ANNUALIZATION)
            if var_c > 0
            else 0.0
        )
        sh_b = (
            mean_b / math.sqrt(var_b) * math.sqrt(ANNUALIZATION)
            if var_b > 0
            else 0.0
        )
        mean_delta[i] = (mean_c - mean_b) * ANNUALIZATION
        sharpe_delta[i] = sh_c - sh_b

    def interval(values: np.ndarray) -> dict[str, float]:
        return {
            "point_estimate": float(np.mean(values)),
            "lower_95": float(np.quantile(values, 0.025)),
            "upper_95": float(np.quantile(values, 0.975)),
        }

    return {
        "method": "paired_non_circular_moving_block",
        "block_hours": block,
        "resamples": BOOTSTRAP_RESAMPLES,
        "seed": BOOTSTRAP_SEED,
        "annualized_mean_delta": interval(mean_delta),
        "sharpe_delta": interval(sharpe_delta),
    }


def build_paths(
    df: pd.DataFrame,
) -> dict[str, np.ndarray | pd.DatetimeIndex | pd.Series]:
    close = df["close"].to_numpy(dtype=np.float64)
    open_ = df["open"].to_numpy(dtype=np.float64)
    timestamps = pd.DatetimeIndex(pd.to_datetime(df["timestamp"], utc=True))
    log_close = np.log(close)
    hourly_log_return = np.empty(len(df), dtype=np.float64)
    hourly_log_return[0] = np.nan
    hourly_log_return[1:] = np.diff(log_close)

    slow = np.full(len(df), np.nan, dtype=np.float64)
    slow[2160:] = log_close[2160:] - log_close[:-2160]

    path_eff = np.full(len(df), np.nan, dtype=np.float64)
    abs_ret = pd.Series(np.abs(hourly_log_return))
    path_length = abs_ret.rolling(720, min_periods=720).sum().to_numpy()
    path_move = np.full(len(df), np.nan, dtype=np.float64)
    path_move[720:] = log_close[720:] - log_close[:-720]
    valid = np.isfinite(path_length) & (path_length > 0)
    path_eff[valid] = path_move[valid] / path_length[valid]

    pe_series = pd.Series(path_eff)
    q40 = (
        pe_series.shift(1)
        .rolling(2160, min_periods=2160)
        .quantile(0.40)
        .to_numpy()
    )
    q60 = (
        pe_series.shift(1)
        .rolling(2160, min_periods=2160)
        .quantile(0.60)
        .to_numpy()
    )

    max_signal = OOS_END_EXCLUSIVE - 1
    if max_signal + 2 >= len(df):
        raise ValueError("insufficient payoff bars")
    payoff = open_[2 : max_signal + 3] / open_[1 : max_signal + 2] - 1.0
    if len(payoff) != max_signal + 1:
        raise AssertionError("payoff alignment failure")

    candidate = np.zeros(max_signal + 1, dtype=np.float64)
    daily_benchmark = np.zeros(max_signal + 1, dtype=np.float64)
    hourly_benchmark = np.zeros(max_signal + 1, dtype=np.float64)

    cand_state = 0.0
    daily_state = 0.0
    for t in range(max_signal + 1):
        if t >= 2160:
            hourly_benchmark[t] = 1.0 if slow[t] > 0 else 0.0
        if timestamps[t].hour == 0:
            if t >= 2160:
                daily_state = 1.0 if slow[t] > 0 else 0.0
            if t >= WARMUP_END:
                if not all(
                    math.isfinite(x)
                    for x in (slow[t], path_eff[t], q40[t], q60[t])
                ):
                    raise ValueError(f"non-finite candidate feature at {t}")
                if cand_state == 0.0 and slow[t] > 0 and path_eff[t] > q60[t]:
                    cand_state = 1.0
                elif cand_state == 1.0 and (
                    slow[t] <= 0 or path_eff[t] < q40[t]
                ):
                    cand_state = 0.0
        candidate[t] = cand_state
        daily_benchmark[t] = daily_state

    def returns(
        position: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        prior = np.concatenate(([0.0], position[:-1]))
        turnover = np.abs(position - prior)
        gross = position * payoff
        net = gross - FEE * turnover
        return net, gross, turnover

    c_net, c_gross, c_turnover = returns(candidate)
    h_net, h_gross, h_turnover = returns(hourly_benchmark)
    d_net, d_gross, d_turnover = returns(daily_benchmark)
    return {
        "timestamps": timestamps[: max_signal + 1],
        "slow": slow[: max_signal + 1],
        "path_eff": path_eff[: max_signal + 1],
        "q40": q40[: max_signal + 1],
        "q60": q60[: max_signal + 1],
        "candidate_position": candidate,
        "candidate_net": c_net,
        "candidate_gross": c_gross,
        "candidate_turnover": c_turnover,
        "hourly_position": hourly_benchmark,
        "hourly_net": h_net,
        "hourly_gross": h_gross,
        "hourly_turnover": h_turnover,
        "daily_position": daily_benchmark,
        "daily_net": d_net,
        "daily_gross": d_gross,
        "daily_turnover": d_turnover,
    }


def interval_report(
    paths: dict[str, Any],
    start: int,
    stop: int,
) -> dict[str, Any]:
    timestamps = paths["timestamps"][start:stop]
    c_net = paths["candidate_net"][start:stop]
    h_net = paths["hourly_net"][start:stop]
    d_net = paths["daily_net"][start:stop]
    candidate = metrics(
        c_net,
        paths["candidate_gross"][start:stop],
        paths["candidate_turnover"][start:stop],
        paths["candidate_position"][start:stop],
    )
    hourly = metrics(
        h_net,
        paths["hourly_gross"][start:stop],
        paths["hourly_turnover"][start:stop],
        paths["hourly_position"][start:stop],
    )
    daily = metrics(
        d_net,
        paths["daily_gross"][start:stop],
        paths["daily_turnover"][start:stop],
        paths["daily_position"][start:stop],
    )
    return {
        "start": timestamps[0].isoformat().replace("+00:00", "Z"),
        "end": timestamps[-1].isoformat().replace("+00:00", "Z"),
        "candidate": candidate,
        "benchmark_hourly_2160h": hourly,
        "benchmark_daily_2160h": daily,
        "candidate_minus_hourly": {
            "net_total_return_delta": (
                candidate["net_total_return"] - hourly["net_total_return"]
            ),
            "sharpe_delta": (
                candidate["sharpe"] - hourly["sharpe"]
                if candidate["sharpe"] is not None
                and hourly["sharpe"] is not None
                else None
            ),
            "residual_sharpe": residual_sharpe(c_net, h_net),
            "turnover_delta": candidate["turnover"] - hourly["turnover"],
        },
        "candidate_minus_daily": {
            "net_total_return_delta": (
                candidate["net_total_return"] - daily["net_total_return"]
            ),
            "sharpe_delta": (
                candidate["sharpe"] - daily["sharpe"]
                if candidate["sharpe"] is not None
                and daily["sharpe"] is not None
                else None
            ),
            "residual_sharpe": residual_sharpe(c_net, d_net),
            "turnover_delta": candidate["turnover"] - daily["turnover"],
        },
    }


def evaluate_market(paths_spec: Paths) -> dict[str, Any]:
    expected = EXPECTED[paths_spec.instrument]
    actual_zip = sha256_file(paths_spec.zip_path)
    actual_csv = sha256_file(paths_spec.csv_path)
    if actual_zip != expected["zip_sha256"]:
        raise ValueError(f"ZIP hash mismatch for {paths_spec.instrument}")
    if actual_csv != expected["csv_sha256"]:
        raise ValueError(f"CSV hash mismatch for {paths_spec.instrument}")

    df = pd.read_csv(paths_spec.csv_path)
    required = {"timestamp", "open", "high", "low", "close", "confirm"}
    if not required.issubset(df.columns):
        raise ValueError("missing required columns")
    if len(df) != 43941 or not (df["confirm"] == 1).all():
        raise ValueError("unexpected observation count or incomplete bar")
    ts = pd.DatetimeIndex(pd.to_datetime(df["timestamp"], utc=True))
    if ts.has_duplicates or not ts.is_monotonic_increasing:
        raise ValueError("timestamp order failure")
    gaps = np.diff(ts.view("int64"))
    if not np.all(gaps == 3_600_000_000_000):
        raise ValueError("non-contiguous 1H grid")
    numeric = df[["open", "high", "low", "close"]].to_numpy(dtype=np.float64)
    if not np.isfinite(numeric).all() or not (numeric > 0).all():
        raise ValueError("invalid prices")

    paths = build_paths(df)
    train = interval_report(paths, WARMUP_END, TRAIN_END_EXCLUSIVE)
    oos = interval_report(paths, TRAIN_END_EXCLUSIVE, OOS_END_EXCLUSIVE)
    full = interval_report(paths, WARMUP_END, OOS_END_EXCLUSIVE)

    breadth = fold_and_year_breadth(
        paths["timestamps"][TRAIN_END_EXCLUSIVE:OOS_END_EXCLUSIVE],
        paths["candidate_net"][TRAIN_END_EXCLUSIVE:OOS_END_EXCLUSIVE],
    )
    bootstrap = paired_block_bootstrap(
        paths["candidate_net"][TRAIN_END_EXCLUSIVE:OOS_END_EXCLUSIVE],
        paths["daily_net"][TRAIN_END_EXCLUSIVE:OOS_END_EXCLUSIVE],
    )

    cand = oos["candidate"]
    b_daily = oos["benchmark_daily_2160h"]
    gates = {
        "positive_net_return": cand["net_total_return"] > 0,
        "positive_sharpe": cand["sharpe"] is not None and cand["sharpe"] > 0,
        "positive_edge_per_turnover": (
            cand["net_edge_per_turnover_bps"] is not None
            and cand["net_edge_per_turnover_bps"] > 0
        ),
        "profitable_folds_at_least_7_of_12": (
            breadth["profitable_fold_count"] >= 7
        ),
        "positive_fold_concentration_at_most_50pct": (
            breadth["positive_fold_return_concentration"] is not None
            and breadth["positive_fold_return_concentration"] <= 0.50
        ),
        "profitable_year_segments_at_least_3": (
            breadth["profitable_year_count"] >= 3
        ),
        "sharpe_exceeds_daily_benchmark": (
            cand["sharpe"] is not None
            and b_daily["sharpe"] is not None
            and cand["sharpe"] > b_daily["sharpe"]
        ),
        "edge_per_turnover_exceeds_daily_benchmark": (
            cand["net_edge_per_turnover_bps"] is not None
            and b_daily["net_edge_per_turnover_bps"] is not None
            and cand["net_edge_per_turnover_bps"]
            > b_daily["net_edge_per_turnover_bps"]
        ),
        "positive_residual_sharpe_vs_hourly": (
            oos["candidate_minus_hourly"]["residual_sharpe"] is not None
            and oos["candidate_minus_hourly"]["residual_sharpe"] > 0
        ),
        "bootstrap_mean_delta_lower_bound_positive": (
            bootstrap["annualized_mean_delta"]["lower_95"] > 0
        ),
        "bootstrap_sharpe_delta_lower_bound_positive": (
            bootstrap["sharpe_delta"]["lower_95"] > 0
        ),
    }
    return {
        "instrument": paths_spec.instrument,
        "source": {
            "workflow_run_id": 30401519824,
            "artifact_id": expected["artifact_id"],
            "artifact_zip_sha256": actual_zip,
            "normalized_csv_sha256": actual_csv,
            "observations": int(len(df)),
            "start": ts[0].isoformat().replace("+00:00", "Z"),
            "end": ts[-1].isoformat().replace("+00:00", "Z"),
            "contiguous_confirmed_grid": True,
        },
        "train": train,
        "development_oos": oos,
        "full_scored": full,
        "oos_breadth": breadth,
        "oos_bootstrap_candidate_minus_daily": bootstrap,
        "acceptance_gates": gates,
        "all_acceptance_gates_pass": bool(all(gates.values())),
        "latest_unscored_signal_bar_start": (
            ts[OOS_END_EXCLUSIVE].isoformat().replace("+00:00", "Z")
        ),
        "unscored_suffix_signal_bar_count": int(
            len(df) - OOS_END_EXCLUSIVE - 2
        ),
    }


def canonical_json_hash(payload: dict[str, Any]) -> str:
    blob = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return hashlib.sha256(blob).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--btc-zip", type=Path, required=True)
    parser.add_argument("--btc-csv", type=Path, required=True)
    parser.add_argument("--eth-zip", type=Path, required=True)
    parser.add_argument("--eth-csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    markets = [
        evaluate_market(Paths("BTC-USDT", args.btc_zip, args.btc_csv)),
        evaluate_market(Paths("ETH-USDT", args.eth_zip, args.eth_csv)),
    ]
    accepted = all(market["all_acceptance_gates_pass"] for market in markets)
    result: dict[str, Any] = {
        "schema_version": 1,
        "family_id": "path-efficiency-hysteresis-1h-v1",
        "issue": 593,
        "classification": "single frozen development architecture",
        "repository_main_inspected": (
            "5a0fcc97d1a882f8223656c51f5bb8055f534e38"
        ),
        "bar": "1H",
        "markets_independent": True,
        "cross_sectional_selection": False,
        "candidate_count": 1,
        "parameter_grid_count": 0,
        "canonical_fee_bps_one_way": 5.0,
        "execution": "completed bar t; open[t+1] to open[t+2]",
        "position_set": [0, 1],
        "rule": {
            "slow_momentum_hours": 2160,
            "path_efficiency_hours": 720,
            "causal_efficiency_distribution_hours": 2160,
            "entry_quantile": 0.60,
            "exit_quantile": 0.40,
            "decision_hour_utc": 0,
            "no_artificial_terminal_exit": True,
        },
        "sample": {
            "warmup_signal_indices": [0, WARMUP_END - 1],
            "train_signal_indices": [WARMUP_END, TRAIN_END_EXCLUSIVE - 1],
            "development_oos_signal_indices": [
                TRAIN_END_EXCLUSIVE,
                OOS_END_EXCLUSIVE - 1,
            ],
            "train_hours": TRAIN_END_EXCLUSIVE - WARMUP_END,
            "development_oos_hours": (
                OOS_END_EXCLUSIVE - TRAIN_END_EXCLUSIVE
            ),
            "full_scored_hours": OOS_END_EXCLUSIVE - WARMUP_END,
            "oos_fold_hours": FOLD_HOURS,
            "oos_fold_count": (
                OOS_END_EXCLUSIVE - TRAIN_END_EXCLUSIVE
            )
            // FOLD_HOURS,
            "official_untouched_oos_consumed": False,
        },
        "safety": {
            "public_data_only": True,
            "credentials_used": False,
            "private_endpoints_used": False,
            "accounts_accessed": False,
            "orders_placed": False,
            "leverage_used": False,
            "synthetic_data_used": False,
            "fifteen_minute_data_used": False,
        },
        "markets": markets,
        "verdict": (
            "accept_for_shadow_observation_only"
            if accepted
            else "reject_exact_path_efficiency_hysteresis_family"
        ),
        "paper_or_live_authorized": False,
        "rescue_tuning_authorized": False,
    }
    result["canonical_payload_sha256"] = canonical_json_hash(result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "verdict": result["verdict"],
                "sha256": sha256_file(args.output),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
