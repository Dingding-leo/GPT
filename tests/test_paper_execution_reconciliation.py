from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from gpt_quant.execution_intent import TargetPositionIntent
from gpt_quant.execution_quote import ExecutionQuoteSnapshot
from gpt_quant.execution_quote_binding import bind_execution_quote
from gpt_quant.execution_quote_binding_journal import record_execution_quote_binding
from gpt_quant.execution_quote_evidence import record_execution_quote_evidence
from gpt_quant.paper_execution_attempt import record_paper_execution_attempt
from gpt_quant.paper_execution_attempt_journal import (
    PaperExecutionAttemptJournal,
    record_paper_execution_attempt_evidence,
)
from gpt_quant.paper_execution_reconciliation import (
    PaperExecutionReconciliationEvidence,
    reconcile_paper_execution_evidence,
)
from gpt_quant.target_intent_journal import record_target_position_intent

_BOOK_SHA256 = "7d12a351f8f51320d1c8beee0063557e1c90388d66ac63412bf66ca544aeb3e3"
_INSTRUMENT_SHA256 = "290bd86ecbb1683351993197b0ec18001dfb604b9ba1cb864d9d6d327855f0eb"
_SOURCE_SHA256 = "dcb30e58e10f8415aefe8c206f99c21fc8862b3b4f5ea65679a01262980c5481"
_CONFIGS = {
    "exchange_fee": b'{"component":"exchange_fee","one_way_bps":"5","version":1}\n',
    "spread": b'{"component":"spread","source":"observed_top_of_book","version":1}\n',
    "slippage": b'{"component":"slippage","status":"observed_only","version":1}\n',
    "market_impact": b'{"component":"market_impact","status":"observed_only","version":1}\n',
    "latency": b'{"component":"latency","status":"observed_unpriced","version":1}\n',
}
_COST_HASHES = {name: hashlib.sha256(value).hexdigest() for name, value in _CONFIGS.items()}


def _persisted_chain(tmp_path):
    signal_open = datetime(2021, 8, 25, tzinfo=UTC)
    signal_close = signal_open + timedelta(days=1)
    observed = datetime(2021, 8, 26, 8, 27, 16, 396000, tzinfo=UTC)
    received = observed + timedelta(milliseconds=4)
    decision = received + timedelta(milliseconds=50)
    submitted = decision + timedelta(milliseconds=25)
    outcome_at = submitted + timedelta(milliseconds=20)

    intent = TargetPositionIntent(
        instrument_id="BTC-USDT",
        bar="1Dutc",
        strategy_id="canonical-walk-forward",
        strategy_revision="1" * 40,
        source_data_sha256=_SOURCE_SHA256,
        config_sha256=hashlib.sha256(b'{"fee_bps":5}\n').hexdigest(),
        signal_bar_open_utc=signal_open,
        signal_bar_close_utc=signal_close,
        decision_not_before_utc=signal_close,
        expires_at_utc=signal_close + timedelta(days=1),
        target_position=0.5,
        minimum_position=0.0,
        maximum_position=1.0,
    )
    quote = ExecutionQuoteSnapshot(
        provider="okx",
        instrument_id="BTC-USDT",
        observed_at_utc=observed,
        received_at_utc=received,
        bid_price="41006.3",
        bid_quantity="0.30178218",
        ask_price="41006.8",
        ask_quantity="0.60038921",
        source_response_sha256=_BOOK_SHA256,
        instrument_snapshot_sha256=_INSTRUMENT_SHA256,
    )
    binding = bind_execution_quote(
        intent,
        quote,
        decision_at_utc=decision,
        maximum_age_ms=250,
    )
    attempt = record_paper_execution_attempt(
        binding,
        quote,
        submitted_at_utc=submitted,
        outcome_at_utc=outcome_at,
        side="buy",
        requested_base_quantity="0.001",
        outcome="filled",
        filled_base_quantity="0.001",
        average_fill_price=quote.ask_price,
        reason_code="paper_touch_fill",
    )

    intent_journal = record_target_position_intent(tmp_path / "intents.jsonl", intent)
    quote_store = record_execution_quote_evidence(tmp_path / "quotes", quote)
    binding_journal = record_execution_quote_binding(
        tmp_path / "bindings.jsonl",
        binding,
        intent_journal=intent_journal,
        quote_store=quote_store,
    )
    attempt_journal = record_paper_execution_attempt_evidence(
        tmp_path / "attempts.jsonl",
        attempt,
        intent_journal=intent_journal,
        quote_store=quote_store,
        binding_journal=binding_journal,
    )
    return intent_journal, quote_store, binding_journal, attempt_journal


