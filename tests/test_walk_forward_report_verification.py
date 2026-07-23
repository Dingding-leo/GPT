from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from gpt_quant.walk_forward_report import write_walk_forward_report

from gpt_quant import (
    StrategyConfig,
    run_walk_forward_research,
    verify_walk_forward_report,
)


def _write_real_report(btc_usdt_prices: pd.Series, output: Path) -> dict[str, Path]:
    result = run_walk_forward_research(
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
        provenance={
            "provider": "OKX",
            "instrument_id": "BTC-USDT",
            "bar": "1Dutc",
        },
    )
    return write_walk_forward_report(result, output)


def test_persisted_walk_forward_report_recomputes_from_real_okx_data(
    btc_usdt_prices: pd.Series,
    tmp_path: Path,
) -> None:
    paths = _write_real_report(btc_usdt_prices, tmp_path)

    verification = verify_walk_forward_report(tmp_path)
    returns = pd.read_csv(paths["returns"])
    expected_turnover = returns["position"].diff().fillna(returns["position"]).abs()

    assert verification["status"] == "passed"
    assert verification["observations"] == len(returns)
    assert verification["folds"] == 1
    assert verification["annualization"] == 365
    assert verification["transaction_cost_bps"] == 5.0
    assert len(str(verification["report_json_sha256"])) == 64
    assert len(str(verification["returns_csv_sha256"])) == 64
    assert {
        "gross_strategy_return",
        "exchange_fee_cost",
        "trading_cost",
        "strategy_return",
    } <= set(returns.columns)
    assert np.allclose(
        returns["turnover"],
        expected_turnover,
        rtol=0.0,
        atol=1e-12,
    )
    assert np.allclose(
        returns["gross_strategy_return"],
        returns["position"] * returns["asset_return"],
        rtol=0.0,
        atol=1e-12,
    )
    assert np.allclose(
        returns["exchange_fee_cost"],
        returns["trading_cost"],
        rtol=0.0,
        atol=1e-12,
    )


def test_persisted_walk_forward_verifier_reconstructs_path_diagnostics(
    btc_usdt_prices: pd.Series,
    tmp_path: Path,
) -> None:
    paths = _write_real_report(btc_usdt_prices, tmp_path)
    verification = verify_walk_forward_report(tmp_path)
    returns = pd.read_csv(paths["returns"])

    threshold = 1e-12
    material_threshold = 0.01
    active_threshold = 0.01
    active = returns["position"].abs().gt(active_threshold)
    starts = active & ~active.shift(1, fill_value=False)
    completed = active & ~active.shift(-1, fill_value=False)
    completed.iloc[-1] = False

    completed_episode_returns: list[float] = []
    row = 0
    while row < len(returns):
        if not bool(active.iloc[row]):
            row += 1
            continue
        start = row
        while row + 1 < len(returns) and bool(active.iloc[row + 1]):
            row += 1
        if row + 1 < len(returns):
            episode = returns["strategy_return"].iloc[start : row + 2]
            completed_episode_returns.append(float((1.0 + episode).prod() - 1.0))
        row += 1

    positive_profit = sum(value for value in completed_episode_returns if value > 0.0)
    negative_loss = -sum(value for value in completed_episode_returns if value < 0.0)

    equity = (1.0 + returns["strategy_return"]).cumprod().to_numpy()
    peaks = np.maximum.accumulate(np.concatenate(([1.0], equity)))[1:]
    drawdown = equity / peaks - 1.0
    underwater = drawdown < -threshold
    runs: list[int] = []
    running = 0
    for value in underwater:
        if bool(value):
            running += 1
            runs.append(running)
        else:
            running = 0

    assert verification["diagnostic_schema"] == "persisted_path_v1"
    assert verification["position_adjustment_threshold"] == threshold
    assert verification["material_position_adjustment_threshold"] == material_threshold
    assert verification["active_position_threshold"] == active_threshold
    assert verification["drawdown_threshold"] == threshold
    assert verification["position_adjustment_count"] == int(returns["turnover"].gt(threshold).sum())
    assert verification["material_position_adjustment_count"] == int(
        returns["turnover"].gt(material_threshold).sum()
    )
    assert verification["total_absolute_turnover"] == pytest.approx(returns["turnover"].sum())
    assert verification["annualized_instrument_turnover"] == pytest.approx(
        returns["turnover"].mean() * 365
    )
    assert verification["holding_episode_count"] == int(starts.sum())
    assert verification["completed_holding_episode_count"] == int(completed.sum())
    assert verification["open_holding_episode_count"] == int(active.iloc[-1])
    assert verification["completed_holding_episode_win_rate"] == pytest.approx(
        sum(value > 0.0 for value in completed_episode_returns) / len(completed_episode_returns)
    )
    assert verification["completed_holding_episode_profit_factor"] == pytest.approx(
        positive_profit / negative_loss
    )
    assert verification["average_absolute_exposure"] == pytest.approx(
        returns["position"].abs().mean()
    )
    assert verification["current_absolute_exposure"] == pytest.approx(
        abs(returns["position"].iloc[-1])
    )
    assert verification["maximum_absolute_exposure"] == pytest.approx(
        returns["position"].abs().max()
    )
    assert verification["current_drawdown"] == pytest.approx(drawdown[-1])
    assert verification["recomputed_maximum_drawdown"] == pytest.approx(drawdown.min())
    assert verification["longest_underwater_duration_bars"] == max(runs, default=0)
    assert verification["current_underwater_duration_bars"] == (
        runs[-1] if len(runs) and bool(underwater[-1]) else 0
    )
    assert verification["evaluation_start"] == pd.Timestamp(
        returns["timestamp"].iloc[0]
    ).isoformat()
    assert verification["evaluation_end"] == pd.Timestamp(
        returns["timestamp"].iloc[-1]
    ).isoformat()


