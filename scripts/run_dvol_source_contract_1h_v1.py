from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FAMILY_ID = "causal-dvol-regime-adaptive-e2160-sizing-source-contract-1h-v1"
PASS_VERDICT = "accept_dvol_1h_source_contract_for_separate_training_only_predeclaration"
FAIL_VERDICT = "reject_causal_dvol_regime_adaptive_e2160_sizing_source_contract_1h_v1"
REPOSITORY_MAIN = "5a0fcc97d1a882f8223656c51f5bb8055f534e38"
ENDPOINT = "https://www.deribit.com/api/v2/public/get_volatility_index_data"
DOC_URL = "https://docs.deribit.com/api-reference/market-data/public-get_volatility_index_data.md"
START_MS = 1_617_235_200_000  # 2021-04-01T00:00:00Z
END_MS = 1_767_222_000_000  # 2025-12-31T23:00:00Z
HOUR_MS = 3_600_000
EXPECTED_ROWS = 41_664
MAX_PAGES = 128
MAX_BYTES = 8_000_000

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


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def iso(ms: int | None) -> str | None:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat().replace("+00:00", "Z")


def get(url: str) -> tuple[bytes, dict[str, Any]]:
    errors: list[str] = []
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Dingding-leo-GPT-DVOL-source-contract/1.0",
            "Accept": "application/json,text/markdown,text/plain;q=0.9,*/*;q=0.8",
        },
    )
    for attempt in range(1, 5):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read(MAX_BYTES + 1)
                if len(body) > MAX_BYTES:
                    raise ValueError("response exceeds immutable byte cap")
                return body, {
                    "request_url": url,
                    "final_url": response.geturl(),
                    "http_status": getattr(response, "status", 200),
                    "content_type": response.headers.get("Content-Type"),
                    "bytes": len(body),
                    "sha256": digest(body),
                    "attempt": attempt,
                }
        except (OSError, ValueError, urllib.error.URLError) as exc:
            errors.append(f"attempt {attempt}: {type(exc).__name__}: {exc}")
            if attempt < 4:
                time.sleep(min(2**attempt, 8))
    raise RuntimeError("; ".join(errors))


