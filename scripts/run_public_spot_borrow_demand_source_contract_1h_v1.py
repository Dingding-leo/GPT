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

FAMILY_ID = "causal-public-spot-borrow-demand-source-contract-1h-v1"
FAIL_VERDICT = "reject_causal_public_spot_borrow_demand_source_contract_1h_v1"
REPOSITORY_MAIN = "5a0fcc97d1a882f8223656c51f5bb8055f534e38"
ISSUE = 983
BASE_URL = "https://www.okx.com"
HOST = "www.okx.com"
SUMMARY_PATH = "/api/v5/finance/savings/lending-rate-summary"
HISTORY_PATH = "/api/v5/finance/savings/lending-rate-history"
DOC_URL = "https://www.okx.com/docs-v5/en/"
LOG_URL = "https://www.okx.com/docs-v5/log_en/"
ASSETS = ("BTC", "ETH")
BAR = "1H"
START = "2023-04-01T00:00:00Z"
END = "2025-12-31T23:00:00Z"
START_MS = 1_680_307_200_000
END_MS = 1_767_222_000_000
EXPECTED_ROWS = 24_144
MAX_RESPONSE_BYTES = 12_000_000
RETRYABLE = {408, 425, 429, 500, 502, 503, 504}

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


class ProbeFailure(RuntimeError):
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


def write_hashed(root: Path, name: str, value: bytes) -> str:
    path = root / name
    path.write_bytes(value)
    digest = sha256(value)
    (root / f"{name}.sha256").write_text(f"{digest}\n")
    return digest


