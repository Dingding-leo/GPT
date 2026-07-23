from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .execution_quote import ExecutionQuoteSnapshot
from .okx import JSONGetter
from .okx_live import sample_okx_server_time

RawBytesGetter = Callable[[str, float], bytes]
Clock = Callable[[], datetime]
_ENDPOINT = "/api/v5/market/books"
_MAX_RESPONSE_BYTES = 1_000_000
_EXPECTED_TOP_LEVEL_KEYS = {"code", "msg", "data"}
_EXPECTED_BOOK_KEYS = {"asks", "bids", "ts", "seqId"}


@dataclass(frozen=True, slots=True)
class OKXTopOfBookObservation:
    """Immutable public OKX top-of-book evidence and its bounded timing envelope.

    The embedded :class:`ExecutionQuoteSnapshot` is market evidence only. This record
    does not create an order, represent a fill, or combine spread with fees, slippage,
    market impact, or latency assumptions.
    """

    base_url: str
    endpoint: str
    request_started_utc: datetime
    response_received_utc: datetime
    exchange_time_observed_utc: datetime
    server_time_response_received_utc: datetime
    request_round_trip_seconds: float
    server_round_trip_seconds: float
    midpoint_clock_skew_seconds: float
    maximum_quote_age_ms: int
    raw_response_json: bytes
    quote: ExecutionQuoteSnapshot

    def __post_init__(self) -> None:
        normalized_base_url = _required_base_url(self.base_url)
        object.__setattr__(self, "base_url", normalized_base_url)
        if self.endpoint != _ENDPOINT:
            raise ValueError("OKX quote observation endpoint is not the public books endpoint")

        request_started = _required_utc_datetime(
            self.request_started_utc,
            field="OKX books request start",
        )
        response_received = _required_utc_datetime(
            self.response_received_utc,
            field="OKX books response receipt",
        )
        exchange_observed = _required_utc_datetime(
            self.exchange_time_observed_utc,
            field="OKX exchange-time observation",
        )
        server_received = _required_utc_datetime(
            self.server_time_response_received_utc,
            field="OKX server-time response receipt",
        )
        for field_name, value in (
            ("request_started_utc", request_started),
            ("response_received_utc", response_received),
            ("exchange_time_observed_utc", exchange_observed),
            ("server_time_response_received_utc", server_received),
        ):
            object.__setattr__(self, field_name, value)

        if response_received < request_started:
            raise ValueError("local clock moved backward during OKX books request")
        if server_received < response_received:
            raise ValueError("OKX server time must be sampled after the books response")

        expected_round_trip = (response_received - request_started).total_seconds()
        request_round_trip = _required_nonnegative_finite_number(
            self.request_round_trip_seconds,
            field="OKX books request round trip",
        )
        if abs(request_round_trip - expected_round_trip) > 1e-9:
            raise ValueError("OKX books request round trip does not match its timestamps")
        object.__setattr__(self, "request_round_trip_seconds", request_round_trip)
        object.__setattr__(
            self,
            "server_round_trip_seconds",
            _required_nonnegative_finite_number(
                self.server_round_trip_seconds,
                field="OKX server-time round trip",
            ),
        )
        object.__setattr__(
            self,
            "midpoint_clock_skew_seconds",
            _required_finite_number(
                self.midpoint_clock_skew_seconds,
                field="OKX midpoint clock skew",
            ),
        )

        maximum_quote_age_ms = _required_nonnegative_integer(
            self.maximum_quote_age_ms,
            field="maximum_quote_age_ms",
        )
        object.__setattr__(self, "maximum_quote_age_ms", maximum_quote_age_ms)

        raw_response = _required_raw_response(self.raw_response_json)
        object.__setattr__(self, "raw_response_json", raw_response)
        response_hash = hashlib.sha256(raw_response).hexdigest()
        if response_hash != self.quote.source_response_sha256:
            raise ValueError("OKX books response hash does not match the execution quote")
        if self.quote.provider != "okx":
            raise ValueError("OKX books observation must contain an OKX execution quote")
        if self.quote.received_at_utc != response_received:
            raise ValueError("OKX books response receipt does not match the execution quote")

        replayed = _quote_from_raw_response(
            raw_response,
            instrument_id=self.quote.instrument_id,
            instrument_snapshot_sha256=self.quote.instrument_snapshot_sha256,
            response_received_utc=response_received,
        )
        if replayed != self.quote:
            raise ValueError("OKX books response does not reproduce the execution quote")

        quote_age_ms = _milliseconds_between(self.quote.observed_at_utc, exchange_observed)
        if quote_age_ms < 0:
            raise ValueError("OKX books timestamp is after the bounded exchange-time observation")
        if quote_age_ms > maximum_quote_age_ms:
            raise ValueError("OKX top-of-book response is stale at exchange observation time")

    @property
    def source_response_sha256(self) -> str:
        return hashlib.sha256(self.raw_response_json).hexdigest()


