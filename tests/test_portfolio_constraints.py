from __future__ import annotations

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


def _fail_if_metrics_run(*args: object, **kwargs: object) -> None:
    pytest.fail("portfolio metrics ran before constraint validation")


@pytest.mark.parametrize(
    "weights",
    [
        {"BTC-USDT": True, "ETH-USDT": False},
        {"BTC-USDT": 1.0, "ETH-USDT": 0.0},
        {"BTC-USDT": 0.0, "ETH-USDT": 1.0},
    ],
)
def test_portfolio_rejects_degenerate_initial_weights_before_metrics(
    weights: dict[str, float],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    btc, eth, metadata = _load_fixture_returns()
    monkeypatch.setattr(portfolio, "performance_metrics", _fail_if_metrics_run)

    with pytest.raises(ValueError, match="strictly positive real numbers"):
        build_buy_and_hold_sleeve_portfolio(
            {"BTC-USDT": btc, "ETH-USDT": eth},
            initial_weights=weights,
            provenance=_fixture_provenance(metadata),
        )


@pytest.mark.parametrize("cap", [True, 1.0])
def test_portfolio_rejects_vacuous_concentration_cap_before_metrics(
    cap: float,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    btc, eth, metadata = _load_fixture_returns()
    monkeypatch.setattr(portfolio, "performance_metrics", _fail_if_metrics_run)

    with pytest.raises(ValueError, match=r"finite real number in \(0, 1\)"):
        build_buy_and_hold_sleeve_portfolio(
            {"BTC-USDT": btc, "ETH-USDT": eth},
            initial_weights={"BTC-USDT": 0.5, "ETH-USDT": 0.5},
            max_sleeve_weight=cap,
            provenance=_fixture_provenance(metadata),
        )


def test_non_vacuous_concentration_cap_preserves_valid_portfolio() -> None:
    btc, eth, metadata = _load_fixture_returns()
    result = build_buy_and_hold_sleeve_portfolio(
        {"BTC-USDT": btc, "ETH-USDT": eth},
        initial_weights={"BTC-USDT": 0.5, "ETH-USDT": 0.5},
        max_sleeve_weight=0.75,
        provenance=_fixture_provenance(metadata),
    )

    assert result.settings["max_sleeve_weight"] == pytest.approx(0.75)
    assert result.concentration["maximum_allowed_sleeve_weight"] == pytest.approx(0.75)
    assert all(weight > 0.0 for weight in result.settings["initial_weights"].values())
