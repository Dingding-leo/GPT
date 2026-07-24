from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .okx_1h import replay_persisted_okx_one_hour_snapshot

_SCHEMA_VERSION = 1
_SOURCE_TRANSPORT = "trusted_okx_https_bounded_exact_bytes"
_OUTPUT_NAME = "intraday-1h-source-provenance.json"
_HEX_DIGITS = frozenset("0123456789abcdef")


def _canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _required_sha256(value: object, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or value.lower() != value
        or any(character not in _HEX_DIGITS for character in value)
    ):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _required_sha256_sequence(value: object, *, field: str) -> list[str]:
    if isinstance(value, str) or not isinstance(value, Sequence) or not value:
        raise ValueError(f"{field} must be a non-empty SHA-256 list")
    return [_required_sha256(item, field=f"{field}[{index}]") for index, item in enumerate(value)]


def _metadata_path(snapshot_dir: Path, inst_id: str) -> Path:
    stem = f"okx-{inst_id.replace('/', '-')}-1H"
    return snapshot_dir / f"{stem}.metadata.json"


def build_intraday_1h_source_provenance(
    output_dir: str | Path,
    *,
    inst_id: str,
) -> dict[str, Any]:
    """Reconstruct exact provider bytes and bind their inventory to research evidence."""

    output = Path(output_dir)
    snapshot_dir = output / "snapshot"
    replayed = replay_persisted_okx_one_hour_snapshot(snapshot_dir, inst_id=inst_id)
    metadata = replayed.metadata

    if metadata.get("provider") != "OKX":
        raise ValueError("intraday 1H source provider must equal OKX")
    if metadata.get("instrument_id") != inst_id or metadata.get("bar") != "1H":
        raise ValueError("intraday 1H source metadata does not match the requested instrument")
    if metadata.get("source_transport") != _SOURCE_TRANSPORT:
        raise ValueError("intraday 1H source is not bound to the exact-byte transport")
    source_hashes = _required_sha256_sequence(
        metadata.get("source_response_sha256"),
        field="source_response_sha256",
    )
    if metadata.get("source_response_count") != len(source_hashes):
        raise ValueError("intraday 1H source response count does not match its hash inventory")
    total_bytes = metadata.get("source_response_total_bytes")
    if isinstance(total_bytes, bool) or not isinstance(total_bytes, int) or total_bytes <= 0:
        raise ValueError("intraday 1H source response byte count must be positive")
    if metadata.get("expected_step_seconds") != 3_600:
        raise ValueError("intraday 1H source cadence must equal one hour")
    if metadata.get("missing_intervals") not in (0, None):
        raise ValueError("intraday 1H source contains missing intervals")
    if metadata.get("requested_start_reached") is not True:
        raise ValueError("intraday 1H source did not reach its requested start")

    metadata_path = _metadata_path(snapshot_dir, inst_id)
    metadata_sha256 = _sha256_bytes(metadata_path.read_bytes())
    inventory_bytes = _canonical_json_bytes({"source_response_sha256": source_hashes})
    return {
        "schema_version": _SCHEMA_VERSION,
        "provider": "OKX",
        "instrument_id": inst_id,
        "bar": "1H",
        "source_transport": _SOURCE_TRANSPORT,
        "offline_replay_verified": True,
        "source_response_count": len(source_hashes),
        "source_response_total_bytes": total_bytes,
        "source_response_sha256": source_hashes,
        "source_response_inventory_sha256": _sha256_bytes(inventory_bytes),
        "normalized_csv_sha256": _required_sha256(
            metadata.get("normalized_csv_sha256"),
            field="normalized_csv_sha256",
        ),
        "raw_pages_sha256": _required_sha256(
            metadata.get("raw_pages_sha256"),
            field="raw_pages_sha256",
        ),
        "metadata_sha256": metadata_sha256,
        "requested_start": metadata.get("requested_start"),
        "requested_end": metadata.get("requested_end"),
        "effective_start": metadata.get("start"),
        "effective_end": metadata.get("end"),
        "observations": metadata.get("observations"),
        "expected_step_seconds": metadata.get("expected_step_seconds"),
        "duplicates_removed": metadata.get("duplicates_removed"),
        "incomplete_rows_removed": metadata.get("incomplete_rows_removed"),
        "missing_intervals": metadata.get("missing_intervals"),
        "economic_boundary": {
            "modeled_fee_bps_one_way": 5.0,
            "spread": "separate_execution_diagnostic_not_modeled_here",
            "slippage": "separate_execution_diagnostic_not_modeled_here",
            "market_impact": "separate_execution_diagnostic_not_modeled_here",
            "latency": "separate_execution_diagnostic_not_modeled_here",
        },
        "safety": {
            "public_read_only_endpoints_only": True,
            "credentials_accessed": False,
            "accounts_accessed": False,
            "orders_placed": False,
        },
    }


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_intraday_1h_source_provenance(
    output_dir: str | Path,
    *,
    inst_id: str,
) -> tuple[Path, str]:
    payload = build_intraday_1h_source_provenance(output_dir, inst_id=inst_id)
    payload_bytes = _canonical_json_bytes(payload)
    output_path = Path(output_dir) / _OUTPUT_NAME
    _write_atomic(output_path, payload_bytes)
    return output_path, _sha256_bytes(payload_bytes)


def verify_intraday_1h_source_provenance(
    output_dir: str | Path,
    *,
    inst_id: str,
) -> dict[str, Any]:
    output_path = Path(output_dir) / _OUTPUT_NAME
    persisted = output_path.read_bytes()
    expected = build_intraday_1h_source_provenance(output_dir, inst_id=inst_id)
    expected_bytes = _canonical_json_bytes(expected)
    if persisted != expected_bytes:
        raise ValueError("persisted intraday 1H source provenance does not reconstruct exactly")
    return expected


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write or verify exact-byte replay provenance for canonical OKX 1H research."
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--inst-id", required=True)
    parser.add_argument("--verify-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_args(argv)
    if arguments.verify_only:
        payload = verify_intraday_1h_source_provenance(
            arguments.output_dir,
            inst_id=arguments.inst_id,
        )
        path = Path(arguments.output_dir) / _OUTPUT_NAME
        digest = _sha256_bytes(path.read_bytes())
    else:
        path, digest = write_intraday_1h_source_provenance(
            arguments.output_dir,
            inst_id=arguments.inst_id,
        )
        payload = verify_intraday_1h_source_provenance(
            arguments.output_dir,
            inst_id=arguments.inst_id,
        )
    print(f"source_provenance_path={path}")
    print(f"source_provenance_sha256={digest}")
    print(f"source_response_count={payload['source_response_count']}")
    print(f"observations={payload['observations']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
