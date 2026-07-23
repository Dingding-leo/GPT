from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from gpt_quant.paper_execution_attempt import PaperExecutionAttempt

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_DOCUMENTATION = _REPOSITORY_ROOT / "docs" / "PAPER_EXECUTION_ATTEMPT.md"


def _run_example() -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, "examples/paper_execution_attempt_replay.py"],
        cwd=_REPOSITORY_ROOT,
        check=True,
        capture_output=True,
    )
    assert completed.stderr == b""
    return json.loads(completed.stdout)


def test_example_replays_one_canonical_non_order_attempt() -> None:
    first = _run_example()
    second = _run_example()

    assert second == first
    assert first["account_connectivity"] == "disabled"
    assert first["order_submission"] == "not_performed"
    assert first["persistence_status"] == "not_implemented"
    assert first["intent_active_at_submission"] is True

    attempt = PaperExecutionAttempt.from_mapping(first["attempt"])
    assert attempt.outcome == "filled"
    assert attempt.side == "buy"
    assert attempt.requested_base_quantity == "0.1"
    assert attempt.filled_base_quantity == "0.1"
    assert attempt.average_fill_price == attempt.reference_ask_price
    assert attempt.submitted_at_utc == datetime(
        2026, 7, 21, 0, 0, 0, 450_000, tzinfo=UTC
    )
    assert attempt.outcome_at_utc == datetime(2026, 7, 21, 0, 0, 0, 500_000, tzinfo=UTC)
    assert attempt.decision_to_submission_latency_us == 50_000
    assert attempt.quote_observed_to_submission_latency_us == 150_000
    assert attempt.quote_received_to_submission_latency_us == 100_000
    assert attempt.submission_to_outcome_latency_us == 50_000

    costs = first["cost_boundary"]
    assert costs["exchange_fee_baseline_bps_one_way"] == 5
    assert costs["slippage_bps"] == "not_modeled"
    assert costs["market_impact_bps"] == "not_modeled"
    assert costs["all_in_fixed_path_sensitivity_bps"] == [7.5, 10, 15]


def test_documentation_matches_current_paper_attempt_boundary() -> None:
    documentation = _DOCUMENTATION.read_text(encoding="utf-8")

    assert "python examples/paper_execution_attempt_replay.py" in documentation
    assert "intent.assert_active_at(submitted_at_utc)" in documentation
    assert "record_paper_execution_attempt()" in documentation
    assert "PaperExecutionAttempt.from_json_bytes()" in documentation
    assert "PaperExecutionAttempt.assert_reconstructs()" in documentation
    assert "market-vwap-at-touch-or-worse" in documentation
    assert "not durable broker state" in documentation
    assert "5 bps one-way exchange fee" in documentation
    assert "Spread, slippage, market impact, and latency" in documentation
    assert "7.5/10/15 bps" in documentation
