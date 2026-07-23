from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from gpt_quant import build_okx_completed_bar_cutoff, fetch_okx_history_candles
from gpt_quant.execution_quote import ExecutionQuoteSnapshot
from gpt_quant.execution_quote_binding import ExecutionQuoteBinding, bind_execution_quote
from gpt_quant.execution_quote_evidence import (
    load_execution_quote_evidence_store,
    record_execution_quote_evidence,
)
from gpt_quant.okx_live_response_evidence import (
    read_okx_live_timing_response_evidence,
    sample_okx_server_time_with_response,
    write_okx_live_timing_response_evidence,
)
from gpt_quant.signal_intent import build_target_position_intent

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_FIXTURE_DIR = (
    _REPOSITORY_ROOT / "tests" / "fixtures" / "okx" / "btc-usdt-1dutc-raw-20260717-20260721"
)
_ROWS_PATH = _FIXTURE_DIR / "rows.json"
_METADATA_PATH = _FIXTURE_DIR / "metadata.json"
_EXPECTED_FIXTURE_SHA256 = "dcb30e58e10f8415aefe8c206f99c21fc8862b3b4f5ea65679a01262980c5481"
_SERVER_TIME_PAYLOAD = {
    "code": "0",
    "msg": "",
    "data": [{"ts": "1784635200100"}],
}
_STRATEGY_REVISION = "a2b3e61a0591121346a6d29f1ddd3ad805aba68d"
_CONFIG_SHA256 = "a0340ca26a0c5e7d0d609ddf69bcb3e4e643a93ab009f27ee03e8ea322aed822"
_STRUCTURAL_QUOTE_SOURCE_BYTES = b"offline-structural-top-of-book-example-v1\n"
_STRUCTURAL_INSTRUMENT_SOURCE_BYTES = b"offline-structural-instrument-example-v1\n"
_QUOTE_DECISION_AT_UTC = datetime(2026, 7, 21, 12, 0, 0, 400_000, tzinfo=UTC)
_QUOTE_MAXIMUM_AGE_MS = 200


def _clock(*values: str):
    timestamps: Iterator[pd.Timestamp] = iter(pd.Timestamp(value) for value in values)
    return lambda: next(timestamps)


def _load_real_okx_rows() -> list[list[str]]:
    rows_bytes = _ROWS_PATH.read_bytes()
    metadata = json.loads(_METADATA_PATH.read_text(encoding="utf-8"))
    digest = hashlib.sha256(rows_bytes).hexdigest()
    if digest != _EXPECTED_FIXTURE_SHA256:
        raise ValueError("immutable OKX fixture hash mismatch")
    if metadata.get("fixture_rows_sha256") != digest:
        raise ValueError("OKX fixture metadata hash mismatch")
    if (
        metadata.get("provider") != "OKX"
        or metadata.get("instrument_id") != "BTC-USDT"
        or metadata.get("bar") != "1Dutc"
    ):
        raise ValueError("OKX fixture metadata does not match the documented example")
    rows = json.loads(rows_bytes)
    if not isinstance(rows, list):
        raise ValueError("OKX fixture rows must be a JSON array")
    return rows


def _build_snapshot():
    rows = _load_real_okx_rows()

    def fixture_getter(url: str, timeout: float) -> dict[str, object]:
        if "instId=BTC-USDT" not in url or "bar=1Dutc" not in url or timeout != 20.0:
            raise ValueError("unexpected OKX candle request in documented example")
        return {"code": "0", "msg": "", "data": [list(row) for row in rows]}

    return fetch_okx_history_candles(
        inst_id="BTC-USDT",
        bar="1Dutc",
        base_url="https://www.okx.com",
        limit=100,
        max_pages=1,
        pause_seconds=0.0,
        as_of="2026-07-21T11:59:59+00:00",
        get_json=fixture_getter,
    )


def _build_server_time_observation():
    def fixture_getter(url: str, timeout: float) -> dict[str, object]:
        if url != "https://www.okx.com/api/v5/public/time" or timeout != 20.0:
            raise ValueError("unexpected OKX public-time request in documented example")
        return json.loads(json.dumps(_SERVER_TIME_PAYLOAD))

    return sample_okx_server_time_with_response(
        base_url="https://www.okx.com",
        get_json=fixture_getter,
        now=_clock(
            "2026-07-21T12:00:00.000+00:00",
            "2026-07-21T12:00:00.200+00:00",
        ),
    )


