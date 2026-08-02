from __future__ import annotations

import argparse
import email.utils
import hashlib
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FAMILY_ID = "causal-same-asset-venue-fragmentation-source-contract-1h-v1"
PASS_VERDICT = (
    "accept_same_asset_venue_fragmentation_1h_source_for_separate_"
    "training_only_predeclaration"
)
FAIL_VERDICT = "reject_causal_same_asset_venue_fragmentation_source_contract_1h_v1"
REPOSITORY_MAIN = "5a0fcc97d1a882f8223656c51f5bb8055f534e38"
PROVIDER_HOST = "min-api.cryptocompare.com"
BASE_URL = f"https://{PROVIDER_HOST}"
ENDPOINT_PATH = "/data/exchange/symbol/histohour"
ENDPOINT_URL = f"{BASE_URL}{ENDPOINT_PATH}"
DOC_URL = (
    "https://developers.coindesk.com/documentation/legacy/Historical/"
    "dataExchangeSymbolHistohour"
)
SCHEMA_URL = f"{BASE_URL}/data/json/path"
ASSETS = ("BTC", "ETH")
VENUES = ("Coinbase", "Kraken", "Bitstamp")
QUOTE = "USD"
START = "2023-04-01T00:00:00Z"
END = "2025-12-31T23:00:00Z"
SUFFIX_END = "2026-01-01T00:00:00Z"
START_TS = 1_680_307_200
END_TS = 1_767_222_000
SUFFIX_END_TS = 1_767_225_600
HOUR_SECONDS = 3_600
EXPECTED_ROWS = 24_144
PAGE_LIMIT = 2_000
MAX_PAGES_PER_ACQUISITION = 20
MAX_RESPONSE_BYTES = 20_000_000
MAX_TOTAL_RAW_BYTES = 2 * 1024 * 1024 * 1024
REQUEST_SLEEP_SECONDS = 0.18
RETRYABLE_HTTP = {408, 425, 429, 500, 502, 503, 504}

NULL_ECONOMICS = {
    "feature": None,
    "candidate_state": None,
    "train_net_return": None,
    "train_sharpe": None,
    "oos_net_return": None,
    "oos_sharpe": None,
    "full_net_return": None,
    "full_sharpe": None,
    "e2160_net_return": None,
    "e2160_sharpe": None,
    "benchmark_residual": None,
    "turnover": None,
    "modeled_fees": None,
    "maximum_drawdown": None,
    "edge_per_turnover_bps": None,
    "fold_breadth": None,
    "calendar_transport": None,
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


def iso_from_ts(timestamp: int | None) -> str | None:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, tz=UTC).isoformat().replace(
        "+00:00", "Z"
    )


def parse_server_date(value: str | None) -> int | None:
    if not value:
        return None
    try:
        dt = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp())


def request_bytes(url: str) -> tuple[bytes, dict[str, Any], int]:
    errors: list[str] = []
    for attempt in range(1, 6):
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
                "User-Agent": "Dingding-leo-GPT-venue-fragmentation-source-contract/1.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
                body = response.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise TransientFailure("response exceeded per-response byte cap")
                headers = dict(response.headers.items())
                status = int(getattr(response, "status", 200))
                return (
                    body,
                    {
                        "request_url": url,
                        "final_url": response.geturl(),
                        "http_status": status,
                        "content_type": response.headers.get("Content-Type"),
                        "cache_control": response.headers.get("Cache-Control"),
                        "age": response.headers.get("Age"),
                        "date": response.headers.get("Date"),
                        "server_date_epoch": parse_server_date(
                            response.headers.get("Date")
                        ),
                        "etag": response.headers.get("ETag"),
                        "last_modified": response.headers.get("Last-Modified"),
                        "header_names": sorted(headers),
                        "bytes": len(body),
                        "sha256": digest(body),
                        "attempt": attempt,
                    },
                    status,
                )
        except urllib.error.HTTPError as exc:
            body = exc.read(MAX_RESPONSE_BYTES + 1)
            status = int(exc.code)
            metadata = {
                "request_url": url,
                "final_url": exc.geturl(),
                "http_status": status,
                "content_type": (
                    exc.headers.get("Content-Type") if exc.headers else None
                ),
                "cache_control": (
                    exc.headers.get("Cache-Control") if exc.headers else None
                ),
                "age": exc.headers.get("Age") if exc.headers else None,
                "date": exc.headers.get("Date") if exc.headers else None,
                "server_date_epoch": parse_server_date(
                    exc.headers.get("Date") if exc.headers else None
                ),
                "etag": exc.headers.get("ETag") if exc.headers else None,
                "last_modified": (
                    exc.headers.get("Last-Modified") if exc.headers else None
                ),
                "header_names": sorted(dict(exc.headers.items()))
                if exc.headers
                else [],
                "bytes": len(body),
                "sha256": digest(body),
                "attempt": attempt,
            }
            if status not in RETRYABLE_HTTP:
                return body, metadata, status
            errors.append(f"attempt {attempt}: HTTP {status} body={digest(body)}")
        except (OSError, TimeoutError, urllib.error.URLError, TransientFailure) as exc:
            errors.append(f"attempt {attempt}: {type(exc).__name__}: {exc}")
        if attempt < 5:
            time.sleep(min(2**attempt, 16))
    raise TransientFailure("; ".join(errors))


