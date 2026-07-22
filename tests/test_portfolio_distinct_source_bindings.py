from __future__ import annotations

import json
from pathlib import Path

import pytest

import gpt_quant.portfolio as portfolio

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "okx" / "btc_eth_oos_20200111_20200219"


def test_builder_rejects_duplicate_verified_source_column_before_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata = json.loads((_FIXTURE_DIR / "metadata.json").read_text(encoding="utf-8"))
    eth_details = metadata["instruments"]["ETH-USDT"]
    source = _FIXTURE_DIR / "eth_usdt_returns.csv"
    eth = portfolio.load_verified_return_csv(
        source,
        expected_sha256=eth_details["fixture_sha256"],
    )

    def unexpected_metrics(*args: object, **kwargs: object) -> None:
        pytest.fail("duplicate verified source columns must be rejected before metrics")

    monkeypatch.setattr(portfolio, "performance_metrics", unexpected_metrics)
    provenance = {
        "provider": metadata["provider"],
        "market_type": metadata["market_type"],
        "timeframe": metadata["timeframe"],
        "source_workflow_run_id": metadata["source_workflow_run_id"],
        "source_artifact_id": metadata["source_artifact_id"],
        "source_artifact_name": metadata["source_artifact_name"],
        "source_artifact_sha256": metadata["source_artifact_sha256"],
        "source_head_sha": metadata["source_head_sha"],
        "return_file_sha256": {
            "BTC-USDT": eth_details["fixture_sha256"],
            "ETH-USDT": eth_details["fixture_sha256"],
        },
    }

    with pytest.raises(ValueError, match="distinct verified return source columns"):
        portfolio.build_buy_and_hold_sleeve_portfolio(
            {"BTC-USDT": eth.copy(), "ETH-USDT": eth.copy()},
            initial_weights={"BTC-USDT": 0.5, "ETH-USDT": 0.5},
            provenance=provenance,
        )
