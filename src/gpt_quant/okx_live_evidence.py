from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd

from .okx_live import OKXCompletedBarCutoff, OKXServerTimeSample

_SCHEMA_VERSION = 1
_PROVIDER = "OKX"
_PUBLIC_TIME_ENDPOINT = "/api/v5/public/time"
_HEX_DIGITS = frozenset("0123456789abcdef")


def _utc_text(value: Any, *, field: str) -> str:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a valid timezone-aware timestamp") from exc
    if pd.isna(timestamp) or timestamp.tzinfo is None:
        raise ValueError(f"{field} must be a valid timezone-aware timestamp")
    return timestamp.tz_convert("UTC").isoformat()


def _canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def build_okx_live_timing_evidence(
    *,
    sample: OKXServerTimeSample,
    cutoff: OKXCompletedBarCutoff,
) -> dict[str, Any]:
    """Build deterministic evidence for one completed-bar decision boundary."""

    if not sample.base_url or sample.base_url.rstrip("/") != sample.base_url:
        raise ValueError("OKX server-time base_url must be non-empty and normalized")
    if sample.endpoint != _PUBLIC_TIME_ENDPOINT:
        raise ValueError("OKX server-time evidence must use the public time endpoint")

    request_started = pd.Timestamp(
        _utc_text(sample.local_request_started_utc, field="request start")
    )
    response_received = pd.Timestamp(
        _utc_text(sample.local_response_received_utc, field="response receipt")
    )
    server_time = pd.Timestamp(_utc_text(sample.server_time_utc, field="server time"))
    bar_open = pd.Timestamp(_utc_text(cutoff.bar_open_utc, field="bar open"))
    bar_close = pd.Timestamp(_utc_text(cutoff.bar_close_utc, field="bar close"))
    observed_at = pd.Timestamp(
        _utc_text(cutoff.observed_at_utc, field="candle observation")
    )
    exchange_observed_at = pd.Timestamp(
        _utc_text(cutoff.exchange_observed_at_utc, field="exchange observation")
    )
    cutoff_response_received = pd.Timestamp(
        _utc_text(
            cutoff.server_time_response_received_utc,
            field="cutoff server-time response receipt",
        )
    )
    signal_not_before = pd.Timestamp(
        _utc_text(cutoff.signal_not_before_utc, field="signal cutoff")
    )

    if request_started > response_received:
        raise ValueError("OKX server-time request timestamps are reversed")
    if exchange_observed_at != server_time:
        raise ValueError("completed-bar cutoff is not bound to the supplied OKX server time")
    if cutoff_response_received != response_received:
        raise ValueError("completed-bar cutoff is not bound to the supplied response receipt")
    if bar_close > server_time:
        raise ValueError("completed bar closes after the supplied OKX server time")

    expected_round_trip = (response_received - request_started).total_seconds()
    if abs(float(sample.round_trip_seconds) - expected_round_trip) > 1e-9:
        raise ValueError("OKX server-time round trip does not match its timestamps")
    if abs(float(cutoff.server_round_trip_seconds) - expected_round_trip) > 1e-9:
        raise ValueError("completed-bar cutoff round trip does not match the sample")

    midpoint = request_started + (response_received - request_started) / 2
    expected_skew = (server_time - midpoint).total_seconds()
    if abs(float(sample.midpoint_clock_skew_seconds) - expected_skew) > 1e-9:
        raise ValueError("OKX server-time clock skew does not match its timestamps")
    if abs(float(cutoff.midpoint_clock_skew_seconds) - expected_skew) > 1e-9:
        raise ValueError("completed-bar cutoff clock skew does not match the sample")

    expected_signal_not_before = max(observed_at, server_time, response_received)
    if signal_not_before != expected_signal_not_before:
        raise ValueError("completed-bar signal cutoff does not match its source observations")
    expected_delay = (server_time - bar_close).total_seconds()
    if abs(float(cutoff.availability_delay_seconds) - expected_delay) > 1e-9:
        raise ValueError("completed-bar availability delay does not match its timestamps")

    if not cutoff.instrument_id or not cutoff.bar:
        raise ValueError("instrument_id and bar must be non-empty")

    return {
        "schema_version": _SCHEMA_VERSION,
        "provider": _PROVIDER,
        "source_url": f"{sample.base_url}{sample.endpoint}",
        "instrument_id": cutoff.instrument_id,
        "bar": cutoff.bar,
        "bar_open_utc": bar_open.isoformat(),
        "bar_close_utc": bar_close.isoformat(),
        "candle_observed_at_utc": observed_at.isoformat(),
        "server_time_request_started_utc": request_started.isoformat(),
        "server_time_response_received_utc": response_received.isoformat(),
        "exchange_server_time_utc": server_time.isoformat(),
        "signal_not_before_utc": signal_not_before.isoformat(),
        "availability_delay_seconds": float(cutoff.availability_delay_seconds),
        "server_round_trip_seconds": float(cutoff.server_round_trip_seconds),
        "midpoint_clock_skew_seconds": float(cutoff.midpoint_clock_skew_seconds),
        "max_server_round_trip_seconds": float(cutoff.max_server_round_trip_seconds),
        "max_abs_midpoint_clock_skew_seconds": float(
            cutoff.max_abs_midpoint_clock_skew_seconds
        ),
    }


