from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FAMILY_ID = "causal-onchain-fee-pressure-source-contract-1h-v1"
PASS_VERDICT = (
    "accept_onchain_fee_pressure_1h_source_contract_for_separate_"
    "training_only_predeclaration"
)
FAIL_VERDICT = "reject_causal_onchain_fee_pressure_source_contract_1h_v1"
REPOSITORY_MAIN = "5a0fcc97d1a882f8223656c51f5bb8055f534e38"
BASE = "https://community-api.coinmetrics.io"
TIMESERIES = "/v4/timeseries/asset-metrics"
REFERENCE = "/v4/reference-data/asset-metrics"
CATALOG = "/v4/catalog-v2/asset-metrics"
DOC_URL = "https://docs.coinmetrics.io/api/v4/"
METRIC = "FeeTotUSD"
ASSETS = ("btc", "eth")
START = "2021-04-01T00:00:00Z"
END = "2025-12-31T23:00:00Z"
SUFFIX_END = "2026-01-01T00:00:00Z"
START_MS = 1_617_235_200_000
END_MS = 1_767_222_000_000
HOUR_MS = 3_600_000
EXPECTED_ROWS = 41_664
PAGE_SIZE = 1_000
MAX_PAGES = 128
MAX_BYTES = 20_000_000
TIME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})T(\d{2}):00:00(?:\.0{1,9})?Z$")

NULL_ECONOMICS = {
    "train_net_return": None,
    "train_sharpe": None,
    "oos_net_return": None,
    "oos_sharpe": None,
    "full_net_return": None,
    "full_sharpe": None,
    "e2160_oos_net_return": None,
    "e2160_oos_sharpe": None,
    "always_long_net_return": None,
    "always_long_sharpe": None,
    "turnover": None,
    "modeled_fees": None,
    "maximum_drawdown": None,
    "edge_per_turnover_bps": None,
    "fold_breadth": None,
    "calendar_year_breadth": None,
    "dependence_aware_uncertainty": None,
    "one_hour_delayed_net_return": None,
    "one_hour_delayed_sharpe": None,
}


class SourceFailure(RuntimeError):
    pass


class TransientFailure(RuntimeError):
    pass


