from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from analysis import build_result


def compact_result(result: dict) -> dict:
    markets = {}
    for market, details in result["markets"].items():
        markets[market] = {
            "market": details["market"],
            "provenance": details["provenance"],
            "metrics": details["metrics"],
            "benchmark_metrics": details["benchmark_metrics"],
            "benchmark_bootstrap": details["benchmark_bootstrap"],
            "fold_stability": {
                key: value
                for key, value in details["fold_stability"].items()
                if key != "fold_returns"
            },
            "month_stability": {
                key: value
                for key, value in details["month_stability"].items()
                if key != "records"
            },
            "year_stability": {
                key: value
                for key, value in details["year_stability"].items()
                if key != "records"
            },
            "activity": details["activity"],
            "neighbourhood": details["neighbourhood"],
            "tail_risk": details["tail_risk"],
            "capacity": details["capacity"],
            "retrospective_gates": details["retrospective_gates"],
            "retrospective_passes": details["retrospective_passes"],
        }
    return {
        "canonical_signature": result["canonical_signature"],
        "hypothesis": result["hypothesis"],
        "candidate_accounting": result["candidate_accounting"],
        "fixed_architecture": result["fixed_architecture"],
        "evaluation": result["evaluation"],
        "markets": markets,
        "joint_retrospective_passes": result["joint_retrospective_passes"],
        "prospective_execution_diagnostics": result["prospective_execution_diagnostics"],
        "paper_testable": result["paper_testable"],
        "live_eligible": result["live_eligible"],
        "verdict": result["verdict"],
        "rejection_reasons": result["rejection_reasons"],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--btc-artifact-dir", required=True)
    parser.add_argument("--eth-artifact-dir", required=True)
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args(argv)
    result = compact_result(
        build_result(arguments.btc_artifact_dir, arguments.eth_artifact_dir)
    )
    output = Path(arguments.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
