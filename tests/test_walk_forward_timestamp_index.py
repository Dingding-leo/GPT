from __future__ import annotations

import pandas as pd
import pytest

import gpt_quant.walk_forward_verify_gate as verify_gate


def test_timestamp_index_vectorizes_immutable_real_okx_utc_encodings(
    btc_usdt_prices: pd.Series,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_index = btc_usdt_prices.index[:500]
    returns_timestamps = pd.Series(source_index.map(lambda value: value.isoformat()))
    snapshot_timestamps = pd.Series(
        source_index.map(lambda value: value.strftime("%Y-%m-%dT%H:%M:%S.%fZ"))
    )
    expected = pd.DatetimeIndex(source_index, name="timestamp")

    def reject_scalar_fallback(_value: object, _label: str) -> pd.Timestamp:
        raise AssertionError("valid UTC evidence used the scalar timestamp fallback")

    monkeypatch.setattr(verify_gate, "_explicit_utc_timestamp", reject_scalar_fallback)

    assert verify_gate._timestamp_index(
        returns_timestamps, "walk-forward returns timestamp"
    ).equals(expected)
    assert verify_gate._timestamp_index(
        snapshot_timestamps, "normalized OKX snapshot timestamp"
    ).equals(expected)


@pytest.mark.parametrize(
    "timestamp",
    ["2026-07-20T00:00:00", "2026-07-20T01:00:00+01:00"],
)
def test_timestamp_index_keeps_non_utc_evidence_fail_closed(timestamp: str) -> None:
    values = pd.Series([timestamp])

    with pytest.raises(ValueError, match="explicit UTC offset"):
        verify_gate._timestamp_index(values, "walk-forward returns timestamp")


def test_timestamp_index_identifies_non_utc_row_after_valid_utc_evidence() -> None:
    values = pd.Series(
        [
            "2026-07-20T00:00:00+00:00",
            "2026-07-21T01:00:00+01:00",
        ]
    )

    with pytest.raises(ValueError, match="row 1 must include an explicit UTC offset"):
        verify_gate._timestamp_index(values, "walk-forward returns timestamp")
