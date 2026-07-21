from __future__ import annotations

from gpt_quant import StrategyConfig, generate_regime_prices, run_holdout_research


def test_research_selects_on_validation_and_reports_holdout() -> None:
    prices = generate_regime_prices(rows=1_200, seed=17)
    result = run_holdout_research(
        prices,
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
