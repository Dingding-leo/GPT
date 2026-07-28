from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

_EXPECTED_CONTRACT_JSON = r'''
{
  "schema_version": 1,
  "mode": "shadow_paper_only",
  "bar": "1H",
  "strategy_boundary": {
    "causal_time_series_only": true,
    "per_instrument_rule_required": true,
    "allowed_inputs": [
      "target_instrument_lagged_history",
      "frozen_lagged_exogenous_market_time_series"
    ],
    "forbidden_methods": [
      "cross_sectional_ranking",
      "contemporaneous_asset_selection",
      "top_n_rotation",
      "pairs_or_spread_trading",
      "cointegration_or_statistical_arbitrage",
      "market_neutral_long_short",
      "post_hoc_asset_filtering"
    ],
    "multiple_assets_use": "independent_replication_under_identical_frozen_rule"
  },
  "observation": {
    "minimum_elapsed_hours": 720,
    "minimum_completed_decision_cycles": 720,
    "minimum_nonzero_target_changes": 20,
    "maximum_collection_hours_before_insufficient_activity": 2160
  },
  "public_data": {
    "public_unauthenticated_only": true,
    "confirmed_bars_only": true,
    "minimum_completeness_ratio": 0.995,
    "maximum_consecutive_missing_bars": 1,
    "stale_after_seconds": 5400,
    "immutable_raw_bytes_required": true,
    "source_and_config_hashes_required": true
  },
  "runtime": {
    "deterministic_schedule_required": true,
    "heartbeat_interval_seconds": 60,
    "maximum_heartbeat_gap_seconds": 180,
    "bounded_queue_capacity": 256,
    "maximum_dropped_events": 0,
    "maximum_unreconciled_events": 0,
    "maximum_p99_decision_persist_latency_ms": 2000,
    "graceful_shutdown_required": true,
    "restart_handoff_required": true,
    "idempotent_event_processing_required": true
  },
  "required_failure_drills": {
    "restart_stages": [
      "before_decision_persist",
      "after_decision_before_execution_attempt",
      "after_execution_attempt_before_reconciliation"
    ],
    "stale_data_halt_count": 1,
    "duplicate_delivery_count": 1,
    "queue_saturation_count": 1,
    "graceful_shutdown_restart_count": 1,
    "zero_duplicate_decisions_required": true,
    "zero_duplicate_fills_required": true,
    "zero_reconciliation_drift_required": true
  },
  "execution_diagnostics": {
    "required_outcome_categories": [
      "rejected",
      "expired",
      "no_fill",
      "partial_fill",
      "filled"
    ],
    "natural_outcome_minimum_counts": 0,
    "complete_submission_to_exclusive_expiry_coverage_required": true,
    "touch_is_fill": false,
    "incomplete_public_coverage_may_authorize_terminal_outcome": false
  },
  "risk": {
    "stale_data_halt_required": true,
    "loss_drawdown_turnover_latches_required": true,
    "policy_identity_immutable": true,
    "kill_switch_breach_must_abort_collection": true,
    "zero_reconciliation_drift_required": true
  },
  "economics": {
    "exchange_fee_one_way_bps": 5.0,
    "fee_applied_to": "filled_notional",
    "separate_diagnostics": [
      "spread",
      "slippage",
      "impact",
      "latency",
      "no_fill",
      "partial_fill",
      "adverse_selection"
    ]
  },
  "required_evidence": {
    "strategy_id": true,
    "strategy_revision": true,
    "source_data_sha256": true,
    "config_sha256": true,
    "event_chain_root_sha256": true,
    "decision_count": true,
    "execution_attempt_count": true,
    "outcome_counts": true,
    "heartbeat_summary": true,
    "latency_summary": true,
    "restart_drill_results": true,
    "risk_latch_summary": true,
    "reconciliation_summary": true
  },
  "classification": {
    "allowed_statuses": [
      "collecting",
      "operational_pass",
      "operational_fail",
      "insufficient_activity",
      "aborted"
    ],
    "operational_pass_may_imply_live_ready": false,
    "limited_capital_authorization": false,
    "human_approval_required_for_any_live_stage": true
  },
  "forbidden_capabilities": {
    "credentials": true,
    "private_endpoints": true,
    "accounts": true,
    "balances": true,
    "order_submission": true,
    "enabled_adapters": true,
    "leverage_or_fund_movement": true,
    "synthetic_price_performance_evidence": true,
    "fifteen_minute_mode": true
  }
}
'''


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"shadow-paper acceptance JSON contains duplicate field {key}")
        result[key] = value
    return result


