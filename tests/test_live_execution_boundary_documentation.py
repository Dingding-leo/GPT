from __future__ import annotations

import json
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_CONFIG_PATH = _REPOSITORY_ROOT / "config" / "okx_research.json"
_GUIDE_PATH = _REPOSITORY_ROOT / "docs" / "LIVE_EXECUTION_BOUNDARY.md"
_README_PATH = _REPOSITORY_ROOT / "README.md"
_BACKTEST_PATH = _REPOSITORY_ROOT / "src" / "gpt_quant" / "backtest.py"
_FEATURES_PATH = _REPOSITORY_ROOT / "src" / "gpt_quant" / "features.py"
_OKX_PATH = _REPOSITORY_ROOT / "src" / "gpt_quant" / "okx.py"


def test_live_execution_boundary_matches_current_code_and_config() -> None:
    config = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    guide = _GUIDE_PATH.read_text(encoding="utf-8")
    readme = _README_PATH.read_text(encoding="utf-8")
    backtest = _BACKTEST_PATH.read_text(encoding="utf-8")
    features = _FEATURES_PATH.read_text(encoding="utf-8")
    okx = _OKX_PATH.read_text(encoding="utf-8")

    assert config["data"]["bar"] == "1Dutc"
    assert config["strategy"]["transaction_cost_bps"] == 10.0
    assert config["robustness"]["cost_multipliers"] == [1.0, 2.0, 4.0]

    assert "using information through time t" in features
    assert "lag this target by one bar" in features
    assert "target_position.shift(1)" in backtest
    assert "clean.pct_change()" in backtest
    assert "turnover * config.transaction_cost_bps / 10_000.0" in backtest
    assert "position * asset_return - trading_cost" in backtest
    assert 'bar == "1Dutc"' in okx
    assert "aligned to midnight UTC" in okx
    assert 'parsed.loc[parsed["confirm"] == "1"]' in okx

    required_claims = (
        "一根 bar 的记账延迟，不是 next-open 成交模型",
        "position_t        = target_position_{t-1}",
        "asset_return_t    = close_t / close_{t-1} - 1",
        "trading_cost_t    = turnover_t * transaction_cost_bps / 10000",
        "strategy_return_t = position_t * asset_return_t - trading_cost_t",
        "当前默认配置为",
        "transaction_cost_bps = 10.0",
        "cost_multipliers = [1.0, 2.0, 4.0]",
        "不包含独立的",
        "exchange fee",
        "bid-ask spread",
        "slippage",
        "market impact",
        "latency cost",
        "不得把当前默认配置描述为 `5 bps` 基线",
        "完整 walk-forward 候选选择与 OOS 评估",
        "只给已持久化仓位重新计费不能替代 full reselection",
        "没有可执行的 paper-run 或 live-run 命令",
        "不读取账户，不创建 order intent，不模拟订单生命周期，也不发送订单",
        "这些命令只验证文档与当前代码/配置一致",
    )
    for claim in required_claims:
        assert claim in guide

    forbidden_claims = (
        "当前默认配置为每单位换手 5 bps",
        "当前回测按 next-open 成交",
        "当前仓库已经支持 paper broker",
        "当前仓库已经支持 live order",
    )
    for claim in forbidden_claims:
        assert claim not in guide

    assert "docs/LIVE_EXECUTION_BOUNDARY.md" in readme
