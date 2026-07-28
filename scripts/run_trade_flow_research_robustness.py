from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
import run_trade_flow_research as base
import run_trade_flow_research_boundary as boundary

ORIGINAL_CANDLE_FETCH = boundary.exact.ORIGINAL_FETCH_CANDLES


def max_drawdown_from_initial_capital(values: pd.Series) -> float:
    """Measure drawdown against the initial unit NAV as well as later peaks."""
    nav = (1.0 + values).cumprod().to_numpy(dtype=float)
    if nav.size == 0:
        return 0.0
    peaks = np.maximum.accumulate(np.concatenate((np.array([1.0]), nav)))
    return float(np.min(nav / peaks[1:] - 1.0))


def overlap_aware_candle_fetch(**kwargs: Any) -> Any:
    """Preserve the frozen interval while budgeting for inclusive cursor overlap."""
    start = pd.Timestamp(kwargs["start"])
    end = pd.Timestamp(kwargs["end"])
    limit = int(kwargs.get("limit", 100))
    safety_pages = int(kwargs.get("safety_pages", 2))
    expected_observations = int((end - start) / pd.Timedelta(hours=1)) + 1
    if expected_observations <= limit:
        overlap_aware_pages = 1
    else:
        if limit <= 1:
            raise ValueError("inclusive cursor pagination needs limit > 1 for multi-page coverage")
        overlap_aware_pages = 1 + math.ceil((expected_observations - limit) / (limit - 1))
    nonoverlap_pages = math.ceil(expected_observations / limit)
    kwargs["safety_pages"] = safety_pages + overlap_aware_pages - nonoverlap_pages
    return ORIGINAL_CANDLE_FETCH(**kwargs)


def assert_frozen_candle_budget() -> None:
    """Prove the 1,200-day candle request cannot repeat the failed 290-page cap."""
    observations = (base.DEVELOPMENT_DAYS - base.RESERVED_DAYS) * 24 + base.TREND_LOOKBACK
    nonoverlap_pages = math.ceil(observations / 100)
    overlap_aware_pages = 1 + math.ceil((observations - 100) / 99)
    corrected_budget = overlap_aware_pages + 2
    if observations != 28_800 or nonoverlap_pages + 2 != 290:
        raise AssertionError("frozen candle interval accounting changed")
    if corrected_budget != 293:
        raise AssertionError("overlap-aware frozen candle budget changed")


def main() -> None:
    assert_frozen_candle_budget()
    base.max_drawdown = max_drawdown_from_initial_capital
    boundary.exact.ORIGINAL_FETCH_CANDLES = overlap_aware_candle_fetch
    boundary.main()


if __name__ == "__main__":
    main()
