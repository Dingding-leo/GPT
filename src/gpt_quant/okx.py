from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class OKXCandleSnapshot:
    """An immutable description of one paginated OKX public-data download."""

    candles: pd.DataFrame
    raw_pages: tuple[dict[str, Any], ...]
    metadata: dict[str, Any]

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


def parse_okx_candle_rows(rows: Sequence[Sequence[Any]]) -> pd.DataFrame:
    """Parse and strictly validate raw OKX candle rows."""

    normalized: list[list[Any]] = []
    for row_number, row in enumerate(rows, start=1):
        if not isinstance(row, Sequence) or isinstance(row, (str, bytes)):
            raise ValueError(f"OKX candle row {row_number} is not an array")
        if len(row) < len(_COLUMNS):
            raise ValueError(f"OKX candle row {row_number} has fewer than 9 fields")
        normalized.append(list(row[: len(_COLUMNS)]))

    if not normalized:
        return pd.DataFrame(columns=_COLUMNS[1:]).rename_axis("timestamp")

    frame = pd.DataFrame(normalized, columns=_COLUMNS)
    timestamp = pd.to_datetime(
        pd.to_numeric(frame.pop("ts"), errors="coerce"),
        unit="ms",
        utc=True,
        errors="coerce",
    )
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
    """

    if not inst_id or any(character.isspace() for character in inst_id):
        raise ValueError("inst_id must be a non-empty OKX instrument identifier")
    if not bar or any(character.isspace() for character in bar):
        raise ValueError("bar must be a non-empty OKX candle interval")
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
        raw_rows.extend(page_data)

        page_timestamps: list[int] = []
        for row in page_data:
            if not isinstance(row, Sequence) or isinstance(row, (str, bytes)) or not row:
                raise ValueError("OKX candle response contains a malformed row")
            try:
                page_timestamps.append(int(row[0]))
            except (TypeError, ValueError) as exc:
                raise ValueError("OKX candle response contains an invalid timestamp") from exc
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

    expected_step_seconds = None
    missing_intervals = None
    if len(candles) > 1:
        deltas = candles.index.to_series().diff().dropna().dt.total_seconds()
        mode = deltas.mode()
        if not mode.empty:
            expected_step_seconds = int(mode.iloc[0])
            if expected_step_seconds > 0:
                missing_intervals = int(
                    np.maximum(np.rint(deltas / expected_step_seconds).astype(int) - 1, 0).sum()
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


def write_okx_snapshot(
    snapshot: OKXCandleSnapshot,
    output_dir: str | Path,
) -> dict[str, Path]:
    """Persist normalized candles, raw responses, and provenance metadata."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    instrument = str(snapshot.metadata["instrument_id"]).replace("/", "-")
    bar = str(snapshot.metadata["bar"]).replace("/", "-")
    stem = f"okx-{instrument}-{bar}"
    paths = {
        "candles": output / f"{stem}.csv",
        "raw": output / f"{stem}.raw.json",
        "metadata": output / f"{stem}.metadata.json",
    }
    paths["candles"].write_bytes(_canonical_csv_bytes(snapshot.candles))
    paths["raw"].write_bytes(_canonical_json_bytes(snapshot.raw_pages))
    paths["metadata"].write_text(
        json.dumps(snapshot.metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return paths
