from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from math import isfinite
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .okx_live import OKXServerTimeSample, _validated_server_time_sample

RawBytesGetter = Callable[[str, float], bytes]
Clock = Callable[[], datetime]
_ENDPOINT = "/api/v5/public/instruments"
_MAX_RESPONSE_BYTES = 1_000_000
_SCHEMA_VERSION = 2
_SUPPORTED_UPCOMING_FIELDS = frozenset({"tickSz", "minSz", "maxMktSz"})


@dataclass(frozen=True, slots=True)
class OKXUpcomingInstrumentChange:
    parameter: str
    new_value: str
    effective_at_utc: datetime

    def as_dict(self) -> dict[str, str]:
        return {
            "parameter": self.parameter,
            "new_value": self.new_value,
            "effective_at_utc": _format_utc(self.effective_at_utc),
        }


@dataclass(frozen=True, slots=True)
class _ParsedSpotInstrument:
    instrument_id: str
    base_currency: str
    quote_currency: str
    state: str
    tick_size: str
    lot_size: str
    minimum_order_size_base: str
    listed_at_utc: datetime | None
    continuous_trading_started_at_utc: datetime | None
    expires_at_utc: datetime | None
    valid_until_utc: datetime | None
    upcoming_changes: tuple[OKXUpcomingInstrumentChange, ...]


