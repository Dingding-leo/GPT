from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

JSONGetter = Callable[[str, float], Mapping[str, Any]]
_ENDPOINT = "/api/v5/market/history-candles"
_COLUMNS = (
    "ts",
    "open",
    "high",
    "low",
    "close",
    "volume_base",
    "volume_quote",
    "volume_quote_alt",
    "confirm",
)
_MILLISECONDS_PER_DAY = 86_400_000


@dataclass(frozen=True, slots=True)
class OKXCandleSnapshot:
    """An immutable description of one paginated OKX public-data download."""

    candles: pd.DataFrame
    raw_pages: tuple[dict[str, Any], ...]
    metadata: dict[str, Any]
    _source_normalized_csv_sha256: str = field(init=False, repr=False, compare=False)
    _source_raw_pages_sha256: str = field(init=False, repr=False, compare=False)
    _source_metadata_sha256: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "_source_normalized_csv_sha256",
            _sha256(_canonical_csv_bytes(self.candles)),
        )
        object.__setattr__(
            self,
            "_source_raw_pages_sha256",
            _sha256(_canonical_json_bytes(self.raw_pages)),
        )
        object.__setattr__(
            self,
            "_source_metadata_sha256",
            _sha256(_canonical_json_bytes(self.metadata)),
        )

    @property
    def close(self) -> pd.Series:
        return self.candles["close"].rename("close")


def _timestamp_utc(value: pd.Timestamp | str | None) -> pd.Timestamp | None:
    if value is None:
        return None
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()


def _canonical_csv_bytes(frame: pd.DataFrame) -> bytes:
    output = frame.reset_index(names="timestamp").to_csv(
        index=False,
        date_format="%Y-%m-%dT%H:%M:%S.%fZ",
        float_format="%.12g",
        lineterminator="\n",
    )
    return output.encode()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fixed_bar_step_seconds(bar: str) -> int | None:
    """Return the declared cadence for fixed-width OKX bars.

    Calendar-month bars are intentionally excluded because they do not have a
    constant duration. The optional ``utc`` suffix changes the session anchor,
    not the interval width.
    """

    normalized = bar.removesuffix("utc")
    if len(normalized) < 2 or not normalized[:-1].isdigit():
        return None
    multiplier = {
        "s": 1,
        "m": 60,
        "H": 60 * 60,
        "D": 24 * 60 * 60,
        "W": 7 * 24 * 60 * 60,
    }.get(normalized[-1])
    if multiplier is None:
        return None
    return int(normalized[:-1]) * multiplier


def _default_json_getter(url: str, timeout: float) -> Mapping[str, Any]:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "gpt-quant-lab/0.2 (+https://github.com/Dingding-leo/GPT)",
        },
    )
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, Mapping):
                raise RuntimeError("OKX returned a non-object JSON payload")
            return payload
        except HTTPError as exc:
            last_error = exc
            if exc.code not in {408, 429, 500, 502, 503, 504} or attempt == 2:
                raise RuntimeError(f"OKX HTTP error {exc.code}") from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt == 2:
                raise RuntimeError("OKX request failed after retries") from exc
        time.sleep(0.5 * (2**attempt))
    raise RuntimeError("OKX request failed") from last_error


def _coerce_okx_timestamp_ms(value: Any) -> int:
    """Return an exact integer millisecond timestamp without truncation."""

    if isinstance(value, (bool, np.bool_)):
        raise ValueError("timestamp must be an integer millisecond value")
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        numeric = float(value)
        if not np.isfinite(numeric) or not numeric.is_integer():
            raise ValueError("timestamp must be an integer millisecond value")
        return int(numeric)
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        return int(value)
    raise ValueError("timestamp must be an integer millisecond value")


def _validate_okx_bar_anchor(timestamp_ms: int, *, bar: str) -> None:
    if bar == "1Dutc" and timestamp_ms % _MILLISECONDS_PER_DAY != 0:
        raise ValueError("OKX 1Dutc candle timestamps must be aligned to midnight UTC")


