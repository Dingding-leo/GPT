from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from gpt_quant import StrategyConfig, run_backtest, run_walk_forward_research
from gpt_quant.metrics import performance_metrics
from gpt_quant.walk_forward_report import write_walk_forward_report


def _five_bps_result(btc_usdt_prices: pd.Series):
    return run_walk_forward_research(
        btc_usdt_prices.iloc[:400],
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
    )


def test_metrics_reject_inconsistent_gross_net_fee_decomposition(
    btc_usdt_prices: pd.Series,
) -> None:
    frame = run_backtest(
        btc_usdt_prices.iloc[:400],
        StrategyConfig(min_position=0.0, transaction_cost_bps=5.0, annualization=365),
    ).frame.copy()
    active = frame.index[frame["turnover"].gt(0.0)]
    assert not active.empty

    frame.at[active[0], "strategy_return"] += 1e-4

    with pytest.raises(
        ValueError,
        match="strategy_return must equal gross_strategy_return minus trading_cost",
    ):
        performance_metrics(frame, annualization=365)


def test_metrics_reject_gross_return_disconnected_from_executed_position(
    btc_usdt_prices: pd.Series,
) -> None:
    frame = run_backtest(
        btc_usdt_prices.iloc[:400],
        StrategyConfig(min_position=0.0, transaction_cost_bps=5.0, annualization=365),
    ).frame.copy()
    active = frame.index[frame["position"].abs().gt(0.0) & frame["asset_return"].abs().gt(0.0)]
    assert not active.empty

    frame.at[active[0], "gross_strategy_return"] += 1e-4
    frame.at[active[0], "strategy_return"] += 1e-4

    with pytest.raises(
        ValueError,
        match="gross_strategy_return must equal position multiplied by asset_return",
    ):
        performance_metrics(frame, annualization=365)


def test_report_metrics_recompute_from_persisted_gross_net_fee_columns(
    btc_usdt_prices: pd.Series,
    tmp_path: Path,
) -> None:
    result = _five_bps_result(btc_usdt_prices)
    paths = write_walk_forward_report(result, tmp_path)

    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    persisted = pd.read_csv(paths["returns"])
    metrics = payload["aggregate_metrics"]

    required = {
        "gross_strategy_return",
        "strategy_return",
        "position",
        "asset_return",
        "turnover",
        "trading_cost",
    }
    assert required <= set(persisted.columns)

    gross = persisted["gross_strategy_return"].to_numpy(dtype=float)
    net = persisted["strategy_return"].to_numpy(dtype=float)
    position = persisted["position"].to_numpy(dtype=float)
    asset_return = persisted["asset_return"].to_numpy(dtype=float)
    fee = persisted["trading_cost"].to_numpy(dtype=float)

    np.testing.assert_allclose(gross, position * asset_return, rtol=0.0, atol=1e-15)
    np.testing.assert_allclose(net, gross - fee, rtol=0.0, atol=1e-15)

    gross_total_return = float(np.prod(1.0 + gross) - 1.0)
    net_total_return = float(np.prod(1.0 + net) - 1.0)
    compounded_fee_drag = gross_total_return - net_total_return

    assert float(metrics["gross_total_return"]) == pytest.approx(gross_total_return, abs=1e-12)
    assert float(metrics["net_total_return"]) == pytest.approx(net_total_return, abs=1e-12)
    assert float(metrics["total_return"]) == pytest.approx(net_total_return, abs=1e-12)
    assert float(metrics["exchange_fee_sum"]) == pytest.approx(float(fee.sum()), abs=1e-12)
    assert float(metrics["compounded_exchange_fee_drag"]) == pytest.approx(
        compounded_fee_drag,
        abs=1e-12,
    )
    assert float(metrics["gross_annualized_arithmetic_mean"]) == pytest.approx(
        float(gross.mean() * 365),
        abs=1e-12,
    )
    assert float(metrics["net_annualized_arithmetic_mean"]) == pytest.approx(
        float(net.mean() * 365),
        abs=1e-12,
    )
    assert float(metrics["exchange_fee_sum"]) > 0.0
    assert float(metrics["compounded_exchange_fee_drag"]) > 0.0

    markdown = paths["markdown"].read_text(encoding="utf-8")
    assert "## Gross, net and exchange-fee decomposition" in markdown
    assert "Declared one-way exchange fee: `5 bps`" in markdown
    assert "not the arithmetic fee sum" in markdown
