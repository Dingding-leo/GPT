#!/usr/bin/env python3
"""Audit the frozen OKX public 1H contract long/short account-ratio source."""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import quantiles
from typing import Any

FAMILY_ID = "causal-public-contract-long-short-account-ratio-source-contract-1h-v1"
ISSUE_NUMBER = 1125
ORIGIN = "https://www.okx.com"
PATH = "/api/v5/rubik/stat/contracts/long-short-account-ratio"
DOCS_URL = "https://www.okx.com/docs-v5/en/"
CHANGELOG_URL = "https://www.okx.com/docs-v5/log_en/"
PERIOD = "1H"
START = datetime(2026, 2, 9, 0, 0, tzinfo=UTC)
END = datetime(2026, 8, 7, 23, 0, tzinfo=UTC)
EXTENSION_END = datetime(2026, 8, 8, 0, 0, tzinfo=UTC)
EXPECTED_ROWS = 4320
CURRENCIES = ("BTC", "ETH")
CHUNK_HOURS = 96
REQUEST_PAUSE_SECONDS = 0.30
MAX_TOTAL_EVIDENCE_BYTES = 100 * 1024 * 1024
OUT = Path("reports/experiments") / FAMILY_ID
SOURCE = OUT / "source"

ACCEPT = (
    "accept_public_contract_long_short_account_ratio_1h_source_for_separate_"
    "training_predeclaration"
)
REJECT = "reject_causal_public_contract_long_short_account_ratio_source_contract_1h_v1"

OFFICIAL_SEMANTIC_SNAPSHOT = {
    "snapshot_date_utc": "2026-08-08",
    "docs_url": DOCS_URL,
    "changelog_url": CHANGELOG_URL,
    "current_docs_section": "Trading Statistics / Get contract long/short ratio",
    "changelog_added_date": "2024-06-13",
    "method": "GET",
    "origin": ORIGIN,
    "path": PATH,
    "frozen_object": "provider-defined contract long/short account-count ratio",
    "frozen_period": PERIOD,
    "frozen_parameters": ["ccy", "period", "begin", "end"],
    "retention_statement": None,
    "retention_decision_basis": (
        "fail closed on observed frozen-boundary coverage; no shorter-window rescue"
    ),
}

PERFORMANCE_NULLS = {
    "train_return": None,
    "train_sharpe": None,
    "oos_return": None,
    "oos_sharpe": None,
    "full_return": None,
    "full_sharpe": None,
    "benchmark_comparison": None,
    "turnover": None,
    "modeled_fee_drag": None,
    "max_drawdown": None,
    "edge_per_turnover": None,
    "fold_breadth": None,
    "year_breadth": None,
    "dependence_uncertainty": None,
    "execution_delay": None,
}


class SourceFailure(RuntimeError):
    """A frozen source gate failed."""


@dataclass(frozen=True)
class ResponseRecord:
    purpose: str
    currency: str
    request_url: str
    received_at_utc: str
    status: int
    headers: dict[str, str]
    raw: bytes
    response_file: str

    def manifest(self) -> dict[str, Any]:
        return {
            "purpose": self.purpose,
            "currency": self.currency,
            "request_url": self.request_url,
            "received_at_utc": self.received_at_utc,
            "status": self.status,
            "headers": self.headers,
            "response_file": self.response_file,
            "response_bytes": len(self.raw),
            "response_sha256": sha256_bytes(self.raw),
        }


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


