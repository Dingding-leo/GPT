from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .okx import JSONGetter, _default_json_getter
from .okx_live import (
    Clock,
    OKXCompletedBarCutoff,
    OKXServerTimeSample,
    sample_okx_server_time,
)
from .okx_live_evidence import build_okx_live_timing_evidence

_SCHEMA_VERSION = 2
_PROVIDER = "OKX"
_PUBLIC_TIME_ENDPOINT = "/api/v5/public/time"
_RESPONSE_ENCODING = "canonical-json-v1"
_HEX_DIGITS = frozenset("0123456789abcdef")


@dataclass(frozen=True, slots=True)
class OKXServerTimeResponseObservation:
    """One validated server-time sample bound to its canonical public response."""

    sample: OKXServerTimeSample
    response_json: bytes

    @property
    def response_sha256(self) -> str:
        return hashlib.sha256(self.response_json).hexdigest()


def _canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _reject_duplicate_object_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    decoded: dict[str, Any] = {}
    for key, value in pairs:
        if key in decoded:
            raise ValueError(f"OKX public-time response contains duplicate field {key!r}")
        decoded[key] = value
    return decoded


def _decode_canonical_response(response_json: bytes) -> dict[str, Any]:
    if not isinstance(response_json, bytes) or not response_json:
        raise ValueError("OKX public-time response must be non-empty bytes")
    try:
        decoded = json.loads(
            response_json,
            object_pairs_hook=_reject_duplicate_object_fields,
        )
    except UnicodeDecodeError as exc:
        raise ValueError("OKX public-time response must be valid UTF-8 JSON") from exc
    except json.JSONDecodeError as exc:
        raise ValueError("OKX public-time response must be valid UTF-8 JSON") from exc
    if not isinstance(decoded, dict):
        raise ValueError("OKX public-time response must be a JSON object")
    if _canonical_json_bytes(decoded) != response_json:
        raise ValueError("OKX public-time response must use canonical JSON encoding")
    if decoded.get("code") != "0" or not isinstance(decoded.get("msg"), str):
        raise ValueError("OKX public-time response must be a successful API response")
    data = decoded.get("data")
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
        raise ValueError("OKX public-time response must contain exactly one object")
    timestamp_text = data[0].get("ts")
    if (
        not isinstance(timestamp_text, str)
        or not timestamp_text.isascii()
        or not timestamp_text.isdecimal()
    ):
        raise ValueError("OKX public-time response ts must be Unix milliseconds")
    return decoded


def _response_server_time(response: Mapping[str, Any]) -> pd.Timestamp:
    timestamp_text = response["data"][0]["ts"]
    try:
        return pd.to_datetime(int(timestamp_text), unit="ms", utc=True)
    except (OverflowError, ValueError) as exc:
        raise ValueError("OKX public-time response ts is outside the supported range") from exc


def _validated_observation(
    observation: OKXServerTimeResponseObservation,
) -> tuple[dict[str, Any], pd.Timestamp]:
    response = _decode_canonical_response(observation.response_json)
    response_server_time = _response_server_time(response)
    sample_server_time = pd.Timestamp(observation.sample.server_time_utc)
    if sample_server_time.tzinfo is None:
        raise ValueError("OKX server-time sample must be timezone-aware")
    sample_server_time = sample_server_time.tz_convert("UTC")
    if response_server_time != sample_server_time:
        raise ValueError("OKX public-time response does not match the validated server-time sample")
    return response, response_server_time


def sample_okx_server_time_with_response(
    *,
    base_url: str = "https://www.okx.com",
    timeout: float = 20.0,
    max_round_trip_seconds: float = 2.0,
    max_abs_clock_skew_seconds: float = 5.0,
    get_json: JSONGetter | None = None,
    now: Clock | None = None,
) -> OKXServerTimeResponseObservation:
    """Sample public OKX time and retain the exact canonical provider response."""

    getter = get_json or _default_json_getter
    response_json: bytes | None = None

    def capture_response(url: str, request_timeout: float) -> Mapping[str, Any]:
        nonlocal response_json
        if response_json is not None:
            raise RuntimeError("OKX public-time getter was invoked more than once")
        payload = dict(getter(url, request_timeout))
        response_json = _canonical_json_bytes(payload)
        return payload

    sample = sample_okx_server_time(
        base_url=base_url,
        timeout=timeout,
        max_round_trip_seconds=max_round_trip_seconds,
        max_abs_clock_skew_seconds=max_abs_clock_skew_seconds,
        get_json=capture_response,
        now=now,
    )
    if response_json is None:
        raise RuntimeError("OKX public-time getter returned no response evidence")
    observation = OKXServerTimeResponseObservation(
        sample=sample,
        response_json=response_json,
    )
    _validated_observation(observation)
    return observation


