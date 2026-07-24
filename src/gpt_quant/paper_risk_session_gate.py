from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime
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


def _nonnegative_fraction(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{field_name} must be a finite fraction in [0, 1]")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0.0 or parsed > 1.0:
        raise ValueError(f"{field_name} must be a finite fraction in [0, 1]")
    return 0.0 if parsed == 0.0 else parsed


def _required_hash(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class PaperRiskSessionHighWatermarks:
    """Source-bound session maxima that keep loss and drawdown stops latched."""

    portfolio_state_sha256: str
    maximum_daily_loss_fraction: float
    maximum_drawdown_fraction: float
    schema_version: int = field(default=_SCHEMA_VERSION, init=False)
    high_watermark_id: str = field(init=False)

    def __post_init__(self) -> None:
        state_hash = _required_hash(
            self.portfolio_state_sha256,
            field_name="portfolio_state_sha256",
        )
        maximum_daily_loss = _nonnegative_fraction(
            self.maximum_daily_loss_fraction,
            field_name="maximum_daily_loss_fraction",
        )
        maximum_drawdown = _nonnegative_fraction(
            self.maximum_drawdown_fraction,
            field_name="maximum_drawdown_fraction",
        )
        object.__setattr__(self, "portfolio_state_sha256", state_hash)
        object.__setattr__(self, "maximum_daily_loss_fraction", maximum_daily_loss)
        object.__setattr__(self, "maximum_drawdown_fraction", maximum_drawdown)
        payload = {
            "schema_version": self.schema_version,
            "portfolio_state_sha256": state_hash,
            "maximum_daily_loss_fraction": maximum_daily_loss,
            "maximum_drawdown_fraction": maximum_drawdown,
        }
        object.__setattr__(
            self,
            "high_watermark_id",
            hashlib.sha256(_canonical_json_bytes(payload)).hexdigest(),
        )

    def assert_compatible(self, snapshot: PaperRiskStateSnapshot) -> None:
        if self.portfolio_state_sha256 != snapshot.portfolio_state_sha256:
            raise ValueError(
                "session high-watermarks do not match the portfolio-state source hash"
            )
        tolerance = 1e-12
        if self.maximum_daily_loss_fraction + tolerance < snapshot.daily_loss_fraction:
            raise ValueError(
                "maximum_daily_loss_fraction cannot be below current daily loss"
            )
        if self.maximum_drawdown_fraction + tolerance < snapshot.drawdown_fraction:
            raise ValueError(
                "maximum_drawdown_fraction cannot be below current drawdown"
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
    base_decision: PaperRiskKillSwitchDecision

    def assert_allowed(self) -> None:
        if not self.allowed:
            raise RuntimeError(
                "paper risk session gate rejected exposure change: "
                + ", ".join(self.blockers)
            )


def evaluate_paper_risk_session_gate(
    proposed_exposures: tuple[ProposedInstrumentExposure, ...],
    *,
    snapshot: PaperRiskStateSnapshot,
    policy: PaperRiskKillSwitchPolicy,
    high_watermarks: PaperRiskSessionHighWatermarks,
    evaluated_at_utc: datetime | str,
) -> PaperRiskSessionDecision:
    """Apply session-latched loss/drawdown limits around the base kill switch."""

    if not isinstance(high_watermarks, PaperRiskSessionHighWatermarks):
        raise TypeError("high_watermarks must be a PaperRiskSessionHighWatermarks")
    high_watermarks.assert_compatible(snapshot)
    base_decision = evaluate_paper_risk_kill_switch(
        proposed_exposures,
        snapshot=snapshot,
        policy=policy,
        evaluated_at_utc=evaluated_at_utc,
    )

    trigger_names = set(base_decision.active_triggers)
    if (
        high_watermarks.maximum_daily_loss_fraction
        >= policy.daily_loss_trigger_fraction
    ):
        trigger_names.add("daily_loss_limit")
    if high_watermarks.maximum_drawdown_fraction >= policy.drawdown_trigger_fraction:
        trigger_names.add("drawdown_limit")
    active_triggers = tuple(name for name in _TRIGGER_ORDER if name in trigger_names)
    mode: Literal["normal", "reduce_only"] = (
        "reduce_only" if active_triggers else "normal"
    )
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
        base_decision=base_decision,
    )
