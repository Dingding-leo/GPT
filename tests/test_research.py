from __future__ import annotations

import pandas as pd

from gpt_quant import StrategyConfig, run_holdout_research


def test_research_selects_on_validation_and_reports_holdout(
    btc_usdt_prices: pd.Series,
) -> None:
    result = run_holdout_research(
        btc_usdt_prices,
        base_config=StrategyConfig(),
        momentum_lookbacks=[21, 63],
        reversal_lookbacks=[3, 5],
        trend_weights=[0.6, 0.8],
        validation_fraction=0.2,
        holdout_fraction=0.2,
        top_candidates=3,
    )

    assert result.candidates_tested == 8
    assert len(result.candidate_ranking) == 3
    assert result.split["validation_end"] < result.split["holdout_start"]
    assert result.holdout_metrics["observations"] > 0
