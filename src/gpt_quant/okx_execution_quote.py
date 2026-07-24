from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .execution_quote import ExecutionQuoteSnapshot
from .okx_live import OKXServerTimeSample, validate_okx_server_time_sample

RawBytesGetter = Callable[[str, float], bytes]
Clock = Callable[[], datetime]
_ENDPOINT = "/api/v5/market/books"
_SERVER_TIME_ENDPOINT = "/api/v5/public/time"
_MAX_RESPONSE_BYTES = 1_000_000
_EXPECTED_TOP_LEVEL_KEYS = {"code", "msg", "data"}
_EXPECTED_BOOK_KEYS = {"asks", "bids", "ts", "seqId"}
_EXPECTED_SERVER_TIME_KEYS = {"ts"}


@dataclass(frozen=True, slots=True)
class OKXTopOfBookObservation:
    """Immutable public OKX top-of-book evidence and its bounded timing envelope."""

    base_url: str
    endpoint: str
    request_started_utc: datetime
    response_received_utc: datetime
    server_time_endpoint: str
    server_time_request_started_utc: datetime
    exchange_time_observed_utc: datetime
    server_time_response_received_utc: datetime
    request_round_trip_seconds: float
    server_round_trip_seconds: float
    midpoint_clock_skew_seconds: float
    max_request_round_trip_seconds: float
    max_server_round_trip_seconds: float
    max_abs_midpoint_clock_skew_seconds: float
    maximum_quote_age_ms: int
    raw_response_json: bytes
    raw_server_time_response_json: bytes
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
        if self.server_time_endpoint != _SERVER_TIME_ENDPOINT:
            raise ValueError("OKX server-time endpoint is not the public time endpoint")
        server_started = _required_utc_datetime(
            self.server_time_request_started_utc,
            field="OKX server-time request start",
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
            ("server_time_request_started_utc", server_started),
            ("exchange_time_observed_utc", exchange_observed),
            ("server_time_response_received_utc", server_received),
        ):
            object.__setattr__(self, field_name, value)

        if response_received < request_started:
            raise ValueError("local clock moved backward during OKX books request")
        if server_started < response_received:
            raise ValueError("OKX server time must be sampled after the books response")

        request_round_trip_bound = _required_finite_number(
            self.max_request_round_trip_seconds,
            field="max_request_round_trip_seconds",
        )
        if request_round_trip_bound <= 0:
            raise ValueError("max_request_round_trip_seconds must be positive")
        server_round_trip_bound = _required_finite_number(
            self.max_server_round_trip_seconds,
            field="max_server_round_trip_seconds",
        )
        if server_round_trip_bound <= 0:
            raise ValueError("max_server_round_trip_seconds must be positive")
        clock_skew_bound = _required_finite_number(
            self.max_abs_midpoint_clock_skew_seconds,
            field="max_abs_midpoint_clock_skew_seconds",
        )
        if clock_skew_bound < 0:
            raise ValueError("max_abs_midpoint_clock_skew_seconds cannot be negative")
        object.__setattr__(
            self,
            "max_request_round_trip_seconds",
            request_round_trip_bound,
        )
        object.__setattr__(
            self,
            "max_server_round_trip_seconds",
            server_round_trip_bound,
        )
        object.__setattr__(
            self,
            "max_abs_midpoint_clock_skew_seconds",
            clock_skew_bound,
        )

        expected_round_trip = (response_received - request_started).total_seconds()
        request_round_trip = _required_nonnegative_finite_number(
            self.request_round_trip_seconds,
            field="OKX books request round trip",
        )
        if abs(request_round_trip - expected_round_trip) > 1e-9:
            raise ValueError("OKX books request round trip does not match its timestamps")
        if request_round_trip > request_round_trip_bound:
            raise ValueError("OKX books request round trip exceeds the configured bound")
        object.__setattr__(self, "request_round_trip_seconds", request_round_trip)

        raw_server_time_response = _required_raw_response(
            self.raw_server_time_response_json,
            response_name="server-time",
        )
        object.__setattr__(
            self,
            "raw_server_time_response_json",
            raw_server_time_response,
        )
        replayed_exchange_observed = _server_time_from_raw_response(raw_server_time_response)
        if replayed_exchange_observed != exchange_observed:
            raise ValueError("OKX server-time response does not reproduce the exchange timestamp")

        server_time_sample = OKXServerTimeSample(
            base_url=normalized_base_url,
            endpoint=self.server_time_endpoint,
            local_request_started_utc=server_started,
            local_response_received_utc=server_received,
            server_time_utc=exchange_observed,
            round_trip_seconds=self.server_round_trip_seconds,
            midpoint_clock_skew_seconds=self.midpoint_clock_skew_seconds,
        )
        (
            validated_server_started,
            validated_server_received,
            validated_exchange_observed,
            server_round_trip,
            midpoint_clock_skew,
        ) = validate_okx_server_time_sample(
            server_time_sample,
            max_round_trip_seconds=server_round_trip_bound,
            max_abs_clock_skew_seconds=clock_skew_bound,
        )
        object.__setattr__(
            self,
            "server_time_request_started_utc",
            validated_server_started.to_pydatetime(),
        )
        object.__setattr__(
            self,
            "server_time_response_received_utc",
            validated_server_received.to_pydatetime(),
        )
        object.__setattr__(
            self,
            "exchange_time_observed_utc",
            validated_exchange_observed.to_pydatetime(),
        )
        object.__setattr__(self, "server_round_trip_seconds", server_round_trip)
        object.__setattr__(self, "midpoint_clock_skew_seconds", midpoint_clock_skew)
        exchange_observed = validated_exchange_observed.to_pydatetime()

        maximum_quote_age_ms = _required_nonnegative_integer(
            self.maximum_quote_age_ms,
            field="maximum_quote_age_ms",
        )
        object.__setattr__(self, "maximum_quote_age_ms", maximum_quote_age_ms)

        raw_response = _required_raw_response(
            self.raw_response_json,
            response_name="books",
        )
        object.__setattr__(self, "raw_response_json", raw_response)
        response_hash = hashlib.sha256(raw_response).hexdigest()
        if response_hash != self.quote.source_response_sha256:
            raise ValueError("OKX books response hash does not match the execution quote")
        if self.quote.provider != "okx":
            raise ValueError("OKX books observation must contain an OKX execution quote")
        if self.quote.received_at_utc != response_received:
            raise ValueError("OKX local books receipt does not match the execution quote")

        replayed, exchange_book_observed = _quote_from_raw_response(
            raw_response,
            instrument_id=self.quote.instrument_id,
            instrument_snapshot_sha256=self.quote.instrument_snapshot_sha256,
            response_received_utc=response_received,
            midpoint_clock_skew_seconds=midpoint_clock_skew,
        )
        if replayed != self.quote:
            raise ValueError("OKX books response does not reproduce the execution quote")

        quote_age_ms = _milliseconds_between(exchange_book_observed, exchange_observed)
        if quote_age_ms < 0:
            raise ValueError("OKX books timestamp is after the bounded exchange-time observation")
        if quote_age_ms > maximum_quote_age_ms:
            raise ValueError("OKX top-of-book response is stale at exchange observation time")

    @property
    def source_response_sha256(self) -> str:
        return hashlib.sha256(self.raw_response_json).hexdigest()

    @property
    def server_time_response_sha256(self) -> str:
        return hashlib.sha256(self.raw_server_time_response_json).hexdigest()


