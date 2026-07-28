from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from gpt_quant.okx import OKXCandleSnapshot, fetch_okx_history_candles

BASE_URL = "https://www.okx.com"
QUAL_START = pd.Timestamp("2023-04-25T00:00:00Z")
QUAL_END = pd.Timestamp("2023-07-23T23:00:00Z")
EVAL_START = pd.Timestamp("2023-07-24T00:00:00Z")
EVAL_END = pd.Timestamp("2026-07-07T23:00:00Z")
LISTED_BEFORE = pd.Timestamp("2022-01-01T00:00:00Z")
LOOKBACK = 2160
FOLD_HOURS = 2160
FOLDS = 12
FEE_BPS = 5.0
ANNUALIZATION = 8760
LIQUIDITY_THRESHOLD = 10_000_000.0
BOOTSTRAP_BLOCK = 168
BOOTSTRAP_RESAMPLES = 5000
BOOTSTRAP_SEED = 20260728
STABLE_BASES = {"USDT", "USDC", "DAI", "TUSD", "USDP", "FDUSD", "EURT", "EUR", "USD"}

POLICY_SPEC = {
    "bar": "1H",
    "fee_bps_one_way": FEE_BPS,
    "initial_position": 0.0,
    "lookback_hours": LOOKBACK,
    "position_rule": "long iff close_t / close_t_minus_2160 - 1 > 0, else cash",
    "execution_delay_hours": 1,
    "position_set": [0.0, 1.0],
    "fold_boundary_reset": False,
}


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def write_json(path: Path, value: Any) -> str:
    payload = canonical_json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return sha256_bytes(payload)


def fetch_public_json(path: str, params: dict[str, str], timeout: float = 30.0) -> tuple[Any, bytes, str]:
    url = BASE_URL + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "GPT-independent-replication/1"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read(5_000_001)
    if not raw or len(raw) > 5_000_000:
        raise ValueError("public response is empty or exceeds the bounded byte limit")
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict) or value.get("code") != "0" or not isinstance(value.get("data"), list):
        raise ValueError(f"unexpected OKX public response from {path}")
    return value, raw, url



def fetch_bounded_one_hour_candles(
    *, inst_id: str, start: pd.Timestamp, end: pd.Timestamp, pause_seconds: float = 0.11
) -> OKXCandleSnapshot:
    """Fetch an exact bounded interval without traversing post-end history.

    The repository helper's page budget is correct only when the first API page is
    near the requested end. OKX otherwise begins at the latest candle, so a past
    bounded interval can exhaust the interval-sized budget before reaching start.
    This getter binds the initial cursor to one millisecond after the requested end.
    """

    raw_responses: list[bytes] = []
    first_request = True
    end_cursor = str(int(end.timestamp() * 1000) + 1)

    def getter(url: str, timeout: float) -> dict[str, Any]:
        nonlocal first_request
        parsed = urllib.parse.urlsplit(url)
        query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
        if first_request:
            if "after" in query:
                raise ValueError("first bounded request unexpectedly contains an after cursor")
            query["after"] = end_cursor
            first_request = False
        bounded_url = urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), parsed.fragment)
        )
        request = urllib.request.Request(
            bounded_url,
            headers={
                "Accept": "application/json",
                "User-Agent": "GPT-independent-replication/1",
            },
        )
        last_error: Exception | None = None
        for attempt in range(4):
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    raw = response.read(1_000_001)
                if not raw or len(raw) > 1_000_000:
                    raise ValueError("OKX candle response is empty or exceeds byte bound")
                payload = json.loads(raw.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("OKX candle response is not an object")
                raw_responses.append(raw)
                return payload
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt == 3:
                    raise
                import time

                time.sleep(0.5 * (2**attempt))
        raise RuntimeError("bounded OKX request failed") from last_error

    expected = int((end - start) / pd.Timedelta(hours=1)) + 1
    max_pages = math.ceil(expected / 100) + 2
    parsed_snapshot = fetch_okx_history_candles(
        inst_id=inst_id,
        bar="1H",
        start=start,
        end=end,
        base_url=BASE_URL,
        limit=100,
        max_pages=max_pages,
        pause_seconds=pause_seconds,
        timeout=30.0,
        get_json=getter,
    )
    if len(raw_responses) != len(parsed_snapshot.raw_pages):
        raise ValueError("bounded raw response count does not match parsed page count")
    evidence_pages = []
    for payload, raw in zip(parsed_snapshot.raw_pages, raw_responses, strict=True):
        evidence_pages.append(
            {
                "payload": payload,
                "raw_response_base64": base64.b64encode(raw).decode("ascii"),
                "raw_response_sha256": sha256_bytes(raw),
            }
        )
    metadata = dict(parsed_snapshot.metadata)
    metadata.update(
        {
            "bounded_initial_after_cursor": end_cursor,
            "source_transport": "trusted_okx_https_bounded_exact_bytes",
            "source_response_count": len(raw_responses),
            "source_response_sha256": [sha256_bytes(raw) for raw in raw_responses],
        }
    )
    return OKXCandleSnapshot(
        candles=parsed_snapshot.candles,
        raw_pages=tuple(evidence_pages),
        metadata=metadata,
    )

def normalize_snapshot_frame(candles: pd.DataFrame) -> pd.DataFrame:
    frame = candles.copy()
    frame.index = pd.DatetimeIndex(frame.index).tz_convert("UTC")
    frame.index.name = "timestamp"
    return frame.sort_index()


def persist_snapshot(root: Path, inst_id: str, label: str, snapshot: Any) -> dict[str, Any]:
    directory = root / "data" / inst_id / label
    directory.mkdir(parents=True, exist_ok=True)
    frame = normalize_snapshot_frame(snapshot.candles)
    csv_bytes = frame.reset_index().to_csv(index=False, lineterminator="\n").encode("utf-8")
    raw_bytes = canonical_json_bytes(list(snapshot.raw_pages))
    metadata_bytes = canonical_json_bytes(dict(snapshot.metadata))
    (directory / "candles.csv").write_bytes(csv_bytes)
    (directory / "raw-pages.json").write_bytes(raw_bytes)
    (directory / "metadata.json").write_bytes(metadata_bytes)
    return {
        "rows": int(len(frame)),
        "start": frame.index[0].isoformat(),
        "end": frame.index[-1].isoformat(),
        "candles_csv_sha256": sha256_bytes(csv_bytes),
        "raw_pages_sha256": sha256_bytes(raw_bytes),
        "metadata_sha256": sha256_bytes(metadata_bytes),
    }


def instrument_candidates(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: str(item.get("instId", ""))):
        inst_id = str(row.get("instId", ""))
        base = str(row.get("baseCcy", ""))
        quote = str(row.get("quoteCcy", ""))
        reason: str | None = None
        try:
            list_time = pd.Timestamp(int(str(row.get("listTime", "0"))), unit="ms", tz="UTC")
        except (TypeError, ValueError, OverflowError):
            list_time = pd.NaT
        if row.get("instType") != "SPOT":
            reason = "not_spot"
        elif row.get("state") != "live":
            reason = "not_live"
        elif quote != "USDT":
            reason = "not_usd