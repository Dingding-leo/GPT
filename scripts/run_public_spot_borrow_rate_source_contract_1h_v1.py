from __future__ import annotations

import argparse
import csv
import html
import importlib.util
import json
import math
import re
import sys
import time
from pathlib import Path
from typing import Any

HELPER_PATH = Path(__file__).with_name(
    "run_public_spot_borrow_demand_source_contract_1h_v1.py"
)
SPEC = importlib.util.spec_from_file_location("spot_borrow_source_helper", HELPER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("unable to load frozen public-source helper")
helper = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = helper
SPEC.loader.exec_module(helper)

FAMILY_ID = "causal-public-spot-borrow-rate-source-contract-1h-v1"
PASS_VERDICT = "accept_causal_public_spot_borrow_rate_source_contract_1h_v1"
FAIL_VERDICT = "reject_causal_public_spot_borrow_rate_source_contract_1h_v1"
REPOSITORY_MAIN = "5a0fcc97d1a882f8223656c51f5bb8055f534e38"
ISSUE = 986
ASSETS = ("BTC", "ETH")
HOUR_MS = 3_600_000
START_MS = 1_680_307_200_000
END_MS = 1_767_222_000_000
EXPECTED_ROWS = 24_144
PAGE_LIMIT = 100
MAX_PAGES = 260
MIN_REQUEST_INTERVAL = 0.22
EXPECTED_FIELDS = {"amt", "ccy", "lendingRate", "rate", "ts"}

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
    "always_long_net_return": None,
    "always_long_sharpe": None,
    "turnover": None,
    "modeled_fees": None,
    "maximum_drawdown": None,
    "edge_per_turnover_bps": None,
    "fold_breadth": None,
    "calendar_year_breadth": None,
    "dependence_aware_uncertainty": None,
    "one_hour_delay": None,
}

FALSE_FIELDS = (
    "candidate_created",
    "target_price_data_downloaded",
    "target_returns_downloaded",
    "performance_accessed",
    "oos_accessed",
    "synthetic_data_used",
    "interpolation_or_fill_used",
    "credentials_used",
    "private_endpoints_used",
    "accounts_balances_or_orders",
    "enabled_adapters",
    "leverage_or_funds_used",
    "cross_sectional_asset_selection",
    "current_relative_rank",
    "pairs_spreads_cointegration_or_stat_arb",
    "market_neutral_or_long_short",
    "post_hoc_asset_filtering",
    "canonical_strategy_changed",
    "paper_trading_authorized",
    "live_trading_authorized",
)

_LAST_REQUEST: float | None = None


def paced_request(url: str) -> tuple[bytes, dict[str, Any]]:
    global _LAST_REQUEST
    now = time.monotonic()
    if _LAST_REQUEST is not None:
        delay = MIN_REQUEST_INTERVAL - (now - _LAST_REQUEST)
        if delay > 0:
            time.sleep(delay)
    _LAST_REQUEST = time.monotonic()
    return helper.request_bytes(url)


def parse_row(row: Any, asset: str, context: str) -> dict[str, str]:
    if not isinstance(row, dict) or set(row) != EXPECTED_FIELDS:
        raise helper.ProbeFailure(f"{context}: schema mismatch")
    if row["ccy"] != asset:
        raise helper.ProbeFailure(f"{context}: currency mismatch")
    if not helper.finite_number(row["rate"]):
        raise helper.ProbeFailure(f"{context}: invalid annual borrow rate")
    if not helper.finite_number(row["lendingRate"]):
        raise helper.ProbeFailure(f"{context}: invalid adjacent lending rate")
    try:
        timestamp = int(row["ts"])
    except (TypeError, ValueError) as exc:
        raise helper.ProbeFailure(f"{context}: invalid timestamp") from exc
    if timestamp % HOUR_MS:
        raise helper.ProbeFailure(f"{context}: timestamp is not UTC-hour aligned")
    return {
        "ts": str(timestamp),
        "ccy": asset,
        "rate": row["rate"],
        "lendingRate": row["lendingRate"],
    }


