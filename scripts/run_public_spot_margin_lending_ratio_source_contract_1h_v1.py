from __future__ import annotations

import argparse
import csv
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

FAMILY = "causal-public-spot-margin-lending-ratio-source-contract-1h-v1"
PASS = "accept_public_spot_margin_lending_ratio_1h_source_for_separate_training_predeclaration"
FAIL = "reject_causal_public_spot_margin_lending_ratio_source_contract_1h_v1"
MAIN = "5a0fcc97d1a882f8223656c51f5bb8055f534e38"
ISSUE = 993
BASE = "https://www.okx.com"
PATH = "/api/v5/rubik/stat/margin/loan-ratio"
DOCS = "https://www.okx.com/docs-v5/en/"
ASSETS = ("BTC", "ETH")
PERIOD = "1H"
HOUR = 3_600_000
START = 1_680_307_200_000
END = 1_767_222_000_000
ROWS = 24_144
CHUNK = 96
MIN_DISTINCT = 30
NULL_ECONOMICS = {
    key: None
    for key in (
        "feature candidate_state train_net_return train_sharpe oos_net_return oos_sharpe "
        "full_net_return full_sharpe e2160_net_return e2160_sharpe always_long_net_return "
        "always_long_sharpe turnover modeled_fees maximum_drawdown edge_per_turnover_bps "
        "fold_breadth calendar_year_breadth dependence_aware_uncertainty one_hour_delay"
    ).split()
}
CONTROLS = {
    key: False
    for key in (
        "candidate_created target_price_data_downloaded target_returns_downloaded "
        "performance_accessed oos_accessed synthetic_data_used interpolation_or_fill_used "
        "credentials_used private_endpoints_used accounts_balances_or_orders enabled_adapters "
        "leverage_or_funds_used cross_sectional_asset_selection current_relative_rank "
        "pairs_spreads_cointegration_or_stat_arb market_neutral_or_long_short "
        "post_hoc_asset_filtering canonical_strategy_changed paper_trading_authorized "
        "live_trading_authorized"
    ).split()
}


class SourceError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


OPENER = urllib.request.build_opener(NoRedirect)
LAST_REQUEST = 0.0


def canonical(value: Any) -> bytes:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return (text + "\n").encode()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_hashed(root: Path, name: str, data: bytes) -> str:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    value = digest(data)
    path.with_name(path.name + ".sha256").write_text(value + "\n")
    return value


def request(url: str) -> tuple[bytes, dict[str, Any]]:
    global LAST_REQUEST
    errors: list[str] = []
    for attempt in range(1, 6):
        wait = 0.30 - (time.monotonic() - LAST_REQUEST)
        if wait > 0:
            time.sleep(wait)
        LAST_REQUEST = time.monotonic()
        started = datetime.now(UTC).isoformat()
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
                "User-Agent": "Dingding-leo-GPT-margin-ratio-audit/1.0",
            },
        )
        try:
            with OPENER.open(req, timeout=45) as response:  # noqa: S310
                body = response.read(8_000_001)
                if len(body) > 8_000_000:
                    raise SourceError("response exceeds byte cap")
                return body, {
                    "url": url,
                    "final_url": response.geturl(),
                    "status": int(getattr(response, "status", 200)),
                    "started_utc": started,
                    "received_utc": datetime.now(UTC).isoformat(),
                    "content_type": response.headers.get("Content-Type"),
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
                    "started_utc": started,
                    "received_utc": datetime.now(UTC).isoformat(),
                    "content_type": exc.headers.get("Content-Type") if exc.headers else None,
                    "bytes": len(body),
                    "sha256": digest(body),
                    "attempt": attempt,
                }
            errors.append(f"HTTP {exc.code}")
        except (OSError, TimeoutError, urllib.error.URLError, SourceError) as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
        if attempt < 5:
            time.sleep(min(2**attempt, 16))
    raise SourceError("; ".join(errors))


def save_raw(root: Path, name: str, body: bytes, meta: dict[str, Any]) -> None:
    write_hashed(root, f"raw/{name}.body", body)
    write_hashed(root, f"raw/{name}.metadata.json", canonical(meta))


def url(asset: str, begin: int, end: int) -> str:
    query = urllib.parse.urlencode(
        {"ccy": asset, "period": PERIOD, "begin": str(begin), "end": str(end)}
    )
    return f"{BASE}{PATH}?{query}"


