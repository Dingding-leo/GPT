from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

BASE_URL = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision/data"
FAMILY_ID = "coinm-liquidation-exhaustion-opportunity-diagnostic-1h-v1"
START_DAY = date(2024, 1, 1)
END_DAY = date(2024, 9, 30)
SCORE_START = date(2024, 2, 1)
SCORE_END = date(2024, 9, 29)
FEE_ONE_WAY = 0.0005
USER_AGENT = "gpt-quant-lab/coinm-liquidation-diagnostic"
MARKETS = {
    "BTCUSDT": "BTCUSD_PERP",
    "ETHUSDT": "ETHUSD_PERP",
}


@dataclass(frozen=True)
class ObjectSpec:
    market: str
    kind: str
    period: str
    url: str
    checksum_url: str


@dataclass(frozen=True)
class VerifiedObject:
    market: str
    kind: str
    period: str
    url: str
    checksum_url: str
    sha256: str
    byte_count: int


@dataclass(frozen=True)
class FailedObject:
    market: str
    kind: str
    period: str
    url: str
    checksum_url: str
    error: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=16)
    return parser.parse_args()


def dates(start: date, end: date) -> list[date]:
    values: list[date] = []
    current = start
    while current <= end:
        values.append(current)
        current += timedelta(days=1)
    return values


def months(start: date, end: date) -> list[str]:
    values: list[str] = []
    current = date(start.year, start.month, 1)
    while current <= end:
        values.append(current.strftime("%Y-%m"))
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)
    return values


def build_specs() -> list[ObjectSpec]:
    specs: list[ObjectSpec] = []
    for spot, coinm in MARKETS.items():
        for month in months(START_DAY, END_DAY):
            filename = f"{spot}-1h-{month}.zip"
            url = f"{BASE_URL}/spot/monthly/klines/{spot}/1h/{filename}"
            specs.append(
                ObjectSpec(
                    market=spot,
                    kind="spot_1h_kline",
                    period=month,
                    url=url,
                    checksum_url=f"{url}.CHECKSUM",
                )
            )
        for day in dates(START_DAY, END_DAY):
            period = day.isoformat()
            filename = f"{coinm}-liquidationSnapshot-{period}.zip"
            url = f"{BASE_URL}/futures/cm/daily/liquidationSnapshot/{coinm}/{filename}"
            specs.append(
                ObjectSpec(
                    market=spot,
                    kind="coinm_liquidation_snapshot",
                    period=period,
                    url=url,
                    checksum_url=f"{url}.CHECKSUM",
                )
            )
    return specs


def http_get(url: str, attempts: int = 5) -> bytes:
    last_error: Exception | None = None
    for attempt in range(attempts):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                if response.status != 200:
                    raise RuntimeError(f"unexpected HTTP status {response.status}")
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise RuntimeError(f"HTTP 404 Not Found: {url}") from exc
            last_error = exc
        except (urllib.error.URLError, TimeoutError, RuntimeError) as exc:
            last_error = exc
        if attempt + 1 < attempts:
            time.sleep(float(2**attempt))
    raise RuntimeError(f"download failed after {attempts} attempts: {url}: {last_error}")


def parse_checksum(payload: bytes, url: str) -> str:
    fields = payload.decode("utf-8", errors="strict").strip().split()
    if not fields or len(fields[0]) != 64:
        raise RuntimeError(f"invalid checksum response: {url}")
    digest = fields[0].lower()
    if any(character not in "0123456789abcdef" for character in digest):
        raise RuntimeError(f"non-hex checksum response: {url}")
    return digest


def verify_object(spec: ObjectSpec) -> VerifiedObject:
    expected = parse_checksum(http_get(spec.checksum_url), spec.checksum_url)
    payload = http_get(spec.url)
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected:
        raise RuntimeError(f"checksum mismatch: expected {expected}, observed {actual}: {spec.url}")
    return VerifiedObject(
        market=spec.market,
        kind=spec.kind,
        period=spec.period,
        url=spec.url,
        checksum_url=spec.checksum_url,
        sha256=actual,
        byte_count=len(payload),
    )


