#!/usr/bin/env python3
"""Audit the frozen public OKX PAXG-USDT completed-1H source contract."""
from __future__ import annotations

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
from statistics import quantiles
from typing import Any

from gpt_quant.okx import write_okx_snapshot
from gpt_quant.okx_1h import fetch_okx_one_hour_candles

FAMILY_ID = "causal-public-paxg-macro-risk-source-contract-1h-v1"
ISSUE_NUMBER = 1133
BASE_MAIN = "5a0fcc97d1a882f8223656c51f5bb8055f534e38"
ORIGIN = "https://www.okx.com"
INSTRUMENT_PATH = "/api/v5/public/instruments"
HISTORY_PATH = "/api/v5/market/history-candles"
INSTRUMENT = "PAXG-USDT"
BAR = "1H"
START = datetime(2025, 11, 1, 0, 0, tzinfo=UTC)
END = datetime(2026, 8, 7, 23, 0, tzinfo=UTC)
EXTENSION_END = datetime(2026, 8, 8, 0, 0, tzinfo=UTC)
EXPECTED_ROWS = 6_720
LIMIT = 100
PAUSE_SECONDS = 0.13
MAX_TOTAL_EVIDENCE_BYTES = 100 * 1024 * 1024
OUT = Path("reports/experiments") / FAMILY_ID
SOURCE = OUT / "source"
REQUESTS = SOURCE / "requests"
SNAPSHOTS = SOURCE / "snapshots"
ACCEPT = "accept_public_paxg_macro_risk_1h_source_for_separate_training_predeclaration"
REJECT = "reject_causal_public_paxg_macro_risk_source_contract_1h_v1"

OFFICIAL_SEMANTIC_SNAPSHOT = {
    "snapshot_date_utc": "2026-08-08",
    "provider": "OKX",
    "public_instruments_docs": (
        "https://www.okx.com/docs-v5/en/#public-data-rest-api-get-instruments"
    ),
    "history_candles_docs": (
        "https://www.okx.com/docs-v5/en/"
        "#order-book-trading-market-data-get-candlesticks-history"
    ),
    "listing_announcement": (
        "https://www.okx.com/en-us/help/okx-to-list-paxg-pax-gold-for-spot-trading"
    ),
    "announcement_spot_open_utc": "2025-10-15T07:00:00Z",
    "instrument_endpoint": f"{ORIGIN}{INSTRUMENT_PATH}",
    "history_endpoint": f"{ORIGIN}{HISTORY_PATH}",
    "history_semantics": (
        "recent-years public history; newest-to-oldest pagination; confirm=1 completed"
    ),
    "requested_bar": BAR,
    "history_limit": LIMIT,
}

PERFORMANCE_NULLS = {
    "training_return": None,
    "training_sharpe": None,
    "oos_return": None,
    "oos_sharpe": None,
    "full_return": None,
    "full_sharpe": None,
    "benchmark_comparison": None,
    "turnover": None,
    "modeled_fee_drag": None,
    "maximum_drawdown": None,
    "edge_per_turnover": None,
    "fold_year_breadth": None,
    "dependence_uncertainty": None,
    "calibration": None,
    "execution_delay_performance": None,
}


class SourceFailure(RuntimeError):
    """A frozen source-contract gate failed non-transiently."""


