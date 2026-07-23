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


def _longer_lookback(value: int, minimum: int) -> int:
    return max(minimum, round(value * 1.2))


def test_walk_forward_warmup_guide_matches_enforced_delayed_boundary() -> None:
    config = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    guide = _GUIDE_PATH.read_text(encoding="utf-8")
    backtest = _BACKTEST_PATH.read_text(encoding="utf-8")
    walk_forward = _WALK_FORWARD_PATH.read_text(encoding="utf-8")
    boundary_test = _BOUNDARY_TEST_PATH.read_text(encoding="utf-8")
    delayed_execution_test = _DELAYED_EXECUTION_TEST_PATH.read_text(encoding="utf-8")
    search = config["search"]
    strategy = config["strategy"]

    required_lookbacks = [
        *(_longer_lookback(value, 2) for value in search["momentum_lookbacks"]),
        *(_longer_lookback(value, 1) for value in search["reversal_lookbacks"]),
        strategy["volatility_lookback"],
    ]
    longest_required_lookback = max(required_lookbacks)
    executable_observations = search["selection_bars"] - longest_required_lookback - 1

    assert search["selection_bars"] >= longest_required_lookback + 2
    assert max(search["momentum_lookbacks"]) == 180
    assert _longer_lookback(max(search["momentum_lookbacks"]), 2) == 216
    assert _longer_lookback(max(search["reversal_lookbacks"]), 1) == 12
    assert longest_required_lookback == 216
    assert executable_observations == 513
    assert "target_position.shift(1)" in backtest

    guard = "if longest_lookback > selection_bars - 2:"
    first_candidate_backtest = "selection_frame = _run_cached_candidate_window("
    fold_initialization = "folds: list[dict[str, Any]] = []"
    assert "def _longer_lookbacks(" in walk_forward
    assert "max(candidate.volatility_lookback, *_longer_lookbacks(candidate))" in walk_forward
    assert guard in walk_forward
    assert "at least one one-bar-delayed" in walk_forward
    assert "selection-window observation after every candidate lookback" in walk_forward
    assert "and longer-lookback perturbation" in walk_forward
    assert walk_forward.index(guard) < walk_forward.index(first_candidate_backtest)
    assert walk_forward.index(guard) < walk_forward.index(fold_initialization)

    for dimension in ("momentum", "reversal", "volatility"):
        assert dimension in boundary_test
        assert dimension in delayed_execution_test
    assert '(("momentum", 248), ("reversal", 248)' in boundary_test
    assert '("volatility", _SELECTION_BARS - 2)' in boundary_test
    assert "test_walk_forward_rejects_underwarmed_longer_lookback_perturbation" in boundary_test
    assert '@pytest.mark.parametrize("lookback", (250, 251))' in boundary_test
    assert 'monkeypatch.setattr(walk_forward, "run_backtest", unexpected_backtest)' in boundary_test
    assert "perturbation warmup validation must run before cache population" in boundary_test

    assert "_SELECTION_BARS - 1" in delayed_execution_test
    assert "_SELECTION_BARS - 2" in delayed_execution_test
    assert 'last_executable["target_position"].iloc[-2] != 0.0' in delayed_execution_test
    assert 'last_executable["position"].iloc[-1] == pytest.approx(' in delayed_execution_test
    assert 'underwarmed["position"].eq(0.0).all()' in delayed_execution_test

    required_claims = (
        "selection_bars >= longest_required_lookback + 2",
        "selection_bars - longest_required_lookback - 1",
        "max(2, round(1.2 * m))",
        "max(1, round(1.2 * r))",
        "round(180 * 1.2) = 216",
        "730 - 216 - 1 = 513",
        "原始候选最大值 `180` 不是完整稳健性网格的最大 lookback",
        "longest_required_lookback= 216 executable_selection_observations= 513",
        "max(candidate.volatility_lookback, *_longer_lookbacks(candidate))",
        "and longer-lookback perturbation",
        "momentum/reversal 原始 lookback `248` 扩展为 `298`",
        "`250` 和 `251` 分别扩展为 `300` 和 `301`",
        "validation 和执行使用同一个 `_longer_lookbacks()` helper",
        "tests/test_walk_forward_lookback_boundary.py",
        "tests/test_walk_forward_delayed_execution_boundary.py",
        "任何 backtest 或 cache population 前被拒绝",
        "倒数第二行",
        "最后一行形成恰好一条延迟执行 position",
        "选择窗口内所有 position 都为零",
        "它验证执行对齐，不宣称现货 long/cash 候选",
        "不证明所有市场窗口都会产生非零 exposure",
        "不证明一条观测足以稳定估计候选或扰动指标",
    )
    for claim in required_claims:
        assert claim in guide

    obsolete_claims = (
        "max(momentum_lookbacks, reversal_lookbacks, strategy.volatility_lookback)",
        "730 - 180 - 1 = 549",
        "longest_lookback= 180 executable_selection_observations= 549",
        '"selection-window observation after every candidate lookback"\n    )',
    )
    for claim in obsolete_claims:
        assert claim not in guide
