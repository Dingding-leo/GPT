from __future__ import annotations

import json
from pathlib import Path

import pytest

from gpt_quant.okx import _fixed_bar_step_seconds, fetch_okx_history_candles

_FIXTURE = Path(__file__).parent / "fixtures" / "okx" / "btc-usdt-1dutc" / "raw.json"


@pytest.mark.parametrize(
    ("bar", "expected_seconds"),
    [
        ("1s", 1),
        ("1m", 60),
        ("2H", 2 * 60 * 60),
        ("3Dutc", 3 * 24 * 60 * 60),
        ("1Wutc", 7 * 24 * 60 * 60),
        ("1M", None),
        ("3Mutc", None),
    ],
)
def test_okx_classifies_fixed_and_calendar_bars(
    bar: str,
    expected_seconds: int | None,
) -> None:
    assert _fixed_bar_step_seconds(bar) == expected_seconds


@pytest.mark.parametrize("bar", ["1M", "3Mutc"])
def test_okx_rejects_calendar_bars_before_request(bar: str) -> None:
    def unexpected_getter(url: str, timeout: float) -> dict[str, object]:
        pytest.fail(f"calendar bar reached network getter: {url=} {timeout=}")

    with pytest.raises(ValueError, match="calendar and unknown intervals are rejected"):
        fetch_okx_history_candles(bar=bar, get_json=unexpected_getter)


def test_okx_rejects_sparse_daily_history_using_declared_bar_cadence() -> None:
    source_page = json.loads(_FIXTURE.read_text(encoding="utf-8"))[0]
    sparse_page = {**source_page, "data": source_page["data"][::2]}

    def fake_getter(url: str, timeout: float) -> dict[str, object]:
        assert timeout == 20.0
        return sparse_page

    with pytest.raises(ValueError, match="missing 2 expected intervals.*1Dutc"):
        fetch_okx_history_candles(
            inst_id="BTC-USDT",
            bar="1Dutc",
            limit=100,
            max_pages=1,
            pause_seconds=0.0,
            get_json=fake_getter,
        )
