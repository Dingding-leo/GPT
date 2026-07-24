from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from gpt_quant.paper_execution_reconciliation import PaperExecutionReconciliationEvidence
from gpt_quant.paper_runtime_health import (
    PaperRuntimeHealthSnapshot,
    evaluate_paper_runtime_health,
)

_PUBLIC_OKX_1H_SOURCE_SHA256 = (
    "dcb30e58e10f8415aefe8c206f99c21fc8862b3b4f5ea65679a01262980c5481"
)
_PUBLIC_OKX_QUOTE_SHA256 = (
    "7d12a351f8f51320d1c8beee0063557e1c90388d66ac63412bf66ca544aeb3e3"
)
_PUBLIC_OKX_INSTRUMENT_SHA256 = (
    "290bd86ecbb1683351993197b0ec18001dfb604b9ba1cb864d9d6d327855f0eb"
)
_FEE_CONFIG = b'{"component":"exchange_fee","one_way_bps":"5","version":1}\n'


def _hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _reconciliation() -> PaperExecutionReconciliationEvidence:
    return PaperExecutionReconciliationEvidence(
        intent_journal_sha256=_PUBLIC_OKX_1H_SOURCE_SHA256,
        quote_store_sha256=_PUBLIC_OKX_QUOTE_SHA256,
        binding_journal_sha256=_PUBLIC_OKX_INSTRUMENT_SHA256,
        attempt_journal_sha256=_hash("paper-attempt-journal"),
        intent_count=1,
        quote_count=1,
        binding_count=1,
        attempt_count=1,
        exchange_fee_config_sha256=hashlib.sha256(_FEE_CONFIG).hexdigest(),
        spread_config_sha256=_hash("observed-spread-diagnostic"),
        slippage_config_sha256=_hash("observed-slippage-diagnostic"),
        market_impact_config_sha256=_hash("observed-market-impact-diagnostic"),
        latency_config_sha256=_hash("observed-latency-diagnostic"),
    )


def _healthy_snapshot(**overrides: object) -> PaperRuntimeHealthSnapshot:
    observed = datetime(2026, 7, 24, 6, 0, tzinfo=UTC)
    arguments: dict[str, object] = {
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
    arguments.update(overrides)
    return evaluate_paper_runtime_health(**arguments)  # type: ignore[arg-type]


def test_runtime_health_accepts_exact_operating_boundaries() -> None:
    snapshot = _healthy_snapshot()

    assert snapshot.runtime_healthy is True
    assert snapshot.status == "healthy"
    assert snapshot.blockers == ()
    assert snapshot.heartbeat_age_ms == 250
    assert snapshot.completed_bar_age_ms == 3_600_000
    assert snapshot.account_adapter_state == "disabled"
    assert snapshot.order_adapter_state == "disabled"
    assert PaperRuntimeHealthSnapshot.from_json_bytes(snapshot.to_json_bytes()) == snapshot


def test_runtime_health_fails_closed_one_microsecond_after_freshness_boundaries() -> None:
    observed = datetime(2026, 7, 24, 6, 0, tzinfo=UTC)
    snapshot = _healthy_snapshot(
        last_completed_bar_close_utc=observed
        - timedelta(hours=1, microseconds=1),
        last_heartbeat_utc=observed - timedelta(milliseconds=250, microseconds=1),
    )

    assert snapshot.heartbeat_age_ms == 251
    assert snapshot.completed_bar_age_ms == 3_600_001
    assert snapshot.runtime_healthy is False
    assert snapshot.blockers == ("heartbeat_stale", "completed_bar_stale")


def test_runtime_health_reports_lag_backpressure_and_unverified_reconciliation() -> None:
    snapshot = _healthy_snapshot(
        event_loop_lag_ms=101,
        queue_depth=10,
        reconciliation_verified=False,
    )

    assert snapshot.status == "blocked"
    assert snapshot.blockers == (
        "reconciliation_unverified",
        "event_loop_lag_exceeded",
        "queue_saturated",
    )


def test_runtime_health_requires_account_and_order_adapters_to_remain_disabled() -> None:
    snapshot = _healthy_snapshot(
        account_adapter_state="configured",
        order_adapter_state="enabled",
    )

    assert snapshot.runtime_healthy is False
    assert snapshot.blockers == (
        "account_adapter_not_disabled",
        "order_adapter_not_disabled",
    )


def test_runtime_health_rejects_future_or_inconsistent_evidence() -> None:
    observed = datetime(2026, 7, 24, 6, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="must not be in the future"):
        _healthy_snapshot(last_heartbeat_utc=observed + timedelta(microseconds=1))

    snapshot = _healthy_snapshot()
    payload = snapshot.to_dict()
    payload["heartbeat_age_ms"] = 249
    with pytest.raises(ValueError, match="does not match runtime timestamps"):
        PaperRuntimeHealthSnapshot.from_mapping(payload)


def test_runtime_health_rejects_forged_status_and_duplicate_fields() -> None:
    snapshot = _healthy_snapshot()
    forged = snapshot.to_dict()
    forged["status"] = "blocked"
    forged["blockers"] = ["heartbeat_stale"]
    with pytest.raises(ValueError, match="status does not match measured evidence"):
        PaperRuntimeHealthSnapshot.from_mapping(forged)

    serialized = snapshot.to_json_bytes().decode("utf-8")
    duplicate = serialized.replace(
        '"account_adapter_state":"disabled",',
        '"account_adapter_state":"disabled","account_adapter_state":"enabled",',
        1,
    )
    with pytest.raises(ValueError, match="duplicate field"):
        PaperRuntimeHealthSnapshot.from_json_bytes(duplicate)