def _current_utc_datetime() -> datetime:
    return datetime.now(UTC)


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
        raise RuntimeError("OKX books response exceeds the configured safety limit")
    return payload


def _required_base_url(value: object) -> str:
    if not isinstance(value, str) or not value or any(character.isspace() for character in value):
        raise ValueError("base_url must be a non-empty URL without whitespace")
    return value.rstrip("/")


def _required_utc_datetime(value: object, *, field: str) -> datetime:
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


def _required_nonnegative_finite_number(value: object, *, field: str) -> float:
    number = _required_finite_number(value, field=field)
    if number < 0:
        raise ValueError(f"{field} cannot be negative")
    return number


def _required_nonnegative_integer(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _required_raw_response(value: object) -> bytes:
    if not isinstance(value, bytes) or not value or len(value) > _MAX_RESPONSE_BYTES:
        raise ValueError("OKX books response must be non-empty bounded bytes")
    try:
        value.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("OKX books response must be UTF-8 JSON") from exc
    return value


def _reject_duplicate_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"OKX books JSON contains duplicate field {key!r}")
        result[key] = value
    return result


def _parse_response(value: bytes) -> Mapping[str, object]:
    try:
        payload = json.loads(value.decode("utf-8"), object_pairs_hook=_reject_duplicate_fields)
    except json.JSONDecodeError as exc:
        raise ValueError("OKX books response is not valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("OKX books response must be a JSON object")
    if set(payload) != _EXPECTED_TOP_LEVEL_KEYS:
        raise ValueError("OKX books response fields do not match the public endpoint schema")
    return payload


def _required_ascii_digits(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
        raise ValueError(f"{field} must contain only ASCII digits")
    return value


def _required_book_level(value: object, *, side: str) -> tuple[str, str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 4:
        raise ValueError(f"OKX {side} level must contain price, size, deprecated field and count")
    price, quantity, deprecated, order_count = value
    if deprecated != "0":
        raise ValueError(f"OKX {side} deprecated liquidation field must be zero")
    count = _required_ascii_digits(order_count, field=f"OKX {side} order count")
    if int(count) <= 0:
        raise ValueError(f"OKX {side} order count must be positive")
    if not isinstance(price, str) or not isinstance(quantity, str):
        raise ValueError(f"OKX {side} price and size must be decimal strings")
    return price, quantity


def _unix_milliseconds_to_datetime(value: object, *, field: str) -> datetime:
    timestamp = _required_ascii_digits(value, field=field)
    milliseconds = int(timestamp)
    seconds, remainder = divmod(milliseconds, 1_000)
    try:
        return datetime.fromtimestamp(seconds, tz=UTC).replace(microsecond=remainder * 1_000)
    except (OverflowError, OSError, ValueError) as exc:
        raise ValueError(f"{field} is outside the supported timestamp range") from exc


def _quote_from_raw_response(
    raw_response_json: bytes,
    *,
    instrument_id: str,
    instrument_snapshot_sha256: str,
    response_received_utc: datetime,
) -> ExecutionQuoteSnapshot:
    payload = _parse_response(raw_response_json)
    if payload["code"] != "0":
        raise RuntimeError(f"OKX API error code={payload['code']!r} message={payload['msg']!r}")
    if not isinstance(payload["msg"], str):
        raise ValueError("OKX books response message must be a string")
    data = payload["data"]
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], Mapping):
        raise ValueError("OKX books response must contain exactly one book object")
    book = data[0]
    if set(book) != _EXPECTED_BOOK_KEYS:
        raise ValueError("OKX books object fields do not match the public endpoint schema")

    asks = book["asks"]
    bids = book["bids"]
    if not isinstance(asks, list) or len(asks) != 1:
        raise ValueError("OKX books response must contain exactly one ask level")
    if not isinstance(bids, list) or len(bids) != 1:
        raise ValueError("OKX books response must contain exactly one bid level")
    ask_price, ask_quantity = _required_book_level(asks[0], side="ask")
    bid_price, bid_quantity = _required_book_level(bids[0], side="bid")

    sequence_id = book["seqId"]
    if isinstance(sequence_id, bool) or not isinstance(sequence_id, int) or sequence_id < 0:
        raise ValueError("OKX books sequence ID must be a non-negative integer")
    observed_at = _unix_milliseconds_to_datetime(book["ts"], field="OKX books timestamp")

    return ExecutionQuoteSnapshot(
        provider="okx",
        instrument_id=instrument_id,
        observed_at_utc=observed_at,
        received_at_utc=response_received_utc,
        bid_price=bid_price,
        bid_quantity=bid_quantity,
        ask_price=ask_price,
        ask_quantity=ask_quantity,
        source_response_sha256=hashlib.sha256(raw_response_json).hexdigest(),
        instrument_snapshot_sha256=instrument_snapshot_sha256,
    )


def _milliseconds_between(earlier: datetime, later: datetime) -> int:
    delta = later - earlier
    return int(delta.total_seconds() * 1_000)


def fetch_okx_top_of_book(
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
) -> OKXTopOfBookObservation:
    """Fetch one public OKX depth level and bind it to public exchange time.

    Only ``GET /api/v5/market/books`` and ``GET /api/v5/public/time`` are used.
    No credentials, account state, order endpoint, or order placement is involved.
    """

    if not isinstance(instrument_id, str) or instrument_id != instrument_id.strip():
        raise ValueError("instrument_id must be a trimmed string")
    parts = instrument_id.split("-")
    if (
        len(parts) != 2
        or instrument_id.upper() != instrument_id
        or any(not part or not part.isalnum() for part in parts)
    ):
        raise ValueError("instrument_id must have uppercase BASE-QUOTE spot format")
    if not isinstance(instrument_snapshot_sha256, str) or len(instrument_snapshot_sha256) != 64:
        raise ValueError("instrument_snapshot_sha256 must be a lowercase SHA-256 digest")
    if any(character not in "0123456789abcdef" for character in instrument_snapshot_sha256):
        raise ValueError("instrument_snapshot_sha256 must be a lowercase SHA-256 digest")

    normalized_base_url = _required_base_url(base_url)
    timeout_seconds = _required_finite_number(timeout, field="timeout")
    if timeout_seconds <= 0:
        raise ValueError("timeout must be positive")
    request_round_trip_bound = _required_finite_number(
        max_request_round_trip_seconds,
        field="max_request_round_trip_seconds",
    )
    if request_round_trip_bound <= 0:
        raise ValueError("max_request_round_trip_seconds must be positive")
    _required_nonnegative_integer(maximum_quote_age_ms, field="maximum_quote_age_ms")

    clock = now or _current_utc_datetime
    getter = get_bytes or _default_raw_bytes_getter
    query = urlencode({"instId": instrument_id, "sz": "1"})
    endpoint_url = f"{normalized_base_url}{_ENDPOINT}?{query}"

    request_started = _required_utc_datetime(clock(), field="OKX books request start")
    raw_response = _required_raw_response(getter(endpoint_url, timeout_seconds))
    response_received = _required_utc_datetime(clock(), field="OKX books response receipt")
    if response_received < request_started:
        raise ValueError("local clock moved backward during OKX books request")
    request_round_trip = (response_received - request_started).total_seconds()
    if request_round_trip > request_round_trip_bound:
        raise ValueError("OKX books request round trip exceeds the configured bound")

    quote = _quote_from_raw_response(
        raw_response,
        instrument_id=instrument_id,
        instrument_snapshot_sha256=instrument_snapshot_sha256,
        response_received_utc=response_received,
    )

    server_time_sample = sample_okx_server_time(
        base_url=normalized_base_url,
        timeout=timeout_seconds,
        max_round_trip_seconds=max_server_round_trip_seconds,
        max_abs_clock_skew_seconds=max_abs_midpoint_clock_skew_seconds,
        get_json=get_json,
        now=clock,
    )
    if server_time_sample.local_request_started_utc.to_pydatetime() < response_received:
        raise ValueError("OKX server time must be sampled after the books response")

    return OKXTopOfBookObservation(
        base_url=normalized_base_url,
        endpoint=_ENDPOINT,
        request_started_utc=request_started,
        response_received_utc=response_received,
        exchange_time_observed_utc=server_time_sample.server_time_utc.to_pydatetime(),
        server_time_response_received_utc=(
            server_time_sample.local_response_received_utc.to_pydatetime()
        ),
        request_round_trip_seconds=request_round_trip,
        server_round_trip_seconds=server_time_sample.round_trip_seconds,
        midpoint_clock_skew_seconds=server_time_sample.midpoint_clock_skew_seconds,
        maximum_quote_age_ms=maximum_quote_age_ms,
        raw_response_json=raw_response,
        quote=quote,
    )
