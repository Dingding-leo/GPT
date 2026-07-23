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


def _shift_numeric_csv_cell(path: Path, *, row: int, column: str, delta: float) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split(",")
    column_index = header.index(column)
    cells = lines[row + 1].split(",")
    cells[column_index] = repr(float(cells[column_index]) + delta)
    lines[row + 1] = ",".join(cells)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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
    original_bytes = paths["returns"].read_bytes()
    original = pd.read_csv(paths["returns"])
    fold_boundaries = np.flatnonzero(original["fold"].ne(original["fold"].shift()).to_numpy())
    assert len(fold_boundaries) == 2
    assert verify_walk_forward_report is direct_verify
    assert verify_walk_forward_report(tmp_path, tolerance=1e-10)["status"] == "passed"

    second_fold_start = int(fold_boundaries[1])
    previous_fold_last_row = second_fold_start - 1
    _shift_numeric_csv_cell(
        paths["returns"],
        row=previous_fold_last_row,
        column="target_position",
        delta=0.1,
    )
    with pytest.raises(ValueError, match="cross-fold delayed position"):
        verify_walk_forward_report(tmp_path, tolerance=1e-10)

    paths["returns"].write_bytes(original_bytes)
    within_fold_target_row = previous_fold_last_row - 1
    _shift_numeric_csv_cell(
        paths["returns"],
        row=within_fold_target_row,
        column="target_position",
        delta=0.1,
    )
    with pytest.raises(ValueError, match="fold 1 position"):
        verify_walk_forward_report(tmp_path, tolerance=1e-10)
