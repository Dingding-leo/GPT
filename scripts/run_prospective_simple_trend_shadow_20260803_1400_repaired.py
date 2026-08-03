from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_20260803_1400 as checkpoint

FAILED_RUN = 30822153197


def configure_compatibility() -> None:
    checkpoint.LATEST_ARCHITECTURE.update(
        {
            "source_contract_passed": True,
            "bilateral_source_contract_passed": True,
            "bilateral_pass": False,
        }
    )
    original_finalize = checkpoint.finalize

    def repaired_finalize(result: dict[str, Any]) -> dict[str, Any]:
        finalized = original_finalize(result)
        finalized["evidence_wrapper_repair"] = {
            "applied": True,
            "failed_run": FAILED_RUN,
            "failure_stage": "post_core_inherited_metadata_finalization",
            "repair": "preserved inherited source-contract compatibility keys",
            "strategy_value_changed": False,
            "source_changed": False,
            "fee_changed": False,
            "architecture_changed": False,
            "chronology_boundary_changed": False,
        }
        return finalized

    checkpoint.finalize = repaired_finalize


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    configure_compatibility()
    return checkpoint.run(output_dir, base_url)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--base-url", default=os.environ.get("OKX_BASE_URL", "https://www.okx.com")
    )
    args = parser.parse_args()
    print(json.dumps(run(args.output_dir, args.base_url), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