def _build_structural_execution_evidence(
    intent,
) -> tuple[ExecutionQuoteSnapshot, ExecutionQuoteBinding]:
    quote = ExecutionQuoteSnapshot(
        provider="okx",
        instrument_id="BTC-USDT",
        observed_at_utc=datetime(2026, 7, 21, 12, 0, 0, 300_000, tzinfo=UTC),
        received_at_utc=datetime(2026, 7, 21, 12, 0, 0, 350_000, tzinfo=UTC),
        bid_price="66113.7",
        bid_quantity="0.5",
        ask_price="66113.9",
        ask_quantity="0.4",
        source_response_sha256=hashlib.sha256(_STRUCTURAL_QUOTE_SOURCE_BYTES).hexdigest(),
        instrument_snapshot_sha256=hashlib.sha256(_STRUCTURAL_INSTRUMENT_SOURCE_BYTES).hexdigest(),
    )
    replayed_quote = ExecutionQuoteSnapshot.from_json_bytes(quote.to_json_bytes())
    binding = bind_execution_quote(
        intent,
        replayed_quote,
        decision_at_utc=_QUOTE_DECISION_AT_UTC,
        maximum_age_ms=_QUOTE_MAXIMUM_AGE_MS,
    )
    replayed_binding = ExecutionQuoteBinding.from_json_bytes(binding.to_json_bytes())
    replayed_binding.assert_reconstructs(intent, replayed_quote)
    return replayed_quote, replayed_binding


def build_example(output_dir: Path) -> dict[str, object]:
    snapshot = _build_snapshot()
    observation = _build_server_time_observation()
    cutoff = build_okx_completed_bar_cutoff(
        snapshot,
        server_time_sample=observation.sample,
    )
    evidence_path, evidence_sha256 = write_okx_live_timing_response_evidence(
        output_dir / "okx-live-timing-response.json",
        observation=observation,
        cutoff=cutoff,
    )
    restored_evidence = read_okx_live_timing_response_evidence(
        evidence_path,
        expected_sha256=evidence_sha256,
    )
    intent = build_target_position_intent(
        cutoff,
        strategy_id="canonical-5bps-walk-forward",
        strategy_revision=_STRATEGY_REVISION,
        source_data_sha256=_EXPECTED_FIXTURE_SHA256,
        config_sha256=_CONFIG_SHA256,
        target_position=0.5393,
        minimum_position=0.0,
        maximum_position=1.0,
    )
    intent.assert_active_at(cutoff.signal_not_before_utc)
    quote, binding = _build_structural_execution_evidence(intent)
    quote_store_path = output_dir / "execution-quotes"
    recorded_quote_store = record_execution_quote_evidence(quote_store_path, quote)
    replayed_quote_store = load_execution_quote_evidence_store(quote_store_path)
    if replayed_quote_store != recorded_quote_store:
        raise ValueError("execution quote evidence replay mismatch")
    return {
        "timing_evidence_path": evidence_path.as_posix(),
        "timing_evidence_sha256": evidence_sha256,
        "signal_bar_open_utc": restored_evidence["bar_open_utc"],
        "signal_bar_close_utc": restored_evidence["bar_close_utc"],
        "candle_observed_at_utc": restored_evidence["candle_observed_at_utc"],
        "exchange_server_time_utc": restored_evidence["exchange_server_time_utc"],
        "server_time_response_received_utc": restored_evidence["server_time_response_received_utc"],
        "signal_not_before_utc": restored_evidence["signal_not_before_utc"],
        "intent": intent.to_dict(),
        "execution_quote": {
            "provenance_status": "structural_only_no_public_quote_producer",
            "midpoint": format(quote.midpoint, "f"),
            "observed_spread_bps": format(quote.spread_bps, "f"),
            "snapshot": quote.to_dict(),
        },
        "execution_quote_store": {
            "path": quote_store_path.as_posix(),
            "count": replayed_quote_store.count,
            "sha256": replayed_quote_store.sha256,
        },
        "execution_quote_binding": binding.to_dict(),
        "paper_decision_status": "not_implemented",
        "order_status": "not_implemented",
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reconstruct the implemented OKX signal-to-quote binding boundary."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reports/examples/signal-intent-timing"),
        help="Directory for timing evidence and the private quote store.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    summary = build_example(args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
