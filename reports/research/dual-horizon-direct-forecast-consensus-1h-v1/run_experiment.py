#!/usr/bin/env python3
"""Run the frozen dual-horizon direct forecast consensus experiment."""

from __future__ import annotations

import argparse
from pathlib import Path

from common import (
    DEFAULT_SEED,
    FULL,
    HORIZONS,
    MIN_TRAIN_ROWS,
    OOS,
    RIDGE_ALPHA,
    TRAIN,
    TRAIN_WINDOW_HOURS,
    canonical_bytes,
    find_csv,
    load_market,
    sha256_file,
)
from diagnostics import common_bootstrap, evaluate_market
from metrics import bootstrap_starts
from reporting import report_markdown
from strategy import build_signals


def run(args: argparse.Namespace) -> dict:
    markets_raw = []
    markets_built = []
    for instrument in args.instrument:
        path = find_csv(args.data_root, instrument)
        market = load_market(path, instrument)
        built = build_signals(market)
        markets_raw.append((instrument, market))
        markets_built.append((instrument, built))

    starts = bootstrap_starts(OOS[1] - OOS[0], args.resamples, args.seed)
    evaluated = [
        evaluate_market(instrument, market, built, starts)
        for (instrument, market), (_, built) in zip(markets_raw, markets_built, strict=True)
    ]
    accepted = all(item["accepted"] for item in evaluated)
    verdict = (
        "accept_dual_horizon_direct_forecast_consensus_for_replication"
        if accepted
        else "reject_dual_horizon_direct_forecast_consensus_family"
    )
    return {
        "schema_version": 1,
        "family_id": "dual-horizon-direct-forecast-consensus-1h-v1",
        "issue": 774,
        "tested_sha": args.tested_sha,
        "source_workflow_run": args.source_workflow_run,
        "candidate_count": 1,
        "parameter_grid": 0,
        "markets_fixed_preperformance": list(args.instrument),
        "provider": "OKX",
        "market_type": "SPOT",
        "bar": "1H",
        "position_domain": [0, 1],
        "fee_bps_one_way": 5.0,
        "fee_formula": "0.0005 * abs(exposure_change)",
        "execution": "completed bar decision; next hourly open",
        "samples": {"train": TRAIN, "oos": OOS, "full": FULL},
        "model": {
            "decision_cadence": "completed 00:00 UTC",
            "forecast_horizons_hours": list(HORIZONS),
            "training_window_hours": TRAIN_WINDOW_HOURS,
            "minimum_training_rows": MIN_TRAIN_ROWS,
            "ridge_penalty": RIDGE_ALPHA,
            "normalization": "training-row median and MAD",
            "features": [
                "log_return_24h",
                "log_return_168h",
                "log_return_720h",
                "rms_volatility_24h_over_168h_minus_1",
                "downside_rms_24h_over_168h_minus_1",
                "drawdown_from_trailing_168h_max",
            ],
            "decision_rule": "long iff both direct forecasts are strictly positive",
        },
        "uncertainty": {
            "method": "paired non-circular 168H moving-block bootstrap",
            "resamples": args.resamples,
            "seed": args.seed,
        },
        "markets": evaluated,
        "common_bootstrap_vs_B1": common_bootstrap(markets_built, starts),
        "markets_passing_every_gate": int(sum(item["accepted"] for item in evaluated)),
        "accepted": accepted,
        "verdict": verdict,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--instrument", action="append", required=True)
    parser.add_argument("--resamples", type=int, default=5_000)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--source-workflow-run", default="local")
    parser.add_argument("--tested-sha", default="local")
    args = parser.parse_args()
    if len(args.instrument) != 2 or len(set(args.instrument)) != 2:
        raise ValueError("exactly two distinct fixed instruments are required")
    if args.resamples <= 0:
        raise ValueError("resamples must be positive")

    result = run(args)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    result_path = args.output_dir / "result.json"
    result_path.write_bytes(canonical_bytes(result))
    summary = {
        "family_id": result["family_id"],
        "tested_sha": result["tested_sha"],
        "candidate_count": result["candidate_count"],
        "parameter_grid": result["parameter_grid"],
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
    (args.output_dir / "report.md").write_text(report_markdown(result))


if __name__ == "__main__":
    main()
