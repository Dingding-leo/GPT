from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from gpt_quant import (
    StrategyConfig,
    run_walk_forward_research,
    verify_walk_forward_report,
)
from gpt_quant.walk_forward_report import write_walk_forward_report
from gpt_quant.walk_forward_verify import verify_walk_forward_report as direct_verify


def test_verifier_keeps_delay_checks_within_each_selected_fold(
    btc_usdt_prices: pd.Series,
    tmp_path: Path,
) -> None:
    result = run_walk_forward_research(
        btc_usdt_prices.iloc[:500],
        base_config=StrategyConfig(
            min_position=0.0,
            transaction_cost_bps=5.0,
            annualization=365,
        ),
        momentum_lookbacks=[21],
        reversal_lookbacks=[3],
        trend_weights=[0.7],
        selection_bars=300,
        test_bars=100,
        cost_multipliers=[1.0, 1.5, 2.0, 3.0],
        provenance={
            "provider": "OKX",
            "instrument_id": "BTC-USDT",
            "bar": "1Dutc",
        },
    )
    paths = write_walk_forward_report(result, tmp_path)
    original = pd.read_csv(paths["returns"])
    fold_boundaries = np.flatnonzero(original["fold"].ne(original["fold"].shift()).to_numpy())
    assert len(fold_boundaries) == 2
    assert verify_walk_forward_report is direct_verify

    second_fold_start = int(fold_boundaries[1])
    previous_fold_last_row = second_fold_start - 1

    boundary_copy = original.copy()
    boundary_copy.loc[previous_fold_last_row, "target_position"] += 0.1
    boundary_copy.to_csv(paths["returns"], index=False)
    verification = verify_walk_forward_report(tmp_path)
    assert verification["status"] == "passed"

    within_fold_copy = original.copy()
    within_fold_target_row = previous_fold_last_row - 1
    within_fold_copy.loc[within_fold_target_row, "target_position"] += 0.1
    within_fold_copy.to_csv(paths["returns"], index=False)
    with pytest.raises(ValueError, match="fold 1 position"):
        verify_walk_forward_report(tmp_path)
