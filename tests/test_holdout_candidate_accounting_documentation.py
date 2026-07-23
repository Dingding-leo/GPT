from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

import gpt_quant.research as research_module
from gpt_quant import StrategyConfig, run_holdout_research

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_CONFIG_PATH = _REPOSITORY_ROOT / "config" / "okx_holdout.json"
_GUIDE_PATH = _REPOSITORY_ROOT / "docs" / "HOLDOUT_CANDIDATE_ACCOUNTING.md"
_RESEARCH_PATH = _REPOSITORY_ROOT / "src" / "gpt_quant" / "research.py"
_BACKTEST_PATH = _REPOSITORY_ROOT / "src" / "gpt_quant" / "backtest.py"
_WARMUP_TEST_PATH = _REPOSITORY_ROOT / "tests" / "test_holdout_warmup_boundary.py"


def test_holdout_candidate_accounting_guide_matches_current_config() -> None:
    config = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    guide = _GUIDE_PATH.read_text(encoding="utf-8")
    research_source = _RESEARCH_PATH.read_text(encoding="utf-8")
    backtest_source = _BACKTEST_PATH.read_text(encoding="utf-8")
    warmup_tests = _WARMUP_TEST_PATH.read_text(encoding="utf-8")
    search = config["search"]
    names = ("momentum_lookbacks", "reversal_lookbacks", "trend_weights")
    raw_dimensions = [len(search[name]) for name in names]
    distinct_dimensions = [len(dict.fromkeys(search[name])) for name in names]
    distinct_grid = distinct_dimensions[0] * distinct_dimensions[1] * distinct_dimensions[2]

    assert raw_dimensions == [3, 3, 3]
    assert distinct_dimensions == [3, 3, 3]
    assert distinct_grid == 27
    assert search["top_candidates"] == 10

    observations = 600
    validation_start_idx = int(
        observations * (1.0 - search["holdout_fraction"] - search["validation_fraction"])
    )
    longest_lookback = max(
        config["strategy"]["volatility_lookback"],
        max(dict.fromkeys(search["momentum_lookbacks"])),
        max(dict.fromkeys(search["reversal_lookbacks"])),
    )
    delayed_warmup_margin = validation_start_idx - 1 - longest_lookback
    assert validation_start_idx == 360
    assert longest_lookback == 180
    assert delayed_warmup_margin == 179

    required_claims = (
        "remove repeats within each dimension while preserving the first declared occurrence",
        "retain only candidates with a finite selection score for `candidates_tested`",
        "duplicate declarations cannot increase `candidates_tested`",
        "`candidates_tested` cannot exceed that value",
        "the momentum ordering remains `42`, then `21`",
        "`3 × 3 × 3 = 27`",
        "limits only the persisted ranking",
        "fully formed one-bar-delayed position at validation start",
        "longest_lookback <= validation_start_idx - 1",
        "`lookback == validation_start_idx - 1` is the final accepted boundary",
        "`lookback == validation_start_idx` is rejected",
        "lookback `359` is accepted and lookback `360` is rejected",
        "'validation_start_idx': 360",
        "'longest_lookback': 180",
        "'delayed_warmup_margin': 179",
        "tests/test_holdout_candidate_deduplication.py",
        "tests/test_holdout_warmup_boundary.py",
    )
    for claim in required_claims:
        assert claim in guide

    guard = "if longest_lookback > validation_start_idx - 1:"
    assert guard in research_source
    assert research_source.index(guard) < research_source.index(
        "candidates: list[tuple[float, StrategyConfig"
    )
    assert "position = target_position.shift(1).fillna(0.0)" in backtest_source
    assert "warmup validation must finish before any backtest" in warmup_tests
    assert "momentum_lookbacks = [359]" in warmup_tests
    assert "([360], [3], _base_config())" in warmup_tests
    assert "btc_usdt_prices.index[360].isoformat()" in warmup_tests


def test_documented_duplicate_grid_preserves_distinct_first_declared_order(
    btc_usdt_prices: pd.Series,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(research_module, "_selection_score", lambda _metrics: 1.0)

    result = run_holdout_research(
        btc_usdt_prices.iloc[:600],
        base_config=StrategyConfig(
            min_position=0.0,
            transaction_cost_bps=10.0,
            annualization=365,
        ),
        momentum_lookbacks=[42, 21, 42],
        reversal_lookbacks=[3, 3],
        trend_weights=[0.7, 0.7],
        top_candidates=10,
    )

    assert result.candidates_tested == 2
    assert len(result.candidate_ranking) == 2
    assert [entry["parameters"]["momentum_lookback"] for entry in result.candidate_ranking] == [
        42,
        21,
    ]
    assert result.selected_parameters["momentum_lookback"] == 42
