from __future__ import annotations

import argparse
import base64
import gzip
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--materialize", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(__file__).parent
    payload_paths = [root / f"run_research_impl.py.gz.b64.part{i:02d}" for i in range(4)]
    encoded = "".join(
        "".join(path.read_text(encoding="ascii").splitlines()) for path in payload_paths
    )
    source = gzip.decompress(base64.b64decode(encoded, validate=True))
    source.decode("utf-8")
    args.materialize.parent.mkdir(parents=True, exist_ok=True)
    args.materialize.write_bytes(source)


if __name__ == "__main__":
    main()
