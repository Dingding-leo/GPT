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

_FIXTURE_METADATA_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "okx"
    / "btc-usdt-1dutc-20180111-20200628"
    / "metadata.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_real_okx_report(prices: pd.Series, root: Path) -> dict[str, Path]:
    source_prices = prices.iloc[:500]
    output = root / "BTC-USDT"
    snapshot = output / "snapshot"
    snapshot.mkdir(parents=True)
    source_csv = snapshot / "okx-BTC-USDT-1Dutc.csv"
    source_metadata = snapshot / "okx-BTC-USDT-1Dutc.metadata.json"
    pd.DataFrame(
        {
            "timestamp": source_prices.index,
            "close": source_prices.to_numpy(copy=False),
            "confirm": 1,
        }
    ).to_csv(
        source_csv,
        index=False,
        date_format="%Y-%m-%dT%H:%M:%S.%fZ",
        float_format="%.12g",
        lineterminator="\n",
    )
    source_csv_sha256 = _sha256(source_csv)
    fixture_metadata = json.loads(_FIXTURE_METADATA_PATH.read_text(encoding="utf-8"))
    metadata = {
        "provider": "OKX",
        "instrument_id": "BTC-USDT",
        "bar": "1Dutc",
        "confirmed_only": True,
        "observations": len(source_prices),
        "start": source_prices.index[0].isoformat(),
        "end": source_prices.index[-1].isoformat(),
        "expected_step_seconds": 86_400,
        "missing_intervals": 0,
        "normalized_csv_sha256": source_csv_sha256,
        "source_artifact_id": fixture_metadata["source_artifact_id"],
        "source_artifact_sha256": fixture_metadata["source_artifact_sha256"],
        "source_head_sha": fixture_metadata["source_head_sha"],
        "source_normalized_csv_sha256": fixture_metadata["source_normalized_csv_sha256"],
        "source_raw_pages_sha256": fixture_metadata["source_raw_pages_sha256"],
        "source_workflow_run_id": fixture_metadata["source_workflow_run_id"],
    }
    source_metadata.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

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
            "normalized_csv_sha256": source_csv_sha256,
        },
    )
    paths = write_walk_forward_report(result, output)

    effective_config = output / "effective_config.json"
    effective_config.write_text(
        json.dumps(
            {
                "data": {"bar": "1Dutc", "inst_id": "BTC-USDT"},
                "robustness": {"cost_multipliers": [1.0, 1.5, 2.0, 3.0]},
                "search": {
                    "momentum_lookbacks": [21],
                    "reversal_lookbacks": [3],
                    "selection_bars": 300,
                    "test_bars": 100,
                    "trend_weights": [0.7],
                },
                "strategy": result.settings["base_config"],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    manifest = root / "experiment-manifest.jsonl"
    manifest_record = {
        "artifact_sha256": {
            "candles": source_csv_sha256,
            "effective_config": _sha256(effective_config),
            "json": _sha256(paths["json"]),
            "metadata": _sha256(source_metadata),
            "returns": _sha256(paths["returns"]),
        },
        "bar": "1Dutc",
        "candidate_count": 1,
        "code_commit": fixture_metadata["source_head_sha"],
        "config_sha256": _sha256(effective_config),
        "data_sha256": {"normalized_csv": source_csv_sha256},
        "instrument_id": "BTC-USDT",
        "result_classification": result.robustness_status,
        "schema_version": 1,
    }
    manifest.write_text(
        json.dumps(
            manifest_record,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        **paths,
        "output": output,
        "source_csv": source_csv,
        "source_metadata": source_metadata,
        "effective_config": effective_config,
        "manifest": manifest,
    }


def _without_explicit_offset(value: object) -> str:
    serialized = str(value)
    if serialized.endswith("+00:00"):
        return serialized[: -len("+00:00")]
    if serialized.endswith("Z"):
        return serialized[:-1]
    raise AssertionError(f"expected an explicit UTC timestamp, got {serialized!r}")


def _refresh_manifest_artifact_hashes(paths: dict[str, Path]) -> None:
    record = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    record["artifact_sha256"]["json"] = _sha256(paths["json"])
    record["artifact_sha256"]["returns"] = _sha256(paths["returns"])
    paths["manifest"].write_text(
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _refresh_persisted_metrics(paths: dict[str, Path], returns: pd.DataFrame) -> None:
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
    _refresh_manifest_artifact_hashes(paths)


def test_verifier_recomputes_persisted_real_okx_report(
    btc_usdt_prices: pd.Series,
    tmp_path: Path,
) -> None:
    paths = _write_real_okx_report(btc_usdt_prices, tmp_path)

    verification = verify_walk_forward_report(paths["output"])

    returns = pd.read_csv(paths["returns"])
    assert verification["status"] == "passed"
    assert verification["transaction_cost_bps"] == 5.0
    assert verification["observations"] == len(returns)
    assert verification["folds"] == returns["fold"].nunique()
    assert verification["fold_boundary_position_transitions_verified"] == 1
    assert verification["within_fold_delayed_position_rows_verified"] == len(returns) - 2
    assert verification["accounting_tolerance"] == 1e-12
    assert verification["metric_tolerance"] == 1e-9
    assert verification["source_provider"] == "OKX"
    assert verification["source_instrument_id"] == "BTC-USDT"
    assert verification["source_bar"] == "1Dutc"
    assert verification["source_price_rows_verified"] == len(returns)
    assert verification["source_return_rows_verified"] == len(returns)
    assert verification["asset_return_source"] == "immutable_normalized_okx_close_pct_change"
    assert verification["source_normalized_csv_sha256"] == _sha256(paths["source_csv"])
    assert verification["source_metadata_sha256"] == _sha256(paths["source_metadata"])
    assert verification["source_manifest_sha256"] == _sha256(paths["manifest"])
    assert verification["source_config_sha256"] == _sha256(paths["effective_config"])
    assert (
        verification["source_preceding_close_timestamp"]
        == btc_usdt_prices.index[299].isoformat()
    )
    assert verification["report_json_sha256"] == _sha256(paths["json"])
    assert verification["returns_csv_sha256"] == _sha256(paths["returns"])
    assert verification["spread_model"] == "not_modeled"
    assert verification["slippage_model"] == "not_modeled"
    assert verification["market_impact_model"] == "not_modeled"
    assert verification["latency_model"] == "not_modeled"


def test_verifier_rejects_self_consistent_asset_return_tamper(
    btc_usdt_prices: pd.Series,
    tmp_path: Path,
) -> None:
    paths = _write_real_okx_report(btc_usdt_prices, tmp_path)
    returns = pd.read_csv(paths["returns"])
    row = int(returns.index[returns["position"].abs() > 0.0][0])
    returns.loc[row, "asset_return"] += 0.01
    returns.loc[row, "gross_strategy_return"] = (
        returns.loc[row, "position"] * returns.loc[row, "asset_return"]
    )
    returns.loc[row, "strategy_return"] = (
        returns.loc[row, "gross_strategy_return"] - returns.loc[row, "trading_cost"]
    )
    returns.to_csv(paths["returns"], index=False)
    _refresh_persisted_metrics(paths, returns)

    with pytest.raises(ValueError, match="asset_return from immutable OKX closes"):
        verify_walk_forward_report(paths["output"])


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
        verify_walk_forward_report(paths["output"])


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
        verify_walk_forward_report(paths["output"])


def test_verifier_accepts_fold_boundary_model_switch_accounting(
    btc_usdt_prices: pd.Series,
    tmp_path: Path,
) -> None:
    paths = _write_real_okx_report(btc_usdt_prices, tmp_path)
    returns = pd.read_csv(paths["returns"])
    boundary = int(returns.index[returns["fold"].ne(returns["fold"].shift())][1])

    returns.loc[boundary - 1, "target_position"] += 0.1
    returns.to_csv(paths["returns"], index=False)
    _refresh_manifest_artifact_hashes(paths)

    verification = verify_walk_forward_report(paths["output"])
    assert verification["status"] == "passed"
    assert verification["fold_boundary_position_transitions_verified"] == 1


def test_verifier_rejects_naive_report_timestamp(
    btc_usdt_prices: pd.Series,
    tmp_path: Path,
) -> None:
    paths = _write_real_okx_report(btc_usdt_prices, tmp_path)
    report = json.loads(paths["json"].read_text(encoding="utf-8"))
    report["data_summary"]["evaluation_start"] = _without_explicit_offset(
        report["data_summary"]["evaluation_start"]
    )
    paths["json"].write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="explicit UTC offset"):
        verify_walk_forward_report(paths["output"])


def test_verifier_rejects_naive_returns_timestamp(
    btc_usdt_prices: pd.Series,
    tmp_path: Path,
) -> None:
    paths = _write_real_okx_report(btc_usdt_prices, tmp_path)
    returns = pd.read_csv(paths["returns"])
    returns["timestamp"] = returns["timestamp"].map(_without_explicit_offset)
    returns.to_csv(paths["returns"], index=False)

    with pytest.raises(ValueError, match="explicit UTC offset"):
        verify_walk_forward_report(paths["output"])
