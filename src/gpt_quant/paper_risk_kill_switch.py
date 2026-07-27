from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from numbers import Real
from typing import Literal

_SCHEMA_VERSION = 1
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"{field_name} must be a non-empty trimmed string")
    if any(ord(character) < 32 for character in value):
        raise ValueError(f"{field_name} must not contain control characters")
    return value


def _required_hash(value: object, *, field_name: str) -> str:
    parsed = _required_text(value, field_name=field_name)
    if _SHA256_PATTERN.fullmatch(parsed) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return parsed


def _required_nonnegative_real(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{field_name} must be a finite non-negative real number")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0.0:
        raise ValueError(f"{field_name} must be a finite non-negative real number")
    return 0.0 if parsed == 0.0 else parsed


def _required_positive_real(value: object, *, field_name: str) -> float:
    parsed = _required_nonnegative_real(value, field_name=field_name)
    if parsed <= 0.0:
        raise ValueError(f"{field_name} must be positive")
    return parsed


def _required_fraction(value: object, *, field_name: str) -> float:
    parsed = _required_positive_real(value, field_name=field_name)
    if parsed > 1.0:
        raise ValueError(f"{field_name} cannot exceed 1")
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
class InstrumentExposure:
    instrument_id: str
    current_exposure: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "instrument_id",
            _required_text(self.instrument_id, field_name="instrument_id"),
        )
        current = _required_nonnegative_real(
            self.current_exposure,
            field_name="current_exposure",
        )
        if current > 1.0:
            raise ValueError("instrument exposure cannot imply leveraged long-only spot state")
        object.__setattr__(self, "current_exposure", current)


@dataclass(frozen=True, slots=True)
class ProposedInstrumentExposure:
    instrument_id: str
    proposed_exposure: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "instrument_id",
            _required_text(self.instrument_id, field_name="instrument_id"),
        )
        proposed = _required_nonnegative_real(
            self.proposed_exposure,
            field_name="proposed_exposure",
        )
        if proposed > 1.0:
            raise ValueError("instrument exposure cannot imply leveraged long-only spot state")
        object.__setattr__(self, "proposed_exposure", proposed)


@dataclass(frozen=True, slots=True)
class InstrumentExposureChange:
    instrument_id: str
    current_exposure: float
    proposed_exposure: float