def fetch(root: Path, asset: str, begin: int, end: int, name: str) -> dict[str, Any]:
    request_url = url(asset, begin, end)
    parsed = urllib.parse.urlsplit(request_url)
    query = urllib.parse.parse_qs(parsed.query)
    identity = (
        parsed.scheme == "https"
        and parsed.netloc == "www.okx.com"
        and parsed.path == PATH
        and query.get("ccy") == [asset]
        and query.get("period") == [PERIOD]
        and not {"key", "token", "secret", "passphrase"}.intersection(query)
    )
    body, meta = request(request_url)
    save_raw(root, name, body, meta)
    result: dict[str, Any] = {"identity": identity, "meta": meta, "rows": []}
    if not identity or meta["status"] != 200 or meta["final_url"] != request_url:
        result["error"] = "endpoint identity or HTTP failure"
        return result
    try:
        payload = json.loads(body)
        if set(payload) != {"code", "data", "msg"} or payload["code"] != "0":
            raise SourceError(f"provider response {payload!r}")
        for item in payload["data"]:
            if not isinstance(item, list) or len(item) != 2:
                raise SourceError("response row is not [timestamp, ratio]")
            ts, ratio = int(item[0]), float(item[1])
            if ts % HOUR or not math.isfinite(ratio) or ratio <= 0:
                raise SourceError("invalid timestamp or ratio")
            result["rows"].append({"ts": str(ts), "ratio": str(item[1])})
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, SourceError) as exc:
        result["error"] = str(exc)
    return result


def exact_grid(rows: list[dict[str, str]], begin: int, end: int) -> bool:
    return sorted(int(row["ts"]) for row in rows) == list(range(begin, end + HOUR, HOUR))


def quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return ordered[low]
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def probe(root: Path, asset: str) -> dict[str, Any]:
    windows = {
        "start": (START, START + 47 * HOUR),
        "middle": (START + 12_000 * HOUR, START + 12_047 * HOUR),
        "end": (END - 47 * HOUR, END),
    }
    evidence: dict[str, Any] = {}
    for name, (begin, end) in windows.items():
        response = fetch(root, asset, begin, end, f"probes/{asset.lower()}-{name}")
        rows = response.pop("rows")
        evidence[name] = {
            **response,
            "row_count": len(rows),
            "exact_requested_grid": not response.get("error") and exact_grid(rows, begin, end),
            "normalized_sha256": digest(canonical(sorted(rows, key=lambda row: int(row["ts"])))),
        }
    passed = all(item["exact_requested_grid"] for item in evidence.values())
    return {"passed": passed, "windows": evidence}


def acquire(root: Path, asset: str, label: str) -> dict[str, Any]:
    rows_by_time: dict[int, dict[str, str]] = {}
    requests: list[dict[str, Any]] = []
    conflict = False
    begin = START
    index = 0
    while begin <= END:
        end = min(END, begin + (CHUNK - 1) * HOUR)
        response = fetch(root, asset, begin, end, f"{label}/{asset.lower()}/{index:03d}")
        rows = response.pop("rows")
        exact = not response.get("error") and exact_grid(rows, begin, end)
        requests.append(
            {
                "begin": begin,
                "end": end,
                "row_count": len(rows),
                "exact_grid": exact,
                "raw_sha256": response["meta"]["sha256"],
                "error": response.get("error"),
            }
        )
        for row in rows:
            ts = int(row["ts"])
            conflict = conflict or (ts in rows_by_time and rows_by_time[ts] != row)
            rows_by_time[ts] = row
        begin = end + HOUR
        index += 1
    rows = [rows_by_time[ts] for ts in sorted(rows_by_time)]
    ratios = [float(row["ratio"]) for row in rows]
    return {
        "rows": rows,
        "request_count": len(requests),
        "request_sha256": digest(canonical(requests)),
        "all_requests_exact": all(item["exact_grid"] for item in requests),
        "conflict": conflict,
        "observed_rows": len(rows),
        "complete_grid": exact_grid(rows, START, END),
        "distinct": len(set(ratios)),
        "minimum": min(ratios) if ratios else None,
        "maximum": max(ratios) if ratios else None,
        "iqr": quantile(ratios, 0.75) - quantile(ratios, 0.25) if ratios else None,
        "normalized_sha256": digest(canonical(rows)),
    }


def write_panel(root: Path, asset: str, rows: list[dict[str, str]]) -> str:
    path = root / "panels" / f"{asset.lower()}-margin-lending-ratio-1h.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["ts", "ratio"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    value = digest(path.read_bytes())
    path.with_name(path.name + ".sha256").write_text(value + "\n")
    return value


