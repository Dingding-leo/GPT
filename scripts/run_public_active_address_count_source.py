#!/usr/bin/env python3
"""Audit the frozen Coin Metrics Community AdrActCnt native-1H source contract.

This is a source-contract-first experiment. It must never access target prices,
returns, benchmarks, OOS labels, accounts, credentials, orders, or executable
strategy state.
"""
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

FAMILY_ID = "causal-public-active-address-count-source-contract-1h-v1"
ISSUE_NUMBER = 1129
BASE_MAIN = "5a0fcc97d1a882f8223656c51f5bb8055f534e38"
ORIGIN = "https://community-api.coinmetrics.io"
CATALOG_PATH = "/v4/catalog-v2/asset-metrics"
TIMESERIES_PATH = "/v4/timeseries/asset-metrics"
METRIC = "AdrActCnt"
FREQUENCY = "1h"
ASSETS = ("btc", "eth")
TARGET_MAP = {"btc": "BTC-USDT", "eth": "ETH-USDT"}
START = datetime(2023, 4, 1, 0, 0, tzinfo=UTC)
END = datetime(2025, 12, 31, 23, 0, tzinfo=UTC)
EXTENSION_END = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
EXPECTED_ROWS = 24_144
PROBE_HOURS = 96
PAGE_SIZE = 10_000
REQUEST_PAUSE_SECONDS = 0.75
MAX_TOTAL_EVIDENCE_BYTES = 100 * 1024 * 1024
OUT = Path("reports/experiments") / FAMILY_ID
SOURCE = OUT / "source"

ACCEPT = (
    "accept_public_bilateral_active_address_count_1h_source_for_separate_"
    "training_predeclaration"
)
REJECT = "reject_causal_public_active_address_count_source_contract_1h_v1"

PERFORMANCE_NULLS = {
    "training_return": None,
    "training_sharpe": None,
    "oos_return": None,
    "oos_sharpe": None,
    "full_return": None,
    "full_sharpe": None,
    "benchmark_comparison": None,
    "turnover": None,
    "modeled_fee_drag": None,
    "maximum_drawdown": None,
    "edge_per_turnover": None,
    "fold_year_breadth": None,
    "dependence_uncertainty": None,
    "execution_delay_performance": None,
}

OFFICIAL_SEMANTIC_SNAPSHOT = {
    "snapshot_date_utc": "2026-08-08",
    "provider": "Coin Metrics",
    "product": "Community API v4",
    "community_origin": ORIGIN,
    "catalog_path": CATALOG_PATH,
    "timeseries_path": TIMESERIES_PATH,
    "metric": METRIC,
    "metric_object": "provider-defined count of unique active blockchain addresses over an interval",
    "requested_frequency": FREQUENCY,
    "catalog_is_authoritative_for_asset_metric_frequency_availability": True,
    "community_rate_limit_reference": "10 requests per 6 seconds per IP in official API conventions",
    "no_api_key_or_account_context": True,
}


class SourceFailure(RuntimeError):
    """A frozen source gate failed."""


