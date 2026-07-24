from __future__ import annotations

import json
from pathlib import Path

from gpt_quant import StrategyConfig

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_DAILY_BARS_PER_YEAR = 365
_HOURLY_BARS_PER_DAY = 24


def _load_config(name: str) -> dict[str, object]:
    return json.loads((_REPOSITORY_ROOT / "config" / name).read_text(encoding="utf-8"))


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
    assert int(hourly_data["limit"]) * int(hourly_data["max_pages"]) >= (
        5 * _DAILY_BARS_PER_YEAR * _HOURLY_BARS_PER_DAY
    )

    validated = StrategyConfig(**hourly_strategy)
    assert validated.transaction_cost_bps == 5.0
    assert validated.annualization == _DAILY_BARS_PER_YEAR * _HOURLY_BARS_PER_DAY

    for key in ("momentum_lookback", "reversal_lookback", "volatility_lookback"):
        assert int(hourly_strategy[key]) == int(daily_strategy[key]) * _HOURLY_BARS_PER_DAY

    for key in ("momentum_lookbacks", "reversal_lookbacks"):
        assert hourly_search[key] == [
            int(value) * _HOURLY_BARS_PER_DAY for value in daily_search[key]
        ]

    assert int(hourly_search["selection_bars"]) == (
        int(daily_search["selection_bars"]) * _HOURLY_BARS_PER_DAY
    )
    assert int(hourly_search["test_bars"]) == (
        int(daily_search["test_bars"]) * _HOURLY_BARS_PER_DAY
    )
    assert hourly["robustness"] == {"cost_multipliers": [1.0]}


def test_workflow_executes_and_verifies_the_canonical_1h_profile() -> None:
    workflow = (
        _REPOSITORY_ROOT / ".github/workflows/intraday-1h-research.yml"
    ).read_text(encoding="utf-8")

    assert workflow.count("--config config/okx_research_1h.json") == 1
    assert workflow.count("reports/okx/1h/BTC-USDT") == 2
    assert "Run canonical BTC-USDT 1h full walk-forward research" in workflow
    assert "Verify persisted canonical BTC-USDT 1h evidence" in workflow
    assert "persist-credentials: false" in workflow
    assert "OKX_BASE_URL: https://www.okx.com" in workflow