def write_okx_live_timing_evidence(
    path: str | Path,
    *,
    sample: OKXServerTimeSample,
    cutoff: OKXCompletedBarCutoff,
) -> tuple[Path, str]:
    """Persist canonical timing evidence once; conflicting rewrites fail closed."""

    output = Path(path)
    if output.is_symlink():
        raise ValueError("OKX live timing evidence path cannot be a symbolic link")
    evidence = build_okx_live_timing_evidence(sample=sample, cutoff=cutoff)
    payload = _canonical_json_bytes(evidence)
    digest = hashlib.sha256(payload).hexdigest()

    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        if not output.is_file():
            raise ValueError("OKX live timing evidence path must be a regular file")
        if output.read_bytes() != payload:
            raise FileExistsError("refusing to replace different OKX live timing evidence")
        return output, digest

    temporary = output.with_name(f".{output.name}.{digest}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, output)
        except FileExistsError:
            if output.is_symlink() or not output.is_file() or output.read_bytes() != payload:
                raise FileExistsError(
                    "refusing to replace different OKX live timing evidence"
                ) from None
    finally:
        temporary.unlink(missing_ok=True)

    return output, digest


def read_okx_live_timing_evidence(
    path: str | Path,
    *,
    expected_sha256: str,
) -> dict[str, Any]:
    """Read canonical timing evidence only when its exact SHA-256 matches."""

    digest = expected_sha256.strip().lower()
    if len(digest) != 64 or not set(digest) <= _HEX_DIGITS:
        raise ValueError("expected_sha256 must be a hexadecimal SHA-256 digest")

    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError("OKX live timing evidence path must be a regular file")
    payload = source.read_bytes()
    if hashlib.sha256(payload).hexdigest() != digest:
        raise ValueError("OKX live timing evidence hash mismatch")

    try:
        decoded = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("OKX live timing evidence is not valid UTF-8 JSON") from exc
    if not isinstance(decoded, dict):
        raise ValueError("OKX live timing evidence must be a JSON object")
    if _canonical_json_bytes(decoded) != payload:
        raise ValueError("OKX live timing evidence is not canonical JSON")
    if (
        decoded.get("schema_version") != _SCHEMA_VERSION
        or decoded.get("provider") != _PROVIDER
    ):
        raise ValueError("unsupported OKX live timing evidence schema")
    source_url = decoded.get("source_url")
    if not isinstance(source_url, str) or not source_url.endswith(_PUBLIC_TIME_ENDPOINT):
        raise ValueError("OKX live timing evidence source is not the public time endpoint")
    return decoded
