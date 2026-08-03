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

FAMILY_ID = "causal-okx-contract-open-interest-source-contract-1h-v1"
ISSUE = 1040
ENDPOINT = "/api/v5/rubik/stat/contracts/open-interest-history"
SERVER_TIME_ENDPOINT = "/api/v5/public/time"
PERIOD = "1H"
HOUR_MS = 3_600_000
SUPPORT_FLOOR = 2_161
MAX_PAGES = 30
LIMIT = 100
INSTRUMENTS = ("BTC-USDT-SWAP", "ETH-USDT-SWAP")


def iso_utc(ts_ms: int | None) -> str | None:
    if ts_ms is None:
        return None
    return (
        datetime.fromtimestamp(ts_ms / 1000.0, tz=UTC)
        .isoformat()
        .replace("+00:00", "Z")
    )


def request_json(base_url: str, path: str, params: dict[str, str]) -> tuple[int, dict[str, Any]]:
    query = urllib.parse.urlencode(params)
    url = base_url.rstrip("/") + path + ("?" + query if query else "")
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "prospective-strategy-source-audit/1.0",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            status = int(response.status)
            payload = json.loads(response.read().decode("utf-8"))
            return status, payload
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {"code": None, "msg": body[:500], "data": []}
        return int(exc.code), payload