def save_response(
    root: Path, stem: str, body: bytes, metadata: dict[str, Any]
) -> tuple[str, str]:
    raw_path = root / "raw" / f"{stem}.bin"
    meta_path = root / "raw" / f"{stem}.json"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(body)
    meta_path.write_bytes(canonical(metadata))
    return raw_path.relative_to(root).as_posix(), meta_path.relative_to(root).as_posix()


def parse_json_object(body: bytes, context: str) -> dict[str, Any]:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceFailure(f"{context}: invalid JSON") from exc
    if not isinstance(value, dict):
        raise SourceFailure(f"{context}: top-level JSON is not an object")
    return value


def endpoint_query(
    asset: str,
    venue: str,
    to_ts: int,
    *,
    limit: int = PAGE_LIMIT,
) -> str:
    query = urllib.parse.urlencode(
        {
            "fsym": asset,
            "tsym": QUOTE,
            "e": venue,
            "aggregate": "1",
            "limit": str(limit),
            "toTs": str(to_ts),
            "tryConversion": "false",
            "extraParams": "Dingding-leo-GPT-prospective-strategy-research",
            "sign": "false",
        }
    )
    return f"{ENDPOINT_URL}?{query}"


def validate_request_url(url: str, asset: str, venue: str) -> bool:
    parsed = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    forbidden = {"api_key", "apikey", "key", "token", "access_token", "secret"}
    return bool(
        parsed.scheme == "https"
        and parsed.netloc == PROVIDER_HOST
        and parsed.path == ENDPOINT_PATH
        and parsed.username is None
        and parsed.password is None
        and not parsed.fragment
        and not forbidden.intersection(name.lower() for name in query)
        and query.get("fsym") == [asset]
        and query.get("tsym") == [QUOTE]
        and query.get("e") == [venue]
        and query.get("aggregate") == ["1"]
        and query.get("tryConversion") == ["false"]
        and query.get("sign") == ["false"]
    )


def find_named_object(value: Any, target_name: str) -> dict[str, Any] | None:
    if isinstance(value, dict):
        if value.get("Name") == target_name:
            return value
        for child in value.values():
            found = find_named_object(child, target_name)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_named_object(child, target_name)
            if found is not None:
                return found
    return None