class TransientSourceError(RuntimeError):
    """Transport or provider availability failed after bounded retries."""


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iso_hour(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:00:00Z")


def timestamp_ms(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def safe_public_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "www.okx.com":
        raise SourceFailure(f"untrusted OKX origin: {url}")
    if parsed.path not in {INSTRUMENT_PATH, HISTORY_PATH}:
        raise SourceFailure(f"prohibited OKX path: {parsed.path}")
    pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    names = [name for name, _ in pairs]
    forbidden = {"api_key", "apikey", "secret", "passphrase", "authorization", "token"}
    if any(name.lower() in forbidden for name in names):
        raise SourceFailure("credential-bearing query parameter appeared")
    if len(names) != len(set(names)):
        raise SourceFailure(f"duplicate OKX query fields: {names}")
    values = dict(pairs)
    if parsed.path == INSTRUMENT_PATH:
        if set(names) != {"instType", "instId"}:
            raise SourceFailure(f"unexpected public-instrument query fields: {names}")
        if values.get("instType") != "SPOT" or values.get("instId") != INSTRUMENT:
            raise SourceFailure("instrument request escaped the frozen PAXG-USDT SPOT object")
    else:
        if not set(names).issubset({"instId", "bar", "limit", "after"}):
            raise SourceFailure(f"unexpected history-candle query fields: {names}")
        if values.get("instId") != INSTRUMENT or values.get("bar") != BAR:
            raise SourceFailure("history request escaped the frozen PAXG-USDT 1H object")
        if values.get("limit") != str(LIMIT):
            raise SourceFailure("history request changed the frozen page size")
        if "after" in values and not values["after"].isascii():
            raise SourceFailure("history pagination cursor is not ASCII")
        if "after" in values and not values["after"].isdecimal():
            raise SourceFailure("history pagination cursor is not millisecond digits")
    return url


class CaptureSession:
    def __init__(self, label: str) -> None:
        self.label = label
        self.folder = REQUESTS / label
        self.folder.mkdir(parents=True, exist_ok=True)
        self.attempts: list[dict[str, Any]] = []
        self.success_urls: list[str] = []
        self.counter = 0

    def _persist(
        self,
        *,
        url: str,
        status: int,
        headers: dict[str, str],
        raw: bytes,
        attempt_number: int,
    ) -> None:
        self.counter += 1
        stem = f"request-{self.counter:04d}-attempt-{attempt_number}"
        body = self.folder / f"{stem}.body"
        body.write_bytes(raw)
        record = {
            "sequence": self.counter,
            "attempt_number": attempt_number,
            "url": url,
            "status": status,
            "received_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "headers": headers,
            "response_file": str(body.relative_to(OUT)),
            "response_bytes": len(raw),
            "response_sha256": sha256_bytes(raw),
        }
        meta = self.folder / f"{stem}.meta.json"
        meta.write_bytes(canonical_bytes(record))
        self.attempts.append(record)

    def get_bytes(self, url: str, timeout: float) -> bytes:
        safe_public_url(url)
        retryable = {408, 429, 500, 502, 503, 504}
        last_error: Exception | None = None
        for attempt in range(1, 4):
            request = urllib.request.Request(
                url,
                method="GET",
                headers={
                    "Accept": "application/json",
                    "User-Agent": "gpt-quant-source-audit/1.0",
                },
            )
            status = 0
            headers: dict[str, str] = {}
            raw = b""
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    status = int(response.status)
                    headers = {
                        key.lower(): value
                        for key, value in response.headers.items()
                        if key.lower()
                        in {
                            "content-type",
                            "date",
                            "server",
                            "cf-ray",
                            "x-ratelimit-limit",
                            "x-ratelimit-remaining",
                        }
                    }
                    raw = response.read(2 * 1024 * 1024 + 1)
            except urllib.error.HTTPError as exc:
                status = int(exc.code)
                headers = {
                    key.lower(): value
                    for key, value in exc.headers.items()
                    if key.lower() in {"content-type", "date", "server", "cf-ray"}
                }
                raw = exc.read(2 * 1024 * 1024 + 1)
                last_error = exc
            except (urllib.error.URLError, TimeoutError) as exc:
                raw = f"{type(exc).__name__}: {exc}".encode("utf-8", errors="replace")
                last_error = exc

            self._persist(
                url=url,
                status=status,
                headers=headers,
                raw=raw,
                attempt_number=attempt,
            )
            if len(raw) > 2 * 1024 * 1024:
                raise SourceFailure(f"oversized OKX response for {self.label}")
            if status == 200:
                self.success_urls.append(url)
                return raw
            if status in retryable or status == 0:
                if attempt < 3:
                    time.sleep(0.75 * (2 ** (attempt - 1)))
                    continue
                raise TransientSourceError(
                    f"transient OKX failure after retries for {self.label}: status={status}"
                ) from last_error
            raise SourceFailure(
                f"non-success OKX response for {self.label}: status={status} "
                f"sha256={sha256_bytes(raw)}"
            )
        raise TransientSourceError(f"unreachable retry exhaustion for {self.label}")

    def persist_manifest(self) -> dict[str, Any]:
        manifest = {
            "label": self.label,
            "attempt_count": len(self.attempts),
            "successful_logical_request_count": len(self.success_urls),
            "successful_request_urls": self.success_urls,
            "logical_request_urls_unique": len(self.success_urls) == len(set(self.success_urls)),
            "attempts": self.attempts,
        }
        path = self.folder / "request-manifest.json"
        path.write_bytes(canonical_bytes(manifest))
        manifest["manifest_file"] = str(path.relative_to(OUT))
        manifest["manifest_sha256"] = sha256_file(path)
        return manifest


def parse_json_object(raw: bytes, *, purpose: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceFailure(f"invalid JSON for {purpose}") from exc
    if not isinstance(payload, dict):
        raise SourceFailure(f"non-object OKX envelope for {purpose}")
    if str(payload.get("code")) != "0" or not isinstance(payload.get("data"), list):
        raise SourceFailure(
            f"OKX provider envelope rejected for {purpose}: "
            f"code={payload.get('code')!r} msg={payload.get('msg')!r}"
        )
    return payload


def audit_instrument() -> dict[str, Any]:
    session = CaptureSession("instrument")
    url = safe_public_url(
        f"{ORIGIN}{INSTRUMENT_PATH}?"
        + urllib.parse.urlencode([("instType", "SPOT"), ("instId", INSTRUMENT)])
    )
    try:
        raw = session.get_bytes(url, 30.0)
        payload = parse_json_object(raw, purpose="public instrument identity")
        rows = payload["data"]
        if len(rows) != 1 or not isinstance(rows[0], dict):
            raise SourceFailure(f"expected exactly one instrument row, observed {len(rows)}")
        row = rows[0]
        required = {
            "instType": "SPOT",
            "instId": INSTRUMENT,
            "baseCcy": "PAXG",
            "quoteCcy": "USDT",
            "state": "live",
        }
        mismatches = {
            key: {"expected": value, "observed": row.get(key)}
            for key, value in required.items()
            if row.get(key) != value
        }
        if mismatches:
            raise SourceFailure(f"instrument identity/state mismatch: {mismatches}")
        try:
            list_time_ms = int(str(row.get("listTime")))
        except (TypeError, ValueError, OverflowError) as exc:
            raise SourceFailure("instrument listTime is absent or invalid") from exc
        if list_time_ms > timestamp_ms(START):
            raise SourceFailure(
                f"instrument listTime {list_time_ms} occurs after frozen source start"
            )
        list_time = datetime.fromtimestamp(list_time_ms / 1000, UTC)
        return {
            "passed": True,
            "instType": row["instType"],
            "instId": row["instId"],
            "baseCcy": row["baseCcy"],
            "quoteCcy": row["quoteCcy"],
            "state": row["state"],
            "listTime_ms": list_time_ms,
            "listTime_utc": list_time.isoformat().replace("+00:00", "Z"),
            "listTime_precedes_frozen_start": True,
            "request": session.attempts[-1],
        }
    finally:
        session.persist_manifest()


def canonical_panel_bytes(frame: Any) -> bytes:
    rows: list[list[str]] = []
    for timestamp, row in frame.iterrows():
        rows.append(
            [
                str(int(timestamp.timestamp() * 1000)),
                format(float(row["open"]), ".17g"),
                format(float(row["high"]), ".17g"),
                format(float(row["low"]), ".17g"),
                format(float(row["close"]), ".17g"),
                format(float(row["volume_base"]), ".17g"),
                format(float(row["volume_quote"]), ".17g"),
                format(float(row["volume_quote_alt"]), ".17g"),
                str(row["confirm"]),
            ]
        )
    return canonical_bytes(rows)


def iqr(values: list[float]) -> float:
    if len(values) < 4:
        return 0.0
    q = quantiles(values, n=4, method="inclusive")
    return float(q[2] - q[0])


def acquire(label: str, start: datetime, end: datetime) -> tuple[Any, dict[str, Any]]:
    session = CaptureSession(label)
    try:
        snapshot = fetch_okx_one_hour_candles(
            inst_id=INSTRUMENT,
            start=iso_hour(start),
            end=iso_hour(end),
            base_url=ORIGIN,
            limit=LIMIT,
            pause_seconds=PAUSE_SECONDS,
            timeout=30.0,
            safety_pages=4,
            get_bytes=session.get_bytes,
        )
    finally:
        request_manifest = session.persist_manifest()

    output_dir = SNAPSHOTS / label
    paths = write_okx_snapshot(snapshot, output_dir)
    values = [float(value) for value in snapshot.candles["close"].tolist()]
    close_iqr = iqr(values)
    distinct_close = len(set(values))
    panel_bytes = canonical_panel_bytes(snapshot.candles)
    metadata = snapshot.metadata
    summary = {
        "label": label,
        "requested_start": iso_hour(start),
        "requested_end": iso_hour(end),
        "observed_rows": len(snapshot.candles),
        "first_timestamp": snapshot.candles.index[0].isoformat().replace("+00:00", "Z"),
        "last_timestamp": snapshot.candles.index[-1].isoformat().replace("+00:00", "Z"),
        "distinct_close_values": distinct_close,
        "close_iqr": close_iqr,
        "normalized_panel_sha256": sha256_bytes(panel_bytes),
        "raw_pages_sha256": metadata.get("raw_pages_sha256"),
        "source_response_count": metadata.get("source_response_count"),
        "source_response_total_bytes": metadata.get("source_response_total_bytes"),
        "source_response_sha256": metadata.get("source_response_sha256"),
        "pagination_termination": metadata.get("pagination_termination"),
        "pagination_complete": metadata.get("pagination_complete"),
        "requested_start_reached": metadata.get("requested_start_reached"),
        "missing_intervals": metadata.get("missing_intervals"),
        "duplicates_removed": metadata.get("duplicates_removed"),
        "incomplete_rows_removed": metadata.get("incomplete_rows_removed"),
        "request_manifest": request_manifest,
        "snapshot_files": {
            key: {
                "path": str(path.relative_to(OUT)),
                "sha256": sha256_file(path),
            }
            for key, path in paths.items()
        },
    }
    return snapshot, summary


def validate_panel(
    snapshot: Any, *, expected_rows: int, start: datetime, end: datetime
) -> dict[str, bool]:
    frame = snapshot.candles
    values = [float(value) for value in frame["close"].tolist()]
    close_iqr = iqr(values)
    return {
        "exact_row_count": len(frame) == expected_rows,
        "exact_start_boundary": frame.index[0].to_pydatetime() == start,
        "exact_end_boundary": frame.index[-1].to_pydatetime() == end,
        "hourly_contiguous_unique": (
            frame.index.is_unique
            and frame.index.is_monotonic_increasing
            and snapshot.metadata.get("missing_intervals") in (0, None)
        ),
        "finite_positive_ohlc": all(
            math.isfinite(float(value)) and float(value) > 0
            for column in ("open", "high", "low", "close")
            for value in frame[column].tolist()
        ),
        "finite_nonnegative_volume": all(
            math.isfinite(float(value)) and float(value) >= 0
            for column in ("volume_base", "volume_quote", "volume_quote_alt")
            for value in frame[column].tolist()
        ),
        "close_support": len(set(values)) >= 500 and close_iqr > 0,
        "pagination_complete": (
            snapshot.metadata.get("pagination_complete") is True
            and snapshot.metadata.get("requested_start_reached") is True
        ),
        "completed_only": set(frame["confirm"].astype(str).tolist()) == {"1"},
    }


def repeat_gates_pass(snapshot: Any) -> bool:
    gates = validate_panel(
        snapshot,
        expected_rows=EXPECTED_ROWS,
        start=START,
        end=END,
    )
    return all(gates.values())


def evidence_bytes_on_disk() -> int:
    return sum(path.stat().st_size for path in OUT.rglob("*") if path.is_file())


def write_terminal(evidence: dict[str, Any]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    evidence_path = OUT / "evidence.json"
    evidence_path.write_bytes(canonical_bytes(evidence))
    (OUT / "evidence.sha256").write_text(sha256_file(evidence_path) + "\n", encoding="utf-8")

    lines = [
        f"# {FAMILY_ID}",
        "",
        f"- verdict: `{evidence['verdict']}`",
        f"- exact head: `{evidence['exact_head']}`",
        "- candidate / grid: `0 / 0`",
        f"- source contract passed: `{str(evidence['source_contract_passed']).lower()}`",
        f"- observed rows: `{evidence.get('observed_rows')}`",
        "- target price/return accessed: `false`",
        "- OOS accessed: `false`",
        "- performance fields: `null`",
    ]
    if evidence.get("source_contract_passed"):
        lines.extend(
            [
                "",
                "## Source result",
                "",
                f"PAXG-USDT produced exactly {EXPECTED_ROWS:,} completed provider-native 1H rows "
                f"from {iso_hour(START)} through {iso_hour(END)}.",
                f"Distinct closes: `{evidence['support']['distinct_close_values']}`; "
                f"close IQR: `{evidence['support']['close_iqr']}`.",
                (
                    "Independent repeat normalization and the one-hour suffix-prefix replay "
                    "were exact."
                ),
            ]
        )
    if evidence.get("failure"):
        lines.extend(["", "## Terminal source failure", "", str(evidence["failure"])])
    report = OUT / "report.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (OUT / "report.sha256").write_text(sha256_file(report) + "\n", encoding="utf-8")

    manifest = {
        str(path.relative_to(OUT)): sha256_file(path)
        for path in sorted(OUT.rglob("*"))
        if path.is_file() and path.name not in {"artifact-manifest.json", "manifest.sha256"}
    }
    manifest_path = OUT / "artifact-manifest.json"
    manifest_path.write_bytes(canonical_bytes(manifest))
    (OUT / "manifest.sha256").write_text(sha256_file(manifest_path) + "\n", encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    SOURCE.mkdir(parents=True, exist_ok=True)
    REQUESTS.mkdir(parents=True, exist_ok=True)
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    exact_head = os.environ.get("GITHUB_SHA", "local-unbound")
    instrument: dict[str, Any] | None = None
    primary_summary: dict[str, Any] | None = None
    repeat_summary: dict[str, Any] | None = None
    extension_summary: dict[str, Any] | None = None
    failure: dict[str, Any] | None = None
    gate_vector: dict[str, bool] = {}

    try:
        instrument = audit_instrument()
        primary, primary_summary = acquire("primary", START, END)
        repeat, repeat_summary = acquire("repeat", START, END)
        extension, extension_summary = acquire("extension", START, EXTENSION_END)

        primary_gates = validate_panel(
            primary,
            expected_rows=EXPECTED_ROWS,
            start=START,
            end=END,
        )
        extension_gates = validate_panel(
            extension,
            expected_rows=EXPECTED_ROWS + 1,
            start=START,
            end=EXTENSION_END,
        )
        repeat_identical = primary.candles.equals(repeat.candles)
        extension_prefix = extension.candles.iloc[:EXPECTED_ROWS]
        prefix_identical = primary.candles.equals(extension_prefix)
        request_order_repeat = (
            primary_summary["request_manifest"]["successful_request_urls"]
            == repeat_summary["request_manifest"]["successful_request_urls"]
        )
        request_sequences_unique = all(
            summary["request_manifest"]["logical_request_urls_unique"]
            for summary in (primary_summary, repeat_summary, extension_summary)
        )

        gate_vector = {
            "anonymous_public_https": True,
            "instrument_identity_spot_live_and_prelisted": bool(instrument["passed"]),
            "provider_native_completed_1h": all(primary_gates.values()),
            "exact_6720_hour_calendar": primary_gates["exact_row_count"],
            "strict_hourly_timestamp_integrity": primary_gates["hourly_contiguous_unique"],
            "ohlcv_valid": (
                primary_gates["finite_positive_ohlc"]
                and primary_gates["finite_nonnegative_volume"]
            ),
            "nonconstant_close_support": primary_gates["close_support"],
            "deterministic_pagination": (
                primary_gates["pagination_complete"]
                and repeat_gates_pass(repeat)
                and request_sequences_unique
            ),
            "repeat_normalized_rows_identical": repeat_identical,
            "one_hour_suffix_prefix_identical": prefix_identical and all(extension_gates.values()),
            "sha256_request_raw_normalized_report_bound": True,
            "no_interpolation_resampling_or_stitching": True,
            "no_target_or_performance_access": True,
        }
        primary_summary["repeat_request_order_identical_diagnostic"] = request_order_repeat
        if not all(gate_vector.values()):
            failed = [name for name, passed in gate_vector.items() if not passed]
            raise SourceFailure(f"frozen source gates failed: {failed}")
    except SourceFailure as exc:
        failure = {
            "stage": "source_contract",
            "message": str(exc),
            "observed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }

    passed = failure is None and bool(gate_vector) and all(gate_vector.values())
    support = {
        "distinct_close_values": (
            primary_summary["distinct_close_values"] if primary_summary is not None else None
        ),
        "close_iqr": primary_summary["close_iqr"] if primary_summary is not None else None,
    }
    evidence = {
        "family_id": FAMILY_ID,
        "issue_number": ISSUE_NUMBER,
        "base_main": BASE_MAIN,
        "exact_head": exact_head,
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "exogenous_source": INSTRUMENT,
        "future_target_sleeves": ["BTC-USDT", "ETH-USDT"],
        "provider": "OKX public REST",
        "bar": BAR,
        "frozen_start": iso_hour(START),
        "frozen_end": iso_hour(END),
        "expected_rows": EXPECTED_ROWS,
        "observed_rows": primary_summary["observed_rows"] if primary_summary else None,
        "canonical_fee_bps_one_way": 5.0,
        "official_semantic_snapshot": OFFICIAL_SEMANTIC_SNAPSHOT,
        "instrument": instrument,
        "primary": primary_summary,
        "repeat": repeat_summary,
        "extension": extension_summary,
        "support": support,
        "source_gates": gate_vector,
        "source_contract_passed": passed,
        "public_data_only": True,
        "credentials_private_endpoints_accounts_orders_adapters_leverage_funds": False,
        "cross_sectional_or_relative_selection": False,
        "target_prices_or_returns_accessed": False,
        "performance_accessed": False,
        "oos_accessed": False,
        "canonical_strategy_changed": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "performance": PERFORMANCE_NULLS,
        "failure": failure,
        "verdict": ACCEPT if passed else REJECT,
    }
    evidence["source_evidence_bytes_before_terminal_files"] = evidence_bytes_on_disk()
    write_terminal(evidence)
    total = evidence_bytes_on_disk()
    if total >= MAX_TOTAL_EVIDENCE_BYTES:
        raise RuntimeError(f"source evidence exceeds 100 MiB: {total}")
    print(
        json.dumps(
            {
                "exact_head": exact_head,
                "source_contract_passed": passed,
                "observed_rows": evidence["observed_rows"],
                "performance_accessed": False,
                "oos_accessed": False,
                "verdict": evidence["verdict"],
                "evidence_sha256": sha256_file(OUT / "evidence.json"),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
