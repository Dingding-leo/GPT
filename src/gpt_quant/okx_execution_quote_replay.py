from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from math import isfinite

from .execution_quote import ExecutionQuoteSnapshot
from .okx import JSONGetter
from .okx_execution_quote import (
    Clock,
    OKXTopOfBookObservation,
    RawBytesGetter,
    fetch_okx_top_of_book,
)

_SCHEMA_VERSION = 1
_PAYLOAD_KEYS = {
    "schema_version",
    "server_time_request_started_utc",
    "timeout_seconds",
    "max_request_round_trip_seconds",
    "max_server_round_trip_seconds",
    "max_abs_midpoint_clock_skew_seconds",
    "observation",
}
_SERIALIZED_KEYS = _PAYLOAD_KEYS | {"evidence_id"}
_OBSERVATION_KEYS = {
    "base_url",
    "endpoint",
    "request_started_utc",
    "response_received_utc",
    "exchange_time_observed_utc",
    "server_time_response_received_utc",
    "request_round_trip_seconds",
    "server_round_trip_seconds",
    "midpoint_clock_skew_seconds",
    "maximum_quote_age_ms",
    "raw_response_json_utf8",
    "quote",
}


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


def _required_finite(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field_name} must be a finite number")
    try:
        parsed = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a finite number") from exc
    if not isfinite(parsed):
        raise ValueError(f"{field_name} must be a finite number")
    return 0.0 if parsed == 0 else parsed


def _required_positive(value: object, *, field_name: str) -> float:
    parsed = _required_finite(value, field_name=field_name)
    if parsed <= 0:
        raise ValueError(f"{field_name} must be positive")
    return parsed


def _required_nonnegative(value: object, *, field_name: str) -> float:
    parsed = _required_finite(value, field_name=field_name)
    if parsed < 0:
        raise ValueError(f"{field_name} cannot be negative")
    return parsed