def _current_utc_datetime() -> datetime:
    return datetime.now(UTC)


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> None:
        return None


def _read_public_response(url: str, timeout: float) -> bytes:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "gpt-quant-lab/0.2 (+https://github.com/Dingding-leo/GPT)",
        },
    )
    opener = build_opener(_RejectRedirects())
    with opener.open(request, timeout=timeout) as response:  # noqa: S310
        payload = response.read(_MAX_RESPONSE_BYTES + 1)
    if len(payload) > _MAX_RESPONSE_BYTES:
        raise RuntimeError("OKX public response exceeds the configured safety limit")
    return payload


def _default_raw_bytes_getter(url: str, timeout: float) -> bytes:
    return _read_public_response(url, timeout)


def _default_json_getter(url: str, timeout: float) -> Mapping[str, object]:
    return _parse_server_time_response(_read_public_response(url, timeout))


def _required_base_url(value: object) -> str:
    error = "base_url must be a trusted public OKX HTTPS origin"
    if not isinstance(value, str) or not value or any(character.isspace() for character in value):
        raise ValueError(error)

    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError(error) from exc

    hostname = parsed.hostname
    labels = hostname.split(".") if hostname is not None else []
    trusted_hostname = hostname == "okx.com" or (
        len(hostname or "") <= 253
        and len(labels) >= 3
        and labels[-2:] == ["okx", "com"]
        and all(
            label
            and len(label) <= 63
            and label.isascii()
            and label[0].isalnum()
            and label[-1].isalnum()
            and all(character.isalnum() or character == "-" for character in label)
            for label in labels[:-2]
        )
    )
    if (
        parsed.scheme.lower() != "https"
        or hostname is None
        or parsed.netloc.lower() != hostname
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or not trusted_hostname
    ):
        raise ValueError(error)

    return f"https://{hostname}"


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


