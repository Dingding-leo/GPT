from __future__ import annotations

import pytest

from gpt_quant.okx_1h import (
    derive_okx_one_hour_page_budget,
    fetch_okx_one_hour_candles,
)


def test_five_year_one_hour_budget_exceeds_daily_default_without_network() -> None:
    pages = derive_okx_one_hour_page_budget(
        start="2021-07-24T00:00:00Z",
        end="2026-07-23T23:00:00Z",
    )

    assert pages == 441
    assert pages > 40


def test_one_hour_fetch_rejects_unaligned_boundaries_before_network() -> None:
    def unexpected_getter(url: str, timeout: float) -> dict[str, object]:
        pytest.fail(f"unaligned 1H request reached network: {url=} {timeout=}")

    with pytest.raises(ValueError, match="start must align to an exact UTC hour"):
        fetch_okx_one_hour_candles(
            inst_id="BTC-USDT",
            start="2021-07-24T00:30:00Z",
            end="2026-07-23T23:00:00Z",
            get_json=unexpected_getter,
        )
