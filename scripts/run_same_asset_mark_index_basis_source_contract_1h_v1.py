from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FAMILY_ID = "causal-same-asset-mark-index-basis-source-contract-1h-v1"
PASS_VERDICT = (
    "accept_same_asset_mark_index_basis_1h_source_for_separate_training_only_"
    "predeclaration"
)
FAIL_VERDICT = "reject_causal_same_asset_mark_index_basis_source_contract_1h_v1"
REPOSITORY_MAIN = "5a0fcc97d1a882f8223656c51f5bb8055f534e38"
BASE_URL = "https://www.okx.com"
HOST = "www.okx.com"
MARK_PATH = "/api/v5/market/history-mark-price-candles"
INDEX_PATH = "/api/v5/market/history-index-candles"
DOC_URLS = {
    "mark": (
        "https://www.okx.com/docs-v5/en/"
        "#rest-api-public-data-get-mark-price-candlesticks-history"
    ),
    "index": (
        "https://www.okx.com/docs-v5/en/"
        "#rest-api-market-data-get-index-candlesticks-history"
    ),
}
SERIES = (
    ("BTC", "mark", "BTC-USDT-SWAP", MARK_PATH),
    ("BTC", "index", "BTC-USDT", INDEX_PATH),
    ("ETH", "mark", "ETH-USDT-SWAP", MARK_PATH),
    ("ETH", "index", "ETH-USDT", INDEX_PATH),
)
START = "2023-04-01T00:00:00Z"
END = "2025-12-31T23:00:00Z"
SUFFIX_END = "2026-01-01T00:00:00Z"
START_MS = 1_680_307_200_000
END_MS = 1_767_222_000_000
SUFFIX_END_MS = 1_767_225_600_000
HOUR_MS = 3_600_000
EXPECTED_ROWS = 24_144
LIMIT = 100
MAX_PAGES = 260
PAUSE_SECONDS = 0.115
MAX_RESPONSE_BYTES = 2_000_000
MAX_TOTAL_RAW_BYTES = 2 * 1024 * 1024 * 1024
RETRYABLE = {408, 425, 429, 500, 502, 503, 504}

