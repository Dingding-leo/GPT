from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from gpt_quant.paper_decision_store import PaperOrderDecision, load_paper_order_decision

_INSTRUMENT_SHA256 = "7bde34f3315c0774f12544c730b4fc19baa3399285aef9cabbb6bbf25869f31b"
_MARKET_SHA256 = "3f0366f59e908cbd0366be93a46d13c74a80d753e6452177ac8341d409c54250"
_PORTFOLIO_SHA256 = "821ce470b97bfbc53529bc2f7a95bded56d5e808a4d628728285a4ffd01c27c9"
_RISK_SHA256 = "6ab0010d4ce8090657d35599267fd73910f2d9a6d9566661a3f7ed9e566f5539"


def _decision(quantity: str) -> PaperOrderDecision:
    observed_at = datetime(2026, 7, 27, 1, tzinfo=UTC)
    return PaperOrderDecision(
        target_intent_id="a" * 64,
        instrument_id="BTC-USDT",
        decided_at_utc=datetime(2026, 7, 27, 1, 0, 1, tzinfo=UTC),
        market_observed_at_utc=observed_at,
        outcome="planned",
        reason_code="pretrade_passed",
        order_type="market",
        side="buy",
        base_quantity=quantity,
        instrument_snapshot_sha256=_INSTRUMENT_SHA256,
        market_snapshot_sha256=_MARKET_SHA256,
        portfolio_state_before_sha256=_PORTFOLIO_SHA256,
        risk_state_before_sha256=_RISK_SHA256,
        exchange_fee_bps="5",
        spread_bps="1.25",
        slippage_bps="0.5",
        market_impact_bps="0.25",
        latency_ms=80,
    )


def test_loader_rejects_same_inode_rewrite_during_deserialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "decision.json"
    original = _decision("0.001")
    replacement = _decision("1000000000")
    path.write_bytes(original.to_json_bytes())
    path.chmod(0o600)
    original_inode = path.stat().st_ino
    original_parser = PaperOrderDecision.from_json_bytes
    rewritten = False

    def rewrite_same_inode_then_parse(
        cls: type[PaperOrderDecision],
        value: bytes,
    ) -> PaperOrderDecision:
        del cls
        nonlocal rewritten
        if not rewritten:
            rewritten = True
            with path.open("wb") as output:
                output.write(replacement.to_json_bytes())
                output.flush()
                os.fsync(output.fileno())
        return original_parser(value)

    monkeypatch.setattr(
        PaperOrderDecision,
        "from_json_bytes",
        classmethod(rewrite_same_inode_then_parse),
    )

    with pytest.raises(RuntimeError, match="contents changed during replay"):
        load_paper_order_decision(path)

    assert rewritten
    assert path.stat().st_ino == original_inode
    assert path.read_bytes() == replacement.to_json_bytes()
