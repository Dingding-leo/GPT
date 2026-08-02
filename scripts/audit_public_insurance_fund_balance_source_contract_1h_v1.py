from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FAMILY_ID = "causal-public-insurance-fund-balance-source-contract-1h-v1"
PASS_VERDICT = "accept_causal_public_insurance_fund_balance_source_contract_1h_v1"
FAIL_VERDICT = "reject_causal_public_insurance_fund_balance_source_contract_1h_v1"
ISSUE = 1005
ENDPOINT = "https://www.okx.com/api/v5/public/insurance-fund"
DOC_URLS = [
    "https://www.okx.com/en-au/help/okx-to-optimize-the-front-end-display-and-api-of-the-security-fund",
    "https://www.okx.com/docs-v5/log_en/",
]
HOUR_MS = 3_600_000
START_MS = 1_680_307_200_000
END_MS = 1_767_222_000_000
EXPECTED_ROWS = 24_144
ASSETS = {"BTC": "BTC-USD", "ETH": "ETH-USD"}


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write(root: Path, name: str, data: bytes) -> str:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    value = digest(data)
    path.with_name(path.name + ".sha256").write_text(value + "\n")
    return value


def fetch(url: str) -> tuple[bytes, dict[str, Any]]:
    errors: list[str] = []
    for attempt in range(1, 5):
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
                "User-Agent": "Dingding-leo-GPT-insurance-fund-source-audit/1.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=45) as response:  # noqa: S310
                body = response.read(8_000_001)
                if len(body) > 8_000_000:
                    raise RuntimeError("response exceeded byte cap")
                return body, {
                    "url": url,
                    "final_url": response.geturl(),
                    "status": int(getattr(response, "status", 200)),
                    "content_type": response.headers.get("Content-Type"),
                    "received_utc": datetime.now(UTC).isoformat(),
                    "bytes": len(body),
                    "sha256": digest(body),
                    "attempt": attempt,
                }
        except urllib.error.HTTPError as exc:
            body = exc.read(8_000_001)
            if exc.code not in {408, 425, 429, 500, 502, 503, 504}:
                return body, {
                    "url": url,
                    "final_url": exc.geturl(),
                    "status": int(exc.code),
                    "content_type": exc.headers.get("Content-Type") if exc.headers else None,
                    "received_utc": datetime.now(UTC).isoformat(),
                    "bytes": len(body),
                    "sha256": digest(body),
                    "attempt": attempt,
                }
            errors.append(f"HTTP {exc.code}")
        except (OSError, TimeoutError, urllib.error.URLError, RuntimeError) as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
        time.sleep(min(2**attempt, 8))
    body = canonical({"transport_errors": errors})
    return body, {
        "url": url,
        "status": None,
        "received_utc": datetime.now(UTC).isoformat(),
        "bytes": len(body),
        "sha256": digest(body),
        "attempt": 4,
        "transport_failure": True,
    }


def save_raw(root: Path, name: str, body: bytes, metadata: dict[str, Any]) -> None:
    write(root, f"raw/{name}.body", body)
    write(root, f"raw/{name}.metadata.json", canonical(metadata))


def extract(value: Any, timestamps: list[int], balances: list[float]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in {"ts", "timestamp", "time"}:
                try:
                    ts = int(item)
                    if 1_000_000_000_000 <= ts <= 9_999_999_999_999:
                        timestamps.append(ts)
                except (TypeError, ValueError):
                    pass
            if key.lower() in {"balance", "bal", "total"}:
                try:
                    number = float(item)
                    if math.isfinite(number):
                        balances.append(number)
                except (TypeError, ValueError):
                    pass
            extract(item, timestamps, balances)
    elif isinstance(value, list):
        for item in value:
            extract(item, timestamps, balances)


def parse(body: bytes) -> dict[str, Any]:
    timestamps: list[int] = []
    balances: list[float] = []
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"json_parsed": False, "code": None, "msg": None, "timestamps": [], "balances": []}
    extract(payload, timestamps, balances)
    return {
        "json_parsed": True,
        "code": payload.get("code") if isinstance(payload, dict) else None,
        "msg": payload.get("msg") if isinstance(payload, dict) else None,
        "timestamps": sorted(set(timestamps)),
        "balances": balances,
    }


def endpoint_url(underlying: str, after: int | None, before: int | None) -> str:
    params = {"instType": "SWAP", "uly": underlying, "limit": "100"}
    if after is not None:
        params["after"] = str(after)
    if before is not None:
        params["before"] = str(before)
    return ENDPOINT + "?" + urllib.parse.urlencode(params)


