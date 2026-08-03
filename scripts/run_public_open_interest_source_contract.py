#!/usr/bin/env python3
"""Prove the frozen Binance public bilateral 1H open-interest source contract."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

FAMILY_ID = "causal-public-open-interest-state-source-contract-1h-v1"
ISSUE_NUMBER = 1037
ORIGIN = "https://fapi.binance.com"
PATH = "/futures/data/openInterestHist"
DOCS_URL = (
    "https://developers.binance.com/en/docs/catalog/"
    "core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data"
    "#open-interest-statistics"
)
PERIOD = "1h"
START = datetime(2026, 7, 4, 0, 0, tzinfo=UTC)
END = datetime(2026, 8, 2, 23, 0, tzinfo=UTC)
EXTENSION_END = datetime(2026, 8, 3, 0, 0, tzinfo=UTC)
EXPECTED_ROWS = 720
SYMBOLS = ("BTCUSDT", "ETHUSDT")
MAX_ROWS_PER_REQUEST = 500
MAX_TOTAL_EVIDENCE_BYTES = 100 * 1024 * 1024
OUT = Path("reports/experiments") / FAMILY_ID
SOURCE = OUT / "source"

OFFICIAL_SEMANTICS = {
    "docs_url": DOCS_URL,
    "origin": ORIGIN,
    "path": PATH,
    "method": "GET",
    "request_weight": 0,
    "required_parameters": ["symbol", "period"],
    "supported_period_bound": PERIOD,
    "maximum_limit": MAX_ROWS_PER_REQUEST,
    "retention_statement": "Only the data of the latest 1 month is available.",
    "timestamp_semantics": "End time of the period, in milliseconds.",
    "required_response_fields": [
        "symbol",
        "sumOpenInterest",
        "sumOpenInterestValue",
        "timestamp",
    ],
    "optional_response_fields": ["CMCCirculatingSupply"],
}


class SourceContractError(RuntimeError):
    """The frozen source contract failed."""


class TransportError(SourceContractError):
    """The public endpoint could not be acquired after bounded retries."""


@dataclass(frozen=True)
class ResponseRecord:
    """One exact public response and its provenance."""

    purpose: str
    request_url: str
    received_at_utc: str
    status: int
    headers: dict[str, str]
    raw: bytes
    response_file: str

    def manifest(self) -> dict[str, Any]:
        return {
            "purpose": self.purpose,
            "request_url": self.request_url,
            "received_at_utc": self.received_at_utc,
            "status": self.status,
            "headers": self.headers,
            "response_file": self.response_file,
            "response_bytes": len(self.raw),
            "response_sha256": sha256_bytes(self.raw),
        }


@dataclass(frozen=True)
class Acquisition:
    """One complete normalized source acquisition."""

    symbol: str
    label: str
    end: datetime
    rows: tuple[dict[str, Any], ...]
    normalized: bytes
    requests: tuple[dict[str, Any], ...]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("utf-8")


def iso_hour(value: datetime) -> str:
    if value.tzinfo != UTC or value.minute or value.second or value.microsecond:
        raise ValueError("timestamp must be an exact UTC hour")
    return value.strftime("%Y-%m-%dT%H:00:00Z")


def ms(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def validate_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "fapi.binance.com"
        or parsed.path != PATH
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise SourceContractError(f"untrusted Binance URL: {url}")
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    names = [name for name, _ in query]
    if names != ["symbol", "period", "startTime", "endTime", "limit"]:
        raise SourceContractError(f"unexpected or unordered query fields: {names}")
    forbidden = {"signature", "timestamp", "recvWindow", "apiKey", "api_key", "token"}
    if forbidden.intersection(names):
        raise SourceContractError("credential-bearing query parameter detected")


def request_url(symbol: str, start: datetime, end: datetime) -> str:
    query = urllib.parse.urlencode(
        [
            ("symbol", symbol),
            ("period", PERIOD),
            ("startTime", str(ms(start))),
            ("endTime", str(ms(end))),
            ("limit", str(MAX_ROWS_PER_REQUEST)),
        ]
    )
    url = f"{ORIGIN}{PATH}?{query}"
    validate_url(url)
    return url


def fetch(url: str, *, purpose: str, directory: Path, attempts: int = 5) -> ResponseRecord:
    validate_url(url)
    directory.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(attempts):
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Accept": "application/json",
                "User-Agent": "causal-public-1h-source-audit/1.0",
            },
        )
        received = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        try:
            with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
                if response.geturl() != url:
                    raise SourceContractError(
                        f"redirect rejected: {url} -> {response.geturl()}"
                    )
                raw = response.read(20_000_001)
                if not raw or len(raw) > 20_000_000:
                    raise TransportError("empty or oversized Binance response")
                path = directory / f"response-attempt-{attempt + 1}.json"
                path.write_bytes(raw)
                headers = {
                    str(name).lower(): str(value)
                    for name, value in sorted(response.headers.items())
                }
                record = ResponseRecord(
                    purpose=purpose,
                    request_url=url,
                    received_at_utc=received,
                    status=response.status,
                    headers=headers,
                    raw=raw,
                    response_file=str(path),
                )
                metadata_path = directory / f"response-attempt-{attempt + 1}.meta.json"
                metadata_path.write_bytes(canonical_bytes(record.manifest()))
                return record
        except urllib.error.HTTPError as exc:
            raw = exc.read(2_000_000)
            path = directory / f"http-{exc.code}-attempt-{attempt + 1}.bin"
            path.write_bytes(raw)
            headers = {
                str(name).lower(): str(value)
                for name, value in sorted(exc.headers.items())
            }
            error_metadata = {
                "purpose": purpose,
                "request_url": url,
                "received_at_utc": received,
                "status": exc.code,
                "headers": headers,
                "response_file": str(path),
                "response_bytes": len(raw),
                "response_sha256": sha256_bytes(raw),
            }
            (directory / f"http-{exc.code}-attempt-{attempt + 1}.meta.json").write_bytes(
                canonical_bytes(error_metadata)
            )
            if exc.code not in {408, 425, 429, 500, 502, 503, 504}:
                raise SourceContractError(
                    f"provider rejected {purpose} with HTTP {exc.code}; "
                    f"body_sha256={sha256_bytes(raw)} headers={headers}"
                ) from exc
            last_error = TransportError(
                f"transient HTTP {exc.code}; body_sha256={sha256_bytes(raw)}"
            )
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
        if attempt + 1 < attempts:
            time.sleep(min(2**attempt, 8))
    raise TransportError(f"{purpose} failed after {attempts} attempts: {last_error}")


def reject_duplicate_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SourceContractError(f"duplicate JSON field {key!r}")
        result[key] = value
    return result


def parse_payload(raw: bytes, *, purpose: str) -> list[dict[str, Any]]:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicate_fields)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceContractError(f"{purpose}: invalid UTF-8 JSON") from exc
    if not isinstance(value, list):
        raise SourceContractError(f"{purpose}: top-level response must be an array")
    if not value:
        raise SourceContractError(f"{purpose}: empty response array")
    if not all(isinstance(row, dict) for row in value):
        raise SourceContractError(f"{purpose}: every row must be an object")
    return value


def canonical_decimal(value: Any, *, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise SourceContractError(f"{context}: expected a non-empty decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise SourceContractError(f"{context}: invalid decimal {value!r}") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise SourceContractError(f"{context}: value must be finite and strictly positive")
    normalized = format(parsed, "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized


def normalize_row(row: dict[str, Any], *, symbol: str, context: str) -> dict[str, Any]:
    required = {"symbol", "sumOpenInterest", "sumOpenInterestValue", "timestamp"}
    allowed = required | {"CMCCirculatingSupply"}
    if not required.issubset(row) or not set(row).issubset(allowed):
        raise SourceContractError(f"{context}: row schema mismatch {sorted(row)}")
    if row["symbol"] != symbol:
        raise SourceContractError(f"{context}: unexpected symbol {row['symbol']!r}")
    timestamp = row["timestamp"]
    if not isinstance(timestamp, int) or isinstance(timestamp, bool):
        raise SourceContractError(f"{context}: timestamp must be integer milliseconds")
    if timestamp % 3_600_000:
        raise SourceContractError(f"{context}: timestamp is off the exact 1H grid")
    result = {
        "symbol": symbol,
        "sumOpenInterest": canonical_decimal(
            row["sumOpenInterest"], context=f"{context} sumOpenInterest"
        ),
        "sumOpenInterestValue": canonical_decimal(
            row["sumOpenInterestValue"], context=f"{context} sumOpenInterestValue"
        ),
        "timestamp": timestamp,
    }
    supply = row.get("CMCCirculatingSupply")
    if supply is not None:
        result["CMCCirculatingSupply"] = canonical_decimal(
            supply, context=f"{context} CMCCirculatingSupply"
        )
    return result


def expected_grid(end: datetime) -> tuple[int, ...]:
    count = int((end - START).total_seconds() // 3600) + 1
    return tuple(ms(START + timedelta(hours=index)) for index in range(count))


def frozen_windows(end: datetime) -> tuple[tuple[datetime, datetime], ...]:
    grid = expected_grid(end)
    windows: list[tuple[datetime, datetime]] = []
    for offset in range(0, len(grid), MAX_ROWS_PER_REQUEST):
        final = min(offset + MAX_ROWS_PER_REQUEST - 1, len(grid) - 1)
        windows.append(
            (
                datetime.fromtimestamp(grid[offset] / 1000, tz=UTC),
                datetime.fromtimestamp(grid[final] / 1000, tz=UTC),
            )
        )
    return tuple(windows)


def acquire(symbol: str, *, label: str, end: datetime) -> Acquisition:
    rows_by_time: dict[int, dict[str, Any]] = {}
    request_records: list[dict[str, Any]] = []
    directory = SOURCE / symbol / label
    for page, (window_start, window_end) in enumerate(frozen_windows(end), 1):
        purpose = f"{symbol} {label} page {page}"
        record = fetch(
            request_url(symbol, window_start, window_end),
            purpose=purpose,
            directory=directory / f"page-{page:02d}",
        )
        payload = parse_payload(record.raw, purpose=purpose)
        request_records.append({**record.manifest(), "response_rows": len(payload)})
        previous: int | None = None
        for row_number, row in enumerate(payload, 1):
            normalized = normalize_row(
                row,
                symbol=symbol,
                context=f"{purpose} row {row_number}",
            )
            timestamp = normalized["timestamp"]
            if previous is not None and timestamp <= previous:
                raise SourceContractError(f"{purpose}: response is not strictly ascending")
            previous = timestamp
            if not ms(window_start) <= timestamp <= ms(window_end):
                raise SourceContractError(f"{purpose}: response row outside requested window")
            if timestamp in rows_by_time:
                raise SourceContractError(f"{purpose}: duplicate timestamp across pages")
            rows_by_time[timestamp] = normalized
    grid = expected_grid(end)
    observed = tuple(sorted(rows_by_time))
    if observed != grid:
        missing = [timestamp for timestamp in grid if timestamp not in rows_by_time]
        extras = [timestamp for timestamp in observed if timestamp not in set(grid)]
        first_missing = (
            datetime.fromtimestamp(missing[0] / 1000, tz=UTC).isoformat()
            if missing
            else None
        )
        raise SourceContractError(
            f"{symbol} {label}: exact-grid failure observed={len(observed)} "
            f"expected={len(grid)} missing={len(missing)} first_missing={first_missing} "
            f"extras={len(extras)}"
        )
    rows = tuple(rows_by_time[timestamp] for timestamp in grid)
    normalized = b"".join(canonical_bytes(row) for row in rows)
    normalized_path = directory / "normalized.jsonl"
    normalized_path.parent.mkdir(parents=True, exist_ok=True)
    normalized_path.write_bytes(normalized)
    return Acquisition(
        symbol=symbol,
        label=label,
        end=end,
        rows=rows,
        normalized=normalized,
        requests=tuple(request_records),
    )


def percentile(values: list[Decimal], fraction: Decimal) -> Decimal:
    if not values:
        raise ValueError("empty percentile input")
    ordered = sorted(values)
    position = fraction * Decimal(len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - Decimal(lower)
    return ordered[lower] * (Decimal(1) - weight) + ordered[upper] * weight


def arm_record(
    symbol: str,
    primary: Acquisition,
    repeat: Acquisition,
    extension: Acquisition,
) -> dict[str, Any]:
    if len(primary.rows) != EXPECTED_ROWS:
        raise SourceContractError(f"{symbol}: primary row count mismatch")
    if primary.normalized != repeat.normalized:
        raise SourceContractError(f"{symbol}: independent repeat normalization differs")
    extension_prefix = extension.rows[:EXPECTED_ROWS]
    if extension_prefix != primary.rows:
        raise SourceContractError(f"{symbol}: later-hour request changed frozen prefix")
    oi_values = [Decimal(row["sumOpenInterest"]) for row in primary.rows]
    value_values = [Decimal(row["sumOpenInterestValue"]) for row in primary.rows]
    distinct = len(set(oi_values))
    q1 = percentile(oi_values, Decimal("0.25"))
    q3 = percentile(oi_values, Decimal("0.75"))
    iqr = q3 - q1
    if distinct < 100 or iqr <= 0:
        raise SourceContractError(
            f"{symbol}: insufficient variation distinct={distinct} iqr={iqr}"
        )
    return {
        "symbol": symbol,
        "requested_start": iso_hour(START),
        "requested_end": iso_hour(END),
        "observed_rows": len(primary.rows),
        "observed_start_timestamp": primary.rows[0]["timestamp"],
        "observed_end_timestamp": primary.rows[-1]["timestamp"],
        "gap_count": 0,
        "duplicate_count": 0,
        "sum_open_interest_minimum": format(min(oi_values), "f"),
        "sum_open_interest_maximum": format(max(oi_values), "f"),
        "sum_open_interest_distinct": distinct,
        "sum_open_interest_iqr": format(iqr, "f"),
        "sum_open_interest_value_minimum": format(min(value_values), "f"),
        "sum_open_interest_value_maximum": format(max(value_values), "f"),
        "calendar_sha256": sha256_bytes(
            canonical_bytes([row["timestamp"] for row in primary.rows])
        ),
        "primary_dataset_sha256": sha256_bytes(primary.normalized),
        "repeat_dataset_sha256": sha256_bytes(repeat.normalized),
        "extension_prefix_sha256": sha256_bytes(
            b"".join(canonical_bytes(row) for row in extension_prefix)
        ),
        "primary_requests": primary.requests,
        "repeat_requests": repeat.requests,
        "extension_requests": extension.requests,
        "repeat_normalization_identical": True,
        "extension_prefix_identical": True,
        "source_gate_passed": True,
    }


def null_performance() -> dict[str, Any]:
    return {
        "training_return": None,
        "training_sharpe": None,
        "oos_return": None,
        "oos_sharpe": None,
        "full_return": None,
        "full_sharpe": None,
        "benchmark_comparison": None,
        "turnover": None,
        "fee_drag": None,
        "maximum_drawdown": None,
        "edge_per_turnover": None,
        "fold_breadth": None,
        "year_breadth": None,
        "uncertainty": None,
        "execution_delay": None,
    }


def total_source_bytes() -> int:
    return sum(path.stat().st_size for path in SOURCE.rglob("*") if path.is_file())


def report_text(evidence: dict[str, Any]) -> str:
    lines = [
        "# Public bilateral 1H open-interest source contract",
        "",
        "```text",
        f"Family                 {evidence['family_id']}",
        f"Exact evidence head    {evidence['exact_head']}",
        f"Fixed source arms      {' / '.join(evidence['fixed_source_arms'])}",
        f"Candidate/grid         {evidence['candidate_count']}/{evidence['parameter_grid_count']}",
        f"Source arms passing    {evidence['source_arms_passing']}/2",
        f"Performance accessed   {str(evidence['performance_accessed']).lower()}",
        f"OOS accessed           {str(evidence['oos_accessed']).lower()}",
        f"Verdict                {evidence['verdict']}",
        "```",
        "",
        "## Source result",
        "",
    ]
    if evidence["source_contract_passed"]:
        lines.extend(
            [
                "| Symbol | Rows | Distinct OI | IQR | Dataset SHA-256 | Repeat | Prefix |",
                "|---|---:|---:|---:|---|---:|---:|",
            ]
        )
        for arm in evidence["arms"]:
            lines.append(
                "| {symbol} | {rows} | {distinct} | {iqr} | `{sha}` | pass | pass |".format(
                    symbol=arm["symbol"],
                    rows=arm["observed_rows"],
                    distinct=arm["sum_open_interest_distinct"],
                    iqr=arm["sum_open_interest_iqr"],
                    sha=arm["primary_dataset_sha256"],
                )
            )
        lines.extend(
            [
                "",
                "Both anonymous public source arms passed the exact 720-hour calendar, "
                "schema, positivity, variation, repeat-acquisition, common-calendar and "
                "one-later-hour prefix-invariance gates.",
            ]
        )
    else:
        failure = evidence.get("failure") or {}
        lines.extend(
            [
                "The frozen source contract failed closed before any target-price, return, "
                "feature, opportunity or OOS access.",
                "",
                f"Failure stage: `{failure.get('stage', 'unknown')}`",
                "",
                f"Failure: `{failure.get('message', 'unspecified')}`",
            ]
        )
    lines.extend(
        [
            "",
            "## Strategy-performance accounting",
            "",
            "No transformation, economic sign, threshold, selector, sizing rule or position "
            "path was defined. Train, OOS, full, benchmark, turnover, drawdown, breadth, "
            "uncertainty and delay metrics are null rather than zero. Exactly 5 bps one way "
            "remains bound only to a separately preregistered executable experiment.",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(evidence: dict[str, Any]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    evidence_path = OUT / "evidence.json"
    report_path = OUT / "report.md"
    evidence_path.write_bytes(canonical_bytes(evidence))
    report_path.write_text(report_text(evidence), encoding="utf-8")
    (OUT / "evidence.sha256").write_text(
        f"{sha256_file(evidence_path)}\n", encoding="utf-8"
    )
    (OUT / "report.sha256").write_text(
        f"{sha256_file(report_path)}\n", encoding="utf-8"
    )
    files = []
    for path in sorted(OUT.rglob("*")):
        if path.is_file() and path.name not in {"artifact-manifest.json", "manifest.sha256"}:
            files.append(
                {
                    "path": str(path.relative_to(OUT)),
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    manifest_path = OUT / "artifact-manifest.json"
    manifest_path.write_bytes(canonical_bytes({"family_id": FAMILY_ID, "files": files}))
    (OUT / "manifest.sha256").write_text(
        f"{sha256_file(manifest_path)}\n", encoding="utf-8"
    )


def run() -> dict[str, Any]:
    exact_head = os.environ.get("GITHUB_SHA", "").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", exact_head):
        raise RuntimeError("GITHUB_SHA must bind evidence to an exact 40-character head")
    semantics_sha = sha256_bytes(canonical_bytes(OFFICIAL_SEMANTICS))
    base = {
        "family_id": FAMILY_ID,
        "issue_number": ISSUE_NUMBER,
        "exact_head": exact_head,
        "classification": "zero-candidate source-contract-first information experiment",
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "fixed_source_arms": list(SYMBOLS),
        "future_target_mapping": {
            "BTCUSDT": "BTC-USDT future unlevered long/cash",
            "ETHUSDT": "ETH-USDT future unlevered long/cash",
        },
        "provider": "Binance USD-M Futures public market data",
        "endpoint": f"{ORIGIN}{PATH}",
        "period": PERIOD,
        "frozen_start": iso_hour(START),
        "frozen_end": iso_hour(END),
        "expected_rows_per_arm": EXPECTED_ROWS,
        "official_semantics": OFFICIAL_SEMANTICS,
        "official_semantics_sha256": semantics_sha,
        "canonical_fee_bps_one_way": 5.0,
        "public_data_only": True,
        "credentials_private_endpoints_accounts_orders_adapters_leverage_funds": False,
        "cross_sectional_or_relative_selection": False,
        "performance_accessed": False,
        "target_prices_or_returns_accessed": False,
        "oos_accessed": False,
        "canonical_strategy_changed": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "performance": null_performance(),
    }
    arms: list[dict[str, Any]] = []
    stage = "preflight"
    try:
        if len(expected_grid(END)) != EXPECTED_ROWS:
            raise SourceContractError("frozen calendar does not contain exactly 720 hours")
        if len(frozen_windows(END)) != 2:
            raise SourceContractError("frozen 720-hour calendar must use exactly two pages")
        for symbol in SYMBOLS:
            stage = f"{symbol}_primary"
            primary = acquire(symbol, label="primary", end=END)
            time.sleep(0.5)
            stage = f"{symbol}_repeat"
            repeat = acquire(symbol, label="repeat", end=END)
            time.sleep(0.5)
            stage = f"{symbol}_extension"
            extension = acquire(symbol, label="extension", end=EXTENSION_END)
            stage = f"{symbol}_validation"
            arms.append(arm_record(symbol, primary, repeat, extension))
        if arms[0]["calendar_sha256"] != arms[1]["calendar_sha256"]:
            raise SourceContractError("source arms do not share an identical calendar")
        source_bytes = total_source_bytes()
        if source_bytes >= MAX_TOTAL_EVIDENCE_BYTES:
            raise SourceContractError(
                f"exact-response evidence exceeds 100 MiB: {source_bytes} bytes"
            )
        evidence = {
            **base,
            "arms": arms,
            "source_arms_passing": 2,
            "common_calendar_identical": True,
            "source_evidence_bytes": source_bytes,
            "source_contract_passed": True,
            "failure": None,
            "verdict": (
                "accept_public_bilateral_open_interest_1h_source_for_separate_"
                "training_predeclaration"
            ),
        }
    except SourceContractError as exc:
        source_bytes = total_source_bytes() if SOURCE.exists() else 0
        evidence = {
            **base,
            "arms": arms,
            "source_arms_passing": len(arms),
            "common_calendar_identical": False,
            "source_evidence_bytes": source_bytes,
            "source_contract_passed": False,
            "failure": {"stage": stage, "kind": type(exc).__name__, "message": str(exc)},
            "verdict": "reject_causal_public_open_interest_state_source_contract_1h_v1",
        }
    write_outputs(evidence)
    return evidence


def main() -> None:
    result = run()
    print(
        json.dumps(
            {
                "family_id": result["family_id"],
                "exact_head": result["exact_head"],
                "source_arms_passing": result["source_arms_passing"],
                "source_contract_passed": result["source_contract_passed"],
                "performance_accessed": result["performance_accessed"],
                "oos_accessed": result["oos_accessed"],
                "verdict": result["verdict"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
