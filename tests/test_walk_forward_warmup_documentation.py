from __future__ import annotations

import json
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_CONFIG_PATH = _REPOSITORY_ROOT / "config" / "okx_research.json"
_GUIDE_PATH = _REPOSITORY_ROOT / "docs" / "WALK_FORWARD_WARMUP.md"
_BACKTEST_PATH = _REPOSITORY_ROOT / "src" / "gpt_quant" / "backtest.py"
_WALK_FORWARD_PATH = _REPOSITORY_ROOT / "src" / "gpt_quant" / "walk_forward.py"
_BOUNDARY_TEST_PATH = _REPOSITORY_ROOT / "tests" / "test_walk_forward_lookback_boundary.py"
_DELAYED_EXECUTION_TEST_PATH = (
    _REPOSITORY_ROOT / "tests" / "test_walk_forward_delayed_execution_boundary.py"
)


def test_walk_forward_warmup_guide_matches_enforced_delayed_boundary() -> None:
    config = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    guide = _GUIDE_PATH.read_text(encoding="utf-8")
    backtest = _BACKTEST_PATH.read_text(encoding="utf-8")
    walk_forward = _WALK_FORWARD_PATH.read_text(encoding="utf-8")
    boundary_test = _BOUNDARY_TEST_PATH.read_text(encoding="utf-8")
    delayed_execution_test = _DELAYED_EXECUTION_TEST_PATH.read_text(encoding="utf-8")
    search = config["search"]
    strategy = config["strategy"]

    candidate_lookbacks = [
        *search["momentum_lookbacks"],
        *search["reversal_lookbacks"],
        strategy["volatility_lookback"],
    ]
    longest_lookback = max(candidate_lookbacks)
    executable_observations = search["selection_bars"] - longest_lookback - 1

    assert search["selection_bars"] >= longest_lookback + 2
    assert longest_lookback == 180
    assert executable_observations == 549
    assert "target_position.shift(1)" in backtest

    guard = "if longest_lookback > selection_bars - 2:"
    fold_initialization = "folds: list[dict[str, Any]] = []"
    assert guard in walk_forward
    assert "at least one one-bar-delayed" in walk_forward
    assert "selection-window observation after every candidate lookback" in walk_forward
    assert walk_forward.index(guard) < walk_forward.index(fold_initialization)

    for dimension in ("momentum", "reversal", "volatility"):
        assert dimension in boundary_test
        assert dimension in delayed_execution_test
    assert "_SELECTION_BARS - 1" in boundary_test
    assert "_SELECTION_BARS - 2" in boundary_test
    assert 'monkeypatch.setattr(walk_forward, "run_backtest", unexpected_backtest)' in boundary_test

    assert "_SELECTION_BARS - 1" in delayed_execution_test
    assert "_SELECTION_BARS - 2" in delayed_execution_test
    assert 'last_executable["target_position"].iloc[-2] != 0.0' in delayed_execution_test
    assert 'last_executable["position"].iloc[-1] == pytest.approx(' in delayed_execution_test
    assert 'underwarmed["position"].eq(0.0).all()' in delayed_execution_test

    required_claims = (
        "selection_bars >= longest_candidate_lookback + 2",
        "selection_bars - longest_candidate_lookback - 1",
        "max(momentum_lookbacks, reversal_lookbacks, strategy.volatility_lookback)",
        "730 - 180 - 1 = 549",
        "selection window has no delayed executable observation",
        "longest_lookback= 180 executable_selection_observations= 549",
        "if longest_lookback > selection_bars - 2:",
        "selection_bars must provide at least one one-bar-delayed",
        "`lookback = selection_bars - 1`",
        "`lookback = selection_bars - 2`",
        "tests/test_walk_forward_lookback_boundary.py",
        "tests/test_walk_forward_delayed_execution_boundary.py",
        "倒数第二行",
        "最后一行形成恰好一条延迟执行 position",
        "选择窗口内所有 position 都为零",
        "它验证执行对齐，不宣称现货 long/cash 候选",
        "不证明所有市场窗口都会产生非零 exposure",
        "不证明窗口足够长、候选排名稳定、策略显著优于基准",
    )
    for claim in required_claims:
        assert claim in guide

    assert "issue #196" not in guide
    assert "不会单独检查该唯一延迟观测的仓位值" not in guide
    assert "目前只拒绝 `selection_bars <= longest_lookback`" not in guide
