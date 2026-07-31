#!/usr/bin/env python3
"""Run the frozen lagged realised B1-payoff state-sizing experiment."""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
PARENT_PATH = (
    ROOT
    / "reports/research/analog-conditioned-weekly-b1-sleeve-payoff-sizing-1h-v1"
    / "run_experiment.py"
)
SPEC = importlib.util.spec_from_file_location("b1_sleeve_parent", PARENT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("unable to load frozen B1-sleeve evaluation framework")
parent = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(parent)

FAMILY_ID = "lagged-realised-b1-payoff-state-sizing-1h-v1"
ISSUE = 790
FIXED_MARKETS = ["ZEC-USDT", "DASH-USDT"]


def trailing_completed_b1_payoff(
    anchor: int,
    daily_b1: np.ndarray,
    opens: np.ndarray,
) -> float:
    """Return the latest fully observed self-contained 168H B1 payoff."""
    start = anchor - 169
    stop = anchor - 1
    positions = daily_b1[start:stop].astype(float)
    if len(positions) != 168:
        raise ValueError("trailing B1 sleeve must contain exactly 168 decisions")
    decision_indices = np.arange(start, stop)
    returns = opens[decision_indices + 2] / opens[decision_indices + 1] - 1.0
    gross = float(np.sum(positions * returns))
    turnover = float(positions[0] + np.sum(np.abs(np.diff(positions))) + positions[-1])
    return gross - parent.parent.fw.FEE * turnover


def build_paths(market: dict[str, Any]) -> dict[str, Any]:
    """Build candidate, comparators, controls, and causal payoff-state diagnostics."""
    timestamps = market["timestamps"]
    closes = market["closes"]
    opens = market["opens"]
    length = len(closes)

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
    lagged_payoff = np.full(length, np.nan)

    anchors = np.flatnonzero(
        (timestamps.dt.dayofweek.to_numpy() == 0) & (timestamps.dt.hour.to_numpy() == 0)
    )
    anchor_set = set(int(value) for value in anchors)
    current_size = 1.0
    current_candidate = 0.0
    activation_index: int | None = None

    for time_index in range(2_160, length):
        if time_index in anchor_set:
            decision_mask[time_index] = True
            if time_index >= 2_160 + 169:
                if activation_index is None:
                    activation_index = time_index
                payoff = trailing_completed_b1_payoff(time_index, daily_b1, opens)
                lagged_payoff[time_index] = payoff
                history_rows[time_index] = 1
                efficiency[time_index] = 1.0 if payoff > 0 else -1.0
                neighbor_mean[time_index] = payoff
                neighbor_positive_fraction[time_index] = float(payoff > 0)
                current_size = 1.0 if payoff > 0 else 0.5
            else:
                current_size = 1.0

            if time_index + 169 < length:
                realized_label[time_index] = parent.self_contained_b1_sleeve_label(
                    time_index,
                    daily_b1,
                    opens,
                )

        if timestamps.iloc[time_index].hour == 0:
            current_candidate = float(daily_b1[time_index]) * current_size

        weekly_size[time_index] = current_size
        candidate[time_index] = current_candidate

    if np.any(candidate < 0) or np.any(candidate > daily_b1 + 1e-12):
        raise ValueError("candidate exposure is outside the frozen B1 subset")
    if np.any(~np.isin(weekly_size[2_160:], [0.5, 1.0])):
        raise ValueError("weekly size escaped the frozen {0.5, 1.0} domain")

    signals = {
        "candidate": candidate,
        "B0": base.astype(float),
        "B1": daily_b1.astype(float),
    }
    paths = {name: parent.path_from_signal(signal, opens) for name, signal in signals.items()}

    fixed_half_signal = daily_b1.astype(float)
    exposure_matched_signal = daily_b1.astype(float)
    exposure_matched_multiplier = 1.0
    if activation_index is not None:
        fixed_half_signal = daily_b1.astype(float).copy()
        fixed_half_signal[activation_index:] *= 0.5

        start = max(parent.parent.fw.OOS[0], activation_index)
        end = parent.parent.fw.OOS[1]
        candidate_exposure = float(np.sum(candidate[start:end]))
        benchmark_exposure = float(np.sum(daily_b1[start:end]))
        if benchmark_exposure > 0:
            exposure_matched_multiplier = float(
                np.clip(candidate_exposure / benchmark_exposure, 0.0, 1.0)
            )
        exposure_matched_signal = daily_b1.astype(float).copy()
        exposure_matched_signal[activation_index:] *= exposure_matched_multiplier

    controls = {
        "fixed_half": parent.path_from_signal(fixed_half_signal, opens),
        "exposure_matched_constant": parent.path_from_signal(
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
        "lagged_payoff": lagged_payoff,
        "activation_index": activation_index,
        "exposure_matched_multiplier": exposure_matched_multiplier,
    }


def evaluate_market(
    instrument: str,
    market: dict[str, Any],
    built: dict[str, Any],
    starts: np.ndarray,
) -> dict[str, Any]:
    """Evaluate frozen gates and direct one-lag payoff calibration."""
    result = parent.evaluate_market(instrument, market, built, starts)
    start, end = parent.parent.fw.OOS
    indices = np.arange(len(built["decision_mask"]))
    valid = (
        built["decision_mask"]
        & (indices >= start)
        & (indices < end)
        & np.isfinite(built["lagged_payoff"])
        & np.isfinite(built["realized_label"])
    )
    lagged = built["lagged_payoff"][valid]
    realized = built["realized_label"][valid]
    correlation = None
    if len(lagged) >= 2 and np.std(lagged, ddof=1) > 0 and np.std(realized, ddof=1) > 0:
        correlation = float(np.corrcoef(lagged, realized)[0, 1])
    positive = lagged > 0
    result["lagged_payoff_diagnostics"] = {
        "eligible_oos_anchors": int(np.sum(valid)),
        "positive_lagged_payoff_anchors": int(np.sum(positive)),
        "nonpositive_lagged_payoff_anchors": int(np.sum(~positive)),
        "lagged_payoff_next_payoff_correlation": correlation,
        "mean_next_payoff_after_positive": (
            float(np.mean(realized[positive])) if np.any(positive) else None
        ),
        "mean_next_payoff_after_nonpositive": (
            float(np.mean(realized[~positive])) if np.any(~positive) else None
        ),
        "positive_next_fraction_after_positive": (
            float(np.mean(realized[positive] > 0)) if np.any(positive) else None
        ),
        "positive_next_fraction_after_nonpositive": (
            float(np.mean(realized[~positive] > 0)) if np.any(~positive) else None
        ),
    }
    return result


def run(args: argparse.Namespace) -> dict[str, Any]:
    """Run the inherited deterministic scorecard with the frozen one-lag state."""
    parent.FAMILY_ID = FAMILY_ID
    parent.ISSUE = ISSUE
    parent.build_paths = build_paths
    parent.evaluate_market = evaluate_market
    result = parent.run(args)
    result["family_id"] = FAMILY_ID
    result["issue"] = ISSUE
    result["model"] = {
        "direction": "daily 2160H endpoint trend",
        "anchor": "completed Monday 00:00 UTC",
        "predictor": "latest fully observed trailing self-contained 168H B1 net payoff",
        "weekly_size": "1.0 when lagged payoff > 0, otherwise 0.5; fallback 1.0",
        "candidate_count": 1,
        "parameter_grid": 0,
    }
    result["accepted"] = (
        all(item["accepted"] for item in result["markets"])
        and parent.parent.fw.ci_lower_positive(
            result["common_bootstrap_vs_B1"]["annualized_mean_delta_ci95"]
        )
        and parent.parent.fw.ci_lower_positive(
            result["common_bootstrap_vs_B1"]["sharpe_delta_ci95"]
        )
    )
    result["verdict"] = (
        "support_lagged_realised_b1_payoff_state_research_nomination"
        if result["accepted"]
        else "reject_lagged_realised_b1_payoff_state_sizing_family"
    )
    return result


def format_optional(value: float | None, digits: int = 3) -> str:
    return "undefined" if value is None else f"{value:+.{digits}f}"


def report(result: dict[str, Any]) -> str:
    """Render inherited evidence plus one-lag payoff calibration."""
    text = parent.report(result)
    text = text.replace(
        "# Analog-conditioned weekly B1-sleeve payoff sizing evidence",
        "# Lagged realised B1-payoff state sizing evidence",
        1,
    )
    lines = [text, "", "## One-lag payoff calibration", ""]
    for item in result["markets"]:
        values = item["lagged_payoff_diagnostics"]
        lines.extend(
            [
                f"### {item['instrument']}",
                "",
                f"Eligible OOS anchors {values['eligible_oos_anchors']}; positive lagged "
                f"payoff {values['positive_lagged_payoff_anchors']}; non-positive "
                f"{values['nonpositive_lagged_payoff_anchors']}.",
                "",
                "Lagged/next payoff correlation "
                f"{format_optional(values['lagged_payoff_next_payoff_correlation'])}; "
                "mean next payoff after positive/non-positive states "
                f"{format_optional(values['mean_next_payoff_after_positive'], 4)} / "
                f"{format_optional(values['mean_next_payoff_after_nonpositive'], 4)}.",
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
    result_path.write_bytes(parent.parent.fw.canonical_bytes(result))
    summary = {
        "family_id": result["family_id"],
        "tested_sha": result["tested_sha"],
        "candidate_count": 1,
        "parameter_grid": 0,
        "markets_passing_every_gate": result["markets_passing_every_gate"],
        "verdict": result["verdict"],
        "result_sha256": parent.parent.fw.sha256_file(result_path),
        "market_headlines": {
            item["instrument"]: {
                "candidate_oos": item["performance"]["oos"]["candidate"],
                "B1_oos": item["performance"]["oos"]["B1"],
                "breadth": item["breadth"],
                "residual_sharpe_vs_B1": item["residual_sharpe_vs_B1"],
                "aligned_label_diagnostics": item["aligned_label_diagnostics"],
                "lagged_payoff_diagnostics": item["lagged_payoff_diagnostics"],
                "accepted": item["accepted"],
            }
            for item in result["markets"]
        },
    }
    (args.output_dir / "result-summary.json").write_bytes(
        parent.parent.fw.canonical_bytes(summary)
    )
    (args.output_dir / "report.md").write_text(report(result), encoding="utf-8")


if __name__ == "__main__":
    main()
