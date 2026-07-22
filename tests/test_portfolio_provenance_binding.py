from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

import gpt_quant.portfolio as portfolio
from gpt_quant.portfolio import build_buy_and_hold_sleeve_portfolio, load_verified_return_csv

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
    pytest.fail("portfolio metrics ran before return-source provenance validation")


def test_programmatic_builder_rejects_swapped_return_hashes_before_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    btc, eth, metadata = _load_fixture_returns()
    provenance = _fixture_provenance(metadata)
    hashes = provenance["return_file_sha256"]
    provenance["return_file_sha256"] = {
        "BTC-USDT": hashes["ETH-USDT"],
        "ETH-USDT": hashes["BTC-USDT"],
    }
    monkeypatch.setattr(portfolio, "performance_metrics", _fail_if_metrics_run)

    with pytest.raises(ValueError, match="BTC-USDT provenance hash does not match"):
        build_buy_and_hold_sleeve_portfolio(
            {"BTC-USDT": btc, "ETH-USDT": eth},
            initial_weights={"BTC-USDT": 0.5, "ETH-USDT": 0.5},
            provenance=provenance,
        )


def test_programmatic_builder_rejects_modified_verified_rows_before_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    btc, eth, metadata = _load_fixture_returns()
    altered_btc = btc.copy()
    altered_btc.attrs = dict(btc.attrs)
    altered_btc.iloc[-1] = altered_btc.iloc[-1] + 0.001
    monkeypatch.setattr(portfolio, "performance_metrics", _fail_if_metrics_run)

    with pytest.raises(ValueError, match="BTC-USDT returns do not match verified return source"):
        build_buy_and_hold_sleeve_portfolio(
            {"BTC-USDT": altered_btc, "ETH-USDT": eth},
            initial_weights={"BTC-USDT": 0.5, "ETH-USDT": 0.5},
            provenance=_fixture_provenance(metadata),
        )
