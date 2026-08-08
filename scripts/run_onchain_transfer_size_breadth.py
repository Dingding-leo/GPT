from __future__ import annotations

import base64
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

FAMILY_ID = "causal-onchain-transfer-size-breadth-opportunity-1h-v1"
COMMUNITY_ROOT = "https://community-api.coinmetrics.io/v4"
HOST = "community-api.coinmetrics.io"
START = "2023-04-01T00:00:00Z"
END = "2025-12-31T23:00:00Z"
EXPECTED_ROWS = 24_144
TRAIN_END = 10_800
TARGETS = {
    "BCH-USDT": {"asset": "bch", "seed": 2026080815},
    "LTC-USDT": {"asset": "ltc", "seed": 2026080816},
}
METRICS = ("TxTfrValMeanNtv", "TxTfrValMedNtv")
OUTPUT = Path("reports/research/onchain-transfer-size-breadth-1h-v1")
SOURCE_REJECT = "reject_causal_onchain_transfer_size_breadth_source_contract_1h_v1"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirect rejected", headers, fp)


class SourceFailure(RuntimeError):
    def __init__(self, message: str, evidence: dict[str, Any] | None = None):
        super().__init__(message)
        self.evidence = evidence or {}


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != HOST or parsed.username or parsed.password:
        raise ValueError(f"untrusted Coin Metrics URL: {url}")
    keys = {
        key.lower()
        for key, _ in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    }
    if "api_key" in keys or "apikey" in keys or "key" in keys or "token" in keys:
        raise ValueError("credential-bearing Coin Metrics URL rejected")


def _get(url: str, *, attempts: int = 3) -> tuple[int, bytes]:
    _safe_url(url)
    opener = urllib.request.build_opener(NoRedirect)
    last: Exception | None = None
    for attempt in range(attempts):
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "Dingding-leo-GPT-research/1.0",
            },
            method="GET",
        )
        try:
            with opener.open(req, timeout=30.0) as response:
                data = response.read(16 * 1024 * 1024 + 1)
                if len(data) > 16 * 1024 * 1024:
                    raise ValueError("Coin Metrics response exceeded 16 MiB")
                return int(response.status), data
        except urllib.error.HTTPError as exc:
            body = exc.read(2 * 1024 * 1024)
            if exc.code in (429, 500, 502, 503, 504) and attempt + 1 < attempts:
                last = RuntimeError(f"HTTP {exc.code}: {body[:500]!r}")
                time.sleep(1.0 + attempt)
                continue
            return int(exc.code), body
        except urllib.error.URLError as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep(1.0 + attempt)
                continue
            raise
    raise RuntimeError(f"Coin Metrics request failed: {last}")


def _parse_json(data: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"{label}: invalid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label}: top-level payload is not an object")
    return value


def _catalog_url(asset: str) -> str:
    query = urllib.parse.urlencode(
        {"assets": asset, "page_size": 10000, "pretty": "false"}
    )
    return f"{COMMUNITY_ROOT}/catalog-all/assets?{query}"


def _timeseries_url(asset: str, end: str) -> str:
    query = urllib.parse.urlencode(
        {
            "assets": asset,
            "metrics": ",".join(METRICS),
            "frequency": "1h",
            "start_time": START,
            "end_time": end,
            "end_inclusive": "true",
            "page_size": 10000,
            "paging_from": "start",
            "sort": "time",
            "pretty": "false",
        }
    )
    return f"{COMMUNITY_ROOT}/timeseries/asset-metrics?{query}"


def _metric_frequency_available(
    asset_payload: dict[str, Any], metric: str
) -> dict[str, Any] | None:
    metrics = asset_payload.get("metrics")
    if not isinstance(metrics, list):
        return None
    for item in metrics:
        if not isinstance(item, dict) or item.get("metric") != metric:
            continue
        freqs = item.get("frequencies")
        if not isinstance(freqs, list):
            return None
        for freq in freqs:
            if isinstance(freq, dict) and freq.get("frequency") == "1h":
                return freq
    return None


def _catalog_contract(asset: str) -> dict[str, Any]:
    url = _catalog_url(asset)
    status, raw = _get(url)
    evidence = {
        "url": url,
        "status": status,
        "raw_sha256": _sha256(raw),
        "raw_base64": base64.b64encode(raw).decode(),
    }
    if status != 200:
        raise SourceFailure(
            f"{asset}: Community catalog HTTP {status}: "
            f"{raw[:1000].decode(errors='replace')}",
            evidence,
        )
    payload = _parse_json(raw, label=f"{asset} catalog")
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise SourceFailure(f"{asset}: malformed catalog response", evidence)
    matches = [
        row for row in rows if isinstance(row, dict) and row.get("asset") == asset
    ]
    if len(matches) != 1:
        raise SourceFailure(
            f"{asset}: expected exactly one catalog asset row, got {len(matches)}",
            evidence,
        )
    asset_payload = matches[0]
    found: dict[str, Any] = {}
    for metric in METRICS:
        freq = _metric_frequency_available(asset_payload, metric)
        if freq is None:
            raise SourceFailure(
                f"{asset}: catalog does not expose {metric} at 1h to Community",
                evidence,
            )
        found[metric] = freq
    evidence["metric_frequency_contract"] = found
    return evidence


