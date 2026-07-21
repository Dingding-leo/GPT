from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from gpt_quant import load_verified_price_snapshot

_FIXTURE_MANIFEST = (
    Path(__file__).parent
    / "fixtures"
    / "okx"
    / "btc-usdt-1dutc-600"
    / "manifest.json"
)


@pytest.fixture(scope="session")
def btc_usdt_prices() -> pd.Series:
    """Load the immutable, hash-verified OKX BTC-USDT regression snapshot."""

    return load_verified_price_snapshot(_FIXTURE_MANIFEST).prices
