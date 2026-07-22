from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import gpt_quant.portfolio as portfolio
from gpt_quant.portfolio import (
    build_buy_and_hold_sleeve_portfolio,
    load_verified_return_csv,
)

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "okx" / "btc_eth_oos_20200111_20200219"
_SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "run_portfolio_risk.py"
_SCRIPT_SPEC = importlib.util.spec_from_file_location("run_portfolio_risk_variance", _SCRIPT_PATH)
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


def _build(max_variance_contribution: float):
    btc, eth, metadata = _load_fixture_returns()
    return build_buy_and_hold_sleeve_portfolio(
        {"BTC-USDT": btc, "ETH-USDT": eth},
        initial_weights={"BTC-USDT": 0.5, "ETH-USDT": 0.5},
        max_sleeve_weight=0.75,
        max_variance_contribution=max_variance_contribution,
        provenance=_fixture_provenance(metadata),
    )


def test_variance_budget_matches_independent_real_return_calculation() -> None:
    btc, eth, _ = _load_fixture_returns()
    returns = np.column_stack([btc.to_numpy(), eth.to_numpy()])
    covariance = np.cov(returns, rowvar=False, ddof=0) * 365
    weights = np.array([0.5, 0.5])
    marginal_variance = covariance @ weights
    expected = weights * marginal_variance / float(weights @ marginal_variance)

    result = _build(max_variance_contribution=0.75)

    assert result.risk_contributions == pytest.approx(
        {"BTC-USDT": expected[0], "ETH-USDT": expected[1]}
    )
    assert result.concentration["maximum_variance_contributor"] == "BTC-USDT"
    assert result.concentration["maximum_observed_variance_contribution"] == pytest.approx(
        expected.max()
    )
    assert result.concentration["variance_contribution_passes"] is True
    assert result.concentration["passes"] is True
    assert result.risk_status.startswith("pass:")


def test_tighter_variance_budget_rejects_single_sleeve_risk_concentration() -> None:
    result = _build(max_variance_contribution=0.70)

    assert result.risk_contributions["BTC-USDT"] > 0.70
    assert result.concentration["variance_contribution_breaches"] == ["BTC-USDT"]
    assert result.concentration["variance_contribution_passes"] is False
    assert result.concentration["weight_concentration_passes"] is True
    assert result.concentration["passes"] is False
    assert "variance contribution" in result.risk_status


def test_simultaneous_weight_and_variance_breaches_are_both_reported() -> None:
    btc, eth, metadata = _load_fixture_returns()

    result = build_buy_and_hold_sleeve_portfolio(
        {"BTC-USDT": btc, "ETH-USDT": eth},
        initial_weights={"BTC-USDT": 0.8, "ETH-USDT": 0.2},
        max_sleeve_weight=0.75,
        max_variance_contribution=0.70,
        provenance=_fixture_provenance(metadata),
    )

    assert result.concentration["initial_weight_breach"] is True
    assert result.concentration["weight_concentration_passes"] is False
    assert result.concentration["variance_contribution_breaches"] == ["BTC-USDT"]
    assert result.concentration["variance_contribution_passes"] is False
    assert result.concentration["passes"] is False
    assert "buy-and-hold sleeve-weight drift" in result.risk_status
    assert "initial-weight variance contribution" in result.risk_status


def test_cli_persists_nondefault_variance_budget_and_rejection(tmp_path: Path) -> None:
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
            "--max-variance-contribution",
            "0.70",
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
    assert saved["settings"]["max_variance_contribution"] == pytest.approx(0.70)
    assert saved["concentration"]["maximum_allowed_variance_contribution"] == pytest.approx(0.70)
    assert saved["concentration"]["maximum_variance_contributor"] == "BTC-USDT"
    assert saved["concentration"]["variance_contribution_passes"] is False
    assert saved["risk_status"].startswith("reject:")
    assert "variance contribution" in saved["risk_status"]
    assert "- Maximum allowed contribution: 70.00%" in markdown
    assert "- Largest observed contribution: BTC-USDT (" in markdown


@pytest.mark.parametrize("limit", [True, 0.0, 1.0, float("nan"), float("inf")])
def test_invalid_variance_budget_fails_before_metrics(
    limit: float,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    btc, eth, metadata = _load_fixture_returns()

    def unexpected_metrics(*args: object, **kwargs: object) -> None:
        pytest.fail("portfolio metrics ran before variance-budget validation")

    monkeypatch.setattr(portfolio, "performance_metrics", unexpected_metrics)
    with pytest.raises(ValueError, match=r"max_variance_contribution.*\(0, 1\)"):
        build_buy_and_hold_sleeve_portfolio(
            {"BTC-USDT": btc, "ETH-USDT": eth},
            initial_weights={"BTC-USDT": 0.5, "ETH-USDT": 0.5},
            max_variance_contribution=limit,
            provenance=_fixture_provenance(metadata),
        )
