from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from gpt_quant import StrategyConfig, run_backtest, run_walk_forward_research
from gpt_quant.metrics import performance_metrics
from gpt_quant.walk_forward_report import write_walk_forward_report
from gpt_quant.walk_forward_selection_verify import verify_walk_forward_selection
from gpt_quant.walk_forward_verify_gate import verify_walk_forward_report


def _write_report(prices: pd.Series, output: Path) -> dict[str, Path]:
    source_prices = prices.iloc[:600]
    snapshot_dir = output / "snapshot"
    snapshot_dir.mkdir(parents=True)
    snapshot_path = snapshot_dir / "okx-BTC-USDT-1Dutc.csv"
    pd.DataFrame(
        {
            "timestamp": source_prices.index.map(lambda value: value.isoformat()),
            "close": source_prices.to_numpy(copy=False),
            "confirm": 1,
        }
    ).to_csv(snapshot_path, index=False)
    snapshot_sha256 = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
    base_config = StrategyConfig(
        min_position=0.0,
        transaction_cost_bps=5.0,
        annualization=365,
    )
    result = run_walk_forward_research(
        source_prices,
        base_config=base_config,
        momentum_lookbacks=[21, 90],
        reversal_lookbacks=[3],
        trend_weights=[0.7],
        selection_bars=300,
        test_bars=100,
        cost_multipliers=[1.0, 1.5, 2.0, 3.0],
        provenance={
            "provider": "OKX",
            "instrument_id": "BTC-USDT",
            "bar": "1Dutc",
            "normalized_csv_sha256": snapshot_sha256,
        },
    )
    paths = write_walk_forward_report(result, output)
    effective_config_path = output / "effective_config.json"
    effective_config_path.write_text(
        json.dumps(
            {
                "data": {"inst_id": "BTC-USDT", "bar": "1Dutc"},
                "strategy": base_config.to_dict(),
                "search": {
                    "momentum_lookbacks": [21, 90],
                    "reversal_lookbacks": [3],
                    "trend_weights": [0.7],
                    "selection_bars": 300,
                    "test_bars": 100,
                },
                "robustness": {"cost_multipliers": [1.0, 1.5, 2.0, 3.0]},
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    paths["snapshot"] = snapshot_path
    paths["effective_config"] = effective_config_path
    return paths


def test_selection_verifier_reruns_every_real_okx_candidate(
    btc_usdt_prices: pd.Series,
    tmp_path: Path,
) -> None:
    paths = _write_report(btc_usdt_prices, tmp_path)

    verification = verify_walk_forward_selection(tmp_path)

    assert verification["selection_folds_verified"] == 3
    assert verification["selection_candidates_per_fold"] == 2
    assert verification["selection_candidate_evaluations_verified"] == 6
    assert verification["selection_metric_tolerance"] == 1e-9
    assert (
        verification["selection_source"]
        == "immutable_normalized_okx_close_and_effective_config_full_5bps_reselection"
    )
    assert (
        verification["effective_config_sha256"]
        == hashlib.sha256(paths["effective_config"].read_bytes()).hexdigest()
    )


def test_selection_verifier_rejects_self_consistent_nonwinning_path(
    btc_usdt_prices: pd.Series,
    tmp_path: Path,
) -> None:
    paths = _write_report(btc_usdt_prices, tmp_path)
    report = json.loads(paths["json"].read_text(encoding="utf-8"))
    returns = pd.read_csv(paths["returns"], float_precision="round_trip")
    first_fold = report["folds"][0]
    selected = StrategyConfig(**first_fold["selected_parameters"])
    wrong = selected.with_overrides(
        momentum_lookback=90 if selected.momentum_lookback == 21 else 21
    )
    test_start = pd.Timestamp(first_fold["test_start"])
    test_end = pd.Timestamp(first_fold["test_end"])
    wrong_frame = run_backtest(
        btc_usdt_prices.iloc[:600].loc[:test_end],
        wrong,
        start=test_start,
        end=test_end,
    ).frame
    fold_mask = returns["fold"].eq(int(first_fold["fold"]))
    assert int(fold_mask.sum()) == len(wrong_frame)
    returns.loc[fold_mask, "target_position"] = wrong_frame["target_position"].to_numpy(copy=False)
    returns.loc[fold_mask, "position"] = wrong_frame["position"].to_numpy(copy=False)
    returns["turnover"] = returns["position"].diff().abs().fillna(returns["position"].abs())
    returns["gross_strategy_return"] = returns["position"] * returns["asset_return"]
    returns["trading_cost"] = returns["turnover"] * 5.0 / 10_000.0
    returns["strategy_return"] = returns["gross_strategy_return"] - returns["trading_cost"]
    returns["nav"] = (1.0 + returns["strategy_return"]).cumprod()
    returns.to_csv(paths["returns"], index=False)

    first_fold["selected_parameters"] = wrong.to_dict()
    annualization = int(report["settings"]["base_config"]["annualization"])
    report["aggregate_metrics"] = performance_metrics(returns, annualization=annualization)
    for fold in report["folds"]:
        fold_frame = returns.loc[returns["fold"].eq(int(fold["fold"]))]
        fold["test_metrics"] = performance_metrics(fold_frame, annualization=annualization)
    paths["json"].write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    assert verify_walk_forward_report(tmp_path)["status"] == "passed"
    with pytest.raises(
        ValueError,
        match="fold 1 selected_parameters do not match full 5 bps reselection",
    ):
        verify_walk_forward_selection(tmp_path)