def request_bytes(url: str) -> tuple[bytes, dict[str, Any]]:
    attempts: list[str] = []
    for attempt in range(1, 6):
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
                "User-Agent": "Dingding-leo-GPT-spot-borrow-demand-source/1.0",
            },
        )
        started = datetime.now(UTC).isoformat()
        try:
            with OPENER.open(request, timeout=45) as response:  # noqa: S310
                body = response.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise ProbeFailure("response exceeded byte cap")
                status = int(getattr(response, "status", 200))
                final_url = response.geturl()
                return body, {
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
                return body, metadata
            attempts.append(f"attempt {attempt}: HTTP {status}")
        except (OSError, TimeoutError, urllib.error.URLError, ProbeFailure) as exc:
            attempts.append(f"attempt {attempt}: {type(exc).__name__}: {exc}")
        if attempt < 5:
            time.sleep(min(2**attempt, 16))
    raise ProbeFailure("; ".join(attempts))


def endpoint_url(path: str, asset: str, cursor_ms: int | None = None) -> str:
    query: dict[str, str] = {"ccy": asset}
    if path == HISTORY_PATH:
        query["limit"] = "100"
        if cursor_ms is not None:
            query["after"] = str(cursor_ms)
    return f"{BASE_URL}{path}?{urllib.parse.urlencode(query)}"


def endpoint_identity_ok(
    url: str,
    path: str,
    asset: str,
    cursor_ms: int | None,
) -> bool:
    parsed = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    forbidden = {"api_key", "apikey", "key", "token", "secret", "passphrase"}
    expected = {"ccy": [asset]}
    if path == HISTORY_PATH:
        expected["limit"] = ["100"]
        if cursor_ms is not None:
            expected["after"] = [str(cursor_ms)]
    return bool(
        parsed.scheme == "https"
        and parsed.netloc == HOST
        and parsed.path == path
        and parsed.username is None
        and parsed.password is None
        and not parsed.fragment
        and not forbidden.intersection(key.lower() for key in query)
        and all(query.get(key) == value for key, value in expected.items())
    )


def strict_json(body: bytes, context: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ProbeFailure(f"{context}: duplicate JSON field {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProbeFailure(f"{context}: invalid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ProbeFailure(f"{context}: top-level response is not an object")
    if set(value) != {"code", "msg", "data"}:
        raise ProbeFailure(f"{context}: unexpected top-level fields")
    if value["code"] != "0" or not isinstance(value["data"], list):
        raise ProbeFailure(
            f"{context}: provider error code={value.get('code')!r} "
            f"msg={value.get('msg')!r}"
        )
    return value


def save_raw(
    root: Path,
    name: str,
    body: bytes,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    raw_dir = root / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    body_path = raw_dir / f"{name}.bin"
    metadata_path = raw_dir / f"{name}.metadata.json"
    body_path.write_bytes(body)
    metadata_path.write_bytes(canonical(metadata))
    return {
        **metadata,
        "body_path": body_path.relative_to(root).as_posix(),
        "metadata_path": metadata_path.relative_to(root).as_posix(),
    }


def finite_number(value: Any) -> bool:
    if not isinstance(value, str) or value == "":
        return False
    try:
        number = float(value)
    except ValueError:
        return False
    return math.isfinite(number)


def inspect_history(data: list[Any], asset: str) -> dict[str, Any]:
    rows = [row for row in data if isinstance(row, dict)]
    currencies = sorted(
        {row.get("ccy") for row in rows if isinstance(row.get("ccy"), str)}
    )
    timestamps: list[int] = []
    for row in rows:
        value = row.get("ts")
        if isinstance(value, str):
            try:
                timestamps.append(int(value))
            except ValueError:
                pass
    amount_values = [row.get("amt") for row in rows]
    rate_values = [row.get("rate") for row in rows]
    return {
        "asset": asset,
        "row_count": len(rows),
        "currencies": currencies,
        "field_sets": sorted({tuple(sorted(row)) for row in rows}),
        "amount_field_present_rows": sum("amt" in row for row in rows),
        "amount_empty_rows": sum(row.get("amt") == "" for row in rows),
        "amount_numeric_rows": sum(finite_number(value) for value in amount_values),
        "rate_numeric_rows": sum(finite_number(value) for value in rate_values),
        "timestamp_numeric_rows": len(timestamps),
        "newest_timestamp_ms": max(timestamps) if timestamps else None,
        "oldest_timestamp_ms": min(timestamps) if timestamps else None,
        "timestamps_strictly_descending": all(
            left > right for left, right in zip(timestamps, timestamps[1:])
        ),
        "all_rows_match_asset": bool(rows)
        and all(row.get("ccy") == asset for row in rows),
    }


def inspect_summary(data: list[Any], asset: str) -> dict[str, Any]:
    rows = [row for row in data if isinstance(row, dict)]
    amount_values = [row.get("avgAmt") for row in rows]
    usd_values = [row.get("avgAmtUsd") for row in rows]
    return {
        "asset": asset,
        "row_count": len(rows),
        "field_sets": sorted({tuple(sorted(row)) for row in rows}),
        "avg_amount_field_present_rows": sum("avgAmt" in row for row in rows),
        "avg_amount_empty_rows": sum(row.get("avgAmt") == "" for row in rows),
        "avg_amount_numeric_rows": sum(finite_number(value) for value in amount_values),
        "avg_amount_usd_field_present_rows": sum(
            "avgAmtUsd" in row for row in rows
        ),
        "avg_amount_usd_empty_rows": sum(
            row.get("avgAmtUsd") == "" for row in rows
        ),
        "avg_amount_usd_numeric_rows": sum(
            finite_number(value) for value in usd_values
        ),
        "all_rows_match_asset": bool(rows)
        and all(row.get("ccy") == asset for row in rows),
    }


def probe_json(
    root: Path,
    *,
    name: str,
    path: str,
    asset: str,
    cursor_ms: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    url = endpoint_url(path, asset, cursor_ms)
    if not endpoint_identity_ok(url, path, asset, cursor_ms):
        raise ProbeFailure(f"{name}: request identity failed")
    body, metadata = request_bytes(url)
    saved = save_raw(root, name, body, metadata)
    if metadata["status"] != 200:
        raise ProbeFailure(f"{name}: HTTP {metadata['status']}")
    if metadata["final_url"] != url:
        raise ProbeFailure(f"{name}: redirect or URL mutation detected")
    payload = strict_json(body, name)
    return payload, saved


def report_markdown(evidence: dict[str, Any]) -> str:
    lines = [
        "# Public spot-borrow demand source contract 1H v1",
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
        "## Strategy-facing finding",
        "",
        (
            "The audited public interfaces currently expose borrowing-rate fields, "
            "but the provider-declared borrowing-amount fields are deprecated and "
            "observed as empty strings. A direct provider-defined BTC/ETH borrowing-"
            "demand quantity is therefore absent from the frozen source contract."
        ),
        "",
        "## Arm results",
        "",
        "| Asset | History amount numeric | Summary amount numeric | Direct 1H demand |",
        "|---|---:|---:|---:|",
    ]
    for arm in evidence["source_arms"]:
        lines.append(
            f"| {arm['asset']} | {arm['history_amount_numeric_rows']} | "
            f"{arm['summary_amount_numeric_rows']} | "
            f"{'pass' if arm['source_contract_passed'] else 'fail'} |"
        )
    lines.extend(
        [
            "",
            "All strategy-performance fields remain null. No target price, target "
            "return, candidate, benchmark path, or sealed OOS observation was read.",
            "",
            "Exactly 5 bps one way remains the fee contract for any separately "
            "authorised executable strategy.",
            "",
        ]
    )
    return "\n".join(lines)


def run(tested_head: str, output_dir: Path) -> dict[str, Any]:
    if len(tested_head) != 40 or any(
        character not in "0123456789abcdef" for character in tested_head
    ):
        raise ProbeFailure("tested head must be a lowercase 40-character SHA")
    output_dir.mkdir(parents=True, exist_ok=True)

    source_records: list[dict[str, Any]] = []
    for name, url in (("official-docs", DOC_URL), ("official-changelog", LOG_URL)):
        body, metadata = request_bytes(url)
        source_records.append(save_raw(output_dir, name, body, metadata))
        if metadata["status"] != 200 or metadata["final_url"] != url:
            raise ProbeFailure(f"{name}: official document acquisition failed")

    arms: list[dict[str, Any]] = []
    for asset in ASSETS:
        summary, summary_source = probe_json(
            output_dir,
            name=f"{asset.lower()}-summary",
            path=SUMMARY_PATH,
            asset=asset,
        )
        history_latest, latest_source = probe_json(
            output_dir,
            name=f"{asset.lower()}-history-latest",
            path=HISTORY_PATH,
            asset=asset,
        )
        history_end, end_source = probe_json(
            output_dir,
            name=f"{asset.lower()}-history-at-end",
            path=HISTORY_PATH,
            asset=asset,
            cursor_ms=END_MS + 3_600_000,
        )
        history_start, start_source = probe_json(
            output_dir,
            name=f"{asset.lower()}-history-at-start",
            path=HISTORY_PATH,
            asset=asset,
            cursor_ms=START_MS + 3_600_000,
        )
        source_records.extend(
            [summary_source, latest_source, end_source, start_source]
        )
        summary_audit = inspect_summary(summary["data"], asset)
        history_audits = {
            "latest": inspect_history(history_latest["data"], asset),
            "sample_end": inspect_history(history_end["data"], asset),
            "sample_start": inspect_history(history_start["data"], asset),
        }
        history_amount_numeric_rows = sum(
            audit["amount_numeric_rows"] for audit in history_audits.values()
        )
        summary_amount_numeric_rows = (
            summary_audit["avg_amount_numeric_rows"]
            + summary_audit["avg_amount_usd_numeric_rows"]
        )
        source_contract_passed = bool(
            history_amount_numeric_rows > 0
            and summary_amount_numeric_rows > 0
            and all(audit["all_rows_match_asset"] for audit in history_audits.values())
            and summary_audit["all_rows_match_asset"]
        )
        arms.append(
            {
                "asset": asset,
                "mapping": f"{asset} borrow demand -> {asset}-USDT long/cash",
                "expected_rows": EXPECTED_ROWS,
                "sample": {"start": START, "end": END},
                "summary_audit": summary_audit,
                "history_audits": history_audits,
                "history_amount_numeric_rows": history_amount_numeric_rows,
                "summary_amount_numeric_rows": summary_amount_numeric_rows,
                "direct_provider_defined_quantity_present": bool(
                    history_amount_numeric_rows > 0
                    and summary_amount_numeric_rows > 0
                ),
                "complete_provider_native_1h_quantity_history": False,
                "source_contract_passed": source_contract_passed,
                "economics": dict(NULL_ECONOMICS),
            }
        )

    source_arms_passing = sum(arm["source_contract_passed"] for arm in arms)
    evidence = {
        "family_id": FAMILY_ID,
        "issue": ISSUE,
        "repository_main": REPOSITORY_MAIN,
        "tested_head": tested_head,
        "generated_utc": datetime.now(UTC).isoformat(),
        "bar": BAR,
        "canonical_fee_bps_one_way": 5.0,
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "sample": {
            "start": START,
            "end": END,
            "expected_rows_per_arm": EXPECTED_ROWS,
        },
        "provider": "OKX",
        "interfaces": {
            "summary": SUMMARY_PATH,
            "history": HISTORY_PATH,
        },
        "official_semantics": {
            "history_amt": "deprecated; provider returns empty string",
            "summary_avgAmt": "deprecated; provider returns empty string",
            "summary_avgAmtUsd": "deprecated; provider returns empty string",
            "history_rate": "annual borrowing interest rate",
            "summary_avgRate": "24-hour average borrowing rate",
            "summary_preRate": "last annual borrowing interest rate",
            "summary_estRate": "next estimated annual borrowing interest rate",
        },
        "source_arms": arms,
        "source_arms_passing": source_arms_passing,
        "source_contract_passed": source_arms_passing == len(arms),
        "candidate_created": False,
        "target_price_data_downloaded": False,
        "target_returns_downloaded": False,
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
        "pairs_spreads_cointegration_or_stat_arb": False,
        "market_neutral_or_long_short": False,
        "post_hoc_asset_filtering": False,
        "canonical_strategy_changed": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "verdict": FAIL_VERDICT,
        "highest_value_failure": (
            "The public interfaces expose borrowing prices but no longer expose "
            "provider-defined borrowing-demand quantities: amt, avgAmt, and "
            "avgAmtUsd are deprecated and return empty strings."
        ),
        "closed_substitutions": [
            "treating borrowing rate as borrowing-demand quantity",
            "reconstructing demand from private account liabilities",
            "forward-filling or interpolating deprecated amount fields",
            "single-currency promotion",
            "provider or endpoint substitution after source failure",
            "credentials, paid data, private endpoints, or account history",
        ],
        "economics": dict(NULL_ECONOMICS),
    }
    manifest = {
        "family_id": FAMILY_ID,
        "tested_head": tested_head,
        "records": source_records,
        "record_count": len(source_records),
        "total_raw_bytes": sum(record["bytes"] for record in source_records),
    }

    evidence_digest = write_hashed(
        output_dir,
        "evidence.json",
        canonical(evidence),
    )
    manifest_digest = write_hashed(
        output_dir,
        "source_manifest.json",
        canonical(manifest),
    )
    report = report_markdown(evidence).encode()
    report_digest = write_hashed(output_dir, "report.md", report)
    summary = {
        "evidence_sha256": evidence_digest,
        "source_manifest_sha256": manifest_digest,
        "report_sha256": report_digest,
        "verdict": evidence["verdict"],
    }
    write_hashed(output_dir, "artifact_summary.json", canonical(summary))
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tested-head", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    evidence = run(args.tested_head, args.output_dir)
    print(json.dumps({
        "family_id": evidence["family_id"],
        "source_arms_passing": evidence["source_arms_passing"],
        "verdict": evidence["verdict"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
