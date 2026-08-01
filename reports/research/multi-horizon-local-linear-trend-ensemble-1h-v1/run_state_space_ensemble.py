from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
from pathlib import Path

EXPECTED_SOURCE_SHA256 = "d92b9626a9429c2177f292ddef7555dbf4b2f3c713ccf120ef4708906c7c49c3"
EXPECTED_PARTS = 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--materialize", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(__file__).parent
    parts = sorted(root.glob("payload.part.*"))
    if len(parts) != EXPECTED_PARTS:
        raise RuntimeError(f"expected {EXPECTED_PARTS} payload parts, found {len(parts)}")
    encoded = "".join(part.read_text(encoding="ascii").strip() for part in parts)
    source = gzip.decompress(base64.b64decode(encoded, validate=True))
    digest = hashlib.sha256(source).hexdigest()
    if digest != EXPECTED_SOURCE_SHA256:
        raise RuntimeError(f"materialized source SHA-256 mismatch: {digest}")
    source.decode("utf-8")
    args.materialize.parent.mkdir(parents=True, exist_ok=True)
    args.materialize.write_bytes(source)


if __name__ == "__main__":
    main()
