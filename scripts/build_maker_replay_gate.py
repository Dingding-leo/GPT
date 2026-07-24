from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from gpt_quant.maker_fill_replay import (
    OKXPublicTradeSnapshot,
    simulate_post_only_maker_fill,
)

_SCHEMA_VERSION = 2
_EXPECTED_SOURCE_SHA256 = (
    "01438cc23709d9c8e9ea8d9d49d3f64c65978d27d592356a333f7a3da213d563"
)
_MANIFEST_NAME = "artifact-manifest.sha256"
_GATE_NAME = "maker-order-replay-gate.json"
_NO_FILL_NAME = "cancelled-no-fill.json"
_PARTIAL_FILL_NAME = "cancelled-partial.json"
_REQUIRED_PATHS = (
    _NO_FILL_NAME,
    _PARTIAL_FILL_NAME,
    _GATE_NAME,
    "source/metadata.json",
    "source/response.json",
)
_SIGNAL = datetime(2022, 6, 2, 9, 0, tzinfo=UTC)
_SUBMITTED = datetime(2022, 6, 2, 9, 20, 40, tzinfo=UTC)
_NO_FILL_EXPIRY = datetime(2022, 6, 2, 9, 20, 45, tzinfo=UTC)
_PARTIAL_FILL_EXPIRY = datetime(2022, 6, 2, 9, 20, 50, tzinfo=UTC)
_ORDER_INTENT_ID = "a" * 64
_COMPLETE_CAPTURE_SOURCE_KIND = "complete_public_trade_capture"
_COVERAGE_BLOCKER = "complete_submission_to_expiry_trade_coverage_missing"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return text.encode("utf-8")


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"unreadable JSON evidence: {path.name}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"JSON evidence must be an object: {path.name}")
    return payload


