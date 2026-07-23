from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from gpt_quant.execution_quote import ExecutionQuoteSnapshot

_REAL_OKX_FIXTURE_ROWS_SHA256 = "dcb30e58e10f8415aefe8c206f99c21fc8862b3b4f5ea65679a01262980c5481"
_REAL_OKX_RAW_PAGES_SHA256 = "0db4334a5fd7cdee0dc500b01cd5610b30d9b78f392b537f18c35ce1fd80971a"


@dataclass(frozen=True)
class _IntentWindow:
    instrument_id: str = "BTC-USDT"
    decision_not_before_utc: datetime = datetime(2026, 7, 22, 0, 0, 0, 100_000, tzinfo=UTC)
    expires_at_utc: datetime = datetime(2026, 7, 23, tzinfo=UTC)

    def assert_active_at(self, value: datetime | str) -> None:
        observed = (
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            if isinstance(value, str)
            else value
        )
        observed = observed.astimezone(UTC)
        if observed < self.decision_not_before_utc:
            raise ValueError("target-position intent is not active yet")
        if observed >= self.expires_at_utc:
            raise ValueError("target-position intent has expired")


def _quote(**overrides: object) -> ExecutionQuoteSnapshot:
    values: dict[str, object] = {
        "provider": "okx",
        "instrument_id": "BTC-USDT",
        "observed_at_utc": datetime(2026, 7, 22, 0, 0, 0, 200_000, tzinfo=UTC),
        "received_at_utc": datetime(2026, 7, 22, 0, 0, 0, 250_000, tzinfo=UTC),
        "bid_price": "66113.7",
        "bid_quantity": "0.5",
        "ask_price": "66113.9",
        "ask_quantity": "0.4",
        "source_response_sha256": _REAL_OKX_RAW_PAGES_SHA256,
        "instrument_snapshot_sha256": _REAL_OKX_FIXTURE_ROWS_SHA256,
    }
    values.update(overrides)
    return ExecutionQuoteSnapshot(**values)


def test_execution_quote_is_canonical_content_addressed_market_evidence() -> None:
    snapshot = _quote()

    replayed = ExecutionQuoteSnapshot.from_json_bytes(snapshot.to_json_bytes())
    offset = timezone(timedelta(hours=9, minutes=30))
    equivalent = _quote(
        observed_at_utc=snapshot.observed_at_utc.astimezone(offset),
        received_at_utc=snapshot.received_at_utc.astimezone(offset),
    )

    assert replayed == snapshot
    assert equivalent.to_json_bytes() == snapshot.to_json_bytes()
    assert equivalent.snapshot_id == snapshot.snapshot_id
    assert snapshot.midpoint == Decimal("66113.8")
    assert snapshot.spread_bps == (Decimal("0.2") / Decimal("66113.8") * Decimal(10_000))


def test_execution_quote_validates_as_of_window_for_target_intent() -> None:
    snapshot = _quote()
    intent = _IntentWindow()

    snapshot.assert_usable_for(
        intent,
        decision_at_utc=datetime(2026, 7, 22, 0, 0, 0, 300_000, tzinfo=UTC),
        maximum_age_ms=100,
    )

    with pytest.raises(ValueError, match="predates target-intent activation"):
        _quote(observed_at_utc=datetime(2026, 7, 22, tzinfo=UTC)).assert_usable_for(
            intent,
            decision_at_utc=datetime(2026, 7, 22, 0, 0, 0, 300_000, tzinfo=UTC),
            maximum_age_ms=1_000,
        )
    with pytest.raises(ValueError, match="received before the decision"):
        snapshot.assert_usable_for(
            intent,
            decision_at_utc=snapshot.received_at_utc,
            maximum_age_ms=100,
        )
    with pytest.raises(ValueError, match="stale"):
        snapshot.assert_usable_for(
            intent,
            decision_at_utc=datetime(2026, 7, 22, 0, 0, 0, 301_000, tzinfo=UTC),
            maximum_age_ms=100,
        )
    with pytest.raises(ValueError, match="does not match"):
        snapshot.assert_usable_for(
            _IntentWindow(instrument_id="ETH-USDT"),
            decision_at_utc=datetime(2026, 7, 22, 0, 0, 0, 300_000, tzinfo=UTC),
            maximum_age_ms=100,
        )


def test_execution_quote_rejects_crossed_or_noncanonical_books() -> None:
    with pytest.raises(ValueError, match="strictly less"):
        _quote(bid_price="66113.9")
    with pytest.raises(ValueError, match="canonical"):
        _quote(bid_quantity="0.500")
    with pytest.raises(ValueError, match="positive"):
        _quote(ask_quantity="0")
    with pytest.raises(ValueError, match="after received_at_utc"):
        _quote(
            observed_at_utc=datetime(2026, 7, 22, 0, 0, 0, 300_000, tzinfo=UTC),
            received_at_utc=datetime(2026, 7, 22, 0, 0, 0, 250_000, tzinfo=UTC),
        )


def test_execution_quote_rejects_noncanonical_or_tampered_replay() -> None:
    snapshot = _quote()
    serialized = snapshot.to_json_bytes()

    with pytest.raises(ValueError, match="canonical encoding"):
        ExecutionQuoteSnapshot.from_json_bytes(serialized.replace(b'"ask_price"', b' "ask_price"'))
    with pytest.raises(ValueError, match="ID does not match"):
        ExecutionQuoteSnapshot.from_json_bytes(
            serialized.replace(snapshot.snapshot_id.encode(), b"0" * 64)
        )
    with pytest.raises(ValueError, match="duplicate field"):
        ExecutionQuoteSnapshot.from_json_bytes(serialized.replace(b"{", b'{"provider":"okx",', 1))


def test_execution_quote_accepts_current_target_position_intent_contract() -> None:
    from gpt_quant.execution_intent import TargetPositionIntent

    intent = TargetPositionIntent(
        instrument_id="BTC-USDT",
        bar="1Dutc",
        strategy_id="canonical-trend",
        strategy_revision="e3ad3cbcf90bb9981ad9bb012506ccbcbbce5040",
        source_data_sha256=_REAL_OKX_FIXTURE_ROWS_SHA256,
        config_sha256=_REAL_OKX_RAW_PAGES_SHA256,
        signal_bar_open_utc=datetime(2026, 7, 21, tzinfo=UTC),
        signal_bar_close_utc=datetime(2026, 7, 22, tzinfo=UTC),
        decision_not_before_utc=datetime(2026, 7, 22, 0, 0, 0, 100_000, tzinfo=UTC),
        expires_at_utc=datetime(2026, 7, 23, tzinfo=UTC),
        target_position=0.5,
        minimum_position=0.0,
        maximum_position=1.0,
    )

    _quote().assert_usable_for(
        intent,
        decision_at_utc=datetime(2026, 7, 22, 0, 0, 0, 300_000, tzinfo=UTC),
        maximum_age_ms=100,
    )
