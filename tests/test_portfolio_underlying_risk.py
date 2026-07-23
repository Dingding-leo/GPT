from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from gpt_quant.portfolio_underlying_risk import (
    build_underlying_sleeve_risk,
    write_underlying_sleeve_risk_report,
)

_FIXTURE_DIR = (
    Path(__file__).parent
    / "fixtures"
    / "okx"
    / "btc_eth_full_path_20200111_20200219"
)


def _fixture_inputs() -> tuple[dict[str, Path], dict[str, str], dict[str, object]]:
    metadata = json.loads((_FIXTURE_DIR / "metadata.json").read_text(encoding="utf-8"))
    paths = {
        name: _FIXTURE_DIR / details["fixture_file"]
        for name, details in metadata["instruments"].items()
    }
    hashes = {
        name: details["fixture_sha256"]
        for name, details in metadata["instruments"].items()
    }
    provenance = {
        key: metadata[key]
        for key in (
            "provider",
            "market_type",
            "timeframe",
            "source_workflow_run_id",
            "source_artifact_id",
            "source_artifact_name",
            "source_artifact_sha256",
            "source_head_sha",
        )
    }
    provenance["return_file_sha256"] = hashes
    return paths, hashes, provenance


def test_underlying_risk_exposes_real_sleeve_exposure_turnover_and_fee(tmp_path: Path) -> None:
    paths, hashes, provenance = _fixture_inputs()
    result = build_underlying_sleeve_risk(
        paths,
        expected_sha256=hashes,
        initial_weights={"BTC-USDT": 0.5, "ETH-USDT": 0.5},
        provenance=provenance,
    )

    source_frames = {
        name: pd.read_csv(path, parse_dates=["timestamp"]).set_index("timestamp")
        for name, path in paths.items()
    }
    for name, frame in source_frames.items():
        metrics = result.sleeve_metrics[name]
        assert metrics["current_absolute_exposure"] == pytest.approx(
            abs(frame["position"].iloc[-1])
        )
        assert metrics["maximum_absolute_exposure"] == pytest.approx(
            frame["position"].abs().max()
        )
        assert metrics["total_absolute_turnover"] == pytest.approx(frame["turnover"].sum())
        assert metrics["exchange_fee_sum"] == pytest.approx(frame["trading_cost"].sum())
        assert metrics["exchange_fee_sum"] == pytest.approx(
            metrics["total_absolute_turnover"] * 0.0005
        )

    assert result.portfolio_metrics["average_start_of_bar_absolute_market_exposure"] < 1.0
    assert result.portfolio_metrics["maximum_start_of_bar_absolute_market_exposure"] < 1.0
    assert result.portfolio_metrics["total_weighted_underlying_turnover"] > 0.0
    assert result.portfolio_metrics["portfolio_exchange_fee_sum"] > 0.0
    assert result.cost_attribution["exchange_fee"]["one_way_bps"] == 5.0
    assert result.cost_attribution["spread"] == {"status": "not_modeled"}
    assert result.cost_attribution["slippage"] == {"status": "not_modeled"}
    assert result.cost_attribution["market_impact"] == {"status": "not_modeled"}
    assert result.cost_attribution["latency"] == {"status": "not_modeled"}
    assert result.cost_attribution["all_in_fixed_path_sensitivity_bps"] == [7.5, 10.0, 15.0]

    path = write_underlying_sleeve_risk_report(result, tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema"] == "portfolio_underlying_path_risk_v1"
    assert payload["deployment_eligible"] is False
    assert payload["portfolio_metrics"] == result.portfolio_metrics


def test_underlying_risk_rejects_self_consistent_hash_for_corrupted_turnover(
    tmp_path: Path,
) -> None:
    paths, hashes, provenance = _fixture_inputs()
    corrupted = tmp_path / "btc.csv"
    frame = pd.read_csv(paths["BTC-USDT"])
    frame.loc[10, "turnover"] = float(frame.loc[10, "turnover"]) + 0.25
    frame.loc[10, "trading_cost"] = float(frame.loc[10, "turnover"]) * 0.0005
    frame.loc[10, "strategy_return"] = (
        float(frame.loc[10, "gross_strategy_return"])
        - float(frame.loc[10, "trading_cost"])
    )
    frame.to_csv(corrupted, index=False)
    corrupted_hash = hashlib.sha256(corrupted.read_bytes()).hexdigest()
    altered_paths = dict(paths)
    altered_hashes = dict(hashes)
    altered_paths["BTC-USDT"] = corrupted
    altered_hashes["BTC-USDT"] = corrupted_hash
    provenance["return_file_sha256"] = altered_hashes

    with pytest.raises(ValueError, match="turnover must equal absolute underlying position changes"):
        build_underlying_sleeve_risk(
            altered_paths,
            expected_sha256=altered_hashes,
            initial_weights={"BTC-USDT": 0.5, "ETH-USDT": 0.5},
            provenance=provenance,
        )


def test_underlying_risk_requires_declared_five_bps_fee_baseline() -> None:
    paths, hashes, provenance = _fixture_inputs()

    with pytest.raises(ValueError, match="declared 5 bps fee baseline"):
        build_underlying_sleeve_risk(
            paths,
            expected_sha256=hashes,
            initial_weights={"BTC-USDT": 0.5, "ETH-USDT": 0.5},
            provenance=provenance,
            exchange_fee_bps=7.5,
        )


def test_hourly_workflow_generates_underlying_risk_before_portfolio_gate() -> None:
    workflow = (
        Path(__file__).parents[1] / ".github" / "workflows" / "hourly-research.yml"
    ).read_text(encoding="utf-8")

    source_upload = workflow.index("- name: Upload immutable sleeve research source")
    underlying = workflow.index("- name: Generate verified underlying sleeve risk report")
    portfolio = workflow.index("- name: Generate verified portfolio risk report")
    upload = workflow.index("- name: Upload verified portfolio risk artifact")

    assert source_upload < underlying < portfolio < upload
    assert workflow.count("python scripts/run_portfolio_underlying_risk.py") == 1
    underlying_block = workflow[underlying:portfolio]
    assert '--btc-returns reports/okx/BTC-USDT/walk_forward_returns.csv' in underlying_block
    assert '--eth-returns reports/okx/ETH-USDT/walk_forward_returns.csv' in underlying_block
    assert '--source-artifact-sha256 "$source_artifact_digest"' in underlying_block
    assert '--source-head-sha "$GITHUB_SHA"' in underlying_block
    assert "--output-dir reports/portfolio" in underlying_block