def metadata_snapshot(root: Path) -> dict[str, Any]:
    records: dict[str, Any] = {}
    for label, url in {
        "official_documentation": DOC_URL,
        "provider_schema": SCHEMA_URL,
    }.items():
        body, meta, status = request_bytes(url)
        raw_path, meta_path = save_response(root, f"metadata-{label}", body, meta)
        records[label] = {
            **meta,
            "raw_path": raw_path,
            "metadata_path": meta_path,
            "status_ok": status == 200,
        }
        if label == "provider_schema" and status == 200:
            try:
                records[label]["parsed"] = parse_json_object(body, label)
            except SourceFailure as exc:
                records[label]["parse_error"] = str(exc)
        else:
            text = body.decode("utf-8", errors="replace").lower()
            records[label]["semantic_marker_counts"] = {
                marker: text.count(marker)
                for marker in (
                    "hourly symbol vol. single exchange",
                    "data/exchange/symbol/histohour",
                    "volumefrom",
                    "volumeto",
                    "tots",
                    "limit=2000",
                    "610 seconds",
                )
            }

    schema = records["provider_schema"].get("parsed")
    endpoint = (
        find_named_object(schema, "Hourly Symbol Vol. Single Exchange")
        if schema is not None
        else None
    )
    endpoint_text = json.dumps(endpoint, sort_keys=True).lower() if endpoint else ""
    parameter_names = sorted(
        {
            str(item.get("name"))
            for item in (endpoint or {}).get("Info", {}).get("Parameters", [])
            if isinstance(item, dict) and item.get("name")
        }
    )
    semantic_gate = {
        "endpoint_object_found": endpoint is not None,
        "endpoint_path_documented": "data/exchange/symbol/histohour" in endpoint_text,
        "hourly_semantics_documented": "hourly" in endpoint_text,
        "single_exchange_semantics_documented": (
            "single exchange" in endpoint_text or "on an exchange" in endpoint_text
        ),
        "from_and_to_volume_documented": (
            "from and to volume" in endpoint_text
            or ("volumefrom" in endpoint_text and "volumeto" in endpoint_text)
        ),
        "pagination_documented": (
            "tots" in endpoint_text and "2000" in endpoint_text
        ),
        "cache_610_seconds_documented": (
            "610" in endpoint_text
            or records["official_documentation"]
            .get("semantic_marker_counts", {})
            .get("610 seconds", 0)
            > 0
        ),
        "documented_parameters": parameter_names,
    }
    semantic_gate["passed"] = all(
        semantic_gate[key]
        for key in (
            "endpoint_object_found",
            "endpoint_path_documented",
            "hourly_semantics_documented",
            "single_exchange_semantics_documented",
            "from_and_to_volume_documented",
            "pagination_documented",
            "cache_610_seconds_documented",
        )
    )
    records["semantic_gate"] = semantic_gate
    if endpoint is not None:
        endpoint_bytes = canonical(endpoint)
        endpoint_path = root / "metadata" / "endpoint-schema.json"
        endpoint_path.parent.mkdir(parents=True, exist_ok=True)
        endpoint_path.write_bytes(endpoint_bytes)
        records["provider_schema"]["endpoint_schema_path"] = endpoint_path.relative_to(
            root
        ).as_posix()
        records["provider_schema"]["endpoint_schema_sha256"] = digest(endpoint_bytes)
        records["provider_schema"].pop("parsed", None)
    return records


def parse_numeric(row: dict[str, Any], name: str, context: str) -> float:
    if name not in row:
        raise SourceFailure(f"{context}: missing {name}")
    try:
        value = float(row[name])
    except (TypeError, ValueError) as exc:
        raise SourceFailure(f"{context}: invalid {name}") from exc
    if not math.isfinite(value) or value < 0.0:
        raise SourceFailure(f"{context}: non-finite or negative {name}")
    return value


