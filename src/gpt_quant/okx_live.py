from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from math import isfinite
from typing import Any

import pandas as pd

from .okx import (
    JSONGetter,
    OKXCandleSnapshot,
    _default_json_getter,
    _verified_snapshot_bytes,
)

Clock = Callable[[], pd.Timestamp | str]
_SERVER_TIME_ENDPOINT = "/api/v5/public/time"


@dataclass(frozen=True, slots=True)
class OKXServerTimeSample:
    """Bounded read-only observation of the OKX public server clock."""

    base_url: str
    endpoint: str
    local_request_started_utc: pd.Timestamp
    local_response_received_utc: pd.Timestamp
    server_time_utc: pd.Timestamp
    round_trip_seconds: float
    midpoint_clock_skew_seconds: float


@dataclass(frozen=True, slots=True)
class OKXCompletedBarCutoff:
    """Conservative timing boundary for one observed, completed OKX candle."""

    instrument_id: str
    bar: str
    bar_open_utc: pd.Timestamp
    bar_close_utc: pd.Timestamp
    observed_at_utc: pd.Timestamp
    exchange_observed_at_utc: pd.Timestamp
    server_time_response_received_utc: pd.Timestamp
    signal_not_before_utc: pd.Timestamp
    availability_delay_seconds: float
    server_round_trip_seconds: float
    midpoint_clock_skew_seconds: float
    max_server_round_trip_seconds: float
    max_abs_midpoint_clock_skew_seconds: float


def _required_utc_timestamp(value: Any, *, field: str) -> pd.Timestamp:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a valid timezone-aware timestamp") from exc
    if pd.isna(timestamp) or timestamp.tzinfo is None:
        raise ValueError(f"{field} must be a valid timezone-aware timestamp")
    return timestamp.tz_convert("UTC")


def _current_utc_timestamp() -> pd.Timestamp:
    return pd.Timestamp.now(tz="UTC")


def _required_unix_milliseconds(value: Any, *, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer Unix millisecond timestamp")
    if isinstance(value, int):
        milliseconds = value
    elif isinstance(value, str) and value.isascii() and value.isdecimal():
        milliseconds = int(value)
    else:
        raise ValueError(f"{field} must be an integer Unix millisecond timestamp")
    if milliseconds < 0:
        raise ValueError(f"{field} must be an integer Unix millisecond timestamp")
    return milliseconds


def _required_finite_number(value: Any, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field} must be a finite number")
    number = float(value)
    if not isfinite(number):
        raise ValueError(f"{field} must be a finite number")
    return number


def validate_okx_server_time_sample(
    sample: OKXServerTimeSample,
    *,
    max_round_trip_seconds: float,
    max_abs_clock_skew_seconds: float,
) -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, float, float]:
    """Revalidate and normalize one persisted OKX public-time observation.

    The caller supplies the exact policy bounds that governed the observation. This
    makes downstream market-data records independently reconstructable instead of
    trusting copied round-trip or clock-skew scalars.
    """
    round_trip_bound = _required_finite_number(
        max_round_trip_seconds,
        field="max_round_trip_seconds",
    )
    if round_trip_bound <= 0:
        raise ValueError("max_round_trip_seconds must be positive")
    clock_skew_bound = _required_finite_number(
        max_abs_clock_skew_seconds,
        field="max_abs_clock_skew_seconds",
    )
    if clock_skew_bound < 0:
        raise ValueError("max_abs_clock_skew_seconds cannot be negative")

    if not sample.base_url or any(character.isspace() for character in sample.base_url):
        raise ValueError(
            "OKX server-time sample base_url must be a non-empty URL without whitespace"
        )
    if sample.base_url.rstrip("/") != sample.base_url:
        raise ValueError("OKX server-time sample base_url must be normalized")
    if sample.endpoint != _SERVER_TIME_ENDPOINT:
        raise ValueError("OKX server-time sample endpoint is not the public time endpoint")

    local_started = _required_utc_timestamp(
        sample.local_request_started_utc,
        field="server-time local request start",
    )
    local_received = _required_utc_timestamp(
        sample.local_response_received_utc,
        field="server-time local response receipt",
    )
    server_time = _required_utc_timestamp(
        sample.server_time_utc,
        field="OKX server time",
    )
    if local_received < local_started:
        raise ValueError("local clock moved backward during OKX server-time request")

    expected_round_trip = (local_received - local_started).total_seconds()
    recorded_round_trip = _required_finite_number(
        sample.round_trip_seconds,
        field="OKX server-time round trip",
    )
    if recorded_round_trip < 0:
        raise ValueError("OKX server-time round trip cannot be negative")
    if abs(recorded_round_trip - expected_round_trip) > 1e-9:
        raise ValueError("OKX server-time round trip does not match its timestamps")
    if recorded_round_trip > round_trip_bound:
        raise ValueError("OKX server-time round trip exceeds the live cutoff bound")

    midpoint = local_started + (local_received - local_started) / 2
    expected_clock_skew = (server_time - midpoint).total_seconds()
    recorded_clock_skew = _required_finite_number(
        sample.midpoint_clock_skew_seconds,
        field="OKX midpoint clock skew",
    )
    if abs(recorded_clock_skew - expected_clock_skew) > 1e-9:
        raise ValueError("OKX midpoint clock skew does not match its timestamps")
    if abs(recorded_clock_skew) > clock_skew_bound:
        raise ValueError("local clock skew from OKX exceeds the live cutoff bound")

    return (
        local_started,
        local_received,
        server_time,
        recorded_round_trip,
        recorded_clock_skew,
    )


