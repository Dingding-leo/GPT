from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from gpt_quant.paper_execution_reconciliation import PaperExecutionReconciliationEvidence
from gpt_quant.paper_runtime_health import (
    PaperRuntimeHealthSnapshot,
    evaluate_paper_runtime_health,
)

_FEE_CONFIG = b'{"component":"exchange_fee","one_way_bps":"5","version":1}\n'


def _hash(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _reconciliation() -> PaperExecutionReconciliationEvidence:
    return PaperExecutionReconciliationEvidence(
        intent_journal_sha256=_hash("intent"),
        quote_store_sha256=_hash("quote"),
        binding_journal_sha256=_hash("binding"),
        attempt_journal_sha256=_hash("attempt"),
        intent_count=1,
        quote_count=1,
        binding_count=1,
        attempt_count=1,
        exchange_fee_config_sha256=hashlib.sha256(_FEE_CONFIG).hexdigest(),
        spread_config_sha256=_hash("spread-diagnostic"),
        slippage_config_sha256=_hash("slippage-diagnostic"),
        market_impact_config_sha256=_hash("impact-diagnostic"),
        latency_config_sha256=_hash("latency-diagnostic"),
    )


def _snapshot(**overrides: object) -> PaperRuntimeHealthSnapshot:
    observed = datetime(2026, 7, 24, 6, tzinfo=UTC)
    values: dict[str, object] = {
        "observed_at_utc": observed,
        "last_completed_bar_close_utc": observed - timedelta(hours=1),
        "last_heartbeat_utc": observed - timedelta(milliseconds=250),
        "event_loop_lag_ms": 100,
        "queue_depth": 9,
        "queue_capacity": 10,
        "maximum_heartbeat_age_ms": 250,
        "maximum_completed_bar_age_ms": 3_600_000,
        "maximum_event_loop_lag_ms": 100,
        "reconciliation": _reconciliation(),
        "reconciliation_verified": True,
    }
    values.update(overrides)
    return evaluate_paper_runtime_health(**values)  # type: ignore[arg-type]


def test_health_accepts_exact_boundaries_and_round_trips() -> None:
    snapshot = _snapshot()

    assert snapshot.runtime_healthy
    assert snapshot.blockers == ()
    assert snapshot.heartbeat_age_ms == 250
    assert snapshot.completed_bar_age_ms == 3_600_000
    assert snapshot.account_adapter_state == "disabled"
    assert snapshot.order_adapter_state == "disabled"
    assert PaperRuntimeHealthSnapshot.from_json_bytes(snapshot.to_json_bytes()) == snapshot


def test_health_fails_one_microsecond_after_freshness_boundaries() -> None:
    observed = datetime(2026, 7, 24, 6, tzinfo=UTC)
    snapshot = _snapshot(
        last_heartbeat_utc=observed - timedelta(milliseconds=250, microseconds=1),
        last_completed_bar_close_utc=observed - timedelta(hours=1, microseconds=1),
    )

    assert snapshot.heartbeat_age_ms == 251
    assert snapshot.completed_bar_age_ms == 3_600_001
    assert snapshot.blockers == ("heartbeat_stale", "completed_bar_stale")


def test_health_reports_reconciliation_lag_backpressure_and_adapters() -> None:
    snapshot = _snapshot(
        reconciliation_verified=False,
        event_loop_lag_ms=101,
        queue_depth=10,
        account_adapter_state="configured",
        order_adapter_state="enabled",
    )

    assert snapshot.status == "blocked"
    assert snapshot.blockers == (
        "reconciliation_unverified",
        "event_loop_lag_exceeded",
        "queue_saturated",
        "account_adapter_not_disabled",
        "order_adapter_not_disabled",
    )


def test_health_rejects_future_and_forged_evidence() -> None:
    observed = datetime(2026, 7, 24, 6, tzinfo=UTC)
    with pytest.raises(ValueError, match="must not be in the future"):
        _snapshot(last_heartbeat_utc=observed + timedelta(microseconds=1))

    snapshot = _snapshot()
    payload = json.loads(snapshot.to_json_bytes())
    payload["status"] = "blocked"
    forged = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    with pytest.raises(ValueError, match="does not match measured evidence"):
        PaperRuntimeHealthSnapshot.from_json_bytes(forged)


def test_health_rejects_duplicate_fields() -> None:
    serialized = _snapshot().to_json_bytes().decode()
    duplicate = serialized.replace(
        '"account_adapter_state":"disabled",',
        '"account_adapter_state":"disabled","account_adapter_state":"enabled",',
        1,
    ).encode()
    with pytest.raises(ValueError, match="JSON is unreadable"):
        PaperRuntimeHealthSnapshot.from_json_bytes(duplicate)