def _fetch_timeseries(asset: str, end: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    url = _timeseries_url(asset, end)
    request_urls: list[str] = []
    pages: list[dict[str, Any]] = []
    normalized_rows: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    while url:
        _safe_url(url)
        if url in seen_urls:
            raise ValueError(f"{asset}: repeated next_page_url")
        seen_urls.add(url)
        request_urls.append(url)
        status, raw = _get(url)
        page_evidence = {
            "url": url,
            "status": status,
            "raw_sha256": _sha256(raw),
            "raw_base64": base64.b64encode(raw).decode(),
        }
        if status != 200:
            raise SourceFailure(
                f"{asset}: Community timeseries HTTP {status}: "
                f"{raw[:1000].decode(errors='replace')}",
                {
                    "request_urls": request_urls,
                    "failed_page": page_evidence,
                    "pages": pages,
                },
            )
        payload = _parse_json(raw, label=f"{asset} timeseries page {len(pages)+1}")
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise ValueError(f"{asset}: timeseries page missing data list")
        pages.append(page_evidence)
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError(f"{asset}: non-object timeseries row")
            if row.get("asset") != asset:
                raise ValueError(f"{asset}: asset identity mismatch")
            missing = [metric for metric in METRICS if metric not in row]
            if missing:
                raise ValueError(f"{asset}: missing requested metrics {missing}")
            values: dict[str, float] = {}
            for metric in METRICS:
                raw_value = row.get(metric)
                if raw_value is None:
                    raise ValueError(f"{asset}: null {metric} at {row.get('time')}")
                try:
                    value = float(raw_value)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"{asset}: non-numeric {metric}") from exc
                if not np.isfinite(value) or value < 0:
                    raise ValueError(f"{asset}: invalid {metric}={raw_value!r}")
                values[metric] = value
            normalized_rows.append(
                {
                    "asset": asset,
                    "time": row.get("time"),
                    METRICS[0]: values[METRICS[0]],
                    METRICS[1]: values[METRICS[1]],
                }
            )
        next_url = payload.get("next_page_url")
        if next_url is None:
            url = ""
        elif isinstance(next_url, str) and next_url:
            _safe_url(next_url)
            url = next_url
        else:
            raise ValueError(f"{asset}: invalid next_page_url")
        if len(pages) > 64:
            raise ValueError(f"{asset}: page budget exceeded")

    frame = pd.DataFrame(normalized_rows)
    if frame.empty:
        raise ValueError(f"{asset}: no timeseries rows")
    if frame["time"].duplicated().any():
        raise ValueError(f"{asset}: duplicate timestamps")
    parsed_time = pd.to_datetime(frame["time"], utc=True, errors="raise")
    frame = (
        frame.assign(timestamp=parsed_time)
        .drop(columns=["time"])
        .set_index("timestamp")
        .sort_index()
    )
    if not frame.index.is_monotonic_increasing or frame.index.has_duplicates:
        raise ValueError(f"{asset}: timestamp order invalid")
    expected = pd.date_range(START, end, freq="h")
    if len(frame) != len(expected) or not frame.index.equals(expected):
        missing = expected.difference(frame.index)
        extra = frame.index.difference(expected)
        raise ValueError(
            f"{asset}: exact hourly grid mismatch rows={len(frame)} "
            f"expected={len(expected)} missing={len(missing)} extra={len(extra)}"
        )
    data = frame.reset_index().to_csv(
        index=False,
        date_format="%Y-%m-%dT%H:%M:%S.%fZ",
        float_format="%.17g",
        lineterminator="\n",
    ).encode()
    return frame, {
        "request_urls": request_urls,
        "page_count": len(pages),
        "pages": pages,
        "rows": len(frame),
        "normalized_csv_sha256": _sha256(data),
        "normalized_csv_base64": base64.b64encode(data).decode(),
    }


def _write_chain_source(
    asset: str, catalog: dict[str, Any], acquisition: dict[str, Any]
) -> None:
    root = OUTPUT / "source" / asset
    root.mkdir(parents=True, exist_ok=True)
    (root / "catalog.json").write_bytes(_json_bytes(catalog))
    (root / "acquisition.json").write_bytes(_json_bytes(acquisition))
    csv_bytes = base64.b64decode(acquisition["full"]["normalized_csv_base64"])
    (root / f"coinmetrics-{asset}-transfer-size-1h.csv").write_bytes(csv_bytes)