def get_server_time(base_url: str) -> tuple[int, int, dict[str, Any]]:
    status, payload = request_json(base_url, SERVER_TIME_ENDPOINT, {})
    if status != 200 or payload.get("code") != "0" or not payload.get("data"):
        raise RuntimeError(
            f"provider server-time request failed: HTTP {status}, code={payload.get('code')}"
        )
    server_ms = int(payload["data"][0]["ts"])
    latest_completed_hour_ms = (server_ms // HOUR_MS) * HOUR_MS - HOUR_MS
    return server_ms, latest_completed_hour_ms, payload


def parse_rows(raw_rows: list[Any], cutoff_ms: int) -> dict[str, Any]:
    row_widths: list[int] = []
    parsed: list[tuple[int, float]] = []
    malformed = 0
    nonfinite_or_nonpositive = 0
    future_or_incomplete = 0

    for row in raw_rows:
        if not isinstance(row, list) or len(row) < 2:
            malformed += 1
            continue
        row_widths.append(len(row))
        try:
            ts = int(row[0])
            oi = float(row[1])
        except (TypeError, ValueError):
            malformed += 1
            continue
        if not math.isfinite(oi) or oi <= 0.0:
            nonfinite_or_nonpositive += 1
            continue
        if ts > cutoff_ms:
            future_or_incomplete += 1
            continue
        parsed.append((ts, oi))

    fixed_width = len(set(row_widths)) == 1 and bool(row_widths)
    timestamps = [ts for ts, _ in parsed]
    duplicates = len(timestamps) - len(set(timestamps))
    canonical = sorted({ts: oi for ts, oi in parsed}.items())
    canonical_ts = [ts for ts, _ in canonical]
    hour_aligned = all(ts % HOUR_MS == 0 for ts in canonical_ts)
    diffs = [b - a for a, b in zip(canonical_ts, canonical_ts[1:])]
    spacing_exact = all(diff == HOUR_MS for diff in diffs)
    missing_internal_hours = sum(max(0, diff // HOUR_MS - 1) for diff in diffs)
    strictly_ordered = all(a < b for a, b in zip(canonical_ts, canonical_ts[1:]))

    return {
        "raw_row_count": len(raw_rows),
        "accepted_completed_row_count": len(canonical),
        "row_widths": sorted(set(row_widths)),
        "fixed_row_width": fixed_width,
        "malformed_row_count": malformed,
        "nonfinite_or_nonpositive_row_count": nonfinite_or_nonpositive,
        "future_or_incomplete_row_count": future_or_incomplete,
        "duplicate_timestamp_count": duplicates,
        "first_timestamp_ms": canonical_ts[0] if canonical_ts else None,
        "first_timestamp": iso_utc(canonical_ts[0]) if canonical_ts else None,
        "last_timestamp_ms": canonical_ts[-1] if canonical_ts else None,
        "last_timestamp": iso_utc(canonical_ts[-1]) if canonical_ts else None,
        "strictly_ordered_after_sort": strictly_ordered,
        "hour_aligned": hour_aligned,
        "spacing_exact_1h": spacing_exact,
        "missing_internal_hours": missing_internal_hours,
        "support_floor": SUPPORT_FLOOR,
        "support_floor_passed": len(canonical) >= SUPPORT_FLOOR,
    }


def audit_arm(base_url: str, instrument: str, cutoff_ms: int) -> dict[str, Any]:
    raw_rows: list[Any] = []
    pages: list[dict[str, Any]] = []
    cursor = cutoff_ms
    provider_code_success = True
    http_success = True
    terminal_reason = "max_pages_reached"

    for page_index in range(MAX_PAGES):
        params = {
            "instId": instrument,
            "period": PERIOD,
            "end": str(cursor),
            "limit": str(LIMIT),
        }
        status, payload = request_json(base_url, ENDPOINT, params)
        code = payload.get("code")
        rows = payload.get("data") if isinstance(payload.get("data"), list) else []
        pages.append(
            {
                "page": page_index + 1,
                "request": params,
                "http_status": status,
                "provider_code": code,
                "provider_message": payload.get("msg"),
                "row_count": len(rows),
            }
        )
        if status != 200:
            http_success = False
            terminal_reason = f"http_{status}"
            break
        if code != "0":
            provider_code_success = False
            terminal_reason = f"provider_code_{code}"
            break
        if not rows:
            terminal_reason = "empty_page"
            break
        raw_rows.extend(rows)
        valid_ts: list[int] = []
        for row in rows:
            if isinstance(row, list) and row:
                try:
                    valid_ts.append(int(row[0]))
                except (TypeError, ValueError):
                    pass
        if not valid_ts:
            terminal_reason = "no_parseable_timestamps"
            break
        next_cursor = min(valid_ts) - 1
        if next_cursor >= cursor:
            terminal_reason = "non_decreasing_pagination_cursor"
            break
        cursor = next_cursor
        if len(rows) < LIMIT:
            terminal_reason = "short_page_provider_retention_boundary"
            break
        time.sleep(0.12)

    parsed = parse_rows(raw_rows, cutoff_ms)
    gates = {
        "http_success": http_success,
        "provider_code_success": provider_code_success,
        "non_empty": parsed["raw_row_count"] > 0,
        "fixed_row_width": parsed["fixed_row_width"],
        "finite_positive_open_interest": (
            parsed["malformed_row_count"] == 0
            and parsed["nonfinite_or_nonpositive_row_count"] == 0
        ),
        "timestamps_unique": parsed["duplicate_timestamp_count"] == 0,
        "timestamps_strictly_ordered": parsed["strictly_ordered_after_sort"],
        "timestamps_hour_aligned": parsed["hour_aligned"],
        "spacing_exact_1h": parsed["spacing_exact_1h"],
        "no_missing_internal_hours": parsed["missing_internal_hours"] == 0,
        "completed_only": parsed["future_or_incomplete_row_count"] == 0,
        "support_floor_passed": parsed["support_floor_passed"],
    }
    return {
        "instrument": instrument,
        "endpoint": ENDPOINT,
        "period": PERIOD,
        "anonymous_public_request": True,
        "credentials_used": False,
        "private_endpoint_used": False,
        "pages_requested": len(pages),
        "terminal_reason": terminal_reason,
        "pages": pages,
        "statistics": parsed,
        "gates": gates,
        "source_contract_passed": all(gates.values()),
    }


def build_evidence(base_url: str, exact_head: str) -> dict[str, Any]:
    server_ms, cutoff_ms, server_payload = get_server_time(base_url)
    arms = [audit_arm(base_url, instrument, cutoff_ms) for instrument in INSTRUMENTS]
    bilateral_pass = all(arm["source_contract_passed"] for arm in arms)
    candidate_count = 1 if bilateral_pass else 0
    status = (
        "source_contract_passed_candidate_frozen_not_evaluated"
        if bilateral_pass
        else "terminally_rejected_source_contract"
    )
    verdict = (
        "support_okx_contract_open_interest_source_contract_1h_v1"
        if bilateral_pass
        else "reject_okx_contract_open_interest_source_contract_1h_v1"
    )
    highest_value_failure = None
    if not bilateral_pass:
        failed = [arm for arm in arms if not arm["source_contract_passed"]]
        highest_value_failure = {
            "classification": "bilateral_source_or_retention_failure",
            "failed_instruments": [arm["instrument"] for arm in failed],
            "details": {
                arm["instrument"]: [
                    gate for gate, passed in arm["gates"].items() if not passed
                ]
                for arm in failed
            },
        }

    return {
        "schema_version": "strategy-source-contract-evidence-v1",
        "family_id": FAMILY_ID,
        "issue": ISSUE,
        "exact_head": exact_head,
        "generated_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        "provider": "OKX",
        "base_url": base_url.rstrip("/"),
        "server_time_request": {
            "endpoint": SERVER_TIME_ENDPOINT,
            "http_provider_code": server_payload.get("code"),
            "server_time_ms": server_ms,
            "server_time": iso_utc(server_ms),
            "latest_completed_source_hour_ms": cutoff_ms,
            "latest_completed_source_hour": iso_utc(cutoff_ms),
        },
        "bar": PERIOD,
        "fee_bps_one_way": 5.0,
        "source_arms": arms,
        "bilateral_source_contract_passed": bilateral_pass,
        "candidate_count": candidate_count,
        "parameter_grid_count": 0,
        "target_returns_accessed": False,
        "strategy_performance_accessed": False,
        "benchmark_path_accessed": False,
        "sealed_oos_accessed": False,
        "canonical_strategy_changed": False,
        "correction_authority": False,
        "observation_epoch_restarted": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "status": status,
        "highest_value_failure": highest_value_failure,
        "verdict": verdict,
        "next_action": (
            "If bilateral support passed, evaluate only the frozen zero-tuning OI-24h "
            "gate under the issue 1040 chronology and training gates. If it failed, "
            "do not rescue the source contract with shorter support, interpolation, "
            "alternate periods, symbol substitution, aggregation or single-market promotion."
        ),
    }


def validate(evidence: dict[str, Any]) -> None:
    assert evidence["family_id"] == FAMILY_ID
    assert evidence["issue"] == ISSUE
    assert evidence["bar"] == "1H"
    assert evidence["fee_bps_one_way"] == 5.0
    assert len(evidence["source_arms"]) == 2
    assert {arm["instrument"] for arm in evidence["source_arms"]} == set(INSTRUMENTS)
    assert evidence["parameter_grid_count"] == 0
    assert evidence["target_returns_accessed"] is False
    assert evidence["strategy_performance_accessed"] is False
    assert evidence["benchmark_path_accessed"] is False
    assert evidence["sealed_oos_accessed"] is False
    assert evidence["canonical_strategy_changed"] is False
    assert evidence["correction_authority"] is False
    assert evidence["paper_trading_authorized"] is False
    assert evidence["live_trading_authorized"] is False
    if evidence["bilateral_source_contract_passed"]:
        assert evidence["candidate_count"] == 1
        assert all(arm["source_contract_passed"] for arm in evidence["source_arms"])
    else:
        assert evidence["candidate_count"] == 0
        assert evidence["status"] == "terminally_rejected_source_contract"


def persist(output_dir: Path, evidence: dict[str, Any]) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(evidence, sort_keys=True, indent=2, allow_nan=False) + "\n"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    (output_dir / "evidence.json").write_text(payload, encoding="utf-8")
    (output_dir / "evidence.sha256").write_text(digest + "\n", encoding="utf-8")
    report = (
        "# OKX contract open-interest 1H source-contract audit\n\n"
        "This evidence was generated before spot target-return, strategy-performance, "
        "benchmark-path or sealed-OOS access.\n\n"
        "```json\n"
        + json.dumps(evidence, sort_keys=True, indent=2, allow_nan=False)
        + "\n```\n\n"
        + f"Evidence SHA-256: `{digest}`\n"
    )
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    return digest


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    exact_head = os.environ.get("GITHUB_SHA", "")
    evidence = build_evidence(base_url, exact_head)
    validate(evidence)
    persist(output_dir, evidence)
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--base-url", default=os.environ.get("OKX_BASE_URL", "https://www.okx.com")
    )
    args = parser.parse_args()
    print(json.dumps(run(args.output_dir, args.base_url), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
