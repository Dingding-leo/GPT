#!/usr/bin/env python3
"""Complete bilateral archive/checksum and exact-grid audit for issue #936."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import time
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

START_MS = int(datetime(2021, 4, 1, tzinfo=timezone.utc).timestamp() * 1000)
END_MS = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
STEP_MS = 3_600_000
SYMBOLS = ("BTCUSDT", "ETHUSDT")
OUT = Path("evidence_vrp")
USER_AGENT = "Dingding-leo-GPT-research/vrp-source-audit-v1"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch_bytes(url: str, attempts: int = 4) -> bytes:
    last_error: Exception | None = None
    for attempt in range(attempts):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                return response.read()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(2**attempt)
    assert last_error is not None
    raise last_error


def months() -> list[str]:
    result: list[str] = []
    year, month = 2021, 4
    while (year, month) <= (2025, 12):
        result.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            month = 1
            year += 1
    return result


def normalize_timestamp(raw: str) -> int:
    value = int(raw)
    if value > 10**15:
        value //= 1000
    return value


def iso(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )


def audit_symbol(symbol: str) -> dict[str, Any]:
    base = "https://data.binance.vision/data/spot/monthly/klines"
    timestamps: list[int] = []
    objects: list[dict[str, Any]] = []
    for month in months():
        name = f"{symbol}-1h-{month}.zip"
        url = f"{base}/{symbol}/1h/{name}"
        checksum_url = url + ".CHECKSUM"
        checksum_payload = fetch_bytes(checksum_url)
        expected_hash = checksum_payload.decode("utf-8").strip().split()[0].lower()
        archive_payload = fetch_bytes(url)
        observed_hash = sha256_bytes(archive_payload)
        checksum_passed = observed_hash == expected_hash
        if not checksum_passed:
            raise ValueError(
                f"{symbol} {month} checksum mismatch {observed_hash} != {expected_hash}"
            )
        with zipfile.ZipFile(io.BytesIO(archive_payload)) as archive:
            members = archive.namelist()
            if len(members) != 1:
                raise ValueError(f"{symbol} {month} unexpected members {members}")
            rows = archive.read(members[0]).decode("utf-8").splitlines()
        month_timestamps: list[int] = []
        for line in rows:
            row = next(csv.reader([line]))
            if not row or not row[0].lstrip("-").isdigit():
                continue
            month_timestamps.append(normalize_timestamp(row[0]))
        timestamps.extend(month_timestamps)
        objects.append(
            {
                "month": month,
                "archive_url": url,
                "checksum_url": checksum_url,
                "archive_sha256": observed_hash,
                "checksum_payload_sha256": sha256_bytes(checksum_payload),
                "checksum_passed": checksum_passed,
                "archive_bytes": len(archive_payload),
                "member": members[0],
                "row_count": len(month_timestamps),
                "first_timestamp_ms": min(month_timestamps),
                "last_timestamp_ms": max(month_timestamps),
            }
        )

    expected = set(range(START_MS, END_MS, STEP_MS))
    observed = set(timestamps)
    missing = sorted(expected - observed)
    extra = sorted(observed - expected)
    duplicates = len(timestamps) - len(observed)
    exact_grid_passed = (
        timestamps == sorted(timestamps)
        and duplicates == 0
        and not missing
        and not extra
        and len(timestamps) == len(expected)
    )
    return {
        "symbol": symbol,
        "provider": "Binance public monthly SPOT kline archives",
        "interval": "1h",
        "requested_start": iso(START_MS),
        "requested_end_exclusive": iso(END_MS),
        "expected_rows": len(expected),
        "observed_rows": len(timestamps),
        "unique_rows": len(observed),
        "duplicates": duplicates,
        "missing_count": len(missing),
        "missing_timestamp_ms": missing,
        "missing_timestamp_utc": [iso(value) for value in missing],
        "extra_count": len(extra),
        "extra_timestamp_ms": extra,
        "extra_timestamp_utc": [iso(value) for value in extra],
        "strictly_ordered": timestamps == sorted(timestamps),
        "all_checksums_passed": all(item["checksum_passed"] for item in objects),
        "exact_grid_passed": exact_grid_passed,
        "objects": objects,
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "family_id": "causal-forward-realized-volatility-premium-opportunity-diagnostic-1h-v1",
        "repair_scope": (
            "evidence completeness only: audit both fixed target source arms and preserve "
            "all immutable archive/checksum identities plus every exact-grid gap"
        ),
        "strategy_changed": False,
        "source_provider_changed": False,
        "calendar_changed": False,
        "feature_changed": False,
        "oos_accessed": False,
        "arms": [],
    }
    try:
        result["arms"] = [audit_symbol(symbol) for symbol in SYMBOLS]
        result["bilateral_source_passed"] = all(
            arm["exact_grid_passed"] for arm in result["arms"]
        )
    except Exception as exc:  # noqa: BLE001
        result["audit_error"] = f"{type(exc).__name__}: {exc}"
        result["bilateral_source_passed"] = False

    path = OUT / "source_gap_audit.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    print(f"source gap audit sha256: {hashlib.sha256(path.read_bytes()).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
