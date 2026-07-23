from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import pytest

from gpt_quant import StrategyConfig, run_walk_forward_research
from gpt_quant.walk_forward_report import write_walk_forward_report
from gpt_quant.walk_forward_verify import verify_walk_forward_report


def _write_real_okx_report(prices: pd.Series, output: Path) -> dict[str, Path]:
    result = run_walk_forward_research(
        prices.iloc[:500],
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


def test_verifier_recomputes_persisted_real_okx_report(
    btc_usdt_prices: pd.Series,
    tmp_path: Path,
) -> None:
    paths = _write_real_okx_report(btc_usdt_prices, tmp_path)

    verification = verify_walk_forward_report(tmp_path)

    returns = pd.read_csv(paths["returns"])
    assert verification["status"] == "passed"
    assert verification["transaction_cost_bps"] == 5.0
    assert verification["observations"] == len(returns)
    assert verification["folds"] == returns["fold"].nunique()
    assert verification["fold_boundary_position_transitions_verified"] == 1
    assert verification["within_fold_delayed_position_rows_verified"] == len(returns) - 2
    assert verification["report_json_sha256"] == hashlib.sha256(
        paths["json"].read_bytes()
    ).hexdigest()
    assert verification["returns_csv_sha256"] == hashlib.sha256(
        paths["returns"].read_bytes()
    ).hexdigest()
    assert verification["spread_model"] == "not_modeled"
    assert verification["slippage_model"] == "not_modeled"
    assert verification["market_impact_model"] == "not_modeled"
    assert verification["latency_model"] == "not_modeled"


def test_verifier_rejects_self_consistent_turnover_fee_tamper(
    btc_usdt_prices: pd.Series,
    tmp_path: Path,
) -> None:
    paths = _write_real_okx_report(btc_usdt_prices, tmp_path)
    returns = pd.read_csv(paths["returns"])
    row = int(returns.index[returns["turnover"] > 0.0][0])
    returns.loc[row, "turnover"] += 0.1
    returns.loc[row, "trading_cost"] += 0.1 * 5.0 / 10_000.0
    returns.loc[row, "strategy_return"] = (
        returns.loc[row, "gross_strategy_return"] - returns.loc[row, "trading_cost"]
    )
    returns.to_csv(paths["returns"], index=False)

    with pytest.raises(ValueError, match="turnover"):
        verify_walk_forward_report(tmp_path)


def test_verifier_rejects_within_fold_delayed_position_drift(
    btc_usdt_prices: pd.Series,
    tmp_path: Path,
) -> None:
    paths = _write_real_okx_report(btc_usdt_prices, tmp_path)
    returns = pd.read_csv(paths["returns"])
    first_fold = int(returns.loc[0, "fold"])
    fold_rows = returns.index[returns["fold"] == first_fold]
    row = int(fold_rows[1])
    returns.loc[row - 1, "target_position"] += 0.1
    returns.to_csv(paths["returns"], index=False)

    with pytest.raises(ValueError, match="delayed position"):
        verify_walk_forward_report(tmp_path)


def test_verifier_accepts_fold_boundary_model_switch_accounting(
    btc_usdt_prices: pd.Series,
    tmp_path: Path,
) -> None:
    paths = _write_real_okx_report(btc_usdt_prices, tmp_path)
    returns = pd.read_csv(paths["returns"])
    boundary = int(returns.index[returns["fold"].ne(returns["fold"].shift())][1])

    returns.loc[boundary - 1, "target_position"] += 0.1
    returns.to_csv(paths["returns"], index=False)

    verification = verify_walk_forward_report(tmp_path)
    assert verification["status"] == "passed"
    assert verification["fold_boundary_position_transitions_verified"] == 1
