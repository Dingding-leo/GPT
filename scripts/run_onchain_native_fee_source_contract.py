#!/usr/bin/env python3
"""Prove the frozen public Coin Metrics FeeTotNtv 1H source contract for issue #1030."""
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

FAMILY_ID = "causal-onchain-native-fee-pressure-source-contract-1h-v1"
ISSUE_NUMBER = 1030
CM_ORIGIN = "https://community-api.coinmetrics.io"
REFERENCE_PATH = "/v4/reference-data/asset-metrics"
CATALOG_PATH = "/v4/catalog-all-v2/asset-metrics"
SERIES_PATH = "/v4/timeseries/asset-metrics"
METRIC = "FeeTotNtv"
FREQUENCY = "1h"
START = datetime(2023, 4, 1, 0, 0, tzinfo=UTC)
END = datetime(2025, 12, 31, 23, 0, tzinfo=UTC)
SUFFIX_END = datetime(2026, 1, 31, 23, 0, tzinfo=UTC)
EXPECTED_ROWS = 24_144
ASSETS = (("btc", "BTC-USDT"), ("eth", "ETH-USDT"))
PAGE_SIZE = 10_000
MAX_PAGES = 20
OUT = Path("reports/experiments") / FAMILY_ID
SOURCE = OUT / "source"
_TIME_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})T(?P<hour>\d{2}):00:00"
    r"(?:\.0{1,9})?Z$"
)


class SourceContractError(RuntimeError):
    """The frozen provider/source contract failed."""


class TransportError(RuntimeError):
    """The public request failed after bounded retries."""


@dataclass(frozen=True)
class ProviderRejection(SourceContractError):
    """The provider returned a non-transient HTTP response."""

    status: int
    url: str
    body: bytes

    def __str__(self) -> str:
        return (
            f"provider rejected fixed request with HTTP {self.status}: {self.url}; "
            f"body_sha256={sha256_bytes(self.body)}"
        )


@dataclass(frozen=True)
class Acquisition:
    asset: str
    label: str
    requested_end: datetime
    rows: tuple[tuple[str, str], ...]
    normalized_bytes: bytes
    manifest: tuple[dict[str, Any], ...]
    exact_duplicate_count: int
    conflicting_duplicate_count: int


def iso_hour(value: datetime) -> str:
    if value.tzinfo != UTC or value.minute or value.second or value.microsecond:
        raise ValueError("timestamp must be an exact UTC hour")
    return value.strftime("%Y-%m-%dT%H:00:00Z")


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def reject_duplicate_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SourceContractError(f"duplicate JSON field {key!r}")
        result[key] = value
    return result


