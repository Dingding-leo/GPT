from __future__ import annotations

import json
from datetime import UTC, datetime

from gpt_quant.execution_intent import TargetPositionIntent
from gpt_quant.execution_quote import ExecutionQuoteSnapshot
from gpt_quant.execution_quote_binding import bind_execution_quote
from gpt_quant.paper_execution_attempt import (
    PaperExecutionAttempt,
    record_paper_execution_attempt,
)

_STRATEGY_REVISION = "49a4eefa9e6d349237832d75f9c1c96070c6799c"
_SOURCE_DATA_SHA256 = "429abcbe5deb56ad6c7e1790cea101644a9fedd622f40de64eec5fd1ac3c4187"
_CONFIG_SHA256 = "6b06037376bce5df483311704f7b701c5e03a2a2735b2dd3361036fccd94da1a"
_STRUCTURAL_QUOTE_SHA256 = (
    "dcb30e58e10f8415aefe8c206f99c21fc8862b3b4f5ea65679a01262980c5481"
)
_STRUCTURAL_INSTRUMENT_SHA256 = (
    "fa567055978b3974e728664af9e90f52dbedf1ee6864a1cdd4cb6f6a462de521"
)


def build_example() -> dict[str, object]:
    intent = TargetPositionIntent(
        instrument_id="BTC-USDT",
        bar="1Dutc",
        strategy_id="canonical-five-bps",
        strategy_revision=_STRATEGY_REVISION,
        source_data_sha256=_SOURCE_DATA_SHA256,
        config_sha256=_CONFIG_SHA256,
        signal_bar_open_utc=datetime(2026, 7, 20, tzinfo=UTC),
        signal_bar_close_utc=datetime(2026, 7, 21, tzinfo=UTC),
        decision_not_before_utc=datetime(2026, 7, 21, 0, 0, 0, 200_000, tzinfo=UTC),
        expires_at_utc=datetime(2026, 7, 22, tzinfo=UTC),
        target_position=0.25,
        minimum_position=0.0,
        maximum_position=1.0,
    )
    quote = ExecutionQuoteSnapshot(
        provider="okx",
        instrument_id="BTC-USDT",
        observed_at_utc=datetime(2026, 7, 21, 0, 0, 0, 300_000, tzinfo=UTC),
        received_at_utc=datetime(2026, 7, 21, 0, 0, 0, 350_000, tzinfo=UTC),
        bid_price="66113.8",
        bid_quantity="0.42",
        ask_price="66114",
        ask_quantity="0.37",
        source_response_sha256=_STRUCTURAL_QUOTE_SHA256,
        instrument_snapshot_sha256=_STRUCTURAL_INSTRUMENT_SHA256,
    )
    decision_at_utc = datetime(2026, 7, 21, 0, 0, 0, 400_000, tzinfo=UTC)
    submitted_at_utc = datetime(2026, 7, 21, 0, 0, 0, 450_000, tzinfo=UTC)
    outcome_at_utc = datetime(2026, 7, 21, 0, 0, 0, 500_000, tzinfo=UTC)

    binding = bind_execution_quote(
        intent,
        quote,
        decision_at_utc=decision_at_utc,
        maximum_age_ms=250,
    )

    # Current main does not pass the intent into record_paper_execution_attempt().
    # The caller must therefore re-check the half-open intent lifetime at submission.
    intent.assert_active_at(submitted_at_utc)

    attempt = record_paper_execution_attempt(
        binding,
        quote,
        submitted_at_utc=submitted_at_utc,
        outcome_at_utc=outcome_at_utc,
        side="buy",
        requested_base_quantity="0.1",
        outcome="filled",
        filled_base_quantity="0.1",
        average_fill_price=quote.ask_price,
        reason_code="paper-touch-fill",
    )
    replayed = PaperExecutionAttempt.from_json_bytes(attempt.to_json_bytes())
    replayed.assert_reconstructs(intent, binding, quote)
    if replayed != attempt:
        raise ValueError("paper execution attempt replay mismatch")

    return {
        "account_connectivity": "disabled",
        "order_submission": "not_performed",
        "persistence_status": "not_implemented",
        "provenance_status": "structural_only_not_exchange_fill_evidence",
        "intent_active_at_submission": True,
        "intent_id": intent.intent_id,
        "binding_id": binding.binding_id,
        "quote_snapshot_id": quote.snapshot_id,
        "attempt": attempt.to_dict(),
        "cost_boundary": {
            "exchange_fee_baseline_bps_one_way": 5,
            "observed_spread_bps": format(quote.spread_bps, "f"),
            "slippage_bps": "not_modeled",
            "market_impact_bps": "not_modeled",
            "latency": "measured_as_timestamps_not_priced",
            "all_in_fixed_path_sensitivity_bps": [7.5, 10, 15],
        },
    }


def main() -> None:
    print(
        json.dumps(
            build_example(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