@dataclass(frozen=True)
class ResponseRecord:
    purpose: str
    asset: str
    request_url: str
    received_at_utc: str
    status: int
    headers: dict[str, str]
    raw: bytes
    response_file: str

    def manifest(self) -> dict[str, Any]:
        return {
            "purpose": self.purpose,
            "asset": self.asset,
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


def iso(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def expected_grid(start: datetime, end: datetime) -> tuple[str, ...]:
    count = int((end - start).total_seconds() // 3600) + 1
    return tuple(iso(start + timedelta(hours=i)) for i in range(count))


def normalize_time(raw: Any) -> str:
    if not isinstance(raw, str) or len(raw) < 20 or not raw.endswith("Z"):
        raise SourceFailure(f"invalid timestamp value: {raw!r}")
    try:
        value = datetime.strptime(raw[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
    except ValueError as exc:
        raise SourceFailure(f"unparseable timestamp: {raw!r}") from exc
    if value.minute != 0 or value.second != 0:
        raise SourceFailure(f"off-hour timestamp: {raw!r}")
    return iso(value)


def safe_url(url: str, expected_path: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "community-api.coinmetrics.io":
        raise SourceFailure(f"untrusted provider URL: {url}")
    if parsed.path != expected_path:
        raise SourceFailure(f"unexpected provider path: {parsed.path}")
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    forbidden = {"api_key", "apikey", "access_token", "authorization", "bearer"}
    if any(name.lower() in forbidden for name, _ in query):
        raise SourceFailure(f"credential parameter appeared in provider URL: {url}")
    return url


def catalog_url(asset: str) -> str:
    query = urllib.parse.urlencode([("assets", asset), ("metrics", METRIC)])
    return safe_url(f"{ORIGIN}{CATALOG_PATH}?{query}", CATALOG_PATH)


def timeseries_url(asset: str, start: datetime, end: datetime) -> str:
    query = urllib.parse.urlencode(
        [
            ("assets", asset),
            ("metrics", METRIC),
            ("frequency", FREQUENCY),
            ("start_time", iso(start)),
            ("end_time", iso(end)),
            ("page_size", str(PAGE_SIZE)),
        ]
    )
    return safe_url(f"{ORIGIN}{TIMESERIES_PATH}?{query}", TIMESERIES_PATH)


def persist_response(
    purpose: str,
    asset: str,
    url: str,
    status: int,
    headers: dict[str, str],
    raw: bytes,
) -> ResponseRecord:
    folder = SOURCE / asset
    folder.mkdir(parents=True, exist_ok=True)
    safe = purpose.replace("/", "-").replace(" ", "-")
    body = folder / f"{safe}.body"
    body.write_bytes(raw)
    record = ResponseRecord(
        purpose=purpose,
        asset=asset,
        request_url=url,
        received_at_utc=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        status=status,
        headers=headers,
        raw=raw,
        response_file=str(body.relative_to(OUT)),
    )
    (folder / f"{safe}.meta.json").write_bytes(canonical_bytes(record.manifest()))
    return record


def request_json(purpose: str, asset: str, url: str) -> tuple[Any | None, ResponseRecord, str | None]:
    safe_url(url, urllib.parse.urlsplit(url).path)
    request = urllib.request.Request(
        url,
        method="GET",
        headers={"Accept": "application/json", "User-Agent": "gpt-quant-source-audit/1.0"},
    )
    status = 0
    headers: dict[str, str] = {}
    raw = b""
    transport_error: str | None = None
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status = int(response.status)
            headers = {
                key.lower(): value
                for key, value in response.headers.items()
                if key.lower()
                in {
                    "content-type",
                    "date",
                    "server",
                    "x-ratelimit-limit",
                    "x-ratelimit-remaining",
                    "x-next-page-url",
                }
            }
            raw = response.read(16 * 1024 * 1024 + 1)
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        headers = {
            key.lower(): value
            for key, value in exc.headers.items()
            if key.lower() in {"content-type", "date", "server", "x-ratelimit-limit", "x-ratelimit-remaining"}
        }
        raw = exc.read(16 * 1024 * 1024 + 1)
    except urllib.error.URLError as exc:
        transport_error = f"{type(exc).__name__}: {exc}"
        raw = transport_error.encode("utf-8", errors="replace")

    record = persist_response(purpose, asset, url, status, headers, raw)
    time.sleep(REQUEST_PAUSE_SECONDS)
    if len(raw) > 16 * 1024 * 1024:
        return None, record, "response exceeded 16 MiB per-request evidence bound"
    if transport_error is not None:
        return None, record, transport_error
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, record, f"invalid JSON: {exc}"
    if status != 200:
        return payload, record, f"HTTP {status}"
    if not isinstance(payload, dict):
        return payload, record, "non-object JSON envelope"
    return payload, record, None


def recursive_frequency_evidence(value: Any) -> tuple[set[str], int]:
    frequencies: set[str] = set()
    metric_nodes = 0

    def walk(node: Any) -> None:
        nonlocal metric_nodes
        if isinstance(node, dict):
            if node.get("metric") == METRIC:
                metric_nodes += 1
                for item in node.get("frequencies", []) if isinstance(node.get("frequencies"), list) else []:
                    if isinstance(item, dict) and isinstance(item.get("frequency"), str):
                        frequencies.add(item["frequency"])
                    elif isinstance(item, str):
                        frequencies.add(item)
                if isinstance(node.get("frequency"), str):
                    frequencies.add(node["frequency"])
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    return frequencies, metric_nodes


def audit_catalog(asset: str) -> dict[str, Any]:
    url = catalog_url(asset)
    payload, record, error = request_json("catalog", asset, url)
    frequencies: set[str] = set()
    metric_nodes = 0
    if payload is not None:
        frequencies, metric_nodes = recursive_frequency_evidence(payload)
    passed = error is None and metric_nodes > 0 and FREQUENCY in frequencies
    return {
        "request": record.manifest(),
        "request_error": error,
        "metric_nodes_found": metric_nodes,
        "frequencies_declared_for_metric": sorted(frequencies),
        "declares_exact_metric_frequency": passed,
    }


def parse_timeseries(payload: Any, asset: str) -> tuple[tuple[str, float], ...]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise SourceFailure(f"missing data array for {asset}")
    rows: list[tuple[str, float]] = []
    for index, item in enumerate(payload["data"]):
        if not isinstance(item, dict):
            raise SourceFailure(f"non-object data row for {asset} at {index}")
        if item.get("asset") != asset:
            raise SourceFailure(f"asset identity mismatch for {asset} at {index}: {item.get('asset')!r}")
        if METRIC not in item or item[METRIC] is None:
            raise SourceFailure(f"metric absent/null for {asset} at {index}")
        stamp = normalize_time(item.get("time"))
        try:
            value = float(item[METRIC])
        except (TypeError, ValueError, OverflowError) as exc:
            raise SourceFailure(f"non-numeric {METRIC} for {asset} at {index}") from exc
        if not math.isfinite(value) or value < 0:
            raise SourceFailure(f"non-finite/negative {METRIC} for {asset} at {index}")
        rows.append((stamp, value))
    return tuple(rows)


def probe(asset: str, label: str, start: datetime, end: datetime) -> dict[str, Any]:
    url = timeseries_url(asset, start, end)
    payload, record, error = request_json(label, asset, url)
    rows: tuple[tuple[str, float], ...] = ()
    parse_error: str | None = None
    if error is None:
        try:
            rows = parse_timeseries(payload, asset)
        except SourceFailure as exc:
            parse_error = str(exc)
    expected = expected_grid(start, end)
    timestamps = tuple(stamp for stamp, _ in rows)
    unique = len(timestamps) == len(set(timestamps))
    exact = error is None and parse_error is None and unique and timestamps == expected
    return {
        "label": label,
        "requested_start": iso(start),
        "requested_end": iso(end),
        "expected_rows": len(expected),
        "observed_rows": len(rows),
        "first_timestamp": timestamps[0] if timestamps else None,
        "last_timestamp": timestamps[-1] if timestamps else None,
        "unique_timestamps": unique,
        "exact_grid": exact,
        "request_error": error,
        "parse_error": parse_error,
        "request": record.manifest(),
    }


def follow_pages(asset: str, label: str, start: datetime, end: datetime) -> tuple[tuple[tuple[str, float], ...], list[dict[str, Any]]]:
    url: str | None = timeseries_url(asset, start, end)
    rows: list[tuple[str, float]] = []
    requests: list[dict[str, Any]] = []
    page = 0
    seen_urls: set[str] = set()
    while url is not None:
        page += 1
        if page > 20:
            raise SourceFailure(f"pagination exceeded 20 pages for {asset} {label}")
        safe_url(url, TIMESERIES_PATH)
        if url in seen_urls:
            raise SourceFailure(f"pagination URL loop for {asset} {label}")
        seen_urls.add(url)
        payload, record, error = request_json(f"{label}-page-{page:02d}", asset, url)
        requests.append(record.manifest())
        if error is not None:
            raise SourceFailure(f"{asset} {label} page {page}: {error}")
        parsed = parse_timeseries(payload, asset)
        rows.extend(parsed)
        next_url = payload.get("next_page_url") if isinstance(payload, dict) else None
        if next_url is None:
            url = None
        elif not isinstance(next_url, str) or not next_url:
            raise SourceFailure(f"invalid next_page_url for {asset} {label}")
        else:
            url = safe_url(next_url, TIMESERIES_PATH)

    rows.sort(key=lambda row: row[0])
    timestamps = [stamp for stamp, _ in rows]
    if len(timestamps) != len(set(timestamps)):
        raise SourceFailure(f"duplicate timestamps in full {asset} {label} acquisition")
    expected = expected_grid(start, end)
    if tuple(timestamps) != expected:
        raise SourceFailure(
            f"calendar mismatch for {asset} {label}: expected={len(expected)} observed={len(rows)}"
        )
    return tuple(rows), requests


def row_bytes(rows: tuple[tuple[str, float], ...]) -> bytes:
    return canonical_bytes([[stamp, format(value, ".17g")] for stamp, value in rows])


def iqr(values: list[float]) -> float:
    if len(values) < 4:
        return 0.0
    q = quantiles(values, n=4, method="inclusive")
    return float(q[2] - q[0])


def full_arm(asset: str) -> dict[str, Any]:
    primary, primary_requests = follow_pages(asset, "primary", START, END)
    repeat, repeat_requests = follow_pages(asset, "repeat", START, END)
    extension, extension_requests = follow_pages(asset, "extension", START, EXTENSION_END)
    values = [value for _, value in primary]
    distinct = len(set(values))
    spread = iqr(values)
    primary_bytes = row_bytes(primary)
    repeat_bytes = row_bytes(repeat)
    extension_prefix_bytes = row_bytes(extension[:EXPECTED_ROWS])
    normalized = SOURCE / asset / "normalized-primary.json"
    normalized.write_bytes(primary_bytes)
    return {
        "asset": asset,
        "future_target": TARGET_MAP[asset],
        "observed_rows": len(primary),
        "first_timestamp": primary[0][0] if primary else None,
        "last_timestamp": primary[-1][0] if primary else None,
        "distinct_values": distinct,
        "iqr": spread,
        "normalized_rows_sha256": sha256_bytes(primary_bytes),
        "repeat_normalized_rows_sha256": sha256_bytes(repeat_bytes),
        "extension_prefix_sha256": sha256_bytes(extension_prefix_bytes),
        "request_counts": {
            "primary": len(primary_requests),
            "repeat": len(repeat_requests),
            "extension": len(extension_requests),
        },
        "gates": {
            "exact_24144_calendar": len(primary) == EXPECTED_ROWS,
            "all_finite_nonnegative": all(math.isfinite(v) and v >= 0 for v in values),
            "at_least_100_distinct": distinct >= 100,
            "positive_iqr": spread > 0,
            "repeat_normalization_identical": primary_bytes == repeat_bytes,
            "extension_prefix_identical": primary_bytes == extension_prefix_bytes,
            "extension_has_one_extra_hour": len(extension) == EXPECTED_ROWS + 1,
        },
        "primary_requests": primary_requests,
        "repeat_requests": repeat_requests,
        "extension_requests": extension_requests,
    }


def evidence_size() -> int:
    if not OUT.exists():
        return 0
    return sum(path.stat().st_size for path in OUT.rglob("*") if path.is_file())


def write_terminal(evidence: dict[str, Any]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    evidence_path = OUT / "evidence.json"
    evidence_path.write_bytes(canonical_bytes(evidence))
    report = [
        "# Public bilateral active-address-count source contract — 1H v1",
        "",
        "This is a zero-candidate source-contract audit. It accessed no target candles, returns, benchmark, OOS, account, order, paper or live state.",
        "",
        f"- verdict: `{evidence['verdict']}`",
        f"- source arms passing: **{evidence['source_arms_passing']}/2**",
        f"- candidate / grid: **0 / 0**",
        f"- exact fee contract for any future executable strategy: **5 bps one way**",
        f"- target-return / OOS access: **false / false**",
        "",
        "## Frozen source result",
        "",
        "| Arm | Catalog declares AdrActCnt 1h | Start probe | Middle probe | End probe | Full source gate |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for arm in evidence["arms"]:
        probes = {item["label"]: item for item in arm["probes"]}
        report.append(
            "| {asset} | {catalog} | {start} | {middle} | {end} | {full} |".format(
                asset=arm["asset"],
                catalog="yes" if arm["catalog"]["declares_exact_metric_frequency"] else "no",
                start="yes" if probes["start-probe"]["exact_grid"] else "no",
                middle="yes" if probes["middle-probe"]["exact_grid"] else "no",
                end="yes" if probes["end-probe"]["exact_grid"] else "no",
                full="yes" if arm["source_gate_passed"] else "no",
            )
        )
    report.extend(
        [
            "",
            "## Strategy accounting",
            "",
            "Training/OOS/full return and Sharpe, benchmark comparison, turnover, fee drag, maximum drawdown, edge per turnover, fold/year breadth, dependence uncertainty and execution-delay performance are all **null, not zero**.",
            "",
            "A source pass would only authorise a separately preregistered training-only temporal-information experiment; it would not establish alpha or authorise OOS/canonical/paper/live use.",
        ]
    )
    if evidence.get("failure"):
        report.extend(["", "## Decisive failure", "", evidence["failure"]])
    report_path = OUT / "report.md"
    report_path.write_text("\n".join(report) + "\n", encoding="utf-8")
    (OUT / "evidence.sha256").write_text(sha256_file(evidence_path) + "\n", encoding="utf-8")
    (OUT / "report.sha256").write_text(sha256_file(report_path) + "\n", encoding="utf-8")

    manifest_entries = []
    for path in sorted(OUT.rglob("*")):
        if not path.is_file() or path.name in {"artifact-manifest.json", "manifest.sha256"}:
            continue
        manifest_entries.append(
            {
                "path": str(path.relative_to(OUT)),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    manifest = {
        "family_id": FAMILY_ID,
        "exact_head": evidence["exact_head"],
        "files": manifest_entries,
    }
    manifest_path = OUT / "artifact-manifest.json"
    manifest_path.write_bytes(canonical_bytes(manifest))
    (OUT / "manifest.sha256").write_text(sha256_file(manifest_path) + "\n", encoding="utf-8")


def main() -> int:
    exact_head = os.environ.get("GITHUB_SHA", "").strip() or None
    OUT.mkdir(parents=True, exist_ok=True)
    SOURCE.mkdir(parents=True, exist_ok=True)

    arms: list[dict[str, Any]] = []
    feasibility_pass = True
    failure_reasons: list[str] = []
    middle_start = START + (END - START) / 2 - timedelta(hours=(PROBE_HOURS - 1) / 2)
    middle_start = middle_start.replace(minute=0, second=0, microsecond=0)
    middle_end = middle_start + timedelta(hours=PROBE_HOURS - 1)

    # Freeze and execute catalog + start/middle/end feasibility for BOTH arms before
    # any full acquisition. Failures are recorded rather than rescued.
    for asset in ASSETS:
        catalog = audit_catalog(asset)
        probes = [
            probe(asset, "start-probe", START, START + timedelta(hours=PROBE_HOURS - 1)),
            probe(asset, "middle-probe", middle_start, middle_end),
            probe(asset, "end-probe", END - timedelta(hours=PROBE_HOURS - 1), END),
        ]
        arm_feasible = catalog["declares_exact_metric_frequency"] and all(
            item["exact_grid"] for item in probes
        )
        if not arm_feasible:
            feasibility_pass = False
            reasons = []
            if not catalog["declares_exact_metric_frequency"]:
                reasons.append(
                    "Community catalog did not prove the exact AdrActCnt/1h asset-metric frequency"
                )
            for item in probes:
                if not item["exact_grid"]:
                    reasons.append(
                        f"{item['label']} observed {item['observed_rows']}/{item['expected_rows']} exact hours"
                        + (f" ({item['request_error']})" if item["request_error"] else "")
                        + (f" ({item['parse_error']})" if item["parse_error"] else "")
                    )
            failure_reasons.append(f"{asset}: " + "; ".join(reasons))
        arms.append(
            {
                "asset": asset,
                "future_target": TARGET_MAP[asset],
                "catalog": catalog,
                "probes": probes,
                "feasibility_passed": arm_feasible,
                "source_gate_passed": False,
                "full": None,
                "failure": None if arm_feasible else failure_reasons[-1],
            }
        )

    source_arms_passing = 0
    common_calendar_identical: bool | None = None
    if feasibility_pass:
        full_results: dict[str, dict[str, Any]] = {}
        for arm in arms:
            asset = arm["asset"]
            try:
                full = full_arm(asset)
                full_gate = all(full["gates"].values())
                arm["full"] = full
                arm["source_gate_passed"] = full_gate
                if full_gate:
                    source_arms_passing += 1
                else:
                    arm["failure"] = f"{asset}: one or more frozen full-source gates failed"
                    failure_reasons.append(arm["failure"])
                full_results[asset] = full
            except SourceFailure as exc:
                arm["failure"] = f"{asset}: {exc}"
                failure_reasons.append(arm["failure"])
                arm["source_gate_passed"] = False
        if all(asset in full_results for asset in ASSETS):
            common_calendar_identical = (
                full_results["btc"]["first_timestamp"] == full_results["eth"]["first_timestamp"]
                and full_results["btc"]["last_timestamp"] == full_results["eth"]["last_timestamp"]
                and full_results["btc"]["observed_rows"] == full_results["eth"]["observed_rows"] == EXPECTED_ROWS
            )
        else:
            common_calendar_identical = False
    else:
        source_arms_passing = 0

    total_bytes = evidence_size()
    size_gate = total_bytes < MAX_TOTAL_EVIDENCE_BYTES
    if not size_gate:
        failure_reasons.append(
            f"evidence size {total_bytes} exceeds frozen {MAX_TOTAL_EVIDENCE_BYTES} byte cap"
        )

    source_contract_passed = (
        feasibility_pass
        and source_arms_passing == 2
        and common_calendar_identical is True
        and size_gate
    )
    verdict = ACCEPT if source_contract_passed else REJECT
    failure = None if source_contract_passed else " | ".join(failure_reasons) or "bilateral source contract failed"

    evidence = {
        "family_id": FAMILY_ID,
        "issue_number": ISSUE_NUMBER,
        "base_main": BASE_MAIN,
        "exact_head": exact_head,
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "fixed_source_arms": list(ASSETS),
        "fixed_target_maps": TARGET_MAP,
        "metric": METRIC,
        "frequency": FREQUENCY,
        "frozen_start": iso(START),
        "frozen_end": iso(END),
        "expected_rows_per_arm": EXPECTED_ROWS,
        "canonical_fee_bps_one_way": 5.0,
        "public_data_only": True,
        "credentials_private_endpoints_accounts_orders_adapters_leverage_funds": False,
        "cross_sectional_or_relative_selection": False,
        "target_prices_or_returns_accessed": False,
        "performance_accessed": False,
        "oos_accessed": False,
        "canonical_strategy_changed": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "official_semantic_snapshot": OFFICIAL_SEMANTIC_SNAPSHOT,
        "feasibility_passed_bilaterally": feasibility_pass,
        "source_arms_passing": source_arms_passing,
        "common_calendar_identical": common_calendar_identical,
        "evidence_bytes_before_terminal_files": total_bytes,
        "evidence_under_100mib": size_gate,
        "source_contract_passed": source_contract_passed,
        "arms": arms,
        "performance": PERFORMANCE_NULLS,
        "failure": failure,
        "verdict": verdict,
        "closed_rescue_surface_on_rejection": [
            "alternate address-count metric",
            "daily-to-hourly expansion",
            "interpolation or forward fill",
            "provider substitution",
            "shortened calendar",
            "single-market promotion",
            "target replacement",
            "feature/sign/window/threshold fitting before a source pass",
        ],
    }
    write_terminal(evidence)
    print(
        json.dumps(
            {
                "family_id": FAMILY_ID,
                "source_arms_passing": source_arms_passing,
                "source_contract_passed": source_contract_passed,
                "target_prices_or_returns_accessed": False,
                "oos_accessed": False,
                "verdict": verdict,
                "evidence_sha256": sha256_file(OUT / "evidence.json"),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
