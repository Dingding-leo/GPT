#!/usr/bin/env python3
# ruff: noqa: E501
# fmt: off
"""Reproduce the frozen path-efficiency hysteresis experiment in issue #593."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

FEE = 0.0005
ANN = 8760.0
TRAIN_START = 2880
OOS_START = 17520
OOS_STOP = 43440
FOLD = 2160
BLOCK = 168
RESAMPLES = 5000
SEED = 20260729
SOURCES = {
    "BTC-USDT": {
        "artifact_id": 8704977298,
        "zip_sha256": "22d6d0e7f5dbffe4e746f091a5ab2488e3edc7d8440fea393ee2862295cf208c",
        "csv_sha256": "92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9",
    },
    "ETH-USDT": {
        "artifact_id": 8704978112,
        "zip_sha256": "e7107f83a4eb5059ada0bb2097aeb5ded976dc9c037f564538f5cf5b4a7dffe3",
        "csv_sha256": "2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726",
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def score(net: np.ndarray, gross: np.ndarray, turn: np.ndarray, pos: np.ndarray) -> dict:
    equity = np.cumprod(1.0 + net)
    path = np.concatenate(([1.0], equity))
    drawdown = path / np.maximum.accumulate(path) - 1.0
    volatility = float(np.std(net, ddof=1))
    turnover = float(turn.sum())
    sharpe = float(net.mean() / volatility * math.sqrt(ANN)) if volatility > 0 else None
    return {
        "net_total_return": float(equity[-1] - 1.0),
        "gross_total_return": float(np.prod(1.0 + gross) - 1.0),
        "sharpe": sharpe,
        "max_drawdown": float(drawdown.min()),
        "turnover": turnover,
        "fee_sum": turnover * FEE,
        "average_exposure": float(pos.mean()),
        "net_edge_per_turnover_bps": float(net.sum() / turnover * 10000.0) if turnover else None,
    }


def residual_sharpe(left: np.ndarray, right: np.ndarray) -> float | None:
    residual = left - right
    volatility = float(np.std(residual, ddof=1))
    return float(residual.mean() / volatility * math.sqrt(ANN)) if volatility > 0 else None


def bootstrap(candidate: np.ndarray, benchmark: np.ndarray) -> dict:
    n = len(candidate)
    count = math.ceil(n / BLOCK)
    lengths = np.full(count, BLOCK, dtype=np.int64)
    lengths[-1] = n - BLOCK * (count - 1)
    rng = np.random.default_rng(SEED)
    pc = np.concatenate(([0.0], np.cumsum(candidate)))
    pb = np.concatenate(([0.0], np.cumsum(benchmark)))
    pc2 = np.concatenate(([0.0], np.cumsum(candidate * candidate)))
    pb2 = np.concatenate(([0.0], np.cumsum(benchmark * benchmark)))
    mean_delta = np.empty(RESAMPLES)
    sharpe_delta = np.empty(RESAMPLES)
    for sample in range(RESAMPLES):
        starts = np.array([rng.integers(0, int(n - length) + 1) for length in lengths])
        sc = float(np.sum(pc[starts + lengths] - pc[starts]))
        sb = float(np.sum(pb[starts + lengths] - pb[starts]))
        sc2 = float(np.sum(pc2[starts + lengths] - pc2[starts]))
        sb2 = float(np.sum(pb2[starts + lengths] - pb2[starts]))
        mc = sc / n
        mb = sb / n
        vc = max(0.0, (sc2 - n * mc * mc) / (n - 1))
        vb = max(0.0, (sb2 - n * mb * mb) / (n - 1))
        hc = mc / math.sqrt(vc) * math.sqrt(ANN) if vc > 0 else 0.0
        hb = mb / math.sqrt(vb) * math.sqrt(ANN) if vb > 0 else 0.0
        mean_delta[sample] = (mc - mb) * ANN
        sharpe_delta[sample] = hc - hb

    def interval(values: np.ndarray) -> dict:
        return {
            "point_estimate": float(values.mean()),
            "lower_95": float(np.quantile(values, 0.025)),
            "upper_95": float(np.quantile(values, 0.975)),
        }

    return {
        "method": "paired_non_circular_moving_block",
        "block_hours": BLOCK,
        "resamples": RESAMPLES,
        "seed": SEED,
        "annualized_mean_delta": interval(mean_delta),
        "sharpe_delta": interval(sharpe_delta),
    }


def construct(df: pd.DataFrame) -> dict:
    close = df["close"].to_numpy(float)
    opening = df["open"].to_numpy(float)
    timestamps = pd.DatetimeIndex(pd.to_datetime(df["timestamp"], utc=True))
    log_close = np.log(close)
    log_return = np.concatenate(([np.nan], np.diff(log_close)))
    slow = np.full(len(df), np.nan)
    slow[2160:] = log_close[2160:] - log_close[:-2160]
    distance = pd.Series(np.abs(log_return)).rolling(720, min_periods=720).sum().to_numpy()
    movement = np.full(len(df), np.nan)
    movement[720:] = log_close[720:] - log_close[:-720]
    efficiency = np.divide(movement, distance, out=np.full(len(df), np.nan), where=distance > 0)
    series = pd.Series(efficiency)
    q40 = series.shift(1).rolling(2160, min_periods=2160).quantile(0.40).to_numpy()
    q60 = series.shift(1).rolling(2160, min_periods=2160).quantile(0.60).to_numpy()
    payoff = opening[2 : OOS_STOP + 2] / opening[1 : OOS_STOP + 1] - 1.0
    candidate = np.zeros(OOS_STOP)
    daily = np.zeros(OOS_STOP)
    hourly = np.zeros(OOS_STOP)
    candidate_state = 0.0
    daily_state = 0.0
    for index in range(OOS_STOP):
        if index >= 2160:
            hourly[index] = float(slow[index] > 0)
        if timestamps[index].hour == 0:
            if index >= 2160:
                daily_state = float(slow[index] > 0)
            if index >= TRAIN_START:
                values = (slow[index], efficiency[index], q40[index], q60[index])
                if not all(math.isfinite(value) for value in values):
                    raise ValueError(f"non-finite feature at index {index}")
                if candidate_state == 0.0 and slow[index] > 0 and efficiency[index] > q60[index]:
                    candidate_state = 1.0
                elif candidate_state == 1.0 and (slow[index] <= 0 or efficiency[index] < q40[index]):
                    candidate_state = 0.0
        candidate[index] = candidate_state
        daily[index] = daily_state

    def returns(position: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        prior = np.concatenate(([0.0], position[:-1]))
        turn = np.abs(position - prior)
        gross = position * payoff
        return gross - FEE * turn, gross, turn

    result = {"timestamps": timestamps[:OOS_STOP]}
    for name, position in (("candidate", candidate), ("hourly", hourly), ("daily", daily)):
        net, gross, turn = returns(position)
        result[name] = {"position": position, "net": net, "gross": gross, "turn": turn}
    return result


def interval(paths: dict, start: int, stop: int) -> dict:
    output = {"window": [paths["timestamps"][start].isoformat(), paths["timestamps"][stop - 1].isoformat()]}
    for name in ("candidate", "hourly", "daily"):
        path = paths[name]
        output[name] = score(
            path["net"][start:stop],
            path["gross"][start:stop],
            path["turn"][start:stop],
            path["position"][start:stop],
        )
    candidate = paths["candidate"]["net"][start:stop]
    hourly = paths["hourly"]["net"][start:stop]
    daily = paths["daily"]["net"][start:stop]
    output["candidate_minus_hourly"] = {
        "net_total_return_delta": output["candidate"]["net_total_return"] - output["hourly"]["net_total_return"],
        "sharpe_delta": output["candidate"]["sharpe"] - output["hourly"]["sharpe"],
        "residual_sharpe": residual_sharpe(candidate, hourly),
        "turnover_delta": output["candidate"]["turnover"] - output["hourly"]["turnover"],
    }
    output["candidate_minus_daily"] = {
        "net_total_return_delta": output["candidate"]["net_total_return"] - output["daily"]["net_total_return"],
        "sharpe_delta": output["candidate"]["sharpe"] - output["daily"]["sharpe"],
        "residual_sharpe": residual_sharpe(candidate, daily),
        "turnover_delta": output["candidate"]["turnover"] - output["daily"]["turnover"],
    }
    return output


def evaluate(instrument: str, zip_path: Path, csv_path: Path) -> dict:
    source = SOURCES[instrument]
    if sha256(zip_path) != source["zip_sha256"] or sha256(csv_path) != source["csv_sha256"]:
        raise ValueError(f"source hash mismatch for {instrument}")
    df = pd.read_csv(csv_path)
    timestamps = pd.DatetimeIndex(pd.to_datetime(df["timestamp"], utc=True))
    gaps = np.diff(timestamps.view("int64"))
    prices = df[["open", "high", "low", "close"]].to_numpy(float)
    if len(df) != 43941 or not (df["confirm"] == 1).all():
        raise ValueError(f"unexpected grid for {instrument}")
    if timestamps.has_duplicates or not timestamps.is_monotonic_increasing:
        raise ValueError(f"timestamp order failure for {instrument}")
    if not np.all(gaps == 3_600_000_000_000) or not np.isfinite(prices).all() or not (prices > 0).all():
        raise ValueError(f"invalid candles for {instrument}")
    paths = construct(df)
    train = interval(paths, TRAIN_START, OOS_START)
    oos = interval(paths, OOS_START, OOS_STOP)
    full = interval(paths, TRAIN_START, OOS_STOP)
    oos_net = paths["candidate"]["net"][OOS_START:OOS_STOP]
    oos_ts = paths["timestamps"][OOS_START:OOS_STOP]
    folds = [float(np.prod(1.0 + oos_net[start : start + FOLD]) - 1.0) for start in range(0, len(oos_net), FOLD)]
    years = {str(year): float(np.prod(1.0 + oos_net[np.asarray(oos_ts.year) == year]) - 1.0) for year in sorted(set(oos_ts.year))}
    positive = [max(0.0, value) for value in folds]
    concentration = max(positive) / sum(positive) if sum(positive) else None
    uncertainty = bootstrap(oos_net, paths["daily"]["net"][OOS_START:OOS_STOP])
    gates = {
        "positive_net_return": oos["candidate"]["net_total_return"] > 0,
        "positive_sharpe": oos["candidate"]["sharpe"] > 0,
        "positive_edge_per_turnover": oos["candidate"]["net_edge_per_turnover_bps"] > 0,
        "profitable_folds_at_least_7_of_12": sum(value > 0 for value in folds) >= 7,
        "positive_fold_concentration_at_most_50pct": concentration is not None and concentration <= 0.50,
        "profitable_year_segments_at_least_3": sum(value > 0 for value in years.values()) >= 3,
        "sharpe_exceeds_daily_benchmark": oos["candidate"]["sharpe"] > oos["daily"]["sharpe"],
        "edge_per_turnover_exceeds_daily_benchmark": oos["candidate"]["net_edge_per_turnover_bps"] > oos["daily"]["net_edge_per_turnover_bps"],
        "positive_residual_sharpe_vs_hourly": oos["candidate_minus_hourly"]["residual_sharpe"] > 0,
        "bootstrap_mean_delta_lower_bound_positive": uncertainty["annualized_mean_delta"]["lower_95"] > 0,
        "bootstrap_sharpe_delta_lower_bound_positive": uncertainty["sharpe_delta"]["lower_95"] > 0,
    }
    return {
        "instrument": instrument,
        "source": {
            **source,
            "workflow_run_id": 30401519824,
            "observations": len(df),
            "start": timestamps[0].isoformat(),
            "end": timestamps[-1].isoformat(),
            "contiguous_confirmed_grid": True,
        },
        "train": train,
        "development_oos": oos,
        "full_scored": full,
        "oos_breadth": {
            "profitable_folds": sum(value > 0 for value in folds),
            "fold_count": len(folds),
            "positive_fold_return_concentration": concentration,
            "profitable_years": sum(value > 0 for value in years.values()),
            "year_count": len(years),
            "year_returns": years,
        },
        "oos_uncertainty_vs_daily": uncertainty,
        "acceptance_gates": gates,
        "accepted": all(gates.values()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--btc-zip", type=Path, required=True)
    parser.add_argument("--btc-csv", type=Path, required=True)
    parser.add_argument("--eth-zip", type=Path, required=True)
    parser.add_argument("--eth-csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    markets = [
        evaluate("BTC-USDT", args.btc_zip, args.btc_csv),
        evaluate("ETH-USDT", args.eth_zip, args.eth_csv),
    ]
    result = {
        "schema_version": 1,
        "family_id": "path-efficiency-hysteresis-1h-v1",
        "issue": 593,
        "main": "5a0fcc97d1a882f8223656c51f5bb8055f534e38",
        "bar": "1H",
        "candidate_count": 1,
        "parameter_grid_count": 0,
        "fee_bps_one_way": 5.0,
        "execution": "completed t; open[t+1] to open[t+2]",
        "cross_sectional_selection": False,
        "untouched_oos_consumed": False,
        "markets": markets,
        "verdict": "accept_for_shadow_observation_only" if all(item["accepted"] for item in markets) else "reject_exact_path_efficiency_hysteresis_family",
        "paper_or_live_authorized": False,
        "rescue_tuning_authorized": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(args.output), "sha256": sha256(args.output), "verdict": result["verdict"]}, indent=2))


if __name__ == "__main__":
    main()
# fmt: on
