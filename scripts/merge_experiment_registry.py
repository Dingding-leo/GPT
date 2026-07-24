from __future__ import annotations

import argparse
import json
from pathlib import Path

from gpt_quant.experiment_registry import merge_experiment_manifests


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge validated per-run experiment manifests into a durable registry."
    )
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--manifest", required=True, action="append", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = merge_experiment_manifests(args.registry, args.manifest)
    print(
        json.dumps(
            {
                "registry": str(result.path),
                "added_runs": result.added_runs,
                "skipped_runs": result.skipped_runs,
                "registry_sha256": result.registry_sha256,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