def _reconcile(chain, **overrides):
    intent_journal, quote_store, binding_journal, attempt_journal = chain
    hashes = {
        "exchange_fee_config_sha256": _COST_HASHES["exchange_fee"],
        "spread_config_sha256": _COST_HASHES["spread"],
        "slippage_config_sha256": _COST_HASHES["slippage"],
        "market_impact_config_sha256": _COST_HASHES["market_impact"],
        "latency_config_sha256": _COST_HASHES["latency"],
    }
    hashes.update(overrides)
    return reconcile_paper_execution_evidence(
        intent_journal=intent_journal,
        quote_store=quote_store,
        binding_journal=binding_journal,
        attempt_journal=attempt_journal,
        **hashes,
    )


def test_reconciliation_replays_exact_chain_under_five_bps_only_economics(tmp_path) -> None:
    chain = _persisted_chain(tmp_path)
    evidence = _reconcile(chain)

    assert evidence.schema_version == 2
    assert evidence.exchange_fee_one_way_bps == "5"
    assert "all_in_stress_bps" not in evidence.to_dict()
    assert evidence.intent_count == evidence.quote_count == 1
    assert evidence.binding_count == evidence.attempt_count == 1
    assert (
        PaperExecutionReconciliationEvidence.from_json_bytes(evidence.to_json_bytes()) == evidence
    )
    evidence.assert_reconstructs(
        intent_journal=chain[0],
        quote_store=chain[1],
        binding_journal=chain[2],
        attempt_journal=chain[3],
        exchange_fee_config_sha256=_COST_HASHES["exchange_fee"],
        spread_config_sha256=_COST_HASHES["spread"],
        slippage_config_sha256=_COST_HASHES["slippage"],
        market_impact_config_sha256=_COST_HASHES["market_impact"],
        latency_config_sha256=_COST_HASHES["latency"],
    )


def test_non_five_bps_fee_config_cannot_enter_reconciliation(tmp_path) -> None:
    chain = _persisted_chain(tmp_path)
    seven_point_five_bps = hashlib.sha256(
        b'{"component":"exchange_fee","one_way_bps":"7.5","version":1}\n'
    ).hexdigest()

    with pytest.raises(ValueError, match="exact-5-bps-only"):
        _reconcile(chain, exchange_fee_config_sha256=seven_point_five_bps)


def test_observed_diagnostics_are_independently_content_addressed(tmp_path) -> None:
    chain = _persisted_chain(tmp_path)
    baseline = _reconcile(chain)
    changed_observation = _reconcile(
        chain,
        slippage_config_sha256=hashlib.sha256(
            b'{"component":"slippage","status":"observed_only","version":2}\n'
        ).hexdigest(),
    )

    assert changed_observation.exchange_fee_config_sha256 == baseline.exchange_fee_config_sha256
    assert changed_observation.exchange_fee_one_way_bps == "5"
    assert changed_observation.slippage_config_sha256 != baseline.slippage_config_sha256
    assert changed_observation.reconciliation_id != baseline.reconciliation_id


def test_reconciliation_rejects_tampered_roots_and_noncanonical_json(tmp_path) -> None:
    chain = _persisted_chain(tmp_path)
    tampered_attempts = PaperExecutionAttemptJournal(
        attempts=chain[3].attempts,
        sha256="0" * 64,
    )
    with pytest.raises(ValueError, match="attempt journal SHA-256"):
        reconcile_paper_execution_evidence(
            intent_journal=chain[0],
            quote_store=chain[1],
            binding_journal=chain[2],
            attempt_journal=tampered_attempts,
            exchange_fee_config_sha256=_COST_HASHES["exchange_fee"],
            spread_config_sha256=_COST_HASHES["spread"],
            slippage_config_sha256=_COST_HASHES["slippage"],
            market_impact_config_sha256=_COST_HASHES["market_impact"],
            latency_config_sha256=_COST_HASHES["latency"],
        )

    evidence = _reconcile(chain)
    payload = json.loads(evidence.to_json_bytes())
    duplicate = evidence.to_json_bytes().replace(
        b'{"attempt_count"',
        b'{"schema_version":2,"attempt_count"',
        1,
    )
    with pytest.raises(ValueError, match="unreadable"):
        PaperExecutionReconciliationEvidence.from_json_bytes(duplicate)

    payload["reconciliation_id"] = "0" * 64
    with pytest.raises(ValueError, match="ID does not match"):
        PaperExecutionReconciliationEvidence.from_json_bytes(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode() + b"\n"
        )