# Backward-compatible private name used by the existing instrument evidence boundary.
_validated_server_time_sample = validate_okx_server_time_sample


def sample_okx_server_time(
    *,
    base_url: str = "https://www.okx.com",
    timeout: float = 20.0,
    max_round_trip_seconds: float = 2.0,
    max_abs_clock_skew_seconds: float = 5.0,
    get_json: JSONGetter | None = None,
    now: Clock | None = None,
) -> OKXServerTimeSample:
    """Sample OKX's unauthenticated server clock and reject uncertain observations.

    The public endpoint returns one Unix-millisecond timestamp. The local clock is
    sampled immediately before and after the request. The server timestamp is
    compared with the local midpoint, while the full request round trip bounds
    network uncertainty. This function never accesses an account or order endpoint.
    """

    if not base_url or any(character.isspace() for character in base_url):
        raise ValueError("base_url must be a non-empty URL without whitespace")
    timeout_seconds = _required_finite_number(timeout, field="timeout")
    if timeout_seconds <= 0:
        raise ValueError("timeout must be positive")
    round_trip_bound = _required_finite_number(
        max_round_trip_seconds,
        field="max_round_trip_seconds",
    )
    if round_trip_bound <= 0:
        raise ValueError("max_round_trip_seconds must be positive")
    clock_skew_bound = _required_finite_number(
        max_abs_clock_skew_seconds,
        field="max_abs_clock_skew_seconds",
    )
    if clock_skew_bound < 0:
        raise ValueError("max_abs_clock_skew_seconds cannot be negative")

    getter = get_json or _default_json_getter
    clock = now or _current_utc_timestamp
    normalized_base_url = base_url.rstrip("/")
    endpoint = f"{normalized_base_url}{_SERVER_TIME_ENDPOINT}"

    local_started = _required_utc_timestamp(clock(), field="local request start")
    payload = dict(getter(endpoint, timeout_seconds))
    local_received = _required_utc_timestamp(clock(), field="local response receipt")
    if local_received < local_started:
        raise ValueError("local clock moved backward during OKX server-time request")

    code = str(payload.get("code", ""))
    if code != "0":
        message = str(payload.get("msg", ""))
        raise RuntimeError(f"OKX API error code={code!r} message={message!r}")
    data = payload.get("data")
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], Mapping):
        raise RuntimeError("OKX server-time response must contain exactly one object")
    server_timestamp_ms = _required_unix_milliseconds(
        data[0].get("ts"),
        field="OKX server time",
    )
    try:
        server_time = pd.to_datetime(server_timestamp_ms, unit="ms", utc=True)
    except (OverflowError, ValueError) as exc:
        raise ValueError("OKX server time is outside the supported timestamp range") from exc

    round_trip_seconds = (local_received - local_started).total_seconds()
    if round_trip_seconds > round_trip_bound:
        raise ValueError("OKX server-time round trip exceeds the configured bound")
    midpoint = local_started + (local_received - local_started) / 2
    clock_skew_seconds = (server_time - midpoint).total_seconds()
    if abs(clock_skew_seconds) > clock_skew_bound:
        raise ValueError("local clock skew from OKX exceeds the configured bound")

    return OKXServerTimeSample(
        base_url=normalized_base_url,
        endpoint=_SERVER_TIME_ENDPOINT,
        local_request_started_utc=local_started,
        local_response_received_utc=local_received,
        server_time_utc=server_time,
        round_trip_seconds=round_trip_seconds,
        midpoint_clock_skew_seconds=clock_skew_seconds,
    )


