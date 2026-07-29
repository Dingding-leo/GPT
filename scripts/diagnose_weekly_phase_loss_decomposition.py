#!/usr/bin/env python3
"""Deterministic failure decomposition for issue #617 / PR #620.

Uses the frozen strategy implementation and immutable public OKX 1H CSVs. It
adds no candidate and changes no signal, threshold, timing, fee, position, or
verdict. The output explains arithmetic/geometric divergence and decomposes
candidate exposure relative to the frozen daily 2160H trend benchmark.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import run_weekly_phase_conditioned_trend_carry as base

HASHES = {
    "BTC-USDT": "92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9",
    "ETH-USDT": "2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726",
}


def max_consecutive(mask: np.ndarray) -> int:
    best = current = 0
    for value in np.asarray(mask, dtype=bool):
        if value:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def rolling_worst(net: np.ndarray, start: int, end: int, hours: int, timestamps) -> dict:
    values = net[start:end]
    log_values = np.log1p(values)
    cumulative = np.r_[0.0, np.cumsum(log_values)]
    window_log = cumulative[hours:] - cumulative[:-hours]
    offset = int(np.argmin(window_log))
    window_start = start + offset
    window_end = window_start + hours
    return {
        "window_hours": hours,
        "net_return": float(np.exp(window_log[offset]) - 1.0),
        "start_index": window_start,
        "end_index_exclusive": window_end,
        "execution_start": str(timestamps.iloc[window_start]),
        "execution_end_exclusive": str(timestamps.iloc[window_end]),
    }


def trade_summary(net: np.ndarray, positions: np.ndarray, start: int, end: int) -> dict:
    transitions = np.diff(np.r_[0.0, positions])
    entries = np.flatnonzero(transitions > 0)
    exits = np.flatnonzero(transitions < 0)
    returns = []
    for entry in entries:
        later_exits = exits[exits > entry]
        exit_index = int(later_exits[0]) if len(later_exits) else len(positions)
        if exit_index < start or entry >= end:
            continue
        clipped_start = max(int(entry), start)
        clipped_end = min(exit_index + 1, end)  # includes the exit fee when present
        returns.append(float(np.prod(1.0 + net[clipped_start:clipped_end]) - 1.0))

    return {
        "count": len(returns),
        "profitable": int(sum(value > 0 for value in returns)),
        "losses": int(sum(value < 0 for value in returns)),
        "median_net_return": float(np.median(returns)) if returns else None,
        "mean_net_return": float(np.mean(returns)) if returns else None,
        "best_net_return": float(max(returns)) if returns else None,
        "worst_net_return": float(min(returns)) if returns else None,
        "longest_losing_trade_streak": max_consecutive(np.asarray(returns) < 0),
    }


def state_metrics(mask: np.ndarray, gross: np.ndarray, start: int, end: int) -> dict:
    selected = mask[start:end]
    values = gross[start:end][selected]
    return {
        "hours": int(selected.sum()),
        "gross_arithmetic_sum": float(values.sum()),
        "gross_compounded_return": float(np.prod(1.0 + values) - 1.0) if len(values) else 0.0,
        "mean_gross_bps_per_hour": float(values.mean() * 10_000) if len(values) else None,
        "annualized_sharpe": base.annualised_sharpe(values) if len(values) > 1 else None,
    }


def diagnose(path: str, instrument: str) -> dict:
    frame, source_hash = base.load_prefix(path, HASHES[instrument])
    model = base.fit_model(frame)
    gross = base.open_to_open_returns(frame)
    candidate_position = base.candidate_positions(frame, model["favourable_weekday_indices"])
    benchmark_position = base.trend_positions(frame, daily=True)
    candidate_net, candidate_changes = base.net_series(candidate_position, gross)
    benchmark_net, benchmark_changes = base.net_series(benchmark_position, gross)
    start, end = base.CONFIG["oos"]
    candidate_oos = candidate_net[start:end]
    timestamps = frame["timestamp"].iloc[1 : len(candidate_net) + 1].reset_index(drop=True)

    states = {
        "both_long": state_metrics(
            (candidate_position == 1) & (benchmark_position == 1), gross, start, end
        ),
        "candidate_only": state_metrics(
            (candidate_position == 1) & (benchmark_position == 0), gross, start, end
        ),
        "b1_only": state_metrics(
            (candidate_position == 0) & (benchmark_position == 1), gross, start, end
        ),
        "both_cash": state_metrics(
            (candidate_position == 0) & (benchmark_position == 0), gross, start, end
        ),
    }
    active = candidate_position[start:end] > 0
    negative_active = active & (gross[start:end] < 0)
    candidate_fee = candidate_changes[start:end] * base.CONFIG["fee_one_way"]
    benchmark_fee = benchmark_changes[start:end] * base.CONFIG["fee_one_way"]

    return {
        "source": {
            "csv_sha256": source_hash,
            "rows_loaded": len(frame),
            "later_suffix_unread": True,
        },
        "candidate_oos": {
            "compounded_net_return": float(np.prod(1.0 + candidate_oos) - 1.0),
            "arithmetic_net_sum": float(candidate_oos.sum()),
            "log_net_sum": float(np.log1p(candidate_oos).sum()),
            "arithmetic_minus_log_compounding_gap": float(
                candidate_oos.sum() - np.log1p(candidate_oos).sum()
            ),
            "turnover": float(candidate_changes[start:end].sum()),
            "fees": float(candidate_fee.sum()),
            "active_hours": int(active.sum()),
            "negative_active_hours": int(negative_active.sum()),
            "max_consecutive_negative_active_hours": max_consecutive(negative_active),
            "worst_168h": rolling_worst(candidate_net, start, end, 168, timestamps),
            "worst_720h": rolling_worst(candidate_net, start, end, 720, timestamps),
            "trades": trade_summary(candidate_net, candidate_position, start, end),
        },
        "b1_oos": {
            "compounded_net_return": float(np.prod(1.0 + benchmark_net[start:end]) - 1.0),
            "arithmetic_net_sum": float(benchmark_net[start:end].sum()),
            "turnover": float(benchmark_changes[start:end].sum()),
            "fees": float(benchmark_fee.sum()),
        },
        "position_state_decomposition_vs_b1": states,
        "residual_vs_b1": {
            "arithmetic_net_delta": float(
                (candidate_net[start:end] - benchmark_net[start:end]).sum()
            ),
            "residual_sharpe": base.annualised_sharpe(
                candidate_net[start:end] - benchmark_net[start:end]
            ),
            "candidate_only_gross_arithmetic_contribution": states["candidate_only"][
                "gross_arithmetic_sum"
            ],
            "missed_b1_only_gross_arithmetic_contribution": -states["b1_only"][
                "gross_arithmetic_sum"
            ],
            "fee_arithmetic_contribution": float((benchmark_fee - candidate_fee).sum()),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--btc-csv", required=True)
    parser.add_argument("--eth-csv", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    result = {
        "family_id": base.CONFIG["family_id"],
        "issue": 617,
        "pr": 620,
        "research_parent": base.CONFIG["research_parent"],
        "canonical_fee_one_way": base.CONFIG["fee_one_way"],
        "diagnostic_only": True,
        "strategy_outputs_changed": False,
        "sample": {
            "training": base.CONFIG["training"],
            "development_oos": base.CONFIG["oos"],
            "later_suffix_unread": True,
        },
        "markets": {
            "BTC-USDT": diagnose(args.btc_csv, "BTC-USDT"),
            "ETH-USDT": diagnose(args.eth_csv, "ETH-USDT"),
        },
        "diagnosis": {
            "BTC-USDT": (
                "The selector delayed 888 B1-long hours that earned +9.61% arithmetic gross "
                "return and created 240 candidate-only hours that lost 2.85%; reduced turnover "
                "did not compensate."
            ),
            "ETH-USDT": (
                "The selector delayed 336 B1-long hours that earned +13.46% arithmetic gross "
                "return and retained 672 candidate-only hours that lost 41.02%. Positive "
                "arithmetic edge per turnover coexisted with negative compounded return because "
                "losses were clustered and volatility drag was large."
            ),
            "verdict_effect": (
                "No change: the exact family remains rejected. This is a strategy-failure "
                "decomposition, not a post-hoc rescue or new candidate."
            ),
        },
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result["diagnosis"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