def ms(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def iso_hour(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:00:00Z")


def expected_grid(start: datetime, end: datetime) -> tuple[int, ...]:
    hours = int((end - start).total_seconds() // 3600) + 1
    return tuple(ms(start + timedelta(hours=i)) for i in range(hours))


def request_url(currency: str, start: datetime, end: datetime) -> str:
    query = urllib.parse.urlencode(
        [
            ("ccy", currency),
            ("period", PERIOD),
            ("begin", str(ms(start))),
            ("end", str(ms(end))),
        ]
    )
    url = f"{ORIGIN}{PATH}?{query}"
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "www.okx.com" or parsed.path != PATH:
        raise ValueError(f"untrusted URL: {url}")
    names = [name for name, _ in urllib.parse.parse_qsl(parsed.query)]
    if names != ["ccy", "period", "begin", "end"]:
        raise ValueError(f"unexpected query ordering: {names}")
    if currency not in CURRENCIES:
        raise ValueError(f"unexpected currency: {currency}")
    return url


def persist_response(
    purpose: str,
    currency: str,
    url: str,
    status: int,
    headers: dict[str, str],
    raw: bytes,
) -> ResponseRecord:
    received = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    safe = purpose.replace("/", "-").replace(" ", "-")
    folder = SOURCE / currency
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{safe}.body"
    path.write_bytes(raw)
    meta = folder / f"{safe}.meta.json"
    record = ResponseRecord(
        purpose=purpose,
        currency=currency,
        request_url=url,
        received_at_utc=received,
        status=status,
        headers=headers,
        raw=raw,
        response_file=str(path.relative_to(OUT)),
    )
    meta.write_bytes(canonical_bytes(record.manifest()))
    return record


def fetch_json(purpose: str, currency: str, start: datetime, end: datetime) -> tuple[Any, ResponseRecord]:
    url = request_url(currency, start, end)
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "gpt-quant-source-audit/1.0",
        },
        method="GET",
    )
    status = 0
    headers: dict[str, str] = {}
    raw = b""
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            status = int(response.status)
            headers = {
                key.lower(): value
                for key, value in response.headers.items()
                if key.lower()
                in {
                    "content-type",
                    "date",
                    "server",
                    "cf-ray",
                    "x-ratelimit-limit",
                    "x-ratelimit-remaining",
                }
            }
            raw = response.read(2 * 1024 * 1024 + 1)
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        headers = {
            key.lower(): value
            for key, value in exc.headers.items()
            if key.lower() in {"content-type", "date", "server", "cf-ray"}
        }
        raw = exc.read(2 * 1024 * 1024 + 1)
    except urllib.error.URLError as exc:
        raw = str(exc).encode("utf-8", errors="replace")
        record = persist_response(purpose, currency, url, status, headers, raw)
        raise SourceFailure(f"transport failure for {currency} {purpose}: {exc}") from exc

    record = persist_response(purpose, currency, url, status, headers, raw)
    time.sleep(REQUEST_PAUSE_SECONDS)
    if status != 200:
        raise SourceFailure(
            f"HTTP {status} for {currency} {purpose}; response_sha256={sha256_bytes(raw)}"
        )
    if len(raw) > 2 * 1024 * 1024:
        raise SourceFailure(f"oversized response for {currency} {purpose}")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceFailure(f"invalid JSON for {currency} {purpose}") from exc
    if not isinstance(payload, dict):
        raise SourceFailure(f"non-object envelope for {currency} {purpose}")
    if str(payload.get("code")) != "0":
        raise SourceFailure(
            f"provider code={payload.get('code')!r} msg={payload.get('msg')!r} "
            f"for {currency} {purpose}"
        )
    if not isinstance(payload.get("data"), list):
        raise SourceFailure(f"missing data array for {currency} {purpose}")
    return payload, record


def parse_rows(payload: dict[str, Any], currency: str, purpose: str) -> list[tuple[int, float]]:
    parsed: list[tuple[int, float]] = []
    for index, row in enumerate(payload["data"]):
        if not isinstance(row, list) or len(row) < 2:
            raise SourceFailure(f"unexpected row schema for {currency} {purpose} row {index}")
        try:
            timestamp = int(row[0])
            ratio = float(row[1])
        except (TypeError, ValueError, OverflowError) as exc:
            raise SourceFailure(f"unparseable row for {currency} {purpose} row {index}") from exc
        if not math.isfinite(ratio) or ratio <= 0.0:
            raise SourceFailure(f"non-finite/non-positive ratio for {currency} {purpose}")
        parsed.append((timestamp, ratio))
    return parsed


def normalize_window(
    payload: dict[str, Any], currency: str, purpose: str, start: datetime, end: datetime
) -> tuple[tuple[int, float], ...]:
    rows = parse_rows(payload, currency, purpose)
    low, high = ms(start), ms(end)
    rows = [row for row in rows if low <= row[0] <= high]
    rows.sort(key=lambda row: row[0])
    timestamps = [row[0] for row in rows]
    if len(timestamps) != len(set(timestamps)):
        raise SourceFailure(f"duplicate timestamp in {currency} {purpose}")
    return tuple(rows)


def probe(currency: str, label: str, start: datetime, end: datetime) -> tuple[tuple[int, float], ..., dict[str, Any]]:
    payload, record = fetch_json(label, currency, start, end)
    rows = normalize_window(payload, currency, label, start, end)
    expected = expected_grid(start, end)
    observed = tuple(row[0] for row in rows)
    return (
        *rows,
    ), {
        "label": label,
        "requested_start": iso_hour(start),
        "requested_end": iso_hour(end),
        "expected_rows": len(expected),
        "observed_rows": len(rows),
        "exact_grid": observed == expected,
        "first_timestamp": iso_hour(datetime.fromtimestamp(observed[0] / 1000, UTC)) if observed else None,
        "last_timestamp": iso_hour(datetime.fromtimestamp(observed[-1] / 1000, UTC)) if observed else None,
        "request": record.manifest(),
    }


def acquire(currency: str, label: str, start: datetime, end: datetime) -> tuple[tuple[tuple[int, float], ...], list[dict[str, Any]]]:
    combined: dict[int, float] = {}
    requests: list[dict[str, Any]] = []
    cursor = start
    part = 0
    while cursor <= end:
        part += 1
        chunk_end = min(end, cursor + timedelta(hours=CHUNK_HOURS - 1))
        purpose = f"{label}-part-{part:03d}"
        payload, record = fetch_json(purpose, currency, cursor, chunk_end)
        rows = normalize_window(payload, currency, purpose, cursor, chunk_end)
        expected = expected_grid(cursor, chunk_end)
        if tuple(row[0] for row in rows) != expected:
            raise SourceFailure(
                f"incomplete observed retention/coverage for {currency} {purpose}: "
                f"expected={len(expected)} observed={len(rows)}"
            )
        for timestamp, ratio in rows:
            previous = combined.get(timestamp)
            if previous is not None and previous != ratio:
                raise SourceFailure(f"conflicting duplicate for {currency} at {timestamp}")
            combined[timestamp] = ratio
        requests.append(record.manifest())
        cursor = chunk_end + timedelta(hours=1)

    normalized = tuple(sorted(combined.items()))
    expected = expected_grid(start, end)
    if tuple(row[0] for row in normalized) != expected:
        raise SourceFailure(
            f"full calendar mismatch for {currency} {label}: "
            f"expected={len(expected)} observed={len(normalized)}"
        )
    return normalized, requests


def iqr(values: list[float]) -> float:
    if len(values) < 4:
        return 0.0
    quartiles = quantiles(values, n=4, method="inclusive")
    return float(quartiles[2] - quartiles[0])


def row_bytes(rows: tuple[tuple[int, float], ...]) -> bytes:
    return canonical_bytes([[timestamp, format(ratio, ".17g")] for timestamp, ratio in rows])


def arm_audit(currency: str) -> dict[str, Any]:
    latest_start = END - timedelta(hours=CHUNK_HOURS - 1)
    earliest_end = START + timedelta(hours=CHUNK_HOURS - 1)
    latest_rows, latest_probe = probe(currency, "latest-probe", latest_start, END)
    earliest_rows, earliest_probe = probe(currency, "earliest-probe", START, earliest_end)

    # The frozen 180-day source contract already fails if either boundary cannot be
    # supplied exactly. This is an observed-retention gate, not a shorter-window rescue.
    if not latest_probe["exact_grid"] or not earliest_probe["exact_grid"]:
        raise SourceFailure(
            f"observed retention/coverage cannot supply both frozen boundaries for {currency}: "
            f"earliest={earliest_probe['observed_rows']}/{earliest_probe['expected_rows']} "
            f"latest={latest_probe['observed_rows']}/{latest_probe['expected_rows']}"
        )

    primary, primary_requests = acquire(currency, "primary", START, END)
    repeat, repeat_requests = acquire(currency, "repeat", START, END)
    extension, extension_requests = acquire(currency, "extension", START, EXTENSION_END)

    primary_bytes = row_bytes(primary)
    repeat_bytes = row_bytes(repeat)
    prefix_bytes = row_bytes(extension[:EXPECTED_ROWS])
    values = [ratio for _, ratio in primary]
    distinct = len(set(values))
    ratio_iqr = iqr(values)
    gates = {
        "anonymous_public_https": True,
        "exact_provider_account_ratio_object": True,
        "direct_provider_1h": True,
        "exact_4320_hour_calendar": len(primary) == EXPECTED_ROWS,
        "strict_unique_on_grid_timestamps": tuple(row[0] for row in primary) == expected_grid(START, END),
        "finite_positive_variable_ratio": all(math.isfinite(v) and v > 0 for v in values) and distinct >= 100 and ratio_iqr > 0,
        "deterministic_complete_windowing": len(primary_requests) == EXPECTED_ROWS // CHUNK_HOURS,
        "sha256_evidence_bound": True,
        "repeat_normalization_identical": primary_bytes == repeat_bytes,
        "extension_prefix_identical": primary_bytes == prefix_bytes,
        "no_interpolation_resampling_stitching": True,
        "no_target_market_or_performance_access": True,
        "frozen_retention_window_complete": True,
    }
    return {
        "currency": currency,
        "source_gate_passed": all(gates.values()),
        "latest_probe": latest_probe,
        "earliest_probe": earliest_probe,
        "observed_rows": len(primary),
        "requested_start": iso_hour(START),
        "requested_end": iso_hour(END),
        "first_timestamp": iso_hour(datetime.fromtimestamp(primary[0][0] / 1000, UTC)),
        "last_timestamp": iso_hour(datetime.fromtimestamp(primary[-1][0] / 1000, UTC)),
        "ratio_distinct_count": distinct,
        "ratio_iqr": ratio_iqr,
        "normalized_sha256": sha256_bytes(primary_bytes),
        "repeat_normalized_sha256": sha256_bytes(repeat_bytes),
        "extension_prefix_sha256": sha256_bytes(prefix_bytes),
        "primary_request_count": len(primary_requests),
        "repeat_request_count": len(repeat_requests),
        "extension_request_count": len(extension_requests),
        "gates": gates,
    }


def evidence_bytes_on_disk() -> int:
    return sum(path.stat().st_size for path in OUT.rglob("*") if path.is_file())


def write_terminal(evidence: dict[str, Any]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    evidence_path = OUT / "evidence.json"
    evidence_path.write_bytes(canonical_bytes(evidence))
    (OUT / "evidence.sha256").write_text(sha256_file(evidence_path) + "\n", encoding="utf-8")

    lines = [
        f"# {FAMILY_ID}",
        "",
        f"- verdict: `{evidence['verdict']}`",
        f"- exact head: `{evidence['exact_head']}`",
        f"- source arms passing: `{evidence['source_arms_passing']}/2`",
        "- candidate / grid: `0 / 0`",
        "- performance accessed: `false`",
        "- target price/return accessed: `false`",
        "- OOS accessed: `false`",
        "",
        "The source-only contract either proves the complete frozen 4,320H direct-1H history "
        "bilaterally or rejects it without shortening the window. Strategy economics remain null.",
    ]
    if evidence.get("failure"):
        lines.extend(["", "## Terminal source failure", "", str(evidence["failure"])])
    report = OUT / "report.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (OUT / "report.sha256").write_text(sha256_file(report) + "\n", encoding="utf-8")

    manifest = {
        str(path.relative_to(OUT)): sha256_file(path)
        for path in sorted(OUT.rglob("*"))
        if path.is_file() and path.name not in {"artifact-manifest.json", "manifest.sha256"}
    }
    manifest_path = OUT / "artifact-manifest.json"
    manifest_path.write_bytes(canonical_bytes(manifest))
    (OUT / "manifest.sha256").write_text(sha256_file(manifest_path) + "\n", encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    SOURCE.mkdir(parents=True, exist_ok=True)
    exact_head = os.environ.get("GITHUB_SHA", "local-unbound")
    arms: list[dict[str, Any]] = []
    failure: dict[str, Any] | None = None

    for currency in CURRENCIES:
        try:
            arms.append(arm_audit(currency))
        except SourceFailure as exc:
            failure = {
                "currency": currency,
                "stage": "source_contract",
                "message": str(exc),
                "observed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            }
            break

    source_arms_passing = sum(bool(arm.get("source_gate_passed")) for arm in arms)
    calendars_identical = False
    if len(arms) == 2 and source_arms_passing == 2:
        calendars_identical = (
            arms[0]["observed_rows"] == arms[1]["observed_rows"] == EXPECTED_ROWS
            and arms[0]["first_timestamp"] == arms[1]["first_timestamp"]
            and arms[0]["last_timestamp"] == arms[1]["last_timestamp"]
        )
    passed = source_arms_passing == 2 and calendars_identical and failure is None

    evidence = {
        "family_id": FAMILY_ID,
        "issue_number": ISSUE_NUMBER,
        "base_main": "5a0fcc97d1a882f8223656c51f5bb8055f534e38",
        "exact_head": exact_head,
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "fixed_target_arms": ["BTC-USDT", "ETH-USDT"],
        "fixed_source_arms": list(CURRENCIES),
        "provider": "OKX Trading Statistics public REST",
        "endpoint": f"{ORIGIN}{PATH}",
        "period": PERIOD,
        "requested_start": iso_hour(START),
        "requested_end": iso_hour(END),
        "expected_rows_per_arm": EXPECTED_ROWS,
        "canonical_fee_bps_one_way": 5.0,
        "official_semantic_snapshot": OFFICIAL_SEMANTIC_SNAPSHOT,
        "public_data_only": True,
        "credentials_private_endpoints_accounts_orders_adapters_leverage_funds": False,
        "cross_sectional_or_relative_selection": False,
        "performance_accessed": False,
        "target_prices_or_returns_accessed": False,
        "oos_accessed": False,
        "canonical_strategy_changed": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "performance": PERFORMANCE_NULLS,
        "arms": arms,
        "source_arms_passing": source_arms_passing,
        "common_calendar_identical": calendars_identical,
        "source_contract_passed": passed,
        "failure": failure,
        "verdict": ACCEPT if passed else REJECT,
    }
    evidence["source_evidence_bytes_before_terminal_files"] = evidence_bytes_on_disk()
    write_terminal(evidence)
    total = evidence_bytes_on_disk()
    if total >= MAX_TOTAL_EVIDENCE_BYTES:
        raise RuntimeError(f"source evidence exceeds 100 MiB: {total}")
    print(
        json.dumps(
            {
                "exact_head": exact_head,
                "source_arms_passing": source_arms_passing,
                "source_contract_passed": passed,
                "performance_accessed": False,
                "oos_accessed": False,
                "verdict": evidence["verdict"],
                "evidence_sha256": sha256_file(OUT / "evidence.json"),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