def build_okx_completed_bar_cutoff(
    snapshot: OKXCandleSnapshot,
    *,
    server_time_sample: OKXServerTimeSample,
    max_round_trip_seconds: float = 2.0,
    max_abs_clock_skew_seconds: float = 5.0,
) -> OKXCompletedBarCutoff:
    """Return the earliest safe decision timestamp for an open-ended candle snapshot.

    A ``confirm=1`` flag and a local post-download timestamp are not sufficient for
    a live decision. The bar's scheduled close must be no later than a bounded OKX
    server-time observation sampled after the candle download. The returned cutoff
    makes no fill-price, spread, slippage, impact, latency, or order-acceptance claim.
    """

    round_trip_bound = _required_finite_number(
        max_round_trip_seconds,
        field="max_round_trip_seconds",
    )
    if round_trip_bound <= 0:
        raise ValueError("max_round_trip_seconds must be positive")
    clock_skew_bound = _required_finite_number(
        max_abs_clock_skew_seconds,
        field="max_abs_clock_skew_seconds",
    )
    if clock_skew_bound < 0:
        raise ValueError("max_abs_clock_skew_seconds cannot be negative")
    _verified_snapshot_bytes(snapshot)
    (
        server_request_started,
        server_response_received,
        exchange_observed_at,
        server_round_trip_seconds,
        midpoint_clock_skew_seconds,
    ) = validate_okx_server_time_sample(
        server_time_sample,
        max_round_trip_seconds=round_trip_bound,
        max_abs_clock_skew_seconds=clock_skew_bound,
    )

    metadata = snapshot.metadata
    if metadata.get("provider") != "OKX":
        raise ValueError("live signal cutoff requires an OKX snapshot")
    if metadata.get("requested_end") is not None:
        raise ValueError("live signal cutoff requires an open-ended OKX snapshot")
    if snapshot.candles.empty:
        raise ValueError("live signal cutoff requires at least one completed candle")

    snapshot_base_url = metadata.get("base_url")
    if not isinstance(snapshot_base_url, str) or not snapshot_base_url:
        raise ValueError("OKX snapshot base_url must be a non-empty string")
    if snapshot_base_url.rstrip("/") != server_time_sample.base_url:
        raise ValueError("OKX candle and server-time observations must use the same base URL")

    instrument_id = metadata.get("instrument_id")
    bar = metadata.get("bar")
    if not isinstance(instrument_id, str) or not instrument_id:
        raise ValueError("OKX snapshot instrument_id must be a non-empty string")
    if not isinstance(bar, str) or not bar:
        raise ValueError("OKX snapshot bar must be a non-empty string")

    step_seconds = metadata.get("expected_step_seconds")
    if isinstance(step_seconds, bool) or not isinstance(step_seconds, int) or step_seconds <= 0:
        raise ValueError("OKX snapshot expected_step_seconds must be a positive integer")

    observed_at = _required_utc_timestamp(
        metadata.get("freshness_checked_at_utc"),
        field="freshness_checked_at_utc",
    )
    if server_request_started < observed_at:
        raise ValueError("OKX server time must be sampled after the candle download")

    latest_open = _required_utc_timestamp(snapshot.candles.index[-1], field="latest candle")
    metadata_end = _required_utc_timestamp(metadata.get("end"), field="metadata end")
    if metadata_end != latest_open:
        raise ValueError("OKX snapshot metadata end does not match the latest candle")

    latest_confirm = str(snapshot.candles.iloc[-1].get("confirm", ""))
    if latest_confirm != "1":
        raise ValueError("live signal cutoff requires a confirmed latest candle")

    reported_age = metadata.get("freshness_age_seconds")
    if isinstance(reported_age, bool) or not isinstance(reported_age, int | float):
        raise ValueError("OKX snapshot freshness_age_seconds must be numeric")
    observed_age_seconds = (observed_at - latest_open).total_seconds()
    if abs(float(reported_age) - observed_age_seconds) > 1e-6:
        raise ValueError("OKX snapshot freshness age does not match its timestamps")

    bar_close = latest_open + pd.Timedelta(seconds=step_seconds)
    if exchange_observed_at < bar_close:
        raise ValueError("latest confirmed OKX candle has not closed according to server time")
    availability_delay_seconds = (exchange_observed_at - bar_close).total_seconds()
    if availability_delay_seconds >= step_seconds:
        raise ValueError("latest confirmed OKX candle is stale relative to server time")

    signal_not_before = max(
        observed_at,
        exchange_observed_at,
        server_response_received,
    )
    return OKXCompletedBarCutoff(
        instrument_id=instrument_id,
        bar=bar,
        bar_open_utc=latest_open,
        bar_close_utc=bar_close,
        observed_at_utc=observed_at,
        exchange_observed_at_utc=exchange_observed_at,
        server_time_response_received_utc=server_response_received,
        signal_not_before_utc=signal_not_before,
        availability_delay_seconds=availability_delay_seconds,
        server_round_trip_seconds=server_round_trip_seconds,
        midpoint_clock_skew_seconds=midpoint_clock_skew_seconds,
        max_server_round_trip_seconds=round_trip_bound,
        max_abs_midpoint_clock_skew_seconds=clock_skew_bound,
    )
