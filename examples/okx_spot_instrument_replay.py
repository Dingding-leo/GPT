from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd

from gpt_quant.execution_intent import TargetPositionIntent
from gpt_quant.execution_quote import ExecutionQuoteSnapshot
from gpt_quant.execution_quote_binding import ExecutionQuoteBinding, bind_execution_quote
from gpt_quant.okx_instrument_archive import write_okx_spot_instrument_observation
from gpt_quant.okx_instruments import fetch_okx_spot_instrument_snapshot
from gpt_quant.okx_live import OKXServerTimeSample
from gpt_quant.okx_order_constraints import (
    validate_okx_paper_execution_attempt_constraints,
    validate_okx_spot_limit_order_constraints,
)
from gpt_quant.paper_execution_attempt import (
    PaperExecutionAttempt,
    record_paper_execution_attempt,
)

_ROOT = Path(__file__).resolve().parents[1]
_INSTRUMENT_DIR = _ROOT / "tests/fixtures/okx/public_instruments_btc_usdt_20251125"
_BOOK_DIR = _ROOT / "tests/fixtures/okx/order-book-btc-usdt-docs-20210826"
_INSTRUMENT_SHA256 = "290bd86ecbb1683351993197b0ec18001dfb604b9ba1cb864d9d6d327855f0eb"
_BOOK_SHA256 = "7d12a351f8f51320d1c8beee0063557e1c90388d66ac63412bf66ca544aeb3e3"
_MAIN_REVISION = "c26473cc2009b0b12aff47c3fa7235a6432eeacc"
_REQUESTED_BASE_QUANTITY = "0.1"
_FILLED_BASE_QUANTITY = "0.04"
_MINIMUM_PAPER_QUOTE_NOTIONAL = "10"
_CONFIG_BYTES = (
    b'{"exchange_fee_bps_one_way":5.0,'
    b'"minimum_paper_quote_notional":"10",'
    b'"purpose":"offline-paper-attempt-constraint-probe"}\n'
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Execute the current offline OKX paper-attempt constraint gate."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reports/examples/okx-spot-instrument"),
    )
    return parser.parse_args()


def _clock(*values: datetime):
    iterator = iter(values)
    return lambda: next(iterator)