def _utc_metadata_timestamp(value: object, *, field: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a UTC timestamp string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be a UTC timestamp string") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed.astimezone(UTC)


def _modeled_economics() -> dict[str, Any]:
    return {
        "exchange_fee_one_way_bps": "5",
        "fee_only_modeled_pnl": True,
        "impact": "separate_not_modeled",
        "latency": "separate_not_modeled",
        "slippage": "separate_not_modeled",
        "spread": "separate_not_modeled",
    }


def _replay_arguments(*, expires_at_utc: datetime, quantity: str) -> dict[str, Any]:
    return {
        "order_intent_id": _ORDER_INTENT_ID,
        "signal_at_utc": _SIGNAL,
        "submitted_at_utc": _SUBMITTED,
        "expires_at_utc": expires_at_utc,
        "side": "buy",
        "limit_price": "29964.1",
        "requested_base_quantity": quantity,
        "queue_ahead_base_quantity": "0",
    }


def _scenario_arguments() -> dict[str, dict[str, Any]]:
    return {
        _NO_FILL_NAME: _replay_arguments(
            expires_at_utc=_NO_FILL_EXPIRY,
            quantity="0.00001",
        ),
        _PARTIAL_FILL_NAME: _replay_arguments(
            expires_at_utc=_PARTIAL_FILL_EXPIRY,
            quantity="0.00002",
        ),
    }


def _build_replays(
    source_bytes: bytes,
) -> tuple[OKXPublicTradeSnapshot, dict[str, bytes]]:
    if _sha256_bytes(source_bytes) != _EXPECTED_SOURCE_SHA256:
        raise ValueError("OKX public trade source hash mismatch")
    snapshot = OKXPublicTradeSnapshot.from_json_bytes(source_bytes)

    replay_bytes: dict[str, bytes] = {}
    for filename, arguments in _scenario_arguments().items():
        first = simulate_post_only_maker_fill(snapshot, **arguments)
        second = simulate_post_only_maker_fill(snapshot, **arguments)
        if first != second or first.to_json_bytes() != second.to_json_bytes():
            raise ValueError("maker replay is not deterministic")
        replay_bytes[filename] = first.to_json_bytes()

    no_fill = json.loads(replay_bytes[_NO_FILL_NAME])
    partial_fill = json.loads(replay_bytes[_PARTIAL_FILL_NAME])
    if no_fill.get("outcome") != "cancelled_no_fill":
        raise ValueError("maker replay did not preserve the no-fill scenario")
    if partial_fill.get("outcome") != "cancelled_partial":
        raise ValueError("maker replay did not preserve the partial-fill scenario")
    if (
        no_fill.get("filled_base_quantity") != "0"
        or no_fill.get("exchange_fee_quote") != "0"
    ):
        raise ValueError("no-fill scenario must not create quantity or fee")
    if partial_fill.get("exchange_fee_one_way_bps") != "5":
        raise ValueError("partial-fill scenario must use exactly 5 bps one-way")
    return snapshot, replay_bytes


def _coverage_evidence(metadata: Mapping[str, Any]) -> dict[str, Any]:
    source_kind = metadata.get("source_kind")
    coverage_start_raw = metadata.get(
        "coverage_start_utc", metadata.get("exchange_start_utc")
    )
    coverage_end_raw = metadata.get(
        "coverage_end_utc", metadata.get("exchange_end_utc")
    )
    coverage_start = _utc_metadata_timestamp(
        coverage_start_raw,
        field="coverage_start_utc",
    )
    coverage_end = _utc_metadata_timestamp(
        coverage_end_raw,
        field="coverage_end_utc",
    )
    source_declares_complete = metadata.get("coverage_complete") is True
    source_is_complete_capture = source_kind == _COMPLETE_CAPTURE_SOURCE_KIND
    brackets_submission = coverage_start is not None and coverage_start <= _SUBMITTED
    brackets_expiry = coverage_end is not None and coverage_end >= _PARTIAL_FILL_EXPIRY
    passes = (
        source_declares_complete
        and source_is_complete_capture
        and brackets_submission
        and brackets_expiry
    )
    return {
        "coverage_complete_declared": source_declares_complete,
        "coverage_start_utc": coverage_start_raw,
        "coverage_end_utc": coverage_end_raw,
        "required_submission_utc": _SUBMITTED.isoformat().replace("+00:00", "Z"),
        "required_expiry_utc": _PARTIAL_FILL_EXPIRY.isoformat().replace("+00:00", "Z"),
        "source_kind": source_kind,
        "source_kind_is_complete_capture": source_is_complete_capture,
        "submission_bracketed": brackets_submission,
        "expiry_bracketed": brackets_expiry,
        "complete_submission_to_expiry": passes,
    }


def _gate_payload(
    *,
    snapshot: OKXPublicTradeSnapshot,
    replay_bytes: Mapping[str, bytes],
    metadata: Mapping[str, Any],
    metadata_sha256: str,
) -> dict[str, Any]:
    replays: dict[str, Any] = {}
    structural_outcomes: list[str] = []
    for filename in (_NO_FILL_NAME, _PARTIAL_FILL_NAME):
        replay = json.loads(replay_bytes[filename])
        outcome = replay["outcome"]
        structural_outcomes.append(outcome)
        replays[outcome] = {
            "evidence_file": filename,
            "evidence_sha256": _sha256_bytes(replay_bytes[filename]),
            "exchange_fee_quote": replay["exchange_fee_quote"],
            "filled_base_quantity": replay["filled_base_quantity"],
            "replay_id": replay["replay_id"],
            "requote_eligible": replay["requote_eligible"],
            "touch_trade_count": replay["touch_trade_count"],
            "trade_through_trade_count": replay["trade_through_trade_count"],
            "unfilled_base_quantity": replay["unfilled_base_quantity"],
        }

    coverage = _coverage_evidence(metadata)
    replay_passes = coverage["complete_submission_to_expiry"] is True
    blockers = [] if replay_passes else [_COVERAGE_BLOCKER]
    return {
        "schema_version": _SCHEMA_VERSION,
        "canonical_timeframe": "1H",
        "benchmark_timeframe": "1Dutc",
        "optional_next_timeframe": "15m",
        "evidence_integrity_passes": True,
        "mechanics_replay_passes": True,
        "execution_interval_coverage_passes": replay_passes,
        "maker_order_replay_passes": replay_passes,
        "replay_equivalent": True,
        "outcome_evidence_scope": (
            "terminal_execution_evidence" if replay_passes else "structural_scenario_only"
        ),
        "modeled_economics": _modeled_economics(),
        "source": {
            "provider": "OKX",
            "endpoint": "/api/v5/market/trades",
            "instrument_id": snapshot.instrument_id,
            "response_sha256": snapshot.source_sha256,
            "metadata_sha256": metadata_sha256,
            "trade_snapshot_id": snapshot.snapshot_id,
            "source_kind": metadata.get("source_kind"),
            "coverage": coverage,
        },
        "execution_policy": {
            "order_type": "post_only_limit",
            "same_price_touch_is_fill": False,
            "strict_trade_through_required": True,
            "queue_ahead_is_explicit": True,
            "terminal_cancellation_requires_complete_interval": True,
        },
        "required_outcomes": ["cancelled_no_fill", "cancelled_partial"],
        "structural_outcomes": structural_outcomes,
        "observed_outcomes": structural_outcomes if replay_passes else [],
        "replays": replays,
        "account_connectivity": "disabled",
        "order_submission": "not_performed",
        "blockers": blockers,
    }


def _write_manifest(root: Path) -> str:
    entries: list[str] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if relative != _MANIFEST_NAME:
            entries.append(f"{_sha256_file(path)}  {relative}\n")
    manifest_bytes = "".join(entries).encode("utf-8")
    (root / _MANIFEST_NAME).write_bytes(manifest_bytes)
    return _sha256_bytes(manifest_bytes)


def _parse_manifest(root: Path) -> dict[str, str]:
    try:
        lines = (root / _MANIFEST_NAME).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError("maker replay manifest is unreadable") from exc

    entries: dict[str, str] = {}
    previous = ""
    for line in lines:
        if len(line) < 67 or line[64:66] != "  ":
            raise ValueError("maker replay manifest entry is malformed")
        digest, relative = line[:64], line[66:]
        if any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("maker replay manifest digest is malformed")
        pure = PurePosixPath(relative)
        if pure.is_absolute() or ".." in pure.parts or relative != pure.as_posix():
            raise ValueError("maker replay manifest path is unsafe")
        if relative <= previous:
            raise ValueError("maker replay manifest entries must be unique and sorted")
        previous = relative
        entries[relative] = digest
    return entries


def verify_evidence(output_dir: str | Path) -> dict[str, Any]:
    root = Path(output_dir).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("maker replay evidence root must be a directory")
    entries = _parse_manifest(root)
    if tuple(entries) != _REQUIRED_PATHS:
        raise ValueError("maker replay manifest inventory is incomplete or unexpected")
    for relative, expected_digest in entries.items():
        path = root / relative
        if not path.is_file() or _sha256_file(path) != expected_digest:
            raise ValueError(f"maker replay artifact digest mismatch: {relative}")

    source_bytes = (root / "source" / "response.json").read_bytes()
    metadata_path = root / "source" / "metadata.json"
    metadata = _load_json_object(metadata_path)
    if metadata.get("response_sha256") != _EXPECTED_SOURCE_SHA256:
        raise ValueError("maker replay metadata source hash mismatch")
    snapshot, replay_bytes = _build_replays(source_bytes)
    for filename, expected_bytes in replay_bytes.items():
        if (root / filename).read_bytes() != expected_bytes:
            raise ValueError(f"maker replay reconstruction mismatch: {filename}")

    expected_gate = _gate_payload(
        snapshot=snapshot,
        replay_bytes=replay_bytes,
        metadata=metadata,
        metadata_sha256=_sha256_file(metadata_path),
    )
    gate_path = root / _GATE_NAME
    if gate_path.read_bytes() != _canonical_json_bytes(expected_gate):
        raise ValueError("maker replay gate reconstruction mismatch")
    if _load_json_object(gate_path) != expected_gate:
        raise ValueError("maker replay gate semantic mismatch")
    return expected_gate


def build_evidence(
    *,
    source_response: str | Path,
    source_metadata: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    response_path = Path(source_response).resolve(strict=True)
    metadata_path = Path(source_metadata).resolve(strict=True)
    source_bytes = response_path.read_bytes()
    metadata_bytes = metadata_path.read_bytes()
    metadata = json.loads(metadata_bytes)
    if not isinstance(metadata, dict):
        raise ValueError("OKX public trade metadata must be an object")
    if metadata.get("response_sha256") != _EXPECTED_SOURCE_SHA256:
        raise ValueError("OKX public trade metadata hash does not match the fixture")

    snapshot, replay_bytes = _build_replays(source_bytes)
    gate = _gate_payload(
        snapshot=snapshot,
        replay_bytes=replay_bytes,
        metadata=metadata,
        metadata_sha256=_sha256_bytes(metadata_bytes),
    )

    output = Path(output_dir).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    try:
        (temporary / "source").mkdir(parents=True)
        (temporary / "source" / "response.json").write_bytes(source_bytes)
        (temporary / "source" / "metadata.json").write_bytes(metadata_bytes)
        for filename, payload in replay_bytes.items():
            (temporary / filename).write_bytes(payload)
        (temporary / _GATE_NAME).write_bytes(_canonical_json_bytes(gate))
        _write_manifest(temporary)
        verify_evidence(temporary)
        if output.exists():
            if not output.is_dir():
                raise ValueError("maker replay output path must be a directory")
            shutil.rmtree(output)
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return verify_evidence(output)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build or verify maker replay gate evidence")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--source-response")
    parser.add_argument("--source-metadata")
    parser.add_argument("--verify-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.verify_only:
        gate = verify_evidence(args.output_dir)
    else:
        if not args.source_response or not args.source_metadata:
            raise SystemExit(
                "--source-response and --source-metadata are required when building"
            )
        gate = build_evidence(
            source_response=args.source_response,
            source_metadata=args.source_metadata,
            output_dir=args.output_dir,
        )
    manifest_sha256 = _sha256_file(Path(args.output_dir) / _MANIFEST_NAME)
    print(
        json.dumps(
            {
                "blockers": gate["blockers"],
                "execution_interval_coverage_passes": gate[
                    "execution_interval_coverage_passes"
                ],
                "manifest_sha256": manifest_sha256,
                "maker_order_replay_passes": gate["maker_order_replay_passes"],
                "observed_outcomes": gate["observed_outcomes"],
                "replay_equivalent": gate["replay_equivalent"],
                "structural_outcomes": gate["structural_outcomes"],
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
