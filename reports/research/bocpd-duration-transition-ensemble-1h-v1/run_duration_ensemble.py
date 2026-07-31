from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
from pathlib import Path

EXPECTED_SOURCE_SHA256 = "96783b2f600837f41aec9c168215671b85540c72f38a3b9d94e0ee90306a788b"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--materialize", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload_path = Path(__file__).with_name("run_duration_ensemble_impl.py.gz.b64")
    encoded = "".join(payload_path.read_text(encoding="ascii").splitlines())
    source = gzip.decompress(base64.b64decode(encoded, validate=True))
    digest = hashlib.sha256(source).hexdigest()
    if digest != EXPECTED_SOURCE_SHA256:
        raise RuntimeError(f"materialized source SHA-256 mismatch: {digest}")
    source.decode("utf-8")
    args.materialize.parent.mkdir(parents=True, exist_ok=True)
    args.materialize.write_bytes(source)


if __name__ == "__main__":
    main()
