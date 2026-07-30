from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

FEE = 0.0005
TREND = 2160
TRAIN = (720, 9360)
OOS = (9360, 26640)
FULL = (720, 26640)
BLOCK = 168
RESAMPLES = 5000
SEED = 20260730
TRADE_SHA = "ffe94da2b8f7ae2357882398e1ed85d787d4a9fb4898ac98fa2604290b9c22c9"
CANDLE_SHA = "92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9"
VERDICT = "reject_exact_onset_aggressive_flow_absorption_selector_family"


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sharpe(values: np.ndarray) -> float:
    return float(math.sqrt(8760.0) * values.mean() / values.std(ddof=1))


def metric(
    returns: np.ndarray,
    gross: np.ndarray,
    turns: np.ndarray,
    start: int,
    end: int,
) -> dict[str, float]:
    net = returns[start:end]
    raw = gross[start:end]
    turnover = float(turns[start:end].sum())
    equity = np.cumprod(1.0 + net)
    path = np.concatenate(([1.0], equity))
    peak = np.maximum.accumulate(path)
    return {
        "gross_return": float(np.prod(1.0 + raw) - 1.0),
        "net_return": float(equity[-1] - 1.0),
        "sharpe": sharpe(net),
        "max_drawdown": float(np.min(path / peak - 1.0)),
        "turnover": turnover,
        "fees": turnover * FEE,
        "edge_per_turnover_bps": float(net.sum() / turnover * 10000.0),
    }


def positions(
    candles: pd.DataFrame,
    trades: pd.DataFrame,
    candle_start: int,
) -> tuple[np.ndarray, np.ndarray, list[dict[str, float | int | bool]]]:
    rows = len(trades)
    close = candles["close"].to_numpy(float)
    signed = trades["signed_quote_notional"].to_numpy(float)
    total = trades["total_quote_notional"].to_numpy(float)
    benchmark_updates: dict[int, float] = {}
    candidate_updates: dict[int, float] = {}
    events: list[dict[str, float | int | bool]] = []
    candidate_state = 0.0

    for local in range(rows):
        global_index = candle_start + local
        timestamp = trades["timestamp"].iloc[local]
        if timestamp.hour != 0:
            continue
        base = close[global_index] > close[global_index - TREND]
        previous = close[global_index - 24] > close[global_index - 24 - TREND]
        execution = local + 1
        benchmark_updates[execution] = float(base)
        if not base:
            candidate_state = 0.0
        elif not previous:
            flow = float(
                signed[local - 23 : local + 1].sum()
                / total[local - 23 : local + 1].sum()
            )
            price = float(math.log(close[global_index] / close[global_index - 24]))
            veto = flow < 0.0 and price < 0.0
            candidate_state = 0.0 if veto else 1.0
            events.append(
                {
                    "decision": local,
                    "execution": execution,
                    "flow24": flow,
                    "price24": price,
                    "veto": veto,
                }
            )
        candidate_updates[execution] = candidate_state

    def fill(updates: dict[int, float]) -> np.ndarray:
        output = np.zeros(rows + 1)
        state = 0.0
        for index in range(rows + 1):
            state = updates.get(index, state)
            output[index] = state
        return output

    return fill(benchmark_updates), fill(candidate_updates), events