def parse_rows(
    payload: dict[str, Any], asset: str, venue: str, context: str
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    response_value = payload.get("Response")
    if response_value not in {None, "Success"}:
        raise SourceFailure(
            f"{context}: provider response was {response_value!r}: {payload.get('Message')!r}"
        )
    data = payload.get("Data")
    if not isinstance(data, list) or not data:
        raise SourceFailure(f"{context}: Data is empty or not a list")

    parsed: list[dict[str, Any]] = []
    row_schema_sets: set[tuple[str, ...]] = set()
    conversion_markers: list[dict[str, Any]] = []
    for index, row in enumerate(data):
        if not isinstance(row, dict):
            raise SourceFailure(f"{context}: row {index} is not an object")
        row_schema_sets.add(tuple(sorted(str(key) for key in row)))
        try:
            timestamp = int(row["time"])
        except (KeyError, TypeError, ValueError) as exc:
            raise SourceFailure(f"{context}: invalid time at row {index}") from exc
        if timestamp % HOUR_SECONDS != 0:
            raise SourceFailure(f"{context}: off-grid timestamp {timestamp}")
        volume_from = parse_numeric(row, "volumefrom", context)
        volume_to = parse_numeric(row, "volumeto", context)
        marker = {
            str(key): value
            for key, value in row.items()
            if "conversion" in str(key).lower()
        }
        if marker:
            conversion_markers.append(marker)
        parsed.append(
            {
                "asset": asset,
                "quote": QUOTE,
                "venue": venue,
                "time": timestamp,
                "volumefrom": volume_from,
                "volumeto": volume_to,
                "raw": row,
            }
        )

    times = [row["time"] for row in parsed]
    if any(left >= right for left, right in zip(times, times[1:])):
        raise SourceFailure(f"{context}: rows are not strictly ascending")

    payload_conversion_markers = {
        str(key): value
        for key, value in payload.items()
        if "conversion" in str(key).lower()
    }
    conversion_values = [
        str(value).lower()
        for marker in conversion_markers
        for value in marker.values()
    ] + [str(value).lower() for value in payload_conversion_markers.values()]
    conversion_path_detected = any(
        value not in {"", "none", "null", "direct", "false", "0"}
        for value in conversion_values
    )
    return parsed, {
        "row_schema_sets": [list(schema) for schema in sorted(row_schema_sets)],
        "conversion_marker_row_count": len(conversion_markers),
        "payload_conversion_markers": payload_conversion_markers,
        "conversion_path_detected": conversion_path_detected,
        "provider_response": response_value,
        "provider_type": payload.get("Type"),
        "provider_message": payload.get("Message"),
        "provider_aggregated": payload.get("Aggregated"),
        "provider_time_from": payload.get("TimeFrom"),
        "provider_time_to": payload.get("TimeTo"),
    }


def longest_gap(times: list[int]) -> int:
    if len(times) < 2:
        return 0
    return max(
        max((right - left) // HOUR_SECONDS - 1, 0)
        for left, right in zip(times, times[1:])
    )


def acquire_history(
    root: Path,
    asset: str,
    venue: str,
    label: str,
    requested_end_ts: int,
) -> dict[str, Any]:
    rows_by_time: dict[int, dict[str, Any]] = {}
    page_manifest: list[dict[str, Any]] = []
    duplicate_occurrences = 0
    conflicting_duplicates = 0
    source_failure: str | None = None
    raw_bytes = 0
    schema_sets: set[tuple[str, ...]] = set()
    conversion_path_detected = False
    prior_page_earliest: int | None = None
    current_to_ts = requested_end_ts

    for page_number in range(1, MAX_PAGES_PER_ACQUISITION + 1):
        url = endpoint_query(asset, venue, current_to_ts)
        if not validate_request_url(url, asset, venue):
            source_failure = "request URL failed frozen identity or anonymous-access validation"
            break
        body, meta, status = request_bytes(url)
        raw_path, metadata_path = save_response(
            root,
            f"{asset.lower()}-{venue.lower()}-{label}-page-{page_number:03d}",
            body,
            meta,
        )
        raw_bytes += len(body)
        page_record: dict[str, Any] = {
            **meta,
            "page": page_number,
            "requested_to_ts": current_to_ts,
            "raw_path": raw_path,
            "metadata_path": metadata_path,
        }
        page_manifest.append(page_record)
        if status != 200:
            text = body.decode("utf-8", errors="replace")[:1000]
            source_failure = f"public endpoint returned HTTP {status}: {text}"
            break
        try:
            payload = parse_json_object(body, f"{asset} {venue} {label} page {page_number}")
            parsed, diagnostics = parse_rows(
                payload, asset, venue, f"{asset} {venue} {label} page {page_number}"
            )
            page_times = [row["time"] for row in parsed]
            earliest = page_times[0]
            latest = page_times[-1]
            if latest > current_to_ts:
                raise SourceFailure("provider returned a row after requested toTs")
            if prior_page_earliest is not None and latest >= prior_page_earliest:
                raise SourceFailure("pagination overlapped after earliest-minus-one-hour continuation")
            for schema in diagnostics["row_schema_sets"]:
                schema_sets.add(tuple(schema))
            conversion_path_detected = bool(
                conversion_path_detected or diagnostics["conversion_path_detected"]
            )
            for row in parsed:
                timestamp = row["time"]
                prior = rows_by_time.get(timestamp)
                if prior is not None:
                    duplicate_occurrences += 1
                    if prior["raw"] != row["raw"]:
                        conflicting_duplicates += 1
                else:
                    rows_by_time[timestamp] = row
            page_record.update(
                {
                    "row_count": len(parsed),
                    "earliest_time": iso_from_ts(earliest),
                    "latest_time": iso_from_ts(latest),
                    "diagnostics": diagnostics,
                }
            )
            prior_page_earliest = earliest
            if earliest <= START_TS:
                break
            next_to_ts = earliest - HOUR_SECONDS
            if next_to_ts >= current_to_ts:
                raise SourceFailure("pagination did not move backwards")
            current_to_ts = next_to_ts
        except SourceFailure as exc:
            source_failure = str(exc)
            break
        time.sleep(REQUEST_SLEEP_SECONDS)
    else:
        source_failure = "page budget exhausted before reaching frozen start"

    expected_times = list(range(START_TS, requested_end_ts + HOUR_SECONDS, HOUR_SECONDS))
    expected_set = set(expected_times)
    observed_times = sorted(ts for ts in rows_by_time if START_TS <= ts <= requested_end_ts)
    observed_set = set(observed_times)
    missing = [timestamp for timestamp in expected_times if timestamp not in observed_set]
    extras = [timestamp for timestamp in observed_times if timestamp not in expected_set]
    normalized = [
        {
            "asset": asset,
            "quote": QUOTE,
            "venue": venue,
            "time": timestamp,
            "volumefrom": rows_by_time[timestamp]["volumefrom"],
            "volumeto": rows_by_time[timestamp]["volumeto"],
        }
        for timestamp in observed_times
    ]
    normalized_bytes = canonical(normalized)
    normalized_path = (
        root
        / "normalized"
        / f"{asset.lower()}-{venue.lower()}-{label}.json"
    )
    normalized_path.parent.mkdir(parents=True, exist_ok=True)
    normalized_path.write_bytes(normalized_bytes)

    zero_from = sum(row["volumefrom"] == 0.0 for row in normalized)
    zero_to = sum(row["volumeto"] == 0.0 for row in normalized)
    positive_from = sum(row["volumefrom"] > 0.0 for row in normalized)
    positive_to = sum(row["volumeto"] > 0.0 for row in normalized)
    expected_rows = (requested_end_ts - START_TS) // HOUR_SECONDS + 1
    coverage_passed = bool(
        source_failure is None
        and len(observed_times) == expected_rows
        and not missing
        and not extras
        and duplicate_occurrences == 0
        and conflicting_duplicates == 0
        and observed_times
        and observed_times[0] == START_TS
        and observed_times[-1] == requested_end_ts
    )
    stable_schema_passed = len(schema_sets) == 1
    conversion_free_passed = not conversion_path_detected
    nonnegative_finite_passed = len(normalized) == len(observed_times)
    direct_market_activity_observed = positive_from > 0 and positive_to > 0

    return {
        "asset": asset,
        "quote": QUOTE,
        "venue": venue,
        "label": label,
        "request_start": START,
        "request_end": iso_from_ts(requested_end_ts),
        "expected_rows": expected_rows,
        "observed_rows": len(observed_times),
        "observed_start": iso_from_ts(observed_times[0]) if observed_times else None,
        "observed_end": iso_from_ts(observed_times[-1]) if observed_times else None,
        "missing_count": len(missing),
        "first_missing": iso_from_ts(missing[0]) if missing else None,
        "last_missing": iso_from_ts(missing[-1]) if missing else None,
        "longest_gap_hours": longest_gap(observed_times),
        "extra_count": len(extras),
        "duplicate_occurrence_count": duplicate_occurrences,
        "conflicting_duplicate_count": conflicting_duplicates,
        "page_count": len(page_manifest),
        "pages": page_manifest,
        "raw_response_bytes": raw_bytes,
        "normalized_path": normalized_path.relative_to(root).as_posix(),
        "normalized_sha256": digest(normalized_bytes),
        "row_schema_sets": [list(schema) for schema in sorted(schema_sets)],
        "stable_schema_passed": stable_schema_passed,
        "conversion_path_detected": conversion_path_detected,
        "conversion_free_passed": conversion_free_passed,
        "zero_volumefrom_count": zero_from,
        "zero_volumeto_count": zero_to,
        "positive_volumefrom_count": positive_from,
        "positive_volumeto_count": positive_to,
        "direct_market_activity_observed": direct_market_activity_observed,
        "nonnegative_finite_passed": nonnegative_finite_passed,
        "coverage_passed": coverage_passed,
        "source_failure": source_failure,
        "normalized_rows": normalized,
    }


def availability_probe(root: Path, asset: str, venue: str) -> dict[str, Any]:
    runner_now = int(time.time())
    requested_to_ts = (runner_now // HOUR_SECONDS) * HOUR_SECONDS
    url = endpoint_query(asset, venue, requested_to_ts, limit=72)
    body, meta, status = request_bytes(url)
    raw_path, metadata_path = save_response(
        root, f"availability-{asset.lower()}-{venue.lower()}", body, meta
    )
    result: dict[str, Any] = {
        **meta,
        "raw_path": raw_path,
        "metadata_path": metadata_path,
        "requested_to_ts": requested_to_ts,
        "passed": False,
        "failure": None,
    }
    if status != 200:
        result["failure"] = f"HTTP {status}"
        return result
    try:
        payload = parse_json_object(body, f"availability {asset} {venue}")
        rows, diagnostics = parse_rows(
            payload, asset, venue, f"availability {asset} {venue}"
        )
        server_time = meta.get("server_date_epoch") or runner_now
        latest_completed_hour = (int(server_time) // HOUR_SECONDS) * HOUR_SECONDS - HOUR_SECONDS
        completed_rows = [row for row in rows if row["time"] <= latest_completed_hour]
        if not completed_rows:
            raise SourceFailure("no completed hourly row was available")
        latest = completed_rows[-1]
        availability_lag_hours = (
            int(server_time) - (latest["time"] + HOUR_SECONDS)
        ) / HOUR_SECONDS
        result.update(
            {
                "server_time": iso_from_ts(int(server_time)),
                "latest_completed_expected_hour": iso_from_ts(latest_completed_hour),
                "latest_completed_observed_hour": iso_from_ts(latest["time"]),
                "availability_lag_hours": availability_lag_hours,
                "diagnostics": diagnostics,
                "passed": bool(
                    latest["time"] == latest_completed_hour
                    and -1.0 <= availability_lag_hours <= 24.0
                    and not diagnostics["conversion_path_detected"]
                ),
            }
        )
        if not result["passed"]:
            result["failure"] = "latest completed row or 24-hour availability gate failed"
    except SourceFailure as exc:
        result["failure"] = str(exc)
    return result


def strip_rows(record: dict[str, Any] | None) -> None:
    if record is not None:
        record.pop("normalized_rows", None)


def evaluate_arm(
    root: Path,
    asset: str,
    venue: str,
    semantic_passed: bool,
) -> dict[str, Any]:
    first = acquire_history(root, asset, venue, "first", END_TS)
    repeat: dict[str, Any] | None = None
    suffix: dict[str, Any] | None = None
    repeat_identity = False
    suffix_prefix_identity = False
    availability = availability_probe(root, asset, venue)

    if (
        first["coverage_passed"]
        and first["stable_schema_passed"]
        and first["conversion_free_passed"]
        and first["nonnegative_finite_passed"]
    ):
        repeat = acquire_history(root, asset, venue, "repeat", END_TS)
        suffix = acquire_history(root, asset, venue, "suffix", SUFFIX_END_TS)
        repeat_identity = bool(
            repeat["coverage_passed"]
            and repeat["normalized_sha256"] == first["normalized_sha256"]
        )
        suffix_rows = suffix.get("normalized_rows", []) if suffix else []
        suffix_prefix = suffix_rows[:EXPECTED_ROWS]
        suffix_prefix_identity = bool(
            suffix
            and suffix["coverage_passed"]
            and len(suffix_prefix) == EXPECTED_ROWS
            and digest(canonical(suffix_prefix)) == first["normalized_sha256"]
        )

    total_raw_bytes = first["raw_response_bytes"]
    for record in (repeat, suffix):
        if record is not None:
            total_raw_bytes += record["raw_response_bytes"]

    passed = bool(
        semantic_passed
        and first["coverage_passed"]
        and first["stable_schema_passed"]
        and first["conversion_free_passed"]
        and first["nonnegative_finite_passed"]
        and first["direct_market_activity_observed"]
        and repeat_identity
        and suffix_prefix_identity
        and availability["passed"]
        and total_raw_bytes <= MAX_TOTAL_RAW_BYTES
    )

    strip_rows(first)
    strip_rows(repeat)
    strip_rows(suffix)
    return {
        "asset": asset,
        "quote": QUOTE,
        "venue": venue,
        "expected_rows": EXPECTED_ROWS,
        "first_acquisition": first,
        "repeat_acquisition": repeat,
        "future_suffix_acquisition": suffix,
        "availability_probe": availability,
        "repeat_normalized_identity": repeat_identity,
        "future_suffix_prefix_identity": suffix_prefix_identity,
        "total_raw_response_bytes": total_raw_bytes,
        "source_contract_passed": passed,
        "economics": dict(NULL_ECONOMICS),
    }


def source_manifest(root: Path, evidence: dict[str, Any]) -> dict[str, Any]:
    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name in {
            "source_manifest.json",
            "source_manifest.sha256",
        }:
            continue
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": digest(path.read_bytes()),
            }
        )
    return {
        "family_id": FAMILY_ID,
        "tested_head": evidence["tested_head"],
        "generated_at": evidence["generated_at"],
        "file_count": len(files),
        "total_bytes": sum(item["bytes"] for item in files),
        "files": files,
    }


def write_outputs(root: Path, evidence: dict[str, Any]) -> None:
    evidence_bytes = canonical(evidence)
    (root / "evidence.json").write_bytes(evidence_bytes)
    (root / "evidence.sha256").write_text(digest(evidence_bytes) + "\n")

    manifest = source_manifest(root, evidence)
    manifest_bytes = canonical(manifest)
    (root / "source_manifest.json").write_bytes(manifest_bytes)
    (root / "source_manifest.sha256").write_text(digest(manifest_bytes) + "\n")

    lines = [
        "# Same-asset venue-fragmentation public 1H source contract",
        "",
        f"- Family: `{FAMILY_ID}`",
        f"- Exact evidence head: `{evidence['tested_head']}`",
        f"- Fixed interval: `{START}` through `{END}`",
        f"- Source arms passing: `{evidence['source_arms_passing']}/6`",
        f"- Source verdict: `{evidence['verdict']}`",
        "- No target price, feature, candidate, return, performance or OOS was accessed.",
        "",
        "| Asset | Venue | Rows | Pages | Missing | Zeros from/to | Repeat | Suffix prefix | <=24H | Pass |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for arm in evidence["source_arms"]:
        first = arm["first_acquisition"]
        lines.append(
            f"| {arm['asset']} | {arm['venue']} | {first['observed_rows']} | "
            f"{first['page_count']} | {first['missing_count']} | "
            f"{first['zero_volumefrom_count']}/{first['zero_volumeto_count']} | "
            f"{arm['repeat_normalized_identity']} | "
            f"{arm['future_suffix_prefix_identity']} | "
            f"{arm['availability_probe']['passed']} | "
            f"{arm['source_contract_passed']} |"
        )
    lines.extend(
        [
            "",
            "All strategy-economic fields are null. A six-arm pass authorises only a "
            "separately preregistered training-only rule; it does not authorise a "
            "candidate, canonical mutation, paper trading or live trading.",
        ]
    )
    (root / "report.md").write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tested-head", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    if not os.environ.get("GITHUB_ACTIONS"):
        workflow_environment = False
    else:
        workflow_environment = True

    root = Path(args.output_dir)
    root.mkdir(parents=True, exist_ok=True)
    metadata = metadata_snapshot(root)
    semantic_passed = bool(metadata["semantic_gate"]["passed"])

    arms = [
        evaluate_arm(root, asset, venue, semantic_passed)
        for asset in ASSETS
        for venue in VENUES
    ]
    source_arms_passing = sum(arm["source_contract_passed"] for arm in arms)
    raw_bytes = sum(arm["total_raw_response_bytes"] for arm in arms)
    total_artifact_bytes_before_outputs = sum(
        path.stat().st_size for path in root.rglob("*") if path.is_file()
    )
    six_arm_pass = bool(
        semantic_passed
        and source_arms_passing == 6
        and raw_bytes <= MAX_TOTAL_RAW_BYTES
        and total_artifact_bytes_before_outputs <= MAX_TOTAL_RAW_BYTES
    )

    evidence = {
        "family_id": FAMILY_ID,
        "tested_head": args.tested_head,
        "repository_main": REPOSITORY_MAIN,
        "generated_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        "classification": (
            "source-contract-first materially orthogonal same-asset market-structure experiment"
        ),
        "bar": "1H",
        "canonical_fee_bps_one_way": 5.0,
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "target_arms": ["BTC-USDT", "ETH-USDT"],
        "fixed_external_panel": {
            "assets": list(ASSETS),
            "quote": QUOTE,
            "venues": list(VENUES),
            "endpoint": ENDPOINT_URL,
            "aggregate": 1,
            "try_conversion": False,
            "start": START,
            "end": END,
            "expected_rows_per_arm": EXPECTED_ROWS,
            "arm_count": 6,
        },
        "provider_cache_contract": {
            "documented_cache_seconds": 610,
            "cached_response_is_not_treated_as_immutability": True,
            "repeat_and_suffix_prefix_replays_required": True,
        },
        "metadata": metadata,
        "source_arms": arms,
        "source_arm_count": 6,
        "source_arms_passing": source_arms_passing,
        "source_contract_passed": six_arm_pass,
        "total_raw_response_bytes": raw_bytes,
        "artifact_bytes_before_outputs": total_artifact_bytes_before_outputs,
        "evidence_ceiling_bytes": MAX_TOTAL_RAW_BYTES,
        "verdict": PASS_VERDICT if six_arm_pass else FAIL_VERDICT,
        "workflow_environment_observed": workflow_environment,
        "target_price_data_downloaded": False,
        "target_returns_downloaded": False,
        "venue_shares_calculated": False,
        "hhi_or_fragmentation_calculated": False,
        "feature_defined": False,
        "candidate_created": False,
        "performance_accessed": False,
        "oos_accessed": False,
        "synthetic_data_used": False,
        "interpolation_or_fill_used": False,
        "credentials_used": False,
        "private_endpoints_used": False,
        "accounts_balances_or_orders": False,
        "enabled_adapters": False,
        "leverage_or_funds_used": False,
        "cross_sectional_asset_selection": False,
        "current_relative_rank": False,
        "top_n_rotation": False,
        "pairs_spreads_cointegration_or_stat_arb": False,
        "market_neutral_or_long_short": False,
        "venue_trading_or_selection": False,
        "canonical_strategy_changed": False,
        "observation_epoch_restarted": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
    }
    write_outputs(root, evidence)
    print(
        json.dumps(
            {
                "tested_head": args.tested_head,
                "source_arms_passing": source_arms_passing,
                "source_contract_passed": six_arm_pass,
                "verdict": evidence["verdict"],
                "evidence_sha256": digest(canonical(evidence)),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
