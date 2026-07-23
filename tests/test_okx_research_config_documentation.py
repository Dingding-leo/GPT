from __future__ import annotations

import json
import math
from numbers import Real
from pathlib import Path

import pytest

from gpt_quant import StrategyConfig

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_CONFIG_PATH = _REPOSITORY_ROOT / "config" / "okx_research.json"
_HOLDOUT_CONFIG_PATH = _REPOSITORY_ROOT / "config" / "okx_holdout.json"
_GUIDE_PATH = _REPOSITORY_ROOT / "docs" / "OKX_RESEARCH_CONFIG.md"
_README_PATH = _REPOSITORY_ROOT / "README.md"


def test_okx_research_config_reference_matches_current_strategy_types() -> None:
    config = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    guide = _GUIDE_PATH.read_text(encoding="utf-8")
    strategy = config["strategy"]

    resolved = StrategyConfig(**strategy).to_dict()
    assert resolved == strategy

    for field in (
        "momentum_lookback",
        "reversal_lookback",
        "volatility_lookback",
        "annualization",
    ):
        assert isinstance(strategy[field], int)
        assert not isinstance(strategy[field], bool)
    for field in (
        "target_volatility",
        "max_abs_position",
        "min_position",
        "trend_weight",
        "reversal_weight",
        "transaction_cost_bps",
    ):
        assert isinstance(strategy[field], Real)
        assert not isinstance(strategy[field], bool)

    assert strategy["min_position"] == 0.0
    assert 0.0 < strategy["target_volatility"] <= 2.0
    assert 0.0 < strategy["max_abs_position"] <= 10.0
    assert strategy["trend_weight"] >= 0.0
    assert strategy["reversal_weight"] >= 0.0
    assert strategy["trend_weight"] + strategy["reversal_weight"] > 0.0
    assert strategy["transaction_cost_bps"] >= 0.0

    required_claims = (
        "`strategy` 参数",
        "`momentum_lookback` | integer",
        "`annualization` | integer",
        "`target_volatility` | number",
        "`max_abs_position` | number",
        "`min_position` | number 或 `null`",
        "两个 signal weight 不能同时为零",
        "OKX 现货长仓/现金基线必须显式使用 `0.0`",
        "JSON 数字 `90.0` 与整数 `90` 在 timing controls 中不是同一种声明",
        "tests/test_strategy_config_type_validation.py",
    )
    for claim in required_claims:
        assert claim in guide


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("momentum_lookback", 90.0),
        ("reversal_lookback", "5"),
        ("volatility_lookback", True),
        ("annualization", 365.0),
        ("target_volatility", "0.5"),
        ("max_abs_position", False),
        ("min_position", "0.0"),
        ("trend_weight", True),
        ("reversal_weight", "0.3"),
        ("transaction_cost_bps", False),
    ],
)
def test_documented_strategy_type_errors_fail_closed(field: str, value: object) -> None:
    config = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    strategy = dict(config["strategy"])
    strategy[field] = value

    with pytest.raises(ValueError):
        StrategyConfig(**strategy)


def test_documented_strategy_cross_field_constraints_fail_closed() -> None:
    config = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    strategy = dict(config["strategy"])

    outside_position_limit = dict(strategy, min_position=1.01)
    with pytest.raises(ValueError, match="min_position"):
        StrategyConfig(**outside_position_limit)

    zero_signal = dict(strategy, trend_weight=0.0, reversal_weight=0.0)
    with pytest.raises(ValueError, match="at least one signal weight"):
        StrategyConfig(**zero_signal)