def _format_utc(value: datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical_decimal(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _load_pinned_bytes(directory: Path, metadata_key: str, expected_sha256: str) -> bytes:
    raw = (directory / "response.json").read_bytes()
    metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("immutable OKX fixture does not match its pinned SHA-256 digest")
    if metadata.get(metadata_key) != expected_sha256:
        raise ValueError("OKX fixture metadata does not match its pinned SHA-256 digest")
    return raw


def _instrument_snapshot(raw: bytes):
    request_started = datetime(2026, 7, 24, 0, 0, tzinfo=UTC)
    response_received = request_started + timedelta(milliseconds=125)
    server_started = response_received + timedelta(milliseconds=1)
    server_received = server_started + timedelta(milliseconds=100)
    exchange_observed = server_started + timedelta(milliseconds=50)
    server_sample = OKXServerTimeSample(
        base_url="https://www.okx.com",
        endpoint="/api/v5/public/time",
        local_request_started_utc=pd.Timestamp(server_started),
        local_response_received_utc=pd.Timestamp(server_received),
        server_time_utc=pd.Timestamp(exchange_observed),
        round_trip_seconds=0.1,
        midpoint_clock_skew_seconds=0.0,
    )

    def get_bytes(url: str, timeout: float) -> bytes:
        expected = (
            "https://www.okx.com/api/v5/public/instruments?"
            "instType=SPOT&instId=BTC-USDT"
        )
        if url != expected or timeout != 20.0:
            raise ValueError("unexpected public OKX instrument request")
        return raw

    return fetch_okx_spot_instrument_snapshot(
        inst_id="BTC-USDT",
        server_time_sample=server_sample,
        get_bytes=get_bytes,
        now=_clock(request_started, response_received),
    )


def _structural_quote(raw: bytes, instrument_sha256: str) -> ExecutionQuoteSnapshot:
    payload = json.loads(raw)
    book = payload["data"][0]
    bid_price, bid_quantity, *_ = book["bids"][0]
    ask_price, ask_quantity, *_ = book["asks"][0]
    return ExecutionQuoteSnapshot(
        provider="okx",
        instrument_id="BTC-USDT",
        observed_at_utc=datetime(2026, 7, 24, 0, 0, 0, 300_000, tzinfo=UTC),
        received_at_utc=datetime(2026, 7, 24, 0, 0, 0, 350_000, tzinfo=UTC),
        bid_price=bid_price,
        bid_quantity=bid_quantity,
        ask_price=ask_price,
        ask_quantity=ask_quantity,
        source_response_sha256=_BOOK_SHA256,
        instrument_snapshot_sha256=instrument_sha256,
    )


def _paper_attempt(
    quote: ExecutionQuoteSnapshot,
) -> tuple[TargetPositionIntent, ExecutionQuoteBinding, PaperExecutionAttempt]:
    intent = TargetPositionIntent(
        instrument_id="BTC-USDT",
        bar="offline-constraint-probe",
        strategy_id="docs-constraint-probe",
        strategy_revision=_MAIN_REVISION,
        source_data_sha256=_BOOK_SHA256,
        config_sha256=hashlib.sha256(_CONFIG_BYTES).hexdigest(),
        signal_bar_open_utc=datetime(2026, 7, 23, 23, 0, tzinfo=UTC),
        signal_bar_close_utc=datetime(2026, 7, 24, 0, 0, tzinfo=UTC),
        decision_not_before_utc=datetime(2026, 7, 24, 0, 0, 0, 250_000, tzinfo=UTC),
        expires_at_utc=datetime(2026, 7, 24, 0, 1, tzinfo=UTC),
        target_position=0.25,
        minimum_position=0.0,
        maximum_position=1.0,
    )
    binding = bind_execution_quote(
        intent,
        quote,
        decision_at_utc=datetime(2026, 7, 24, 0, 0, 0, 400_000, tzinfo=UTC),
        maximum_age_ms=500,
    )
    submitted_at = datetime(2026, 7, 24, 0, 0, 0, 450_000, tzinfo=UTC)
    intent.assert_active_at(submitted_at)
    attempt = record_paper_execution_attempt(
        binding,
        quote,
        submitted_at_utc=submitted_at,
        outcome_at_utc=datetime(2026, 7, 24, 0, 0, 0, 500_000, tzinfo=UTC),
        side="buy",
        requested_base_quantity=_REQUESTED_BASE_QUANTITY,
        outcome="partial",
        filled_base_quantity=_FILLED_BASE_QUANTITY,
        average_fill_price=quote.ask_price,
        reason_code="offline-partial-probe",
    )
    return intent, binding, attempt


def main() -> int:
    args = _parse_args()
    instrument_raw = _load_pinned_bytes(
        _INSTRUMENT_DIR,
        "fixture_sha256",
        _INSTRUMENT_SHA256,
    )
    book_raw = _load_pinned_bytes(_BOOK_DIR, "response_sha256", _BOOK_SHA256)

    snapshot = _instrument_snapshot(instrument_raw)
    archive_paths = write_okx_spot_instrument_observation(snapshot, args.output_dir)
    retry_paths = write_okx_spot_instrument_observation(snapshot, args.output_dir)
    if archive_paths != retry_paths:
        raise ValueError("instrument archive retry changed its content-addressed paths")
    if archive_paths["raw"].read_bytes() != instrument_raw:
        raise ValueError("instrument archive changed the exact provider bytes")

    quote = _structural_quote(book_raw, snapshot.raw_response_sha256)
    intent, binding, attempt = _paper_attempt(quote)

    validated_quantity, validated_limit_price = validate_okx_spot_limit_order_constraints(
        snapshot,
        submitted_at_utc=attempt.submitted_at_utc,
        maximum_snapshot_age_ms=1_000,
        base_quantity=attempt.requested_base_quantity,
        limit_price=quote.ask_price,
    )
    validate_okx_paper_execution_attempt_constraints(
        snapshot,
        quote,
        attempt,
        maximum_snapshot_age_ms=1_000,
        minimum_paper_quote_notional=_MINIMUM_PAPER_QUOTE_NOTIONAL,
    )
    attempt.assert_reconstructs(intent, binding, quote)
    replayed_attempt = PaperExecutionAttempt.from_json_bytes(attempt.to_json_bytes())
    replayed_attempt.assert_reconstructs(intent, binding, quote)

    requested = Decimal(attempt.requested_base_quantity)
    filled = Decimal(attempt.filled_base_quantity)
    touch = Decimal(quote.ask_price)
    requested_notional = requested * touch
    minimum_base = snapshot.minimum_order_size_base_decimal

    summary = {
        "account_connectivity": "disabled",
        "canonical_research_economics": {
            "additional_execution_costs_in_pnl": "none",
            "exchange_fee_bps_one_way": 5.0,
        },
        "constraint_probe": {
            "base_quantity": validated_quantity,
            "limit_price": validated_limit_price,
            "maximum_instrument_snapshot_age_ms": 1_000,
            "status": "passed",
            "submitted_at_utc": _format_utc(attempt.submitted_at_utc),
        },
        "execution_diagnostics": {
            "latency": "recorded_as_timestamps_only_not_priced",
            "market_impact": "not_modeled",
            "observed_spread_bps": _canonical_decimal(quote.spread_bps),
            "slippage": "not_modeled",
        },
        "instrument": {
            "archive_idempotent": archive_paths == retry_paths,
            "lot_size": snapshot.lot_size,
            "minimum_order_size_base": snapshot.minimum_order_size_base,
            "raw_response_sha256": snapshot.raw_response_sha256,
            "state": snapshot.state,
            "tick_size": snapshot.tick_size,
        },
        "minimum_buy_quote_equivalent_at_observed_ask": _canonical_decimal(
            minimum_base * touch
        ),
        "minimum_quote_notional_constraint": "not_reported_by_public_instrument_endpoint",
        "order_submission": "not_performed",
        "paper_attempt_probe": {
            "attempt_id": attempt.attempt_id,
            "average_fill_price": attempt.average_fill_price,
            "binding_id": binding.binding_id,
            "fill_fraction": _canonical_decimal(filled / requested),
            "fill_price_convention": attempt.fill_price_convention,
            "filled_base_quantity": attempt.filled_base_quantity,
            "minimum_paper_quote_notional_policy": _MINIMUM_PAPER_QUOTE_NOTIONAL,
            "outcome": attempt.outcome,
            "reconstructs": True,
            "replay_equal": replayed_attempt == attempt,
            "requested_base_quantity": attempt.requested_base_quantity,
            "requested_quote_notional_at_ask": _canonical_decimal(requested_notional),
            "status": "passed",
            "target_intent_id": intent.intent_id,
            "visible_same_side_touch_quantity": quote.ask_quantity,
        },
        "paper_order_blockers": [
            "official_fixtures_are_not_contemporaneous",
            "probe_timestamps_are_structural_not_provider_observations",
            "one_hour_research_pipeline_not_implemented",
            "maker_post_only_order_lifecycle_not_implemented",
            "no_fill_timeout_cancel_requote_events_not_implemented",
            "paper_minimum_notional_policy_is_example_only",
            "risk_approval_not_present",
            "durable_order_fill_portfolio_state_not_present",
            "reconciliation_and_kill_switches_not_present",
        ],
        "paper_order_eligible": False,
        "quote": {
            "ask_price": quote.ask_price,
            "ask_quantity": quote.ask_quantity,
            "bid_price": quote.bid_price,
            "bid_quantity": quote.bid_quantity,
            "source_response_sha256": quote.source_response_sha256,
        },
        "timeframe_status": {
            "current_main_research": "1Dutc_benchmark_only",
            "intraday_1h": "not_implemented",
            "intraday_15m": "not_implemented",
            "this_gate": "timeframe_neutral_offline_constraint_probe",
        },
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