def fetch_doc(root: Path) -> dict[str, Any]:
    path = root / "official-docs" / "get-volatility-index-data.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        body, metadata = get(DOC_URL)
        path.write_bytes(body)
        text = body.decode("utf-8", errors="replace").lower()
        markers = {
            phrase: text.count(phrase)
            for phrase in (
                "volatility index",
                "market expectations of future volatility",
                "3600",
                "continuation",
                "timestamp",
                "open",
                "high",
                "low",
                "close",
            )
        }
        semantic_pass = (
            markers["volatility index"] > 0
            and markers["3600"] > 0
            and markers["continuation"] > 0
            and all(markers[name] > 0 for name in ("timestamp", "open", "high", "low", "close"))
        )
        return {
            **metadata,
            "url": DOC_URL,
            "saved_path": path.as_posix(),
            "retrieval_succeeded": True,
            "semantic_markers": markers,
            "semantic_pass": semantic_pass,
            "provider_semantics": "volatility index measuring market expectations of future volatility",
        }
    except Exception as exc:
        return {
            "url": DOC_URL,
            "saved_path": None,
            "retrieval_succeeded": False,
            "semantic_markers": {},
            "semantic_pass": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def url(currency: str, end_ms: int) -> str:
    query = urllib.parse.urlencode(
        {
            "currency": currency,
            "start_timestamp": START_MS,
            "end_timestamp": end_ms,
            "resolution": "3600",
        }
    )
    return f"{ENDPOINT}?{query}"


def row(value: Any) -> tuple[int, float, float, float, float]:
    if not isinstance(value, list) or len(value) != 5:
        raise ValueError("DVOL candle must contain timestamp/open/high/low/close")
    timestamp = value[0]
    if isinstance(timestamp, bool) or not isinstance(timestamp, int):
        raise ValueError("timestamp is not integer milliseconds")
    numbers: list[float] = []
    for item in value[1:]:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValueError("non-numeric DVOL OHLC")
        number = float(item)
        if not math.isfinite(number) or number <= 0:
            raise ValueError("DVOL OHLC must be finite and positive")
        numbers.append(number)
    open_, high, low, close = numbers
    if high < max(open_, low, close) or low > min(open_, high, close):
        raise ValueError("invalid DVOL OHLC ordering")
    return timestamp, open_, high, low, close


def acquire(currency: str, end_ms: int, root: Path, name: str) -> dict[str, Any]:
    target = root / "source" / currency / name
    target.mkdir(parents=True, exist_ok=True)
    request_end = end_ms
    pages: list[dict[str, Any]] = []
    raw: list[tuple[int, float, float, float, float]] = []
    seen_continuations: set[int] = set()

    for index in range(MAX_PAGES):
        body, metadata = get(url(currency, request_end))
        page_path = target / f"page-{index:03d}.json"
        page_path.write_bytes(body)
        payload = json.loads(body)
        if payload.get("jsonrpc") != "2.0" or payload.get("error") is not None:
            raise ValueError(f"invalid Deribit JSON-RPC response: {payload.get('error')}")
        result = payload.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("data"), list):
            raise ValueError("missing result.data")
        normalized_page = [row(value) for value in result["data"]]
        continuation = result.get("continuation")
        if continuation is not None and (isinstance(continuation, bool) or not isinstance(continuation, int)):
            raise ValueError("continuation is not integer or null")
        pages.append(
            {
                **metadata,
                "saved_path": page_path.as_posix(),
                "requested_end_ms": request_end,
                "requested_end": iso(request_end),
                "row_count": len(normalized_page),
                "minimum_timestamp": iso(min((item[0] for item in normalized_page), default=None)),
                "maximum_timestamp": iso(max((item[0] for item in normalized_page), default=None)),
                "continuation": continuation,
            }
        )
        raw.extend(normalized_page)
        if continuation is None:
            break
        if continuation in seen_continuations or continuation >= request_end:
            raise ValueError("non-progressing or repeated continuation")
        seen_continuations.add(continuation)
        request_end = continuation
        time.sleep(0.08)
    else:
        raise ValueError("pagination exceeded frozen maximum")

    counts = Counter(item[0] for item in raw)
    duplicate_rows = sum(count - 1 for count in counts.values())
    unique: dict[int, tuple[int, float, float, float, float]] = {}
    conflicts: list[int] = []
    for item in raw:
        if item[0] in unique and unique[item[0]] != item:
            conflicts.append(item[0])
        else:
            unique[item[0]] = item
    rows = [unique[key] for key in sorted(unique) if START_MS <= key <= end_ms]
    timestamps = [item[0] for item in rows]
    gaps = [
        {"after": iso(left), "before": iso(right), "missing_hours": (right - left) // HOUR_MS - 1}
        for left, right in zip(timestamps, timestamps[1:])
        if right - left != HOUR_MS
    ]
    normalized_bytes = canonical([list(item) for item in rows])
    normalized_path = target / "normalized.json"
    normalized_path.write_bytes(normalized_bytes)
    manifest = [
        {
            "request_url": page["request_url"],
            "requested_end_ms": page["requested_end_ms"],
            "response_sha256": page["sha256"],
        }
        for page in pages
    ]
    manifest_bytes = canonical(manifest)
    manifest_path = target / "request-manifest.json"
    manifest_path.write_bytes(manifest_bytes)
    return {
        "name": name,
        "currency": currency,
        "requested_start": iso(START_MS),
        "requested_end": iso(end_ms),
        "expected_rows": (end_ms - START_MS) // HOUR_MS + 1,
        "observed_rows": len(rows),
        "first_timestamp": iso(timestamps[0]) if timestamps else None,
        "last_timestamp": iso(timestamps[-1]) if timestamps else None,
        "page_count": len(pages),
        "continuation_terminated": bool(pages and pages[-1]["continuation"] is None),
        "exact_hour_alignment": all(value % HOUR_MS == 0 for value in timestamps),
        "boundary_pass": bool(timestamps and timestamps[0] == START_MS and timestamps[-1] == end_ms),
        "gap_count": len(gaps),
        "gaps": gaps[:100],
        "longest_gap_hours": max((item["missing_hours"] for item in gaps), default=0),
        "raw_duplicate_timestamp_count": duplicate_rows,
        "conflicting_timestamp_count": len(set(conflicts)),
        "unique_normalized_timestamps": len(timestamps) == len(set(timestamps)),
        "normalized_path": normalized_path.as_posix(),
        "normalized_sha256": digest(normalized_bytes),
        "request_manifest_path": manifest_path.as_posix(),
        "request_manifest_sha256": digest(manifest_bytes),
        "pages": pages,
        "rows": [list(item) for item in rows],
    }


def without_rows(value: dict[str, Any]) -> dict[str, Any]:
    result = dict(value)
    result.pop("rows", None)
    return result


def prefix_sha(rows: list[list[Any]]) -> str:
    return digest(canonical([value for value in rows if value[0] <= END_MS]))


def arm(currency: str, root: Path, semantic_pass: bool) -> dict[str, Any]:
    primary = acquire(currency, END_MS, root, "fixed-primary")
    repeated = acquire(currency, END_MS, root, "fixed-repeat")
    suffix = acquire(currency, END_MS + HOUR_MS, root, "future-suffix")
    repeat_pass = primary["normalized_sha256"] == repeated["normalized_sha256"]
    prefix_pass = prefix_sha(primary["rows"]) == prefix_sha(suffix["rows"])
    suffix_present = any(value[0] == END_MS + HOUR_MS for value in suffix["rows"])
    conditions = {
        "official_volatility_index_semantics": semantic_pass,
        "credential_free_official_public_endpoint": True,
        "direct_provider_resolution_3600": True,
        "exact_fixed_row_count": primary["observed_rows"] == EXPECTED_ROWS,
        "exact_utc_hour_grid": (
            primary["exact_hour_alignment"]
            and primary["boundary_pass"]
            and primary["gap_count"] == 0
            and primary["conflicting_timestamp_count"] == 0
            and primary["unique_normalized_timestamps"]
        ),
        "finite_positive_schema_valid_values": True,
        "complete_replayable_continuation": all(
            value["continuation_terminated"] for value in (primary, repeated, suffix)
        ),
        "causal_completed_bar_available_by_next_open": True,
        "response_request_dataset_hashes_persisted": all(
            value["normalized_sha256"] and value["request_manifest_sha256"]
            for value in (primary, repeated, suffix)
        ),
        "repeat_acquisition_identity": repeat_pass,
        "future_suffix_prefix_identity": prefix_pass and suffix_present,
        "source_only_fail_closed_boundary": True,
    }
    passed = all(conditions.values())
    return {
        "currency": currency,
        "target_market": f"{currency}-USDT",
        "series": f"{currency} DVOL",
        "provider": "Deribit",
        "semantics": "provider-defined forward implied-volatility index; not skew or realised volatility",
        "resolution_seconds": 3600,
        "expected_rows": EXPECTED_ROWS,
        "source_conditions": conditions,
        "source_conditions_passed": sum(conditions.values()),
        "source_conditions_total": len(conditions),
        "source_contract_passed": passed,
        "availability_convention": {
            "timestamp": "UTC candle opening",
            "available_from": "after the complete 1H candle",
            "permitted_future_use": "strictly lagged completed candle no earlier than the next hourly open",
        },
        "repeat_identity": {"passed": repeat_pass},
        "future_suffix_prefix_identity": {"passed": prefix_pass and suffix_present, "suffix_row_present": suffix_present},
        "fixed_primary": without_rows(primary),
        "fixed_repeat": without_rows(repeated),
        "future_suffix": without_rows(suffix),
        "economics": dict(NULL_ECONOMICS),
        "economics_null_reason": "source-only run forbids target prices, labels, strategies, performance and OOS access",
    }


def report(evidence: dict[str, Any]) -> str:
    lines = [
        "# Direct public 1H DVOL source-contract audit",
        "",
        f"- Family: `{evidence['family_id']}`",
        f"- Tested head: `{evidence['tested_head']}`",
        f"- Fixed interval: `{iso(START_MS)}` through `{iso(END_MS)}`",
        f"- Expected rows per arm: `{EXPECTED_ROWS}`",
        f"- Performance accessed: `{evidence['performance_accessed']}`",
        "",
        "| Arm | Rows | Pages | Gaps | Raw duplicate seams | Repeat | Prefix | Gates | Verdict |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for value in evidence["market_arms"]:
        fixed = value.get("fixed_primary", {})
        lines.append(
            f"| {value['currency']} | {fixed.get('observed_rows')}/{fixed.get('expected_rows')} | "
            f"{fixed.get('page_count')} | {fixed.get('gap_count')} | "
            f"{fixed.get('raw_duplicate_timestamp_count')} | {value.get('repeat_identity', {}).get('passed')} | "
            f"{value.get('future_suffix_prefix_identity', {}).get('passed')} | "
            f"{value['source_conditions_passed']}/{value['source_conditions_total']} | "
            f"{'pass' if value['source_contract_passed'] else 'reject'} |"
        )
    lines += [
        "",
        "No BTC-USDT or ETH-USDT spot price, target return, regime label, strategy path or economic metric was accessed. All economic fields remain null.",
        "",
        "## Machine-readable verdict",
        "",
        "```json",
        json.dumps(evidence["machine_readable_verdict"], sort_keys=True, indent=2),
        "```",
        "",
        f"Terminal verdict: `{evidence['verdict']}`.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tested-head", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    if len(args.tested_head) != 40 or any(character not in "0123456789abcdef" for character in args.tested_head):
        raise ValueError("tested head must be a lowercase 40-character SHA")
    root = Path(args.output_dir)
    root.mkdir(parents=True, exist_ok=True)
    document = fetch_doc(root)
    values: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    for currency in ("BTC", "ETH"):
        try:
            values.append(arm(currency, root, document["semantic_pass"]))
        except Exception as exc:
            errors[currency] = f"{type(exc).__name__}: {exc}"
            values.append(
                {
                    "currency": currency,
                    "target_market": f"{currency}-USDT",
                    "series": f"{currency} DVOL",
                    "provider": "Deribit",
                    "semantics": "provider-defined forward implied-volatility index; not skew or realised volatility",
                    "resolution_seconds": 3600,
                    "expected_rows": EXPECTED_ROWS,
                    "source_conditions": {
                        "official_volatility_index_semantics": document["semantic_pass"],
                        "credential_free_official_public_endpoint": True,
                        "direct_provider_resolution_3600": True,
                        "exact_fixed_row_count": False,
                        "exact_utc_hour_grid": False,
                        "finite_positive_schema_valid_values": False,
                        "complete_replayable_continuation": False,
                        "causal_completed_bar_available_by_next_open": False,
                        "response_request_dataset_hashes_persisted": False,
                        "repeat_acquisition_identity": False,
                        "future_suffix_prefix_identity": False,
                        "source_only_fail_closed_boundary": True,
                    },
                    "source_conditions_passed": 4 if document["semantic_pass"] else 3,
                    "source_conditions_total": 12,
                    "source_contract_passed": False,
                    "error": errors[currency],
                    "economics": dict(NULL_ECONOMICS),
                    "economics_null_reason": "source acquisition failed before target-return access",
                }
            )
    bilateral = document["semantic_pass"] and all(value["source_contract_passed"] for value in values)
    verdict = PASS_VERDICT if bilateral else FAIL_VERDICT
    evidence = {
        "family_id": FAMILY_ID,
        "classification": "source-contract-first forward-implied-volatility information experiment",
        "tested_head": args.tested_head,
        "repository_main": REPOSITORY_MAIN,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "provider": "Deribit official public API",
        "endpoint": ENDPOINT,
        "bar": "1H",
        "resolution_seconds": 3600,
        "canonical_fee_bps_one_way": 5.0,
        "fixed_targets": ["BTC-USDT", "ETH-USDT"],
        "requested_start": iso(START_MS),
        "requested_end": iso(END_MS),
        "expected_common_rows_per_arm": EXPECTED_ROWS,
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "target_spot_data_downloaded": False,
        "target_returns_downloaded": False,
        "feature_defined": False,
        "regime_mapping_defined": False,
        "candidate_created": False,
        "performance_accessed": False,
        "oos_accessed": False,
        "synthetic_data_used": False,
        "cross_sectional_selection": False,
        "pairs_or_spreads": False,
        "market_neutral_or_long_short": False,
        "credentials_used": False,
        "private_endpoints_used": False,
        "accounts_or_orders": False,
        "enabled_adapters": False,
        "leverage_used": False,
        "official_document": document,
        "market_arms": values,
        "acquisition_errors": errors,
        "source_contract_passed": bilateral,
        "markets_passing_source_contract": sum(value["source_contract_passed"] for value in values),
        "canonical_strategy_changed": False,
        "correction_permitted": False,
        "correction_applied": False,
        "observation_epoch_restarted": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "verdict": verdict,
        "machine_readable_verdict": {
            "family_id": FAMILY_ID,
            "source_contract_passed": bilateral,
            "markets_passing_source_contract": sum(value["source_contract_passed"] for value in values),
            "candidate_count": 0,
            "performance_accessed": False,
            "oos_accessed": False,
            "correction_permitted": False,
            "observation_epoch_restarted": False,
            "paper_trading_authorized": False,
            "live_trading_authorized": False,
            "verdict": verdict,
        },
    }
    evidence_bytes = json.dumps(evidence, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"
    (root / "evidence.json").write_bytes(evidence_bytes)
    (root / "evidence.sha256").write_text(digest(evidence_bytes) + "\n")
    manifest = {
        "family_id": FAMILY_ID,
        "tested_head": args.tested_head,
        "official_document": document,
        "market_sources": [
            {
                "currency": value["currency"],
                "source_contract_passed": value["source_contract_passed"],
                "fixed_primary": value.get("fixed_primary"),
                "fixed_repeat": value.get("fixed_repeat"),
                "future_suffix": value.get("future_suffix"),
            }
            for value in values
        ],
    }
    manifest_bytes = json.dumps(manifest, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"
    (root / "source_manifest.json").write_bytes(manifest_bytes)
    (root / "source_manifest.sha256").write_text(digest(manifest_bytes) + "\n")
    (root / "report.md").write_text(report(evidence))


if __name__ == "__main__":
    main()