@dataclass(frozen=True, slots=True)
class OKXSpotInstrumentSnapshot:
    """Immutable public OKX spot-instrument constraints observed at one request."""

    base_url: str
    request_started_utc: datetime
    response_received_utc: datetime
    server_time_request_started_utc: datetime
    exchange_observed_at_utc: datetime
    server_time_response_received_utc: datetime
    server_round_trip_seconds: float
    midpoint_clock_skew_seconds: float
    max_server_round_trip_seconds: float
    max_abs_midpoint_clock_skew_seconds: float
    instrument_id: str
    base_currency: str
    quote_currency: str
    state: str
    tick_size: str
    lot_size: str
    minimum_order_size_base: str
    listed_at_utc: datetime | None
    continuous_trading_started_at_utc: datetime | None
    expires_at_utc: datetime | None
    valid_until_utc: datetime | None
    upcoming_changes: tuple[OKXUpcomingInstrumentChange, ...]
    raw_response_json: bytes

    def __post_init__(self) -> None:
        raw_response = _required_raw_response(self.raw_response_json)
        object.__setattr__(self, "raw_response_json", raw_response)

        request_started = _required_utc_datetime(
            self.request_started_utc,
            field="request_started_utc",
        )
        response_received = _required_utc_datetime(
            self.response_received_utc,
            field="response_received_utc",
        )
        server_request_started = _required_utc_datetime(
            self.server_time_request_started_utc,
            field="server_time_request_started_utc",
        )
        observed_at = _required_utc_datetime(
            self.exchange_observed_at_utc,
            field="exchange_observed_at_utc",
        )
        server_response_received = _required_utc_datetime(
            self.server_time_response_received_utc,
            field="server_time_response_received_utc",
        )
        for field_name, value in (
            ("request_started_utc", request_started),
            ("response_received_utc", response_received),
            ("server_time_request_started_utc", server_request_started),
            ("exchange_observed_at_utc", observed_at),
            ("server_time_response_received_utc", server_response_received),
        ):
            object.__setattr__(self, field_name, value)

        if response_received < request_started:
            raise ValueError("local clock moved backward during OKX instrument request")
        if server_request_started < response_received:
            raise ValueError("OKX server time must be sampled after the instrument response")

        max_round_trip = _required_finite_number(
            self.max_server_round_trip_seconds,
            field="max_server_round_trip_seconds",
        )
        if max_round_trip <= 0:
            raise ValueError("max_server_round_trip_seconds must be positive")
        max_clock_skew = _required_finite_number(
            self.max_abs_midpoint_clock_skew_seconds,
            field="max_abs_midpoint_clock_skew_seconds",
        )
        if max_clock_skew < 0:
            raise ValueError("max_abs_midpoint_clock_skew_seconds cannot be negative")
        object.__setattr__(self, "max_server_round_trip_seconds", max_round_trip)
        object.__setattr__(self, "max_abs_midpoint_clock_skew_seconds", max_clock_skew)

        sample = OKXServerTimeSample(
            base_url=self.base_url,
            endpoint="/api/v5/public/time",
            local_request_started_utc=server_request_started,
            local_response_received_utc=server_response_received,
            server_time_utc=observed_at,
            round_trip_seconds=self.server_round_trip_seconds,
            midpoint_clock_skew_seconds=self.midpoint_clock_skew_seconds,
        )
        (
            validated_server_started,
            validated_server_received,
            validated_observed_at,
            validated_round_trip,
            validated_clock_skew,
        ) = _validated_server_time_sample(
            sample,
            max_round_trip_seconds=max_round_trip,
            max_abs_clock_skew_seconds=max_clock_skew,
        )
        object.__setattr__(
            self,
            "server_time_request_started_utc",
            validated_server_started,
        )
        object.__setattr__(
            self,
            "server_time_response_received_utc",
            validated_server_received,
        )
        object.__setattr__(
            self,
            "exchange_observed_at_utc",
            validated_observed_at,
        )
        object.__setattr__(self, "server_round_trip_seconds", validated_round_trip)
        object.__setattr__(self, "midpoint_clock_skew_seconds", validated_clock_skew)
        observed_at = validated_observed_at

        replayed = _parse_spot_instrument_response(
            raw_response,
            inst_id=self.instrument_id,
            observed_at=observed_at,
        )
        for field_name in (
            "instrument_id",
            "base_currency",
            "quote_currency",
            "state",
            "tick_size",
            "lot_size",
            "minimum_order_size_base",
            "listed_at_utc",
            "continuous_trading_started_at_utc",
            "expires_at_utc",
            "valid_until_utc",
            "upcoming_changes",
        ):
            if getattr(self, field_name) != getattr(replayed, field_name):
                raise ValueError(f"{field_name} does not match the exact OKX instrument response")

    @property
    def tick_size_decimal(self) -> Decimal:
        return Decimal(self.tick_size)

    @property
    def lot_size_decimal(self) -> Decimal:
        return Decimal(self.lot_size)

    @property
    def minimum_order_size_base_decimal(self) -> Decimal:
        return Decimal(self.minimum_order_size_base)

    @property
    def raw_response_sha256(self) -> str:
        return hashlib.sha256(self.raw_response_json).hexdigest()

    def metadata_bytes(self) -> bytes:
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "provider": "OKX",
            "endpoint": _ENDPOINT,
            "base_url": self.base_url,
            "request_started_utc": _format_utc(self.request_started_utc),
            "response_received_utc": _format_utc(self.response_received_utc),
            "server_time_request_started_utc": _format_utc(self.server_time_request_started_utc),
            "exchange_observed_at_utc": _format_utc(self.exchange_observed_at_utc),
            "server_time_response_received_utc": _format_utc(
                self.server_time_response_received_utc
            ),
            "server_round_trip_seconds": self.server_round_trip_seconds,
            "midpoint_clock_skew_seconds": self.midpoint_clock_skew_seconds,
            "max_server_round_trip_seconds": self.max_server_round_trip_seconds,
            "max_abs_midpoint_clock_skew_seconds": (self.max_abs_midpoint_clock_skew_seconds),
            "instrument_id": self.instrument_id,
            "instrument_type": "SPOT",
            "base_currency": self.base_currency,
            "quote_currency": self.quote_currency,
            "state": self.state,
            "tick_size": self.tick_size,
            "lot_size": self.lot_size,
            "minimum_order_size_base": self.minimum_order_size_base,
            "listed_at_utc": _format_optional_utc(self.listed_at_utc),
            "continuous_trading_started_at_utc": _format_optional_utc(
                self.continuous_trading_started_at_utc
            ),
            "expires_at_utc": _format_optional_utc(self.expires_at_utc),
            "valid_until_utc": _format_optional_utc(self.valid_until_utc),
            "upcoming_changes": [change.as_dict() for change in self.upcoming_changes],
            "raw_response_sha256": self.raw_response_sha256,
            "limitations": [
                "This public endpoint reports minimum base-asset quantity, "
                "not minimum quote notional.",
                "A current executable quote is required before deriving minimum "
                "notional or spread.",
                "The public instrument response is accepted only with a bounded "
                "public OKX server-time observation sampled after receipt.",
                "This snapshot does not model spread, slippage, market impact, "
                "execution latency, fills or rejections.",
            ],
        }
        return _canonical_json_bytes(payload)

    @property
    def metadata_sha256(self) -> str:
        return hashlib.sha256(self.metadata_bytes()).hexdigest()