@dataclass(frozen=True, slots=True)
class PaperRiskStateSnapshot:
    """Immutable paper portfolio state required by the runtime kill switch."""

    observed_at_utc: datetime
    session_start_utc: datetime
    market_data_observed_at_utc: datetime
    session_start_equity: float
    peak_equity: float
    current_equity: float
    daily_underlying_turnover: float
    instrument_exposures: tuple[InstrumentExposure, ...]
    portfolio_state_sha256: str
    market_data_source_sha256: str
    schema_version: int = field(default=_SCHEMA_VERSION, init=False)
    daily_loss_fraction: float = field(init=False)
    drawdown_fraction: float = field(init=False)
    snapshot_id: str = field(init=False)

    def __post_init__(self) -> None:
        observed_at = _required_utc_datetime(
            self.observed_at_utc,
            field_name="observed_at_utc",
        )
        session_start = _required_utc_datetime(
            self.session_start_utc,
            field_name="session_start_utc",
        )
        market_observed_at = _required_utc_datetime(
            self.market_data_observed_at_utc,
            field_name="market_data_observed_at_utc",
        )
        if session_start > observed_at:
            raise ValueError("session_start_utc cannot be after the portfolio observation")

        session_start_equity = _required_positive_real(
            self.session_start_equity,
            field_name="session_start_equity",
        )
        peak_equity = _required_positive_real(self.peak_equity, field_name="peak_equity")
        current_equity = _required_nonnegative_real(
            self.current_equity,
            field_name="current_equity",
        )
        tolerance = max(1.0, session_start_equity, peak_equity, current_equity) * 1e-12
        if peak_equity + tolerance < max(session_start_equity, current_equity):
            raise ValueError("peak_equity cannot be below session start or current equity")

        daily_turnover = _required_nonnegative_real(
            self.daily_underlying_turnover,
            field_name="daily_underlying_turnover",
        )
        instrument_exposures = tuple(
            sorted(self.instrument_exposures, key=lambda value: value.instrument_id)
        )
        instrument_ids = [exposure.instrument_id for exposure in instrument_exposures]
        if len(set(instrument_ids)) != len(instrument_ids):
            raise ValueError("paper risk state contains duplicate instruments")
        if sum(exposure.current_exposure for exposure in instrument_exposures) > 1.0 + 1e-12:
            raise ValueError("current gross exposure cannot imply leveraged long-only spot state")
        portfolio_state_sha256 = _required_hash(
            self.portfolio_state_sha256,
            field_name="portfolio_state_sha256",
        )
        market_data_source_sha256 = _required_hash(
            self.market_data_source_sha256,
            field_name="market_data_source_sha256",
        )
        daily_loss_fraction = max(
            0.0,
            (session_start_equity - current_equity) / session_start_equity,
        )
        drawdown_fraction = max(0.0, (peak_equity - current_equity) / peak_equity)

        object.__setattr__(self, "observed_at_utc", observed_at)
        object.__setattr__(self, "session_start_utc", session_start)
        object.__setattr__(self, "market_data_observed_at_utc", market_observed_at)
        object.__setattr__(self, "session_start_equity", session_start_equity)
        object.__setattr__(self, "peak_equity", peak_equity)
        object.__setattr__(self, "current_equity", current_equity)
        object.__setattr__(self, "daily_underlying_turnover", daily_turnover)
        object.__setattr__(self, "instrument_exposures", instrument_exposures)
        object.__setattr__(self, "portfolio_state_sha256", portfolio_state_sha256)
        object.__setattr__(self, "market_data_source_sha256", market_data_source_sha256)
        object.__setattr__(self, "daily_loss_fraction", daily_loss_fraction)
        object.__setattr__(self, "drawdown_fraction", drawdown_fraction)

        payload = {
            "schema_version": self.schema_version,
            "observed_at_utc": _format_utc(observed_at),
            "session_start_utc": _format_utc(session_start),
            "market_data_observed_at_utc": _format_utc(market_observed_at),
            "session_start_equity": session_start_equity,
            "peak_equity": peak_equity,
            "current_equity": current_equity,
            "daily_underlying_turnover": daily_turnover,
            "instrument_exposures": [
                {
                    "instrument_id": exposure.instrument_id,
                    "current_exposure": exposure.current_exposure,
                }
                for exposure in instrument_exposures
            ],
            "daily_loss_fraction": daily_loss_fraction,
            "drawdown_fraction": drawdown_fraction,
            "portfolio_state_sha256": portfolio_state_sha256,
            "market_data_source_sha256": market_data_source_sha256,
        }
        object.__setattr__(
            self,
            "snapshot_id",
            hashlib.sha256(_canonical_json_bytes(payload)).hexdigest(),
        )


