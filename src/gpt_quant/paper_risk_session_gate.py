from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from numbers import Real
from typing import Literal

from .paper_risk_kill_switch import (
    PaperRiskKillSwitchDecision,
    PaperRiskKillSwitchPolicy,
    PaperRiskStateSnapshot,
    ProposedInstrumentExposure,
    evaluate_paper_risk_kill_switch,
)

_SCHEMA_VERSION = 1
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_TRIGGER_ORDER = (
    "stale_portfolio_state",
    "stale_market_data",
    "daily_loss_limit",
    "drawdown_limit",
    "abnormal_turnover_limit",
)
_LATCH_FIELDS = frozenset(
    {
        "schema_version",
        "session_start_utc",
        "latest_observed_at_utc",
        "latest_snapshot_id",
        "latest_portfolio_state_sha256",
        "maximum_daily_loss_fraction",
        "maximum_drawdown_fraction",
        "previous_latch_id",
        "latch_id",
    }
)


def _nonnegative_fraction(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{field_name} must be a finite fraction in [0, 1]")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0.0 or parsed > 1.0:
        raise ValueError(f"{field_name} must be a finite fraction in [0, 1]")
    return 0.0 if parsed == 0.0 else parsed


def _required_hash(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _optional_hash(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    return _required_hash(value, field_name=field_name)


def _utc_datetime(value: object, *, field_name: str) -> datetime:
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


def _reject_duplicate_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


@dataclass(frozen=True, slots=True)
class PaperRiskSessionLatch:
    """Content-addressed session maxima that keep loss and drawdown stops latched."""

    session_start_utc: datetime
    latest_observed_at_utc: datetime
    latest_snapshot_id: str
    latest_portfolio_state_sha256: str
    maximum_daily_loss_fraction: float
    maximum_drawdown_fraction: float
    previous_latch_id: str | None = None
    schema_version: int = field(default=_SCHEMA_VERSION, init=False)
    latch_id: str = field(init=False)

    def __post_init__(self) -> None:
        session_start = _utc_datetime(self.session_start_utc, field_name="session_start_utc")
        latest_observed_at = _utc_datetime(
            self.latest_observed_at_utc,
            field_name="latest_observed_at_utc",
        )
        if latest_observed_at < session_start:
            raise ValueError("latest_observed_at_utc cannot be before session_start_utc")
        latest_snapshot_id = _required_hash(
            self.latest_snapshot_id,
            field_name="latest_snapshot_id",
        )
        latest_state_hash = _required_hash(
            self.latest_portfolio_state_sha256,
            field_name="latest_portfolio_state_sha256",
        )
        maximum_daily_loss = _nonnegative_fraction(
            self.maximum_daily_loss_fraction,
            field_name="maximum_daily_loss_fraction",
        )
        maximum_drawdown = _nonnegative_fraction(
            self.maximum_drawdown_fraction,
            field_name="maximum_drawdown_fraction",
        )
        previous_latch_id = _optional_hash(
            self.previous_latch_id,
            field_name="previous_latch_id",
        )

        object.__setattr__(self, "session_start_utc", session_start)
        object.__setattr__(self, "latest_observed_at_utc", latest_observed_at)
        object.__setattr__(self, "latest_snapshot_id", latest_snapshot_id)
        object.__setattr__(self, "latest_portfolio_state_sha256", latest_state_hash)
        object.__setattr__(self, "maximum_daily_loss_fraction", maximum_daily_loss)
        object.__setattr__(self, "maximum_drawdown_fraction", maximum_drawdown)
        object.__setattr__(self, "previous_latch_id", previous_latch_id)
        object.__setattr__(
            self,
            "latch_id",
            hashlib.sha256(_canonical_json_bytes(self._identity_payload())).hexdigest(),
        )

    def _identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "session_start_utc": _format_utc(self.session_start_utc),
            "latest_observed_at_utc": _format_utc(self.latest_observed_at_utc),
            "latest_snapshot_id": self.latest_snapshot_id,
            "latest_portfolio_state_sha256": self.latest_portfolio_state_sha256,
            "maximum_daily_loss_fraction": self.maximum_daily_loss_fraction,
            "maximum_drawdown_fraction": self.maximum_drawdown_fraction,
            "previous_latch_id": self.previous_latch_id,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_payload(), "latch_id": self.latch_id}

    def to_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> PaperRiskSessionLatch:
        if not isinstance(raw, bytes):
            raise TypeError("raw must be bytes")
        try:
            payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_fields)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("session latch must be valid UTF-8 JSON") from exc
        if not isinstance(payload, dict) or set(payload) != _LATCH_FIELDS:
            raise ValueError("session latch JSON schema is invalid")
        if payload["schema_version"] != _SCHEMA_VERSION:
            raise ValueError("unsupported session latch schema_version")
        supplied_latch_id = _required_hash(payload["latch_id"], field_name="latch_id")
        reconstructed = cls(
            session_start_utc=payload["session_start_utc"],
            latest_observed_at_utc=payload["latest_observed_at_utc"],
            latest_snapshot_id=payload["latest_snapshot_id"],
            latest_portfolio_state_sha256=payload["latest_portfolio_state_sha256"],
            maximum_daily_loss_fraction=payload["maximum_daily_loss_fraction"],
            maximum_drawdown_fraction=payload["maximum_drawdown_fraction"],
            previous_latch_id=payload["previous_latch_id"],
        )
        if supplied_latch_id != reconstructed.latch_id:
            raise ValueError("session latch content hash does not match latch_id")
        if raw != reconstructed.to_json_bytes():
            raise ValueError("session latch JSON is not canonical")
        return reconstructed

    def assert_matches(self, snapshot: PaperRiskStateSnapshot) -> None:
        if self.session_start_utc != snapshot.session_start_utc:
            raise ValueError("session latch does not match snapshot session_start_utc")
        if self.latest_observed_at_utc != snapshot.observed_at_utc:
            raise ValueError("session latch is not advanced to the supplied portfolio observation")
        if self.latest_snapshot_id != snapshot.snapshot_id:
            raise ValueError("session latch does not match the supplied snapshot_id")
        if self.latest_portfolio_state_sha256 != snapshot.portfolio_state_sha256:
            raise ValueError("session latch does not match the portfolio-state source hash")
        tolerance = 1e-12
        if self.maximum_daily_loss_fraction + tolerance < snapshot.daily_loss_fraction:
            raise ValueError("maximum_daily_loss_fraction cannot be below current daily loss")
        if self.maximum_drawdown_fraction + tolerance < snapshot.drawdown_fraction:
            raise ValueError("maximum_drawdown_fraction cannot be below current drawdown")


def advance_paper_risk_session_latch(
    snapshot: PaperRiskStateSnapshot,
    *,
    previous_latch: PaperRiskSessionLatch | None = None,
) -> PaperRiskSessionLatch:
    """Advance session maxima exactly once per ordered, source-bound portfolio snapshot."""

    if not isinstance(snapshot, PaperRiskStateSnapshot):
        raise TypeError("snapshot must be a PaperRiskStateSnapshot")
    if previous_latch is None:
        return PaperRiskSessionLatch(
            session_start_utc=snapshot.session_start_utc,
            latest_observed_at_utc=snapshot.observed_at_utc,
            latest_snapshot_id=snapshot.snapshot_id,
            latest_portfolio_state_sha256=snapshot.portfolio_state_sha256,
            maximum_daily_loss_fraction=snapshot.daily_loss_fraction,
            maximum_drawdown_fraction=snapshot.drawdown_fraction,
        )
    if not isinstance(previous_latch, PaperRiskSessionLatch):
        raise TypeError("previous_latch must be a PaperRiskSessionLatch")
    if previous_latch.session_start_utc != snapshot.session_start_utc:
        raise ValueError("cannot advance a session latch across session_start_utc")
    if snapshot.snapshot_id == previous_latch.latest_snapshot_id:
        previous_latch.assert_matches(snapshot)
        return previous_latch
    if snapshot.observed_at_utc <= previous_latch.latest_observed_at_utc:
        raise ValueError("portfolio snapshots must advance strictly within a risk session")
    return PaperRiskSessionLatch(
        session_start_utc=snapshot.session_start_utc,
        latest_observed_at_utc=snapshot.observed_at_utc,
        latest_snapshot_id=snapshot.snapshot_id,
        latest_portfolio_state_sha256=snapshot.portfolio_state_sha256,
        maximum_daily_loss_fraction=max(
            previous_latch.maximum_daily_loss_fraction,
            snapshot.daily_loss_fraction,
        ),
        maximum_drawdown_fraction=max(
            previous_latch.maximum_drawdown_fraction,
            snapshot.drawdown_fraction,
        ),
        previous_latch_id=previous_latch.latch_id,
    )


@dataclass(frozen=True, slots=True)
class PaperRiskSessionDecision:
    decision_id: str
    base_decision_id: str
    session_latch_id: str
    mode: Literal["normal", "reduce_only"]
    active_triggers: tuple[str, ...]
    allowed: bool
    blockers: tuple[str, ...]
    maximum_daily_loss_fraction: float
    maximum_drawdown_fraction: float
    base_decision: PaperRiskKillSwitchDecision

    def assert_allowed(self) -> None:
        if not self.allowed:
            raise RuntimeError(
                "paper risk session gate rejected exposure change: " + ", ".join(self.blockers)
            )


def evaluate_paper_risk_session_gate(
    proposed_exposures: tuple[ProposedInstrumentExposure, ...],
    *,
    snapshot: PaperRiskStateSnapshot,
    policy: PaperRiskKillSwitchPolicy,
    session_latch: PaperRiskSessionLatch,
    evaluated_at_utc: datetime | str,
) -> PaperRiskSessionDecision:
    """Apply replayable session-latched loss/drawdown limits around the base kill switch."""

    if not isinstance(session_latch, PaperRiskSessionLatch):
        raise TypeError("session_latch must be a PaperRiskSessionLatch")
    session_latch.assert_matches(snapshot)
    base_decision = evaluate_paper_risk_kill_switch(
        proposed_exposures,
        snapshot=snapshot,
        policy=policy,
        evaluated_at_utc=evaluated_at_utc,
    )

    trigger_names = set(base_decision.active_triggers)
    if session_latch.maximum_daily_loss_fraction >= policy.daily_loss_trigger_fraction:
        trigger_names.add("daily_loss_limit")
    if session_latch.maximum_drawdown_fraction >= policy.drawdown_trigger_fraction:
        trigger_names.add("drawdown_limit")
    active_triggers = tuple(name for name in _TRIGGER_ORDER if name in trigger_names)
    mode: Literal["normal", "reduce_only"] = "reduce_only" if active_triggers else "normal"
    blockers = (
        tuple(
            f"kill_switch_exposure_increase:{instrument_id}"
            for instrument_id in base_decision.exposure_increase_instruments
        )
        if active_triggers
        else ()
    )
    allowed = not blockers
    payload = {
        "schema_version": _SCHEMA_VERSION,
        "base_decision_id": base_decision.decision_id,
        "session_latch_id": session_latch.latch_id,
        "mode": mode,
        "active_triggers": list(active_triggers),
        "allowed": allowed,
        "blockers": list(blockers),
        "maximum_daily_loss_fraction": session_latch.maximum_daily_loss_fraction,
        "maximum_drawdown_fraction": session_latch.maximum_drawdown_fraction,
    }
    return PaperRiskSessionDecision(
        decision_id=hashlib.sha256(_canonical_json_bytes(payload)).hexdigest(),
        base_decision_id=base_decision.decision_id,
        session_latch_id=session_latch.latch_id,
        mode=mode,
        active_triggers=active_triggers,
        allowed=allowed,
        blockers=blockers,
        maximum_daily_loss_fraction=session_latch.maximum_daily_loss_fraction,
        maximum_drawdown_fraction=session_latch.maximum_drawdown_fraction,
        base_decision=base_decision,
    )
