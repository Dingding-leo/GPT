from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

import gpt_quant.walk_forward_verify_gate as verify_gate
from gpt_quant import StrategyConfig, run_walk_forward_research
from gpt_quant.walk_forward_report import write_walk_forward_report


def _write_repeated_selection_report(prices: pd.Series, output: Path) -> dict[str, Path]:
    source_prices = prices.iloc[:500]
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
            "normalized_csv_sha256": hashlib.sha256(snapshot_path.read_bytes()).hexdigest(),
        },
    )
    paths = write_walk_forward_report(result, output)
    paths["snapshot"] = snapshot_path
    return paths


def test_verifier_reuses_one_source_path_per_selected_config(
    btc_usdt_prices: pd.Series,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _write_repeated_selection_report(btc_usdt_prices, tmp_path)
    report = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert len(report["folds"]) == 2
    assert report["folds"][0]["selected_parameters"] == report["folds"][1]["selected_parameters"]

    original = verify_gate.run_backtest
    calls: list[tuple[pd.Timestamp, pd.Timestamp, StrategyConfig]] = []

    def counted_run_backtest(
        prices: pd.Series,
        config: StrategyConfig,
        *,
        start: pd.Timestamp | str | None = None,
        end: pd.Timestamp | str | None = None,
    ):
        calls.append((prices.index[0], prices.index[-1], config))
        return original(prices, config, start=start, end=end)

    monkeypatch.setattr(verify_gate, "run_backtest", counted_run_backtest)

    verification = verify_gate.verify_walk_forward_report(tmp_path)

    assert verification["selected_folds_verified"] == 2
    assert verification["selected_target_rows_verified"] == 200
    assert verification["selected_position_rows_verified"] == 200
    assert len(calls) == 1
    assert calls[0][0] == btc_usdt_prices.index[0]
    assert calls[0][1] == btc_usdt_prices.index[499]
    assert calls[0][2] == StrategyConfig(**report["folds"][0]["selected_parameters"])
