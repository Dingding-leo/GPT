from __future__ import annotations

import numpy as np
import pandas as pd

import run_trade_flow_research as base
import run_trade_flow_research_boundary as boundary


def max_drawdown_from_initial_capital(values: pd.Series) -> float:
    """Measure drawdown against the initial unit NAV as well as later peaks."""
    nav = (1.0 + values).cumprod().to_numpy(dtype=float)
    if nav.size == 0:
        return 0.0
    peaks = np.maximum.accumulate(np.concatenate((np.array([1.0]), nav)))
    return float(np.min(nav / peaks[1:] - 1.0))


def main() -> None:
    base.max_drawdown = max_drawdown_from_initial_capital
    boundary.main()


if __name__ == "__main__":
    main()
