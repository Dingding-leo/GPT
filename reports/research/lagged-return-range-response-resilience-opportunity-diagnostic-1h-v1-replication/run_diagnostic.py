from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SOURCE_COMMIT = "086d7b419d29c29330f90d4d190c75cc41ab34fd"
SOURCE_PATH = (
    "reports/research/lagged-return-range-response-resilience-opportunity-"
    "diagnostic-1h-v1/run_diagnostic.py"
)
REPLACEMENTS = {
    'FAMILY_ID = "lagged-return-range-response-resilience-opportunity-diagnostic-1h-v1"': (
        'FAMILY_ID = "lagged-return-range-response-resilience-opportunity-'
        'diagnostic-1h-v1-replication"'
    ),
    'MONTHS = ("2022-12",) + tuple(f"2023-{month:02d}" for month in range(1, 13))': (
        'MONTHS = ("2024-12",) + tuple(f"2025-{month:02d}" for month in range(1, 13))'
    ),
    'SOURCE_START = pd.Timestamp("2022-12-01T00:00:00Z")': (
        'SOURCE_START = pd.Timestamp("2024-12-01T00:00:00Z")'
    ),
    'SOURCE_END_EXCLUSIVE = pd.Timestamp("2024-01-01T00:00:00Z")': (
        'SOURCE_END_EXCLUSIVE = pd.Timestamp("2026-01-01T00:00:00Z")'
    ),
    'SCORE_START = pd.Timestamp("2023-02-01T00:00:00Z")': (
        'SCORE_START = pd.Timestamp("2025-02-01T00:00:00Z")'
    ),
    'SCORE_END = pd.Timestamp("2023-12-30T00:00:00Z")': (
        'SCORE_END = pd.Timestamp("2025-12-30T00:00:00Z")'
    ),
    'USER_AGENT = "gpt-quant-lab/lagged-return-range-response-resilience"': (
        'USER_AGENT = "gpt-quant-lab/lagged-return-range-response-resilience-replication"'
    ),
    'period="2022-12..2023-12"': 'period="2024-12..2025-12"',
}


def load_frozen_program() -> dict[str, Any]:
    source = subprocess.run(
        ["git", "show", f"{SOURCE_COMMIT}:{SOURCE_PATH}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    for old, new in REPLACEMENTS.items():
        if source.count(old) != 1:
            raise RuntimeError(f"frozen source replacement count is not one: {old}")
        source = source.replace(old, new)
    namespace: dict[str, Any] = {
        "__file__": f"{SOURCE_COMMIT}:{SOURCE_PATH}",
        "__name__": "frozen_lagged_response_replication",
    }
    exec(compile(source, namespace["__file__"], "exec"), namespace)
    return namespace


def output_directory() -> Path:
    try:
        position = sys.argv.index("--output-dir")
        return Path(sys.argv[position + 1])
    except (ValueError, IndexError) as exc:
        raise RuntimeError("--output-dir is required") from exc


def bind_reproducer_provenance(directory: Path) -> None:
    evidence_path = directory / "evidence.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["reproducer"] = {
        "source_commit": SOURCE_COMMIT,
        "source_path": SOURCE_PATH,
        "replacement_count": len(REPLACEMENTS),
        "replacement_scope": "family identifier, immutable source dates, and user agent only",
    }
    evidence_path.write_text(
        json.dumps(evidence, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    (directory / "evidence.sha256").write_text(
        f"{digest}  evidence.json\n", encoding="utf-8"
    )
    with (directory / "report.md").open("a", encoding="utf-8") as report:
        report.write(
            "\n## Reproducer provenance\n\n"
            f"Frozen source program: `{SOURCE_COMMIT}:{SOURCE_PATH}`. "
            "Only the preregistered family identifier, immutable source dates, "
            "and user agent were replaced before execution.\n"
        )


def main() -> None:
    namespace = load_frozen_program()
    namespace["main"]()
    bind_reproducer_provenance(output_directory())


if __name__ == "__main__":
    main()
