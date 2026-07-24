from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from numbers import Real

from .execution_intent import TargetPositionIntent
from .portfolio_target_risk import (
    PaperPortfolioRiskSnapshot,
    PortfolioTargetRiskPolicy,
    TargetRiskDecision,
    evaluate_target_position_intents,
)

_SCHEMA_VERSION = 1


def _required_positive_real(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{field_name} must be a positive finite real number")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0.0:
        raise ValueError(f"{field_name} must be a positive finite real number")
    return parsed


def _required_utc_datetime(value: object, *, field_name: str) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field_name} must be a timezone-aware timestamp") from exc
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise ValueError(f"{field_name} must be a timezone-aware timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be a timezone-aware timestamp")
    return parsed.astimezone(UTC)


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class PortfolioFreshnessPolicy:
    """Maximum age accepted for persisted paper portfolio and mark evidence."""

    maximum_snapshot_age_seconds: float
    maximum_mark_age_seconds: float
    schema_version: int = field(default=_SCHEMA_VERSION, init=False)
    policy_id: str = field(init=False)

    def __post_init__(self) -> None:
        snapshot_age = _required_positive_real(
            self.maximum_snapshot_age_seconds,
            field_name="maximum_snapshot_age_seconds",
        )
        mark_age = _required_positive_real(
            self.maximum_mark_age_seconds,
            field_name="maximum_mark_age_seconds",
        )
        object.__setattr__(self, "maximum_snapshot_age_seconds", snapshot_age)
        object.__setattr__(self, "maximum_mark_age_seconds", mark_age)
        payload = {
            "schema_version": self.schema_version,
            "maximum_snapshot_age_seconds": snapshot_age,
            "maximum_mark_age_seconds": mark_age,
        }
        object.__setattr__(
            self,
            "policy_id",
            hashlib.sha256(_canonical_json_bytes(payload)).hexdigest(),
        )


@dataclass(frozen=True, slots=True)
class InstrumentMarkAge:
    instrument_id: str
    age_seconds: float


@dataclass(frozen=True, slots=True)
class FreshPortfolioTargetRiskDecision:
    """Risk result bound to the actual paper decision time and state freshness."""

    decision_id: str
    decision_at_utc: datetime
    portfolio_snapshot_age_seconds: float
    instrument_mark_ages: tuple[InstrumentMarkAge, ...]
    freshness_policy_id: str
    target_risk_decision_id: str
    allowed: bool
    blockers: tuple[str, ...]
    target_risk_decision: TargetRiskDecision = field(repr=False, compare=False)

    def assert_allowed(self) -> None:
        if not self.allowed:
            raise RuntimeError(
                "target-position intent batch rejected by fresh portfolio risk gate: "
                + ", ".join(self.blockers)
            )


def evaluate_fresh_target_position_intents(
    intents: tuple[TargetPositionIntent, ...],
    *,
    snapshot: PaperPortfolioRiskSnapshot,
    target_policy: PortfolioTargetRiskPolicy,
    freshness_policy: PortfolioFreshnessPolicy,
    decision_at_utc: datetime | str,
) -> FreshPortfolioTargetRiskDecision:
    """Evaluate targets only against state that is fresh at the actual decision time.

    Paper/live callers should use this boundary instead of directly invoking the lower-level
    target-risk evaluator. It adds no order connectivity and remains an offline decision.
    """

    decision_at = _required_utc_datetime(decision_at_utc, field_name="decision_at_utc")
    if snapshot.observed_at_utc > decision_at:
        raise ValueError("portfolio snapshot cannot be observed after the risk decision")

    for intent in intents:
        intent.assert_active_at(decision_at)

    portfolio_snapshot_age_seconds = (decision_at - snapshot.observed_at_utc).total_seconds()
    freshness_blockers: list[str] = []
    if portfolio_snapshot_age_seconds > freshness_policy.maximum_snapshot_age_seconds:
        freshness_blockers.append("stale_portfolio_snapshot")

    mark_ages: list[InstrumentMarkAge] = []
    for position in sorted(snapshot.positions, key=lambda value: value.instrument_id):
        if position.quantity <= 0.0:
            continue
        age_seconds = (decision_at - position.mark_observed_at_utc).total_seconds()
        if age_seconds < 0.0:
            raise ValueError("position mark cannot be observed after the risk decision")
        mark_ages.append(InstrumentMarkAge(position.instrument_id, age_seconds))
        if age_seconds > freshness_policy.maximum_mark_age_seconds:
            freshness_blockers.append(f"stale_position_mark:{position.instrument_id}")

    target_decision = evaluate_target_position_intents(
        intents,
        snapshot=snapshot,
        policy=target_policy,
    )
    blockers = tuple((*freshness_blockers, *target_decision.blockers))
    decision_id = hashlib.sha256(
        _canonical_json_bytes(
            {
                "schema_version": _SCHEMA_VERSION,
                "decision_at_utc": _format_utc(decision_at),
                "snapshot_id": snapshot.snapshot_id,
                "target_policy_id": target_policy.policy_id,
                "freshness_policy_id": freshness_policy.policy_id,
                "intent_ids": sorted(intent.intent_id for intent in intents),
                "target_risk_decision_id": target_decision.decision_id,
                "blockers": blockers,
            }
        )
    ).hexdigest()
    return FreshPortfolioTargetRiskDecision(
        decision_id=decision_id,
        decision_at_utc=decision_at,
        portfolio_snapshot_age_seconds=portfolio_snapshot_age_seconds,
        instrument_mark_ages=tuple(mark_ages),
        freshness_policy_id=freshness_policy.policy_id,
        target_risk_decision_id=target_decision.decision_id,
        allowed=not blockers,
        blockers=blockers,
        target_risk_decision=target_decision,
    )
