from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from numbers import Real

from .execution_intent import TargetPositionIntent

_SCHEMA_VERSION = 2
_EXCHANGE_FEE_BPS = 5.0
_ALL_IN_STRESS_BPS = (7.5, 10.0, 15.0)
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
class PortfolioPosition:
    """Long-only spot holding marked from immutable market evidence."""

    instrument_id: str
    quantity: float
    mark_price: float
    mark_observed_at_utc: datetime
    mark_source_sha256: str
    gross_notional: float = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "instrument_id",
            _required_text(self.instrument_id, field_name="instrument_id"),
        )
        quantity = _required_nonnegative_real(self.quantity, field_name="quantity")
        mark_price = _required_positive_real(self.mark_price, field_name="mark_price")
        mark_observed_at = _required_utc_datetime(
            self.mark_observed_at_utc,
            field_name="mark_observed_at_utc",
        )
        mark_source_sha256 = _required_hash(
            self.mark_source_sha256,
            field_name="mark_source_sha256",
        )
        gross_notional = quantity * mark_price
        if not math.isfinite(gross_notional):
            raise ValueError("gross_notional must be finite")

        object.__setattr__(self, "quantity", quantity)
        object.__setattr__(self, "mark_price", mark_price)
        object.__setattr__(self, "mark_observed_at_utc", mark_observed_at)
        object.__setattr__(self, "mark_source_sha256", mark_source_sha256)
        object.__setattr__(self, "gross_notional", gross_notional)


@dataclass(frozen=True, slots=True)
class PaperPortfolioRiskSnapshot:
    observed_at_utc: datetime
    equity: float
    cash: float
    positions: tuple[PortfolioPosition, ...]
    schema_version: int = field(default=_SCHEMA_VERSION, init=False)
    snapshot_id: str = field(init=False)
    current_gross_notional: float = field(init=False)
    current_gross_exposure: float = field(init=False)

    def __post_init__(self) -> None:
        observed_at = _required_utc_datetime(
            self.observed_at_utc,
            field_name="observed_at_utc",
        )
        equity = _required_positive_real(self.equity, field_name="equity")
        cash = _required_nonnegative_real(self.cash, field_name="cash")
        positions = tuple(sorted(self.positions, key=lambda position: position.instrument_id))
        instrument_ids = [position.instrument_id for position in positions]
        if len(set(instrument_ids)) != len(instrument_ids):
            raise ValueError("paper portfolio risk snapshot contains duplicate instruments")
        for position in positions:
            if position.mark_observed_at_utc > observed_at:
                raise ValueError("position mark cannot be observed after the portfolio snapshot")

        current_gross_notional = sum(position.gross_notional for position in positions)
        current_gross_exposure = current_gross_notional / equity
        tolerance = max(1.0, equity) * 1e-9
        if current_gross_notional > equity + tolerance:
            raise ValueError("paper portfolio risk snapshot cannot contain leveraged spot exposure")
        if abs(cash + current_gross_notional - equity) > tolerance:
            raise ValueError("cash plus marked spot positions must reconcile to equity")

        object.__setattr__(self, "observed_at_utc", observed_at)
        object.__setattr__(self, "equity", equity)
        object.__setattr__(self, "cash", cash)
        object.__setattr__(self, "positions", positions)
        object.__setattr__(self, "current_gross_notional", current_gross_notional)
        object.__setattr__(self, "current_gross_exposure", current_gross_exposure)
        payload = {
            "schema_version": self.schema_version,
            "observed_at_utc": _format_utc(observed_at),
            "equity": equity,
            "cash": cash,
            "positions": [
                {
                    "instrument_id": position.instrument_id,
                    "quantity": position.quantity,
                    "mark_price": position.mark_price,
                    "mark_observed_at_utc": _format_utc(position.mark_observed_at_utc),
                    "mark_source_sha256": position.mark_source_sha256,
                    "gross_notional": position.gross_notional,
                }
                for position in positions
            ],
        }
        object.__setattr__(
            self,
            "snapshot_id",
            hashlib.sha256(_canonical_json_bytes(payload)).hexdigest(),
        )


@dataclass(frozen=True, slots=True)
class InstrumentTargetRiskLimit:
    instrument_id: str
    maximum_target_position: float
    maximum_gross_notional: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "instrument_id",
            _required_text(self.instrument_id, field_name="instrument_id"),
        )
        maximum_target_position = _required_positive_real(
            self.maximum_target_position,
            field_name="maximum_target_position",
        )
        if maximum_target_position > 1.0:
            raise ValueError("maximum_target_position cannot imply leveraged spot exposure")
        object.__setattr__(self, "maximum_target_position", maximum_target_position)
        object.__setattr__(
            self,
            "maximum_gross_notional",
            _required_positive_real(
                self.maximum_gross_notional,
                field_name="maximum_gross_notional",
            ),
        )


