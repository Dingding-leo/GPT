#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_HEX_DIGITS = frozenset("0123456789abcdef")
_REQUIRED_METADATA_FIELDS = {
    "provider",
    "instrument_id",
    "bar",
    "observations",
    "start",
    "end",
    "normalized_csv_sha256",
}
_OPTIONAL_PROVENANCE_FIELDS = (
    "source_workflow_run_id",
    "source_artifact_id",
    "source_artifact_name",
    "source_artifact_sha256",
    "source_head_sha",
)


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_sha256(value: object, label: str) -> str:
    digest = _require_text(value, label).lower()
    if len(digest) != 64 or set(digest) - _HEX_DIGITS:
        raise ValueError(f"{label} must be a SHA-256 digest")
    return digest


def _parse_aware_utc(value: object, label: str) -> datetime:
    text = _require_text(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include an explicit timezone")
    return parsed.astimezone(UTC)


def _load_metadata(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("OKX metadata is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("OKX metadata must contain a JSON object")
    missing = sorted(_REQUIRED_METADATA_FIELDS - set(value))
    if missing:
        raise ValueError(f"OKX metadata is missing required fields: {missing}")
    return value


def _inspect_csv(path: Path) -> tuple[list[str], int, datetime, datetime]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle, strict=True)
            try:
                columns = next(reader)
            except StopIteration as exc:
                raise ValueError("snapshot CSV is empty") from exc
            if not columns or any(not column for column in columns):
                raise ValueError("snapshot CSV header must contain non-empty column names")
            if len(columns) != len(set(columns)):
                raise ValueError("snapshot CSV header must contain unique column names")
            if "timestamp" not in columns or "close" not in columns:
                raise ValueError("snapshot CSV must contain timestamp and close columns")
            timestamp_index = columns.index("timestamp")
            observations = 0
            first_timestamp: datetime | None = None
            last_timestamp: datetime | None = None
            for row_number, row in enumerate(reader, start=2):
                if len(row) != len(columns):
                    raise ValueError(
                        f"snapshot CSV row {row_number} has {len(row)} fields; "
                        f"expected {len(columns)}"
                    )
                timestamp = _parse_aware_utc(
                    row[timestamp_index], f"snapshot CSV timestamp on row {row_number}"
                )
                if first_timestamp is None:
                    first_timestamp = timestamp
                last_timestamp = timestamp
                observations += 1
    except (csv.Error, UnicodeDecodeError) as exc:
        raise ValueError("snapshot CSV could not be parsed") from exc

    if observations < 1 or first_timestamp is None or last_timestamp is None:
        raise ValueError("snapshot CSV must contain at least one observation")
    return columns, observations, first_timestamp, last_timestamp


def _build_provenance(metadata: dict[str, Any], metadata_path: Path) -> dict[str, Any]:
    provenance: dict[str, Any] = {"source_metadata_path": metadata_path.name}
    if "fetched_at_utc" in metadata:
        retrieved = _parse_aware_utc(metadata["fetched_at_utc"], "metadata.fetched_at_utc")
        provenance["retrieved_at_utc"] = retrieved.isoformat()
    for field in _OPTIONAL_PROVENANCE_FIELDS:
        if field in metadata:
            provenance[field] = metadata[field]

    raw_digest = metadata.get("raw_pages_sha256", metadata.get("source_raw_pages_sha256"))
    if raw_digest is not None:
        provenance["raw_pages_sha256"] = _require_sha256(raw_digest, "metadata.raw_pages_sha256")
    if "retrieved_at_utc" not in provenance and "source_workflow_run_id" not in provenance:
        raise ValueError(
            "metadata must provide fetched_at_utc or source_workflow_run_id for provenance"
        )
    return provenance


def create_manifest(
    *,
    metadata_path: str | Path,
    csv_path: str | Path,
    output_path: str | Path,
    market_type: str = "spot",
) -> dict[str, Any]:
    metadata_source = Path(metadata_path).resolve(strict=True)
    csv_source = Path(csv_path).resolve(strict=True)
    output = Path(output_path)
    output_parent = output.parent.resolve(strict=True)
    output = output_parent / output.name

    if not metadata_source.is_file() or not csv_source.is_file():
        raise ValueError("metadata and CSV inputs must be regular files")
    if metadata_source.parent != output_parent or csv_source.parent != output_parent:
        raise ValueError("metadata, CSV, and output manifest must share one directory")
    if output in {metadata_source, csv_source}:
        raise ValueError("output manifest must not overwrite metadata or CSV input")

    metadata = _load_metadata(metadata_source)
    expected_hash = _require_sha256(
        metadata["normalized_csv_sha256"], "metadata.normalized_csv_sha256"
    )
    actual_hash = _sha256_file(csv_source)
    if actual_hash != expected_hash:
        raise ValueError(
            "metadata normalized_csv_sha256 does not match CSV bytes: "
            f"expected {expected_hash}, actual {actual_hash}"
        )

    columns, observations, first_timestamp, last_timestamp = _inspect_csv(csv_source)
    declared_observations = metadata["observations"]
    if (
        isinstance(declared_observations, bool)
        or not isinstance(declared_observations, int)
        or declared_observations < 1
    ):
        raise ValueError("metadata.observations must be a positive integer")
    if observations != declared_observations:
        raise ValueError(
            f"metadata observation count mismatch: expected {declared_observations}, "
            f"actual {observations}"
        )

    declared_start = _parse_aware_utc(metadata["start"], "metadata.start")
    declared_end = _parse_aware_utc(metadata["end"], "metadata.end")
    if first_timestamp != declared_start or last_timestamp != declared_end:
        raise ValueError("metadata start/end do not match the snapshot CSV boundaries")

    manifest = {
        "schema_version": 1,
        "provider": _require_text(metadata["provider"], "metadata.provider"),
        "market_type": _require_text(market_type, "market_type"),
        "instrument_id": _require_text(metadata["instrument_id"], "metadata.instrument_id"),
        "timeframe": _require_text(metadata["bar"], "metadata.bar"),
        "schema": {
            "columns": columns,
            "timestamp_column": "timestamp",
            "close_column": "close",
        },
        "observations": observations,
        "start": first_timestamp.isoformat(),
        "end": last_timestamp.isoformat(),
        "data_path": csv_source.name,
        "data_sha256": actual_hash,
        "provenance": _build_provenance(metadata, metadata_source),
    }
    payload = (
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    )
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(output)
    return manifest


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create a schema-v1 verified-snapshot manifest from one repository-generated "
            "OKX CSV and its metadata."
        )
    )
    parser.add_argument("--metadata", required=True, help="OKX snapshot metadata JSON path")
    parser.add_argument("--csv", required=True, help="normalized OKX snapshot CSV path")
    parser.add_argument("--output", required=True, help="schema-v1 manifest output path")
    parser.add_argument("--market-type", default="spot")
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    return _build_parser().parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        manifest = create_manifest(
            metadata_path=args.metadata,
            csv_path=args.csv,
            output_path=args.output,
            market_type=args.market_type,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    output = Path(args.output).resolve()
    print(f"snapshot_manifest={output}")
    print(f"data_sha256={manifest['data_sha256']}")
    print(f"observations={manifest['observations']}")
    print(f"start={manifest['start']}")
    print(f"end={manifest['end']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
