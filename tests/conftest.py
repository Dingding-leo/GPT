from __future__ import annotations

import os

import pandas as pd
import pytest

from gpt_quant import fetch_okx_history_candles


@pytest.fixture(scope="session")
def btc_usdt_prices() -> pd.Series:
    """Download completed public OKX BTC-USDT daily closes for regression tests."""

    snapshot = fetch_okx_history_candles(
        inst_id="BTC-USDT",
        bar="1Dutc",
        base_url=os.environ.get("OKX_BASE_URL", "https://www.okx.com"),
        limit=100,
        max_pages=12,
        pause_seconds=0.0,
    )
    return snapshot.close