@dataclass(frozen=True, slots=True)
class ExecutionCostInputs:
    spread_bps: float
    slippage_bps: float
    market_impact_bps: float
    latency_bps: float
    exchange_fee_bps: float = field(default=_EXCHANGE_FEE_BPS, init=False)
    all_in_stress_bps: tuple[float, float, float] = field(
        default=_ALL_IN_STRESS_BPS,
        init=False,
    )

    def __post_init__(self) -> None:
        for field_name in (
            "spread_bps",
            "slippage_bps",
            "market_impact_bps",
            "latency_bps",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_nonnegative_real(getattr(self, field_name), field_name=field_name),
            )

    @property
    def decomposed_total_bps(self) -> float:
        return (
            self.exchange_fee_bps
            + self.spread_bps
            + self.slippage_bps
            + self.market_impact_bps
            + self.latency_bps
        )


@dataclass(frozen=True, slots=True)
class PortfolioTargetRiskPolicy:
    instrument_limits: tuple[InstrumentTargetRiskLimit, ...]
    maximum_gross_target_exposure: float
    maximum_gross_notional: float
    maximum_batch_turnover: float
    minimum_cash_reserve: float
    maximum_position_mark_age_seconds: float
    costs: ExecutionCostInputs
    schema_version: int = field(default=_SCHEMA_VERSION, init=False)
    policy_id: str = field(init=False)

    def __post_init__(self) -> None:
        limits = tuple(sorted(self.instrument_limits, key=lambda limit: limit.instrument_id))
        instrument_ids = [limit.instrument_id for limit in limits]
        if not limits:
            raise ValueError("portfolio target risk policy requires at least one instrument limit")
        if len(set(instrument_ids)) != len(instrument_ids):
            raise ValueError("portfolio target risk policy contains duplicate instruments")
        object.__setattr__(self, "instrument_limits", limits)
        maximum_gross_target_exposure = _required_positive_real(
            self.maximum_gross_target_exposure,
            field_name="maximum_gross_target_exposure",
        )
        if maximum_gross_target_exposure > 1.0:
            raise ValueError("maximum_gross_target_exposure cannot imply leveraged spot exposure")
        object.__setattr__(
            self,
            "maximum_gross_target_exposure",
            maximum_gross_target_exposure,
        )
        for field_name in (
            "maximum_gross_notional",
            "maximum_batch_turnover",
            "maximum_position_mark_age_seconds",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_positive_real(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(
            self,
            "minimum_cash_reserve",
            _required_nonnegative_real(
                self.minimum_cash_reserve,
                field_name="minimum_cash_reserve",
            ),
        )
        payload = {
            "schema_version": self.schema_version,
            "instrument_limits": [
                {
                    "instrument_id": limit.instrument_id,
                    "maximum_target_position": limit.maximum_target_position,
                    "maximum_gross_notional": limit.maximum_gross_notional,
                }
                for limit in limits
            ],
            "maximum_gross_target_exposure": self.maximum_gross_target_exposure,
            "maximum_gross_notional": self.maximum_gross_notional,
            "maximum_batch_turnover": self.maximum_batch_turnover,
            "minimum_cash_reserve": self.minimum_cash_reserve,
            "maximum_position_mark_age_seconds": self.maximum_position_mark_age_seconds,
            "costs": {
                "exchange_fee_bps": self.costs.exchange_fee_bps,
                "spread_bps": self.costs.spread_bps,
                "slippage_bps": self.costs.slippage_bps,
                "market_impact_bps": self.costs.market_impact_bps,
                "latency_bps": self.costs.latency_bps,
                "all_in_stress_bps": list(self.costs.all_in_stress_bps),
            },
        }
        object.__setattr__(
            self,
            "policy_id",
            hashlib.sha256(_canonical_json_bytes(payload)).hexdigest(),
        )


@dataclass(frozen=True, slots=True)
class InstrumentTargetRiskMeasure:
    instrument_id: str
    current_quantity: float
    current_mark_price: float | None
    current_mark_observed_at_utc: datetime | None
    current_mark_source_sha256: str | None
    current_mark_age_seconds: float | None
    current_gross_notional: float
    current_position: float
    projected_position: float
    turnover: float
    turnover_notional: float
    projected_gross_notional: float
    maximum_target_position: float
    maximum_gross_notional: float


@dataclass(frozen=True, slots=True)
class TargetRiskDecision:
    decision_id: str
    allowed: bool
    blockers: tuple[str, ...]
    snapshot_id: str
    policy_id: str
    intent_ids: tuple[str, ...]
    current_gross_target_exposure: float
    current_gross_notional: float
    projected_gross_target_exposure: float
    projected_gross_notional: float
    batch_turnover: float
    traded_notional: float
    required_buy_notional: float
    required_sell_notional: float
    exchange_fee_reserve: float
    spread_reserve: float
    slippage_reserve: float
    market_impact_reserve: float
    latency_reserve: float
    decomposed_cost_reserve: float
    stress_7_5_bps_reserve: float
    stress_10_bps_reserve: float
    stress_15_bps_reserve: float
    cash_cost_reserve: float
    minimum_cash_reserve: float
    required_cash: float
    available_cash: float
    instrument_measures: tuple[InstrumentTargetRiskMeasure, ...]

    def assert_allowed(self) -> None:
        if not self.allowed:
            raise RuntimeError(
                "target-position intent batch rejected by portfolio risk gate: "
                + ", ".join(self.blockers)
            )


def evaluate_target_position_intents(
    intents: tuple[TargetPositionIntent, ...],
    *,
    snapshot: PaperPortfolioRiskSnapshot,
    policy: PortfolioTargetRiskPolicy,
) -> TargetRiskDecision:
    if not intents:
        raise ValueError("portfolio target risk gate requires at least one intent")
    ordered_intents = tuple(sorted(intents, key=lambda intent: intent.instrument_id))
    intent_ids = [intent.intent_id for intent in ordered_intents]
    instrument_ids = [intent.instrument_id for intent in ordered_intents]
    if len(set(intent_ids)) != len(intent_ids):
        raise ValueError("portfolio target risk gate received duplicate intent IDs")
    if len(set(instrument_ids)) != len(instrument_ids):
        raise ValueError("portfolio target risk gate received duplicate instruments")

    limit_by_instrument = {limit.instrument_id: limit for limit in policy.instrument_limits}
    current_by_instrument = {
        position.instrument_id: position for position in snapshot.positions
    }
    unsupported_current = sorted(set(current_by_instrument) - set(limit_by_instrument))
    if unsupported_current:
        raise ValueError(
            "paper portfolio risk snapshot contains instruments without policy limits: "
            + ", ".join(unsupported_current)
        )

    projected_position_by_instrument = {
        instrument_id: position.gross_notional / snapshot.equity
        for instrument_id, position in current_by_instrument.items()
    }
    for intent in ordered_intents:
        intent.assert_active_at(snapshot.observed_at_utc)
        if intent.minimum_position < 0.0 or intent.target_position < 0.0:
            raise ValueError("portfolio target risk gate supports long-only spot intents")
        if intent.instrument_id not in limit_by_instrument:
            raise ValueError(
                f"target-position intent {intent.instrument_id!r} has no portfolio risk limit"
            )
        projected_position_by_instrument[intent.instrument_id] = intent.target_position

    all_instruments = sorted(set(projected_position_by_instrument) | set(limit_by_instrument))
    blockers: list[str] = []
    measures: list[InstrumentTargetRiskMeasure] = []
    current_gross_exposure = 0.0
    current_gross_notional = 0.0
    projected_gross_exposure = 0.0
    projected_gross_notional = 0.0
    traded_notional = 0.0
    required_buy_notional = 0.0
    required_sell_notional = 0.0

    for instrument_id in all_instruments:
        current_position_record = current_by_instrument.get(instrument_id)
        current_notional = (
            current_position_record.gross_notional if current_position_record is not None else 0.0
        )
        current_position = current_notional / snapshot.equity
        projected_position = projected_position_by_instrument.get(
            instrument_id,
            current_position,
        )
        projected_notional = projected_position * snapshot.equity
        turnover_notional = abs(projected_notional - current_notional)
        turnover = turnover_notional / snapshot.equity
        limit = limit_by_instrument[instrument_id]

        current_mark_age_seconds: float | None = None
        if current_position_record is not None and current_position_record.quantity > 0.0:
            current_mark_age_seconds = (
                snapshot.observed_at_utc - current_position_record.mark_observed_at_utc
            ).total_seconds()
            if current_mark_age_seconds > policy.maximum_position_mark_age_seconds:
                blockers.append(f"stale_position_mark:{instrument_id}")

        current_gross_exposure += current_position
        current_gross_notional += current_notional
        projected_gross_exposure += projected_position
        projected_gross_notional += projected_notional
        traded_notional += turnover_notional
        required_buy_notional += max(projected_notional - current_notional, 0.0)
        required_sell_notional += max(current_notional - projected_notional, 0.0)
        if projected_position > limit.maximum_target_position:
            blockers.append(f"instrument_target_position_limit:{instrument_id}")
        if projected_notional > limit.maximum_gross_notional:
            blockers.append(f"instrument_gross_notional_limit:{instrument_id}")
        measures.append(
            InstrumentTargetRiskMeasure(
                instrument_id=instrument_id,
                current_quantity=(
                    current_position_record.quantity
                    if current_position_record is not None
                    else 0.0
                ),
                current_mark_price=(
                    current_position_record.mark_price
                    if current_position_record is not None
                    else None
                ),
                current_mark_observed_at_utc=(
                    current_position_record.mark_observed_at_utc
                    if current_position_record is not None
                    else None
                ),
                current_mark_source_sha256=(
                    current_position_record.mark_source_sha256
                    if current_position_record is not None
                    else None
                ),
                current_mark_age_seconds=current_mark_age_seconds,
                current_gross_notional=current_notional,
                current_position=current_position,
                projected_position=projected_position,
                turnover=turnover,
                turnover_notional=turnover_notional,
                projected_gross_notional=projected_notional,
                maximum_target_position=limit.maximum_target_position,
                maximum_gross_notional=limit.maximum_gross_notional,
            )
        )

    batch_turnover = traded_notional / snapshot.equity
    if projected_gross_exposure > policy.maximum_gross_target_exposure:
        blockers.append("portfolio_gross_target_exposure_limit")
    if projected_gross_notional > policy.maximum_gross_notional:
        blockers.append("portfolio_gross_notional_limit")
    if batch_turnover > policy.maximum_batch_turnover:
        blockers.append("portfolio_batch_turnover_limit")

    bps_scale = traded_notional / 10_000.0
    exchange_fee_reserve = policy.costs.exchange_fee_bps * bps_scale
    spread_reserve = policy.costs.spread_bps * bps_scale
    slippage_reserve = policy.costs.slippage_bps * bps_scale
    market_impact_reserve = policy.costs.market_impact_bps * bps_scale
    latency_reserve = policy.costs.latency_bps * bps_scale
    decomposed_cost_reserve = (
        exchange_fee_reserve
        + spread_reserve
        + slippage_reserve
        + market_impact_reserve
        + latency_reserve
    )
    stress_7_5_bps_reserve = _ALL_IN_STRESS_BPS[0] * bps_scale
    stress_10_bps_reserve = _ALL_IN_STRESS_BPS[1] * bps_scale
    stress_15_bps_reserve = _ALL_IN_STRESS_BPS[2] * bps_scale
    buy_bps_scale = required_buy_notional / 10_000.0
    cash_cost_reserve = max(
        policy.costs.decomposed_total_bps * buy_bps_scale,
        _ALL_IN_STRESS_BPS[2] * buy_bps_scale,
    )
    tolerance = max(1.0, snapshot.equity) * 1e-12
    sell_only_reduction = (
        required_sell_notional > tolerance and required_buy_notional <= tolerance
    )
    required_cash = (
        0.0
        if sell_only_reduction
        else required_buy_notional + cash_cost_reserve + policy.minimum_cash_reserve
    )
    if not sell_only_reduction and required_cash > snapshot.cash + tolerance:
        blockers.append("cash_reserve_limit")

    blockers_tuple = tuple(blockers)
    decision_id = hashlib.sha256(
        _canonical_json_bytes(
            {
                "snapshot_id": snapshot.snapshot_id,
                "policy_id": policy.policy_id,
                "intent_ids": intent_ids,
                "blockers": blockers_tuple,
            }
        )
    ).hexdigest()
    return TargetRiskDecision(
        decision_id=decision_id,
        allowed=not blockers_tuple,
        blockers=blockers_tuple,
        snapshot_id=snapshot.snapshot_id,
        policy_id=policy.policy_id,
        intent_ids=tuple(intent_ids),
        current_gross_target_exposure=current_gross_exposure,
        current_gross_notional=current_gross_notional,
        projected_gross_target_exposure=projected_gross_exposure,
        projected_gross_notional=projected_gross_notional,
        batch_turnover=batch_turnover,
        traded_notional=traded_notional,
        required_buy_notional=required_buy_notional,
        required_sell_notional=required_sell_notional,
        exchange_fee_reserve=exchange_fee_reserve,
        spread_reserve=spread_reserve,
        slippage_reserve=slippage_reserve,
        market_impact_reserve=market_impact_reserve,
        latency_reserve=latency_reserve,
        decomposed_cost_reserve=decomposed_cost_reserve,
        stress_7_5_bps_reserve=stress_7_5_bps_reserve,
        stress_10_bps_reserve=stress_10_bps_reserve,
        stress_15_bps_reserve=stress_15_bps_reserve,
        cash_cost_reserve=cash_cost_reserve,
        minimum_cash_reserve=policy.minimum_cash_reserve,
        required_cash=required_cash,
        available_cash=snapshot.cash,
        instrument_measures=tuple(measures),
    )