@dataclass(frozen=True, slots=True)
class PaperRiskKillSwitchPolicy:
    daily_loss_trigger_fraction: float
    drawdown_trigger_fraction: float
    daily_underlying_turnover_trigger: float
    maximum_state_age_seconds: float
    maximum_market_data_age_seconds: float
    schema_version: int = field(default=_SCHEMA_VERSION, init=False)
    policy_id: str = field(init=False)

    def __post_init__(self) -> None:
        daily_loss = _required_fraction(
            self.daily_loss_trigger_fraction,
            field_name="daily_loss_trigger_fraction",
        )
        drawdown = _required_fraction(
            self.drawdown_trigger_fraction,
            field_name="drawdown_trigger_fraction",
        )
        daily_turnover = _required_positive_real(
            self.daily_underlying_turnover_trigger,
            field_name="daily_underlying_turnover_trigger",
        )
        maximum_state_age = _required_positive_real(
            self.maximum_state_age_seconds,
            field_name="maximum_state_age_seconds",
        )
        maximum_market_data_age = _required_positive_real(
            self.maximum_market_data_age_seconds,
            field_name="maximum_market_data_age_seconds",
        )
        object.__setattr__(self, "daily_loss_trigger_fraction", daily_loss)
        object.__setattr__(self, "drawdown_trigger_fraction", drawdown)
        object.__setattr__(self, "daily_underlying_turnover_trigger", daily_turnover)
        object.__setattr__(self, "maximum_state_age_seconds", maximum_state_age)
        object.__setattr__(
            self,
            "maximum_market_data_age_seconds",
            maximum_market_data_age,
        )
        payload = {
            "schema_version": self.schema_version,
            "daily_loss_trigger_fraction": daily_loss,
            "drawdown_trigger_fraction": drawdown,
            "daily_underlying_turnover_trigger": daily_turnover,
            "maximum_state_age_seconds": maximum_state_age,
            "maximum_market_data_age_seconds": maximum_market_data_age,
        }
        object.__setattr__(
            self,
            "policy_id",
            hashlib.sha256(_canonical_json_bytes(payload)).hexdigest(),
        )


@dataclass(frozen=True, slots=True)
class PaperRiskKillSwitchDecision:
    decision_id: str
    evaluated_at_utc: datetime
    snapshot_id: str
    policy_id: str
    mode: Literal["normal", "reduce_only"]
    active_triggers: tuple[str, ...]
    exposure_increase_instruments: tuple[str, ...]
    allowed: bool
    blockers: tuple[str, ...]
    state_age_seconds: float
    market_data_age_seconds: float
    daily_loss_fraction: float
    drawdown_fraction: float
    daily_underlying_turnover: float
    current_gross_exposure: float
    proposed_gross_exposure: float
    exposure_changes: tuple[InstrumentExposureChange, ...]

    def assert_allowed(self) -> None:
        if not self.allowed:
            raise RuntimeError(
                "paper risk kill switch rejected exposure change: " + ", ".join(self.blockers)
            )


