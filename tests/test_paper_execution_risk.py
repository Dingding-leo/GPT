from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from gpt_quant.execution_intent import TargetPositionIntent
from gpt_quant.execution_quote import ExecutionQuoteSnapshot
from gpt_quant.execution_quote_binding import bind_execution_quote
from gpt_quant.paper_execution_attempt import record_paper_execution_attempt
from gpt_quant.paper_execution_risk import (
    PaperExecutionRiskImpact,
    measure_paper_execution_risk,
)

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "okx" / "order-book-btc-usdt-docs-20210826"
_RESPONSE_PATH = _FIXTURE_DIR / "response.json"
_METADATA_PATH = _FIXTURE_DIR / "metadata.json"
_EXPECTED_RESPONSE_SHA256 = "7d12a351f8f51320d1c8beee0063557e1c90388d66ac63412bf66ca544aeb3e3"
_INSTRUMENT_SNAPSHOT_SHA256 = "290bd86ecbb1683351993197b0ec18001dfb604b9ba1cb864d9d6d327855f0eb"
_SOURCE_DATA_SHA256 = "429abcbe5deb56ad6c7e1790cea101644a9fedd622f40de64eec5fd1ac3c4187"
_CONFIG_SHA256 = "6b06037376bce5df483311704f7b701c5e03a2a2735b2dd3361036fccd94da1a"


def _quote() -> ExecutionQuoteSnapshot:
    response = _RESPONSE_PATH.read_bytes()
    metadata = json.loads(_METADATA_PATH.read_text(encoding="utf-8"))
    payload = json.loads(response)
    book = payload["data"][0]

    assert hashlib.sha256(response).hexdigest() == _EXPECTED_RESPONSE_SHA256
    assert metadata["response_sha256"] == _EXPECTED_RESPONSE_SHA256
    assert metadata["instrument_snapshot_sha256"] == _INSTRUMENT_SNAPSHOT_SHA256
    return ExecutionQuoteSnapshot(
        provider="okx",
        instrument_id="BTC-USDT",
        observed_at_utc=datetime(2021, 8, 26, 8, 27, 16, 396_000, tzinfo=UTC),
        received_at_utc=datetime(2021, 8, 26, 8, 27, 16, 420_000, tzinfo=UTC),
        bid_price=book["bids"][0][0],
        bid_quantity=book["bids"][0][1],
        ask_price=book["asks"][0][0],
        ask_quantity=book["asks"][0][1],
        source_response_sha256=_EXPECTED_RESPONSE_SHA256,
        instrument_snapshot_sha256=_INSTRUMENT_SNAPSHOT_SHA256,
    )


def _intent() -> TargetPositionIntent:
    return TargetPositionIntent(
        instrument_id="BTC-USDT",
        bar="1H",
        strategy_id="canonical-five-bps",
        strategy_revision="e5e7ef22a23e6673c0183f47c0398f6af490d6d1",
        source_data_sha256=_SOURCE_DATA_SHA256,
        config_sha256=_CONFIG_SHA256,
        signal_bar_open_utc=datetime(2021, 8, 26, 7, tzinfo=UTC),
        signal_bar_close_utc=datetime(2021, 8, 26, 8, tzinfo=UTC),
        decision_not_before_utc=datetime(2021, 8, 26, 8, 27, 16, 390_000, tzinfo=UTC),
        expires_at_utc=datetime(2021, 8, 26, 9, tzinfo=UTC),
        target_position=0.25,
        minimum_position=0.0,
        maximum_position=1.0,
    )