def _required_raw_response(value: object, *, response_name: str) -> bytes:
    if not isinstance(value, bytes) or not value or len(value) > _MAX_RESPONSE_BYTES:
        raise ValueError(f"OKX {response_name} response must be non-empty bounded bytes")
    try:
        value.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"OKX {response_name} response must be UTF-8 JSON") from exc
    return value


def _reject_duplicate_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"OKX public JSON contains duplicate field {key!r}")
        result[key] = value
    return result


def _parse_json_object(value: bytes, *, response_name: str) -> Mapping[str, object]:
    try:
        payload = json.loads(value.decode("utf-8"), object_pairs_hook=_reject_duplicate_fields)
    except json.JSONDecodeError as exc:
        raise ValueError(f"OKX {response_name} response is not valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise ValueError(f"OKX {response_name} response must be a JSON object")
    if set(payload) != _EXPECTED_TOP_LEVEL_KEYS:
        raise ValueError(
            f"OKX {response_name} response fields do not match the public endpoint schema"
        )
    return payload


def _parse_response(value: bytes) -> Mapping[str, object]:
    return _parse_json_object(value, response_name="books")


def _parse_server_time_response(value: bytes) -> Mapping[str, object]:
    payload = _parse_json_object(value, response_name="server-time")
    if payload["code"] != "0":
        if not isinstance(payload["msg"], str):
            raise ValueError("OKX server-time response message must be a string")
        raise RuntimeError(f"OKX API error code={payload['code']!r} message={payload['msg']!r}")
    if not isinstance(payload["msg"], str):
        raise ValueError("OKX server-time response message must be a string")
    data = payload["data"]
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], Mapping):
        raise ValueError("OKX server-time response must contain exactly one object")
    if set(data[0]) != _EXPECTED_SERVER_TIME_KEYS:
        raise ValueError("OKX server-time object fields do not match the public endpoint schema")
    _unix_milliseconds_to_datetime(data[0]["ts"], field="OKX server time")
    return payload


