from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from numbers import Real
from typing import Literal, Self

from .paper_risk_kill_switch import (
    PaperRiskKillSwitchDecision,
    PaperRiskKillSwitchPolicy,
    PaperRiskStateSnapshot,
    ProposedInstrumentExposure,
    evaluate_paper_risk_kill_switch,
)

_SCHEMA_VERSION = 3
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_TRIGGER_ORDER = (
    "stale_portfolio_state",
    "stale_market_data",
    "daily_loss_limit",
    "drawdown_limit",
    "abnormal_turnover_limit",
)


def _nonnegative_real(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{field_name} must be a finite non-negative real number")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0.0:
        raise ValueError(f"{field_name} must be a finite non-negative real number")
    return 0.0 if parsed == 0.0 else parsed


def _nonnegative_fraction(value: object, *, field_name: str) -> float:
    parsed = _nonnegative_real(value, field_name=field_name)
    if parsed > 1.0:
        raise ValueError(f"{field_name} must be a finite fraction in [0, 1]")
    return parsed


def _required_hash(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _required_utc_datetime(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a timezone-aware datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be a timezone-aware datetime")
    return value.astimezone(UTC)


def _canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


@dataclass(frozen=True, slots=True, init=False)
class PaperRiskSessionHighWatermarks:
    """Append-only session maxima bound to one snapshot and immutable policy."""

    observed_at_utc: datetime
    session_start_utc: datetime
    snapshot_id: str
    portfolio_state_sha256: str
    policy_id: str
    maximum_daily_loss_fraction: float
    maximum_drawdown_fraction: float
    maximum_daily_underlying_turnover: float
    previous_high_watermark_id: str | None
    schema_version: int = field(default=_SCHEMA_VERSION, init=False)
    high_watermark_id: str = field(init=False)

    @classmethod
    def _create(
        cls,
        *,
        snapshot: PaperRiskStateSnapshot,
        policy: PaperRiskKillSwitchPolicy,
        maximum_daily_loss_fraction: float,
        maximum_drawdown_fraction: float,
        maximum_daily_underlying_turnover: float,
        previous_high_watermark_id: str | None,
    ) -> Self:
        instance = object.__new__(cls)
        observed_at = _required_utc_datetime(
            snapshot.observed_at_utc,
            field_name="observed_at_utc",
        )
        session_start = _required_utc_datetime(
            snapshot.session_start_utc,
            field_name="session_start_utc",
        )
        snapshot_id = _required_hash(snapshot.snapshot_id, field_name="snapshot_id")
        state_hash = _required_hash(
            snapshot.portfolio_state_sha256,
            field_name="portfolio_state_sha256",
        )
        policy_id = _required_hash(policy.policy_id, field_name="policy_id")
        maximum_daily_loss = _nonnegative_fraction(
            maximum_daily_loss_fraction,
            field_name="maximum_daily_loss_fraction",
        )
        maximum_drawdown = _nonnegative_fraction(
            maximum_drawdown_fraction,
            field_name="maximum_drawdown_fraction",
        )
        maximum_daily_turnover = _nonnegative_real(
            maximum_daily_underlying_turnover,
            field_name="maximum_daily_underlying_turnover",
        )
        previous_id = (
            None
            if previous_high_watermark_id is None
            else _required_hash(
                previous_high_watermark_id,
                field_name="previous_high_watermark_id",
            )
        )

        object.__setattr__(instance, "observed_at_utc", observed_at)
        object.__setattr__(instance, "session_start_utc", session_start)
        object.__setattr__(instance, "snapshot_id", snapshot_id)
        object.__setattr__(instance, "portfolio_state_sha256", state_hash)
        object.__setattr__(instance, "policy_id", policy_id)
        object.__setattr__(
            instance,
            "maximum_daily_loss_fraction",
            maximum_daily_loss,
        )
        object.__setattr__(
            instance,
            "maximum_drawdown_fraction",
            maximum_drawdown,
        )
        object.__setattr__(
            instance,
            "maximum_daily_underlying_turnover",
            maximum_daily_turnover,
        )
        object.__setattr__(instance, "previous_high_watermark_id", previous_id)
        object.__setattr__(instance, "schema_version", _SCHEMA_VERSION)

        payload = {
            "schema_version": _SCHEMA_VERSION,
            "observed_at_utc": _format_utc(observed_at),
            "session_start_utc": _format_utc(session_start),
            "snapshot_id": snapshot_id,
            "portfolio_state_sha256": state_hash,
            "policy_id": policy_id,
            "maximum_daily_loss_fraction": maximum_daily_loss,
            "maximum_drawdown_fraction": maximum_drawdown,
            "maximum_daily_underlying_turnover": maximum_daily_turnover,
            "previous_high_watermark_id": previous_id,
        }
        object.__setattr__(
            instance,
            "high_watermark_id",
            hashlib.sha256(_canonical_json_bytes(payload)).hexdigest(),
        )
        return instance

    def assert_policy(self, policy: PaperRiskKillSwitchPolicy) -> None:
        if not isinstance(policy, PaperRiskKillSwitchPolicy):
            raise TypeError("policy must be a PaperRiskKillSwitchPolicy")
        if self.policy_id != policy.policy_id:
            raise ValueError("session high-watermarks do not match the immutable risk policy")

    def assert_compatible(self, snapshot: PaperRiskStateSnapshot) -> None:
        if self.snapshot_id != snapshot.snapshot_id:
            raise ValueError("session high-watermarks do not match the exact portfolio snapshot")
        if self.portfolio_state_sha256 != snapshot.portfolio_state_sha256:
            raise ValueError("session high-watermarks do not match the portfolio-state source hash")
        if self.session_start_utc != snapshot.session_start_utc:
            raise ValueError("session high-watermarks do not match the portfolio session")
        if self.observed_at_utc != snapshot.observed_at_utc:
            raise ValueError("session high-watermarks do not match the portfolio observation time")
        tolerance = 1e-12
        if self.maximum_daily_loss_fraction + tolerance < snapshot.daily_loss_fraction:
            raise ValueError("maximum_daily_loss_fraction cannot be below current daily loss")
        if self.maximum_drawdown_fraction + tolerance < snapshot.drawdown_fraction:
            raise ValueError("maximum_drawdown_fraction cannot be below current drawdown")
        if self.maximum_daily_underlying_turnover + tolerance < snapshot.daily_underlying_turnover:
            raise ValueError("maximum_daily_underlying_turnover cannot be below current turnover")


def advance_paper_risk_session_high_watermarks(
    snapshot: PaperRiskStateSnapshot,
    *,
    policy: PaperRiskKillSwitchPolicy,
    previous: PaperRiskSessionHighWatermarks | None = None,
) -> PaperRiskSessionHighWatermarks:
    """Advance append-only session maxima under one immutable risk policy."""

    if not isinstance(snapshot, PaperRiskStateSnapshot):
        raise TypeError("snapshot must be a PaperRiskStateSnapshot")
    if not isinstance(policy, PaperRiskKillSwitchPolicy):
        raise TypeError("policy must be a PaperRiskKillSwitchPolicy")
    tolerance = 1e-12
    if previous is None:
        if snapshot.observed_at_utc != snapshot.session_start_utc:
            raise ValueError("initial session high-watermarks require a session-start snapshot")
        if (
            snapshot.daily_loss_fraction > tolerance
            or snapshot.drawdown_fraction > tolerance
            or snapshot.daily_underlying_turnover > tolerance
        ):
            raise ValueError(
                "initial session high-watermarks require a zero-loss, zero-drawdown, "
                "zero-turnover snapshot"
            )
        maximum_daily_loss = snapshot.daily_loss_fraction
        maximum_drawdown = snapshot.drawdown_fraction
        maximum_daily_turnover = snapshot.daily_underlying_turnover
        previous_id = None
    else:
        if not isinstance(previous, PaperRiskSessionHighWatermarks):
            raise TypeError("previous must be a PaperRiskSessionHighWatermarks")
        previous.assert_policy(policy)
        if previous.session_start_utc != snapshot.session_start_utc:
            raise ValueError("cannot advance session high-watermarks across sessions")
        if snapshot.observed_at_utc < previous.observed_at_utc:
            raise ValueError("cannot advance session high-watermarks to an older snapshot")
        same_observation = snapshot.observed_at_utc == previous.observed_at_utc
        if same_observation and snapshot.snapshot_id != previous.snapshot_id:
            raise ValueError("conflicting portfolio snapshots share one session observation time")
        if same_observation:
            previous.assert_compatible(snapshot)
            return previous
        if (
            snapshot.daily_underlying_turnover + tolerance
            < previous.maximum_daily_underlying_turnover
        ):
            raise ValueError("daily_underlying_turnover cannot decrease within one session")
        maximum_daily_loss = max(
            previous.maximum_daily_loss_fraction,
            snapshot.daily_loss_fraction,
        )
        maximum_drawdown = max(
            previous.maximum_drawdown_fraction,
            snapshot.drawdown_fraction,
        )
        maximum_daily_turnover = max(
            previous.maximum_daily_underlying_turnover,
            snapshot.daily_underlying_turnover,
        )
        previous_id = previous.high_watermark_id

    return PaperRiskSessionHighWatermarks._create(
        snapshot=snapshot,
        policy=policy,
        maximum_daily_loss_fraction=maximum_daily_loss,
        maximum_drawdown_fraction=maximum_drawdown,
        maximum_daily_underlying_turnover=maximum_daily_turnover,
        previous_high_watermark_id=previous_id,
    )


@dataclass(frozen=True, slots=True)
class PaperRiskSessionDecision:
    decision_id: str
    base_decision_id: str
    high_watermark_id: str
    mode: Literal["normal", "reduce_only"]
    active_triggers: tuple[str, ...]
    allowed: bool
    blockers: tuple[str, ...]
    maximum_daily_loss_fraction: float
    maximum_drawdown_fraction: float
    maximum_daily_underlying_turnover: float
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
    high_watermarks: PaperRiskSessionHighWatermarks,
    evaluated_at_utc: datetime | str,
) -> PaperRiskSessionDecision:
    """Apply session-latched loss, drawdown and turnover limits."""

    if not isinstance(high_watermarks, PaperRiskSessionHighWatermarks):
        raise TypeError("high_watermarks must be a PaperRiskSessionHighWatermarks")
    high_watermarks.assert_policy(policy)
    high_watermarks.assert_compatible(snapshot)
    base_decision = evaluate_paper_risk_kill_switch(
        proposed_exposures,
        snapshot=snapshot,
        policy=policy,
        evaluated_at_utc=evaluated_at_utc,
    )

    trigger_names = set(base_decision.active_triggers)
    if high_watermarks.maximum_daily_loss_fraction >= policy.daily_loss_trigger_fraction:
        trigger_names.add("daily_loss_limit")
    if high_watermarks.maximum_drawdown_fraction >= policy.drawdown_trigger_fraction:
        trigger_names.add("drawdown_limit")
    if (
        high_watermarks.maximum_daily_underlying_turnover
        >= policy.daily_underlying_turnover_trigger
    ):
        trigger_names.add("abnormal_turnover_limit")
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
        "high_watermark_id": high_watermarks.high_watermark_id,
        "mode": mode,
        "active_triggers": list(active_triggers),
        "allowed": allowed,
        "blockers": list(blockers),
        "maximum_daily_loss_fraction": high_watermarks.maximum_daily_loss_fraction,
        "maximum_drawdown_fraction": high_watermarks.maximum_drawdown_fraction,
        "maximum_daily_underlying_turnover": high_watermarks.maximum_daily_underlying_turnover,
    }
    return PaperRiskSessionDecision(
        decision_id=hashlib.sha256(_canonical_json_bytes(payload)).hexdigest(),
        base_decision_id=base_decision.decision_id,
        high_watermark_id=high_watermarks.high_watermark_id,
        mode=mode,
        active_triggers=active_triggers,
        allowed=allowed,
        blockers=blockers,
        maximum_daily_loss_fraction=high_watermarks.maximum_daily_loss_fraction,
        maximum_drawdown_fraction=high_watermarks.maximum_drawdown_fraction,
        maximum_daily_underlying_turnover=high_watermarks.maximum_daily_underlying_turnover,
        base_decision=base_decision,
    )
