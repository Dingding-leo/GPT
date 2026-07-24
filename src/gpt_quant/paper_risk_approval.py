from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from numbers import Real

from .paper_risk_kill_switch import (
    PaperRiskKillSwitchDecision,
    PaperRiskKillSwitchPolicy,
    PaperRiskStateSnapshot,
    ProposedInstrumentExposure,
    evaluate_paper_risk_kill_switch,
)

__all__ = [
    "PaperRiskApproval",
    "RiskApprovedExposure",
    "create_paper_risk_approval",
    "verify_paper_risk_approval",
]

_SCHEMA_VERSION = 1
_SHA256 = re.compile(r"[0-9a-f]{64}")
_ERROR = "paper risk approval"
_FIELDS = {
    "schema_version",
    "target_intent_id",
    "evaluated_at_utc",
    "snapshot_id",
    "policy_id",
    "risk_decision_id",
    "proposed_exposures",
}
_SERIALIZED_FIELDS = _FIELDS | {"approval_id"}


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"{name} must be a non-empty trimmed string")
    if any(ord(character) < 32 for character in value):
        raise ValueError(f"{name} must not contain control characters")
    return value


def _digest(value: object, name: str) -> str:
    parsed = _text(value, name)
    if _SHA256.fullmatch(parsed) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return parsed


def _utc(value: object, name: str) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{name} must be a timezone-aware timestamp") from exc
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise ValueError(f"{name} must be a timezone-aware timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware timestamp")
    return parsed.astimezone(UTC)


def _fraction(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite fraction from zero to one")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0.0 or parsed > 1.0:
        raise ValueError(f"{name} must be a finite fraction from zero to one")
    return 0.0 if parsed == 0.0 else parsed


def _format_utc(value: datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _json_bytes(payload: Mapping[str, object]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"{_ERROR} JSON contains duplicate field {key!r}")
        result[key] = value
    return result


@dataclass(frozen=True, slots=True)
class RiskApprovedExposure:
    instrument_id: str
    proposed_exposure: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "instrument_id", _text(self.instrument_id, "instrument_id"))
        object.__setattr__(
            self,
            "proposed_exposure",
            _fraction(self.proposed_exposure, "proposed_exposure"),
        )

    def to_proposal(self) -> ProposedInstrumentExposure:
        return ProposedInstrumentExposure(self.instrument_id, self.proposed_exposure)


@dataclass(frozen=True, slots=True)
class PaperRiskApproval:
    """Content-addressed approval that must replay against exact risk inputs."""

    target_intent_id: str
    evaluated_at_utc: datetime
    snapshot_id: str
    policy_id: str
    risk_decision_id: str
    proposed_exposures: tuple[RiskApprovedExposure, ...]
    schema_version: int = field(default=_SCHEMA_VERSION, init=False)
    approval_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "target_intent_id",
            _digest(self.target_intent_id, "target_intent_id"),
        )
        object.__setattr__(
            self,
            "evaluated_at_utc",
            _utc(self.evaluated_at_utc, "evaluated_at_utc"),
        )
        for name in ("snapshot_id", "policy_id", "risk_decision_id"):
            object.__setattr__(self, name, _digest(getattr(self, name), name))

        exposures = tuple(sorted(self.proposed_exposures, key=lambda item: item.instrument_id))
        if not exposures:
            raise ValueError(f"{_ERROR} requires at least one proposed exposure")
        instrument_ids = [item.instrument_id for item in exposures]
        if len(set(instrument_ids)) != len(instrument_ids):
            raise ValueError(f"{_ERROR} contains duplicate instruments")
        object.__setattr__(self, "proposed_exposures", exposures)
        object.__setattr__(
            self,
            "approval_id",
            hashlib.sha256(_json_bytes(self._payload())).hexdigest(),
        )

    def _payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "target_intent_id": self.target_intent_id,
            "evaluated_at_utc": _format_utc(self.evaluated_at_utc),
            "snapshot_id": self.snapshot_id,
            "policy_id": self.policy_id,
            "risk_decision_id": self.risk_decision_id,
            "proposed_exposures": [
                {
                    "instrument_id": item.instrument_id,
                    "proposed_exposure": item.proposed_exposure,
                }
                for item in self.proposed_exposures
            ],
        }

    def to_json_bytes(self) -> bytes:
        return _json_bytes({**self._payload(), "approval_id": self.approval_id}) + b"\n"

    @classmethod
    def from_json_bytes(cls, value: bytes) -> PaperRiskApproval:
        try:
            payload = json.loads(value.decode("utf-8"), object_pairs_hook=_reject_duplicates)
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValueError(f"{_ERROR} JSON is unreadable") from exc
        if not isinstance(payload, Mapping) or set(payload) != _SERIALIZED_FIELDS:
            raise ValueError(f"{_ERROR} fields do not match schema")
        if payload["schema_version"] != _SCHEMA_VERSION:
            raise ValueError(f"unsupported {_ERROR} schema")
        raw_exposures = payload["proposed_exposures"]
        if not isinstance(raw_exposures, list):
            raise ValueError(f"{_ERROR} proposed exposures must be a list")
        exposures: list[RiskApprovedExposure] = []
        for item in raw_exposures:
            if not isinstance(item, Mapping) or set(item) != {
                "instrument_id",
                "proposed_exposure",
            }:
                raise ValueError(f"{_ERROR} exposure fields do not match schema")
            exposures.append(
                RiskApprovedExposure(
                    instrument_id=item["instrument_id"],
                    proposed_exposure=item["proposed_exposure"],
                )
            )
        approval = cls(
            target_intent_id=payload["target_intent_id"],
            evaluated_at_utc=payload["evaluated_at_utc"],
            snapshot_id=payload["snapshot_id"],
            policy_id=payload["policy_id"],
            risk_decision_id=payload["risk_decision_id"],
            proposed_exposures=tuple(exposures),
        )
        if payload["approval_id"] != approval.approval_id:
            raise ValueError(f"{_ERROR} ID does not match its payload")
        if approval.to_json_bytes() != value:
            raise ValueError(f"{_ERROR} JSON must use canonical encoding")
        return approval


