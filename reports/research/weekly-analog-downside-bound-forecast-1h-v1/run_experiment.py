#!/usr/bin/env python3
"""Run the frozen weekly analog downside-bound forecast experiment."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
LEGACY = HERE.parent / "dual-horizon-direct-forecast-consensus-1h-v1"
sys.path.insert(0, str(LEGACY))
from common import (  # noqa: E402
    ANNUAL_HOURS,
    DEFAULT_SEED,
    FULL,
    OOS,
    TRAIN,
    canonical_bytes,
    find_csv,
    finite_or_none,
    load_market,
    sha256_file,
)
from metrics import (  # noqa: E402
    bootstrap_starts,
    fold_year_diagnostics,
    metrics,
    paired_bootstrap,
    residual_sharpe,
    sampled_indices,
    sharpe_value,
)

FEE = 0.0005
HURDLE = 0.001
MIN_HISTORY = 64
NEIGHBOURS = 32
QUANTILE = 0.25


def features(market: dict[str, Any]) -> np.ndarray:
    close = market["closes"]
    log_close = np.log(close)
    ret = np.diff(log_close, prepend=np.nan)
    output = np.full((len(close), 6), np.nan)
    for column, window in enumerate((168, 720, 2160)):
        output[window:, column] = log_close[window:] - log_close[:-window]
    squared = np.nan_to_num(ret) ** 2
    downside = np.minimum(np.nan_to_num(ret), 0.0) ** 2
    prefix_sq = np.r_[0.0, np.cumsum(squared)]
    prefix_down = np.r_[0.0, np.cumsum(downside)]
    rms: dict[int, np.ndarray] = {}
    down_rms: dict[int, np.ndarray] = {}
    for window in (168, 2160):
        values = np.full(len(close), np.nan)
        down_values = np.full(len(close), np.nan)
        index = np.arange(window, len(close))
        values[index] = np.sqrt((prefix_sq[index + 1] - prefix_sq[index + 1 - window]) / window)
        down_values[index] = np.sqrt(
            (prefix_down[index + 1] - prefix_down[index + 1 - window]) / window
        )
        rms[window] = values
        down_rms[window] = down_values
    valid = (rms[2160] > 0) & (down_rms[2160] > 0)
    output[valid, 3] = rms[168][valid] / rms[2160][valid] - 1.0
    output[valid, 4] = down_rms[168][valid] / down_rms[2160][valid] - 1.0
    high = pd.Series(close).rolling(720, min_periods=720).max().to_numpy(float)
    output[:, 5] = close / high - 1.0
    if not np.all(np.isfinite(output[2160:])):
        raise ValueError("non-finite frozen feature after 2160H warm-up")
    return output


def build_paths(market: dict[str, Any]) -> dict[str, Any]:
    timestamps = market["timestamps"]
    close = market["closes"]
    opens = market["opens"]
    n = len(close)
    x = features(market)
    base = np.zeros(n, dtype=np.int8)
    base[2160:] = (close[2160:] > close[:-2160]).astype(np.int8)
    b1 = np.zeros(n, dtype=np.int8)
    candidate = np.zeros(n, dtype=np.int8)
    decision_mask = np.zeros(n, dtype=bool)
    lower_bound = np.full(n, np.nan)
    history_rows = np.zeros(n, dtype=np.int32)
    realized_label = np.full(n, np.nan)
    current_b1 = 0
    current_candidate = 0
    anchors = np.flatnonzero(
        (timestamps.dt.dayofweek.to_numpy() == 0) & (timestamps.dt.hour.to_numpy() == 0)
    )
    anchor_set = set(int(value) for value in anchors)
    for t in range(2160, n):
        if timestamps.iloc[t].hour == 0:
            current_b1 = int(base[t])
        if int(t) in anchor_set:
            decision_mask[t] = True
            eligible = anchors[(anchors >= 2160) & (anchors + 169 <= t)]
            history_rows[t] = len(eligible)
            if t + 169 < n:
                realized_label[t] = opens[t + 169] / opens[t + 1] - 1.0
            if len(eligible) >= MIN_HISTORY:
                train_x = x[eligible]
                centre = np.median(train_x, axis=0)
                scale = np.median(np.abs(train_x - centre), axis=0)
                scale[~np.isfinite(scale) | (scale <= 0)] = 1.0
                scaled_train = (train_x - centre) / scale
                scaled_query = (x[t] - centre) / scale
                distance = np.sum((scaled_train - scaled_query) ** 2, axis=1)
                order = np.lexsort((eligible, distance))[:NEIGHBOURS]
                neighbours = eligible[order]
                labels = opens[neighbours + 169] / opens[neighbours + 1] - 1.0
                lower_bound[t] = float(np.quantile(labels, QUANTILE, method="linear"))
                current_candidate = int(lower_bound[t] > HURDLE)
            else:
                current_candidate = 0
        b1[t] = current_b1
        candidate[t] = current_candidate
    signals = {"candidate": candidate, "B0": base, "B1": b1}
    paths: dict[str, Any] = {}
    market_return = opens[1:] / opens[:-1] - 1.0
    for name, signal in signals.items():
        position = np.zeros(n - 1, dtype=float)
        position[1:] = signal[:-2]
        changes = np.abs(position - np.r_[0.0, position[:-1]])
        gross = position * market_return
        fee = FEE * changes
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
        "lower_bound": lower_bound,
        "history_rows": history_rows,
        "realized_label": realized_label,
    }


def forecast_diagnostics(built: dict[str, Any]) -> dict[str, Any]:
    start, end = OOS
    index = np.arange(len(built["decision_mask"]))
    valid = (
        built["decision_mask"]
        & (index >= start)
        & (index < end)
        & np.isfinite(built["lower_bound"])
        & np.isfinite(built["realized_label"])
    )
    selected = valid & (built["lower_bound"] > HURDLE)
    rejected = valid & ~selected
    lower = built["lower_bound"]
    label = built["realized_label"]
    corr = None
    if np.sum(valid) > 1 and np.std(lower[valid]) > 0 and np.std(label[valid]) > 0:
        corr = finite_or_none(float(np.corrcoef(lower[valid], label[valid])[0, 1]))

    def group(mask: np.ndarray) -> dict[str, Any]:
        values = label[mask]
        return {
            "count": int(np.sum(mask)),
            "mean_realized_168h": finite_or_none(float(np.mean(values))) if len(values) else None,
            "positive_fraction": float(np.mean(values > 0)) if len(values) else None,
            "sum_realized_168h": float(np.sum(values)),
        }

    candidate = built["paths"]["candidate"]
    b1 = built["paths"]["B1"]
    cpos = candidate["position"][start:end]
    bpos = b1["position"][start:end]
    gross_timing = float(np.sum(candidate["gross"][start:end] - b1["gross"][start:end]))
    fee_contribution = float(np.sum(b1["fee"][start:end] - candidate["fee"][start:end]))
    net_residual = float(np.sum(candidate["net"][start:end] - b1["net"][start:end]))
    if not np.isclose(gross_timing + fee_contribution, net_residual, atol=1e-12):
        raise ValueError("candidate-minus-B1 decomposition failure")
    return {
        "eligible_oos_weekly_decisions": int(np.sum(valid)),
        "selected": group(selected),
        "rejected": group(rejected),
        "lower_bound_realized_correlation": corr,
        "median_history_rows": float(np.median(built["history_rows"][valid])),
        "candidate_only_hours": int(np.sum((cpos == 1) & (bpos == 0))),
        "b1_only_hours": int(np.sum((cpos == 0) & (bpos == 1))),
        "gross_timing_residual": gross_timing,
        "fee_contribution": fee_contribution,
        "net_arithmetic_residual": net_residual,
    }


def evaluate_market(
    instrument: str, market: dict[str, Any], built: dict[str, Any], starts: np.ndarray
) -> dict[str, Any]:
    paths = built["paths"]
    samples = {"train": TRAIN, "oos": OOS, "full": FULL}
    performance = {
        sample: {name: metrics(paths[name], *bounds) for name in ("candidate", "B0", "B1")}
        for sample, bounds in samples.items()
    }
    breadth = fold_year_diagnostics(paths["candidate"], market["timestamps"])
    start, end = OOS
    candidate_oos = paths["candidate"]["net"][start:end]
    b1_oos = paths["B1"]["net"][start:end]
    bootstrap = paired_bootstrap(candidate_oos, b1_oos, starts)
    residual = residual_sharpe(candidate_oos, b1_oos)
    c = performance["oos"]["candidate"]
    b1 = performance["oos"]["B1"]
    concentration = breadth["positive_fold_concentration"]
    gates = {
        "positive_oos_return": c["net_return"] > 0,
        "return_at_least_B1": c["net_return"] >= b1["net_return"],
        "sharpe_at_least_B1": c["sharpe"] is not None
        and b1["sharpe"] is not None
        and c["sharpe"] >= b1["sharpe"],
        "drawdown_no_worse_B1": c["max_drawdown"] >= b1["max_drawdown"],
        "turnover_no_worse_B1": c["turnover"] <= b1["turnover"],
        "edge_per_turn_positive_and_at_least_B1": c["edge_per_turn_bps"] is not None
        and b1["edge_per_turn_bps"] is not None
        and c["edge_per_turn_bps"] > 0
        and c["edge_per_turn_bps"] >= b1["edge_per_turn_bps"],
        "profitable_folds_at_least_7": breadth["profitable_folds"] >= 7,
        "profitable_years_at_least_3": breadth["profitable_years"] >= 3,
        "positive_fold_concentration_at_most_0_5": concentration is not None
        and concentration <= 0.5,
        "positive_residual_sharpe": residual is not None and residual > 0,
        "mean_delta_ci_lower_positive": bootstrap["annualized_mean_delta_ci95"][0] > 0,
        "sharpe_delta_ci_lower_positive": bootstrap["sharpe_delta_ci95"][0] > 0,
        "positive_full_return": performance["full"]["candidate"]["net_return"] > 0,
    }
    return {
        "instrument": instrument,
        "source": {
            "csv_path": market["csv_path"],
            "csv_sha256": market["csv_sha256"],
            "source_rows": market["source_rows"],
            "frozen_prefix_rows": 43_441,
            "frozen_start": market["timestamps"].iloc[0].isoformat(),
            "frozen_end": market["timestamps"].iloc[-1].isoformat(),
        },
        "performance": performance,
        "breadth": breadth,
        "residual_sharpe_vs_B1": residual,
        "bootstrap_vs_B1": bootstrap,
        "forecast_diagnostics": forecast_diagnostics(built),
        "gates": gates,
        "accepted": all(gates.values()),
    }


def common_bootstrap(markets: list[dict[str, Any]], starts: np.ndarray) -> dict[str, Any]:
    start, end = OOS
    mean_point = []
    sharpe_point = []
    sampled_mean = np.empty(len(starts))
    sampled_sharpe = np.empty(len(starts))
    for built in markets:
        c = built["paths"]["candidate"]["net"][start:end]
        b = built["paths"]["B1"]["net"][start:end]
        mean_point.append(float(np.mean(c - b) * ANNUAL_HOURS))
        sharpe_point.append(sharpe_value(c) - sharpe_value(b))
    for k, block_starts in enumerate(starts):
        means = []
        sharpes = []
        for built in markets:
            c_all = built["paths"]["candidate"]["net"][start:end]
            b_all = built["paths"]["B1"]["net"][start:end]
            indices = sampled_indices(block_starts, len(c_all))
            c = c_all[indices]
            b = b_all[indices]
            means.append(float(np.mean(c - b) * ANNUAL_HOURS))
            sharpes.append(sharpe_value(c) - sharpe_value(b))
        sampled_mean[k] = float(np.median(means))
        sampled_sharpe[k] = float(np.median(sharpes))
    return {
        "annualized_mean_delta_point": float(np.median(mean_point)),
        "annualized_mean_delta_ci95": [
            float(value) for value in np.quantile(sampled_mean, [0.025, 0.975])
        ],
        "sharpe_delta_point": finite_or_none(float(np.median(sharpe_point))),
        "sharpe_delta_ci95": [
            float(value) for value in np.nanquantile(sampled_sharpe, [0.025, 0.975])
        ],
    }


def report(result: dict[str, Any]) -> str:
    lines = [
        "# Weekly analog downside-bound forecast evidence",
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
                "|---|---|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for sample in ("train", "oos", "full"):
            for policy in ("candidate", "B1", "B0"):
                value = item["performance"][sample][policy]
                sharpe = "undefined" if value["sharpe"] is None else f"{value['sharpe']:+.3f}"
                edge = (
                    "undefined"
                    if value["edge_per_turn_bps"] is None
                    else f"{value['edge_per_turn_bps']:+.2f}"
                )
                lines.append(
                    f"| {sample} | {policy} | {value['net_return']:+.2%} | {sharpe} | "
                    f"{value['max_drawdown']:+.2%} | {value['turnover']:.0f} | "
                    f"{value['fees']:.2%} | {edge} bps |"
                )
        diag = item["forecast_diagnostics"]
        boot = item["bootstrap_vs_B1"]
        lines.extend(
            [
                "",
                f"Breadth: {item['breadth']['profitable_folds']}/12 profitable folds; "
                f"{item['breadth']['profitable_years']}/4 profitable years; "
                f"residual Sharpe {item['residual_sharpe_vs_B1']}.",
                "",
                f"Eligible OOS weekly decisions: {diag['eligible_oos_weekly_decisions']}; "
                f"selected {diag['selected']['count']}; lower-bound/realized correlation "
                f"{diag['lower_bound_realized_correlation']}.",
                "",
                "Selected label sum "
                f"{diag['selected']['sum_realized_168h']:+.2%}; rejected label sum "
                f"{diag['rejected']['sum_realized_168h']:+.2%}. Gross timing residual "
                f"{diag['gross_timing_residual']:+.2%}; fee contribution "
                f"{diag['fee_contribution']:+.2%}; net arithmetic residual "
                f"{diag['net_arithmetic_residual']:+.2%}.",
                "",
                f"Annualised mean delta 95% CI {boot['annualized_mean_delta_ci95']}; "
                f"Sharpe delta 95% CI {boot['sharpe_delta_ci95']}.",
                "",
            ]
        )
    lines.extend(
        [
            "## Common-index inference",
            "",
            f"{json.dumps(result['common_bootstrap_vs_B1'], sort_keys=True)}",
            "",
            f"Markets passing every gate: {result['markets_passing_every_gate']}/2.",
            "",
            f"## Verdict\n\n`{result['verdict']}`",
            "",
            "No paper or live-trading authority is created.",
            "",
        ]
    )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    raw = []
    built = []
    for instrument in args.instrument:
        market = load_market(find_csv(args.data_root, instrument), instrument)
        state = build_paths(market)
        raw.append((instrument, market))
        built.append(state)
    starts = bootstrap_starts(OOS[1] - OOS[0], args.resamples, args.seed)
    evaluated = [
        evaluate_market(instrument, market, state, starts)
        for (instrument, market), state in zip(raw, built, strict=True)
    ]
    common = common_bootstrap(built, starts)
    accepted = (
        all(item["accepted"] for item in evaluated)
        and common["annualized_mean_delta_ci95"][0] > 0
        and common["sharpe_delta_ci95"][0] > 0
    )
    return {
        "schema_version": 1,
        "family_id": "weekly-analog-downside-bound-forecast-1h-v1",
        "issue": 777,
        "tested_sha": args.tested_sha,
        "source_workflow_run": args.source_workflow_run,
        "candidate_count": 1,
        "parameter_grid": 0,
        "markets_fixed_preperformance": list(args.instrument),
        "provider": "OKX public confirmed SPOT",
        "bar": "1H",
        "fee_bps_one_way": 5.0,
        "execution": "completed Monday 00:00 UTC decision; next hourly open",
        "samples": {"train": TRAIN, "oos": OOS, "full": FULL},
        "model": {
            "label": "non-overlapping next-open 168H arithmetic return",
            "minimum_history": MIN_HISTORY,
            "neighbours": NEIGHBOURS,
            "quantile": QUANTILE,
            "hurdle": HURDLE,
            "normalization": "causal historical median and MAD",
        },
        "markets": evaluated,
        "common_bootstrap_vs_B1": common,
        "markets_passing_every_gate": int(sum(item["accepted"] for item in evaluated)),
        "accepted": accepted,
        "verdict": (
            "support_weekly_analog_downside_bound_forecast_research_nomination"
            if accepted
            else "reject_weekly_analog_downside_bound_forecast_family"
        ),
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--instrument", action="append", required=True)
    parser.add_argument("--resamples", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--source-workflow-run", default="local")
    parser.add_argument("--tested-sha", default="local")
    args = parser.parse_args()
    if len(args.instrument) != 2 or len(set(args.instrument)) != 2:
        raise ValueError("exactly two distinct fixed instruments are required")
    result = run(args)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    result_path = args.output_dir / "result.json"
    result_path.write_bytes(canonical_bytes(result))
    summary = {
        "family_id": result["family_id"],
        "tested_sha": result["tested_sha"],
        "candidate_count": 1,
        "parameter_grid": 0,
        "markets_passing_every_gate": result["markets_passing_every_gate"],
        "verdict": result["verdict"],
        "result_sha256": sha256_file(result_path),
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
    (args.output_dir / "result-summary.json").write_bytes(canonical_bytes(summary))
    (args.output_dir / "report.md").write_text(report(result), encoding="utf-8")


if __name__ == "__main__":
    main()