_EXPECTED_CONTRACT: dict[str, Any] = json.loads(
    _EXPECTED_CONTRACT_JSON,
    object_pairs_hook=_object_pairs,
)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _validate_exact(actual: object, expected: object, path: str) -> None:
    if isinstance(expected, Mapping):
        if not isinstance(actual, Mapping):
            raise ValueError(f"{path} must be an object")
        actual_keys = set(actual)
        expected_keys = set(expected)
        missing = sorted(expected_keys - actual_keys)
        unknown = sorted(actual_keys - expected_keys)
        if missing:
            raise ValueError(f"{path} is missing required fields: {', '.join(missing)}")
        if unknown:
            raise ValueError(f"{path} contains unknown fields: {', '.join(unknown)}")
        for key, expected_value in expected.items():
            _validate_exact(actual[key], expected_value, f"{path}.{key}")
        return

    if isinstance(expected, list):
        if not isinstance(actual, list):
            raise ValueError(f"{path} must be an array")
        if len(actual) != len(expected):
            raise ValueError(f"{path} must contain exactly {len(expected)} items")
        for index, (actual_value, expected_value) in enumerate(zip(actual, expected, strict=True)):
            _validate_exact(actual_value, expected_value, f"{path}[{index}]")
        return

    if type(actual) is not type(expected) or actual != expected:
        raise ValueError(f"{path} must remain exactly {expected!r}")


def expected_shadow_paper_acceptance_contract() -> dict[str, Any]:
    """Return a defensive copy of the immutable shadow-paper acceptance contract."""

    return deepcopy(_EXPECTED_CONTRACT)


def validate_shadow_paper_acceptance_contract(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Fail closed unless payload exactly preserves the predeclared contract."""

    _validate_exact(payload, _EXPECTED_CONTRACT, "contract")
    return deepcopy(dict(payload))


def load_shadow_paper_acceptance_contract(path: str | Path) -> tuple[dict[str, Any], str]:
    """Load, validate, and hash one stable regular-file acceptance contract."""

    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"acceptance contract is missing or not a regular file: {source}")
    before = source.read_bytes()
    try:
        payload = json.loads(before.decode("utf-8"), object_pairs_hook=_object_pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"acceptance contract is not valid UTF-8 JSON: {source}") from exc
    if not isinstance(payload, dict):
        raise ValueError("acceptance contract must be a JSON object")
    if before != source.read_bytes():
        raise ValueError(f"acceptance contract changed during read: {source}")
    return validate_shadow_paper_acceptance_contract(payload), _sha256(before)


def build_shadow_paper_acceptance_evidence(path: str | Path) -> dict[str, Any]:
    """Build deterministic evidence that the runtime contract remains fail closed."""

    contract, contract_sha256 = load_shadow_paper_acceptance_contract(path)
    forbidden = sorted(
        key for key, prohibited in contract["forbidden_capabilities"].items() if prohibited
    )
    return {
        "bar": contract["bar"],
        "contract_schema_version": contract["schema_version"],
        "contract_sha256": contract_sha256,
        "forbidden_capabilities": forbidden,
        "limited_capital_authorization": False,
        "live_ready": False,
        "mode": contract["mode"],
        "operational_pass_may_imply_live_ready": False,
        "schema_version": 1,
        "status": "pass",
        "strategy_boundary": "causal_time_series_per_instrument_only",
    }


def write_shadow_paper_acceptance_evidence(
    payload: Mapping[str, Any],
    path: str | Path,
) -> str:
    """Write canonical acceptance evidence and return its SHA-256 digest."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        + b"\n"
    )
    destination.write_bytes(encoded)
    return _sha256(encoded)
