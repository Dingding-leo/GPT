#!/usr/bin/env python3
"""Run the frozen analog-conditioned weekly payoff-efficiency sizing experiment."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
FRAMEWORK_PATH = (
    ROOT
    / "reports/research/trend-conditioned-weekly-loss-probability-veto-1h-v1"
    / "run_experiment.py"
)
SPEC = importlib.util.spec_from_file_location("weekly_research_framework", FRAMEWORK_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("unable to load frozen research framework")
fw = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fw)

FAMILY_ID = "analog-conditioned-weekly-payoff-efficiency-sizing-1h-v1"
ISSUE = 785
HURDLE = 0.001
MIN_HISTORY = 64
NEIGHBOURS = 32


def build_paths(market: dict[str, Any]) -> dict[str, Any]:
    timestamps = market["timestamps"]
    closes = market["closes"]
    opens = market["opens"]
    length = len(closes)
    feature_values = fw.features(market)

    base = np.zeros(length, dtype=np.int8)
    base[2_160:] = (closes[2_160:] > closes[:-2_160]).astype(np.int8)
    daily_b1 = np.zeros(length, dtype=np.int8)
    candidate = np.zeros(length, dtype=float)
    weekly_size = np.ones(length, dtype=float)
    decision_mask = np.zeros(length, dtype=bool)
    history_rows = np.zeros(length, dtype=np.int32)
    efficiency = np.full(length, np.nan)
    neighbor_mean = np.full(length, np.nan)
    neighbor_positive_fraction = np.full(length, np.nan)
    realized_label = np.full(length, np.nan)

    anchors = np.flatnonzero(
        (timestamps.dt.dayofweek.to_numpy() == 0) & (timestamps.dt.hour.to_numpy() == 0)
    )
    anchor_set = set(int(value) for value in anchors)
    current_b1 = 0
    current_size = 1.0
    current_candidate = 0.0

    for time_index in range(2_160, length):
        if time_index in anchor_set:
            decision_mask[time_index] = True
            eligible = anchors[
                (anchors >= 2_160) & (anchors + 169 <= time_index) & (base[anchors] == 1)
            ]
            history_rows[time_index] = len(eligible)
            if time_index + 169 < length:
                realized_label[time_index] = (
                    opens[time_index + 169] / opens[time_index + 1] - 1.0 - HURDLE
                )
            if len(eligible) >= MIN_HISTORY:
                historical_features = feature_values[eligible]
                centre = np.median(historical_features, axis=0)
                scale = np.median(np.abs(historical_features - centre), axis=0)
                scale[~np.isfinite(scale) | (scale <= 0)] = 1.0
                scaled_history = (historical_features - centre) / scale
                scaled_query = (feature_values[time_index] - centre) / scale
                distance = np.sum((scaled_history - scaled_query) ** 2, axis=1)
                order = np.lexsort((eligible, distance))[:NEIGHBOURS]
                neighbours = eligible[order]
                labels = opens[neighbours + 169] / opens[neighbours + 1] - 1.0 - HURDLE
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
            current_b1 = int(base[time_index])
            current_candidate = float(current_b1) * current_size

        weekly_size[time_index] = current_size
        daily_b1[time_index] = current_b1
        candidate[time_index] = current_candidate

    if np.any(candidate < 0) or np.any(candidate > daily_b1 + 1e-12):
        raise ValueError("candidate exposure is outside the frozen B1 subset")
    if np.any(weekly_size < 0) or np.any(weekly_size > 1):
        raise ValueError("weekly size is outside [0, 1]")

    signals = {"candidate": candidate, "B0": base.astype(float), "B1": daily_b1.astype(float)}
    paths: dict[str, dict[str, np.ndarray]] = {}
    market_return = opens[1:] / opens[:-1] - 1.0
    for name, signal in signals.items():
        position = np.zeros(length - 1, dtype=float)
        position[1:] = signal[:-2]
        changes = np.abs(position - np.r_[0.0, position[:-1]])
        gross = position * market_return
        fee = fw.FEE * changes
        paths[name] = {
            "signal": signal,
            "position": position,
            "changes": changes,
            "gross": gross,
            "fee": fee,
            "net": gross - fee,
        }

    return {
        "paths": paths,
        "decision_mask": decision_mask,
        "history_rows": history_rows,
        "efficiency": efficiency,
        "neighbor_mean": neighbor_mean,
        "neighbor_positive_fraction": neighbor_positive_fraction,
        "realized_label": realized_label,
        "weekly_size": weekly_size,
        "base": base,
    }


def state_diagnostics(built: dict[str, Any]) -> dict[str, Any]:
    start, end = fw.OOS
    indices = np.arange(len(built["decision_mask"]))
    valid = (
        built["decision_mask"]
        & (indices >= start)
        & (indices < end)
        & np.isfinite(built["efficiency"])
        & np.isfinite(built["realized_label"])
    )
    values = built["weekly_size"][valid]
    efficiencies = built["efficiency"][valid]
    means = built["neighbor_mean"][valid]
    realized = built["realized_label"][valid]
    state_changes = int(np.sum(np.abs(np.diff(values)) > 1e-12)) if len(values) > 1 else 0

    candidate = built["paths"]["candidate"]
    benchmark = built["paths"]["B1"]
    candidate_position = candidate["position"][start:end]
    benchmark_position = benchmark["position"][start:end]
    if np.any(candidate_position > benchmark_position + 1e-12):
        raise ValueError("candidate exceeds B1 exposure")
    difference = benchmark_position - candidate_position
    gross_timing = float(np.sum(candidate["gross"][start:end] - benchmark["gross"][start:end]))
    fee_contribution = float(np.sum(benchmark["fee"][start:end] - candidate["fee"][start:end]))
    net_residual = float(np.sum(candidate["net"][start:end] - benchmark["net"][start:end]))
    if not np.isclose(gross_timing + fee_contribution, net_residual, atol=1e-12):
        raise ValueError("candidate-minus-B1 decomposition failure")

    forecast_correlation = None
    if len(means) >= 2 and np.std(means, ddof=1) > 0 and np.std(realized, ddof=1) > 0:
        forecast_correlation = float(np.corrcoef(means, realized)[0, 1])

    return {
        "eligible_oos_weekly_decisions": int(np.sum(valid)),
        "weekly_size_min_q25_median_q75_max": (
            [float(value) for value in np.quantile(values, [0.0, 0.25, 0.5, 0.75, 1.0])]
            if len(values)
            else [None, None, None, None, None]
        ),
        "efficiency_min_median_max": (
            [
                float(np.min(efficiencies)),
                float(np.median(efficiencies)),
                float(np.max(efficiencies)),
            ]
            if len(efficiencies)
            else [None, None, None]
        ),
        "weekly_size_state_changes": state_changes,
        "median_history_rows": (
            float(np.median(built["history_rows"][valid])) if np.any(valid) else None
        ),
        "neighbor_mean_realized_correlation": forecast_correlation,
        "reduced_exposure_hours": int(np.sum(difference > 1e-12)),
        "reduced_exposure_equivalent_hours": float(np.sum(difference)),
        "gross_timing_residual": gross_timing,
        "fee_contribution": fee_contribution,
        "net_arithmetic_residual": net_residual,
    }


def evaluate_market(
    instrument: str,
    market: dict[str, Any],
    built: dict[str, Any],
    starts: np.ndarray,
) -> dict[str, Any]:
    paths = built["paths"]
    samples = {"train": fw.TRAIN, "oos": fw.OOS, "full": fw.FULL}
    performance = {
        sample: {name: fw.metrics(paths[name], *bounds) for name in ("candidate", "B0", "B1")}
        for sample, bounds in samples.items()
    }
    breadth = fw.fold_year_diagnostics(paths["candidate"], market["timestamps"])
    start, end = fw.OOS
    candidate_oos = paths["candidate"]["net"][start:end]
    benchmark_oos = paths["B1"]["net"][start:end]
    bootstrap = fw.paired_bootstrap(candidate_oos, benchmark_oos, starts)
    residual = fw.residual_sharpe(candidate_oos, benchmark_oos)
    candidate_metrics = performance["oos"]["candidate"]
    benchmark_metrics = performance["oos"]["B1"]
    concentration = breadth["positive_fold_concentration"]
    gates = {
        "positive_oos_return": candidate_metrics["net_return"] > 0,
        "return_at_least_B1": candidate_metrics["net_return"] >= benchmark_metrics["net_return"],
        "sharpe_at_least_B1": (
            candidate_metrics["sharpe"] is not None
            and benchmark_metrics["sharpe"] is not None
            and candidate_metrics["sharpe"] >= benchmark_metrics["sharpe"]
        ),
        "drawdown_no_worse_B1": (
            candidate_metrics["max_drawdown"] >= benchmark_metrics["max_drawdown"]
        ),
        "turnover_no_worse_B1": candidate_metrics["turnover"] <= benchmark_metrics["turnover"],
        "edge_per_turn_positive_and_at_least_B1": (
            candidate_metrics["edge_per_turn_bps"] is not None
            and benchmark_metrics["edge_per_turn_bps"] is not None
            and candidate_metrics["edge_per_turn_bps"] > 0
            and candidate_metrics["edge_per_turn_bps"] >= benchmark_metrics["edge_per_turn_bps"]
        ),
        "profitable_folds_at_least_7": breadth["profitable_folds"] >= 7,
        "profitable_years_at_least_3": breadth["profitable_years"] >= 3,
        "positive_fold_concentration_at_most_0_5": (
            concentration is not None and concentration <= 0.5
        ),
        "positive_residual_sharpe": residual is not None and residual > 0,
        "mean_delta_ci_lower_positive": fw.ci_lower_positive(
            bootstrap["annualized_mean_delta_ci95"]
        ),
        "sharpe_delta_ci_lower_positive": fw.ci_lower_positive(bootstrap["sharpe_delta_ci95"]),
        "positive_full_return": performance["full"]["candidate"]["net_return"] > 0,
    }
    return {
        "instrument": instrument,
        "source": {
            "csv_path": market["csv_path"],
            "csv_sha256": market["csv_sha256"],
            "source_rows": market["source_rows"],
            "frozen_prefix_rows": fw.PREFIX_ROWS,
            "frozen_start": market["timestamps"].iloc[0].isoformat(),
            "frozen_end": market["timestamps"].iloc[-1].isoformat(),
        },
        "performance": performance,
        "breadth": breadth,
        "residual_sharpe_vs_B1": residual,
        "bootstrap_vs_B1": bootstrap,
        "state_diagnostics": state_diagnostics(built),
        "gates": gates,
        "accepted": all(gates.values()),
    }


def format_optional(value: float | None, digits: int = 3) -> str:
    return "undefined" if value is None else f"{value:+.{digits}f}"


def report(result: dict[str, Any]) -> str:
    lines = [
        "# Analog-conditioned weekly payoff-efficiency sizing evidence",
        "",
        "```text",
        f"Family          {result['family_id']}",
        "Candidate count 1",
        "Parameter grid  0",
        "Fee             exactly 5 bps one way",
        f"Verdict         {result['verdict']}",
        "```",
        "",
    ]
    for item in result["markets"]:
        lines.extend(
            [
                f"## {item['instrument']}",
                "",
                "| Sample | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |",
                "|---|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for sample in ("train", "oos", "full"):
            for policy in ("candidate", "B1", "B0"):
                value = item["performance"][sample][policy]
                lines.append(
                    f"| {sample} | {policy} | {value['net_return']:+.2%} | "
                    f"{format_optional(value['sharpe'])} | {value['max_drawdown']:+.2%} | "
                    f"{value['turnover']:.2f} | {value['fees']:.2%} | "
                    f"{format_optional(value['edge_per_turn_bps'], 2)} bps |"
                )
        diagnostics = item["state_diagnostics"]
        bootstrap = item["bootstrap_vs_B1"]
        lines.extend(
            [
                "",
                f"Breadth: {item['breadth']['profitable_folds']}/12 profitable folds; "
                f"{item['breadth']['profitable_years']}/4 profitable years; residual Sharpe "
                f"{format_optional(item['residual_sharpe_vs_B1'])}.",
                "",
                f"Weekly size quantiles: {diagnostics['weekly_size_min_q25_median_q75_max']}; "
                f"state changes {diagnostics['weekly_size_state_changes']}; median causal "
                f"history {diagnostics['median_history_rows']}.",
                "",
                f"Neighbour-mean/realized correlation "
                f"{format_optional(diagnostics['neighbor_mean_realized_correlation'])}; "
                f"gross timing residual {diagnostics['gross_timing_residual']:+.2%}; fee "
                f"contribution {diagnostics['fee_contribution']:+.2%}; net arithmetic "
                f"residual {diagnostics['net_arithmetic_residual']:+.2%}.",
                "",
                f"Annualised mean delta 95% CI {bootstrap['annualized_mean_delta_ci95']}; "
                f"Sharpe delta 95% CI {bootstrap['sharpe_delta_ci95']}.",
                "",
            ]
        )
    lines.extend(
        [
            "## Common-index inference",
            "",
            json.dumps(result["common_bootstrap_vs_B1"], sort_keys=True),
            "",
            f"Markets passing every gate: {result['markets_passing_every_gate']}/2.",
            "",
            "## Verdict",
            "",
            f"`{result['verdict']}`",
            "",
            "No paper or live-trading authority is created.",
            "",
        ]
    )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    raw_markets = []
    built_markets = []
    for instrument in args.instrument:
        market = fw.load_market(fw.find_csv(args.data_root, instrument), instrument)
        built = build_paths(market)
        raw_markets.append((instrument, market))
        built_markets.append(built)
    starts = fw.bootstrap_starts(fw.OOS[1] - fw.OOS[0], args.resamples, args.seed)
    evaluated = [
        evaluate_market(instrument, market, built, starts)
        for (instrument, market), built in zip(raw_markets, built_markets, strict=True)
    ]
    common = fw.common_bootstrap(built_markets, starts)
    accepted = (
        all(item["accepted"] for item in evaluated)
        and fw.ci_lower_positive(common["annualized_mean_delta_ci95"])
        and fw.ci_lower_positive(common["sharpe_delta_ci95"])
    )
    return {
        "schema_version": 1,
        "family_id": FAMILY_ID,
        "issue": ISSUE,
        "tested_sha": args.tested_sha,
        "source_workflow_run": args.source_workflow_run,
        "candidate_count": 1,
        "parameter_grid": 0,
        "markets_fixed_preperformance": list(args.instrument),
        "provider": "OKX public confirmed SPOT",
        "bar": "1H",
        "fee_bps_one_way": 5.0,
        "execution": "weekly sizing and daily direction from completed bars; next hourly open",
        "samples": {"train": fw.TRAIN, "oos": fw.OOS, "full": fw.FULL},
        "model": {
            "direction": "daily 2160H endpoint trend",
            "features": "six fixed own-history return, volatility, downside and drawdown features",
            "history": "strictly prior fully observed positive-trend Monday anchors",
            "minimum_history": MIN_HISTORY,
            "neighbors": NEIGHBOURS,
            "label": "next-open 168H return less 10 bps",
            "efficiency": "sum(label) / sum(abs(label))",
            "weekly_size": "clip((1 + efficiency) / 2, 0, 1); fallback 1",
        },
        "markets": evaluated,
        "common_bootstrap_vs_B1": common,
        "markets_passing_every_gate": int(sum(item["accepted"] for item in evaluated)),
        "accepted": accepted,
        "verdict": (
            "support_analog_payoff_efficiency_sizing_research_nomination"
            if accepted
            else "reject_analog_payoff_efficiency_sizing_family"
        ),
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
    }


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
    if len(args.instrument) != 2 or len(set(args.instrument)) != 2:
        raise ValueError("exactly two distinct fixed instruments are required")
    if list(args.instrument) != ["NEO-USDT", "QTUM-USDT"]:
        raise ValueError("fixed preperformance instruments changed")
    result = run(args)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    result_path = args.output_dir / "result.json"
    result_path.write_bytes(fw.canonical_bytes(result))
    summary = {
        "family_id": result["family_id"],
        "tested_sha": result["tested_sha"],
        "candidate_count": 1,
        "parameter_grid": 0,
        "markets_passing_every_gate": result["markets_passing_every_gate"],
        "verdict": result["verdict"],
        "result_sha256": fw.sha256_file(result_path),
        "market_headlines": {
            item["instrument"]: {
                "candidate_oos": item["performance"]["oos"]["candidate"],
                "B1_oos": item["performance"]["oos"]["B1"],
                "breadth": item["breadth"],
                "residual_sharpe_vs_B1": item["residual_sharpe_vs_B1"],
                "accepted": item["accepted"],
            }
            for item in result["markets"]
        },
    }
    (args.output_dir / "result-summary.json").write_bytes(fw.canonical_bytes(summary))
    (args.output_dir / "report.md").write_text(report(result), encoding="utf-8")


if __name__ == "__main__":
    main()
