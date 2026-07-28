from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import run_prospective_simple_trend_shadow as base

PRIOR_RESULT_SHA256 = "0a0461a79a11362e380c7eb323f3387cd578dfaf7bc937fc71650af403314689"
PRIOR_ARTIFACT_SHA256 = "efbbaf91108df686e0855441365cd110020585c37fa489a859271ae10a8e893b"
PRIOR_LAST_SIGNAL_HOUR_MS = 1_785_250_800_000  # 2026-07-28T15:00:00Z
LAST_COMPLETE_SIGNAL_HOUR_MS = 1_785_258_000_000  # 2026-07-28T17:00:00Z


def run(output_dir: Path, base_url: str) -> dict[str, object]:
    base.PRIOR_LAST_SIGNAL_HOUR_MS = PRIOR_LAST_SIGNAL_HOUR_MS
    base.LAST_COMPLETE_SIGNAL_HOUR_MS = LAST_COMPLETE_SIGNAL_HOUR_MS

    result = base.run(output_dir, base_url)
    result["prospective_lineage"] = {
        "prior_result_sha256": PRIOR_RESULT_SHA256,
        "prior_artifact_sha256": PRIOR_ARTIFACT_SHA256,
        "prior_last_signal_bar_start": base.iso_utc(PRIOR_LAST_SIGNAL_HOUR_MS),
        "latest_complete_signal_bar_start": base.iso_utc(LAST_COMPLETE_SIGNAL_HOUR_MS),
        "policy_unchanged": True,
    }
    window = result["window"]
    if not isinstance(window, dict):
        raise TypeError("result window is not a mapping")
    window["prior_cumulative_realized_hours"] = 495
    window["updated_cumulative_realized_hours"] = 496
    result["next_strategy_action"] = (
        "continue the immutable benchmark-shadow epoch without policy changes; "
        "the active V1/V2 family remains separately gated by issue #579"
    )
    base.write_outputs(output_dir, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("OKX_BASE_URL", "https://www.okx.com"),
    )
    args = parser.parse_args()
    result = run(args.output_dir, args.base_url.rstrip("/"))
    print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
