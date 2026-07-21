from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from gpt_quant.bootstrap import moving_block_indices, paired_moving_block_bootstrap


def _frame(strategy: np.ndarray, benchmark: np.ndarray) -> pd.DataFrame:
    return pd.DataFrame({"strategy_return": strategy, "benchmark_return": benchmark})


def test_moving_block_indices_are_contiguous_inside_each_block() -> None:
    indices = moving_block_indices(12, 4, np.random.default_rng(7))

    assert len(indices) == 12
    assert np.all(np.diff(indices.reshape(3, 4), axis=1) == 1)
    assert indices.min() >= 0
    assert indices.max() < 12


def test_paired_bootstrap_is_deterministic_and_preserves_zero_delta() -> None:
    returns = np.tile(np.array([0.01, -0.005, 0.002, -0.001]), 30)
    frame = _frame(returns, returns.copy())
    kwargs = {
        "strategy_column": "strategy_return",
        "benchmark_columns": {"benchmark": "benchmark_return"},
        "block_length": 4,
        "resamples": 200,
        "annualization": 365,
        "seed": 42,
    }

    first = paired_moving_block_bootstrap(frame, **kwargs)
    second = paired_moving_block_bootstrap(frame, **kwargs)

    assert first.to_dict() == second.to_dict()
    for metric in ("cagr", "sharpe", "calmar", "max_drawdown"):
        comparison = first.comparisons["benchmark"][metric]
        assert comparison["observed_delta"] == pytest.approx(0.0)
        assert comparison["ci_lower"] == pytest.approx(0.0)
        assert comparison["ci_upper"] == pytest.approx(0.0)
        assert comparison["lower_bound_positive"] is False
    assert first.hypothesis["verdict"] == "rejected"


def test_paired_bootstrap_detects_persistent_drawdown_reduction() -> None:
    benchmark = np.tile(np.array([0.02, 0.01, -0.12, 0.01, 0.02]), 60)
    strategy = benchmark * 0.25
    result = paired_moving_block_bootstrap(
        _frame(strategy, benchmark),
        strategy_column="strategy_return",
        benchmark_columns={"benchmark": "benchmark_return"},
        block_length=5,
        resamples=300,
        annualization=365,
        seed=19,
    )

    drawdown = result.comparisons["benchmark"]["max_drawdown"]
    assert drawdown["observed_delta"] > 0.0
    assert drawdown["ci_lower"] > 0.0
    assert drawdown["lower_bound_positive"] is True


def test_paired_bootstrap_rejects_non_finite_returns() -> None:
    frame = _frame(np.ones(40) * 0.001, np.ones(40) * 0.001)
    frame.loc[3, "strategy_return"] = np.nan

    with pytest.raises(ValueError, match="finite numeric"):
        paired_moving_block_bootstrap(
            frame,
            strategy_column="strategy_return",
            benchmark_columns={"benchmark": "benchmark_return"},
            block_length=5,
            resamples=100,
        )
