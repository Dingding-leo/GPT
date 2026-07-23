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


def test_holdout_candidate_accounting_guide_matches_current_config() -> None:
    search = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))["search"]
    guide = _GUIDE_PATH.read_text(encoding="utf-8")
    names = ("momentum_lookbacks", "reversal_lookbacks", "trend_weights")
    raw_dimensions = [len(search[name]) for name in names]
    distinct_dimensions = [len(dict.fromkeys(search[name])) for name in names]
    distinct_grid = distinct_dimensions[0] * distinct_dimensions[1] * distinct_dimensions[2]

    assert raw_dimensions == [3, 3, 3]
    assert distinct_dimensions == [3, 3, 3]
    assert distinct_grid == 27
    assert search["top_candidates"] == 10

    required_claims = (
        "remove repeats within each dimension while preserving the first declared occurrence",
        "retain only candidates with a finite selection score for `candidates_tested`",
        "duplicate declarations cannot increase `candidates_tested`",
        "`candidates_tested` cannot exceed that value",
        "the momentum ordering remains `42`, then `21`",
        "`3 × 3 × 3 = 27`",
        "limits only the persisted ranking",
        "tests/test_holdout_candidate_deduplication.py",
    )
    for claim in required_claims:
        assert claim in guide


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
