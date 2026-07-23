from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol

from .execution_intent import TargetPositionIntent


class CompletedSignalCutoff(Protocol):
    """Provider-neutral completed-bar timing evidence accepted by the intent boundary."""

    instrument_id: str
    bar: str
    bar_open_utc: datetime | str
    bar_close_utc: datetime | str
    signal_not_before_utc: datetime | str


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


def build_target_position_intent(
    cutoff: CompletedSignalCutoff,
    *,
    strategy_id: str,
    strategy_revision: str,
    source_data_sha256: str,
    config_sha256: str,
    target_position: float,
    minimum_position: float,
    maximum_position: float,
) -> TargetPositionIntent:
    """Translate one verified completed-bar cutoff into one immutable target intent.

    The activation timestamp is copied from the cutoff and expiry is the next scheduled
    bar close. This function does not create an exchange order or make any price, spread,
    slippage, market-impact, latency, acceptance, or fill claim.
    """

    try:
        instrument_id = cutoff.instrument_id
        bar = cutoff.bar
        signal_bar_open = _required_utc_datetime(
            cutoff.bar_open_utc,
            field_name="signal cutoff bar_open_utc",
        )
        signal_bar_close = _required_utc_datetime(
            cutoff.bar_close_utc,
            field_name="signal cutoff bar_close_utc",
        )
        decision_not_before = _required_utc_datetime(
            cutoff.signal_not_before_utc,
            field_name="signal cutoff signal_not_before_utc",
        )
    except AttributeError as exc:
        raise TypeError("cutoff must implement the CompletedSignalCutoff contract") from exc

    bar_duration = signal_bar_close - signal_bar_open
    if bar_duration <= timedelta(0):
        raise ValueError("signal cutoff bar_close_utc must be after bar_open_utc")
    if bar == "1Dutc":
        if bar_duration != timedelta(days=1):
            raise ValueError("1Dutc signal cutoff must cover exactly one UTC day")
        if signal_bar_open != signal_bar_open.replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        ) or signal_bar_close != signal_bar_close.replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        ):
            raise ValueError("1Dutc signal cutoff must align to UTC midnight")

    if decision_not_before <= signal_bar_close:
        raise ValueError("signal cutoff signal_not_before_utc must be after the signal bar close")

    expires_at = signal_bar_close + bar_duration
    if decision_not_before >= expires_at:
        raise ValueError("signal cutoff is stale at or after the next scheduled bar close")

    return TargetPositionIntent(
        instrument_id=instrument_id,
        bar=bar,
        strategy_id=strategy_id,
        strategy_revision=strategy_revision,
        source_data_sha256=source_data_sha256,
        config_sha256=config_sha256,
        signal_bar_open_utc=signal_bar_open,
        signal_bar_close_utc=signal_bar_close,
        decision_not_before_utc=decision_not_before,
        expires_at_utc=expires_at,
        target_position=target_position,
        minimum_position=minimum_position,
        maximum_position=maximum_position,
    )
