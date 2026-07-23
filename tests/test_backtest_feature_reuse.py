from __future__ import annotations

import pandas as pd
import pytest

import gpt_quant.backtest as backtest_module
import gpt_quant.features as features_module
from gpt_quant import StrategyConfig, run_backtest, validate_prices
from gpt_quant.features import _build_target_position_from_validated, build_target_position


def _config() -> StrategyConfig:
    return StrategyConfig(
        momentum_lookback=90,
        reversal_lookback=5,
        volatility_lookback=20,
        min_position=0.0,
        transaction_cost_bps=5.0,
        annualization=365,
    )


def test_validated_feature_fast_path_preserves_real_okx_output(
    btc_usdt_prices: pd.Series,
) -> None:
    clean = validate_prices(btc_usdt_prices)

    expected = build_target_position(clean, _config())
    actual = _build_target_position_from_validated(clean, _config())

    pd.testing.assert_series_equal(actual, expected, check_exact=True)


def test_backtest_reuses_single_price_validation(
    btc_usdt_prices: pd.Series,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = build_target_position(btc_usdt_prices, _config())
    calls = 0
    original_validate = backtest_module.validate_prices

    def counting_validate(prices: pd.Series) -> pd.Series:
        nonlocal calls
        calls += 1
        return original_validate(prices)

    monkeypatch.setattr(backtest_module, "validate_prices", counting_validate)
    monkeypatch.setattr(features_module, "validate_prices", counting_validate)

    result = run_backtest(btc_usdt_prices, _config())

    assert calls == 1
    pd.testing.assert_series_equal(result.frame["target_position"], expected, check_exact=True)
