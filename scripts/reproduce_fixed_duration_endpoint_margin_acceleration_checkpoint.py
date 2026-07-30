#!/usr/bin/env python3
"""Reproduce issue #730 with immutable public OKX 1H candles."""

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
ROWS = 43_441
TRAIN = (2_880, 17_520)
OOS = (17_520, 43_440)
FULL = (2_880, 43_440)
FOLD = 2_160
BLOCK = 168
CHECKPOINT = 168
DRAWS = 5_000
SEED = 20_260_731
EXPECTED = {
    "BTC-USDT": (
        "40c7ba3dbf64b8b31c634a79e1a2d5e2fa9d60b024c1fd62848d37ed967c13a0",
        "4efd9875f8205f2c44c6e26042b24bdfb89f077f7c89b2888a6bac9b645747e0",
    ),
    "ETH-USDT": (
        "0164a5cc1730f70ad9817980d67d6350cf71013cdb759c1a153a66890127d6f8",
        "3c6ce0c424280f1e0b6210501380336190d832359895df9534e5c5a16d9ec6ed",
    ),
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load(path: Path, market: str, rows: int | None = ROWS) -> pd.DataFrame:
    raw = path.read_bytes()
    lines = raw.splitlines(keepends=True)
    full_hash, prefix_hash = EXPECTED[market]
    if sha(raw) != full_hash:
        raise ValueError(f"full hash mismatch: {market}")
    if sha(b"".join(lines[: ROWS + 1])) != prefix_hash:
        raise ValueError(f"prefix hash mismatch: {market}")
    frame = pd.read_csv(path, nrows=rows)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    if len(frame) != (ROWS if rows is not None else len(lines) - 1):
        raise ValueError(f"unexpected row count: {market}")
    if not (frame["confirm"].to_numpy() == 1).all():
        raise ValueError(f"unconfirmed bars: {market}")
    step = frame["timestamp"].diff().dropna()
    if not (step == pd.Timedelta(hours=1)).all():
        raise ValueError(f"non-contiguous chronology: {market}")
    return frame


def positions(frame: pd.DataFrame) -> tuple[dict[str, np.ndarray], list[dict[str, int | str]]]:
    close = frame["close"].to_numpy(float)
    hours = frame["timestamp"].dt.hour.to_numpy()
    n = len(frame) - 1
    candidate = np.zeros(n)
    daily = np.zeros(n)
    hourly = np.zeros(n)
    margin = np.full(len(frame), np.nan)
    margin[2_160:] = np.log(close[2_160:] / close[:-2_160])

    current_candidate = 0.0
    current_daily = 0.0
    prior_daily_base = 0
    checkpoint_used = False
    checkpoint_active = False
    checkpoint_end = -1
    events: list[dict[str, int | str]] = []
    active_event: int | None = None

    for t in range(2_160, len(frame) - 2):
        base = int(margin[t] > 0)

        if hours[t] == 0:
            execution_index = t + 1
            onset = base == 1 and prior_daily_base == 0
            if base == 0:
                current_daily = 0.0
                current_candidate = 0.0
                if checkpoint_active and active_event is not None:
                    events[active_event]["finish_index"] = execution_index
                    events[active_event]["finish_reason"] = "base_exit"
                checkpoint_used = False
                checkpoint_active = False
                checkpoint_end = -1
                active_event = None
            else:
                current_daily = 1.0
                if onset:
                    current_candidate = 1.0
                    checkpoint_used = False
                    checkpoint_active = False
                    checkpoint_end = -1
                    active_event = None
                elif checkpoint_active:
                    if execution_index >= checkpoint_end:
                        current_candidate = 1.0
                        checkpoint_active = False
                        if active_event is None:
                            raise AssertionError("checkpoint event missing at restoration")
                        events[active_event]["finish_index"] = execution_index
                        events[active_event]["finish_reason"] = "automatic_restore"
                        active_event = None
                    else:
                        current_candidate = 0.5
                elif checkpoint_used:
                    current_candidate = 1.0
                elif t >= 2_496:
                    latest_change = margin[t] - margin[t - 168]
                    preceding_change = margin[t - 168] - margin[t - 336]
                    if (
                        latest_change < 0
                        and preceding_change < 0
                        and latest_change < preceding_change
                    ):
                        current_candidate = 0.5
                        checkpoint_used = True
                        checkpoint_active = True
                        checkpoint_end = execution_index + CHECKPOINT
                        events.append(
                            {
                                "decision_index": t,
                                "execution_index": execution_index,
                                "scheduled_end_index": checkpoint_end,
                                "finish_index": -1,
                                "finish_reason": "unresolved",
                            }
                        )
                        active_event = len(events) - 1
                    else:
                        current_candidate = 1.0
                else:
                    current_candidate = 1.0
            prior_daily_base = base

        candidate[t + 1] = current_candidate
        daily[t + 1] = current_daily

    if checkpoint_active and active_event is not None:
        events[active_event]["finish_index"] = len(candidate)
        events[active_event]["finish_reason"] = "sample_end"

    for t in range(2_160, len(frame) - 2):
        hourly[t + 1] = float(margin[t] > 0)

    if not np.isin(candidate, [0.0, 0.5, 1.0]).all():
        raise AssertionError("invalid candidate positions")
    if not np.isin(daily, [0.0, 1.0]).all() or not np.isin(hourly, [0.0, 1.0]).all():
        raise AssertionError("invalid benchmark positions")
    for event in events:
        start = int(event["execution_index"])
        finish = int(event["finish_index"])
        if finish < start:
            raise AssertionError("invalid checkpoint finish")
        duration = finish - start
        if event["finish_reason"] == "automatic_restore" and duration != CHECKPOINT:
            raise AssertionError("automatic checkpoint duration mismatch")
        if duration > CHECKPOINT:
            raise AssertionError("checkpoint exceeded frozen duration")
        if not np.all(candidate[start:finish] == 0.5):
            raise AssertionError("checkpoint exposure mismatch")
        if (
            finish < len(candidate)
            and event["finish_reason"] == "automatic_restore"
            and candidate[finish] != 1.0
        ):
            raise AssertionError("automatic restoration mismatch")
    return {"candidate": candidate, "b1": daily, "b0": hourly}, events


def returns(
    frame: pd.DataFrame,
    position: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    open_ = frame["open"].to_numpy(float)
    gross = open_[1:] / open_[:-1] - 1
    turnover = np.abs(np.diff(np.r_[0.0, position]))
    net = position * gross - FEE * turnover
    return net, turnover, gross


def compounded(values: np.ndarray) -> float:
    return float(np.prod(1 + values) - 1)


def sharpe(values: np.ndarray) -> float:
    std = float(values.std(ddof=1))
    return float(values.mean() / std * math.sqrt(ANN)) if std > 0 else math.nan


def metric(
    net: np.ndarray,
    turn: np.ndarray,
    position: np.ndarray,
    span: tuple[int, int],
) -> dict[str, float | int]:
    start, end = span
    values = net[start:end]
    turnover = float(turn[start:end].sum())
    equity = np.cumprod(1 + values)
    peaks = np.maximum.accumulate(np.r_[1.0, equity])[1:]
    arithmetic = float(values.sum())
    return {
        "net_return": compounded(values),
        "sharpe": sharpe(values),
        "max_drawdown": float((equity / peaks - 1).min()),
        "turnover": turnover,
        "fees": FEE * turnover,
        "edge_per_turnover_bps": arithmetic / turnover * 10_000,
        "exposure_hours": int(np.count_nonzero(position[start:end])),
        "full_equivalent_exposure_hours": float(position[start:end].sum()),
        "effective_transitions": int(np.count_nonzero(turn[start:end])),
    }


def breadth(
    frame: pd.DataFrame,
    candidate: np.ndarray,
    b1: np.ndarray,
) -> dict[str, Any]:
    folds: list[dict[str, Any]] = []
    for number in range(12):
        start = OOS[0] + number * FOLD
        end = start + FOLD
        c = compounded(candidate[start:end])
        b = compounded(b1[start:end])
        folds.append({"number": number + 1, "candidate": c, "b1": b})
    positive = [row["candidate"] for row in folds if row["candidate"] > 0]
    timestamps = frame["timestamp"].iloc[1:].reset_index(drop=True)
    years = timestamps.iloc[OOS[0] : OOS[1]].dt.year.to_numpy()
    year_rows: list[dict[str, Any]] = []
    for year in sorted(set(years)):
        index = np.flatnonzero(years == year) + OOS[0]
        c = compounded(candidate[index])
        b = compounded(b1[index])
        year_rows.append({"year": int(year), "candidate": c, "b1": b})
    residual = candidate[OOS[0] : OOS[1]] - b1[OOS[0] : OOS[1]]
    return {
        "profitable_folds": sum(row["candidate"] > 0 for row in folds),
        "profitable_years": sum(row["candidate"] > 0 for row in year_rows),
        "improved_folds": sum(row["candidate"] > row["b1"] for row in folds),
        "improved_years": sum(row["candidate"] > row["b1"] for row in year_rows),
        "positive_fold_concentration": (
            max(positive) / sum(positive) if positive and sum(positive) > 0 else math.nan
        ),
        "residual_sharpe": sharpe(residual),
        "folds": folds,
        "years": year_rows,
    }


def basic_interval(point: float, values: np.ndarray) -> list[float]:
    low, high = np.quantile(values, [0.025, 0.975])
    return [float(2 * point - high), float(2 * point - low)]


def uncertainty(candidate: np.ndarray, b1: np.ndarray) -> dict[str, Any]:
    c = candidate[OOS[0] : OOS[1]]
    b = b1[OOS[0] : OOS[1]]
    n = len(c)
    blocks = math.ceil(n / BLOCK)
    offsets = np.arange(BLOCK)
    rng = np.random.default_rng(SEED)
    mean_draws = np.empty(DRAWS)
    sharpe_draws = np.empty(DRAWS)
    for start in range(0, DRAWS, 100):
        size = min(100, DRAWS - start)
        heads = rng.integers(0, n - BLOCK + 1, (size, blocks))
        index = (heads[:, :, None] + offsets).reshape(size, -1)[:, :n]
        cs = c[index]
        bs = b[index]
        mean_draws[start : start + size] = (cs - bs).mean(axis=1) * ANN
        c_ratio = cs.mean(axis=1) / cs.std(axis=1, ddof=1)
        b_ratio = bs.mean(axis=1) / bs.std(axis=1, ddof=1)
        sharpe_draws[start : start + size] = (c_ratio - b_ratio) * math.sqrt(ANN)
    mean_point = float((c - b).mean() * ANN)
    sharpe_point = sharpe(c) - sharpe(b)
    return {
        "mean_delta_annualized": {
            "point": mean_point,
            "ci95": basic_interval(mean_point, mean_draws),
        },
        "sharpe_delta": {
            "point": sharpe_point,
            "ci95": basic_interval(sharpe_point, sharpe_draws),
        },
    }


def event_rows(
    frame: pd.DataFrame,
    events: list[dict[str, int | str]],
    gross: np.ndarray,
    span: tuple[int, int],
) -> list[dict[str, Any]]:
    start, end = span
    timestamps = frame["timestamp"].iloc[:-1].reset_index(drop=True)
    rows: list[dict[str, Any]] = []
    for event in events:
        execution = int(event["execution_index"])
        finish = int(event["finish_index"])
        overlap_start = max(start, execution)
        overlap_end = min(end, finish)
        if overlap_start >= overlap_end:
            continue
        rows.append(
            {
                "execution_timestamp": timestamps.iloc[execution].isoformat(),
                "scheduled_duration_hours": CHECKPOINT,
                "realized_duration_hours": finish - execution,
                "span_overlap_hours": overlap_end - overlap_start,
                "finish_reason": event["finish_reason"],
                "market_return": compounded(gross[execution:finish]),
                "arithmetic_market_return": float(gross[execution:finish].sum()),
                "span_overlap_arithmetic_market_return": float(
                    gross[overlap_start:overlap_end].sum()
                ),
                "span_timing_contribution": float(-0.5 * gross[overlap_start:overlap_end].sum()),
                "next_24h": compounded(gross[execution : min(execution + 24, end)]),
                "next_168h": compounded(gross[execution : min(execution + 168, end)]),
                "next_720h": compounded(gross[execution : min(execution + 720, end)]),
            }
        )
    return rows


def diagnostics(
    frame: pd.DataFrame,
    events: list[dict[str, int | str]],
    position: dict[str, np.ndarray],
    net: dict[str, np.ndarray],
    turn: dict[str, np.ndarray],
    gross: np.ndarray,
    span: tuple[int, int],
) -> dict[str, Any]:
    start, end = span
    rows = event_rows(frame, events, gross, span)
    mask = (position["candidate"][start:end] == 0.5) & (position["b1"][start:end] == 1)
    difference = position["candidate"][start:end] - position["b1"][start:end]
    timing = float((difference * gross[start:end]).sum())
    turn_difference = turn["candidate"][start:end] - turn["b1"][start:end]
    fee = float(-FEE * turn_difference.sum())
    delta = float((net["candidate"][start:end] - net["b1"][start:end]).sum())
    if abs(delta - timing - fee) > 1e-12:
        raise AssertionError("return decomposition failed")
    following: dict[str, dict[str, float]] = {}
    for horizon in (24, 168, 720):
        values = [row[f"next_{horizon}h"] for row in rows]
        following[str(horizon)] = {
            "mean": float(np.mean(values)) if values else math.nan,
            "positive_share": float(np.mean(np.asarray(values) > 0)) if values else math.nan,
        }
    event_hours = sum(int(row["span_overlap_hours"]) for row in rows)
    event_timing = float(sum(float(row["span_timing_contribution"]) for row in rows))
    if event_hours != int(mask.sum()):
        raise AssertionError("event-hour attribution failed")
    if abs(event_timing - timing) > 1e-12:
        raise AssertionError("event timing attribution failed")
    finish_counts = {
        reason: sum(row["finish_reason"] == reason for row in rows)
        for reason in ("automatic_restore", "base_exit", "sample_end")
    }
    return {
        "checkpoint_count": len(rows),
        "finish_counts": finish_counts,
        "half_state_hours": int(mask.sum()),
        "full_equivalent_exposure_removed": float(mask.sum() * 0.5),
        "arithmetic_market_return_during_half_state": float(gross[start:end][mask].sum()),
        "timing_contribution": timing,
        "event_timing_reconstruction": event_timing,
        "fee_contribution": fee,
        "arithmetic_delta": delta,
        "incremental_turnover": float(turn_difference.sum()),
        "next_returns": following,
        "events": rows,
    }


def gate_results(result: dict[str, Any]) -> dict[str, bool]:
    oos = result["oos"]
    breadth_ = result["breadth"]
    uncertainty_ = result["uncertainty"]
    c = oos["candidate"]
    b = oos["b1"]
    return {
        "return": bool(c["net_return"] > 0 and c["net_return"] >= b["net_return"]),
        "sharpe": bool(math.isfinite(c["sharpe"]) and c["sharpe"] >= b["sharpe"]),
        "drawdown": bool(c["max_drawdown"] >= b["max_drawdown"] - 1e-12),
        "turnover": bool(c["turnover"] <= b["turnover"] + 1e-12),
        "edge_per_turnover": bool(c["edge_per_turnover_bps"] >= b["edge_per_turnover_bps"]),
        "profitable_folds": bool(breadth_["profitable_folds"] >= 7),
        "profitable_years": bool(breadth_["profitable_years"] >= 3),
        "fold_concentration": bool(breadth_["positive_fold_concentration"] <= 0.5),
        "residual_sharpe": bool(breadth_["residual_sharpe"] > 0),
        "mean_uncertainty": bool(uncertainty_["mean_delta_annualized"]["ci95"][0] > 0),
        "sharpe_uncertainty": bool(uncertainty_["sharpe_delta"]["ci95"][0] > 0),
        "full_positive": bool(result["full"]["candidate"]["net_return"] > 0),
        "integrity": True,
    }


def evaluate(frame: pd.DataFrame) -> dict[str, Any]:
    position, events = positions(frame)
    net: dict[str, np.ndarray] = {}
    turn: dict[str, np.ndarray] = {}
    gross = np.empty(0)
    for name, values in position.items():
        net[name], turn[name], gross = returns(frame, values)
    result = {
        "training": {
            name: metric(net[name], turn[name], position[name], TRAIN) for name in position
        },
        "oos": {name: metric(net[name], turn[name], position[name], OOS) for name in position},
        "full": {name: metric(net[name], turn[name], position[name], FULL) for name in position},
        "breadth": breadth(frame, net["candidate"], net["b1"]),
        "uncertainty": uncertainty(net["candidate"], net["b1"]),
        "diagnostics": {
            "training": diagnostics(frame, events, position, net, turn, gross, TRAIN),
            "oos": diagnostics(frame, events, position, net, turn, gross, OOS),
        },
    }
    result["gates"] = gate_results(result)
    result["all_gates_pass"] = all(result["gates"].values())
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--btc", type=Path, required=True)
    parser.add_argument("--eth", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    paths = {"BTC-USDT": args.btc, "ETH-USDT": args.eth}
    result: dict[str, Any] = {
        "family_id": "fixed-duration-endpoint-margin-acceleration-checkpoint-1h-v1",
        "issue": 730,
        "candidate_count": 1,
        "parameter_grid_count": 0,
        "fee_one_way": FEE,
        "checkpoint_hours": CHECKPOINT,
        "source_run_id": 30567744552,
        "source_artifacts": {
            "BTC-USDT": 8769605568,
            "ETH-USDT": 8769619607,
        },
        "markets": {},
    }
    for market, path in paths.items():
        prefix = load(path, market)
        full = load(path, market, None)
        prefix_position, _ = positions(prefix)
        full_position, _ = positions(full)
        invariant = all(
            np.array_equal(
                prefix_position[name],
                full_position[name][: len(prefix) - 1],
            )
            for name in prefix_position
        )
        if not invariant:
            raise AssertionError(f"future suffix changed positions: {market}")
        result["markets"][market] = evaluate(prefix)
        result["markets"][market]["future_suffix_invariance"] = True
    bilateral = all(row["all_gates_pass"] for row in result["markets"].values())
    result["verdict"] = (
        "nominate_fixed_duration_endpoint_margin_acceleration_checkpoint_for_research_gate"
        if bilateral
        else "reject_exact_fixed_duration_endpoint_margin_acceleration_checkpoint_family"
    )
    canonical = json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False)
    result["canonical_result_sha256"] = sha(canonical.encode())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
