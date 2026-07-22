from __future__ import annotations

import json
from pathlib import Path

import pytest

from gpt_quant.portfolio import (
    build_buy_and_hold_sleeve_portfolio,
    load_verified_return_csv,
    write_portfolio_risk_report,
)

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "okx" / "btc_eth_oos_20200111_20200219"


def _build_result():
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
            name: details["fixture_sha256"] for name, details in instruments.items()
        },
    }
    return build_buy_and_hold_sleeve_portfolio(
        {"BTC-USDT": btc, "ETH-USDT": eth},
        initial_weights={"BTC-USDT": 0.5, "ETH-USDT": 0.5},
        max_sleeve_weight=0.75,
        provenance=provenance,
    )


def test_report_rejects_metric_tampering_before_creating_files(tmp_path: Path) -> None:
    result = _build_result()
    result.portfolio_metrics["sharpe"] = 999.0
    output_dir = tmp_path / "report"

    with pytest.raises(ValueError, match="does not match its verified source inputs"):
        write_portfolio_risk_report(result, output_dir)

    assert not output_dir.exists()


@pytest.mark.parametrize("column", ["strategy_return", "nav"])
def test_report_rejects_frame_tampering_before_creating_files(
    tmp_path: Path,
    column: str,
) -> None:
    result = _build_result()
    result.frame.loc[result.frame.index[-1], column] += 0.01
    output_dir = tmp_path / "report"

    with pytest.raises(ValueError, match="frame does not match its verified source inputs"):
        write_portfolio_risk_report(result, output_dir)

    assert not output_dir.exists()


def test_to_dict_does_not_expose_mutable_result_state() -> None:
    result = _build_result()
    payload = result.to_dict()
    payload["portfolio_metrics"]["sharpe"] = 999.0
    assert result.portfolio_metrics["sharpe"] != 999.0
