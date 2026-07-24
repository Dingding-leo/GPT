from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from analysis import build_result


def compact_result(result: dict) -> dict:
    for details in result["markets"].values():
        details["month_stability"].pop("records", None)
        details["year_stability"].pop("records", None)
    return result


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