def build_okx_live_timing_response_evidence(
    *,
    observation: OKXServerTimeResponseObservation,
    cutoff: OKXCompletedBarCutoff,
) -> dict[str, Any]:
    """Build timing evidence that can reconstruct the accepted exchange timestamp."""

    response, response_server_time = _validated_observation(observation)
    evidence = build_okx_live_timing_evidence(
        sample=observation.sample,
        cutoff=cutoff,
    )
    recorded_server_time = pd.Timestamp(evidence["exchange_server_time_utc"])
    if recorded_server_time != response_server_time:
        raise ValueError("completed-bar cutoff is not bound to the public-time response")

    evidence["schema_version"] = _SCHEMA_VERSION
    evidence["server_time_response_encoding"] = _RESPONSE_ENCODING
    evidence["server_time_response"] = response
    evidence["server_time_response_sha256"] = observation.response_sha256
    return evidence


def _evidence_payload(
    *,
    observation: OKXServerTimeResponseObservation,
    cutoff: OKXCompletedBarCutoff,
) -> bytes:
    return _canonical_json_bytes(
        build_okx_live_timing_response_evidence(
            observation=observation,
            cutoff=cutoff,
        )
    )


def write_okx_live_timing_response_evidence(
    path: str | Path,
    *,
    observation: OKXServerTimeResponseObservation,
    cutoff: OKXCompletedBarCutoff,
) -> tuple[Path, str]:
    """Persist response-bound timing evidence once; conflicting rewrites fail closed."""

    output = Path(path)
    if output.is_symlink():
        raise ValueError("OKX live timing evidence path cannot be a symbolic link")
    payload = _evidence_payload(observation=observation, cutoff=cutoff)
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


def read_okx_live_timing_response_evidence(
    path: str | Path,
    *,
    expected_sha256: str,
) -> dict[str, Any]:
    """Read canonical response-bound timing evidence after all hashes revalidate."""

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
        decoded = json.loads(
            payload,
            object_pairs_hook=_reject_duplicate_object_fields,
        )
    except UnicodeDecodeError as exc:
        raise ValueError("OKX live timing evidence is not valid UTF-8 JSON") from exc
    except json.JSONDecodeError as exc:
        raise ValueError("OKX live timing evidence is not valid UTF-8 JSON") from exc
    if not isinstance(decoded, dict) or _canonical_json_bytes(decoded) != payload:
        raise ValueError("OKX live timing evidence is not canonical JSON")
    if decoded.get("schema_version") != _SCHEMA_VERSION or decoded.get("provider") != _PROVIDER:
        raise ValueError("unsupported OKX live timing evidence schema")
    if decoded.get("server_time_response_encoding") != _RESPONSE_ENCODING:
        raise ValueError("unsupported OKX public-time response encoding")

    response = decoded.get("server_time_response")
    if not isinstance(response, dict):
        raise ValueError("OKX live timing evidence is missing the public-time response")
    response_json = _canonical_json_bytes(response)
    response_digest = decoded.get("server_time_response_sha256")
    if (
        not isinstance(response_digest, str)
        or hashlib.sha256(response_json).hexdigest() != response_digest
    ):
        raise ValueError("OKX public-time response hash mismatch")
    validated_response = _decode_canonical_response(response_json)
    response_server_time = _response_server_time(validated_response)
    recorded_server_time = pd.Timestamp(decoded.get("exchange_server_time_utc"))
    if recorded_server_time.tzinfo is None:
        raise ValueError("exchange_server_time_utc must be timezone-aware")
    if recorded_server_time.tz_convert("UTC") != response_server_time:
        raise ValueError("persisted exchange time does not match the public-time response")
    source_url = decoded.get("source_url")
    if not isinstance(source_url, str) or not source_url.endswith(_PUBLIC_TIME_ENDPOINT):
        raise ValueError("OKX live timing evidence source is not the public time endpoint")
    return decoded