def get_page(
    root: Path,
    *,
    asset: str,
    cursor: int,
    raw_name: str,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    url = helper.endpoint_url(helper.HISTORY_PATH, asset, cursor)
    if not helper.endpoint_identity_ok(url, helper.HISTORY_PATH, asset, cursor):
        raise helper.ProbeFailure(f"{raw_name}: endpoint identity failure")
    body, metadata = paced_request(url)
    saved = helper.save_raw(root, raw_name, body, metadata)
    if metadata["status"] != 200 or metadata["final_url"] != url:
        raise helper.ProbeFailure(f"{raw_name}: endpoint request failure")
    payload = helper.strict_json(body, raw_name)
    rows = [parse_row(row, asset, raw_name) for row in payload["data"]]
    return rows, saved


def acquire(root: Path, asset: str, acquisition: str) -> dict[str, Any]:
    cursor = END_MS + HOUR_MS
    prior_oldest: int | None = None
    all_rows: list[dict[str, str]] = []
    cursors: list[int] = []
    body_hashes: list[str] = []
    row_counts: list[int] = []

    for page_index in range(MAX_PAGES):
        rows, saved = get_page(
            root,
            asset=asset,
            cursor=cursor,
            raw_name=f"{acquisition}/{asset.lower()}/page-{page_index:03d}",
        )
        if not rows or len(rows) > PAGE_LIMIT:
            raise helper.ProbeFailure(f"{asset} {acquisition}: invalid page size")
        timestamps = [int(row["ts"]) for row in rows]
        if timestamps[0] >= cursor:
            raise helper.ProbeFailure(f"{asset} {acquisition}: non-exclusive cursor")
        if not all(left - right == HOUR_MS for left, right in zip(timestamps, timestamps[1:])):
            raise helper.ProbeFailure(f"{asset} {acquisition}: within-page gap")
        if prior_oldest is not None and prior_oldest - timestamps[0] != HOUR_MS:
            raise helper.ProbeFailure(f"{asset} {acquisition}: cross-page gap")
        cursors.append(cursor)
        body_hashes.append(saved["sha256"])
        row_counts.append(len(rows))
        all_rows.extend(rows)
        prior_oldest = timestamps[-1]
        if prior_oldest <= START_MS:
            break
        cursor = prior_oldest
    else:
        raise helper.ProbeFailure(f"{asset} {acquisition}: page bound exceeded")

    panel = [row for row in all_rows if START_MS <= int(row["ts"]) <= END_MS]
    timestamps = [int(row["ts"]) for row in panel]
    return {
        "rows": panel,
        "page_count": len(cursors),
        "cursor_sequence_sha256": helper.sha256(helper.canonical(cursors)),
        "body_hash_sequence_sha256": helper.sha256(helper.canonical(body_hashes)),
        "row_count_sequence_sha256": helper.sha256(helper.canonical(row_counts)),
        "panel_sha256": helper.sha256(helper.canonical(panel)),
        "observed_rows": len(panel),
        "newest_timestamp_ms": timestamps[0] if timestamps else None,
        "oldest_timestamp_ms": timestamps[-1] if timestamps else None,
        "timestamps_unique": len(timestamps) == len(set(timestamps)),
        "exact_hour_grid": bool(timestamps)
        and len(timestamps) == EXPECTED_ROWS
        and timestamps[0] == END_MS
        and timestamps[-1] == START_MS
        and all(left - right == HOUR_MS for left, right in zip(timestamps, timestamps[1:])),
    }


def normalized_html(body: bytes) -> str:
    text = body.decode("utf-8")
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(html.unescape(text).split())


def audit_semantics(root: Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    bodies: dict[str, bytes] = {}
    for name, url in (("official-docs", helper.DOC_URL), ("official-changelog", helper.LOG_URL)):
        body, metadata = paced_request(url)
        records.append(helper.save_raw(root, name, body, metadata))
        if metadata["status"] != 200 or metadata["final_url"] != url:
            raise helper.ProbeFailure(f"{name}: acquisition failed")
        bodies[name] = body

    docs = normalized_html(bodies["official-docs"])
    changelog = normalized_html(bodies["official-changelog"])
    docs_phrases = (
        "GET / Public borrow history (public)",
        "Authentication is not required for this public endpoint.",
        "Only returned records after December 14, 2021.",
        helper.HISTORY_PATH,
        "Pagination of data to return records earlier than the requested ts",
        "The maximum is 100.",
        "Annual borrowing interest rate",
        "Annual lending interest rate",
    )
    changelog_phrases = (
        "Deprecate amt field, return",
        "Public borrow history (public)",
        "rate String Annual borrowing interest rate",
    )
    missing_docs = [phrase for phrase in docs_phrases if phrase not in docs]
    missing_changelog = [phrase for phrase in changelog_phrases if phrase not in changelog]
    contract = {
        "provider": "OKX",
        "endpoint": helper.HISTORY_PATH,
        "authentication": "not required",
        "primary_field": "rate",
        "primary_field_semantics": "Annual borrowing interest rate",
        "adjacent_field": "lendingRate",
        "adjacent_field_semantics": "Annual lending interest rate",
        "rate_handling": "finite provider string retained without unit rescaling",
        "currency_field": "ccy",
        "timestamp_field": "ts",
        "timestamp_unit": "Unix milliseconds",
        "pagination": "after returns records earlier than requested ts",
        "page_limit": PAGE_LIMIT,
        "missing_docs_phrases": missing_docs,
        "missing_changelog_phrases": missing_changelog,
        "semantics_passed": not missing_docs and not missing_changelog,
        "official_docs_sha256": helper.sha256(bodies["official-docs"]),
        "official_changelog_sha256": helper.sha256(bodies["official-changelog"]),
        "source_records": records,
    }
    helper.write_hashed(root, "semantic_contract.json", helper.canonical(contract))
    return contract


def write_panel(root: Path, asset: str, rows_descending: list[dict[str, str]]) -> str:
    path = root / "panels" / f"{asset.lower()}-borrow-rate-1h.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["ts", "ccy", "rate", "lendingRate"],
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(reversed(rows_descending))
    digest = helper.sha256(path.read_bytes())
    path.with_name(f"{path.name}.sha256").write_text(f"{digest}\n")
    return digest


def build_arm(root: Path, asset: str, semantics_passed: bool) -> dict[str, Any]:
    first = acquire(root, asset, "acquisition-a")
    second = acquire(root, asset, "acquisition-b")
    prefix, prefix_raw = get_page(
        root,
        asset=asset,
        cursor=END_MS + HOUR_MS,
        raw_name=f"probes/{asset.lower()}-prefix",
    )
    suffix_cursor = START_MS + PAGE_LIMIT * HOUR_MS
    suffix, suffix_raw = get_page(
        root,
        asset=asset,
        cursor=suffix_cursor,
        raw_name=f"probes/{asset.lower()}-suffix",
    )
    rows = first["rows"]
    rates = [float(row["rate"]) for row in rows]
    lending_rates = [float(row["lendingRate"]) for row in rows]
    expected_suffix = [row for row in rows if START_MS <= int(row["ts"]) < suffix_cursor]
    replay_identical = bool(
        first["panel_sha256"] == second["panel_sha256"]
        and first["body_hash_sequence_sha256"] == second["body_hash_sequence_sha256"]
        and first["rows"] == second["rows"]
    )
    checks = {
        "official_semantics": semantics_passed,
        "expected_rows": first["observed_rows"] == EXPECTED_ROWS,
        "complete_grid": first["exact_hour_grid"],
        "unique_timestamps": first["timestamps_unique"],
        "repeat_acquisition_identical": replay_identical,
        "prefix_probe_match": prefix == rows[:PAGE_LIMIT],
        "suffix_probe_match": suffix == expected_suffix,
        "rates_finite": len(rates) == EXPECTED_ROWS and all(math.isfinite(value) for value in rates),
        "lending_rates_finite": len(lending_rates) == EXPECTED_ROWS
        and all(math.isfinite(value) for value in lending_rates),
    }
    passed = all(checks.values())
    compact_first = {key: value for key, value in first.items() if key != "rows"}
    compact_second = {key: value for key, value in second.items() if key != "rows"}
    return {
        "asset": asset,
        "expected_rows": EXPECTED_ROWS,
        "observed_rows": first["observed_rows"],
        "start_timestamp_ms": START_MS,
        "end_timestamp_ms": END_MS,
        "rate_min": min(rates) if rates else None,
        "rate_max": max(rates) if rates else None,
        "rate_distinct_count": len(set(rates)),
        "lending_rate_min": min(lending_rates) if lending_rates else None,
        "lending_rate_max": max(lending_rates) if lending_rates else None,
        "lending_rate_distinct_count": len(set(lending_rates)),
        "panel_csv_sha256": write_panel(root, asset, rows),
        "normalized_panel_sha256": first["panel_sha256"],
        "acquisition_a": compact_first,
        "acquisition_b": compact_second,
        "repeat_acquisition_identical": replay_identical,
        "prefix_probe_body_sha256": prefix_raw["sha256"],
        "suffix_probe_body_sha256": suffix_raw["sha256"],
        "checks": checks,
        "failure_reasons": [name for name, value in checks.items() if not value],
        "source_contract_passed": passed,
        "economics": dict(NULL_ECONOMICS),
    }


def source_manifest(root: Path) -> dict[str, Any]:
    records = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "source_manifest.json":
            body = path.read_bytes()
            records.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "bytes": len(body),
                    "sha256": helper.sha256(body),
                }
            )
    return {
        "record_count": len(records),
        "total_bytes": sum(record["bytes"] for record in records),
        "records": records,
    }


