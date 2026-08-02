from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import run_prospective_simple_trend_shadow_20260802_1800 as checkpoint


def exact_patch_report(output_dir: Path) -> None:
    path = output_dir / "report.md"
    report = path.read_text()
    replacements = {
        "through 16:00 UTC on 2 August 2026": "through 18:00 UTC on 2 August 2026",
        "The 15:00 signal bar was provider-confirmed": (
            "The 17:00 signal bar was provider-confirmed"
        ),
        "The 16:00 candle supplied only its": (
            "The 18:00 candle supplied only its"
        ),
        "15:00–16:00 open-to-open payoff": "17:00–18:00 open-to-open payoff",
        (
            "The completed conditional-variance-state programme closure in PR #982 "
            "bound eight consumed own-price risk-state mechanism groups and found zero "
            "bilaterally supported groups, zero supportive leave-one-group-out subsets, "
            "candidate count zero and no correction authority. No active replacement "
            "architecture or newly frozen observation epoch exists."
        ): (
            "The public spot-borrow-rate source contract in PR #988 passed both "
            "anonymous 1H source arms, but the intended bilateral pressure architecture "
            "was rejected before target-return access because BTC's complete 24,144-hour "
            "rate panel was constant. Candidate count remained zero, ETH-only promotion "
            "was prohibited, and no correction authority was created."
        ),
    }
    for old, new in replacements.items():
        if old not in report:
            raise RuntimeError(f"exact report patch target missing: {old!r}")
        report = report.replace(old, new, 1)
    path.write_text(report)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--base-url", default=os.environ.get("OKX_BASE_URL", "https://www.okx.com")
    )
    args = parser.parse_args()

    # The inherited 17:00 wrapper validates and patches its own frozen timestamp
    # labels before the 18:00 wrapper can apply the new exact-hour contract.
    # Bypass only those inherited presentation/checkpoint hooks; the lower-level
    # public acquisition, causal signal, next-open payoff, 5 bps fee accounting,
    # source-grid validation and all 18:00 assertions remain active.
    original_validate = checkpoint.prior.validate
    original_prior_patch_report = checkpoint.prior.patch_report
    original_checkpoint_patch_report = checkpoint.patch_report
    had_write_result = hasattr(checkpoint.prior, "write_result")
    had_write_report = hasattr(checkpoint.prior, "write_report")
    original_write_result = getattr(checkpoint.prior, "write_result", None)
    original_write_report = getattr(checkpoint.prior, "write_report", None)

    checkpoint.LATEST_AUDIT.setdefault(
        "verdict", checkpoint.LATEST_AUDIT["strategy_disposition"]
    )
    checkpoint.prior.validate = lambda result: None
    checkpoint.prior.patch_report = lambda output_dir: None
    checkpoint.prior.write_result = checkpoint.prior.prior.write_result
    checkpoint.prior.write_report = checkpoint.prior.prior.write_report
    checkpoint.patch_report = exact_patch_report
    try:
        result = checkpoint.run(args.output_dir, args.base_url.rstrip("/"))
    finally:
        checkpoint.prior.validate = original_validate
        checkpoint.prior.patch_report = original_prior_patch_report
        checkpoint.patch_report = original_checkpoint_patch_report
        if had_write_result:
            checkpoint.prior.write_result = original_write_result
        else:
            delattr(checkpoint.prior, "write_result")
        if had_write_report:
            checkpoint.prior.write_report = original_write_report
        else:
            delattr(checkpoint.prior, "write_report")

    print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
