#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

from gpt_quant.okx import write_okx_snapshot
from gpt_quant.okx_1h import (
    fetch_okx_one_hour_candles,
    replay_persisted_okx_one_hour_snapshot,
)
from gpt_quant.okx_execution_quote import _required_base_url
from gpt_quant.okx_live_response_evidence import sample_okx_server_time_with_response

_SCHEMA_VERSION = 1
_BAR = "1H"
_MARKET_TYPE = "spot"
_DEFAULT_INSTRUMENTS = ("BTC-USDT", "ETH-USDT")


def _canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_once_or_same(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise FileExistsError(f"refusing to replace different immutable evidence: {path}")
        return
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


def _utc_timestamp(value: str, *, field: str) -> pd.Timestamp:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must be a valid timestamp") from exc
    if pd.isna(timestamp):
        raise ValueError(f"{field} must be a valid timestamp")
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    if timestamp != timestamp.floor("h"):
        raise ValueError(f"{field} must align to an exact UTC hour")
    return timestamp


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Acquire and replay immutable public OKX spot 1H coverage without research."
    )
    parser.add_argument("--output-dir", default="reports/okx/1h-coverage")
    parser.add_argument("--start", default="2021-07-24T00:00:00Z")
    parser.add_argument("--base-url", default=os.environ.get("OKX_BASE_URL", "https://www.okx.com"))
    parser.add_argument("--instrument", action="append", dest="instruments")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--pause-seconds", type=float, default=0.12)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--server-max-round-trip-seconds", type=float, default=2.0)
    parser.add_argument("--server-max-abs-clock-skew-seconds", type=float, default=5.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    instruments = tuple(args.instruments or _DEFAULT_INSTRUMENTS)
    if not instruments or len(set(instruments)) != len(instruments):
        raise ValueError("instruments must be a non-empty unique list")
    requested_start = _utc_timestamp(args.start, field="start")
    base_url = _required_base_url(args.base_url)
    output = Path(args.output_dir)

    server_observation = sample_okx_server_time_with_response(
        base_url=base_url,
        timeout=args.timeout,
        max_round_trip_seconds=args.server_max_round_trip_seconds,
        max_abs_clock_skew_seconds=args.server_max_abs_clock_skew_seconds,
    )
    exchange_time = pd.Timestamp(server_observation.sample.server_time_utc).tz_convert("UTC")
    requested_end = exchange_time.floor("h") - pd.Timedelta(hours=1)
    if requested_end < requested_start:
        raise ValueError("OKX exchange time does not permit the requested 1H history window")

    public_time_path = output / "okx-public-time.canonical.json"
    _write_once_or_same(public_time_path, server_observation.response_json)

    instrument_evidence: dict[str, dict[str, Any]] = {}
    for inst_id in instruments:
        snapshot = fetch_okx_one_hour_candles(
            inst_id=inst_id,
            start=requested_start,
            end=requested_end,
            base_url=base_url,
            limit=args.limit,
            pause_seconds=args.pause_seconds,
            timeout=args.timeout,
        )
        snapshot_dir = output / inst_id / "snapshot"
        paths = write_okx_snapshot(snapshot, snapshot_dir)
        replayed = replay_persisted_okx_one_hour_snapshot(snapshot_dir, inst_id=inst_id)
        if not replayed.candles.equals(snapshot.candles):
            raise ValueError(f"persisted OKX 1H replay differs for {inst_id}")
        metadata_bytes = paths["metadata"].read_bytes()
        instrument_evidence[inst_id] = {
            "provider": "OKX",
            "endpoint": snapshot.metadata["endpoint"],
            "market_type": _MARKET_TYPE,
            "bar": _BAR,
            "requested_start": snapshot.metadata["requested_start"],
            "requested_end": snapshot.metadata["requested_end"],
            "effective_start": snapshot.metadata["start"],
            "effective_end": snapshot.metadata["end"],
            "expected_step_seconds": snapshot.metadata["expected_step_seconds"],
            "observations": snapshot.metadata["observations"],
            "pages": snapshot.metadata["pages"],
            "max_pages": snapshot.metadata["max_pages"],
            "duplicates_removed": snapshot.metadata["duplicates_removed"],
            "missing_intervals": snapshot.metadata["missing_intervals"],
            "incomplete_rows_removed": snapshot.metadata["incomplete_rows_removed"],
            "pagination_termination": snapshot.metadata["pagination_termination"],
            "requested_start_reached": snapshot.metadata["requested_start_reached"],
            "finality": "confirm=1_only",
            "offline_replay_equal": True,
            "normalized_csv_sha256": snapshot.metadata["normalized_csv_sha256"],
            "raw_pages_sha256": snapshot.metadata["raw_pages_sha256"],
            "metadata_sha256": _sha256(metadata_bytes),
            "paths": {name: str(path) for name, path in sorted(paths.items())},
        }

    starts = {item["effective_start"] for item in instrument_evidence.values()}
    ends = {item["effective_end"] for item in instrument_evidence.values()}
    observations = {item["observations"] for item in instrument_evidence.values()}
    if len(starts) != 1 or len(ends) != 1 or len(observations) != 1:
        raise ValueError("OKX 1H instruments do not share one exact common coverage window")

    manifest = {
        "schema_version": _SCHEMA_VERSION,
        "provider": "OKX",
        "market_type": _MARKET_TYPE,
        "bar": _BAR,
        "base_url": base_url,
        "instruments": list(instruments),
        "requested_start": requested_start.isoformat(),
        "requested_end": requested_end.isoformat(),
        "common_effective_start": next(iter(starts)),
        "common_effective_end": next(iter(ends)),
        "common_observations": next(iter(observations)),
        "expected_step_seconds": 3_600,
        "coverage_complete": True,
        "offline_replay_verified": True,
        "exchange_time_evidence": {
            "endpoint": server_observation.sample.endpoint,
            "server_time_utc": exchange_time.isoformat(),
            "local_request_started_utc": (
                server_observation.sample.local_request_started_utc.isoformat()
            ),
            "local_response_received_utc": (
                server_observation.sample.local_response_received_utc.isoformat()
            ),
            "round_trip_seconds": server_observation.sample.round_trip_seconds,
            "midpoint_clock_skew_seconds": server_observation.sample.midpoint_clock_skew_seconds,
            "max_round_trip_seconds": args.server_max_round_trip_seconds,
            "max_abs_clock_skew_seconds": args.server_max_abs_clock_skew_seconds,
            "canonical_response_path": str(public_time_path),
            "canonical_response_sha256": server_observation.response_sha256,
        },
        "instruments_evidence": instrument_evidence,
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
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_path = output / "coverage-manifest.json"
    _write_once_or_same(manifest_path, manifest_bytes)
    print(f"manifest_path={manifest_path}")
    print(f"manifest_sha256={_sha256(manifest_bytes)}")
    print(f"common_start={manifest['common_effective_start']}")
    print(f"common_end={manifest['common_effective_end']}")
    print(f"common_observations={manifest['common_observations']}")
    for inst_id in instruments:
        item = instrument_evidence[inst_id]
        print(f"{inst_id}_pages={item['pages']}")
        print(f"{inst_id}_raw_pages_sha256={item['raw_pages_sha256']}")
        print(f"{inst_id}_normalized_csv_sha256={item['normalized_csv_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
