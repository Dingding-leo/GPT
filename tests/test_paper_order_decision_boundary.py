from __future__ import annotations

import hashlib
import pickle
from datetime import UTC, datetime

from gpt_quant.paper_decision_store import PaperOrderDecision as StoreDecision
from gpt_quant.paper_order_decision import PaperOrderDecision


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


def test_legacy_store_pickle_global_resolves_to_stable_domain_class() -> None:
    legacy_global = b"cgpt_quant.paper_decision_store\nPaperOrderDecision\n."

    assert pickle.loads(legacy_global) is PaperOrderDecision
    assert pickle.loads(pickle.dumps(_decision())) == _decision()
