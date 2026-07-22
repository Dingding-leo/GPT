from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

import gpt_quant.portfolio as portfolio
from gpt_quant.portfolio import (
    build_buy_and_hold_sleeve_portfolio,
    load_verified_return_csv,
)

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "okx" / "btc_eth_oos_20200111_20200219"
_SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "run_portfolio_risk.py"
_SCRIPT_SPEC = importlib.util.spec_from_file_location(
    "run_portfolio_risk_correlation", _SCRIPT_PATH
)
if _SCRIPT_SPEC is None or _SCRIPT_SPEC.loader is None:
    raise RuntimeError(f"unable to load portfolio risk CLI from {_SCRIPT_PATH}")
run_portfolio_risk = importlib.util.module_from_spec(_SCRIPT_SPEC)
_SCRIPT_SPEC.loader.exec_module(run_portfolio_risk)


def _load_fixture_returns() -> tuple[pd.Series, pd.Series, dict[str, object]]:
    metadata = json.loads((_FIXTURE_DIR / "metadata.json").read_text(encoding="utf-8"))
    instruments = metadata["instruments"]
    btc = load_verified_return_csv(
        _FIXTURE_DIR / "btc_usdt_returns.csv",
        expected_sha256=instruments["BTC-USDT"]["fixture_sha256"],
    )
    eth = load_verified_return_csv(
        _FIXTURE_DIR / "eth_usdt_returns.csv",
        expected_sha256=instruments["ETH-USDT"]["fixture_sha256"],
    )
    return btc, eth, metadata


def _fixture_provenance(metadata: dict[str, object]) -> dict[str, object]:
    instruments = metadata["instruments"]
    return {
        "provider": metadata["provider"],
        "market_type": metadata["market_type"],
        "timeframe": metadata["timeframe"],
        "source_workflow_run_id": metadata["source_workflow_run_id"],
        "source_artifact_id": metadata["source_artifact_id"],
        "source_artifact_name": metadata["source_artifact_name"],
        "source_artifact_sha256": metadata["source_artifact_sha256"],
        "source_head_sha": metadata["source_head_sha"],
        "return_file_sha256": {
            name: details["fixture_sha256"] for name, details in instruments.items()
        },
    }


def _build(max_pairwise_correlation: float):
    btc, eth, metadata = _load_fixture_returns()
    return build_buy_and_hold_sleeve_portfolio(
        {"BTC-USDT": btc, "ETH-USDT": eth},
        initial_weights={"BTC-USDT": 0.5, "ETH-USDT": 0.5},
        max_sleeve_weight=0.75,
        max_variance_contribution=0.75,
        max_pairwise_correlation=max_pairwise_correlation,
        provenance=_fixture_provenance(metadata),
    )


def test_correlation_budget_matches_independent_real_return_calculation() -> None:
    btc, eth, _ = _load_fixture_returns()
    expected = float(btc.corr(eth))

    result = _build(max_pairwise_correlation=0.90)

    assert expected == pytest.approx(0.7624497485015761)
    assert result.dependence["maximum_observed_pairwise_correlation"] == pytest.approx(expected)
    assert result.dependence["maximum_correlation_pair"] == ["BTC-USDT", "ETH-USDT"]
    assert result.dependence["correlation_breaches"] == []
    assert result.dependence["unavailable_correlation_pairs"] == []
    assert result.dependence["correlation_control_passes"] is True
    assert result.concentration["passes"] is True
    assert result.risk_status.startswith("pass:")


def test_tighter_correlation_budget_rejects_real_sleeve_dependence() -> None:
    result = _build(max_pairwise_correlation=0.75)

    assert result.dependence["maximum_observed_pairwise_correlation"] > 0.75
    assert result.dependence["correlation_breaches"] == [["BTC-USDT", "ETH-USDT"]]
    assert result.dependence["correlation_control_passes"] is False
    assert result.concentration["weight_concentration_passes"] is True
    assert result.concentration["variance_contribution_passes"] is True
    assert result.concentration["passes"] is False
    assert "pairwise return correlation breaches the declared limit" in result.risk_status