def evaluate_paper_risk_kill_switch(
    proposed_exposures: tuple[ProposedInstrumentExposure, ...],
    *,
    snapshot: PaperRiskStateSnapshot,
    policy: PaperRiskKillSwitchPolicy,
    evaluated_at_utc: datetime | str,
) -> PaperRiskKillSwitchDecision:
    """Fail closed to per-instrument reduce-only mode after a runtime risk trigger."""

    if not proposed_exposures:
        raise ValueError("paper risk kill switch requires at least one proposed exposure")
    ordered_proposals = tuple(sorted(proposed_exposures, key=lambda value: value.instrument_id))
    proposal_ids = [proposal.instrument_id for proposal in ordered_proposals]
    if len(set(proposal_ids)) != len(proposal_ids):
        raise ValueError("paper risk kill switch received duplicate instruments")

    evaluated_at = _required_utc_datetime(evaluated_at_utc, field_name="evaluated_at_utc")
    if snapshot.observed_at_utc > evaluated_at:
        raise ValueError("portfolio state cannot be observed after kill-switch evaluation")
    if snapshot.market_data_observed_at_utc > evaluated_at:
        raise ValueError("market data cannot be observed after kill-switch evaluation")

    current_by_instrument = {
        exposure.instrument_id: exposure.current_exposure
        for exposure in snapshot.instrument_exposures
    }
    proposed_by_instrument = dict(current_by_instrument)
    for proposal in ordered_proposals:
        proposed_by_instrument[proposal.instrument_id] = proposal.proposed_exposure
    ordered_changes = tuple(
        InstrumentExposureChange(
            instrument_id=instrument_id,
            current_exposure=current_by_instrument.get(instrument_id, 0.0),
            proposed_exposure=proposed_by_instrument[instrument_id],
        )
        for instrument_id in sorted(proposed_by_instrument)
    )
    current_gross_exposure = sum(change.current_exposure for change in ordered_changes)
    proposed_gross_exposure = sum(change.proposed_exposure for change in ordered_changes)
    tolerance = 1e-12
    if proposed_gross_exposure > 1.0 + tolerance:
        raise ValueError("proposed gross exposure cannot imply leveraged long-only spot state")

    state_age_seconds = (evaluated_at - snapshot.observed_at_utc).total_seconds()
    market_data_age_seconds = (evaluated_at - snapshot.market_data_observed_at_utc).total_seconds()
    active_triggers: list[str] = []
    if state_age_seconds > policy.maximum_state_age_seconds:
        active_triggers.append("stale_portfolio_state")
    if market_data_age_seconds > policy.maximum_market_data_age_seconds:
        active_triggers.append("stale_market_data")
    if snapshot.daily_loss_fraction >= policy.daily_loss_trigger_fraction:
        active_triggers.append("daily_loss_limit")
    if snapshot.drawdown_fraction >= policy.drawdown_trigger_fraction:
        active_triggers.append("drawdown_limit")
    if snapshot.daily_underlying_turnover >= policy.daily_underlying_turnover_trigger:
        active_triggers.append("abnormal_turnover_limit")

    exposure_increases = tuple(
        change.instrument_id
        for change in ordered_changes
        if change.proposed_exposure > change.current_exposure + tolerance
    )
    mode: Literal["normal", "reduce_only"] = "reduce_only" if active_triggers else "normal"
    blockers = (
        tuple(
            f"kill_switch_exposure_increase:{instrument_id}" for instrument_id in exposure_increases
        )
        if active_triggers
        else ()
    )
    allowed = not blockers
    active_triggers_tuple = tuple(active_triggers)
    decision_payload = {
        "schema_version": _SCHEMA_VERSION,
        "evaluated_at_utc": _format_utc(evaluated_at),
        "snapshot_id": snapshot.snapshot_id,
        "policy_id": policy.policy_id,
        "mode": mode,
        "active_triggers": list(active_triggers_tuple),
        "exposure_increase_instruments": list(exposure_increases),
        "allowed": allowed,
        "blockers": list(blockers),
        "state_age_seconds": state_age_seconds,
        "market_data_age_seconds": market_data_age_seconds,
        "daily_loss_fraction": snapshot.daily_loss_fraction,
        "drawdown_fraction": snapshot.drawdown_fraction,
        "daily_underlying_turnover": snapshot.daily_underlying_turnover,
        "current_gross_exposure": current_gross_exposure,
        "proposed_gross_exposure": proposed_gross_exposure,
        "exposure_changes": [
            {
                "instrument_id": change.instrument_id,
                "current_exposure": change.current_exposure,
                "proposed_exposure": change.proposed_exposure,
            }
            for change in ordered_changes
        ],
    }
    decision_id = hashlib.sha256(_canonical_json_bytes(decision_payload)).hexdigest()
    return PaperRiskKillSwitchDecision(
        decision_id=decision_id,
        evaluated_at_utc=evaluated_at,
        snapshot_id=snapshot.snapshot_id,
        policy_id=policy.policy_id,
        mode=mode,
        active_triggers=active_triggers_tuple,
        exposure_increase_instruments=exposure_increases,
        allowed=allowed,
        blockers=blockers,
        state_age_seconds=state_age_seconds,
        market_data_age_seconds=market_data_age_seconds,
        daily_loss_fraction=snapshot.daily_loss_fraction,
        drawdown_fraction=snapshot.drawdown_fraction,
        daily_underlying_turnover=snapshot.daily_underlying_turnover,
        current_gross_exposure=current_gross_exposure,
        proposed_gross_exposure=proposed_gross_exposure,
        exposure_changes=ordered_changes,
    )