def _server_time_from_raw_response(value: bytes) -> datetime:
    payload = _parse_server_time_response(value)
    data = payload["data"]
    assert isinstance(data, list)
    server_time = data[0]
    assert isinstance(server_time, Mapping)
    return _unix_milliseconds_to_datetime(server_time["ts"], field="OKX server time")


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
    midpoint_clock_skew_seconds: float,
) -> tuple[ExecutionQuoteSnapshot, datetime]:
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
    exchange_observed_at = _unix_milliseconds_to_datetime(
        book["ts"], field="OKX books timestamp"
    )
    local_observed_at = exchange_observed_at - timedelta(seconds=midpoint_clock_skew_seconds)

    return (
        ExecutionQuoteSnapshot(
            provider="okx",
            instrument_id=instrument_id,
            observed_at_utc=local_observed_at,
            received_at_utc=response_received_utc,
            bid_price=bid_price,
            bid_quantity=bid_quantity,
            ask_price=ask_price,
            ask_quantity=ask_quantity,
            source_response_sha256=hashlib.sha256(raw_response_json).hexdigest(),
            instrument_snapshot_sha256=instrument_snapshot_sha256,
        ),
        exchange_observed_at,
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
    get_server_time_bytes: RawBytesGetter | None = None,
    now: Clock | None = None,
) -> OKXTopOfBookObservation:
    """Fetch one public OKX depth level and bind it to public exchange time."""

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
    server_round_trip_bound = _required_finite_number(
        max_server_round_trip_seconds,
        field="max_server_round_trip_seconds",
    )
    if server_round_trip_bound <= 0:
        raise ValueError("max_server_round_trip_seconds must be positive")
    clock_skew_bound = _required_finite_number(
        max_abs_midpoint_clock_skew_seconds,
        field="max_abs_midpoint_clock_skew_seconds",
    )
    if clock_skew_bound < 0:
        raise ValueError("max_abs_midpoint_clock_skew_seconds cannot be negative")
    _required_nonnegative_integer(maximum_quote_age_ms, field="maximum_quote_age_ms")

    clock = now or _current_utc_datetime
    books_getter = get_bytes or _default_raw_bytes_getter
    server_time_getter = get_server_time_bytes or _default_raw_bytes_getter
    query = urlencode({"instId": instrument_id, "sz": "1"})
    endpoint_url = f"{normalized_base_url}{_ENDPOINT}?{query}"

    request_started = _required_utc_datetime(clock(), field="OKX books request start")
    raw_response = _required_raw_response(
        books_getter(endpoint_url, timeout_seconds),
        response_name="books",
    )
    response_received = _required_utc_datetime(clock(), field="OKX books response receipt")
    if response_received < request_started:
        raise ValueError("local clock moved backward during OKX books request")
    request_round_trip = (response_received - request_started).total_seconds()
    if request_round_trip > request_round_trip_bound:
        raise ValueError("OKX books request round trip exceeds the configured bound")

    server_endpoint_url = f"{normalized_base_url}{_SERVER_TIME_ENDPOINT}"
    server_started = _required_utc_datetime(clock(), field="OKX server-time request start")
    if server_started < response_received:
        raise ValueError("OKX server time must be sampled after the books response")
    raw_server_time_response = _required_raw_response(
        server_time_getter(server_endpoint_url, timeout_seconds),
        response_name="server-time",
    )
    server_received = _required_utc_datetime(clock(), field="OKX server-time response receipt")
    exchange_observed = _server_time_from_raw_response(raw_server_time_response)
    server_round_trip = (server_received - server_started).total_seconds()
    midpoint = server_started + (server_received - server_started) / 2
    midpoint_clock_skew = (exchange_observed - midpoint).total_seconds()
    server_time_sample = OKXServerTimeSample(
        base_url=normalized_base_url,
        endpoint=_SERVER_TIME_ENDPOINT,
        local_request_started_utc=server_started,
        local_response_received_utc=server_received,
        server_time_utc=exchange_observed,
        round_trip_seconds=server_round_trip,
        midpoint_clock_skew_seconds=midpoint_clock_skew,
    )
    (
        validated_server_started,
        validated_server_received,
        validated_exchange_observed,
        validated_server_round_trip,
        validated_midpoint_clock_skew,
    ) = validate_okx_server_time_sample(
        server_time_sample,
        max_round_trip_seconds=server_round_trip_bound,
        max_abs_clock_skew_seconds=clock_skew_bound,
    )

    quote, _ = _quote_from_raw_response(
        raw_response,
        instrument_id=instrument_id,
        instrument_snapshot_sha256=instrument_snapshot_sha256,
        response_received_utc=response_received,
        midpoint_clock_skew_seconds=validated_midpoint_clock_skew,
    )

    return OKXTopOfBookObservation(
        base_url=normalized_base_url,
        endpoint=_ENDPOINT,
        request_started_utc=request_started,
        response_received_utc=response_received,
        server_time_endpoint=_SERVER_TIME_ENDPOINT,
        server_time_request_started_utc=validated_server_started.to_pydatetime(),
        exchange_time_observed_utc=validated_exchange_observed.to_pydatetime(),
        server_time_response_received_utc=validated_server_received.to_pydatetime(),
        request_round_trip_seconds=request_round_trip,
        server_round_trip_seconds=validated_server_round_trip,
        midpoint_clock_skew_seconds=validated_midpoint_clock_skew,
        max_request_round_trip_seconds=request_round_trip_bound,
        max_server_round_trip_seconds=server_round_trip_bound,
        max_abs_midpoint_clock_skew_seconds=clock_skew_bound,
        maximum_quote_age_ms=maximum_quote_age_ms,
        raw_response_json=raw_response,
        raw_server_time_response_json=raw_server_time_response,
        quote=quote,
    )