def _default_raw_bytes_getter(url: str, timeout: float) -> bytes:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "gpt-quant-lab/0.2 (+https://github.com/Dingding-leo/GPT)",
        },
    )
    with urlopen(request, timeout=timeout) as response:  # noqa: S310
        payload = response.read(_MAX_RESPONSE_BYTES + 1)
    if len(payload) > _MAX_RESPONSE_BYTES:
        raise RuntimeError("OKX instrument response exceeds the configured safety limit")
    return payload


def _required_raw_response(value: object) -> bytes:
    if not isinstance(value, bytes) or not value or len(value) > _MAX_RESPONSE_BYTES:
        raise ValueError("OKX instrument response must be non-empty bounded bytes")
    try:
        value.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("OKX instrument response must be UTF-8 JSON") from exc
    return value


def _reject_duplicate_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"OKX instrument JSON contains duplicate field {key!r}")
        result[key] = value
    return result


def _parse_json_response(value: bytes) -> Mapping[str, object]:
    try:
        payload = json.loads(value.decode("utf-8"), object_pairs_hook=_reject_duplicate_fields)
    except json.JSONDecodeError as exc:
        raise ValueError("OKX instrument response is not valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("OKX instrument response must be a JSON object")
    return payload


def _current_utc_datetime() -> datetime:
    return datetime.now(UTC)


def _required_utc_datetime(value: datetime, *, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be a timezone-aware datetime")
    return value.astimezone(UTC)


def _required_finite_number(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field} must be a finite number")
    number = float(value)
    if not isfinite(number):
        raise ValueError(f"{field} must be a finite number")
    return number


def _format_utc(value: datetime) -> str:
    return _required_utc_datetime(value, field="timestamp").isoformat().replace("+00:00", "Z")


def _format_optional_utc(value: datetime | None) -> str | None:
    return None if value is None else _format_utc(value)


def _canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _required_nonempty_string(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field} must be a non-empty string without surrounding whitespace")
    return value


def _positive_decimal_string(value: Any, *, field: str) -> str:
    text = _required_nonempty_string(value, field=field)
    parts = text.split(".")
    if len(parts) > 2 or any(
        not part or not part.isascii() or not part.isdecimal() for part in parts
    ):
        raise ValueError(f"{field} must be a plain positive decimal string")
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"{field} must be a plain positive decimal string") from exc
    if not number.is_finite() or number <= 0:
        raise ValueError(f"{field} must be a plain positive decimal string")
    return text


def _optional_unix_milliseconds(value: Any, *, field: str) -> datetime | None:
    if value == "" or value is None:
        return None
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
        raise ValueError(f"{field} must be an empty string or Unix milliseconds")
    milliseconds = int(value)
    try:
        return datetime.fromtimestamp(milliseconds / 1_000, tz=UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise ValueError(f"{field} is outside the supported timestamp range") from exc


def _parse_upcoming_changes(
    value: Any,
    *,
    observed_at: datetime,
) -> tuple[tuple[OKXUpcomingInstrumentChange, ...], datetime | None]:
    if value is None:
        return (), None
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise ValueError("OKX upcChg must be a list")

    normalized: list[OKXUpcomingInstrumentChange] = []
    valid_until: datetime | None = None
    for index, item in enumerate(value, start=1):
        if not isinstance(item, Mapping):
            raise ValueError(f"OKX upcChg item {index} must be an object")
        parameter = _required_nonempty_string(item.get("param"), field="upcChg param")
        if parameter not in _SUPPORTED_UPCOMING_FIELDS:
            raise ValueError(f"unsupported OKX upcoming instrument change {parameter!r}")
        effective_at = _optional_unix_milliseconds(item.get("effTime"), field="upcChg effTime")
        if effective_at is None:
            raise ValueError("OKX upcChg effTime is required")
        if effective_at <= observed_at:
            raise ValueError("OKX instrument metadata contains an already-effective pending change")
        new_value = _positive_decimal_string(item.get("newValue"), field="upcChg newValue")
        normalized.append(
            OKXUpcomingInstrumentChange(
                parameter=parameter,
                new_value=new_value,
                effective_at_utc=effective_at,
            )
        )
        valid_until = effective_at if valid_until is None else min(valid_until, effective_at)

    normalized.sort(key=lambda change: (change.effective_at_utc, change.parameter))
    return tuple(normalized), valid_until


def _validate_instrument_id(inst_id: str) -> tuple[str, str]:
    if not isinstance(inst_id, str) or inst_id != inst_id.strip() or inst_id.upper() != inst_id:
        raise ValueError("inst_id must be an uppercase OKX spot instrument identifier")
    parts = inst_id.split("-")
    if len(parts) != 2 or any(not part or not part.isalnum() for part in parts):
        raise ValueError("inst_id must have BASE-QUOTE spot format")
    return parts[0], parts[1]


def _parse_spot_instrument_response(
    raw_response: bytes,
    *,
    inst_id: str,
    observed_at: datetime,
) -> _ParsedSpotInstrument:
    expected_base, expected_quote = _validate_instrument_id(inst_id)
    payload = _parse_json_response(_required_raw_response(raw_response))
    if payload.get("code") != "0":
        raise RuntimeError(
            f"OKX API error code={payload.get('code')!r} message={payload.get('msg')!r}"
        )
    if not isinstance(payload.get("msg"), str):
        raise ValueError("OKX instrument response message must be a string")
    data = payload.get("data")
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], Mapping):
        raise RuntimeError("OKX instrument response must contain exactly one object")
    instrument = data[0]

    instrument_id = _required_nonempty_string(instrument.get("instId"), field="instId")
    instrument_type = _required_nonempty_string(instrument.get("instType"), field="instType")
    base_currency = _required_nonempty_string(instrument.get("baseCcy"), field="baseCcy")
    quote_currency = _required_nonempty_string(instrument.get("quoteCcy"), field="quoteCcy")
    if instrument_id != inst_id:
        raise ValueError("OKX instrument response does not match the requested inst_id")
    if instrument_type != "SPOT":
        raise ValueError("OKX instrument response is not SPOT")
    if (base_currency, quote_currency) != (expected_base, expected_quote):
        raise ValueError("OKX instrument currencies do not match the requested inst_id")

    state = _required_nonempty_string(instrument.get("state"), field="state")
    if state != "live":
        raise ValueError(f"OKX spot instrument is not live: state={state!r}")

    tick_size = _positive_decimal_string(instrument.get("tickSz"), field="tickSz")
    lot_size = _positive_decimal_string(instrument.get("lotSz"), field="lotSz")
    minimum_order_size = _positive_decimal_string(instrument.get("minSz"), field="minSz")
    listed_at = _optional_unix_milliseconds(instrument.get("listTime"), field="listTime")
    continuous_started = _optional_unix_milliseconds(
        instrument.get("contTdSwTime"),
        field="contTdSwTime",
    )
    expires_at = _optional_unix_milliseconds(instrument.get("expTime"), field="expTime")

    if listed_at is not None and listed_at > observed_at:
        raise ValueError("OKX live instrument has a future listing time")
    if continuous_started is not None and continuous_started > observed_at:
        raise ValueError("OKX live instrument has not reached continuous trading")
    if expires_at is not None and expires_at <= observed_at:
        raise ValueError("OKX spot instrument is expired or offline")

    upcoming_changes, valid_until = _parse_upcoming_changes(
        instrument.get("upcChg"),
        observed_at=observed_at,
    )
    if expires_at is not None:
        valid_until = expires_at if valid_until is None else min(valid_until, expires_at)

    return _ParsedSpotInstrument(
        instrument_id=instrument_id,
        base_currency=base_currency,
        quote_currency=quote_currency,
        state=state,
        tick_size=tick_size,
        lot_size=lot_size,
        minimum_order_size_base=minimum_order_size,
        listed_at_utc=listed_at,
        continuous_trading_started_at_utc=continuous_started,
        expires_at_utc=expires_at,
        valid_until_utc=valid_until,
        upcoming_changes=upcoming_changes,
    )


