from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from math import isfinite

from .execution_quote import ExecutionQuoteSnapshot
from .okx_execution_quote import OKXTopOfBookObservation

_SCHEMA_VERSION = 1
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_DECIMAL_PATTERN = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")
_PAYLOAD_KEYS = {
    "schema_version",
    "base_url",
    "endpoint",
    "request_started_utc",
    "response_received_utc",
    "server_time_endpoint",
    "server_time_request_started_utc",
    "exchange_time_observed_utc",
    "server_time_response_received_utc",
    "request_round_trip_seconds",
    "server_round_trip_seconds",
    "midpoint_clock_skew_seconds",
    "max_request_round_trip_seconds",
    "max_server_round_trip_seconds",
    "max_abs_midpoint_clock_skew_seconds",
    "maximum_quote_age_ms",
    "raw_response_json_utf8",
    "raw_server_time_response_json_utf8",
    "quote",
}
_SERIALIZED_KEYS = _PAYLOAD_KEYS | {"evidence_id"}


def _required_utc(value: object, *, field_name: str) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field_name} must be a timezone-aware timestamp") from exc
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise ValueError(f"{field_name} must be a timezone-aware timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be a timezone-aware timestamp")
    return parsed.astimezone(UTC)


def _format_utc(value: datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical_finite_decimal(value: object, *, field_name: str) -> str:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise ValueError(f"{field_name} must be a canonical finite decimal")
    if isinstance(value, str) and _DECIMAL_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a canonical finite decimal")
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field_name} must be a canonical finite decimal") from exc
    if not decimal_value.is_finite():
        raise ValueError(f"{field_name} must be a canonical finite decimal")
    canonical = format(decimal_value, "f")
    if "." in canonical:
        canonical = canonical.rstrip("0").rstrip(".")
    if canonical == "-0":
        canonical = "0"
    if isinstance(value, str) and value != canonical:
        raise ValueError(f"{field_name} must use canonical decimal encoding")
    return canonical


def _decimal_float(value: object, *, field_name: str) -> float:
    canonical = _canonical_finite_decimal(value, field_name=field_name)
    number = float(canonical)
    if not isfinite(number):
        raise ValueError(f"{field_name} is outside the supported float range")
    return number


def _canonical_json_bytes(payload: Mapping[str, object]) -> bytes:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _reject_duplicate_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"OKX quote replay JSON contains duplicate field {key!r}")
        result[key] = value
    return result


def _reject_nonfinite_number(value: str) -> None:
    raise ValueError(f"OKX quote replay JSON contains non-finite number {value!r}")