def arm(root: Path, asset: str) -> dict[str, Any]:
    source_probe = probe(root, asset)
    if not source_probe["passed"]:
        return {
            "asset": asset,
            "probe": source_probe,
            "full_acquisition_attempted": False,
            "observed_rows": 0,
            "source_contract_passed": False,
            "failure_reasons": ["historical_boundary_or_window_semantics_failed"],
        }
    first, second = acquire(root, asset, "acquisition-a"), acquire(root, asset, "acquisition-b")
    rows = first.pop("rows")
    second_rows = second.pop("rows")
    ratios = [float(row["ratio"]) for row in rows]
    extended = fetch(root, asset, START, END + 24 * HOUR, f"probes/{asset.lower()}-extended")
    prefix = [row for row in extended.pop("rows") if START <= int(row["ts"]) <= END]
    checks = {
        "expected_rows": first["observed_rows"] == ROWS,
        "complete_grid": first["complete_grid"],
        "all_requests_exact": first["all_requests_exact"],
        "no_conflicts": not first["conflict"],
        "repeat_identity": rows == second_rows,
        "prefix_invariance": not extended.get("error") and prefix == rows,
        "finite_positive": len(ratios) == ROWS and all(value > 0 for value in ratios),
        "minimum_distinct": len(set(ratios)) >= MIN_DISTINCT,
        "positive_iqr": bool(ratios) and quantile(ratios, 0.75) > quantile(ratios, 0.25),
    }
    return {
        "asset": asset,
        "probe": source_probe,
        "full_acquisition_attempted": True,
        "observed_rows": first["observed_rows"],
        "acquisition_a": first,
        "acquisition_b": second,
        "panel_csv_sha256": write_panel(root, asset, rows),
        "checks": checks,
        "failure_reasons": [name for name, passed in checks.items() if not passed],
        "source_contract_passed": all(checks.values()),
    }


def manifest(root: Path) -> dict[str, Any]:
    records = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "source_manifest.json":
            data = path.read_bytes()
            records.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "bytes": len(data),
                    "sha256": digest(data),
                }
            )
    return {
        "record_count": len(records),
        "total_bytes": sum(item["bytes"] for item in records),
        "records": records,
    }


def run(root: Path, tested_head: str) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    semantic = {
        "provider": "OKX",
        "official_docs_url": DOCS,
        "endpoint": PATH,
        "authentication": "not required/public",
        "object": "spot-margin lending ratio",
        "definition": (
            "cumulative value of quote-currency loans divided by cumulative value of "
            "underlying-currency loans"
        ),
        "period": PERIOD,
        "window_parameters": ["begin", "end"],
        "response_row": ["timestamp_ms", "ratio"],
        "frozen_before_acquisition": True,
    }
    write_hashed(root, "semantic_contract.json", canonical(semantic))
    arms = [arm(root, asset) for asset in ASSETS]
    passing = sum(int(item["source_contract_passed"]) for item in arms)
    evidence = {
        "family_id": FAMILY,
        "issue": ISSUE,
        "tested_head": tested_head,
        "repository_main": MAIN,
        "provider": "OKX",
        "endpoint": PATH,
        "bar": PERIOD,
        "sample_start_ms": START,
        "sample_end_ms": END,
        "expected_rows_per_arm": ROWS,
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "canonical_fee_bps_one_way": 5.0,
        "source_arms": arms,
        "source_arms_passing": passing,
        "source_contract_passed": passing == 2,
        "controls": CONTROLS,
        "economics": NULL_ECONOMICS,
        "verdict": PASS if passing == 2 else FAIL,
        "generated_utc": datetime.now(UTC).isoformat(),
    }
    evidence_hash = write_hashed(root, "evidence.json", canonical(evidence))
    report = (
        "# Public spot-margin lending-ratio source contract 1H v1\n\n"
        f"- Tested head: `{tested_head}`\n"
        f"- Source arms passing: `{passing}/2`\n"
        f"- Candidate count: `0`\n"
        f"- OOS accessed: `False`\n"
        f"- Verdict: `{evidence['verdict']}`\n\n"
        "No target prices, returns, benchmarks, turnover, drawdown, uncertainty, fold/year "
        "breadth, or OOS values were accessed; all strategy economics are null.\n"
    ).encode()
    report_hash = write_hashed(root, "report.md", report)
    source_manifest = manifest(root)
    manifest_hash = write_hashed(root, "source_manifest.json", canonical(source_manifest))
    write_hashed(
        root,
        "artifact_summary.json",
        canonical(
            {
                "family_id": FAMILY,
                "tested_head": tested_head,
                "verdict": evidence["verdict"],
                "source_arms_passing": passing,
                "evidence_sha256": evidence_hash,
                "report_sha256": report_hash,
                "source_manifest_sha256": manifest_hash,
            }
        ),
    )
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tested-head", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    if len(args.tested_head) != 40 or any(ch not in "0123456789abcdef" for ch in args.tested_head):
        raise SystemExit("--tested-head must be a lowercase 40-character SHA")
    evidence = run(args.output_dir, args.tested_head)
    print(json.dumps({"verdict": evidence["verdict"], "passing": evidence["source_arms_passing"]}))


if __name__ == "__main__":
    main()
