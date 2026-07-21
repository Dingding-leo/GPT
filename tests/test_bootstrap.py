from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from gpt_quant.bootstrap import moving_block_indices, paired_moving_block_bootstrap

_FIXTURE_DIR = Path(__file__).parent / "fixtures"
_RETURNS_FIXTURE = _FIXTURE_DIR / "okx_btc_usdt_oos_returns_20200111_20200219.csv"
_METADATA_FIXTURE = (
    _FIXTURE_DIR / "okx_btc_usdt_oos_returns_20200111_20200219.metadata.json"
)


def _real_returns_frame() -> pd.DataFrame:
    metadata = json.loads(_METADATA_FIXTURE.read_text(encoding="utf-8"))
    assert (
        hashlib.sha256(_RETURNS_FIXTURE.read_bytes()).hexdigest()
        == metadata["fixture_sha256"]
    )
    frame = pd.read_csv(_RETURNS_FIXTURE)
    assert len(frame) == metadata["rows"]
    assert frame["timestamp"].iloc[0] == metadata["start"]
    assert frame["timestamp"].iloc[-1] == metadata["end"]
    return frame


def _comparison_frame() -> pd.DataFrame:
    return _real_returns_frame().rename(
        columns={"benchmark_buy_and_hold_return": "benchmark_return"}
    )


def test_real_returns_fixture_has_auditable_okx_provenance() -> None:
    metadata = json.loads(_METADATA_FIXTURE.read_text(encoding="utf-8"))

    assert metadata["provider"] == "OKX"
    assert metadata["instrument_id"] == "BTC-USDT"
    assert metadata["bar"] == "1Dutc"
    assert metadata["source_returns_csv_sha256"] == (
        "539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73"
    )
    assert metadata["source_artifact_sha256"] == (
        "dbe25282321fa1d1fdafa2945c1a45e6a6481060d693956fd5fb3225b03f3fd7"
    )
    _real_returns_frame()


def test_moving_block_indices_are_contiguous_inside_each_block() -> None:
    indices = moving_block_indices(12, 4, np.random.default_rng(7))

    assert len(indices) == 12
    assert np.all(np.diff(indices.reshape(3, 4), axis=1) == 1)
    assert indices.min() >= 0
    assert indices.max() < 12


def test_paired_bootstrap_is_deterministic_and_preserves_zero_delta() -> None:
    observed = _real_returns_frame()["strategy_return"]
    frame = pd.DataFrame(
        {"strategy_return": observed, "benchmark_return": observed.copy()}
    )
    kwargs = {
        "strategy_column": "strategy_return",
        "benchmark_columns": {"benchmark": "benchmark_return"},
        "block_length": 10,
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


def test_paired_bootstrap_detects_observed_drawdown_reduction() -> None:
    result = paired_moving_block_bootstrap(
        _comparison_frame(),
        strategy_column="strategy_return",
        benchmark_columns={"benchmark": "benchmark_return"},
        block_length=10,
        resamples=300,
        annualization=365,
        seed=19,
    )

    drawdown = result.comparisons["benchmark"]["max_drawdown"]
    assert drawdown["observed_delta"] > 0.0
    assert drawdown["ci_lower"] > 0.0
    assert drawdown["lower_bound_positive"] is True


def test_paired_bootstrap_rejects_non_finite_returns() -> None:
    frame = _comparison_frame()
    frame.loc[3, "strategy_return"] = np.nan

    with pytest.raises(ValueError, match="finite numeric"):
        paired_moving_block_bootstrap(
            frame,
            strategy_column="strategy_return",
            benchmark_columns={"benchmark": "benchmark_return"},
            block_length=10,
            resamples=100,
        )
