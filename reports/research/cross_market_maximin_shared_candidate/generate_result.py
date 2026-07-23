from __future__ import annotations

import argparse
import json
from pathlib import Path

import analysis


def compact_result(result: dict) -> dict:
    markets = {}
    for market, data in result["markets"].items():
        markets[market] = {
            "metrics_5bps": data["metrics_5bps"],
            "volatility_targeted_long": {
                key: data["volatility_targeted_long"][key]
                for key in ("total_return", "cagr", "sharpe", "calmar", "max_drawdown")
            },
            "bootstrap_vs_volatility_targeted_long": data["bootstrap_vs_volatility_targeted_long"],
            "fold_stability": {
                key: data["fold_stability"][key]
                for key in (
                    "fold_count",
                    "profitable_folds",
                    "positive_fold_ratio",
                    "best_fold_total_return",
                    "worst_fold_total_return",
                    "max_positive_fold_share",
                    "minimum_profitable_folds",
                    "maximum_allowed_positive_fold_share",
                    "passes",
                    "failure_reasons",
                )
            },
            "calendar_stability": data["calendar_stability"],
            "cost_scenarios_bps": data["cost_scenarios_bps"],
            "parameter_neighbourhood": data["parameter_neighbourhood"],
            "tail_risk": data["tail_risk"],
            "execution_delay_scenarios": {
                key: data["execution_delay_scenarios"][key]
                for key in (
                    "scenarios_tested",
                    "passes",
                    "minimum_total_return",
                    "worst_max_drawdown",
                    "minimum_annualized_mean_95pct_lower",
                    "minimum_sharpe_95pct_lower",
                )
            },
            "fold_selection_summary": data["fold_selection_summary"],
            "evaluation": data["evaluation"],
            "gates": data["gates"],
        }
    return {
        key: result[key]
        for key in (
            "hypothesis",
            "economic_rationale",
            "canonical_signature",
            "candidate_accounting",
            "source",
            "joint_gates",
            "architecture_freeze_eligible",
            "live_eligible",
            "verdict",
            "limitations",
        )
    } | {"markets": markets}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = compact_result(analysis.analyze(args.artifact_dir))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