def _attempt(
    *,
    side: str,
    outcome: str,
    requested: str = "0.1",
    filled: str = "0",
    fill_price: str = "0",
):
    quote = _quote()
    binding = bind_execution_quote(
        _intent(),
        quote,
        decision_at_utc=datetime(2021, 8, 26, 8, 27, 16, 430_000, tzinfo=UTC),
        maximum_age_ms=200,
    )
    return record_paper_execution_attempt(
        binding,
        quote,
        submitted_at_utc=datetime(2021, 8, 26, 8, 27, 16, 450_000, tzinfo=UTC),
        outcome_at_utc=datetime(2021, 8, 26, 8, 27, 16, 500_000, tzinfo=UTC),
        side=side,
        requested_base_quantity=requested,
        outcome=outcome,
        filled_base_quantity=filled,
        average_fill_price=fill_price,
        reason_code=f"paper-{outcome}",
    )


def test_partial_buy_accounts_five_bps_and_reserves_unfilled_cash() -> None:
    attempt = _attempt(
        side="buy",
        outcome="partial",
        filled="0.04",
        fill_price="41006.8",
    )

    impact = measure_paper_execution_risk(attempt)
    replayed = PaperExecutionRiskImpact.from_json_bytes(impact.to_json_bytes())

    assert replayed == impact
    assert impact.exchange_fee_one_way_bps == 5
    assert impact.unfilled_base_quantity == "0.06"
    assert impact.realized_quote_notional == "1640.272"
    assert impact.realized_exchange_fee_quote == "0.820136"
    assert impact.realized_cash_delta_quote == "-1641.092136"
    assert impact.position_delta_base == "0.04"
    assert impact.pending_cash_reservation_quote == "2461.638204"
    assert impact.pending_base_reservation == "0"
    assert impact.total_buy_cash_commitment_quote == "4102.73034"
    replayed.assert_reconstructs(attempt)


def test_accepted_and_rejected_no_fill_have_distinct_cash_reservations() -> None:
    accepted = measure_paper_execution_risk(_attempt(side="buy", outcome="accepted"))
    rejected = measure_paper_execution_risk(_attempt(side="buy", outcome="rejected"))

    assert accepted.realized_cash_delta_quote == "0"
    assert accepted.pending_cash_reservation_quote == "4102.73034"
    assert accepted.total_buy_cash_commitment_quote == "4102.73034"
    assert rejected.realized_cash_delta_quote == "0"
    assert rejected.pending_cash_reservation_quote == "0"
    assert rejected.total_buy_cash_commitment_quote == "0"


def test_partial_sell_reserves_remaining_base_and_rejects_fee_tampering() -> None:
    impact = measure_paper_execution_risk(
        _attempt(
            side="sell",
            outcome="partial",
            filled="0.04",
            fill_price="41006.3",
        )
    )

    assert impact.realized_quote_notional == "1640.252"
    assert impact.realized_exchange_fee_quote == "0.820126"
    assert impact.realized_cash_delta_quote == "1639.431874"
    assert impact.position_delta_base == "-0.04"
    assert impact.pending_cash_reservation_quote == "0"
    assert impact.pending_base_reservation == "0.06"

    payload = json.loads(impact.to_json_bytes())
    payload["exchange_fee_one_way_bps"] = 10
    tampered = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode() + b"\n"
    with pytest.raises(ValueError, match="exactly 5 bps"):
        PaperExecutionRiskImpact.from_json_bytes(tampered)


def test_high_precision_partial_buy_preserves_exact_five_bps_cash_math() -> None:
    attempt = _attempt(
        side="buy",
        outcome="partial",
        requested="0.12345678901234567890123456789",
        filled="0.02345678901234567890123456789",
        fill_price="41006.8",
    )

    impact = measure_paper_execution_risk(attempt)

    assert impact.unfilled_base_quantity == "0.1"
    assert impact.realized_quote_notional == "961.887855671456785567145678551652"
    assert impact.realized_exchange_fee_quote == "0.480943927835728392783572839275826"
    assert impact.realized_cash_delta_quote == "-962.368799599292513959929251390927826"
    assert impact.pending_cash_reservation_quote == "4102.73034"
    assert impact.total_buy_cash_commitment_quote == ("5065.099139599292513959929251390927826")
