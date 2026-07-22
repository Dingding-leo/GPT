#!/usr/bin/env python3
from __future__ import annotations

import argparse

from gpt_quant.experiment_registry import merge_experiment_manifests


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge verified experiment manifests into an append-only registry."
    )
    parser.add_argument("--registry", required=True)
    parser.add_argument("--manifest", action="append", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = merge_experiment_manifests(args.registry, args.manifest)
    print(f"registry_path={result.registry_path}")
    print(f"existing_runs={result.existing_runs}")
    print(f"appended_runs={result.appended_runs}")
    print(f"skipped_runs={result.skipped_runs}")
    print(f"total_runs={result.total_runs}")
    print(f"registry_sha256={result.registry_sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
