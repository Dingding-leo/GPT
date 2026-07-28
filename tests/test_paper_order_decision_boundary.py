from __future__ import annotations

import hashlib
import json
import pickle
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from gpt_quant.paper_decision_store import PaperOrderDecision as StoreDecision
from gpt_quant.paper_order_decision import _MAX_SERIALIZED_BYTES, PaperOrderDecision


def _decision() -> PaperOrderDecision:
    return PaperOrderDecision(
        target_intent_id="1" * 64,
        instrument_id="BTC-USDT",
        decided_at_utc=datetime(2026, 7, 24, 0, 0, 1, tzinfo=UTC),
        market_observed_at_utc=datetime(2026, 7, 24, 0, 0, tzinfo=UTC),
        outcome="planned",
        reason_code="pretrade_passed",
        order_type="market",
        side="buy",
        base_quantity="0.001",
        instrument_snapshot_sha256="2" * 64,
        market_snapshot_sha256="3" * 64,
        portfolio_state_before_sha256="4" * 64,
        risk_state_before_sha256="5" * 64,
        exchange_fee_bps="5",
        spread_bps="1.25",
        slippage_bps="0.5",
        market_impact_bps="0.25",
        latency_ms=80,
    )


def _canonical_json_bytes(payload: dict[str, object]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def test_domain_decision_is_independent_of_store_and_preserves_canonical_bytes() -> None:
    decision = _decision()

    assert StoreDecision is PaperOrderDecision
    assert PaperOrderDecision.__module__ == "gpt_quant.paper_order_decision"
    assert PaperOrderDecision.from_json_bytes(decision.to_json_bytes()) == decision
    assert decision.decision_id == (
        "fc299bb48bb6d34ac7406a10b7978f84651b932d6cd9245ae8637b0295ce6cb0"
    )
    assert hashlib.sha256(decision.to_json_bytes()).hexdigest() == (
        "fa7201a014cc46c240f8ef146df37558efd78ad074c75880a1760d03da38fa09"
    )


@pytest.mark.parametrize("exchange_fee_bps", ["0", "4", "7.5", "10", "15"])
def test_domain_decision_rejects_noncanonical_exchange_fee(exchange_fee_bps: str) -> None:
    with pytest.raises(ValueError, match="exchange_fee_bps must be exactly 5"):
        replace(_decision(), exchange_fee_bps=exchange_fee_bps)


@pytest.mark.parametrize("exchange_fee_bps", ["0", "4", "7.5", "10", "15"])
def test_serialized_decision_rejects_rehashed_noncanonical_exchange_fee(
    exchange_fee_bps: str,
) -> None:
    payload = json.loads(_decision().to_json_bytes())
    payload["exchange_fee_bps"] = exchange_fee_bps
    unsigned_payload = {key: value for key, value in payload.items() if key != "decision_id"}
    payload["decision_id"] = hashlib.sha256(_canonical_json_bytes(unsigned_payload)).hexdigest()
    serialized = _canonical_json_bytes(payload) + b"\n"

    with pytest.raises(ValueError, match="exchange_fee_bps must be exactly 5"):
        PaperOrderDecision.from_json_bytes(serialized)


def test_every_constructible_decision_fits_and_round_trips_at_the_record_limit() -> None:
    decision = _decision()
    exact_instrument_size = len(decision.instrument_id) + (
        _MAX_SERIALIZED_BYTES - len(decision.to_json_bytes())
    )
    exact = replace(decision, instrument_id="X" * exact_instrument_size)
    serialized = exact.to_json_bytes()

    assert len(serialized) == _MAX_SERIALIZED_BYTES
    assert PaperOrderDecision.from_json_bytes(serialized) == exact
    with pytest.raises(ValueError, match="exceeds the maximum record size"):
        replace(decision, instrument_id="X" * (exact_instrument_size + 1))


def test_serialized_decision_enforces_record_byte_limit_before_json_parsing() -> None:
    oversized = _decision().to_json_bytes().ljust(_MAX_SERIALIZED_BYTES + 1, b" ")

    assert len(oversized) == _MAX_SERIALIZED_BYTES + 1
    with pytest.raises(ValueError, match="exceeds the maximum record size"):
        PaperOrderDecision.from_json_bytes(oversized)


def test_domain_decision_rejects_unbounded_scalars_before_serialization() -> None:
    with pytest.raises(ValueError, match="base_quantity exceeds the maximum length"):
        replace(_decision(), base_quantity="1" * 257)
    with pytest.raises(ValueError, match="latency_ms is outside the supported range"):
        replace(_decision(), latency_ms=2**63)


def test_legacy_store_pickle_global_resolves_to_stable_domain_class() -> None:
    legacy_global = b"cgpt_quant.paper_decision_store\nPaperOrderDecision\n."

    assert pickle.loads(legacy_global) is PaperOrderDecision
    assert pickle.loads(pickle.dumps(_decision())) == _decision()
