from __future__ import annotations

import argparse
import json
import re
import stat
from pathlib import Path

from gpt_quant.execution_quote_evidence import load_execution_quote_evidence_store

_SHA256 = re.compile(r"[0-9a-f]{64}")


def verify_execution_quote_store(
    store_path: Path,
    *,
    expected_sha256: str,
    expected_count: int,
) -> dict[str, object]:
    if _SHA256.fullmatch(expected_sha256) is None:
        raise ValueError("expected SHA-256 must be 64 lowercase hexadecimal characters")
    if expected_count < 0:
        raise ValueError("expected count must be non-negative")

    try:
        path_stat = store_path.lstat()
    except FileNotFoundError as exc:
        raise FileNotFoundError("execution quote evidence store does not exist") from exc
    if not stat.S_ISDIR(path_stat.st_mode):
        raise ValueError("execution quote evidence store path must already be a directory")

    store = load_execution_quote_evidence_store(store_path)
    if store.count != expected_count:
        raise ValueError(
            f"execution quote evidence count mismatch: expected {expected_count}, got {store.count}"
        )
    if store.sha256 != expected_sha256:
        raise ValueError(
            "execution quote evidence SHA-256 mismatch: "
            f"expected {expected_sha256}, got {store.sha256}"
        )

    return {
        "count": store.count,
        "path": store_path.as_posix(),
        "sha256": store.sha256,
        "snapshot_ids": [snapshot.snapshot_id for snapshot in store.snapshots],
        "status": "verified",
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Replay an existing execution-quote evidence store and verify its expected root."
        )
    )
    parser.add_argument("--store", required=True, type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--expected-count", required=True, type=int)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    result = verify_execution_quote_store(
        args.store,
        expected_sha256=args.expected_sha256,
        expected_count=args.expected_count,
    )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