def parse_okx_candle_rows(rows: Sequence[Sequence[Any]]) -> pd.DataFrame:
    """Parse and strictly validate raw OKX candle rows."""

    normalized: list[list[Any]] = []
    for row_number, row in enumerate(rows, start=1):
        if not isinstance(row, Sequence) or isinstance(row, (str, bytes)):
            raise ValueError(f"OKX candle row {row_number} is not an array")
        if len(row) != len(_COLUMNS):
            raise ValueError(
                f"OKX candle row {row_number} must contain exactly {len(_COLUMNS)} fields"
            )
        normalized.append(list(row))

    if not normalized:
        return pd.DataFrame(columns=_COLUMNS[1:]).rename_axis("timestamp")

    frame = pd.DataFrame(normalized, columns=_COLUMNS)
    try:
        timestamp = pd.to_datetime(
            frame.pop("ts").map(_coerce_okx_timestamp_ms),
            unit="ms",
            utc=True,
            errors="coerce",
        )
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError("OKX candle payload contains an invalid timestamp") from exc
    if timestamp.isna().any():
        raise ValueError("OKX candle payload contains an invalid timestamp")

    numeric_columns = [
        "open",
        "high",
        "low",
        "close",
        "volume_base",
        "volume_quote",
        "volume_quote_alt",
    ]
    for column in numeric_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if frame[numeric_columns].isna().any().any():
        raise ValueError("OKX candle payload contains a non-numeric market-data value")
    if not np.isfinite(frame[numeric_columns].to_numpy(dtype=float)).all():
        raise ValueError("OKX candle payload contains a non-finite market-data value")

    frame["confirm"] = frame["confirm"].astype(str)
    if not frame["confirm"].isin({"0", "1"}).all():
        raise ValueError("OKX candle payload contains an invalid confirm flag")

    price_columns = ["open", "high", "low", "close"]
    if (frame[price_columns] <= 0).any().any():
        raise ValueError("OKX candle prices must be strictly positive")
    if (frame[["volume_base", "volume_quote", "volume_quote_alt"]] < 0).any().any():
        raise ValueError("OKX candle volumes cannot be negative")
    if (frame["high"] < frame[["open", "close", "low"]].max(axis=1)).any():
        raise ValueError("OKX candle high violates OHLC invariants")
    if (frame["low"] > frame[["open", "close", "high"]].min(axis=1)).any():
        raise ValueError("OKX candle low violates OHLC invariants")

    frame.index = pd.DatetimeIndex(timestamp, name="timestamp")
    return frame.sort_index()


