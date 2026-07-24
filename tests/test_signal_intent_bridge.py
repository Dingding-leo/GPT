from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

import pytest

from gpt_quant.signal_intent import build_target_position_intent

_SOURCE_DATA_SHA256 = "dcb30e58e10f8415aefe8c206f99c21fc8862b3b4f5ea65679a01262980c5481"
_CONFIG_SHA256 = "a0340ca26a0c5e7d0d609ddf69bcb3e4e643a93ab009f27ee03e8ea322aed822"
_STRATEGY_REVISION = "82bd124f49b0d183ce723303b114bbe934b10cb6"
_DAILY_INTENT_ID = "918a4eeab9e29593d6f716e6cf0d865e02cc2e9e8b008441ba69e99a539624e5"
_HOURLY_INTENT_ID = "85295c6d4108c7ad63eca8162735953f8b4a528d0c50ef890cec5734059b2fcf"


@dataclass(frozen=True, slots=True)
class _CompletedSignalCutoff:
    instrument_id: str = "BTC-USDT"
    bar: str = "1Dutc"
    bar_open_utc: datetime | str = datetime(2026, 7, 21, tzinfo=UTC)
    bar_close_utc: datetime | str = datetime(2026, 7, 22, tzinfo=UTC)
    signal_not_before_utc: datetime | str = datetime(2026, 7, 22, 0, 0, 1, tzinfo=UTC)


def _build(cutoff: object, **overrides: object):
    values: dict[str, object] = {
        "strategy_id": "canonical-5bps-walk-forward",
        "strategy_revision": _STRATEGY_REVISION,
        "source_data_sha256": _SOURCE_DATA_SHA256,
        "config_sha256": _CONFIG_SHA256,
        "target_position": 0.5393,
        "minimum_position": 0.0,
        "maximum_position": 1.0,
    }
    values.update(overrides)
    return build_target_position_intent(cutoff, **values)


def test_completed_signal_cutoff_maps_to_one_deterministic_intent_window() -> None:
    cutoff = _CompletedSignalCutoff()
    adelaide = timezone(timedelta(hours=9, minutes=30))
    equivalent = _CompletedSignalCutoff(
        bar_open_utc="2026-07-21T09:30:00+09:30",
        bar_close_utc="2026-07-22T09:30:00+09:30",
        signal_not_before_utc="2026-07-22T09:30:01+09:30",
    )

    intent = _build(cutoff)
    replayed = _build(equivalent)

    assert intent.intent_id == _DAILY_INTENT_ID
    assert intent.intent_id == replayed.intent_id
    assert intent.to_json_bytes() == replayed.to_json_bytes()
    assert intent.signal_bar_open_utc == datetime(2026, 7, 21, tzinfo=UTC)
    assert intent.signal_bar_close_utc == datetime(2026, 7, 22, tzinfo=UTC)
    assert intent.decision_not_before_utc == datetime(2026, 7, 22, 0, 0, 1, tzinfo=UTC)
    assert intent.expires_at_utc == datetime(2026, 7, 23, tzinfo=UTC)
    assert intent.signal_bar_open_utc.astimezone(adelaide).hour == 9


def test_hourly_signal_cutoff_maps_to_one_deterministic_intent_window() -> None:
    cutoff = _CompletedSignalCutoff(
        bar="1H",
        bar_open_utc=datetime(2026, 7, 22, 12, tzinfo=UTC),
        bar_close_utc=datetime(2026, 7, 22, 13, tzinfo=UTC),
        signal_not_before_utc=datetime(2026, 7, 22, 13, 0, 1, tzinfo=UTC),
    )
    equivalent = _CompletedSignalCutoff(
        bar="1H",
        bar_open_utc="2026-07-22T21:30:00+09:30",
        bar_close_utc="2026-07-22T22:30:00+09:30",
        signal_not_before_utc="2026-07-22T22:30:01+09:30",
    )

    intent = _build(cutoff)
    replayed = _build(equivalent)

    assert intent.intent_id == _HOURLY_INTENT_ID
    assert intent.intent_id == replayed.intent_id
    assert intent.to_json_bytes() == replayed.to_json_bytes()
    assert intent.bar == "1H"
    assert intent.signal_bar_open_utc == datetime(2026, 7, 22, 12, tzinfo=UTC)
    assert intent.signal_bar_close_utc == datetime(2026, 7, 22, 13, tzinfo=UTC)
    assert intent.decision_not_before_utc == datetime(2026, 7, 22, 13, 0, 1, tzinfo=UTC)
    assert intent.expires_at_utc == datetime(2026, 7, 22, 14, tzinfo=UTC)


def test_completed_signal_cutoff_rejects_activation_at_bar_close() -> None:
    cutoff = _CompletedSignalCutoff(
        signal_not_before_utc=datetime(2026, 7, 22, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="after the signal bar close"):
        _build(cutoff)


def test_completed_signal_cutoff_rejects_stale_activation() -> None:
    cutoff = _CompletedSignalCutoff(
        signal_not_before_utc=datetime(2026, 7, 23, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="stale"):
        _build(cutoff)


def test_completed_signal_cutoff_rejects_inconsistent_1dutc_window() -> None:
    cutoff = _CompletedSignalCutoff(
        bar_close_utc=datetime(2026, 7, 21, 23, 59, 59, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="exactly one UTC day"):
        _build(cutoff)


def test_completed_signal_cutoff_rejects_misaligned_1dutc_window() -> None:
    cutoff = _CompletedSignalCutoff(
        bar_open_utc=datetime(2026, 7, 21, 0, 0, 1, tzinfo=UTC),
        bar_close_utc=datetime(2026, 7, 22, 0, 0, 1, tzinfo=UTC),
        signal_not_before_utc=datetime(2026, 7, 22, 0, 0, 2, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="align to UTC midnight"):
        _build(cutoff)


def test_hourly_signal_cutoff_rejects_inconsistent_window() -> None:
    cutoff = _CompletedSignalCutoff(
        bar="1H",
        bar_open_utc=datetime(2026, 7, 22, 12, tzinfo=UTC),
        bar_close_utc=datetime(2026, 7, 22, 12, 59, 59, tzinfo=UTC),
        signal_not_before_utc=datetime(2026, 7, 22, 13, 0, 1, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="exactly one hour"):
        _build(cutoff)


def test_hourly_signal_cutoff_rejects_misaligned_window() -> None:
    cutoff = _CompletedSignalCutoff(
        bar="1H",
        bar_open_utc=datetime(2026, 7, 22, 12, 0, 1, tzinfo=UTC),
        bar_close_utc=datetime(2026, 7, 22, 13, 0, 1, tzinfo=UTC),
        signal_not_before_utc=datetime(2026, 7, 22, 13, 0, 2, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="align to exact UTC hours"):
        _build(cutoff)


def test_signal_cutoff_rejects_unapproved_intraday_bar() -> None:
    cutoff = _CompletedSignalCutoff(
        bar="15m",
        bar_open_utc=datetime(2026, 7, 22, 12, tzinfo=UTC),
        bar_close_utc=datetime(2026, 7, 22, 12, 15, tzinfo=UTC),
        signal_not_before_utc=datetime(2026, 7, 22, 12, 15, 1, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="unsupported completed signal bar '15m'"):
        _build(cutoff)


def test_completed_signal_cutoff_contract_and_position_limits_fail_closed() -> None:
    with pytest.raises(TypeError, match="CompletedSignalCutoff"):
        _build(object())

    with pytest.raises(ValueError, match="declared position limits"):
        _build(_CompletedSignalCutoff(), target_position=1.01)
