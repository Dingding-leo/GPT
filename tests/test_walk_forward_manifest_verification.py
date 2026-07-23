from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from gpt_quant import StrategyConfig, run_walk_forward_research
from gpt_quant.reproducibility import (
    append_experiment_manifest,
    build_experiment_manifest_entry,
)
from gpt_quant.walk_forward_manifest_verify import verify_walk_forward_manifest
from gpt_quant.walk_forward_report import write_walk_forward_report


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def _write_manifest_bound_report(prices: pd.Series, output: Path) -> dict[str, Path]:
    source_prices = prices.iloc[:500]
    snapshot_dir = output / "snapshot"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = snapshot_dir / "okx-BTC-USDT-1Dutc.csv"
    pd.DataFrame(
        {
            "timestamp": source_prices.index.map(lambda value: value.isoformat()),
            "close": source_prices.to_numpy(copy=False),
            "confirm": 1,
        }
    ).to_csv(snapshot_path, index=False)
    snapshot_sha256 = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()

    strategy = StrategyConfig(
        min_position=0.0,
        transaction_cost_bps=5.0,
        annualization=365,
    )
    cost_multipliers = [1.0, 1.5, 2.0, 3.0]
    result = run_walk_forward_research(
        source_prices,
        base_config=strategy,
        momentum_lookbacks=[21],
        reversal_lookbacks=[3],
        trend_weights=[0.7],
        selection_bars=300,
        test_bars=100,
        cost_multipliers=cost_multipliers,
        provenance={
            "provider": "OKX",
            "instrument_id": "BTC-USDT",
            "bar": "1Dutc",
            "normalized_csv_sha256": snapshot_sha256,
        },
    )
    paths = write_walk_forward_report(result, output)

    effective_config = {
        "data": {"inst_id": "BTC-USDT", "bar": "1Dutc"},
        "strategy": strategy.to_dict(),
        "search": {
            "momentum_lookbacks": [21],
            "reversal_lookbacks": [3],
            "trend_weights": [0.7],
            "selection_bars": 300,
            "test_bars": 100,
        },
        "robustness": {"cost_multipliers": cost_multipliers},
    }
    effective_config_path = output / "effective_config.json"
    effective_config_path.write_text(_canonical_json(effective_config), encoding="utf-8")

    manifest_path = output / "experiment-manifest.jsonl"
    entry = build_experiment_manifest_entry(
        effective_config=effective_config,
        data_hashes={"normalized_csv": snapshot_sha256},
        data_paths={"normalized_csv": snapshot_path},
        artifact_paths={
            "candles": snapshot_path,
            "effective_config": effective_config_path,
            "json": paths["json"],
            "returns": paths["returns"],
        },
        candidate_count=int(result.settings["candidate_count"]),
        result_classification=result.robustness_status,
        instrument_id="BTC-USDT",
        bar="1Dutc",
        code_commit="a" * 40,
        recorded_at_utc="2026-07-24T00:00:00+00:00",
    )
    append_experiment_manifest(manifest_path, entry)
    paths["snapshot"] = snapshot_path
    paths["effective_config"] = effective_config_path
    paths["manifest"] = manifest_path
    return paths


def test_manifest_verifier_binds_real_okx_report_to_exact_evidence(
    btc_usdt_prices: pd.Series,
    tmp_path: Path,
) -> None:
    paths = _write_manifest_bound_report(btc_usdt_prices, tmp_path)

    binding = verify_walk_forward_manifest(tmp_path, paths["manifest"])

    assert binding["manifest_schema_version"] == 1
    assert binding["manifest_code_commit"] == "a" * 40
    assert binding["manifest_candidate_count"] == 1
    assert binding["manifest_experiment_id"].startswith("exp-")
    assert binding["manifest_run_id"].startswith("run-")
    assert binding["manifest_normalized_csv_sha256"] == hashlib.sha256(
        paths["snapshot"].read_bytes()
    ).hexdigest()


def test_manifest_verifier_rejects_self_consistent_report_outside_manifest(
    btc_usdt_prices: pd.Series,
    tmp_path: Path,
) -> None:
    paths = _write_manifest_bound_report(btc_usdt_prices, tmp_path)
    entry = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    entry["artifact_sha256"]["returns"] = "0" * 64
    paths["manifest"].write_text(_canonical_json(entry), encoding="utf-8")

    with pytest.raises(ValueError, match="exactly one entry bound"):
        verify_walk_forward_manifest(tmp_path, paths["manifest"])