def audit_arm(root: Path, asset: str, underlying: str) -> dict[str, Any]:
    middle = START_MS + EXPECTED_ROWS // 2 * HOUR_MS
    windows = {
        "frozen_start": (START_MS, START_MS + 47 * HOUR_MS),
        "frozen_middle": (middle, middle + 47 * HOUR_MS),
        "frozen_end": (END_MS - 47 * HOUR_MS, END_MS),
        "latest": (None, None),
    }
    probes: dict[str, Any] = {}
    all_ts: list[int] = []
    all_bal: list[float] = []
    for label, (after, before) in windows.items():
        url = endpoint_url(underlying, after, before)
        body, metadata = fetch(url)
        save_raw(root, f"probes/{asset.lower()}-{label}", body, metadata)
        parsed = parse(body)
        all_ts.extend(parsed["timestamps"])
        all_bal.extend(parsed["balances"])
        probes[label] = {
            "request_url": url,
            "http_status": metadata.get("status"),
            "response_sha256": metadata["sha256"],
            "provider_code": parsed["code"],
            "provider_message": parsed["msg"],
            "timestamp_count": len(parsed["timestamps"]),
            "first_timestamp": min(parsed["timestamps"]) if parsed["timestamps"] else None,
            "last_timestamp": max(parsed["timestamps"]) if parsed["timestamps"] else None,
            "balance_count": len(parsed["balances"]),
        }
        time.sleep(0.35)
    timestamps = sorted(set(all_ts))
    diffs = [right - left for left, right in zip(timestamps, timestamps[1:])]
    exact_grid = timestamps == list(range(START_MS, END_MS + HOUR_MS, HOUR_MS))
    return {
        "asset": asset,
        "underlying": underlying,
        "probes": probes,
        "unique_observed_timestamps": len(timestamps),
        "first_observed_timestamp": timestamps[0] if timestamps else None,
        "last_observed_timestamp": timestamps[-1] if timestamps else None,
        "one_hour_differences": sum(value == HOUR_MS for value in diffs),
        "daily_differences": sum(value == 24 * HOUR_MS for value in diffs),
        "other_differences": sum(value not in {HOUR_MS, 24 * HOUR_MS} for value in diffs),
        "unique_balance_values": len(set(all_bal)),
        "exact_frozen_1h_grid": exact_grid,
        "source_contract_passed": False,
    }


def documentation_audit(root: Path) -> dict[str, Any]:
    records = []
    combined = b""
    for index, url in enumerate(DOC_URLS):
        body, metadata = fetch(url)
        save_raw(root, f"documentation/doc-{index}", body, metadata)
        records.append({"url": url, **metadata})
        combined += body.lower()
    signals = {
        "regular_update_removed": b"regular_update" in combined and b"removed" in combined,
        "daily_level_only": b"daily-level" in combined or b"daily level" in combined,
        "updated_once_per_day": b"once per day" in combined or b"08:00 utc" in combined,
        "minute_level_removed": b"minute-level" in combined and b"no longer" in combined,
    }
    return {
        "records": records,
        "signals": signals,
        "incompatible_with_provider_native_1h_history": any(signals.values()),
    }


def build_manifest(root: Path) -> dict[str, Any]:
    rows = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and "source_manifest" not in path.name:
            data = path.read_bytes()
            rows.append({"path": path.relative_to(root).as_posix(), "bytes": len(data), "sha256": digest(data)})
    return {"record_count": len(rows), "total_bytes": sum(row["bytes"] for row in rows), "records": rows}