def create_paper_risk_approval(
    target_intent_id: str,
    proposed_exposures: tuple[ProposedInstrumentExposure, ...],
    *,
    snapshot: PaperRiskStateSnapshot,
    policy: PaperRiskKillSwitchPolicy,
    evaluated_at_utc: datetime | str,
) -> PaperRiskApproval:
    """Mint an approval only after the exact fail-closed risk evaluation allows it."""

    decision = evaluate_paper_risk_kill_switch(
        proposed_exposures,
        snapshot=snapshot,
        policy=policy,
        evaluated_at_utc=evaluated_at_utc,
    )
    decision.assert_allowed()
    approval = PaperRiskApproval(
        target_intent_id=target_intent_id,
        evaluated_at_utc=decision.evaluated_at_utc,
        snapshot_id=decision.snapshot_id,
        policy_id=decision.policy_id,
        risk_decision_id=decision.decision_id,
        proposed_exposures=tuple(
            RiskApprovedExposure(item.instrument_id, item.proposed_exposure)
            for item in proposed_exposures
        ),
    )
    verify_paper_risk_approval(approval, snapshot=snapshot, policy=policy)
    return approval


def verify_paper_risk_approval(
    approval: PaperRiskApproval,
    *,
    snapshot: PaperRiskStateSnapshot,
    policy: PaperRiskKillSwitchPolicy,
) -> PaperRiskKillSwitchDecision:
    """Re-evaluate exact persisted inputs instead of trusting an approval-shaped object."""

    if not isinstance(approval, PaperRiskApproval):
        raise TypeError("approval must be a PaperRiskApproval")
    if snapshot.snapshot_id != approval.snapshot_id:
        raise ValueError(f"{_ERROR} snapshot does not match persisted approval")
    if policy.policy_id != approval.policy_id:
        raise ValueError(f"{_ERROR} policy does not match persisted approval")
    decision = evaluate_paper_risk_kill_switch(
        tuple(item.to_proposal() for item in approval.proposed_exposures),
        snapshot=snapshot,
        policy=policy,
        evaluated_at_utc=approval.evaluated_at_utc,
    )
    decision.assert_allowed()
    if decision.decision_id != approval.risk_decision_id:
        raise ValueError(f"{_ERROR} decision does not reconstruct from exact inputs")
    return decision
