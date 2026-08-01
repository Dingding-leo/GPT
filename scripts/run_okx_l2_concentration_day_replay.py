from __future__ import annotations

import argparse
import json
from pathlib import Path

import run_okx_l2_concentration_diagnostic as concentration
import run_okx_l2_day_replay as replay


def main() -> None:
    concentration.configure_core()
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest-path", type=Path, required=True)
    parser.add_argument("--market", choices=concentration.MARKETS, required=True)
    parser.add_argument("--anchor", choices=concentration.ANCHOR_DATES, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = replay.process_archive(
        args.manifest_path,
        args.market,
        args.anchor,
        args.output_dir,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