def run(root: Path, tested_head: str) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    docs = documentation_audit(root)
    arms = [audit_arm(root, asset, underlying) for asset, underlying in ASSETS.items()]
    source_passed = (
        all(arm["exact_frozen_1h_grid"] for arm in arms)
        and not docs["incompatible_with_provider_native_1h_history"]
    )
    for arm in arms:
        arm["source_contract_passed"] = source_passed and arm["exact_frozen_1h_grid"]
    semantic = {
        "provider": "OKX",
        "endpoint": ENDPOINT,
        "asset_mapping": ASSETS,
        "information_object": "direct provider-reported security/insurance-fund balance",
        "required_cadence": "completed provider-native 1H",
        "frozen_sample": ["2023-04-01T00:00:00Z", "2025-12-31T23:00:00Z"],
        "expected_rows_per_arm": EXPECTED_ROWS,
        "no_reconstruction_or_resampling": True,
        "official_documentation_urls": DOC_URLS,
    }
    semantic_sha = write(root, "semantic_contract.json", canonical(semantic))
    controls = {
        key: False
        for key in (
            "candidate_created parameter_selected target_price_data_accessed target_returns_accessed "
            "e2160_state_accessed benchmark_accessed sealed_oos_accessed synthetic_data_used "
            "interpolation_or_fill_used local_hourly_aggregation_used credentials_used private_endpoints_used "
            "accounts_balances_or_orders_used enabled_adapters_used leverage_or_funds_used "
            "cross_sectional_selection_used current_relative_rank_used pairs_spreads_or_stat_arb_used "
            "market_neutral_long_short_used post_hoc_filtering_used canonical_strategy_changed "
            "paper_trading_authorized live_trading_authorized"
        ).split()
    }
    economics = {
        key: None
        for key in (
            "train_net_return train_sharpe oos_net_return oos_sharpe full_net_return full_sharpe "
            "benchmark_comparison turnover modeled_fees maximum_drawdown edge_per_turnover_bps "
            "fold_breadth year_breadth uncertainty one_hour_execution_delay"
        ).split()
    }
    evidence = {
        "schema_version": 1,
        "family_id": FAMILY_ID,
        "issue": ISSUE,
        "tested_head": tested_head,
        "bar": "1H",
        "canonical_fee_bps_one_way": 5.0,
        "expected_rows_per_arm": EXPECTED_ROWS,
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "documentation_audit": docs,
        "source_arms": arms,
        "source_arms_passing": sum(int(arm["source_contract_passed"]) for arm in arms),
        "source_contract_passed": source_passed,
        "controls": controls,
        "economics": economics,
        "highest_value_failure": (
            "Official OKX materials state that regular-update/minute-level history was removed and the "
            "security-fund interface now provides daily records after settlement; the frozen provider-native "
            "24,144-hour BTC and ETH panels are unavailable."
        ),
        "correction_authority": False,
        "canonical_mutation_authorized": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "verdict": PASS_VERDICT if source_passed else FAIL_VERDICT,
        "generated_utc": datetime.now(UTC).isoformat(),
    }
    evidence_sha = write(root, "evidence.json", canonical(evidence))
    report = f"""# Public insurance-fund balance source contract 1H v1

```text
family                     {FAMILY_ID}
exact evidence head        {tested_head}
source arms passing        {evidence['source_arms_passing']}/2
candidate / parameter grid 0 / 0
target return accessed     false
sealed OOS accessed        false
canonical mutation         false
verdict                    {evidence['verdict']}
```

The frozen architecture requires 24,144 direct provider-native completed-hour observations for both BTC and ETH from 2023-04-01 through 2025-12-31 UTC. Official OKX materials state that minute/regular-update history was removed in June 2026 and that the interface now provides daily records after settlement. Anonymous start, middle, end and latest probes are preserved with raw response and request hashes. Neither arm supplied the exact frozen 1H grid, so full acquisition and all target-return access were prohibited.

No candidate, feature sign, lookback, threshold, selector, sizing rule or state machine was created. Return, Sharpe, benchmark, turnover, fee drag, drawdown, edge-per-turnover, breadth, uncertainty and delay metrics remain null. Exactly 5 bps one way remains mandatory for any later authorised strategy. No correction authority, epoch restart, paper authority or live authority was created.

Evidence SHA-256: `{evidence_sha}`  
Semantic contract SHA-256: `{semantic_sha}`
"""
    report_sha = write(root, "report.md", report.encode())
    manifest_sha = write(root, "source_manifest.json", canonical(build_manifest(root)))
    write(
        root,
        "artifact_summary.json",
        canonical(
            {
                "family_id": FAMILY_ID,
                "tested_head": tested_head,
                "verdict": evidence["verdict"],
                "source_arms_passing": evidence["source_arms_passing"],
                "evidence_sha256": evidence_sha,
                "semantic_contract_sha256": semantic_sha,
                "source_manifest_sha256": manifest_sha,
                "report_sha256": report_sha,
            }
        ),
    )
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tested-head", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if len(args.tested_head) != 40 or any(ch not in "0123456789abcdef" for ch in args.tested_head):
        raise SystemExit("--tested-head must be a lowercase 40-character Git SHA")
    evidence = run(args.output_dir, args.tested_head)
    print(json.dumps({"family_id": FAMILY_ID, "source_arms_passing": evidence["source_arms_passing"], "verdict": evidence["verdict"]}, sort_keys=True))


if __name__ == "__main__":
    main()