def test_persisted_walk_forward_verifier_rejects_report_metric_drift(
    btc_usdt_prices: pd.Series,
    tmp_path: Path,
) -> None:
    paths = _write_real_report(btc_usdt_prices, tmp_path)
    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    payload["aggregate_metrics"]["sharpe"] += 0.1
    paths["json"].write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"aggregate_metrics\.sharpe"):
        verify_walk_forward_report(tmp_path)


def test_persisted_walk_forward_verifier_rejects_fee_accounting_drift(
    btc_usdt_prices: pd.Series,
    tmp_path: Path,
) -> None:
    paths = _write_real_report(btc_usdt_prices, tmp_path)
    returns = pd.read_csv(paths["returns"])
    changed_row = int(returns["turnover"].gt(0.0).to_numpy().argmax())
    returns.loc[changed_row, "exchange_fee_cost"] += 0.001
    returns.to_csv(paths["returns"], index=False)

    with pytest.raises(ValueError, match="exchange_fee_cost"):
        verify_walk_forward_report(tmp_path)


def test_persisted_walk_forward_verifier_rejects_turnover_path_drift(
    btc_usdt_prices: pd.Series,
    tmp_path: Path,
) -> None:
    paths = _write_real_report(btc_usdt_prices, tmp_path)
    returns = pd.read_csv(paths["returns"])
    changed_row = int(returns["turnover"].gt(0.0).to_numpy().argmax())
    extra_turnover = 0.25
    extra_fee = extra_turnover * 5.0 / 10_000.0
    returns.loc[changed_row, "turnover"] += extra_turnover
    returns.loc[changed_row, "exchange_fee_cost"] += extra_fee
    returns.loc[changed_row, "trading_cost"] += extra_fee
    returns.loc[changed_row, "strategy_return"] -= extra_fee
    returns.to_csv(paths["returns"], index=False)

    with pytest.raises(ValueError, match="turnover"):
        verify_walk_forward_report(tmp_path)


def test_persisted_walk_forward_verifier_rejects_position_delay_drift(
    btc_usdt_prices: pd.Series,
    tmp_path: Path,
) -> None:
    paths = _write_real_report(btc_usdt_prices, tmp_path)
    returns = pd.read_csv(paths["returns"])
    returns.loc[0, "target_position"] += 0.1
    returns.to_csv(paths["returns"], index=False)

    with pytest.raises(ValueError, match="fold 1 position"):
        verify_walk_forward_report(tmp_path)
