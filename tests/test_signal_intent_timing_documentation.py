from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from gpt_quant.execution_intent import TargetPositionIntent
from gpt_quant.execution_quote import ExecutionQuoteSnapshot
from gpt_quant.execution_quote_binding import ExecutionQuoteBinding, bind_execution_quote
from gpt_quant.execution_quote_evidence import load_execution_quote_evidence_store
from gpt_quant.okx_live_response_evidence import read_okx_live_timing_response_evidence

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_DOCUMENTATION = _REPOSITORY_ROOT / "docs" / "SIGNAL_INTENT_TIMING.md"


def _run_example(output_dir: Path) -> dict[str, object]:
    completed = subprocess.run(
        [
            sys.executable,
            "examples/signal_intent_timing.py",
            "--output-dir",
            str(output_dir),
        ],
        cwd=_REPOSITORY_ROOT,
        check=True,
        capture_output=True,
    )
    assert completed.stderr == b""
    return json.loads(completed.stdout)


def test_documented_okx_timing_example_executes_persists_and_replays(tmp_path) -> None:
    output_dir = tmp_path / "timing"
    first = _run_example(output_dir)
    second = _run_example(output_dir)

    assert second == first
    assert first["paper_decision_status"] == "not_implemented"
    assert first["order_status"] == "not_implemented"
    evidence_path = Path(first["timing_evidence_path"])
    evidence = read_okx_live_timing_response_evidence(
        evidence_path,
        expected_sha256=str(first["timing_evidence_sha256"]),
    )
    assert evidence["provider"] == "OKX"
    assert evidence["source_url"] == "https://www.okx.com/api/v5/public/time"
    assert evidence["bar_open_utc"] == "2026-07-20T00:00:00+00:00"
    assert evidence["bar_close_utc"] == "2026-07-21T00:00:00+00:00"
    assert evidence["candle_observed_at_utc"] == "2026-07-21T11:59:59+00:00"
    assert evidence["exchange_server_time_utc"] == "2026-07-21T12:00:00.100000+00:00"
    assert evidence["server_time_response_received_utc"] == ("2026-07-21T12:00:00.200000+00:00")
    assert evidence["signal_not_before_utc"] == "2026-07-21T12:00:00.200000+00:00"
    assert evidence["availability_delay_seconds"] == pytest.approx(43200.1)
    assert evidence["server_round_trip_seconds"] == pytest.approx(0.2)
    assert evidence["midpoint_clock_skew_seconds"] == pytest.approx(0.0)

    observation_times = [
        pd.Timestamp(evidence["candle_observed_at_utc"]),
        pd.Timestamp(evidence["exchange_server_time_utc"]),
        pd.Timestamp(evidence["server_time_response_received_utc"]),
    ]
    assert pd.Timestamp(evidence["signal_not_before_utc"]) == max(observation_times)

    intent = TargetPositionIntent.from_mapping(first["intent"])
    assert intent.strategy_revision == "a2b3e61a0591121346a6d29f1ddd3ad805aba68d"
    assert intent.signal_bar_open_utc == datetime(2026, 7, 20, tzinfo=UTC)
    assert intent.signal_bar_close_utc == datetime(2026, 7, 21, tzinfo=UTC)
    assert intent.decision_not_before_utc == datetime(2026, 7, 21, 12, 0, 0, 200000, tzinfo=UTC)
    assert intent.expires_at_utc == datetime(2026, 7, 22, tzinfo=UTC)
    intent.assert_active_at(intent.decision_not_before_utc)
    with pytest.raises(ValueError, match="expired"):
        intent.assert_active_at(intent.expires_at_utc)

    quote_summary = first["execution_quote"]
    assert quote_summary["provenance_status"] == "structural_only_no_public_quote_producer"
    assert quote_summary["midpoint"] == "66113.8"
    assert Decimal(quote_summary["observed_spread_bps"]) == (
        Decimal("0.2") / Decimal("66113.8") * Decimal(10_000)
    )
    quote = ExecutionQuoteSnapshot.from_mapping(quote_summary["snapshot"])

    quote_store_summary = first["execution_quote_store"]
    quote_store = load_execution_quote_evidence_store(quote_store_summary["path"])
    assert quote_store.count == 1
    assert quote_store.sha256 == quote_store_summary["sha256"]
    assert quote_store.snapshots == (quote,)

    binding = ExecutionQuoteBinding.from_mapping(first["execution_quote_binding"])
    assert binding.target_intent_id == intent.intent_id
    assert binding.quote_snapshot_id == quote.snapshot_id
    assert binding.decision_at_utc == datetime(2026, 7, 21, 12, 0, 0, 400000, tzinfo=UTC)
    assert binding.maximum_age_ms == 200
    assert binding.instrument_snapshot_sha256 == quote.instrument_snapshot_sha256
    assert Decimal(binding.observed_spread_bps) == Decimal(quote_summary["observed_spread_bps"])
    assert ExecutionQuoteBinding.from_json_bytes(binding.to_json_bytes()) == binding
    binding.assert_reconstructs(intent, quote)

    with pytest.raises(ValueError, match="stale"):
        bind_execution_quote(
            intent,
            quote,
            decision_at_utc=datetime(2026, 7, 21, 12, 0, 0, 501_000, tzinfo=UTC),
            maximum_age_ms=200,
        )


def test_signal_intent_timing_documentation_matches_implemented_boundary() -> None:
    documentation = _DOCUMENTATION.read_text(encoding="utf-8")

    assert "python examples/signal_intent_timing.py" in documentation
    assert "write_okx_live_timing_response_evidence()" in documentation
    assert "record_execution_quote_evidence()" in documentation
    assert "load_execution_quote_evidence_store()" in documentation
    assert "bind_execution_quote()" in documentation
    assert "ExecutionQuoteBinding.from_json_bytes()" in documentation
    assert "ExecutionQuoteBinding.assert_reconstructs()" in documentation
    assert "signal_not_before_utc = max(" in documentation
    assert "[decision_not_before_utc, expires_at_utc)" in documentation
    assert "quote_received_at_utc < decision_at_utc" in documentation
    assert "decision_at_utc - quote_observed_at_utc <= maximum_age_ms" in documentation
    assert "binding_id" in documentation
    assert "Intent translation first permitted" in documentation
    assert "Quote binding decision timestamp" in documentation
    assert "is not an order timestamp" in documentation
    assert "availability_delay_seconds" in documentation
    assert "It is **not** network latency" in documentation
    assert "structural quote bytes are not a captured OKX top-of-book response" in documentation
    assert "5 bps one-way exchange fee" in documentation
    assert "Spread, slippage, market impact, and latency remain separate" in documentation
    assert "does not persist the binding" in documentation
    assert "mode `0700`" in documentation
    assert "mode `0600`" in documentation
