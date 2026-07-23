from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from gpt_quant.execution_intent import TargetPositionIntent

_SOURCE_ARTIFACT_SHA256 = "ab0846180ff5b9397de26de8ca8d728ad237be00bdb92ba1612ef6ba243fc149"
_CONFIG_SHA256 = "a0340ca26a0c5e7d0d609ddf69bcb3e4e643a93ab009f27ee03e8ea322aed822"
_MAIN_REVISION = "bd3bf844d0c37e2e65d6591cb2a3c4a03e6e45c3"


def _intent(**overrides: object) -> TargetPositionIntent:
    values: dict[str, object] = {
        "instrument_id": "BTC-USDT",
        "bar": "1Dutc",
        "strategy_id": "canonical-5bps-walk-forward",
        "strategy_revision": _MAIN_REVISION,
        "source_data_sha256": _SOURCE_ARTIFACT_SHA256,
        "config_sha256": _CONFIG_SHA256,
        "signal_bar_open_utc": datetime(2026, 7, 22, tzinfo=UTC),
        "signal_bar_close_utc": datetime(2026, 7, 23, tzinfo=UTC),
        "decision_not_before_utc": datetime(2026, 7, 23, 0, 0, 3, tzinfo=UTC),
        "expires_at_utc": datetime(2026, 7, 24, tzinfo=UTC),
        "target_position": 0.5393,
        "minimum_position": 0.0,
        "maximum_position": 1.0,
    }
    values.update(overrides)
    return TargetPositionIntent(**values)


def test_target_position_intent_is_deterministic_and_replayable() -> None:
    intent = _intent()
    equivalent = _intent(
        signal_bar_open_utc="2026-07-22T09:30:00+09:30",
        signal_bar_close_utc="2026-07-23T09:30:00+09:30",
        decision_not_before_utc="2026-07-23T09:30:03+09:30",
        expires_at_utc="2026-07-24T09:30:00+09:30",
    )

    assert intent.intent_id == equivalent.intent_id
    assert intent.to_json_bytes() == equivalent.to_json_bytes()
    assert TargetPositionIntent.from_json_bytes(intent.to_json_bytes()) == intent
    assert intent.to_json_bytes().endswith(b"\n")
    assert json.loads(intent.to_json_bytes())["schema_version"] == 1
    intent.assert_active_at("2026-07-23T09:30:03+09:30")


def test_target_position_intent_detects_payload_tampering() -> None:
    intent = _intent()
    payload = intent.to_dict()
    payload["target_position"] = 0.75

    with pytest.raises(ValueError, match="ID does not match"):
        TargetPositionIntent.from_mapping(payload)

    changed_source = _intent(source_data_sha256="0" * 64)
    changed_config = _intent(config_sha256="1" * 64)
    changed_target = _intent(target_position=0.75)
    intent_ids = {
        intent.intent_id,
        changed_source.intent_id,
        changed_config.intent_id,
        changed_target.intent_id,
    }
    assert len(intent_ids) == 4


def test_target_position_intent_fails_closed_on_invalid_live_boundaries() -> None:
    with pytest.raises(ValueError, match="cannot precede"):
        _intent(decision_not_before_utc=datetime(2026, 7, 22, 23, 59, 59, tzinfo=UTC))
    with pytest.raises(ValueError, match="expires_at_utc"):
        _intent(expires_at_utc=datetime(2026, 7, 23, 0, 0, 3, tzinfo=UTC))
    with pytest.raises(ValueError, match="declared position limits"):
        _intent(target_position=1.01)
    with pytest.raises(ValueError, match="finite real"):
        _intent(target_position=float("nan"))
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        _intent(source_data_sha256="not-a-hash")

    active = _intent()
    with pytest.raises(ValueError, match="not active yet"):
        active.assert_active_at("2026-07-23T00:00:02Z")
    with pytest.raises(ValueError, match="expired"):
        active.assert_active_at("2026-07-24T00:00:00Z")

    payload = _intent().to_dict()
    payload["unexpected"] = True
    with pytest.raises(ValueError, match="unexpected"):
        TargetPositionIntent.from_mapping(payload)

    expired = _intent(expires_at_utc=datetime(2026, 7, 23, 0, 0, 4, tzinfo=UTC))
    assert expired.expires_at_utc - expired.decision_not_before_utc == timedelta(seconds=1)


def test_target_position_intent_rejects_noncanonical_or_ambiguous_json() -> None:
    intent = _intent()
    canonical = intent.to_json_bytes().decode("utf-8")

    noncanonical = json.dumps(intent.to_dict(), indent=2, sort_keys=False)
    with pytest.raises(ValueError, match="canonical encoding"):
        TargetPositionIntent.from_json_bytes(noncanonical)

    duplicate = canonical.replace(
        '"bar":"1Dutc"',
        '"bar":"1Dutc","bar":"1Dutc"',
        1,
    )
    with pytest.raises(ValueError, match="unreadable"):
        TargetPositionIntent.from_json_bytes(duplicate)
