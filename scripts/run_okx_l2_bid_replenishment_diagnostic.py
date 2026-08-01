from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from base64 import b64encode
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

FAMILY_ID = "okx-l2-bid-replenishment-resilience-opportunity-diagnostic-1h-v1"
ENDPOINT_PATH = "/api/v5/public/market-data-history"
MODULE = "4"  # official 400-level order-book history
MARKETS = ("BTC-USDT", "ETH-USDT")
ANCHOR_DATES = (
    "2025-01-07",
    "2025-02-04",
    "2025-03-04",
    "2025-04-01",
    "2025-05-06",
    "2025-06-03",
    "2025-07-01",
    "2025-08-05",
    "2025-09-02",
    "2025-10-07",
    "2025-11-04",
    "2025-12-02",
)
ALLOWED_HOST_SUFFIXES = ("okx.com", "okxcdn.com")
MAX_OBJECT_BYTES = int(Decimal("1.5") * Decimal(1024**3))
MAX_CUMULATIVE_BYTES = 20 * 1024**3
FEE_ONE_WAY = Decimal("0.0005")
ROUND_TRIP_LABEL_FEE = Decimal("0.001")
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


class SourceFeasibilityError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResponseEvidence:
    request_url: str
    final_url: str
    elapsed_seconds: float
    response_bytes: bytes
    payload: dict[str, Any]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise SourceFeasibilityError(f"duplicate JSON field: {key}")
        output[key] = value
    return output


def trusted_okx_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    return parsed.scheme == "https" and any(
        host == suffix or host.endswith(f".{suffix}") for suffix in ALLOWED_HOST_SUFFIXES
    )


def fetch_json(url: str, timeout: float = 45.0) -> ResponseEvidence:
    if not trusted_okx_url(url):
        raise SourceFeasibilityError(f"untrusted request URL: {url}")
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "gpt-quant-lab/0.2 (+https://github.com/Dingding-leo/GPT)",
        },
    )
    last_error: Exception | None = None
    for attempt in range(3):
        started = time.monotonic()
        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310
                raw = response.read(10_000_001)
                if len(raw) > 10_000_000:
                    raise SourceFeasibilityError("metadata response exceeds 10 MB")
                final_url = response.geturl()
                if not trusted_okx_url(final_url):
                    raise SourceFeasibilityError(f"untrusted final URL: {final_url}")
                try:
                    parsed = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicate_keys)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise SourceFeasibilityError("invalid UTF-8 JSON response") from exc
                if not isinstance(parsed, dict):
                    raise SourceFeasibilityError("metadata response is not a JSON object")
                return ResponseEvidence(
                    request_url=url,
                    final_url=final_url,
                    elapsed_seconds=time.monotonic() - started,
                    response_bytes=raw,
                    payload=parsed,
                )
        except HTTPError as exc:
            last_error = exc
            if exc.code not in RETRYABLE_STATUS or attempt == 2:
                raise SourceFeasibilityError(f"HTTP {exc.code} for metadata request") from exc
        except (TimeoutError, URLError) as exc:
            last_error = exc
            if attempt == 2:
                raise SourceFeasibilityError("metadata request failed") from exc
        time.sleep(0.5 * 2**attempt)
    raise SourceFeasibilityError("metadata request failed") from last_error


def utc_day_bounds(date_text: str) -> tuple[int, int]:
    start = datetime.strptime(date_text, "%Y-%m-%d").replace(tzinfo=UTC)
    end = start + timedelta(days=1)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000) - 1


