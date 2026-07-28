#!/usr/bin/env python3
"""Run the frozen funding/basis family with executable next-open accounting.

This wrapper does not add a strategy candidate. It repairs the active F0/F1
experiment so that a target available at an hourly boundary earns the observed
next-open-to-next-open return rather than assuming execution at the preceding
close. It also emits realized-edge diagnostics required to interpret the
unchanged strategy decisions.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

MODULE_PATH = Path(__file__).with_name("run_funding_basis_crowding_research.py")
SPEC = importlib.util.spec_from_file_location("funding_basis_core", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {MODULE_PATH}")
CORE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CORE
SPEC.loader.exec_module(CORE)


def build_hourly_next_open(events: pd.DataFrame, spot: pd.DataFrame) -> pd.DataFrame:
    """Map frozen targets to observed next-open-to-next-open returns.

    A funding event at T uses the completed derivatives candle ending at T.
    The first completed spot bar strictly after T ends at T+1H. Its target is
    executable at the observed open at T+1H and earns open(T+1H)->open(T+2H).
    Return rows remain labelled by their end timestamp, preserving the frozen
    evaluation calendar and fold boundaries.
    """

    frame = spot[["open_time_ms", "open", "close"]].copy()
    frame["execution_open_time_ms"] = frame["open_time_ms"]
    frame["close_time_ms"] = frame["open_time_ms"] + CORE.HOUR_MS
    frame = frame.set_index("close_time_ms")

    event_times = set(events["funding_time_ms"].astype(int))
    actions: dict[int, tuple[float, float, str]] = {}
    for row in events.itertuples(index=False):
        timestamp = int(row.funding_time_ms)
        actions[timestamp + CORE.HOUR_MS] = (
            float(row.target_f0),
            float(row.target_f1),
            "event",
        )
        if row.interval_hours in {1.0, 2.0, 4.0, 6.0, 8.0}:
            deadline = timestamp + int(float(row.interval_hours) * CORE.HOUR_MS)
            if deadline not in event_times:
                actions[deadline + CORE.HOUR_MS] = (0.0, 0.0, "expiry")

    current_f0 = current_f1 = 0.0
    targets_f0: list[float] = []
    targets_f1: list[float] = []
    reasons: list[str] = []
    for row in frame.itertuples():
        execution_time = int(row.execution_open_time_ms)
        if execution_time in actions:
            current_f0, current_f1, reason = actions[execution_time]
        else:
            reason = "carry"
        targets_f0.append(current_f0)
        targets_f1.append(current_f1)
        reasons.append(reason)

    frame["target_f0"] = targets_f0
    frame["target_f1"] = targets_f1
    frame["action_reason"] = reasons
    frame["spot_return"] = frame["open"].shift(-1) / frame["open"] - 1.0
    frame["prior_close_to_execution_open_gap"] = (
        frame["open"] / frame["close"].shift(1) - 1.0
    )

    for policy in ("f0", "f1"):
        frame[f"position_{policy}"] = frame[f"target_{policy}"]
        turnover = frame[f"position_{policy}"].diff().abs()
        turnover.iloc[0] = abs(float(frame[f"position_{policy}"].iloc[0]))
        frame[f"turnover_{policy}"] = turnover
        frame[f"gross_return_{policy}"] = frame[f"position_{policy}"] * frame["spot_return"]
        frame[f"net_return_{policy}"] = (
            frame[f"gross_return_{policy}"] - CORE.FEE * turnover
        )

    # At open h, only the bar ending at h is complete. The frozen 2160H trend
    # therefore uses close[h-1] versus close[h-2161].
    trend_target = (
        frame["close"].shift(1) / frame["close"].shift(2161) - 1.0 > 0
    ).astype(float)
    frame["position_trend"] = trend_target
    trend_turnover = frame["position_trend"].diff().abs()
    trend_turnover.iloc[0] = abs(float(frame["position_trend"].iloc[0]))
    frame["turnover_trend"] = trend_turnover
    frame["gross_return_trend"] = frame["position_trend"] * frame["spot_return"]
    frame["net_return_trend"] = frame["gross_return_trend"] - CORE.FEE * trend_turnover
    return frame.reset_index()


_ORIGINAL_METRICS = CORE.metrics


def metrics_with_realized_edge(
    frame: pd.DataFrame, policy: str, fold_ids: np.ndarray
) -> dict[str, Any]:
    result = _ORIGINAL_METRICS(frame, policy, fold_ids)
    turnover = frame[f"turnover_{policy}"].to_numpy(dtype=float)
    changes = np.flatnonzero(turnover > 0)
    holding = np.diff(changes) if len(changes) > 1 else np.array([], dtype=int)
    gaps = frame["prior_close_to_execution_open_gap"].to_numpy(dtype=float)
    trade_gaps = np.abs(gaps[turnover > 0]) * 10_000.0
    trade_gaps = trade_gaps[np.isfinite(trade_gaps)]
    result.update(
        {
            "mean_holding_hours": None if not len(holding) else float(np.mean(holding)),
            "no_trade_frequency": float(np.mean(turnover == 0.0)),
            "mean_abs_prior_close_to_execution_open_gap_bps_on_adjustments": (
                None if not len(trade_gaps) else float(np.mean(trade_gaps))
            ),
            "max_abs_prior_close_to_execution_open_gap_bps_on_adjustments": (
                None if not len(trade_gaps) else float(np.max(trade_gaps))
            ),
        }
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    CORE.build_hourly = build_hourly_next_open
    CORE.metrics = metrics_with_realized_edge
    result = CORE.run(args.output_dir)
    result["availability"] = (
        "funding event T uses the completed mark/index candle ending at T; "
        "the target is formed when the first completed spot bar after T ends, "
        "then evaluated from the observed open at that boundary to the next observed hourly open"
    )
    result["execution_semantics"] = "observed_next_open_to_next_open"
    result["methodological_repair"] = (
        "replaced close-to-close return attribution with observed next-open-to-next-open "
        "accounting without changing F0/F1 targets, fees, folds, thresholds, or candidate count"
    )
    result["fill_diagnostics"] = {
        "available": False,
        "observed_data": "hourly OHLC opens only",
        "not_observed": [
            "spread",
            "slippage",
            "market impact",
            "queue position",
            "fill probability",
            "partial fills",
            "adverse selection",
        ],
        "interpretation": "the observed next open is a deterministic stress endpoint, not an assumed executable fill",
    }
    result_bytes = CORE.canonical_bytes(CORE.finite(result))
    (args.output_dir / "result-summary.json").write_bytes(result_bytes)
    (args.output_dir / "result-summary.sha256").write_text(
        f"{CORE.sha256(result_bytes)}  result-summary.json\n"
    )
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
