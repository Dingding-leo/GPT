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


def test_verifier_rejects_cross_fold_position_delay_drift(
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
    returns = pd.read_csv(paths["returns"])
    fold_boundaries = np.flatnonzero(
        returns["fold"].ne(returns["fold"].shift()).to_numpy()
    )
    assert len(fold_boundaries) == 2
    second_fold_start = int(fold_boundaries[1])
    previous_row = second_fold_start - 1
    assert returns.loc[second_fold_start, "position"] == pytest.approx(
        returns.loc[previous_row, "target_position"]
    )

    returns.loc[previous_row, "target_position"] += 0.1
    returns.to_csv(paths["returns"], index=False)

    for verifier in (verify_walk_forward_report, direct_verify):
        with pytest.raises(ValueError, match="cross-fold delayed position"):
            verifier(tmp_path)