def report(evidence: dict[str, Any]) -> str:
    lines = [
        "# Public BTC/ETH spot-borrow rate source contract 1H v1",
        "",
        "```text",
        f"family                 {evidence['family_id']}",
        f"tested head            {evidence['tested_head']}",
        f"source arms passing    {evidence['source_arms_passing']}/2",
        f"candidate count        {evidence['candidate_count']}",
        f"OOS accessed           {str(evidence['oos_accessed']).lower()}",
        f"verdict                 {evidence['verdict']}",
        "```",
        "",
        "| Asset | Rows | Pages | Distinct rates | Replay | Grid | Result |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for arm in evidence["source_arms"]:
        lines.append(
            f"| {arm['asset']} | {arm['observed_rows']:,} | "
            f"{arm['acquisition_a']['page_count']} | {arm['rate_distinct_count']} | "
            f"{'pass' if arm['repeat_acquisition_identical'] else 'fail'} | "
            f"{'pass' if arm['checks']['complete_grid'] else 'fail'} | "
            f"{'pass' if arm['source_contract_passed'] else 'fail'} |"
        )
    lines.extend(
        [
            "",
            "`rate` is bound to annual borrowing interest rate; `lendingRate` is kept separate.",
            "No target prices, returns, candidate values, performance or sealed OOS were accessed.",
            "All economic fields are null. Exactly 5 bps one way remains reserved for a later",
            "separately preregistered executable experiment.",
            "",
        ]
    )
    return "\n".join(lines)


def run(tested_head: str, output_dir: Path) -> dict[str, Any]:
    if len(tested_head) != 40 or any(character not in "0123456789abcdef" for character in tested_head):
        raise helper.ProbeFailure("tested head must be a lowercase 40-character SHA")
    output_dir.mkdir(parents=True, exist_ok=True)
    semantics = audit_semantics(output_dir)
    arms = [build_arm(output_dir, asset, bool(semantics["semantics_passed"])) for asset in ASSETS]
    passing = sum(arm["source_contract_passed"] for arm in arms)
    passed = passing == len(ASSETS)
    evidence: dict[str, Any] = {
        "family_id": FAMILY_ID,
        "issue": ISSUE,
        "repository_main": REPOSITORY_MAIN,
        "tested_head": tested_head,
        "provider": "OKX",
        "endpoint": helper.HISTORY_PATH,
        "bar": "1H",
        "sample_start": "2023-04-01T00:00:00Z",
        "sample_end": "2025-12-31T23:00:00Z",
        "expected_rows_per_arm": EXPECTED_ROWS,
        "canonical_fee_bps_one_way": 5.0,
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "source_semantics": semantics,
        "source_arms": arms,
        "source_arms_passing": passing,
        "source_contract_passed": passed,
        "verdict": PASS_VERDICT if passed else FAIL_VERDICT,
        "economics": dict(NULL_ECONOMICS),
    }
    evidence.update({field: False for field in FALSE_FIELDS})
    evidence_sha = helper.write_hashed(output_dir, "evidence.json", helper.canonical(evidence))
    report_sha = helper.write_hashed(output_dir, "report.md", report(evidence).encode())
    manifest_sha = helper.write_hashed(
        output_dir,
        "source_manifest.json",
        helper.canonical(source_manifest(output_dir)),
    )
    summary = {
        "family_id": FAMILY_ID,
        "tested_head": tested_head,
        "evidence_sha256": evidence_sha,
        "report_sha256": report_sha,
        "source_manifest_sha256": manifest_sha,
        "source_arms_passing": passing,
        "source_contract_passed": passed,
        "verdict": evidence["verdict"],
        "candidate_count": 0,
        "parameter_grid_count": 0,
    }
    helper.write_hashed(output_dir, "artifact_summary.json", helper.canonical(summary))
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tested-head", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.tested_head, args.output_dir), sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
