from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import run_prospective_simple_trend_shadow_20260802_1900 as checkpoint


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--base-url", default=os.environ.get("OKX_BASE_URL", "https://www.okx.com")
    )
    args = parser.parse_args()

    # The inherited 17:00 module does not expose write_result/write_report until
    # its exact wrapper binds the lower-level writers. Bind those compatibility
    # hooks before entering the frozen 19:00 checkpoint. The inherited 16:00
    # report template also assumes an obsolete closure schema, so suppress only
    # that intermediate report; the 19:00 checkpoint persists its own verified
    # result and report after all strategy-facing fields are final. Restore every
    # module binding afterward. This changes no source row, signal, position,
    # fee, strategy parameter, scorecard value or target-return access boundary.
    prior = checkpoint.checkpoint.prior
    lower_prior = prior.prior
    had_write_result = hasattr(prior, "write_result")
    had_write_report = hasattr(prior, "write_report")
    original_write_result = getattr(prior, "write_result", None)
    original_write_report = getattr(prior, "write_report", None)
    original_lower_write_report = lower_prior.write_report

    prior.write_result = lower_prior.write_result
    prior.write_report = lambda output_dir, result: None
    lower_prior.write_report = lambda output_dir, result: None
    try:
        result = checkpoint.run(args.output_dir, args.base_url.rstrip("/"))
    finally:
        lower_prior.write_report = original_lower_write_report
        if had_write_result:
            prior.write_result = original_write_result
        else:
            delattr(prior, "write_result")
        if had_write_report:
            prior.write_report = original_write_report
        else:
            delattr(prior, "write_report")

    print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
