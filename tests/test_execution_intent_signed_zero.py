from __future__ import annotations

from datetime import UTC, datetime

from gpt_quant.execution_intent import TargetPositionIntent

_SOURCE_ARTIFACT_SHA256 = "ab0846180ff5b9397de26de8ca8d728ad237be00bdb92ba1612ef6ba243fc149"
_CONFIG_SHA256 = "a0340ca26a0c5e7d0d609ddf69bcb3e4e643a93ab009f27ee03e8ea322aed822"
_MAIN_REVISION = "bd3bf844d0c37e2e65d6591cb2a3c4a03e6e45c3"


def _flat_intent(target_position: float) -> TargetPositionIntent:
    return TargetPositionIntent(
        instrument_id="BTC-USDT",
        bar="1Dutc",
        strategy_id="canonical-5bps-walk-forward",
        strategy_revision=_MAIN_REVISION,
        source_data_sha256=_SOURCE_ARTIFACT_SHA256,
        config_sha256=_CONFIG_SHA256,
        signal_bar_open_utc=datetime(2026, 7, 22, tzinfo=UTC),
        signal_bar_close_utc=datetime(2026, 7, 23, tzinfo=UTC),
        decision_not_before_utc=datetime(2026, 7, 23, 0, 0, 3, tzinfo=UTC),
        expires_at_utc=datetime(2026, 7, 24, tzinfo=UTC),
        target_position=target_position,
        minimum_position=0.0,
        maximum_position=1.0,
    )


def test_flat_target_signed_zero_has_one_idempotency_identity() -> None:
    positive_zero = _flat_intent(0.0)
    negative_zero = _flat_intent(-0.0)

    assert positive_zero.target_position == negative_zero.target_position == 0.0
    assert positive_zero.intent_id == negative_zero.intent_id
    assert positive_zero.to_json_bytes() == negative_zero.to_json_bytes()