def fetch_okx_history_candles(
    *,
    inst_id: str = "BTC-USDT",
    bar: str = "1Dutc",
    start: pd.Timestamp | str | None = None,
    end: pd.Timestamp | str | None = None,
    base_url: str = "https://www.okx.com",
    limit: int = 100,
    max_pages: int = 40,
    pause_seconds: float = 0.12,
    timeout: float = 20.0,
    get_json: JSONGetter | None = None,
) -> OKXCandleSnapshot:
    """Download completed historical candles from OKX's unauthenticated REST API.

    Pagination always moves backward in exchange time. The current, unconfirmed
    candle is excluded so repeated research runs cannot mix partial and complete bars.
    A requested ``start`` is a completeness boundary: exhausting ``max_pages`` before
    reaching it raises instead of silently returning a truncated research sample.
    Raw pagination overlaps must agree exactly, and fixed-width bars must be continuous
    at the declared cadence. Calendar bars fail closed until calendar-aware continuity
    validation is implemented.
    """

    if not inst_id or any(character.isspace() for character in inst_id):
        raise ValueError("inst_id must be a non-empty OKX instrument identifier")
    if not bar or any(character.isspace() for character in bar):
        raise ValueError("bar must be a non-empty OKX candle interval")
    declared_step_seconds = _fixed_bar_step_seconds(bar)
    if declared_step_seconds is None:
        raise ValueError(
            "bar must be a supported fixed-width OKX interval; calendar and unknown "
            "intervals are rejected until calendar-aware continuity validation exists"
        )
    if not 1 <= limit <= 100:
        raise ValueError("history-candles limit must be in [1, 100]")
    if max_pages < 1:
        raise ValueError("max_pages must be positive")
    if pause_seconds < 0:
        raise ValueError("pause_seconds cannot be negative")
    if timeout <= 0:
        raise ValueError("timeout must be positive")

    start_timestamp = _timestamp_utc(start)
    end_timestamp = _timestamp_utc(end)
    if (
        start_timestamp is not None
        and end_timestamp is not None
        and start_timestamp > end_timestamp
    ):
        raise ValueError("start must not be after end")

    getter = get_json or _default_json_getter
    endpoint = f"{base_url.rstrip('/')}{_ENDPOINT}"
    raw_pages: list[dict[str, Any]] = []
    raw_rows: list[Sequence[Any]] = []
    cursor: str | None = None
    previous_oldest: int | None = None
    seen_rows_by_timestamp: dict[int, tuple[Any, ...]] = {}
    start_ms = int(start_timestamp.timestamp() * 1_000) if start_timestamp is not None else None
    pagination_termination = "max_pages"

    for page_number in range(max_pages):
        parameters = {"instId": inst_id, "bar": bar, "limit": str(limit)}
        if cursor is not None:
            parameters["after"] = cursor
        url = f"{endpoint}?{urlencode(parameters)}"
        payload = dict(getter(url, timeout))
        code = str(payload.get("code", ""))
        if code != "0":
            message = str(payload.get("msg", ""))
            raise RuntimeError(f"OKX API error code={code!r} message={message!r}")
        page_data = payload.get("data")
        if not isinstance(page_data, list):
            raise RuntimeError("OKX API response is missing a list-valued data field")

        raw_pages.append(payload)
        if not page_data:
            pagination_termination = "empty_page"
            break

        page_timestamps: list[int] = []
        for row_number, row in enumerate(page_data, start=1):
            if not isinstance(row, Sequence) or isinstance(row, (str, bytes)):
                raise ValueError("OKX candle response contains a malformed row")
            if len(row) != len(_COLUMNS):
                raise ValueError(
                    f"OKX candle response page {page_number + 1} row {row_number} "
                    f"must contain exactly {len(_COLUMNS)} fields"
                )
            try:
                timestamp = _coerce_okx_timestamp_ms(row[0])
            except (TypeError, ValueError) as exc:
                raise ValueError("OKX candle response contains an invalid timestamp") from exc
            _validate_okx_bar_anchor(timestamp, bar=bar)
            normalized_row = tuple(row)
            previous = seen_rows_by_timestamp.get(timestamp)
            if previous is not None and normalized_row != previous:
                raise ValueError(
                    f"OKX candle response conflicts with an earlier row for timestamp {timestamp}"
                )
            seen_rows_by_timestamp.setdefault(timestamp, normalized_row)
            page_timestamps.append(timestamp)
        raw_rows.extend(page_data)

        oldest = min(page_timestamps)
        if previous_oldest is not None and oldest >= previous_oldest:
            raise RuntimeError("OKX pagination did not move backward in time")
        previous_oldest = oldest
        cursor = str(oldest)

        if start_ms is not None and oldest <= start_ms:
            pagination_termination = "requested_start"
            break
        if len(page_data) < limit:
            pagination_termination = "short_page"
            break
        if page_number + 1 < max_pages and pause_seconds:
            time.sleep(pause_seconds)

    if (
        pagination_termination == "max_pages"
        and start_ms is not None
        and previous_oldest is not None
        and previous_oldest > start_ms
    ):
        raise RuntimeError("OKX pagination exhausted max_pages before reaching the requested start")

    parsed = parse_okx_candle_rows(raw_rows)
    raw_observations = len(parsed)
    duplicates_removed = int(parsed.index.duplicated(keep="last").sum())
    parsed = parsed[~parsed.index.duplicated(keep="last")].sort_index()
    incomplete_removed = int((parsed["confirm"] != "1").sum())
    candles = parsed.loc[parsed["confirm"] == "1"].copy()
    if start_timestamp is not None:
        candles = candles.loc[candles.index >= start_timestamp]
    if end_timestamp is not None:
        candles = candles.loc[candles.index <= end_timestamp]
    if candles.empty:
        raise ValueError("OKX download contains no completed candles in the requested interval")

    expected_step_seconds = declared_step_seconds
    missing_intervals = None
    if len(candles) > 1:
        deltas = candles.index.to_series().diff().dropna().dt.total_seconds()
        interval_multiples = deltas / declared_step_seconds
        rounded_multiples = np.rint(interval_multiples).astype(int)
        off_cadence = ~np.isclose(
            interval_multiples.to_numpy(dtype=float),
            rounded_multiples.to_numpy(dtype=float),
            rtol=0.0,
            atol=1e-9,
        )
        if off_cadence.any():
            raise ValueError(f"OKX download contains off-cadence intervals for bar {bar!r}")
        missing_intervals = int(np.maximum(rounded_multiples - 1, 0).sum())
        if missing_intervals:
            raise ValueError(
                f"OKX download is missing {missing_intervals} expected intervals for bar {bar!r}"
            )

    canonical_csv = _canonical_csv_bytes(candles)
    canonical_raw = _canonical_json_bytes(raw_pages)
    metadata: dict[str, Any] = {
        "provider": "OKX",
        "endpoint": _ENDPOINT,
        "base_url": base_url.rstrip("/"),
        "instrument_id": inst_id,
        "bar": bar,
        "fetched_at_utc": datetime.now(UTC).isoformat(),
        "requested_start": start_timestamp.isoformat() if start_timestamp is not None else None,
        "requested_end": end_timestamp.isoformat() if end_timestamp is not None else None,
        "limit": limit,
        "max_pages": max_pages,
        "pages": len(raw_pages),
        "pagination_termination": pagination_termination,
        "pagination_complete": pagination_termination != "max_pages",
        "requested_start_reached": (
            start_ms is not None and previous_oldest is not None and previous_oldest <= start_ms
        ),
        "raw_rows": len(raw_rows),
        "parsed_rows": raw_observations,
        "duplicates_removed": duplicates_removed,
        "incomplete_rows_removed": incomplete_removed,
        "observations": len(candles),
        "start": candles.index[0].isoformat(),
        "end": candles.index[-1].isoformat(),
        "expected_step_seconds": expected_step_seconds,
        "missing_intervals": missing_intervals,
        "normalized_csv_sha256": _sha256(canonical_csv),
        "raw_pages_sha256": _sha256(canonical_raw),
        "limitations": [
            "OKX public candle data is exchange-specific and may be revised by the provider.",
            "The final unconfirmed candle is excluded.",
            "A close-price backtest does not model order-book depth or guaranteed fills.",
        ],
    }
    return OKXCandleSnapshot(candles=candles, raw_pages=tuple(raw_pages), metadata=metadata)