def canonical(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def iso(ms: int | None) -> str | None:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat().replace("+00:00", "Z")


def parse_time(value: Any) -> int:
    if not isinstance(value, str):
        raise SourceFailure("time is not a string")
    match = TIME_RE.fullmatch(value)
    if match is None:
        raise SourceFailure(f"off-grid timestamp {value!r}")
    dt = datetime.fromisoformat(
        f"{match.group(1)}T{match.group(2)}:00:00+00:00"
    )
    return int(dt.timestamp() * 1000)


def parse_status_time(value: Any) -> int:
    if not isinstance(value, str):
        raise SourceFailure("status-time is not a string")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SourceFailure(f"invalid status-time {value!r}") from exc
    if dt.tzinfo is None:
        raise SourceFailure("status-time is missing a timezone")
    return int(dt.timestamp() * 1000)


def request_bytes(url: str) -> tuple[bytes, dict[str, Any], int]:
    errors: list[str] = []
    for attempt in range(1, 6):
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json,text/html,text/plain;q=0.9,*/*;q=0.8",
                "User-Agent": "Dingding-leo-GPT-onchain-fee-source-contract/1.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:  # noqa: S310
                body = response.read(MAX_BYTES + 1)
                if len(body) > MAX_BYTES:
                    raise TransientFailure("response exceeds byte cap")
                status = int(getattr(response, "status", 200))
                return body, {
                    "request_url": url,
                    "final_url": response.geturl(),
                    "http_status": status,
                    "content_type": response.headers.get("Content-Type"),
                    "bytes": len(body),
                    "sha256": digest(body),
                    "attempt": attempt,
                }, status
        except urllib.error.HTTPError as exc:
            body = exc.read(MAX_BYTES + 1)
            status = int(exc.code)
            metadata = {
                "request_url": url,
                "final_url": exc.geturl(),
                "http_status": status,
                "content_type": (
                    exc.headers.get("Content-Type") if exc.headers else None
                ),
                "bytes": len(body),
                "sha256": digest(body),
                "attempt": attempt,
            }
            if status not in {429, 500, 502, 503, 504}:
                return body, metadata, status
            errors.append(f"attempt {attempt}: HTTP {status} body={digest(body)}")
        except (OSError, TimeoutError, urllib.error.URLError, TransientFailure) as exc:
            errors.append(f"attempt {attempt}: {type(exc).__name__}: {exc}")
        if attempt < 5:
            time.sleep(min(2**attempt, 12))
    raise TransientFailure("; ".join(errors))


def save_response(root: Path, stem: str, body: bytes, metadata: dict[str, Any]) -> None:
    raw_path = root / "raw" / f"{stem}.bin"
    meta_path = root / "raw" / f"{stem}.json"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(body)
    meta_path.write_bytes(canonical(metadata))


def parse_object(body: bytes, context: str) -> dict[str, Any]:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceFailure(f"{context}: invalid JSON") from exc
    if not isinstance(value, dict):
        raise SourceFailure(f"{context}: top-level JSON is not an object")
    return value


def allowed_page_url(url: str) -> bool:
    parsed = urllib.parse.urlsplit(url)
    return (
        parsed.scheme == "https"
        and parsed.netloc == "community-api.coinmetrics.io"
        and parsed.path == TIMESERIES
        and parsed.username is None
        and parsed.password is None
        and not parsed.fragment
        and not any(
            name.lower() in {"api_key", "apikey", "key", "token", "access_token"}
            for name in urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        )
    )


def initial_url(asset: str, end_time: str) -> str:
    query = urllib.parse.urlencode(
        {
            "assets": asset,
            "metrics": METRIC,
            "frequency": "1h",
            "start_time": START,
            "end_time": end_time,
            "paging_from": "start",
            "page_size": str(PAGE_SIZE),
        }
    )
    return f"{BASE}{TIMESERIES}?{query}"


def metadata_snapshot(root: Path) -> dict[str, Any]:
    records: dict[str, Any] = {}
    urls = {
        "official_api_documentation": DOC_URL,
        "metric_reference": f"{BASE}{REFERENCE}?metrics={METRIC}&page_size=100",
        "asset_metric_catalog": f"{BASE}{CATALOG}?assets=btc%2Ceth&page_size=1000",
    }
    for name, url in urls.items():
        body, meta, status = request_bytes(url)
        save_response(root, f"metadata-{name}", body, meta)
        record = {**meta, "status_ok": status == 200}
        if status == 200 and "json" in (meta.get("content_type") or "").lower():
            try:
                record["parsed"] = parse_object(body, name)
            except SourceFailure as exc:
                record["parse_error"] = str(exc)
        else:
            text = body.decode("utf-8", errors="replace").lower()
            record["semantic_marker_counts"] = {
                marker: text.count(marker)
                for marker in ("feetotusd", "fee", "usd", "frequency", "1h")
            }
        records[name] = record

    reference = records["metric_reference"].get("parsed", {})
    rows = reference.get("data", []) if isinstance(reference, dict) else []
    matching = [
        row
        for row in rows
        if isinstance(row, dict) and row.get("metric") == METRIC
    ]
    semantic_text = " ".join(
        str(row.get(key, ""))
        for row in matching
        for key in ("full_name", "description", "unit", "type")
    ).lower()
    records["semantic_gate"] = {
        "matching_records": len(matching),
        "defines_total_fees": (
            "fee" in semantic_text
            and ("total" in semantic_text or "sum" in semantic_text)
        ),
        "defines_usd_unit": "usd" in semantic_text,
        "passed": bool(
            matching
            and "fee" in semantic_text
            and ("total" in semantic_text or "sum" in semantic_text)
            and "usd" in semantic_text
        ),
    }
    return records


def parse_row(row: Any, asset: str) -> tuple[int, float, int | None, dict[str, Any]]:
    if not isinstance(row, dict):
        raise SourceFailure(f"{asset}: row is not an object")
    if row.get("asset") != asset or "time" not in row or METRIC not in row:
        raise SourceFailure(f"{asset}: row schema or identity mismatch")
    timestamp = parse_time(row["time"])
    try:
        value = float(row[METRIC])
    except (TypeError, ValueError) as exc:
        raise SourceFailure(f"{asset}: invalid {METRIC}") from exc
    if not math.isfinite(value) or value < 0:
        raise SourceFailure(f"{asset}: non-finite or negative {METRIC}")
    status_time_value = row.get(f"{METRIC}-status-time")
    status_ms = (
        None if status_time_value is None else parse_status_time(status_time_value)
    )
    return timestamp, value, status_ms, row


def acquire(root: Path, asset: str, label: str, end_time: str) -> dict[str, Any]:
    url: str | None = initial_url(asset, end_time)
    seen_urls: set[str] = set()
    rows_by_time: dict[int, tuple[float, dict[str, Any]]] = {}
    conflicts = 0
    duplicate_occurrences = 0
    page_manifest: list[dict[str, Any]] = []
    prior_last: int | None = None
    source_failure: str | None = None

    for page in range(1, MAX_PAGES + 1):
        if url is None:
            break
        if not allowed_page_url(url) or url in seen_urls:
            source_failure = "untrusted or repeated continuation URL"
            break
        seen_urls.add(url)
        body, meta, status = request_bytes(url)
        save_response(root, f"{asset}-{label}-page-{page:04d}", body, meta)
        page_record = {**meta, "page": page}
        page_manifest.append(page_record)
        if status != 200:
            source_failure = f"public endpoint returned HTTP {status}"
            break
        try:
            payload = parse_object(body, f"{asset} {label} page {page}")
            data = payload.get("data")
            if not isinstance(data, list) or not data:
                raise SourceFailure("empty or invalid data page")
            parsed = [parse_row(row, asset) for row in data]
            times = [item[0] for item in parsed]
            if any(
                left >= right
                for left, right in zip(times, times[1:], strict=False)
            ):
                raise SourceFailure("page rows are not strictly ascending")
            if prior_last is not None and times[0] <= prior_last:
                raise SourceFailure("pagination overlaps or reverses chronology")
            for timestamp, value, _status_ms, raw_row in parsed:
                prior = rows_by_time.get(timestamp)
                if prior is not None:
                    duplicate_occurrences += 1
                    if prior[1] != raw_row:
                        conflicts += 1
                rows_by_time.setdefault(timestamp, (value, raw_row))
            prior_last = times[-1]
            page_record.update(
                {
                    "rows": len(parsed),
                    "first_time": iso(times[0]),
                    "last_time": iso(times[-1]),
                }
            )
            next_url = payload.get("next_page_url")
            if next_url is None:
                url = None
            elif isinstance(next_url, str) and next_url:
                url = next_url
            else:
                raise SourceFailure("invalid next_page_url")
        except SourceFailure as exc:
            source_failure = str(exc)
            break
        time.sleep(0.08)
    else:
        source_failure = "page budget exhausted"

    requested_end_ms = END_MS if end_time == END else END_MS + HOUR_MS
    expected = list(range(START_MS, requested_end_ms + HOUR_MS, HOUR_MS))
    observed = sorted(ts for ts in rows_by_time if START_MS <= ts <= requested_end_ms)
    observed_set = set(observed)
    expected_set = set(expected)
    missing = [ts for ts in expected if ts not in observed_set]
    extras = [ts for ts in observed if ts not in expected_set]
    duplicate_count = duplicate_occurrences + sum(
        count - 1 for count in Counter(observed).values() if count > 1
    )
    normalized = [
        {"asset": asset, "time": iso(ts), METRIC: rows_by_time[ts][0]}
        for ts in observed
    ]
    normalized_bytes = canonical(normalized)
    normalized_path = root / "normalized" / f"{asset}-{label}.json"
    normalized_path.parent.mkdir(parents=True, exist_ok=True)
    normalized_path.write_bytes(normalized_bytes)

    lags: list[float] = []
    for ts in observed:
        status_value = rows_by_time[ts][1].get(f"{METRIC}-status-time")
        if status_value is not None:
            try:
                lags.append((parse_status_time(status_value) - ts) / HOUR_MS)
            except SourceFailure:
                source_failure = source_failure or "invalid status-time"

    expected_rows = EXPECTED_ROWS if end_time == END else EXPECTED_ROWS + 1
    coverage_pass = (
        source_failure is None
        and len(observed) == expected_rows
        and not missing
        and not extras
        and conflicts == 0
        and duplicate_count == 0
        and observed
        and observed[0] == START_MS
        and observed[-1] == requested_end_ms
    )
    availability_pass = bool(lags) and max(lags) <= 24.0 and min(lags) >= 0.0
    return {
        "asset": asset,
        "label": label,
        "request_start": START,
        "request_end": end_time,
        "expected_rows": expected_rows,
        "observed_rows": len(observed),
        "observed_start": iso(observed[0]) if observed else None,
        "observed_end": iso(observed[-1]) if observed else None,
        "missing_count": len(missing),
        "first_missing": iso(missing[0]) if missing else None,
        "longest_gap_hours": longest_gap(observed),
        "extra_count": len(extras),
        "duplicate_count": duplicate_count,
        "conflicting_duplicate_count": conflicts,
        "page_count": len(page_manifest),
        "pages": page_manifest,
        "normalized_path": normalized_path.as_posix(),
        "normalized_sha256": digest(normalized_bytes),
        "status_time_observations": len(lags),
        "minimum_observed_availability_lag_hours": min(lags) if lags else None,
        "maximum_observed_availability_lag_hours": max(lags) if lags else None,
        "coverage_passed": coverage_pass,
        "availability_within_24h_passed": availability_pass,
        "source_failure": source_failure,
        "normalized_rows": normalized,
    }


def longest_gap(times: list[int]) -> int:
    if len(times) < 2:
        return 0
    return max(
        max((right - left) // HOUR_MS - 1, 0)
        for left, right in zip(times, times[1:], strict=False)
    )


def arm_result(root: Path, asset: str, semantic_pass: bool) -> dict[str, Any]:
    first = acquire(root, asset, "first", END)
    if not first["coverage_passed"]:
        repeat = None
        suffix = None
        repeat_identical = False
        prefix_identical = False
    else:
        repeat = acquire(root, asset, "repeat", END)
        suffix = acquire(root, asset, "suffix", SUFFIX_END)
        repeat_identical = bool(
            repeat["coverage_passed"]
            and repeat["normalized_sha256"] == first["normalized_sha256"]
        )
        prefix = suffix["normalized_rows"][:EXPECTED_ROWS] if suffix else []
        prefix_identical = bool(
            suffix
            and suffix["coverage_passed"]
            and digest(canonical(prefix)) == first["normalized_sha256"]
        )
    for record in (first, repeat, suffix):
        if isinstance(record, dict):
            record.pop("normalized_rows", None)
    return {
        "asset": asset,
        "metric": METRIC,
        "frequency": "1h",
        "expected_rows": EXPECTED_ROWS,
        "first_acquisition": first,
        "repeat_acquisition": repeat,
        "future_suffix_acquisition": suffix,
        "repeat_normalized_identity": repeat_identical,
        "future_suffix_prefix_identity": prefix_identical,
        "source_contract_passed": bool(
            semantic_pass
            and first["coverage_passed"]
            and first["availability_within_24h_passed"]
            and repeat_identical
            and prefix_identical
        ),
        "economics": dict(NULL_ECONOMICS),
    }


def write_outputs(root: Path, evidence: dict[str, Any]) -> None:
    evidence_bytes = canonical(evidence)
    (root / "evidence.json").write_bytes(evidence_bytes)
    (root / "evidence.sha256").write_text(digest(evidence_bytes) + "\n")
    manifest = {
        "family_id": FAMILY_ID,
        "tested_head": evidence["tested_head"],
        "files": [
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": digest(path.read_bytes()),
            }
            for path in sorted(root.rglob("*"))
            if path.is_file()
            and path.name not in {"source_manifest.json", "source_manifest.sha256"}
        ],
    }
    manifest_bytes = canonical(manifest)
    (root / "source_manifest.json").write_bytes(manifest_bytes)
    (root / "source_manifest.sha256").write_text(digest(manifest_bytes) + "\n")
    lines = [
        "# On-chain fee-pressure source contract",
        "",
        f"- Exact evidence head: `{evidence['tested_head']}`",
        f"- Source arms passing: `{evidence['markets_passing_source_contract']}/2`",
        f"- Verdict: `{evidence['verdict']}`",
        (
            "- Target spot prices, features, returns, performance, and OOS "
            "were not accessed."
        ),
        "",
        (
            "| Asset | Rows | Pages | Missing | 24H availability | Repeat | "
            "Suffix prefix | Pass |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for arm in evidence["market_arms"]:
        first = arm["first_acquisition"]
        lines.append(
            f"| {arm['asset']} | {first['observed_rows']} | "
            f"{first['page_count']} | {first['missing_count']} | "
            f"{first['availability_within_24h_passed']} | "
            f"{arm['repeat_normalized_identity']} | "
            f"{arm['future_suffix_prefix_identity']} | "
            f"{arm['source_contract_passed']} |"
        )
    lines.extend(
        [
            "",
            "All train/OOS/full returns, Sharpe ratios, benchmark comparisons, "
            "turnover, fees, drawdown, fold/year breadth, uncertainty, and "
            "delayed-execution fields are null.",
        ]
    )
    (root / "report.md").write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tested-head", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    root = Path(args.output_dir)
    root.mkdir(parents=True, exist_ok=True)
    metadata = metadata_snapshot(root)
    semantic_pass = bool(metadata["semantic_gate"]["passed"])
    arms = [arm_result(root, asset, semantic_pass) for asset in ASSETS]
    markets_passing = sum(arm["source_contract_passed"] for arm in arms)
    overall_pass = markets_passing == len(ASSETS)
    evidence = {
        "family_id": FAMILY_ID,
        "tested_head": args.tested_head,
        "repository_main": REPOSITORY_MAIN,
        "classification": (
            "source-contract-first orthogonal exogenous-information experiment"
        ),
        "bar": "1H",
        "canonical_fee_bps_one_way": 5.0,
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "target_arms": ["BTC-USDT", "ETH-USDT"],
        "exogenous_mapping": {"btc": "BTC-USDT", "eth": "ETH-USDT"},
        "metric": METRIC,
        "fixed_interval": {"start": START, "end": END, "expected_rows": EXPECTED_ROWS},
        "metadata": metadata,
        "market_arms": arms,
        "markets_passing_source_contract": markets_passing,
        "source_contract_passed": overall_pass,
        "verdict": PASS_VERDICT if overall_pass else FAIL_VERDICT,
        "target_spot_data_downloaded": False,
        "target_returns_downloaded": False,
        "feature_defined": False,
        "candidate_created": False,
        "performance_accessed": False,
        "oos_accessed": False,
        "synthetic_data_used": False,
        "credentials_used": False,
        "private_endpoints_used": False,
        "accounts_or_orders": False,
        "enabled_adapters": False,
        "leverage_used": False,
        "cross_sectional_selection": False,
        "pairs_or_spreads": False,
        "market_neutral_or_long_short": False,
        "canonical_strategy_changed": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
    }
    write_outputs(root, evidence)
    print(
        json.dumps(
            {
                "tested_head": args.tested_head,
                "markets_passing_source_contract": markets_passing,
                "verdict": evidence["verdict"],
                "evidence_sha256": digest(canonical(evidence)),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