def parse_json(raw: bytes, *, context: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicate_fields)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceContractError(f"{context}: invalid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise SourceContractError(f"{context}: top-level JSON must be an object")
    return value


def validate_url(url: str, *, path: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "community-api.coinmetrics.io"
        or parsed.path != path
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise SourceContractError(f"untrusted Coin Metrics URL: {url}")
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    forbidden = {"api_key", "apikey", "key", "token", "access_token", "cookie"}
    if forbidden.intersection(name.lower() for name, _ in query):
        raise SourceContractError(f"credential parameter present in Coin Metrics URL: {url}")


def fetch(url: str, *, byte_limit: int, attempts: int = 6) -> bytes:
    last_error: Exception | None = None
    for attempt in range(attempts):
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "causal-1h-source-contract-research/1.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:  # noqa: S310
                if response.status != 200:
                    raise TransportError(f"unexpected HTTP {response.status} for {url}")
                if response.geturl() != url:
                    raise SourceContractError(
                        f"redirect rejected for Coin Metrics request: {url} -> {response.geturl()}"
                    )
                raw = response.read(byte_limit + 1)
                if not raw or len(raw) > byte_limit:
                    raise TransportError(f"empty or oversized response for {url}")
                return raw
        except urllib.error.HTTPError as exc:
            body = exc.read(min(byte_limit, 1_000_000))
            if exc.code in {408, 425, 429, 500, 502, 503, 504}:
                last_error = TransportError(
                    f"transient HTTP {exc.code} for {url}; body_sha256={sha256_bytes(body)}"
                )
            else:
                raise ProviderRejection(status=exc.code, url=url, body=body) from exc
        except (urllib.error.URLError, TimeoutError, TransportError) as exc:
            last_error = exc
        if attempt + 1 < attempts:
            time.sleep(min(2**attempt, 12))
    raise TransportError(f"request failed after {attempts} attempts: {url}: {last_error}")


def request_page(
    *,
    url: str,
    path: str,
    directory: Path,
    filename: str,
    purpose: str,
    page: int | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    validate_url(url, path=path)
    raw = fetch(url, byte_limit=25_000_000)
    directory.mkdir(parents=True, exist_ok=True)
    response_path = directory / filename
    response_path.write_bytes(raw)
    record = {
        "purpose": purpose,
        "page": page,
        "request_url": url,
        "response_file": str(response_path),
        "response_bytes": len(raw),
        "response_sha256": sha256_bytes(raw),
    }
    return parse_json(raw, context=purpose), record


def follow_pages(
    *,
    initial_url: str,
    path: str,
    directory: Path,
    purpose: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    url: str | None = initial_url
    seen_urls: set[str] = set()
    payloads: list[dict[str, Any]] = []
    manifest: list[dict[str, Any]] = []
    for page in range(1, MAX_PAGES + 1):
        if url is None:
            break
        validate_url(url, path=path)
        if url in seen_urls:
            raise SourceContractError(f"{purpose}: repeated next_page_url")
        seen_urls.add(url)
        payload, record = request_page(
            url=url,
            path=path,
            directory=directory,
            filename=f"page-{page:04d}.json",
            purpose=f"{purpose} page {page}",
            page=page,
        )
        if "data" not in payload or not isinstance(payload["data"], list):
            raise SourceContractError(f"{purpose} page {page}: missing data list")
        unknown = set(payload) - {"data", "next_page_token", "next_page_url"}
        if unknown:
            raise SourceContractError(
                f"{purpose} page {page}: unexpected top-level fields {sorted(unknown)}"
            )
        record["rows"] = len(payload["data"])
        payloads.append(payload)
        manifest.append(record)
        next_url = payload.get("next_page_url")
        if next_url is None:
            url = None
        elif not isinstance(next_url, str) or not next_url:
            raise SourceContractError(f"{purpose} page {page}: invalid next_page_url")
        else:
            validate_url(next_url, path=path)
            url = next_url
        time.sleep(0.12)
    else:
        raise SourceContractError(f"{purpose}: page budget exhausted")
    if url is not None:
        raise SourceContractError(f"{purpose}: pagination did not terminate")
    return payloads, manifest


def reference_url() -> str:
    query = urllib.parse.urlencode({"metrics": METRIC, "page_size": "100"})
    return f"{CM_ORIGIN}{REFERENCE_PATH}?{query}"


def catalog_url(asset: str) -> str:
    query = urllib.parse.urlencode(
        {"assets": asset, "metrics": METRIC, "page_size": "100"}
    )
    return f"{CM_ORIGIN}{CATALOG_PATH}?{query}"


def series_url(asset: str, end: datetime) -> str:
    query = urllib.parse.urlencode(
        {
            "assets": asset,
            "metrics": METRIC,
            "frequency": FREQUENCY,
            "start_time": iso_hour(START),
            "end_time": iso_hour(end),
            "paging_from": "start",
            "page_size": str(PAGE_SIZE),
        }
    )
    return f"{CM_ORIGIN}{SERIES_PATH}?{query}"


def freeze_semantics() -> dict[str, Any]:
    payloads, manifest = follow_pages(
        initial_url=reference_url(),
        path=REFERENCE_PATH,
        directory=SOURCE / "reference",
        purpose="FeeTotNtv official reference",
    )
    rows = [row for payload in payloads for row in payload["data"]]
    matches = [row for row in rows if isinstance(row, dict) and row.get("metric") == METRIC]
    if len(matches) != 1:
        raise SourceContractError(
            f"official reference returned {len(matches)} exact {METRIC} rows"
        )
    row = matches[0]
    full_name = row.get("full_name")
    description = row.get("description")
    unit = row.get("unit")
    metric_type = row.get("type")
    if not all(isinstance(value, str) and value for value in (full_name, description, unit)):
        raise SourceContractError("FeeTotNtv official reference semantics are incomplete")
    semantics = " ".join((full_name, description, unit)).lower()
    participant_terms = ("miner", "validator", "staker", "block producer")
    if (
        "fee" not in semantics
        or "native" not in unit.lower()
        or not any(term in semantics for term in participant_terms)
        or "burn" not in semantics
    ):
        raise SourceContractError(
            "FeeTotNtv official semantics do not unambiguously identify native-unit "
            "consensus fees including burned fees"
        )
    if metric_type is not None and not isinstance(metric_type, str):
        raise SourceContractError("FeeTotNtv reference type has invalid schema")
    return {
        "metric": METRIC,
        "full_name": full_name,
        "description": description,
        "unit": unit,
        "type": metric_type,
        "reference_manifest": manifest,
        "reference_rows_sha256": sha256_bytes(canonical_bytes(matches)),
        "semantic_gate_passed": True,
    }


def freeze_catalog(asset: str) -> dict[str, Any]:
    payloads, manifest = follow_pages(
        initial_url=catalog_url(asset),
        path=CATALOG_PATH,
        directory=SOURCE / f"catalog-{asset}",
        purpose=f"{asset} FeeTotNtv catalog",
    )
    assets = [row for payload in payloads for row in payload["data"]]
    asset_rows = [row for row in assets if isinstance(row, dict) and row.get("asset") == asset]
    if len(asset_rows) != 1:
        raise SourceContractError(f"catalog returned {len(asset_rows)} rows for {asset}")
    metrics = asset_rows[0].get("metrics")
    if not isinstance(metrics, list):
        raise SourceContractError(f"{asset} catalog metrics are missing")
    metric_rows = [
        row for row in metrics if isinstance(row, dict) and row.get("metric") == METRIC
    ]
    if len(metric_rows) != 1:
        raise SourceContractError(
            f"{asset} catalog returned {len(metric_rows)} exact {METRIC} rows"
        )
    frequencies = metric_rows[0].get("frequencies")
    if not isinstance(frequencies, list):
        raise SourceContractError(f"{asset} {METRIC} frequencies are missing")
    hourly = [
        row for row in frequencies if isinstance(row, dict) and row.get("frequency") == FREQUENCY
    ]
    if len(hourly) != 1:
        raise SourceContractError(
            f"{asset} catalog returned {len(hourly)} exact {METRIC}/{FREQUENCY} rows"
        )
    min_time = hourly[0].get("min_time")
    max_time = hourly[0].get("max_time")
    if not isinstance(min_time, str) or not isinstance(max_time, str):
        raise SourceContractError(f"{asset} catalog coverage boundaries are missing")
    min_hour = parse_time(min_time, context=f"{asset} catalog min_time")
    max_hour = parse_time(max_time, context=f"{asset} catalog max_time")
    if min_hour > START or max_hour < END:
        raise SourceContractError(
            f"{asset} catalog does not cover frozen interval: "
            f"min={min_time} max={max_time}"
        )
    return {
        "asset": asset,
        "metric": METRIC,
        "frequency": FREQUENCY,
        "min_time": min_time,
        "max_time": max_time,
        "catalog_manifest": manifest,
        "catalog_row_sha256": sha256_bytes(canonical_bytes(metric_rows[0])),
        "direct_1h_catalog_gate_passed": True,
    }


def parse_time(value: Any, *, context: str) -> datetime:
    if not isinstance(value, str):
        raise SourceContractError(f"{context}: time must be a string")
    match = _TIME_RE.fullmatch(value)
    if match is None:
        raise SourceContractError(f"{context}: off-grid timestamp {value!r}")
    return datetime.fromisoformat(
        f"{match.group('date')}T{match.group('hour')}:00:00+00:00"
    )


def canonical_decimal(value: Any, *, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise SourceContractError(f"{context}: {METRIC} must be a non-empty string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise SourceContractError(f"{context}: invalid decimal {value!r}") from exc
    if not parsed.is_finite() or parsed < 0:
        raise SourceContractError(f"{context}: {METRIC} must be finite and non-negative")
    normalized = format(parsed, "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized or "0"


def parse_series_row(
    row: Any, *, asset: str, page: int, row_number: int
) -> tuple[datetime, str, bytes]:
    context = f"{asset} series page {page} row {row_number}"
    if not isinstance(row, dict):
        raise SourceContractError(f"{context}: row must be an object")
    required = {"asset", "time", METRIC}
    allowed = required | {f"{METRIC}-status", f"{METRIC}-status-time"}
    if not required.issubset(row) or not set(row).issubset(allowed):
        raise SourceContractError(f"{context}: row schema mismatch: {sorted(row)}")
    if row["asset"] != asset:
        raise SourceContractError(f"{context}: unexpected asset {row['asset']!r}")
    timestamp = parse_time(row["time"], context=context)
    value = canonical_decimal(row[METRIC], context=context)
    identity = canonical_bytes(row)
    return timestamp, value, identity


def expected_grid(end: datetime) -> tuple[datetime, ...]:
    if end < START:
        raise ValueError("end precedes start")
    count = int((end - START).total_seconds() // 3600) + 1
    return tuple(START + timedelta(hours=index) for index in range(count))


def acquire_series(asset: str, *, label: str, end: datetime) -> Acquisition:
    payloads, manifest = follow_pages(
        initial_url=series_url(asset, end),
        path=SERIES_PATH,
        directory=SOURCE / f"series-{asset}-{label}",
        purpose=f"{asset} {METRIC}/{FREQUENCY} {label}",
    )
    values: dict[datetime, str] = {}
    identities: dict[datetime, bytes] = {}
    exact_duplicates = 0
    conflicts = 0
    previous: datetime | None = None
    for page, payload in enumerate(payloads, 1):
        rows = payload["data"]
        if not rows:
            raise SourceContractError(f"{asset} {label} page {page}: empty data page")
        parsed = [
            parse_series_row(row, asset=asset, page=page, row_number=row_number)
            for row_number, row in enumerate(rows, 1)
        ]
        timestamps = [item[0] for item in parsed]
        if any(
            left >= right
            for left, right in zip(timestamps, timestamps[1:], strict=False)
        ):
            raise SourceContractError(f"{asset} {label} page {page}: rows not ascending")
        if previous is not None and timestamps[0] <= previous:
            raise SourceContractError(f"{asset} {label}: pagination overlaps or reverses")
        previous = timestamps[-1]
        manifest[page - 1].update(
            {
                "asset": asset,
                "metric": METRIC,
                "frequency": FREQUENCY,
                "oldest": iso_hour(timestamps[0]),
                "newest": iso_hour(timestamps[-1]),
            }
        )
        for timestamp, value, identity in parsed:
            prior = identities.get(timestamp)
            if prior is not None:
                if prior == identity:
                    exact_duplicates += 1
                else:
                    conflicts += 1
                continue
            identities[timestamp] = identity
            values[timestamp] = value
    if exact_duplicates or conflicts:
        raise SourceContractError(
            f"{asset} {label}: duplicate timestamps exact={exact_duplicates} conflicts={conflicts}"
        )
    grid = expected_grid(end)
    expected_set = set(grid)
    missing = [timestamp for timestamp in grid if timestamp not in values]
    extras = sorted(timestamp for timestamp in values if timestamp not in expected_set)
    if missing or extras or len(values) != len(grid):
        raise SourceContractError(
            f"{asset} {label}: exact-grid failure observed={len(values)} expected={len(grid)} "
            f"missing={len(missing)} first_missing={iso_hour(missing[0]) if missing else None} "
            f"extras={len(extras)}"
        )
    rows = tuple((iso_hour(timestamp), values[timestamp]) for timestamp in grid)
    normalized = b"".join(
        canonical_bytes({"asset": asset, "time": timestamp, METRIC: value})
        for timestamp, value in rows
    )
    normalized_path = SOURCE / f"series-{asset}-{label}" / "normalized.jsonl"
    normalized_path.write_bytes(normalized)
    return Acquisition(
        asset=asset,
        label=label,
        requested_end=end,
        rows=rows,
        normalized_bytes=normalized,
        manifest=tuple(manifest),
        exact_duplicate_count=exact_duplicates,
        conflicting_duplicate_count=conflicts,
    )


def aggregate_response_hash(manifest: tuple[dict[str, Any], ...]) -> str:
    return sha256_bytes(
        canonical_bytes(
            [
                {
                    "request_url": row["request_url"],
                    "response_sha256": row["response_sha256"],
                    "response_bytes": row["response_bytes"],
                }
                for row in manifest
            ]
        )
    )


def coverage_record(
    *,
    asset: str,
    target: str,
    catalog: dict[str, Any],
    primary: Acquisition,
    repeat: Acquisition,
    suffix: Acquisition,
) -> dict[str, Any]:
    if len(primary.rows) != EXPECTED_ROWS:
        raise SourceContractError(
            f"{asset}: frozen row count {len(primary.rows)} != {EXPECTED_ROWS}"
        )
    if primary.normalized_bytes != repeat.normalized_bytes:
        raise SourceContractError(f"{asset}: repeated normalized acquisition differs")
    suffix_prefix = suffix.rows[: len(primary.rows)]
    if tuple(primary.rows) != tuple(suffix_prefix):
        raise SourceContractError(f"{asset}: later suffix altered frozen historical prefix")
    values = [Decimal(value) for _, value in primary.rows]
    if not all(value.is_finite() and value >= 0 for value in values):
        raise SourceContractError(f"{asset}: normalized values failed finite/non-negative gate")
    zero_count = sum(value == 0 for value in values)
    return {
        "asset": asset,
        "target": target,
        "catalog": catalog,
        "requested_start": iso_hour(START),
        "requested_end": iso_hour(END),
        "observed_start": primary.rows[0][0],
        "observed_end": primary.rows[-1][0],
        "expected_rows": EXPECTED_ROWS,
        "observed_rows": len(primary.rows),
        "gap_count": 0,
        "longest_gap_hours": 0,
        "exact_duplicate_count": primary.exact_duplicate_count,
        "conflicting_duplicate_count": primary.conflicting_duplicate_count,
        "null_count": 0,
        "non_finite_count": 0,
        "negative_count": 0,
        "zero_count": zero_count,
        "minimum": format(min(values), "f"),
        "maximum": format(max(values), "f"),
        "primary_dataset_sha256": sha256_bytes(primary.normalized_bytes),
        "repeat_dataset_sha256": sha256_bytes(repeat.normalized_bytes),
        "suffix_prefix_sha256": sha256_bytes(
            b"".join(
                canonical_bytes({"asset": asset, "time": timestamp, METRIC: value})
                for timestamp, value in suffix_prefix
            )
        ),
        "primary_response_manifest_sha256": aggregate_response_hash(primary.manifest),
        "repeat_response_manifest_sha256": aggregate_response_hash(repeat.manifest),
        "suffix_response_manifest_sha256": aggregate_response_hash(suffix.manifest),
        "repeat_normalization_identical": True,
        "future_prefix_identical": True,
        "timestamp_grid": "strictly increasing unique exact UTC hours",
        "causal_available_from_rule": "source hour open + 25 completed hours",
        "source_gate_passed": True,
    }


def null_performance() -> dict[str, Any]:
    return {
        "training_net_return": None,
        "training_sharpe": None,
        "oos_net_return": None,
        "oos_sharpe": None,
        "full_net_return": None,
        "full_sharpe": None,
        "benchmark_comparison": None,
        "turnover": None,
        "modeled_fee_drag": None,
        "maximum_drawdown": None,
        "edge_per_turnover": None,
        "fold_breadth": None,
        "year_breadth": None,
        "uncertainty": None,
        "execution_delay": None,
    }


def persist_provider_rejection(error: ProviderRejection) -> dict[str, Any]:
    failure_dir = SOURCE / "failure"
    failure_dir.mkdir(parents=True, exist_ok=True)
    path = failure_dir / "provider-rejection-body.bin"
    path.write_bytes(error.body)
    return {
        "kind": "provider_rejection",
        "http_status": error.status,
        "request_url": error.url,
        "response_file": str(path),
        "response_bytes": len(error.body),
        "response_sha256": sha256_bytes(error.body),
        "message": str(error),
    }


def report_text(evidence: dict[str, Any]) -> str:
    lines = [
        "# Public on-chain native fee-pressure 1H source contract",
        "",
        "```text",
        f"family                  {evidence['family_id']}",
        f"exact evidence head     {evidence['exact_head']}",
        f"candidate count         {evidence['candidate_count']}",
        f"parameter grid          {evidence['parameter_grid_count']}",
        f"source arms passing     {evidence['source_arms_passing']}/2",
        f"performance accessed    {str(evidence['performance_accessed']).lower()}",
        f"OOS accessed            {str(evidence['oos_accessed']).lower()}",
        f"verdict                 {evidence['verdict']}",
        "```",
        "",
        "## Source result",
        "",
    ]
    if evidence["source_contract_passed"]:
        semantics = evidence["official_semantics"]
        lines.extend(
            [
                f"Official metric: `{semantics['metric']}` — {semantics['full_name']}.",
                "",
                "| Asset | Rows | Range | Dataset SHA-256 | Repeat | Prefix |",
                "|---|---:|---|---|---:|---:|",
            ]
        )
        for market in evidence["markets"]:
            lines.append(
                "| {asset} | {rows:,} | {start} to {end} | `{sha}` | {repeat} | {prefix} |".format(
                    asset=market["asset"].upper(),
                    rows=market["observed_rows"],
                    start=market["observed_start"],
                    end=market["observed_end"],
                    sha=market["primary_dataset_sha256"],
                    repeat="pass" if market["repeat_normalization_identical"] else "fail",
                    prefix="pass" if market["future_prefix_identical"] else "fail",
                )
            )
        lines.extend(
            [
                "",
                "Both arms passed direct catalog support, anonymous acquisition, exact-grid, "
                "value-validity, canonical pagination, independent-repeat and future-prefix gates.",
            ]
        )
    else:
        failure = evidence.get("failure") or {}
        lines.extend(
            [
                "The frozen bilateral source contract failed closed before any target-price or "
                "performance access.",
                "",
                f"Failure: `{failure.get('message', 'unspecified source-contract failure')}`",
            ]
        )
    lines.extend(
        [
            "",
            "## Strategy-performance fields",
            "",
            "All train, OOS, full, benchmark, turnover, drawdown, breadth, uncertainty and "
            "delay fields are null rather than zero. Exactly 5 bps one way remains bound only "
            "to a future separately authorised executable experiment.",
            "",
            "No signal sign, transform, window, threshold, sizing rule or position path "
            "was defined.",
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
    (OUT / "evidence.sha256").write_text(f"{sha256_file(evidence_path)}\n", encoding="utf-8")
    (OUT / "report.sha256").write_text(f"{sha256_file(report_path)}\n", encoding="utf-8")
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
        raise RuntimeError("GITHUB_SHA must be the exact 40-character evidence head")
    base = {
        "family_id": FAMILY_ID,
        "issue_number": ISSUE_NUMBER,
        "exact_head": exact_head,
        "classification": "source-contract-first exogenous-information experiment",
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "fixed_targets": [target for _, target in ASSETS],
        "metric": METRIC,
        "frequency": FREQUENCY,
        "bar_interval": "1H",
        "requested_start": iso_hour(START),
        "requested_end": iso_hour(END),
        "expected_rows_per_arm": EXPECTED_ROWS,
        "canonical_fee_bps_one_way": 5.0,
        "public_data_only": True,
        "credentials_private_endpoints_accounts_orders_adapters_leverage_funds": False,
        "cross_sectional_or_contemporaneous_selection": False,
        "canonical_strategy_changed": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "performance_accessed": False,
        "oos_accessed": False,
        "performance": null_performance(),
    }
    semantics: dict[str, Any] | None = None
    markets: list[dict[str, Any]] = []
    stage = "official_semantics"
    try:
        semantics = freeze_semantics()
        for asset, target in ASSETS:
            stage = f"{asset}_catalog"
            catalog = freeze_catalog(asset)
            stage = f"{asset}_primary"
            primary = acquire_series(asset, label="primary", end=END)
            time.sleep(0.5)
            stage = f"{asset}_repeat"
            repeat = acquire_series(asset, label="repeat", end=END)
            time.sleep(0.5)
            stage = f"{asset}_suffix"
            suffix = acquire_series(asset, label="suffix", end=SUFFIX_END)
            stage = f"{asset}_coverage"
            markets.append(
                coverage_record(
                    asset=asset,
                    target=target,
                    catalog=catalog,
                    primary=primary,
                    repeat=repeat,
                    suffix=suffix,
                )
            )
        source_passed = len(markets) == len(ASSETS) and all(
            market["source_gate_passed"] for market in markets
        )
        if not source_passed:
            raise SourceContractError("bilateral source gate did not pass")
        evidence = {
            **base,
            "official_semantics": semantics,
            "markets": markets,
            "source_arms_passing": len(markets),
            "source_contract_passed": True,
            "failure": None,
            "verdict": (
                "accept_onchain_native_fee_pressure_1h_source_for_separate_"
                "training_only_predeclaration"
            ),
        }
    except ProviderRejection as exc:
        evidence = {
            **base,
            "official_semantics": semantics,
            "markets": markets,
            "source_arms_passing": len(markets),
            "source_contract_passed": False,
            "failure": {**persist_provider_rejection(exc), "stage": stage},
            "verdict": "reject_causal_onchain_native_fee_pressure_source_contract_1h_v1",
        }
    except (SourceContractError, TransportError) as exc:
        evidence = {
            **base,
            "official_semantics": semantics,
            "markets": markets,
            "source_arms_passing": len(markets),
            "source_contract_passed": False,
            "failure": {
                "kind": type(exc).__name__,
                "stage": stage,
                "message": str(exc),
            },
            "verdict": "reject_causal_onchain_native_fee_pressure_source_contract_1h_v1",
        }
    write_outputs(evidence)
    return evidence


if __name__ == "__main__":
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