NULL_ECONOMICS = {
    "basis_feature": None,
    "candidate_state": None,
    "train_net_return": None,
    "train_sharpe": None,
    "oos_net_return": None,
    "oos_sharpe": None,
    "full_net_return": None,
    "full_sharpe": None,
    "e2160_net_return": None,
    "e2160_sharpe": None,
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


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


OPENER = urllib.request.build_opener(NoRedirect)


def canonical(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode()


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def iso_ms(value: int | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1000, tz=UTC).isoformat().replace(
        "+00:00", "Z"
    )


def strict_json(body: bytes, context: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise SourceFailure(f"{context}: duplicate JSON field {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceFailure(f"{context}: invalid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise SourceFailure(f"{context}: top-level response is not an object")
    return value


def request_bytes(url: str) -> tuple[bytes, dict[str, Any], int]:
    attempts: list[str] = []
    for attempt in range(1, 6):
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
                "User-Agent": "Dingding-leo-GPT-mark-index-basis-source/1.0",
            },
        )
        started = datetime.now(UTC).isoformat()
        try:
            with OPENER.open(request, timeout=40) as response:  # noqa: S310
                body = response.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise TransientFailure("response exceeded byte cap")
                status = int(getattr(response, "status", 200))
                final_url = response.geturl()
                metadata = {
                    "request_url": url,
                    "final_url": final_url,
                    "status": status,
                    "started_utc": started,
                    "received_utc": datetime.now(UTC).isoformat(),
                    "content_type": response.headers.get("Content-Type"),
                    "date": response.headers.get("Date"),
                    "cache_control": response.headers.get("Cache-Control"),
                    "etag": response.headers.get("ETag"),
                    "last_modified": response.headers.get("Last-Modified"),
                    "bytes": len(body),
                    "sha256": sha256(body),
                    "attempt": attempt,
                }
                return body, metadata, status
        except urllib.error.HTTPError as exc:
            body = exc.read(MAX_RESPONSE_BYTES + 1)
            status = int(exc.code)
            metadata = {
                "request_url": url,
                "final_url": exc.geturl(),
                "status": status,
                "started_utc": started,
                "received_utc": datetime.now(UTC).isoformat(),
                "content_type": (
                    exc.headers.get("Content-Type") if exc.headers else None
                ),
                "date": exc.headers.get("Date") if exc.headers else None,
                "cache_control": (
                    exc.headers.get("Cache-Control") if exc.headers else None
                ),
                "etag": exc.headers.get("ETag") if exc.headers else None,
                "last_modified": (
                    exc.headers.get("Last-Modified") if exc.headers else None
                ),
                "bytes": len(body),
                "sha256": sha256(body),
                "attempt": attempt,
            }
            if status not in RETRYABLE:
                return body, metadata, status
            attempts.append(f"attempt {attempt}: HTTP {status} {sha256(body)}")
        except (OSError, TimeoutError, urllib.error.URLError, TransientFailure) as exc:
            attempts.append(f"attempt {attempt}: {type(exc).__name__}: {exc}")
        if attempt < 5:
            time.sleep(min(2**attempt, 16))
    raise TransientFailure("; ".join(attempts))


def save_raw(
    root: Path,
    series_id: str,
    acquisition_id: str,
    page_number: int,
    body: bytes,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    directory = root / "raw" / series_id / acquisition_id
    directory.mkdir(parents=True, exist_ok=True)
    body_path = directory / f"page-{page_number:04d}.json"
    meta_path = directory / f"page-{page_number:04d}.metadata.json"
    body_path.write_bytes(body)
    meta_path.write_bytes(canonical(metadata))
    return {
        "body_path": body_path.relative_to(root).as_posix(),
        "metadata_path": meta_path.relative_to(root).as_posix(),
        **metadata,
    }


def query_url(path: str, inst_id: str, cursor_ms: int) -> str:
    query = urllib.parse.urlencode(
        {
            "instId": inst_id,
            "bar": "1H",
            "after": str(cursor_ms),
            "limit": str(LIMIT),
        }
    )
    return f"{BASE_URL}{path}?{query}"


def request_identity_ok(url: str, path: str, inst_id: str, cursor_ms: int) -> bool:
    parsed = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    forbidden = {"api_key", "apikey", "key", "token", "secret", "passphrase"}
    return bool(
        parsed.scheme == "https"
        and parsed.netloc == HOST
        and parsed.path == path
        and parsed.username is None
        and parsed.password is None
        and not parsed.fragment
        and not forbidden.intersection(key.lower() for key in query)
        and query.get("instId") == [inst_id]
        and query.get("bar") == ["1H"]
        and query.get("after") == [str(cursor_ms)]
        and query.get("limit") == [str(LIMIT)]
    )


def finite_positive(value: Any, name: str, context: str) -> str:
    if not isinstance(value, str):
        raise SourceFailure(f"{context}: {name} must be a provider string")
    try:
        number = float(value)
    except ValueError as exc:
        raise SourceFailure(f"{context}: {name} is not numeric") from exc
    if not math.isfinite(number) or number <= 0:
        raise SourceFailure(f"{context}: {name} is non-positive or non-finite")
    return value


def parse_page(
    payload: dict[str, Any],
    *,
    context: str,
) -> list[tuple[str, str, str, str, str, str]]:
    if set(payload) != {"code", "msg", "data"}:
        raise SourceFailure(f"{context}: top-level fields differ from OKX schema")
    if payload["code"] != "0" or not isinstance(payload["msg"], str):
        raise SourceFailure(
            f"{context}: provider error code={payload.get('code')!r} "
            f"message={payload.get('msg')!r}"
        )
    data = payload["data"]
    if not isinstance(data, list):
        raise SourceFailure(f"{context}: data is not a list")
    parsed: list[tuple[str, str, str, str, str, str]] = []
    timestamps: list[int] = []
    for row_number, row in enumerate(data, start=1):
        if not isinstance(row, list) or len(row) != 6:
            raise SourceFailure(
                f"{context}: row {row_number} must contain exactly six fields"
            )
        if any(not isinstance(value, str) for value in row):
            raise SourceFailure(f"{context}: row {row_number} contains non-string fields")
        try:
            timestamp = int(row[0])
        except ValueError as exc:
            raise SourceFailure(f"{context}: invalid timestamp") from exc
        if timestamp % HOUR_MS:
            raise SourceFailure(f"{context}: off-grid timestamp {timestamp}")
        open_value = finite_positive(row[1], "open", context)
        high_value = finite_positive(row[2], "high", context)
        low_value = finite_positive(row[3], "low", context)
        close_value = finite_positive(row[4], "close", context)
        if row[5] != "1":
            raise SourceFailure(f"{context}: incomplete candle at {timestamp}")
        prices = [float(open_value), float(high_value), float(low_value), float(close_value)]
        if prices[1] < max(prices[0], prices[2], prices[3]):
            raise SourceFailure(f"{context}: high consistency failure at {timestamp}")
        if prices[2] > min(prices[0], prices[1], prices[3]):
            raise SourceFailure(f"{context}: low consistency failure at {timestamp}")
        parsed.append(tuple(row))
        timestamps.append(timestamp)
    if any(newer <= older for newer, older in zip(timestamps, timestamps[1:])):
        raise SourceFailure(f"{context}: page is not strictly newest-to-oldest")
    return parsed


def acquire(
    root: Path,
    *,
    asset: str,
    series_type: str,
    inst_id: str,
    path: str,
    acquisition_id: str,
    requested_end_ms: int,
) -> dict[str, Any]:
    series_id = f"{asset.lower()}-{series_type}"
    cursor = requested_end_ms + HOUR_MS
    previous_oldest: int | None = None
    seen: dict[int, tuple[str, str, str, str, str, str]] = {}
    page_records: list[dict[str, Any]] = []
    exact_duplicates = 0
    raw_rows = 0

    for page_number in range(1, MAX_PAGES + 1):
        url = query_url(path, inst_id, cursor)
        if not request_identity_ok(url, path, inst_id, cursor):
            raise SourceFailure(f"{series_id}: request identity validation failed")
        body, metadata, status = request_bytes(url)
        metadata.update(
            {
                "asset": asset,
                "series_type": series_type,
                "inst_id": inst_id,
                "endpoint_path": path,
                "bar": "1H",
                "cursor_ms": cursor,
                "cursor_utc": iso_ms(cursor),
                "page_number": page_number,
                "acquisition_id": acquisition_id,
            }
        )
        page_records.append(
            save_raw(
                root,
                series_id,
                acquisition_id,
                page_number,
                body,
                metadata,
            )
        )
        if status != 200:
            text = body.decode("utf-8", errors="replace")[:1000]
            raise SourceFailure(
                f"{series_id}: HTTP {status} at page {page_number}: {text!r}"
            )
        if metadata["final_url"] != url:
            raise SourceFailure(f"{series_id}: redirect or URL mutation detected")
        payload = strict_json(body, f"{series_id} page {page_number}")
        rows = parse_page(payload, context=f"{series_id} page {page_number}")
        if not rows:
            raise SourceFailure(f"{series_id}: empty page before reaching start")
        timestamps = [int(row[0]) for row in rows]
        newest = timestamps[0]
        oldest = timestamps[-1]
        if previous_oldest is not None and newest > previous_oldest:
            raise SourceFailure(f"{series_id}: page returned rows newer than cursor")
        if previous_oldest is not None and oldest >= previous_oldest:
            raise SourceFailure(f"{series_id}: pagination did not move backward")
        for row in rows:
            timestamp = int(row[0])
            previous = seen.get(timestamp)
            if previous is not None:
                if previous != row:
                    raise SourceFailure(
                        f"{series_id}: conflicting duplicate timestamp {timestamp}"
                    )
                exact_duplicates += 1
            else:
                seen[timestamp] = row
        raw_rows += len(rows)
        previous_oldest = oldest
        if oldest <= START_MS:
            break
        if len(rows) < LIMIT:
            raise SourceFailure(
                f"{series_id}: short page before requested start "
                f"(oldest={iso_ms(oldest)})"
            )
        cursor = oldest
        time.sleep(PAUSE_SECONDS)
    else:
        raise SourceFailure(f"{series_id}: page budget exhausted")

    rows_in_range = [
        seen[timestamp]
        for timestamp in sorted(seen)
        if START_MS <= timestamp <= END_MS
    ]
    expected_grid = list(range(START_MS, END_MS + HOUR_MS, HOUR_MS))
    observed_grid = [int(row[0]) for row in rows_in_range]
    observed_set = set(observed_grid)
    expected_set = set(expected_grid)
    missing = sorted(expected_set - observed_set)
    extra = sorted(observed_set - expected_set)
    row_bytes = canonical(rows_in_range)
    normalized_path = root / "normalized" / f"{series_id}-{acquisition_id}.json"
    normalized_path.parent.mkdir(parents=True, exist_ok=True)
    normalized_path.write_bytes(row_bytes)

    return {
        "asset": asset,
        "series_type": series_type,
        "series_id": series_id,
        "inst_id": inst_id,
        "endpoint_path": path,
        "acquisition_id": acquisition_id,
        "requested_start": START,
        "requested_end": iso_ms(requested_end_ms),
        "expected_rows": EXPECTED_ROWS,
        "observed_rows": len(rows_in_range),
        "first_observed": iso_ms(observed_grid[0]) if observed_grid else None,
        "last_observed": iso_ms(observed_grid[-1]) if observed_grid else None,
        "missing_rows": len(missing),
        "missing_first_20": [iso_ms(value) for value in missing[:20]],
        "extra_rows": len(extra),
        "extra_first_20": [iso_ms(value) for value in extra[:20]],
        "raw_rows": raw_rows,
        "exact_duplicates": exact_duplicates,
        "pages": len(page_records),
        "page_records": page_records,
        "normalized_path": normalized_path.relative_to(root).as_posix(),
        "normalized_sha256": sha256(row_bytes),
        "page_manifest_sha256": sha256(canonical(page_records)),
        "grid_complete": observed_grid == expected_grid,
    }


def snapshot_docs(root: Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, url in DOC_URLS.items():
        try:
            body, metadata, status = request_bytes(url)
        except TransientFailure as exc:
            result[name] = {"url": url, "transient_error": str(exc), "status_ok": False}
            continue
        directory = root / "documentation"
        directory.mkdir(parents=True, exist_ok=True)
        body_path = directory / f"{name}.html"
        meta_path = directory / f"{name}.metadata.json"
        body_path.write_bytes(body)
        meta_path.write_bytes(canonical(metadata))
        text = body.decode("utf-8", errors="replace").lower()
        result[name] = {
            **metadata,
            "url": url,
            "body_path": body_path.relative_to(root).as_posix(),
            "metadata_path": meta_path.relative_to(root).as_posix(),
            "status_ok": status == 200,
            "semantic_markers": {
                "history_mark_price_candles": text.count(
                    "history-mark-price-candles"
                ),
                "history_index_candles": text.count("history-index-candles"),
                "1h": text.count("1h"),
                "limit_100": text.count("100"),
            },
        }
    return result


def run(*, tested_head: str, output_dir: Path) -> dict[str, Any]:
    if len(tested_head) != 40 or any(char not in "0123456789abcdef" for char in tested_head):
        raise ValueError("tested head must be a lowercase 40-character SHA")
    output_dir.mkdir(parents=True, exist_ok=True)
    documentation = snapshot_docs(output_dir)
    arms: list[dict[str, Any]] = []
    acquisitions: dict[str, dict[str, dict[str, Any]]] = {}
    transient_errors: list[str] = []

    for asset, series_type, inst_id, path in SERIES:
        series_id = f"{asset.lower()}-{series_type}"
        acquisitions[series_id] = {}
        failures: list[str] = []
        for acquisition_id, requested_end_ms in (
            ("primary", END_MS),
            ("repeat", END_MS),
            ("suffix", SUFFIX_END_MS),
        ):
            try:
                acquisition = acquire(
                    output_dir,
                    asset=asset,
                    series_type=series_type,
                    inst_id=inst_id,
                    path=path,
                    acquisition_id=acquisition_id,
                    requested_end_ms=requested_end_ms,
                )
                acquisitions[series_id][acquisition_id] = acquisition
            except TransientFailure as exc:
                transient_errors.append(f"{series_id}/{acquisition_id}: {exc}")
                break
            except SourceFailure as exc:
                failures.append(f"{acquisition_id}: {exc}")
                break

        values = acquisitions[series_id]
        primary = values.get("primary")
        repeat = values.get("repeat")
        suffix = values.get("suffix")
        repeat_identity = bool(
            primary
            and repeat
            and primary["normalized_sha256"] == repeat["normalized_sha256"]
        )
        suffix_identity = bool(
            primary
            and suffix
            and primary["normalized_sha256"] == suffix["normalized_sha256"]
        )
        source_passed = bool(
            not failures
            and primary
            and repeat
            and suffix
            and primary["grid_complete"]
            and repeat["grid_complete"]
            and suffix["grid_complete"]
            and repeat_identity
            and suffix_identity
        )
        arms.append(
            {
                "asset": asset,
                "series_type": series_type,
                "series_id": series_id,
                "inst_id": inst_id,
                "endpoint_path": path,
                "expected_rows": EXPECTED_ROWS,
                "source_contract_passed": source_passed,
                "failures": failures,
                "repeat_normalized_identity": repeat_identity,
                "future_suffix_prefix_identity": suffix_identity,
                "primary": primary,
                "repeat": repeat,
                "suffix": suffix,
                "economics": dict(NULL_ECONOMICS),
            }
        )

    if transient_errors:
        raise TransientFailure("; ".join(transient_errors))

    common_grid: dict[str, Any] = {}
    for asset in ("BTC", "ETH"):
        mark = acquisitions.get(f"{asset.lower()}-mark", {}).get("primary")
        index = acquisitions.get(f"{asset.lower()}-index", {}).get("primary")
        same_hash = False
        same_timestamps = False
        if mark and index:
            mark_rows = json.loads((output_dir / mark["normalized_path"]).read_text())
            index_rows = json.loads((output_dir / index["normalized_path"]).read_text())
            same_timestamps = [row[0] for row in mark_rows] == [
                row[0] for row in index_rows
            ]
            same_hash = sha256(canonical([row[0] for row in mark_rows])) == sha256(
                canonical([row[0] for row in index_rows])
            )
        common_grid[asset] = {
            "mark_index_same_timestamps": same_timestamps,
            "timestamp_grid_sha256_equal": same_hash,
        }

    all_arms_pass = all(arm["source_contract_passed"] for arm in arms)
    common_grid_pass = all(
        value["mark_index_same_timestamps"] for value in common_grid.values()
    )
    raw_files = (
        list((output_dir / "raw").rglob("*"))
        if (output_dir / "raw").exists()
        else []
    )
    total_raw_bytes = sum(path.stat().st_size for path in raw_files if path.is_file())
    source_contract_passed = bool(
        all_arms_pass
        and common_grid_pass
        and total_raw_bytes <= MAX_TOTAL_RAW_BYTES
    )
    source_manifest = {
        "family_id": FAMILY_ID,
        "tested_head": tested_head,
        "provider": "OKX",
        "base_url": BASE_URL,
        "bar": "1H",
        "period": {"start": START, "end": END, "expected_rows": EXPECTED_ROWS},
        "series": [
            {
                "asset": asset,
                "series_type": series_type,
                "inst_id": inst_id,
                "endpoint_path": path,
            }
            for asset, series_type, inst_id, path in SERIES
        ],
        "documentation": documentation,
        "arms": arms,
        "common_grid": common_grid,
        "total_raw_response_and_metadata_bytes": total_raw_bytes,
    }
    source_manifest_bytes = canonical(source_manifest)
    (output_dir / "source_manifest.json").write_bytes(source_manifest_bytes)
    (output_dir / "source_manifest.sha256").write_text(
        sha256(source_manifest_bytes) + "\n"
    )

    evidence = {
        "family_id": FAMILY_ID,
        "tested_head": tested_head,
        "repository_main": REPOSITORY_MAIN,
        "issue": 941,
        "provider": "OKX",
        "bar": "1H",
        "canonical_fee_bps_one_way": 5.0,
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "source_arm_count": 4,
        "source_arms_passing": sum(
            arm["source_contract_passed"] for arm in arms
        ),
        "source_contract_passed": source_contract_passed,
        "common_grid_passed": common_grid_pass,
        "source_arms": arms,
        "common_grid": common_grid,
        "total_raw_response_and_metadata_bytes": total_raw_bytes,
        "evidence_ceiling_bytes": MAX_TOTAL_RAW_BYTES,
        "source_manifest_sha256": sha256(source_manifest_bytes),
        "target_price_data_downloaded": False,
        "target_returns_downloaded": False,
        "basis_calculated": False,
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
        "post_hoc_asset_filtering": False,
        "canonical_strategy_changed": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "verdict": PASS_VERDICT if source_contract_passed else FAIL_VERDICT,
    }
    evidence_bytes = canonical(evidence)
    (output_dir / "evidence.json").write_bytes(evidence_bytes)
    (output_dir / "evidence.sha256").write_text(sha256(evidence_bytes) + "\n")

    lines = [
        "# Same-asset mark/index basis 1H source contract",
        "",
        "```text",
        f"family                 {FAMILY_ID}",
        f"tested head            {tested_head}",
        f"period                 {START} through {END}",
        f"expected rows/arm      {EXPECTED_ROWS}",
        f"source arms passing    {evidence['source_arms_passing']}/4",
        "candidate count        0",
        "performance accessed   no",
        "OOS accessed           no",
        f"verdict                {evidence['verdict']}",
        "```",
        "",
        "## Arms",
        "",
        "| Asset | Series | Rows | Repeat | Suffix-prefix | Result |",
        "|---|---|---:|---:|---:|---|",
    ]
    for arm in arms:
        primary = arm["primary"] or {}
        lines.append(
            "| {asset} | {kind} | {rows} | {repeat} | {suffix} | {result} |".format(
                asset=arm["asset"],
                kind=arm["series_type"],
                rows=primary.get("observed_rows"),
                repeat=arm["repeat_normalized_identity"],
                suffix=arm["future_suffix_prefix_identity"],
                result="pass" if arm["source_contract_passed"] else "fail",
            )
        )
        if arm["failures"]:
            lines.append(
                f"\nFailure `{arm['series_id']}`: " + " | ".join(arm["failures"])
            )
    lines.extend(
        [
            "",
            "No basis value, target return, candidate, benchmark, turnover, "
            "drawdown, uncertainty, or delayed-execution metric was calculated.",
            "",
            f"Source manifest SHA-256: `{evidence['source_manifest_sha256']}`",
            f"Evidence SHA-256: `{sha256(evidence_bytes)}`",
        ]
    )
    (output_dir / "report.md").write_text("\n".join(lines) + "\n")
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tested-head", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args()
    evidence = run(
        tested_head=arguments.tested_head,
        output_dir=arguments.output_dir,
    )
    print(
        json.dumps(
            {
                "verdict": evidence["verdict"],
                "source_arms_passing": evidence["source_arms_passing"],
                "source_contract_passed": evidence["source_contract_passed"],
                "evidence_sha256": sha256(canonical(evidence)),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
