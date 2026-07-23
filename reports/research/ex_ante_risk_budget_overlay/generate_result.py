from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import analysis


def _without(mapping: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {key: value for key, value in mapping.items() if key not in keys}


def _compact_delay(delay: dict[str, Any]) -> dict[str, Any]:
    scenarios = delay["scenario_results"]
    return {
        "scenarios_tested": delay["scenarios_tested"],
        "scenarios_passed": sum(bool(item["passes"]) for item in scenarios),
        "passes": delay["passes"],
        "minimum_total_return": min(float(item["metrics"]["total_return"]) for item in scenarios),
        "worst_max_drawdown": min(float(item["metrics"]["max_drawdown"]) for item in scenarios),
        "minimum_annualized_mean_95pct_lower": min(
            float(item["bootstrap"]["annualized_arithmetic_mean"]["lower"])
            for item in scenarios
        ),
        "minimum_sharpe_95pct_lower": min(
            float(item["bootstrap"]["sharpe"]["lower"]) for item in scenarios
        ),
        "failed_scenarios": [item["scenario"] for item in scenarios if not item["passes"]],
    }


def compact_result(result: dict[str, Any]) -> dict[str, Any]:
    compact = _without(result, "candidates")
    compact_candidates: dict[str, Any] = {}
    for name, candidate in result["candidates"].items():
        markets: dict[str, Any] = {}
        for market, evidence in candidate["markets"].items():
            markets[market] = {
                "metrics_5bps": evidence["metrics_5bps"],
                "volatility_targeted_long": evidence["volatility_targeted_long"],
                "bootstrap_vs_volatility_targeted_long": evidence[
                    "bootstrap_vs_volatility_targeted_long"
                ],
                "fold_stability": _without(evidence["fold_stability"], "records"),
                "calendar_stability": _without(evidence["calendar_stability"], "years"),
                "cost_scenarios_bps": evidence["cost_scenarios_bps"],
                "parameter_neighbourhood": evidence["parameter_neighbourhood"],
                "tail_risk": evidence["tail_risk"],
                "execution_delay_scenarios": _compact_delay(
                    evidence["execution_delay_scenarios"]
                ),
                "risk_budget_scaling": _without(
                    evidence["risk_budget_scaling"], "records"
                ),
                "gates": evidence["gates"],
            }
        compact_candidates[name] = {
            "risk_budget": candidate["risk_budget"],
            "markets": markets,
            "joint_gates": candidate["joint_gates"],
            "architecture_freeze_eligible": candidate["architecture_freeze_eligible"],
            "live_eligible": candidate["live_eligible"],
        }
    compact["candidates"] = compact_candidates
    return compact


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = compact_result(analysis.analyze(args.artifact_dir))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