def test_simultaneous_concentration_failures_are_all_reported() -> None:
    btc, eth, metadata = _load_fixture_returns()

    result = build_buy_and_hold_sleeve_portfolio(
        {"BTC-USDT": btc, "ETH-USDT": eth},
        initial_weights={"BTC-USDT": 0.8, "ETH-USDT": 0.2},
        max_sleeve_weight=0.75,
        max_variance_contribution=0.70,
        max_pairwise_correlation=0.75,
        provenance=_fixture_provenance(metadata),
    )

    assert result.concentration["weight_concentration_passes"] is False
    assert result.concentration["variance_contribution_breaches"] == ["BTC-USDT"]
    assert result.concentration["variance_contribution_passes"] is False
    assert result.dependence["correlation_breaches"] == [["BTC-USDT", "ETH-USDT"]]
    assert result.dependence["correlation_control_passes"] is False
    assert result.concentration["passes"] is False
    assert "buy-and-hold sleeve-weight drift breaches the declared limit" in result.risk_status
    assert "initial-weight variance contribution breaches the declared limit" in result.risk_status
    assert "pairwise return correlation breaches the declared limit" in result.risk_status


def test_zero_variance_pair_fails_closed_as_unavailable() -> None:
    btc, eth, metadata = _load_fixture_returns()
    btc = btc.iloc[:20]
    eth = eth.iloc[:20]
    assert eth.eq(0.0).all()

    result = build_buy_and_hold_sleeve_portfolio(
        {"BTC-USDT": btc, "ETH-USDT": eth},
        initial_weights={"BTC-USDT": 0.5, "ETH-USDT": 0.5},
        max_pairwise_correlation=0.90,
        provenance=_fixture_provenance(metadata),
    )

    assert result.dependence["maximum_observed_pairwise_correlation"] is None
    assert result.dependence["maximum_correlation_pair"] is None
    assert result.dependence["correlation_breaches"] == []
    assert result.dependence["unavailable_correlation_pairs"] == [["BTC-USDT", "ETH-USDT"]]
    assert result.dependence["correlation_control_passes"] is False
    assert "pairwise return correlation is unavailable" in result.risk_status
    assert "pairwise return correlation breaches" not in result.risk_status


def test_cli_persists_nondefault_correlation_budget_and_rejection(tmp_path: Path) -> None:
    _, _, metadata = _load_fixture_returns()
    instruments = metadata["instruments"]
    output_dir = tmp_path / "portfolio"

    exit_code = run_portfolio_risk.main(
        [
            "--btc-returns",
            str(_FIXTURE_DIR / "btc_usdt_returns.csv"),
            "--eth-returns",
            str(_FIXTURE_DIR / "eth_usdt_returns.csv"),
            "--btc-sha256",
            instruments["BTC-USDT"]["fixture_sha256"],
            "--eth-sha256",
            instruments["ETH-USDT"]["fixture_sha256"],
            "--max-pairwise-correlation",
            "0.75",
            "--provider",
            metadata["provider"],
            "--market-type",
            metadata["market_type"],
            "--timeframe",
            metadata["timeframe"],
            "--source-workflow-run",
            str(metadata["source_workflow_run_id"]),
            "--source-artifact-id",
            str(metadata["source_artifact_id"]),
            "--source-artifact-name",
            metadata["source_artifact_name"],
            "--source-artifact-sha256",
            metadata["source_artifact_sha256"],
            "--source-head-sha",
            metadata["source_head_sha"],
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    saved = json.loads((output_dir / "portfolio_risk.json").read_text(encoding="utf-8"))
    markdown = (output_dir / "portfolio_risk.md").read_text(encoding="utf-8")
    assert saved["settings"]["max_pairwise_correlation"] == pytest.approx(0.75)
    assert saved["dependence"]["maximum_allowed_pairwise_correlation"] == pytest.approx(0.75)
    assert saved["dependence"]["maximum_correlation_pair"] == ["BTC-USDT", "ETH-USDT"]
    assert saved["dependence"]["correlation_control_passes"] is False
    assert saved["risk_status"].startswith("reject:")
    assert "pairwise return correlation" in saved["risk_status"]
    assert "- Maximum allowed pairwise correlation: 0.750000" in markdown
    assert "- Maximum observed pairwise correlation: BTC-USDT / ETH-USDT (0.762450)" in markdown


@pytest.mark.parametrize("limit", [True, 0.0, 1.0, float("nan"), float("inf")])
def test_invalid_correlation_budget_fails_before_metrics(
    limit: float,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    btc, eth, metadata = _load_fixture_returns()

    def unexpected_metrics(*args: object, **kwargs: object) -> None:
        pytest.fail("portfolio metrics ran before correlation-budget validation")

    monkeypatch.setattr(portfolio, "performance_metrics", unexpected_metrics)
    with pytest.raises(ValueError, match=r"max_pairwise_correlation.*\(0, 1\)"):
        build_buy_and_hold_sleeve_portfolio(
            {"BTC-USDT": btc, "ETH-USDT": eth},
            initial_weights={"BTC-USDT": 0.5, "ETH-USDT": 0.5},
            max_pairwise_correlation=limit,
            provenance=_fixture_provenance(metadata),
        )
