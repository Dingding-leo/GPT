#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from gpt_quant.walk_forward_verify import verify_walk_forward_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Recompute and hash a persisted canonical 5 bps walk-forward report."
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--verification-path",
        help="Defaults to <output-dir>/walk_forward_verification.json.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = Path(args.output_dir)
    verification = verify_walk_forward_report(output)
    verification_path = (
        Path(args.verification_path)
        if args.verification_path
        else output / "walk_forward_verification.json"
    )
    verification_path.parent.mkdir(parents=True, exist_ok=True)
    verification_path.write_text(
        json.dumps(verification, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"verification_status={verification['status']}")
    print(f"verification_path={verification_path}")
    print(f"report_json_sha256={verification['report_json_sha256']}")
    print(f"returns_csv_sha256={verification['returns_csv_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