def _verified_snapshot_bytes(
    snapshot: OKXCandleSnapshot,
) -> tuple[bytes, bytes, bytes, str, str]:
    canonical_csv = _canonical_csv_bytes(snapshot.candles)
    canonical_raw = _canonical_json_bytes(snapshot.raw_pages)
    metadata = deepcopy(snapshot.metadata)
    canonical_metadata = _canonical_json_bytes(metadata)
    csv_sha256 = _sha256(canonical_csv)
    raw_sha256 = _sha256(canonical_raw)
    metadata_sha256 = _sha256(canonical_metadata)

    if csv_sha256 != snapshot._source_normalized_csv_sha256:
        raise ValueError("OKX snapshot candles changed after download")
    if raw_sha256 != snapshot._source_raw_pages_sha256:
        raise ValueError("OKX snapshot raw pages changed after download")
    if metadata_sha256 != snapshot._source_metadata_sha256:
        raise ValueError("OKX snapshot metadata changed after download")
    if metadata.get("normalized_csv_sha256") != csv_sha256:
        raise ValueError("OKX snapshot metadata normalized CSV hash does not match source bytes")
    if metadata.get("raw_pages_sha256") != raw_sha256:
        raise ValueError("OKX snapshot metadata raw-pages hash does not match source bytes")

    instrument = str(metadata["instrument_id"]).replace("/", "-")
    bar = str(metadata["bar"]).replace("/", "-")
    metadata_bytes = (
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()
    return canonical_csv, canonical_raw, metadata_bytes, instrument, bar


def write_okx_snapshot(
    snapshot: OKXCandleSnapshot,
    output_dir: str | Path,
) -> dict[str, Path]:
    """Persist normalized candles, raw responses, and provenance metadata."""

    canonical_csv, canonical_raw, metadata_bytes, instrument, bar = _verified_snapshot_bytes(
        snapshot
    )
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    stem = f"okx-{instrument}-{bar}"
    paths = {
        "candles": output / f"{stem}.csv",
        "raw": output / f"{stem}.raw.json",
        "metadata": output / f"{stem}.metadata.json",
    }
    paths["candles"].write_bytes(canonical_csv)
    paths["raw"].write_bytes(canonical_raw)
    paths["metadata"].write_bytes(metadata_bytes)
    return paths
