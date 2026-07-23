from __future__ import annotations

import hashlib
import io
from pathlib import Path

import numpy as np
import pandas as pd

from . import walk_forward_verify as _walk_forward_verify
from .walk_forward_verify import _assert_series_close, _numeric_column

_verify_core = _walk_forward_verify.verify_walk_forward_report
_SELECTED_PARAMETER_COLUMNS = (
    "selected_momentum_lookback",
    "selected_reversal_lookback",
    "selected_trend_weight",
)


def _verify_global_position_delay(persisted: pd.DataFrame, *, tolerance: float) -> None:
    required = {"fold", "position", "target_position"}
    if not required <= set(persisted.columns) or len(persisted) <= 1:
        return

    positions = _numeric_column(persisted, "position")
    targets = _numeric_column(persisted, "target_position")
    folds = _numeric_column(persisted, "fold").to_numpy()
    actual = positions.iloc[1:].reset_index(drop=True)
    expected = targets.shift(1).iloc[1:].reset_index(drop=True)

    same_fold = folds[1:] == folds[:-1]
    comparable = same_fold.copy()
    if set(_SELECTED_PARAMETER_COLUMNS) <= set(persisted.columns):
        same_strategy = np.ones(len(persisted) - 1, dtype=bool)
        for name in _SELECTED_PARAMETER_COLUMNS:
            values = _numeric_column(persisted, name).to_numpy()
            same_strategy &= values[1:] == values[:-1]
        comparable |= same_strategy

    mismatches = np.flatnonzero(
        (np.abs(actual.to_numpy() - expected.to_numpy()) > tolerance) & comparable
    )
    if not mismatches.size:
        return

    offset = int(mismatches[0])
    row = offset + 1
    label = (
        "cross-fold delayed position"
        if folds[row] != folds[row - 1]
        else f"fold {int(folds[row])} position"
    )
    _assert_series_close(
        label,
        actual.iloc[[offset]],
        expected.iloc[[offset]],
        tolerance=tolerance,
    )


def verify_walk_forward_report(
    output_dir: str | Path,
    *,
    tolerance: float = 1e-12,
) -> dict[str, float | int | str]:
    """Verify persisted metrics and every reconstructable delayed position."""

    returns_path = Path(output_dir) / "walk_forward_returns.csv"
    returns_bytes = returns_path.read_bytes()
    _verify_global_position_delay(
        pd.read_csv(io.BytesIO(returns_bytes)),
        tolerance=tolerance,
    )

    verification = _verify_core(
        output_dir,
        tolerance=tolerance,
    )
    actual_sha256 = hashlib.sha256(returns_bytes).hexdigest()
    if actual_sha256 != verification["returns_csv_sha256"]:
        raise ValueError("walk-forward returns CSV changed during verification")
    return verification


_walk_forward_verify.verify_walk_forward_report = verify_walk_forward_report