def fetch_okx_spot_instrument_snapshot(
    *,
    inst_id: str,
    base_url: str = "https://www.okx.com",
    server_time_sample: OKXServerTimeSample,
    timeout: float = 20.0,
    max_server_round_trip_seconds: float = 2.0,
    max_abs_midpoint_clock_skew_seconds: float = 5.0,
    get_bytes: RawBytesGetter | None = None,
    now: Clock | None = None,
) -> OKXSpotInstrumentSnapshot:
    """Fetch fail-closed spot sizing constraints from OKX's public endpoint."""

    _validate_instrument_id(inst_id)
    if (
        not isinstance(base_url, str)
        or not base_url
        or any(character.isspace() for character in base_url)
    ):
        raise ValueError("base_url must be a non-empty URL without whitespace")
    timeout_seconds = _required_finite_number(timeout, field="timeout")
    if timeout_seconds <= 0:
        raise ValueError("timeout must be positive")
    max_round_trip = _required_finite_number(
        max_server_round_trip_seconds,
        field="max_server_round_trip_seconds",
    )
    if max_round_trip <= 0:
        raise ValueError("max_server_round_trip_seconds must be positive")
    max_clock_skew = _required_finite_number(
        max_abs_midpoint_clock_skew_seconds,
        field="max_abs_midpoint_clock_skew_seconds",
    )
    if max_clock_skew < 0:
        raise ValueError("max_abs_midpoint_clock_skew_seconds cannot be negative")

    normalized_base_url = base_url.rstrip("/")
    endpoint = f"{normalized_base_url}{_ENDPOINT}"
    query = urlencode({"instType": "SPOT", "instId": inst_id})
    getter = get_bytes or _default_raw_bytes_getter
    clock = now or _current_utc_datetime

    request_started = _required_utc_datetime(clock(), field="request start")
    raw_response = _required_raw_response(getter(f"{endpoint}?{query}", timeout_seconds))
    response_received = _required_utc_datetime(clock(), field="response receipt")
    if response_received < request_started:
        raise ValueError("local clock moved backward during OKX instrument request")

    (
        server_request_started,
        server_response_received,
        exchange_observed_at,
        server_round_trip_seconds,
        midpoint_clock_skew_seconds,
    ) = _validated_server_time_sample(
        server_time_sample,
        max_round_trip_seconds=max_round_trip,
        max_abs_clock_skew_seconds=max_clock_skew,
    )
    if server_time_sample.base_url != normalized_base_url:
        raise ValueError("OKX instrument and server-time observations must use the same base URL")
    if server_request_started < response_received:
        raise ValueError("OKX server time must be sampled after the instrument response")
    exchange_observed = exchange_observed_at
    server_response_received_at = server_response_received

    parsed = _parse_spot_instrument_response(
        raw_response,
        inst_id=inst_id,
        observed_at=exchange_observed,
    )

    return OKXSpotInstrumentSnapshot(
        base_url=normalized_base_url,
        request_started_utc=request_started,
        response_received_utc=response_received,
        server_time_request_started_utc=server_request_started,
        exchange_observed_at_utc=exchange_observed,
        server_time_response_received_utc=server_response_received_at,
        server_round_trip_seconds=server_round_trip_seconds,
        midpoint_clock_skew_seconds=midpoint_clock_skew_seconds,
        max_server_round_trip_seconds=max_round_trip,
        max_abs_midpoint_clock_skew_seconds=max_clock_skew,
        instrument_id=parsed.instrument_id,
        base_currency=parsed.base_currency,
        quote_currency=parsed.quote_currency,
        state=parsed.state,
        tick_size=parsed.tick_size,
        lot_size=parsed.lot_size,
        minimum_order_size_base=parsed.minimum_order_size_base,
        listed_at_utc=parsed.listed_at_utc,
        continuous_trading_started_at_utc=parsed.continuous_trading_started_at_utc,
        expires_at_utc=parsed.expires_at_utc,
        valid_until_utc=parsed.valid_until_utc,
        upcoming_changes=parsed.upcoming_changes,
        raw_response_json=raw_response,
    )