@dataclass(frozen=True, slots=True)
class ReconstructableOKXTopOfBookEvidence:
    """Canonical replay record for one complete bounded public OKX quote observation."""

    observation: OKXTopOfBookObservation
    schema_version: int = field(default=_SCHEMA_VERSION, init=False)
    evidence_id: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.observation, OKXTopOfBookObservation):
            raise TypeError("observation must be an OKXTopOfBookObservation")
        object.__setattr__(
            self,
            "evidence_id",
            hashlib.sha256(_canonical_json_bytes(self._payload())).hexdigest(),
        )

    def _payload(self) -> dict[str, object]:
        observation = self.observation
        return {
            "schema_version": self.schema_version,
            "base_url": observation.base_url,
            "endpoint": observation.endpoint,
            "request_started_utc": _format_utc(observation.request_started_utc),
            "response_received_utc": _format_utc(observation.response_received_utc),
            "server_time_endpoint": observation.server_time_endpoint,
            "server_time_request_started_utc": _format_utc(
                observation.server_time_request_started_utc
            ),
            "exchange_time_observed_utc": _format_utc(observation.exchange_time_observed_utc),
            "server_time_response_received_utc": _format_utc(
                observation.server_time_response_received_utc
            ),
            "request_round_trip_seconds": _canonical_finite_decimal(
                observation.request_round_trip_seconds,
                field_name="request_round_trip_seconds",
            ),
            "server_round_trip_seconds": _canonical_finite_decimal(
                observation.server_round_trip_seconds,
                field_name="server_round_trip_seconds",
            ),
            "midpoint_clock_skew_seconds": _canonical_finite_decimal(
                observation.midpoint_clock_skew_seconds,
                field_name="midpoint_clock_skew_seconds",
            ),
            "max_request_round_trip_seconds": _canonical_finite_decimal(
                observation.max_request_round_trip_seconds,
                field_name="max_request_round_trip_seconds",
            ),
            "max_server_round_trip_seconds": _canonical_finite_decimal(
                observation.max_server_round_trip_seconds,
                field_name="max_server_round_trip_seconds",
            ),
            "max_abs_midpoint_clock_skew_seconds": _canonical_finite_decimal(
                observation.max_abs_midpoint_clock_skew_seconds,
                field_name="max_abs_midpoint_clock_skew_seconds",
            ),
            "maximum_quote_age_ms": observation.maximum_quote_age_ms,
            "raw_response_json_utf8": observation.raw_response_json.decode("utf-8"),
            "raw_server_time_response_json_utf8": (
                observation.raw_server_time_response_json.decode("utf-8")
            ),
            "quote": observation.quote.to_dict(),
        }

    def to_json_bytes(self) -> bytes:
        return _canonical_json_bytes({**self._payload(), "evidence_id": self.evidence_id}) + b"\n"

    @classmethod
    def from_json_bytes(cls, value: bytes) -> ReconstructableOKXTopOfBookEvidence:
        try:
            serialized = value.decode("utf-8")
            payload = json.loads(
                serialized,
                object_pairs_hook=_reject_duplicate_fields,
                parse_constant=_reject_nonfinite_number,
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("OKX quote replay JSON is unreadable") from exc
        if not isinstance(payload, Mapping) or set(payload) != _SERIALIZED_KEYS:
            raise ValueError("OKX quote replay fields do not match schema")
        if payload["schema_version"] != _SCHEMA_VERSION:
            raise ValueError("unsupported OKX quote replay schema")
        raw_response = payload["raw_response_json_utf8"]
        if not isinstance(raw_response, str):
            raise ValueError("raw_response_json_utf8 must be UTF-8 text")
        raw_server_time_response = payload["raw_server_time_response_json_utf8"]
        if not isinstance(raw_server_time_response, str):
            raise ValueError("raw_server_time_response_json_utf8 must be UTF-8 text")

        observation = OKXTopOfBookObservation(
            base_url=payload["base_url"],
            endpoint=payload["endpoint"],
            request_started_utc=_required_utc(
                payload["request_started_utc"], field_name="request_started_utc"
            ),
            response_received_utc=_required_utc(
                payload["response_received_utc"], field_name="response_received_utc"
            ),
            server_time_endpoint=payload["server_time_endpoint"],
            server_time_request_started_utc=_required_utc(
                payload["server_time_request_started_utc"],
                field_name="server_time_request_started_utc",
            ),
            exchange_time_observed_utc=_required_utc(
                payload["exchange_time_observed_utc"],
                field_name="exchange_time_observed_utc",
            ),
            server_time_response_received_utc=_required_utc(
                payload["server_time_response_received_utc"],
                field_name="server_time_response_received_utc",
            ),
            request_round_trip_seconds=_decimal_float(
                payload["request_round_trip_seconds"],
                field_name="request_round_trip_seconds",
            ),
            server_round_trip_seconds=_decimal_float(
                payload["server_round_trip_seconds"],
                field_name="server_round_trip_seconds",
            ),
            midpoint_clock_skew_seconds=_decimal_float(
                payload["midpoint_clock_skew_seconds"],
                field_name="midpoint_clock_skew_seconds",
            ),
            max_request_round_trip_seconds=_decimal_float(
                payload["max_request_round_trip_seconds"],
                field_name="max_request_round_trip_seconds",
            ),
            max_server_round_trip_seconds=_decimal_float(
                payload["max_server_round_trip_seconds"],
                field_name="max_server_round_trip_seconds",
            ),
            max_abs_midpoint_clock_skew_seconds=_decimal_float(
                payload["max_abs_midpoint_clock_skew_seconds"],
                field_name="max_abs_midpoint_clock_skew_seconds",
            ),
            maximum_quote_age_ms=payload["maximum_quote_age_ms"],
            raw_response_json=raw_response.encode("utf-8"),
            raw_server_time_response_json=raw_server_time_response.encode("utf-8"),
            quote=ExecutionQuoteSnapshot.from_mapping(payload["quote"]),
        )
        evidence = cls(observation=observation)
        serialized_id = payload["evidence_id"]
        if not isinstance(serialized_id, str) or _SHA256_PATTERN.fullmatch(serialized_id) is None:
            raise ValueError("evidence_id must be a lowercase SHA-256 digest")
        if serialized_id != evidence.evidence_id:
            raise ValueError("OKX quote replay ID does not match its canonical payload")
        if evidence.to_json_bytes() != value:
            raise ValueError("OKX quote replay JSON must use canonical encoding")
        return evidence