def test_okx_research_config_reference_matches_current_control_types() -> None:
    config = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    guide = _GUIDE_PATH.read_text(encoding="utf-8")
    search = config["search"]
    robustness = config["robustness"]

    assert isinstance(search["selection_bars"], int)
    assert not isinstance(search["selection_bars"], bool)
    assert search["selection_bars"] >= 100
    assert isinstance(search["test_bars"], int)
    assert not isinstance(search["test_bars"], bool)
    assert search["test_bars"] >= 20

    for value in search["momentum_lookbacks"]:
        assert isinstance(value, int)
        assert not isinstance(value, bool)
        assert value >= 2
    for value in search["reversal_lookbacks"]:
        assert isinstance(value, int)
        assert not isinstance(value, bool)
        assert value >= 1
    for value in search["trend_weights"]:
        assert isinstance(value, Real)
        assert not isinstance(value, bool)
        assert 0.0 <= value <= 1.0
    for value in robustness["cost_multipliers"]:
        assert isinstance(value, Real)
        assert not isinstance(value, bool)
        assert value > 0.0

    required_claims = (
        "配置值的 **JSON 类型是研究协议的一部分**",
        "`selection_bars` | integer",
        "`test_bars` | integer",
        "JSON 数字 `90.0` 与整数 `90` 在研究协议中不是同一种声明",
        "`cost_multipliers` 必须是 JSON array",
        '字符串，例如 `"2"`',
        "布尔值，例如 `true`",
        "确保 `1.0` 和 `2.0` 两个压力倍数存在",
        "tests/test_walk_forward_control_validation.py",
    )
    for claim in required_claims:
        assert claim in guide


def test_okx_holdout_config_reference_matches_candidate_and_ranking_controls() -> None:
    rolling = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    holdout = json.loads(_HOLDOUT_CONFIG_PATH.read_text(encoding="utf-8"))
    guide = _GUIDE_PATH.read_text(encoding="utf-8")
    search = holdout["search"]

    assert holdout["strategy"] == rolling["strategy"]
    for field in ("momentum_lookbacks", "reversal_lookbacks", "trend_weights"):
        assert search[field] == rolling["search"][field]

    assert all(
        isinstance(value, int) and not isinstance(value, bool) and value >= 2
        for value in search["momentum_lookbacks"]
    )
    assert all(
        isinstance(value, int) and not isinstance(value, bool) and value >= 1
        for value in search["reversal_lookbacks"]
    )
    assert all(
        isinstance(value, Real) and not isinstance(value, bool) and 0.0 <= value <= 1.0
        for value in search["trend_weights"]
    )

    for field in ("validation_fraction", "holdout_fraction"):
        value = search[field]
        assert isinstance(value, Real)
        assert not isinstance(value, bool)
        assert math.isfinite(float(value))
        assert 0.05 <= value <= 0.40
    assert search["validation_fraction"] + search["holdout_fraction"] < 0.80

    top_candidates = search["top_candidates"]
    assert isinstance(top_candidates, int)
    assert not isinstance(top_candidates, bool)
    assert top_candidates >= 1

    candidates_tested = (
        len(search["momentum_lookbacks"])
        * len(search["reversal_lookbacks"])
        * len(search["trend_weights"])
    )
    assert candidates_tested == 27
    assert top_candidates == 10
    assert candidates_tested > top_candidates

    required_claims = (
        "固定 holdout 的切分、候选与 ranking 控制",
        "`validation_fraction` | number",
        "`holdout_fraction` | number",
        "位于 `[0.05, 0.40]`",
        "和必须严格小于 `0.80`",
        '不再对 `"0.2"`、`true` 或其他错误类型调用 `float(...)`',
        "价格校验、候选回测和报告目录创建前失败",
        "`top_candidates` | integer",
        "`candidate_ranking`",
        "`candidates_tested`",
        "`3 × 3 × 3 = 27`",
        "配置保存前 `10` 名",
        "python -m json.tool config/okx_holdout.json",
        "tests/test_holdout_candidate_validation.py",
    )
    for claim in required_claims:
        assert claim in guide


def test_readme_links_to_okx_research_config_reference() -> None:
    readme = _README_PATH.read_text(encoding="utf-8")
    reference = "[`docs/OKX_RESEARCH_CONFIG.md`](docs/OKX_RESEARCH_CONFIG.md)"

    assert readme.count(reference) == 1
