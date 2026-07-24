from __future__ import annotations

import json
from pathlib import Path

from gpt_quant import StrategyConfig

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_DAILY_BARS_PER_YEAR = 365
_HOURLY_BARS_PER_DAY = 24
_CANONICAL_INTRADAY_INSTRUMENTS = ("BTC-USDT", "ETH-USDT")


def _load_config(name: str) -> dict[str, object]:
    path = _REPOSITORY_ROOT / "config" / name
    return json.loads(path.read_text(encoding="utf-8"))


def test_canonical_1h_profile_preserves_daily_horizons_at_five_bps() -> None:
    daily = _load_config("okx_research.json")
    hourly = _load_config("okx_research_1h.json")

    daily_data = daily["data"]
    hourly_data = hourly["data"]
    daily_strategy = daily["strategy"]
    hourly_strategy = hourly["strategy"]
    daily_search = daily["search"]
    hourly_search = hourly["search"]

    assert isinstance(daily_data, dict)
    assert isinstance(hourly_data, dict)
    assert isinstance(daily_strategy, dict)
    assert isinstance(hourly_strategy, dict)
    assert isinstance(daily_search, dict)
    assert isinstance(hourly_search, dict)

    assert hourly_data["bar"] == "1H"
    page_capacity = int(hourly_data["limit"]) * int(hourly_data["max_pages"])
    minimum_five_year_bars = 5 * _DAILY_BARS_PER_YEAR * _HOURLY_BARS_PER_DAY
    assert page_capacity >= minimum_five_year_bars

    validated = StrategyConfig(**hourly_strategy)
    assert validated.transaction_cost_bps == 5.0
    assert validated.annualization == _DAILY_BARS_PER_YEAR * _HOURLY_BARS_PER_DAY

    for key in ("momentum_lookback", "reversal_lookback", "volatility_lookback"):
        expected = int(daily_strategy[key]) * _HOURLY_BARS_PER_DAY
        assert int(hourly_strategy[key]) == expected

    for key in ("momentum_lookbacks", "reversal_lookbacks"):
        expected = [int(value) * _HOURLY_BARS_PER_DAY for value in daily_search[key]]
        assert hourly_search[key] == expected

    expected_selection_bars = int(daily_search["selection_bars"]) * _HOURLY_BARS_PER_DAY
    expected_test_bars = int(daily_search["test_bars"]) * _HOURLY_BARS_PER_DAY
    assert int(hourly_search["selection_bars"]) == expected_selection_bars
    assert int(hourly_search["test_bars"]) == expected_test_bars
    assert hourly["robustness"] == {"cost_multipliers": [1.0]}


def test_workflow_reselects_and_verifies_btc_and_eth_independently() -> None:
    path = _REPOSITORY_ROOT / ".github/workflows/intraday-1h-research.yml"
    workflow = path.read_text(encoding="utf-8")

    matrix = f"inst_id: [{', '.join(_CANONICAL_INTRADAY_INSTRUMENTS)}]"
    assert workflow.count(matrix) == 1
    assert workflow.count("--config config/okx_research_1h.json") == 1
    assert workflow.count('--inst-id "${{ matrix.inst_id }}"') == 1
    assert workflow.count('reports/okx/1h/${{ matrix.inst_id }}') == 5
    assert workflow.count("experiment-manifest.jsonl") == 2
    assert "Run canonical 1h full walk-forward research" in workflow
    assert "Verify persisted canonical 1h evidence" in workflow
    assert "fail-fast: false" in workflow
    assert "persist-credentials: false" in workflow
    assert "OKX_BASE_URL: https://www.okx.com" in workflow