def _write_immutable_file(path: Path, content: bytes) -> None:
    if path.is_symlink():
        raise ValueError(f"refusing symbolic-link instrument snapshot destination: {path}")
    if path.exists():
        if not path.is_file():
            raise ValueError(f"instrument snapshot destination is not a regular file: {path}")
        if path.read_bytes() != content:
            raise FileExistsError(f"refusing to replace conflicting instrument snapshot: {path}")
        return

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def write_okx_spot_instrument_snapshot(
    snapshot: OKXSpotInstrumentSnapshot,
    output_dir: str | Path,
) -> dict[str, Path]:
    """Persist one canonical, idempotent public-instrument snapshot."""

    destination = Path(output_dir)
    if destination.is_symlink():
        raise ValueError("instrument snapshot output directory cannot be a symbolic link")
    destination.mkdir(parents=True, exist_ok=True)
    stem = f"okx-{snapshot.instrument_id}-SPOT.instrument"
    paths = {
        "raw": destination / f"{stem}.raw.json",
        "metadata": destination / f"{stem}.metadata.json",
    }
    raw_existed = paths["raw"].exists()
    _write_immutable_file(paths["raw"], snapshot.raw_response_json)
    try:
        _write_immutable_file(paths["metadata"], snapshot.metadata_bytes())
    except BaseException:
        if not raw_existed:
            paths["raw"].unlink(missing_ok=True)
        raise
    return paths
