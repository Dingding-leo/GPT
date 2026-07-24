from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from gpt_quant.maker_fill_replay import (
    OKXPublicTradeSnapshot,
    simulate_post_only_maker_fill,
)

_FIXTURE = (
    Path(__file__).parent / "fixtures" / "okx" / "trades-btc-usdt-docs-20220602" / "response.json"
)
_ORDER_INTENT_ID = "a" * 64
_SIGNAL = datetime(2022, 6, 2, 9, 0, tzinfo=UTC)
_SUBMITTED = datetime(2022, 6, 2, 9, 20, 40, tzinfo=UTC)
_TRADE_THROUGH_AT = datetime(2022, 6, 2, 9, 20, 46, 974000, tzinfo=UTC)


def _snapshot() -> OKXPublicTradeSnapshot:
    raw = _FIXTURE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "01438cc23709d9c8e9ea8d9d49d3f64c65978d27d592356a333f7a3da213d563"
    )
    return OKXPublicTradeSnapshot.from_json_bytes(raw)


def test_touch_without_trade_through_never_fills() -> None:
    replay = simulate_post_only_maker_fill(
        _snapshot(),
        order_intent_id=_ORDER_INTENT_ID,
        signal_at_utc=_SIGNAL,
        submitted_at_utc=_SUBMITTED,
        expires_at_utc=datetime(2022, 6, 2, 9, 20, 45, tzinfo=UTC),
        side="buy",
        limit_price="29964.1",
        requested_base_quantity="0.00001",
        queue_ahead_base_quantity="0",
    )

    assert replay.outcome == "cancelled_no_fill"
    assert replay.touch_trade_count == 1
    assert replay.touch_base_quantity == "0.00001"
    assert replay.trade_through_trade_count == 0
    assert replay.filled_base_quantity == "0"
    assert replay.exchange_fee_quote == "0"
    assert replay.cancelled_at_utc == datetime(2022, 6, 2, 9, 20, 45, tzinfo=UTC)
    assert replay.requote_eligible is True


def test_trade_through_can_only_partially_fill_available_volume() -> None:
    replay = simulate_post_only_maker_fill(
        _snapshot(),
        order_intent_id=_ORDER_INTENT_ID,
        signal_at_utc=_SIGNAL,
        submitted_at_utc=_SUBMITTED,
        expires_at_utc=datetime(2022, 6, 2, 9, 20, 50, tzinfo=UTC),
        side="buy",
        limit_price="29964.1",
        requested_base_quantity="0.00002",
        queue_ahead_base_quantity="0",
    )

    assert replay.outcome == "cancelled_partial"
    assert replay.touch_trade_count == 1
    assert replay.trade_through_trade_count == 1
    assert replay.trade_through_base_quantity == "0.00001"
    assert replay.filled_base_quantity == "0.00001"
    assert replay.unfilled_base_quantity == "0.00001"
    assert replay.average_fill_price == "29964.1"
    assert replay.exchange_fee_one_way_bps == "5"
    assert replay.exchange_fee_quote == "0.0001498205"
    assert replay.first_trade_through_at_utc == datetime(
        2022,
        6,
        2,
        9,
        20,
        46,
        974000,
        tzinfo=UTC,
    )
    assert replay.filled_at_utc is None
    assert replay.requote_eligible is True


def test_declared_queue_ahead_can_consume_all_trade_through_volume() -> None:
    replay = simulate_post_only_maker_fill(
        _snapshot(),
        order_intent_id=_ORDER_INTENT_ID,
        signal_at_utc=_SIGNAL,
        submitted_at_utc=_SUBMITTED,
        expires_at_utc=datetime(2022, 6, 2, 9, 20, 50, tzinfo=UTC),
        side="buy",
        limit_price="29964.1",
        requested_base_quantity="0.00001",
        queue_ahead_base_quantity="0.00001",
    )

    assert replay.outcome == "cancelled_no_fill"
    assert replay.trade_through_trade_count == 1
    assert replay.queue_consumed_base_quantity == "0.00001"
    assert replay.remaining_queue_ahead_base_quantity == "0"
    assert replay.filled_base_quantity == "0"


def test_full_trade_through_fill_is_deterministic_and_hash_bound() -> None:
    snapshot = _snapshot()
    first = simulate_post_only_maker_fill(
        snapshot,
        order_intent_id=_ORDER_INTENT_ID,
        signal_at_utc=_SIGNAL,
        submitted_at_utc=_SUBMITTED,
        expires_at_utc=datetime(2022, 6, 2, 9, 20, 50, tzinfo=UTC),
        side="buy",
        limit_price="29964.1",
        requested_base_quantity="0.000005",
        queue_ahead_base_quantity="0",
    )
    second = simulate_post_only_maker_fill(
        snapshot,
        order_intent_id=_ORDER_INTENT_ID,
        signal_at_utc=_SIGNAL,
        submitted_at_utc=_SUBMITTED,
        expires_at_utc=datetime(2022, 6, 2, 9, 20, 50, tzinfo=UTC),
        side="buy",
        limit_price="29964.1",
        requested_base_quantity="0.000005",
        queue_ahead_base_quantity="0",
    )

    assert first == second
    assert first.outcome == "filled"
    assert first.filled_base_quantity == "0.000005"
    assert first.unfilled_base_quantity == "0"
    assert first.filled_at_utc == datetime(2022, 6, 2, 9, 20, 46, 974000, tzinfo=UTC)
    assert first.cancelled_at_utc is None
    assert first.requote_eligible is False
    assert first.to_json_bytes() == second.to_json_bytes()
    assert hashlib.sha256(first.to_json_bytes()).hexdigest() != first.replay_id


@pytest.mark.parametrize(
    ("submitted_at_utc", "expires_at_utc", "expected_touch_count"),
    [
        (
            _TRADE_THROUGH_AT,
            datetime(2022, 6, 2, 9, 20, 50, tzinfo=UTC),
            0,
        ),
        (
            _SUBMITTED,
            _TRADE_THROUGH_AT,
            1,
        ),
    ],
    ids=("trade-at-submission", "trade-at-exclusive-expiry"),
)
def test_boundary_trade_cannot_fill_post_only_order(
    submitted_at_utc: datetime,
    expires_at_utc: datetime,
    expected_touch_count: int,
) -> None:
    replay = simulate_post_only_maker_fill(
        _snapshot(),
        order_intent_id=_ORDER_INTENT_ID,
        signal_at_utc=_SIGNAL,
        submitted_at_utc=submitted_at_utc,
        expires_at_utc=expires_at_utc,
        side="buy",
        limit_price="29964.1",
        requested_base_quantity="0.000005",
        queue_ahead_base_quantity="0",
    )

    assert replay.outcome == "cancelled_no_fill"
    assert replay.touch_trade_count == expected_touch_count
    assert replay.trade_through_trade_count == 0
    assert replay.filled_base_quantity == "0"
    assert replay.exchange_fee_quote == "0"
    assert replay.cancelled_at_utc == expires_at_utc
    assert replay.requote_eligible is True


def test_duplicate_public_trade_fields_fail_closed() -> None:
    raw = _FIXTURE.read_bytes().replace(
        b'"tradeId":"242720720"',
        b'"tradeId":"242720720","tradeId":"242720721"',
        1,
    )

    with pytest.raises(ValueError, match="duplicate field 'tradeId'"):
        OKXPublicTradeSnapshot.from_json_bytes(raw)