def _source_arm(asset: str) -> dict[str, Any]:
    catalog = _catalog_contract(asset)
    full, full_ev = _fetch_timeseries(asset, END)
    repeat, repeat_ev = _fetch_timeseries(asset, END)
    prefix_end = (
        pd.Timestamp(START) + pd.Timedelta(hours=TRAIN_END - 1)
    ).isoformat().replace("+00:00", "Z")
    prefix, prefix_ev = _fetch_timeseries(asset, prefix_end)

    if not full.equals(repeat):
        raise ValueError(f"{asset}: repeated normalized acquisition differs")
    if full_ev["normalized_csv_sha256"] != repeat_ev["normalized_csv_sha256"]:
        raise ValueError(f"{asset}: repeated normalized hash differs")
    full_prefix = full.iloc[:TRAIN_END]
    if not full_prefix.equals(prefix):
        raise ValueError(f"{asset}: future-suffix prefix invariance failed")

    acquisition = {"full": full_ev, "repeat": repeat_ev, "prefix": prefix_ev}
    _write_chain_source(asset, catalog, acquisition)
    return {
        "asset": asset,
        "rows": len(full),
        "catalog_raw_sha256": catalog["raw_sha256"],
        "normalized_csv_sha256": full_ev["normalized_csv_sha256"],
        "repeat_normalized_csv_sha256": repeat_ev["normalized_csv_sha256"],
        "prefix_normalized_csv_sha256": prefix_ev["normalized_csv_sha256"],
        "catalog_contract_pass": True,
        "exact_hourly_grid_pass": len(full) == EXPECTED_ROWS,
        "repeat_identity_pass": True,
        "future_suffix_prefix_invariance_pass": True,
        "finite_nonnegative_metrics_pass": True,
    }


def _render(result: dict[str, Any]) -> str:
    lines = [
        "# On-chain transfer-size breadth — source-contract diagnostic",
        "",
        f"- Family: `{FAMILY_ID}`",
        f"- Exact head: `{result['code_head']}`",
        "- Candidate/grid: `0/0`",
        "- OOS: sealed and unused",
        "- Target-return statistics: not accessed in this source-contract stage",
        f"- Verdict: `{result['verdict']}`",
        "",
    ]
    if result["source_contract_pass"]:
        lines += [
            "Both fixed Coin Metrics Community source arms passed catalog, exact 1H calendar, repeated acquisition, finite/non-negative value, and future-suffix prefix-invariance gates.",
            "",
        ]
        for target, spec in TARGETS.items():
            item = result["chain_sources"][spec["asset"]]
            lines.append(
                f"- {target} / {spec['asset']}: {item['rows']} rows, "
                f"`{item['normalized_csv_sha256']}`"
            )
    else:
        lines += [
            "The frozen credential-free Coin Metrics source contract failed before any OKX target return was downloaded or inspected.",
            "",
            f"- Failure: `{result['failure']}`",
        ]
    lines += [
        "",
        "## Executable-performance accounting",
        "",
        "Train/OOS/full return and Sharpe, benchmark comparison, turnover, drawdown, edge per turnover, fold/year breadth and uncertainty are null rather than zero in a source-contract rejection.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    chain_sources: dict[str, Any] = {}
    failure: str | None = None
    failure_evidence: dict[str, Any] | None = None
    for target, spec in TARGETS.items():
        asset = spec["asset"]
        try:
            chain_sources[asset] = _source_arm(asset)
        except Exception as exc:
            failure = f"{target}/{asset}: {type(exc).__name__}: {exc}"
            if isinstance(exc, SourceFailure):
                failure_evidence = exc.evidence
            break

    passed = failure is None and len(chain_sources) == len(TARGETS)
    result: dict[str, Any] = {
        "family_id": FAMILY_ID,
        "code_head": os.environ.get("GITHUB_SHA", "local"),
        "base_main": "5a0fcc97d1a882f8223656c51f5bb8055f534e38",
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "bar": "1H",
        "chain_provider": "Coin Metrics Community API",
        "chain_root": COMMUNITY_ROOT,
        "metrics": list(METRICS),
        "source_start": START,
        "source_end": END,
        "expected_rows_per_chain_arm": EXPECTED_ROWS,
        "fixed_targets": list(TARGETS),
        "chain_sources": chain_sources,
        "source_contract_pass": passed,
        "failure": failure,
        "failure_evidence": failure_evidence,
        "oos_accessed": False,
        "target_return_statistics_accessed": False,
        "strategy_metrics": {
            "train": None,
            "oos": None,
            "full": None,
            "benchmark_comparison": None,
            "turnover": None,
            "max_drawdown": None,
            "edge_per_turnover": None,
            "fold_year_breadth": None,
            "uncertainty": None,
        },
        "verdict": (
            "source_contract_pass_requires_training_diagnostic"
            if passed
            else SOURCE_REJECT
        ),
    }
    evidence = _json_bytes(result)
    report = _render(result)
    (OUTPUT / "evidence.json").write_bytes(evidence)
    (OUTPUT / "report.md").write_text(report, encoding="utf-8")
    manifest = {
        "evidence_sha256": _sha256(evidence),
        "report_sha256": _sha256(report.encode()),
        "code_head": result["code_head"],
        "verdict": result["verdict"],
    }
    (OUTPUT / "manifest.json").write_bytes(_json_bytes(manifest))
    print(report)


if __name__ == "__main__":
    main()
