from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from gpt_quant.execution_intent import TargetPositionIntent
from gpt_quant.okx_execution_quote import fetch_okx_top_of_book
from gpt_quant.okx_execution_quote_replay import ReconstructableOKXTopOfBookEvidence

_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "okx"
    / "order-book-btc-usdt-docs-20210826"
    / "response.json"
)
_EXPECTED_RESPONSE_SHA256 = "7d12a351f8f51320d1c8beee0063557e1c90388d66ac63412bf66ca544aeb3e3"
_INSTRUMENT_SNAPSHOT_SHA256 = "290bd86ecbb1683351993197b0ec18001dfb604b9ba1cb864d9d6d327855f0eb"


def _fixture_response() -> bytes:
    response = _FIXTURE.read_bytes()
    assert hashlib.sha256(response).hexdigest() == _EXPECTED_RESPONSE_SHA256
    return response


def _clock(*values: str):
    timestamps: Iterator[datetime] = iter(
        datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC) for value in values
    )
    return lambda: next(timestamps)


def _server_time_response() -> bytes:
    return b'{"code":"0","msg":"","data":[{"ts":"1629966436500"}]}'


def _intent() -> TargetPositionIntent:
    return TargetPositionIntent(
        instrument_id="BTC-USDT",
        bar="1Dutc",
        strategy_id="quote-clock-domain-regression",
        strategy_revision="1" * 40,
        source_data_sha256="2" * 64,
        config_sha256="3" * 64,
        signal_bar_open_utc=datetime(2021, 8, 25, tzinfo=UTC),
        signal_bar_close_utc=datetime(2021, 8, 26, tzinfo=UTC),
        decision_not_before_utc=datetime(2021, 8, 26, 8, 27, 16, 200_000, tzinfo=UTC),
        expires_at_utc=datetime(2021, 8, 26, 8, 27, 17, tzinfo=UTC),
        target_position=0.5,
        minimum_position=0.0,
        maximum_position=1.0,
    )


@pytest.mark.parametrize(
    ("clock_values", "expected_skew", "expected_local_observed", "expected_local_receipt"),
    [
        (
            (
                "2021-08-26T08:27:16.320000Z",
                "2021-08-26T08:27:16.350000Z",
                "2021-08-26T08:27:16.360000Z",
                "2021-08-26T08:27:16.440000Z",
            ),
            0.1,
            datetime(2021, 8, 26, 8, 27, 16, 296_000, tzinfo=UTC),
            datetime(2021, 8, 26, 8, 27, 16, 350_000, tzinfo=UTC),
        ),
        (
            (
                "2021-08-26T08:27:16.520000Z",
                "2021-08-26T08:27:16.550000Z",
                "2021-08-26T08:27:16.560000Z",
                "2021-08-26T08:27:16.640000Z",
            ),
            -0.1,
            datetime(2021, 8, 26, 8, 27, 16, 496_000, tzinfo=UTC),
            datetime(2021, 8, 26, 8, 27, 16, 550_000, tzinfo=UTC),
        ),
    ],
)
def test_quote_uses_one_local_clock_for_downstream_chronology(
    clock_values: tuple[str, ...],
    expected_skew: float,
    expected_local_observed: datetime,
    expected_local_receipt: datetime,
) -> None:
    observation = fetch_okx_top_of_book(
        instrument_id="BTC-USDT",
        instrument_snapshot_sha256=_INSTRUMENT_SNAPSHOT_SHA256,
        base_url="https://test.okx.com",
        maximum_quote_age_ms=200,
        max_abs_midpoint_clock_skew_seconds=0.2,
        get_bytes=lambda _url, _timeout: _fixture_response(),
        get_server_time_bytes=lambda _url, _timeout: _server_time_response(),
        now=_clock(*clock_values),
    )

    assert observation.midpoint_clock_skew_seconds == pytest.approx(expected_skew)
    assert observation.quote.observed_at_utc == expected_local_observed
    assert observation.quote.received_at_utc == expected_local_receipt
    assert observation.quote.received_at_utc == observation.response_received_utc

    decision_at = expected_local_receipt + timedelta(milliseconds=1)
    observation.quote.assert_usable_for(
        _intent(),
        decision_at_utc=decision_at,
        maximum_age_ms=200,
    )

    evidence = ReconstructableOKXTopOfBookEvidence(observation=observation)
    replayed = ReconstructableOKXTopOfBookEvidence.from_json_bytes(evidence.to_json_bytes())
    assert replayed.observation == observation