def blocks(length: int, rng: np.random.Generator) -> np.ndarray:
    selected: list[int] = []
    while len(selected) < length:
        start = int(rng.integers(0, length - BLOCK + 1))
        selected.extend(range(start, start + BLOCK))
    return np.asarray(selected[:length])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candles", type=Path, required=True)
    parser.add_argument("--trade-features", type=Path, required=True)
    args = parser.parse_args()

    if file_sha(args.candles) != CANDLE_SHA:
        raise SystemExit("candle SHA mismatch")
    if file_sha(args.trade_features) != TRADE_SHA:
        raise SystemExit("trade-feature SHA mismatch")

    candles = pd.read_csv(args.candles)
    trades = pd.read_csv(args.trade_features)
    candles["timestamp"] = pd.to_datetime(candles["timestamp"], utc=True)
    trades["timestamp"] = pd.to_datetime(trades["timestamp"], utc=True)
    if len(trades) != 26640:
        raise SystemExit("unexpected trade-feature row count")
    expected = pd.date_range(trades["timestamp"].iloc[0], periods=len(trades), freq="h")
    if not np.array_equal(expected.to_numpy(), trades["timestamp"].to_numpy()):
        raise SystemExit("non-contiguous trade chronology")

    matches = candles.index[
        candles["timestamp"].eq(trades["timestamp"].iloc[0])
    ].tolist()
    if len(matches) != 1:
        raise SystemExit("candle/trade alignment failed")
    candle_start = int(matches[0])
    aligned = candles.iloc[candle_start : candle_start + len(trades) + 1]
    if not np.array_equal(
        aligned["timestamp"].iloc[:-1].to_numpy(),
        trades["timestamp"].to_numpy(),
    ):
        raise SystemExit("candle/trade timestamp mismatch")

    benchmark_pos, candidate_pos, events = positions(
        candles,
        trades,
        candle_start,
    )
    market = aligned["open"].to_numpy(float)
    market = market[1:] / market[:-1] - 1.0
    benchmark_turn = np.abs(np.diff(np.r_[0.0, benchmark_pos[:-1]]))
    candidate_turn = np.abs(np.diff(np.r_[0.0, candidate_pos[:-1]]))
    benchmark_gross = benchmark_pos[:-1] * market
    candidate_gross = candidate_pos[:-1] * market
    benchmark_net = benchmark_gross - FEE * benchmark_turn
    candidate_net = candidate_gross - FEE * candidate_turn

    samples = {}
    for name, (start, end) in {
        "training": TRAIN,
        "development_oos": OOS,
        "full_scored": FULL,
    }.items():
        samples[name] = {
            "candidate": metric(
                candidate_net,
                candidate_gross,
                candidate_turn,
                start,
                end,
            ),
            "benchmark": metric(
                benchmark_net,
                benchmark_gross,
                benchmark_turn,
                start,
                end,
            ),
        }

    folds = []
    for fold in range(8):
        start = OOS[0] + fold * 2160
        end = start + 2160
        candidate = float(np.prod(1.0 + candidate_net[start:end]) - 1.0)
        benchmark = float(np.prod(1.0 + benchmark_net[start:end]) - 1.0)
        folds.append(
            {
                "candidate": candidate,
                "benchmark": benchmark,
                "profitable": candidate > 0.0,
                "improved": candidate > benchmark + 1e-15,
            }
        )

    residual = candidate_net[OOS[0] : OOS[1]] - benchmark_net[OOS[0] : OOS[1]]
    rng = np.random.default_rng(SEED)
    mean_delta = np.empty(RESAMPLES)
    sharpe_delta = np.empty(RESAMPLES)
    candidate_oos = candidate_net[OOS[0] : OOS[1]]
    benchmark_oos = benchmark_net[OOS[0] : OOS[1]]
    for sample in range(RESAMPLES):
        index = blocks(len(candidate_oos), rng)
        candidate_draw = candidate_oos[index]
        benchmark_draw = benchmark_oos[index]
        mean_delta[sample] = (
            candidate_draw.mean() - benchmark_draw.mean()
        ) * 8760.0
        sharpe_delta[sample] = sharpe(candidate_draw) - sharpe(benchmark_draw)

    exposure_gap = benchmark_pos[OOS[0] : OOS[1]] - candidate_pos[OOS[0] : OOS[1]]
    omitted = float(np.sum(exposure_gap * market[OOS[0] : OOS[1]]))
    fee_delta = float(
        np.sum(candidate_turn[OOS[0] : OOS[1]] - benchmark_turn[OOS[0] : OOS[1]])
        * FEE
    )
    arithmetic_delta = float(residual.sum())
    if abs(arithmetic_delta - (-omitted - fee_delta)) > 1e-12:
        raise SystemExit("return decomposition failed")

    result = {
        "architecture": "onset-aggressive-flow-absorption-selector-1h-v1",
        "candidate_count": 1,
        "parameter_grid_count": 0,
        "metrics": samples,
        "profitable_folds": sum(row["profitable"] for row in folds),
        "improved_folds": sum(row["improved"] for row in folds),
        "residual_sharpe": sharpe(residual),
        "annualized_mean_delta_95": np.quantile(
            mean_delta,
            [0.025, 0.975],
        ).tolist(),
        "sharpe_delta_95": np.quantile(
            sharpe_delta,
            [0.025, 0.975],
        ).tolist(),
        "oos_vetoes": sum(
            event["veto"] and event["decision"] >= OOS[0]
            for event in events
        ),
        "oos_benchmark_only_hours": float(exposure_gap.sum()),
        "omitted_market_carry": omitted,
        "fee_delta": fee_delta,
        "arithmetic_delta": arithmetic_delta,
        "verdict": VERDICT,
    }
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