def _format_utc(value: datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical_json_bytes(value: Mapping[str, object]) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"OKX quote replay JSON contains duplicate field {key!r}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"OKX quote replay JSON contains non-finite number {value!r}")


def _observation_payload(observation: OKXTopOfBookObservation) -> dict[str, object]:
    return {
        "base_url": observation.base_url,
        "endpoint": observation.endpoint,
        "request_started_utc": _format_utc(observation.request_started_utc),
        "response_received_utc": _format_utc(observation.response_received_utc),
        "exchange_time_observed_utc": _format_utc(observation.exchange_time_observed_utc),
        "server_time_response_received_utc": _format_utc(
            observation.server_time_response_received_utc
        ),
        "request_round_trip_seconds": (
            0.0
            if observation.request_round_trip_seconds == 0
            else observation.request_round_trip_seconds
        ),
        "server_round_trip_seconds": (
            0.0
            if observation.server_round_trip_seconds == 0
            else observation.server_round_trip_seconds
        ),
        "midpoint_clock_skew_seconds": (
            0.0
            if observation.midpoint_clock_skew_seconds == 0
            else observation.midpoint_clock_skew_seconds
        ),
        "maximum_quote_age_ms": observation.maximum_quote_age_ms,
        "raw_response_json_utf8": observation.raw_response_json.decode("utf-8"),
        "quote": observation.quote.to_dict(),
    }


@dataclass(frozen=True, slots=True)
class ReconstructableOKXTopOfBookEvidence:
    """Content-addressed replay of one bounded public OKX quote observation."""

    server_time_request_started_utc: datetime
    timeout_seconds: float
    max_request_round_trip_seconds: float
    max_server_round_trip_seconds: float
    max_abs_midpoint_clock_skew_seconds: float
    observation: OKXTopOfBookObservation
    schema_version: int = field(default=_SCHEMA_VERSION, init=False)
    evidence_id: str = field(init=False)

    def __post_init__(self) -> None:
        server_started = _required_utc(
            self.server_time_request_started_utc,
            field_name="server_time_request_started_utc",
        )
        object.__setattr__(self, "server_time_request_started_utc", server_started)
        object.__setattr__(
            self,
            "timeout_seconds",
            _required_positive(self.timeout_seconds, field_name="timeout_seconds"),
        )
        request_bound = _required_positive(
            self.max_request_round_trip_seconds,
            field_name="max_request_round_trip_seconds",
        )
        server_bound = _required_positive(
            self.max_server_round_trip_seconds,
            field_name="max_server_round_trip_seconds",
        )
        skew_bound = _required_nonnegative(
            self.max_abs_midpoint_clock_skew_seconds,
            field_name="max_abs_midpoint_clock_skew_seconds",
        )
        object.__setattr__(self, "max_request_round_trip_seconds", request_bound)
        object.__setattr__(self, "max_server_round_trip_seconds", server_bound)
        object.__setattr__(self, "max_abs_midpoint_clock_skew_seconds", skew_bound)

        if not isinstance(self.observation, OKXTopOfBookObservation):
            raise TypeError("observation must be an OKXTopOfBookObservation")
        if server_started < self.observation.response_received_utc:
            raise ValueError("OKX server-time request predates books response receipt")
        server_received = self.observation.server_time_response_received_utc
        if server_received < server_started:
            raise ValueError("local clock moved backward during OKX server-time request")

        expected_server_round_trip = (server_received - server_started).total_seconds()
        if abs(self.observation.server_round_trip_seconds - expected_server_round_trip) > 1e-9:
            raise ValueError("OKX server-time round trip does not match replay timestamps")
        midpoint = server_started + (server_received - server_started) / 2
        expected_skew = (self.observation.exchange_time_observed_utc - midpoint).total_seconds()
        if abs(self.observation.midpoint_clock_skew_seconds - expected_skew) > 1e-9:
            raise ValueError("OKX midpoint clock skew does not match replay timestamps")
        if self.observation.request_round_trip_seconds > request_bound:
            raise ValueError("OKX books request round trip exceeds replay policy")
        if self.observation.server_round_trip_seconds > server_bound:
            raise ValueError("OKX server-time round trip exceeds replay policy")
        if abs(self.observation.midpoint_clock_skew_seconds) > skew_bound:
            raise ValueError("OKX midpoint clock skew exceeds replay policy")

        object.__setattr__(
            self,
            "evidence_id",
            hashlib.sha256(_canonical_json_bytes(self._payload())).hexdigest(),
        )

    def _payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "server_time_request_started_utc": _format_utc(
                self.server_time_request_started_utc
            ),
            "timeout_seconds": self.timeout_seconds,
            "max_request_round_trip_seconds": self.max_request_round_trip_seconds,
            "max_server_round_trip_seconds": self.max_server_round_trip_seconds,
            "max_abs_midpoint_clock_skew_seconds": self.max_abs_midpoint_clock_skew_seconds,
            "observation": _observation_payload(self.observation),
        }

    def to_json_bytes(self) -> bytes:
        return _canonical_json_bytes({**self._payload(), "evidence_id": self.evidence_id}) + b"\n"

    @classmethod
    def from_json_bytes(cls, value: bytes) -> ReconstructableOKXTopOfBookEvidence:
        try:
            text = value.decode("utf-8")
            payload = json.loads(
                text,
                object_pairs_hook=_reject_duplicates,
                parse_constant=_reject_nonfinite,
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("OKX quote replay JSON is unreadable") from exc
        if not isinstance(payload, Mapping) or set(payload) != _SERIALIZED_KEYS:
            raise ValueError("OKX quote replay fields do not match schema")
        if payload["schema_version"] != _SCHEMA_VERSION:
            raise ValueError("unsupported OKX quote replay schema")
        raw_observation = payload["observation"]
        if not isinstance(raw_observation, Mapping) or set(raw_observation) != _OBSERVATION_KEYS:
            raise ValueError("OKX quote replay observation fields do not match schema")
        raw_response = raw_observation["raw_response_json_utf8"]
        if not isinstance(raw_response, str):
            raise ValueError("OKX quote replay raw response must be UTF-8 text")
        quote = ExecutionQuoteSnapshot.from_mapping(raw_observation["quote"])
        observation = OKXTopOfBookObservation(
            base_url=raw_observation["base_url"],
            endpoint=raw_observation["endpoint"],
            request_started_utc=_required_utc(
                raw_observation["request_started_utc"],
                field_name="request_started_utc",
            ),
            response_received_utc=_required_utc(
                raw_observation["response_received_utc"],
                field_name="response_received_utc",
            ),
            exchange_time_observed_utc=_required_utc(
                raw_observation["exchange_time_observed_utc"],
                field_name="exchange_time_observed_utc",
            ),
            server_time_response_received_utc=_required_utc(
                raw_observation["server_time_response_received_utc"],
                field_name="server_time_response_received_utc",
            ),
            request_round_trip_seconds=raw_observation["request_round_trip_seconds"],
            server_round_trip_seconds=raw_observation["server_round_trip_seconds"],
            midpoint_clock_skew_seconds=raw_observation["midpoint_clock_skew_seconds"],
            maximum_quote_age_ms=raw_observation["maximum_quote_age_ms"],
            raw_response_json=raw_response.encode("utf-8"),
            quote=quote,
        )
        evidence = cls(
            server_time_request_started_utc=_required_utc(
                payload["server_time_request_started_utc"],
                field_name="server_time_request_started_utc",
            ),
            timeout_seconds=payload["timeout_seconds"],
            max_request_round_trip_seconds=payload["max_request_round_trip_seconds"],
            max_server_round_trip_seconds=payload["max_server_round_trip_seconds"],
            max_abs_midpoint_clock_skew_seconds=payload[
                "max_abs_midpoint_clock_skew_seconds"
            ],
            observation=observation,
        )
        if payload["evidence_id"] != evidence.evidence_id:
            raise ValueError("OKX quote replay ID does not match its canonical payload")
        if evidence.to_json_bytes() != value:
            raise ValueError("OKX quote replay JSON must use canonical encoding")
        return evidence


def _current_utc() -> datetime:
    return datetime.now(UTC)


def fetch_reconstructable_okx_top_of_book(
    *,
    instrument_id: str,
    instrument_snapshot_sha256: str,
    base_url: str = "https://www.okx.com",
    timeout: float = 20.0,
    maximum_quote_age_ms: int = 1_000,
    max_request_round_trip_seconds: float = 2.0,
    max_server_round_trip_seconds: float = 2.0,
    max_abs_midpoint_clock_skew_seconds: float = 5.0,
    get_bytes: RawBytesGetter | None = None,
    get_json: JSONGetter | None = None,
    now: Clock | None = None,
) -> ReconstructableOKXTopOfBookEvidence:
    """Fetch public market evidence and retain the complete replay timing envelope."""

    clock = now or _current_utc
    clock_samples: list[datetime] = []

    def recording_clock() -> datetime:
        value = clock()
        clock_samples.append(value)
        return value

    observation = fetch_okx_top_of_book(
        instrument_id=instrument_id,
        instrument_snapshot_sha256=instrument_snapshot_sha256,
        base_url=base_url,
        timeout=timeout,
        maximum_quote_age_ms=maximum_quote_age_ms,
        max_request_round_trip_seconds=max_request_round_trip_seconds,
        max_server_round_trip_seconds=max_server_round_trip_seconds,
        max_abs_midpoint_clock_skew_seconds=max_abs_midpoint_clock_skew_seconds,
        get_bytes=get_bytes,
        get_json=get_json,
        now=recording_clock,
    )
    if len(clock_samples) != 4:
        raise RuntimeError("OKX top-of-book replay requires exactly four local clock samples")
    normalized_samples = tuple(
        _required_utc(value, field_name=f"clock_samples[{index}]")
        for index, value in enumerate(clock_samples)
    )
    if normalized_samples[0] != observation.request_started_utc:
        raise RuntimeError("OKX books request start was not preserved")
    if normalized_samples[1] != observation.response_received_utc:
        raise RuntimeError("OKX books response receipt was not preserved")
    if normalized_samples[3] != observation.server_time_response_received_utc:
        raise RuntimeError("OKX server-time response receipt was not preserved")

    return ReconstructableOKXTopOfBookEvidence(
        server_time_request_started_utc=normalized_samples[2],
        timeout_seconds=timeout,
        max_request_round_trip_seconds=max_request_round_trip_seconds,
        max_server_round_trip_seconds=max_server_round_trip_seconds,
        max_abs_midpoint_clock_skew_seconds=max_abs_midpoint_clock_skew_seconds,
        observation=observation,
    )
