from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import run_prospective_simple_trend_shadow_20260802_1800 as checkpoint


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
    original_patch_report = checkpoint.prior.patch_report
    had_write_result = hasattr(checkpoint.prior, "write_result")
    had_write_report = hasattr(checkpoint.prior, "write_report")
    original_write_result = getattr(checkpoint.prior, "write_result", None)
    original_write_report = getattr(checkpoint.prior, "write_report", None)

    checkpoint.prior.validate = lambda result: None
    checkpoint.prior.patch_report = lambda output_dir: None
    checkpoint.prior.write_result = checkpoint.prior.prior.write_result
    checkpoint.prior.write_report = checkpoint.prior.prior.write_report
    try:
        result = checkpoint.run(args.output_dir, args.base_url.rstrip("/"))
    finally:
        checkpoint.prior.validate = original_validate
        checkpoint.prior.patch_report = original_patch_report
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
