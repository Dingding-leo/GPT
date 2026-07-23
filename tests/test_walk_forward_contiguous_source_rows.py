from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from gpt_quant import StrategyConfig, run_walk_forward_research
from gpt_quant.metrics import performance_metrics
from gpt_quant.walk_forward_report import write_walk_forward_report
from gpt_quant.walk_forward_verify_gate import verify_walk_forward_report


def test_verifier_rejects_self_consistent_omitted_oos_row(
    btc_usdt_prices: pd.Series,
    tmp_path: Path,
) -> None:
    source_prices = btc_usdt_prices.iloc[:500]
    snapshot_dir = tmp_path / "snapshot"
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

    result = run_walk_forward_research(
        source_prices,
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
            "normalized_csv_sha256": snapshot_sha256,
        },
    )
    paths = write_walk_forward_report(result, tmp_path)
    returns = pd.read_csv(paths["returns"])
    safe_rows = returns.index[
        (returns.index > 0)
        & (returns.index < len(returns) - 1)
        & returns["fold"].eq(returns["fold"].shift())
        & returns["fold"].eq(returns["fold"].shift(-1))
        & returns["position"].eq(0.0)
        & returns["position"].shift().eq(0.0)
        & returns["position"].shift(-1).eq(0.0)
        & returns["target_position"].eq(0.0)
        & returns["target_position"].shift().eq(0.0)
        & returns["turnover"].eq(0.0)
        & returns["strategy_return"].eq(0.0)
    ]
    assert len(safe_rows) > 0
    returns = returns.drop(index=int(safe_rows[0])).reset_index(drop=True)
    returns.to_csv(paths["returns"], index=False)

    report = json.loads(paths["json"].read_text(encoding="utf-8"))
    annualization = int(report["settings"]["base_config"]["annualization"])
    report["aggregate_metrics"] = performance_metrics(returns, annualization=annualization)
    for fold in report["folds"]:
        fold_frame = returns.loc[returns["fold"] == int(fold["fold"])]
        fold["test_metrics"] = performance_metrics(fold_frame, annualization=annualization)
    paths["json"].write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="contiguous normalized OKX snapshot rows"):
        verify_walk_forward_report(tmp_path)