def verify_all(
    specs: list[ObjectSpec], workers: int
) -> tuple[list[VerifiedObject], list[FailedObject]]:
    verified: list[VerifiedObject] = []
    failed: list[FailedObject] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {executor.submit(verify_object, spec): spec for spec in specs}
        for future in as_completed(futures):
            spec = futures[future]
            try:
                verified.append(future.result())
            except Exception as exc:  # noqa: BLE001
                failed.append(
                    FailedObject(
                        market=spec.market,
                        kind=spec.kind,
                        period=spec.period,
                        url=spec.url,
                        checksum_url=spec.checksum_url,
                        error=str(exc),
                    )
                )
    verified.sort(key=lambda item: (item.market, item.kind, item.period))
    failed.sort(key=lambda item: (item.market, item.kind, item.period))
    return verified, failed


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def render_report(evidence: dict[str, Any]) -> str:
    source = evidence["source"]
    lines = [
        "# COIN-M liquidation-exhaustion source contract aborted",
        "",
        "```text",
        f"family          {FAMILY_ID}",
        "candidate count 0",
        "diagnostic      1",
        "parameter grid  0",
        "performance     not inspected",
        f"verdict         {evidence['verdict']}",
        "```",
        "",
        "## Fixed public-data contract",
        "",
        f"Requested source objects: {source['requested_object_count']}.",
        f"Verified payload/checksum pairs: {source['successful_object_count']}.",
        f"Failed source objects: {source['failed_object_count']}.",
        "",
        "## Failures",
        "",
    ]
    for failure in source["failures"]:
        lines.append(
            f"- `{failure['market']} {failure['kind']} {failure['period']}`: {failure['error']}"
        )
    lines.extend(
        [
            "",
            "## Performance disposition",
            "",
            "The immutable source contract failed before feature or target construction. "
            "No strategy return, Sharpe, drawdown, benchmark comparison, turnover, "
            "fold/month breadth, bootstrap uncertainty or alpha verdict was computed. "
            "The exactly 5 bps one-way fee remained frozen but was never applied to a "
            "completed target label.",
            "",
            "No date shift, missing-day tolerance, imputation, alternate source, symbol "
            "substitution or same-sample rescue was performed.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    specs = build_specs()
    verified, failed = verify_all(specs, args.workers)
    if failed:
        verdict = "abort_fixed_source_contract_missing_public_objects"
    else:
        verdict = "source_contract_passed_full_diagnostic_required"

    evidence = {
        "family_id": FAMILY_ID,
        "classification": "training-only exogenous-information eligibility diagnostic",
        "candidate_count": 0,
        "diagnostic_count": 1,
        "parameter_grid_count": 0,
        "fee_one_way": FEE_ONE_WAY,
        "accepted": False,
        "performance_seen": False,
        "OOS_accessed": False,
        "markets_passing": 0,
        "verdict": verdict,
        "source": {
            "base_url": BASE_URL,
            "source_start": START_DAY.isoformat(),
            "source_end": END_DAY.isoformat(),
            "requested_object_count": len(specs),
            "successful_object_count": len(verified),
            "checksum_matches": len(verified),
            "failed_object_count": len(failed),
            "failures": [asdict(item) for item in failed],
        },
        "sample": {
            "score_start": SCORE_START.isoformat(),
            "score_end": SCORE_END.isoformat(),
            "intended_decisions": 242,
            "completed_decisions": 0,
        },
    }
    write_json(output_dir / "source-manifest.json", [asdict(item) for item in verified])
    write_json(output_dir / "evidence.json", evidence)
    (output_dir / "report.md").write_text(render_report(evidence), encoding="utf-8")
    print(
        json.dumps(
            {
                "verdict": verdict,
                "verified_objects": len(verified),
                "failed_objects": len(failed),
            },
            sort_keys=True,
        )
    )
    if not failed:
        raise RuntimeError(
            "fixed source contract unexpectedly passed; execute the full preregistered "
            "diagnostic before making any strategy claim"
        )


if __name__ == "__main__":
    main()
