#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

BASE_URL = "https://www.okx.com"
BEGIN = pd.Timestamp("2026-06-28T10:00:00Z")
END = pd.Timestamp("2026-07-28T10:00:00Z")
MARKETS = {"BTC-USDT": "BTC", "ETH-USDT": "ETH"}


def canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def fetch(ccy: str) -> bytes:
    params = {
        "instType": "SPOT",
        "ccy": ccy,
        "period": "1H",
        "begin": str(int(BEGIN.timestamp() * 1000)),
        "end": str(int(END.timestamp() * 1000)),
    }
    url = f"{BASE_URL}/api/v5/rubik/stat/taker-volume?{urlencode(params)}"
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "gpt-quant-lab/0.2 (+https://github.com/Dingding-leo/GPT)",
        },
    )
    with urlopen(request, timeout=30.0) as response:  # noqa: S310
        return response.read()


def inspect(raw: bytes) -> dict[str, object]:
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, Mapping) or payload.get("code") != "0":
        raise ValueError(f"unexpected OKX payload: {payload!r}")
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise ValueError("OKX data must be an array")
    timestamps: list[pd.Timestamp] = []
    for number, row in enumerate(rows, start=1):
        if not isinstance(row, Sequence) or isinstance(row, (str, bytes)) or len(row) != 3:
            raise ValueError(f"row {number} must be [ts, sellVol, buyVol]")
        timestamp_raw = row[0]
        if not isinstance(timestamp_raw, str) or not timestamp_raw.isdecimal():
            raise ValueError(f"row {number} timestamp is invalid")
        timestamps.append(pd.to_datetime(int(timestamp_raw), unit="ms", utc=True))
    index = pd.DatetimeIndex(sorted(timestamps))
    expected = pd.date_range(BEGIN, END - pd.Timedelta(hours=1), freq="1h")
    in_window = index[(index >= BEGIN) & (index < END)]
    missing = expected.difference(in_window)
    extra = index.difference(expected)
    gaps = 0
    if len(index) > 1:
        gaps = int(((index[1:] - index[:-1]) != pd.Timedelta(hours=1)).sum())
    return {
        "response_rows": len(index),
        "in_window_rows": len(in_window),
        "expected_rows": len(expected),
        "minimum_timestamp": index[0].isoformat() if len(index) else None,
        "maximum_timestamp": index[-1].isoformat() if len(index) else None,
        "duplicate_timestamps": int(index.duplicated().sum()),
        "non_hourly_gaps": gaps,
        "missing_expected_hours": [value.isoformat() for value in missing],
        "extra_hours": [value.isoformat() for value in extra],
        "raw_response_sha256": digest(raw),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    markets: dict[str, object] = {}
    for instrument, ccy in MARKETS.items():
        raw = fetch(ccy)
        (args.output_dir / f"{instrument}-taker-volume.raw.json").write_bytes(raw)
        markets[instrument] = inspect(raw)
    result = {
        "family_id": "okx-aggregate-spot-taker-flow-resilience-v1",
        "issue": 566,
        "source_head_sha": "fda3c8cc5fe8c1902ce7fbaf3fe51edd5c337791",
        "window": {"begin": BEGIN.isoformat(), "end_exclusive": END.isoformat()},
        "candidate_count": 2,
        "candidate_market_evaluations_planned": 4,
        "candidate_market_evaluations_executed": 0,
        "fee_one_way_bps": 5.0,
        "markets": markets,
        "performance_inspected": False,
        "strategy_metrics": None,
        "bootstrap": None,
        "dsr": None,
        "pbo": None,
        "untouched_archive_consumed": False,
        "source_failure": "predeclared_exact_720h_grid_unavailable",
        "verdict": "aggregate_taker_flow_family_rejected_exact_window",
    }
    output = canonical_json(result)
    (args.output_dir / "result-summary.json").write_bytes(output)
    (args.output_dir / "result-summary.sha256").write_text(
        f"{digest(output)}  result-summary.json\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
