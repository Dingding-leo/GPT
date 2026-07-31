#!/usr/bin/env python3
"""Run the frozen analog-conditioned weekly B1-sleeve payoff sizing experiment."""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
PARENT_PATH = (
    ROOT
    / "reports/research/analog-conditioned-weekly-payoff-efficiency-sizing-1h-v1"
    / "run_experiment.py"
)
SPEC = importlib.util.spec_from_file_location("analog_payoff_parent", PARENT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("unable to load frozen analog-payoff evaluation framework")
parent = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(parent)

FAMILY_ID = "analog-conditioned-weekly-b1-sleeve-payoff-sizing-1h-v1"
ISSUE = 787
MIN_HISTORY = 64
NEIGHBOURS = 32
FIXED_MARKETS = ["KSM-USDT", "IOTA-USDT"]

ORIGINAL_EVALUATE = parent.evaluate_market


def path_from_signal(signal: np.ndarray, opens: np.ndarray) -> dict[str, np.ndarray]:
    """Map completed-bar signals to causal next-open net-return paths."""
    length = len(opens)
    position = np.zeros(length - 1, dtype=float)
    position[1:] = signal[:-2]
    changes = np.abs(position - np.r_[0.0, position[:-1]])
    market_return = opens[1:] / opens[:-1] - 1.0
    gross = position * market_return
    fee = parent.fw.FEE * changes
    return {
        "signal": signal,
        "position": position,
        "changes": changes,
        "gross": gross,
        "fee": fee,
        "net": gross - fee,
    }


def self_contained_b1_sleeve_label(
    anchor: int,
    daily_b1: np.ndarray,
    opens: np.ndarray,
) -> float:
    """Return the exact net payoff of a cash-funded 168H B1 sleeve."""
    positions = daily_b1[anchor : anchor + 168].astype(float)
    decision_indices = np.arange(anchor, anchor + 168)
    returns = opens[decision_indices + 2] / opens[decision_indices + 1] - 1.0
    gross = float(np.sum(positions * returns))
    turnover = float(
        positions[0]
        + np.sum(np.abs(np.diff(positions)))
        + positions[-1]
    )
    return gross - parent.fw.FEE * turnover


def build_paths(market: dict[str, Any]) -> dict[str, Any]:
    """Build the aligned candidate and frozen comparator paths."""
    timestamps = market["timestamps"]
    closes = market["closes"]
    opens = market["opens"]
    length = len(closes)
    feature_values = parent.fw.features(market)

    base = np.zeros(length, dtype=np.int8)
    base[2_160:] = (closes[2_160:] > closes[:-2_160]).astype(np.int8)

    daily_b1 = np.zeros(length, dtype=np.int8)
    current_b1 = 0
    for time_index in range(2_160, length):
        if timestamps.iloc[time_index].hour == 0:
            current_b1 = int(base[time_index])
        daily_b1[time_index] = current_b1

    candidate = np.zeros(length, dtype=float)
    weekly_size = np.ones(length, dtype=float)
    decision_mask = np.zeros(length, dtype=bool)
    history_rows = np.zeros(length, dtype=np.int32)
    efficiency = np.full(length, np.nan)
    neighbor_mean = np.full(length, np.nan)
    neighbor_positive_fraction = np.full(length, np.nan)
    realized_label = np.full(length, np.nan)

    anchors = np.flatnonzero(
        (timestamps.dt.dayofweek.to_numpy() == 0)
        & (timestamps.dt.hour.to_numpy() == 0)
    )
    anchor_set = set(int(value) for value in anchors)
    complete_labels = {
        int(anchor): self_contained_b1_sleeve_label(int(anchor), daily_b1, opens)
        for anchor in anchors
        if anchor >= 2_160 and anchor + 169 < length
    }

    current_size = 1.0
    current_candidate = 0.0
    activation_index: int | None = None

    for time_index in range(2_160, length):
        if time_index in anchor_set:
            decision_mask[time_index] = True
            eligible = anchors[
                (anchors >= 2_160) & (anchors + 169 <= time_index)
            ]
            history_rows[time_index] = len(eligible)
            if time_index in complete_labels:
                realized_label[time_index] = complete_labels[time_index]
            if len(eligible) >= MIN_HISTORY:
                if activation_index is None:
                    activation_index = time_index
                historical_features = feature_values[eligible]
                centre = np.median(historical_features, axis=0)
                scale = np.median(np.abs(historical_features - centre), axis=0)
                scale[~np.isfinite(scale) | (scale <= 0)] = 1.0
                scaled_history = (historical_features - centre) / scale
                scaled_query = (feature_values[time_index] - centre) / scale
                distance = np.sum((scaled_history - scaled_query) ** 2, axis=1)
                order = np.lexsort((eligible, distance))[:NEIGHBOURS]
                neighbours = eligible[order]
                labels = np.asarray(
                    [complete_labels[int(index)] for index in neighbours],
                    dtype=float,
                )
                numerator = float(np.sum(labels))
                denominator = float(np.sum(np.abs(labels)))
                score = numerator / denominator if denominator > 0 else 0.0
                current_size = float(np.clip((1.0 + score) / 2.0, 0.0, 1.0))
                efficiency[time_index] = score
                neighbor_mean[time_index] = float(np.mean(labels))
                neighbor_positive_fraction[time_index] = float(np.mean(labels > 0))
            else:
                current_size = 1.0

        if timestamps.iloc[time_index].hour == 0:
            current_candidate = float(daily_b1[time_index]) * current_size

        weekly_size[time_index] = current_size
        candidate[time_index] = current_candidate

    if np.any(candidate < 0) or np.any(candidate > daily_b1 + 1e-12):
        raise ValueError("candidate exposure is outside the frozen B1 subset")
    if np.any(weekly_size < 0) or np.any(weekly_size > 1):
        raise ValueError("weekly size is outside [0, 1]")

    signals = {
        "candidate": candidate,
        "B0": base.astype(float),
        "B1": daily_b1.astype(float),
    }
    paths = {name: path_from_signal(signal, opens) for name, signal in signals.items()}

    fixed_half_signal = daily_b1.astype(float)
    exposure_matched_signal = daily_b1.astype(float)
    exposure_matched_multiplier = 1.0
    if activation_index is not None:
        fixed_half_signal = daily_b1.astype(float).copy()
        fixed_half_signal[activation_index:] *= 0.5

        start = max(parent.fw.OOS[0], activation_index)
        end = parent.fw.OOS[1]
        candidate_exposure = float(np.sum(candidate[start:end]))
        benchmark_exposure = float(np.sum(daily_b1[start:end]))
        if benchmark_exposure > 0:
            exposure_matched_multiplier = float(
                np.clip(candidate_exposure / benchmark_exposure, 0.0, 1.0)
            )
        exposure_matched_signal = daily_b1.astype(float).copy()
        exposure_matched_signal[activation_index:] *= exposure_matched_multiplier

    controls = {
        "fixed_half": path_from_signal(fixed_half_signal, opens),
        "exposure_matched_constant": path_from_signal(
            exposure_matched_signal,
            opens,
        ),
    }

    return {
        "paths": paths,
        "controls": controls,
        "decision_mask": decision_mask,
        "history_rows": history_rows,
        "efficiency": efficiency,
        "neighbor_mean": neighbor_mean,
        "neighbor_positive_fraction": neighbor_positive_fraction,
        "realized_label": realized_label,
        "weekly_size": weekly_size,
        "base": base,
        "daily_b1": daily_b1,
        "activation_index": activation_index,
        "exposure_matched_multiplier": exposure_matched_multiplier,
    }


def evaluate_market(
    instrument: str,
    market: dict[str, Any],
    built: dict[str, Any],
    starts: np.ndarray,
) -> dict[str, Any]:
    """Evaluate frozen gates plus preregistered constant-sizing attribution controls."""
    result = ORIGINAL_EVALUATE(instrument, market, built, starts)
    start, end = parent.fw.OOS
    candidate_arithmetic = float(
        np.sum(built["paths"]["candidate"]["net"][start:end])
    )
    controls = {
        name: parent.fw.metrics(path, start, end)
        for name, path in built["controls"].items()
    }
    fixed_half_arithmetic = float(
        np.sum(built["controls"]["fixed_half"]["net"][start:end])
    )
    matched_arithmetic = float(
        np.sum(
            built["controls"]["exposure_matched_constant"]["net"][start:end]
        )
    )
    result["gates"]["adaptive_beats_fixed_half_arithmetic"] = (
        candidate_arithmetic > fixed_half_arithmetic
    )
    result["gates"]["adaptive_beats_exposure_matched_constant_arithmetic"] = (
        candidate_arithmetic > matched_arithmetic
    )
    result["accepted"] = all(result["gates"].values())

    activation_index = built["activation_index"]
    result["aligned_label_diagnostics"] = {
        "activation_index": activation_index,
        "activation_timestamp": (
            market["timestamps"].iloc[activation_index].isoformat()
            if activation_index is not None
            else None
        ),
        "exposure_matched_multiplier": built["exposure_matched_multiplier"],
        "candidate_oos_arithmetic_net": candidate_arithmetic,
        "fixed_half_oos_arithmetic_net": fixed_half_arithmetic,
        "exposure_matched_constant_oos_arithmetic_net": matched_arithmetic,
        "control_metrics": controls,
    }
    return result


def run(args: argparse.Namespace) -> dict[str, Any]:
    """Run the inherited deterministic scorecard with the aligned target."""
    parent.FAMILY_ID = FAMILY_ID
    parent.ISSUE = ISSUE
    parent.MIN_HISTORY = MIN_HISTORY
    parent.NEIGHBOURS = NEIGHBOURS
    parent.build_paths = build_paths
    parent.evaluate_market = evaluate_market
    result = parent.run(args)
    result["family_id"] = FAMILY_ID
    result["issue"] = ISSUE
    result["model"] = {
        "direction": "daily 2160H endpoint trend",
        "features": "six fixed own-history return, volatility, downside and drawdown features",
        "history": "all strictly prior Monday anchors with fully observed self-contained labels",
        "minimum_history": MIN_HISTORY,
        "neighbors": NEIGHBOURS,
        "label": "self-contained next-168H daily-B1 sleeve net payoff including start, internal and terminal 5-bps turnover",
        "efficiency": "sum(label) / sum(abs(label))",
        "weekly_size": "clip((1 + efficiency) / 2, 0, 1); fallback 1",
    }
    result["accepted"] = (
        all(item["accepted"] for item in result["markets"])
        and parent.fw.ci_lower_positive(
            result["common_bootstrap_vs_B1"]["annualized_mean_delta_ci95"]
        )
        and parent.fw.ci_lower_positive(
            result["common_bootstrap_vs_B1"]["sharpe_delta_ci95"]
        )
    )
    result["verdict"] = (
        "support_b1_sleeve_payoff_sizing_research_nomination"
        if result["accepted"]
        else "reject_b1_sleeve_payoff_sizing_family"
    )
    return result


def report(result: dict[str, Any]) -> str:
    """Render the inherited report plus target-alignment attribution controls."""
    text = parent.report(result)
    text = text.replace(
        "# Analog-conditioned weekly payoff-efficiency sizing evidence",
        "# Analog-conditioned weekly B1-sleeve payoff sizing evidence",
        1,
    )
    lines = [text, "", "## Aligned-label attribution controls", ""]
    for item in result["markets"]:
        values = item["aligned_label_diagnostics"]
        lines.extend(
            [
                f"### {item['instrument']}",
                "",
                f"Activation: {values['activation_timestamp']}; exposure-matched multiplier "
                f"{values['exposure_matched_multiplier']:.6f}.",
                "",
                f"OOS arithmetic net: adaptive {values['candidate_oos_arithmetic_net']:+.4%}; "
                f"fixed-half {values['fixed_half_oos_arithmetic_net']:+.4%}; "
                f"exposure-matched constant "
                f"{values['exposure_matched_constant_oos_arithmetic_net']:+.4%}.",
                "",
            ]
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--instrument", action="append", required=True)
    parser.add_argument("--resamples", type=int, default=5_000)
    parser.add_argument("--seed", type=int, default=20_260_731)
    parser.add_argument("--source-workflow-run", default="local")
    parser.add_argument("--tested-sha", default="local")
    args = parser.parse_args()
    if list(args.instrument) != FIXED_MARKETS:
        raise ValueError("fixed preperformance instruments changed")

    result = run(args)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    result_path = args.output_dir / "result.json"
    result_path.write_bytes(parent.fw.canonical_bytes(result))
    summary = {
        "family_id": result["family_id"],
        "tested_sha": result["tested_sha"],
        "candidate_count": 1,
        "parameter_grid": 0,
        "markets_passing_every_gate": result["markets_passing_every_gate"],
        "verdict": result["verdict"],
        "result_sha256": parent.fw.sha256_file(result_path),
        "market_headlines": {
            item["instrument"]: {
                "candidate_oos": item["performance"]["oos"]["candidate"],
                "B1_oos": item["performance"]["oos"]["B1"],
                "breadth": item["breadth"],
                "residual_sharpe_vs_B1": item["residual_sharpe_vs_B1"],
                "aligned_label_diagnostics": item["aligned_label_diagnostics"],
                "accepted": item["accepted"],
            }
            for item in result["markets"]
        },
    }
    (args.output_dir / "result-summary.json").write_bytes(
        parent.fw.canonical_bytes(summary)
    )
    (args.output_dir / "report.md").write_text(report(result), encoding="utf-8")


if __name__ == "__main__":
    main()