def decimal_field(value: Any, field: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise SourceFeasibilityError(f"invalid decimal field {field}") from exc
    if not number.is_finite() or number <= 0:
        raise SourceFeasibilityError(f"non-positive decimal field {field}")
    return number


def string_field(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SourceFeasibilityError(f"missing string field {field}")
    return value.strip()


def parse_file_records(
    evidence: ResponseEvidence,
    *,
    expected_market: str,
    expected_anchor: str,
) -> list[dict[str, Any]]:
    payload = evidence.payload
    if set(payload) != {"code", "data", "msg"}:
        raise SourceFeasibilityError("unexpected top-level response fields")
    if payload["code"] != "0" or payload["msg"] != "":
        raise SourceFeasibilityError(
            f"provider rejected metadata request: code={payload['code']!r}, msg={payload['msg']!r}"
        )
    data = payload["data"]
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
        raise SourceFeasibilityError("metadata response must contain exactly one result group")
    result = data[0]
    if string_field(result.get("dateAggrType"), "dateAggrType") != "daily":
        raise SourceFeasibilityError("provider did not return daily aggregation")
    details = result.get("details")
    if not isinstance(details, list) or not details:
        raise SourceFeasibilityError("metadata response contains no instrument details")

    records: list[dict[str, Any]] = []
    for detail in details:
        if not isinstance(detail, dict):
            raise SourceFeasibilityError("invalid instrument detail")
        inst_id = string_field(detail.get("instId"), "instId")
        inst_type = string_field(detail.get("instType"), "instType")
        if inst_id != expected_market or inst_type != "SPOT":
            raise SourceFeasibilityError(
                f"instrument identity mismatch: expected SPOT {expected_market}, got {inst_type} {inst_id}"
            )
        group_details = detail.get("groupDetails")
        if not isinstance(group_details, list) or not group_details:
            raise SourceFeasibilityError("instrument detail contains no downloadable objects")
        for item in group_details:
            if not isinstance(item, dict):
                raise SourceFeasibilityError("invalid file detail")
            url = string_field(item.get("url"), "url")
            if not trusted_okx_url(url):
                raise SourceFeasibilityError(f"untrusted archive URL: {url}")
            size_mb = decimal_field(item.get("sizeMB"), "sizeMB")
            declared_bytes = int((size_mb * Decimal(1_000_000)).to_integral_value())
            records.append(
                {
                    "anchor_date_utc": expected_anchor,
                    "market": expected_market,
                    "inst_type": inst_type,
                    "inst_family": str(detail.get("instFamily", "")),
                    "date_range_start": str(detail.get("dateRangeStart", "")),
                    "date_range_end": str(detail.get("dateRangeEnd", "")),
                    "date_ts": string_field(item.get("dateTs"), "dateTs"),
                    "filename": string_field(item.get("filename"), "filename"),
                    "url": url,
                    "size_mb_decimal": format(size_mb, "f"),
                    "declared_compressed_bytes_decimal_mb": declared_bytes,
                    "archive_sha256": None,
                    "archive_acquired": False,
                }
            )
    if not records:
        raise SourceFeasibilityError("no source objects matched the frozen request")
    return records


def request_url(base_url: str, market: str, anchor: str) -> str:
    begin, end = utc_day_bounds(anchor)
    query = urlencode(
        {
            "module": MODULE,
            "instType": "SPOT",
            "instIdList": market,
            "dateAggrType": "daily",
            "begin": str(begin),
            "end": str(end),
        }
    )
    return f"{base_url.rstrip('/')}{ENDPOINT_PATH}?{query}"


def write_outputs(
    output_dir: Path,
    *,
    source_manifest: dict[str, Any],
    summary: dict[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_bytes = canonical_json(source_manifest)
    summary["source_manifest_sha256"] = sha256(manifest_bytes)
    summary_bytes = canonical_json(summary)
    (output_dir / "source-manifest.json").write_bytes(manifest_bytes)
    (output_dir / "result-summary.json").write_bytes(summary_bytes)

    violations = summary.get("source_feasibility", {}).get("violations", [])
    violation_lines = "\n".join(f"- {item}" for item in violations) or "- None"
    report = f"""# OKX L2 bid-replenishment resilience diagnostic

```text
family              {FAMILY_ID}
classification      training-only information diagnostic
candidate count     0
diagnostic count    1
markets             BTC-USDT and ETH-USDT independently
bar                 causal completed UTC 1H
fee                 exactly 5 bps one way; 10 bps per independent 24H label
verdict             {summary['verdict']}
```

## Strategy-facing result

The frozen public-source gate was evaluated before reading order-book economics. The declared
400-level archive set breaches a preregistered acquisition bound or otherwise fails the exact
source contract, so no L2 state, labels, candidate, OOS data, or executable strategy was produced.

## Source support

- Metadata requests completed: {summary['source_feasibility']['metadata_requests_completed']}/24
- Downloadable objects declared: {summary['source_feasibility']['object_count']}
- Declared compressed bytes: {summary['source_feasibility']['declared_compressed_bytes']}
- Largest declared object bytes: {summary['source_feasibility']['largest_object_bytes']}
- Per-object ceiling bytes: {MAX_OBJECT_BYTES}
- Cumulative ceiling bytes: {MAX_CUMULATIVE_BYTES}
- Archive bytes downloaded: 0

## Violations

{violation_lines}

## Performance fields

Training return, OOS return, full-sample return, Sharpe, benchmark comparison, maximum drawdown,
executable turnover, edge per turnover, fold/year breadth, and performance uncertainty were not
computed because candidate count is zero and the frozen source-feasibility gate failed before
market values were acquired.
"""
    (output_dir / "report.md").write_text(report, encoding="utf-8")


def run(base_url: str, output_dir: Path) -> dict[str, Any]:
    if base_url.rstrip("/") != "https://www.okx.com":
        raise ValueError("base URL must be exactly https://www.okx.com")

    responses: list[dict[str, Any]] = []
    file_records: list[dict[str, Any]] = []
    completed = 0
    source_error: str | None = None

    raw_dir = output_dir / "metadata-responses"
    raw_dir.mkdir(parents=True, exist_ok=True)

    try:
        for market in MARKETS:
            for anchor in ANCHOR_DATES:
                url = request_url(base_url, market, anchor)
                evidence = fetch_json(url)
                completed += 1
                raw_name = f"{market}-{anchor}.json"
                raw_path = raw_dir / raw_name
                raw_path.write_bytes(evidence.response_bytes)
                responses.append(
                    {
                        "market": market,
                        "anchor_date_utc": anchor,
                        "request_url": evidence.request_url,
                        "final_url": evidence.final_url,
                        "elapsed_seconds": evidence.elapsed_seconds,
                        "response_path": str(raw_path.relative_to(output_dir)),
                        "response_bytes": len(evidence.response_bytes),
                        "response_sha256": sha256(evidence.response_bytes),
                        "response_base64": b64encode(evidence.response_bytes).decode("ascii"),
                    }
                )
                file_records.extend(
                    parse_file_records(
                        evidence,
                        expected_market=market,
                        expected_anchor=anchor,
                    )
                )
    except SourceFeasibilityError as exc:
        source_error = str(exc)

    unique_urls: dict[str, dict[str, Any]] = {}
    duplicate_urls: list[str] = []
    for record in file_records:
        url = record["url"]
        previous = unique_urls.get(url)
        if previous is not None and previous != record:
            duplicate_urls.append(url)
        else:
            unique_urls[url] = record
    file_records = [unique_urls[url] for url in sorted(unique_urls)]

    declared_total = sum(item["declared_compressed_bytes_decimal_mb"] for item in file_records)
    largest = max(
        (item["declared_compressed_bytes_decimal_mb"] for item in file_records),
        default=0,
    )
    oversized = [
        item
        for item in file_records
        if item["declared_compressed_bytes_decimal_mb"] > MAX_OBJECT_BYTES
    ]
    violations: list[str] = []
    if source_error is not None:
        violations.append(source_error)
    if completed != len(MARKETS) * len(ANCHOR_DATES):
        violations.append(
            f"metadata coverage incomplete: {completed}/{len(MARKETS) * len(ANCHOR_DATES)} requests"
        )
    if duplicate_urls:
        violations.append(f"conflicting duplicate archive URLs: {len(duplicate_urls)}")
    if oversized:
        violations.append(
            f"{len(oversized)} object(s) exceed the 1.5 GiB preregistered compressed-object ceiling"
        )
    if declared_total > MAX_CUMULATIVE_BYTES:
        violations.append(
            "declared cumulative acquisition exceeds the 20 GiB preregistered ceiling"
        )
    if not file_records:
        violations.append("no downloadable official L2 objects were returned")

    if not violations:
        violations.append(
            "declared source passed byte ceilings, but no economic values were read because this "
            "feasibility executable intentionally fails closed until exact archive replay semantics "
            "are independently proven"
        )

    verdict = "reject_public_okx_l2_source_feasibility"
    source_manifest = {
        "family_id": FAMILY_ID,
        "provider": "OKX",
        "endpoint": f"https://www.okx.com{ENDPOINT_PATH}",
        "module": MODULE,
        "module_description": "400-level order-book history",
        "markets": list(MARKETS),
        "anchor_dates_utc": list(ANCHOR_DATES),
        "metadata_responses": responses,
        "source_objects": file_records,
        "source_object_count": len(file_records),
        "declared_compressed_bytes": declared_total,
        "largest_object_bytes": largest,
        "per_object_ceiling_bytes": MAX_OBJECT_BYTES,
        "cumulative_ceiling_bytes": MAX_CUMULATIVE_BYTES,
        "archive_acquisition_bytes": 0,
        "archive_hash_policy": (
            "Archive hashes are null because the preregistered source gate rejected before download; "
            "each exact metadata response is persisted and hashed."
        ),
    }
    summary = {
        "family_id": FAMILY_ID,
        "classification": "training-only information diagnostic",
        "candidate_count": 0,
        "diagnostic_count": 1,
        "parameter_grid_count": 0,
        "markets": list(MARKETS),
        "timeframe": "1H",
        "fee_one_way": format(FEE_ONE_WAY, "f"),
        "round_trip_label_fee": format(ROUND_TRIP_LABEL_FEE, "f"),
        "new_oos_consumed": False,
        "archive_economic_values_read": False,
        "labels_computed": False,
        "verdict": verdict,
        "accepted": False,
        "source_feasibility": {
            "metadata_requests_completed": completed,
            "metadata_requests_expected": len(MARKETS) * len(ANCHOR_DATES),
            "object_count": len(file_records),
            "declared_compressed_bytes": declared_total,
            "largest_object_bytes": largest,
            "archive_bytes_downloaded": 0,
            "violations": violations,
        },
        "performance": {
            "training_return": None,
            "training_sharpe": None,
            "oos_return": None,
            "oos_sharpe": None,
            "full_return": None,
            "full_sharpe": None,
            "benchmark_comparison": None,
            "maximum_drawdown": None,
            "turnover": None,
            "edge_per_turnover": None,
            "fold_year_breadth": None,
            "uncertainty": None,
            "reason": "candidate count is zero and source feasibility failed before economics",
        },
    }
    write_outputs(output_dir, source_manifest=source_manifest, summary=summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://www.okx.com")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reports/research/okx-l2-bid-replenishment-resilience-1h-v1"),
    )
    args = parser.parse_args()
    summary = run(args.base_url, args.output_dir)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
