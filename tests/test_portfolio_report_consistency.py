from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from gpt_quant.portfolio import (
    build_buy_and_hold_sleeve_portfolio,
    load_verified_return_csv,
    write_portfolio_risk_report,
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


def _markdown_metric_rows(markdown: str) -> dict[str, str]:
    block = markdown.split("## Portfolio metrics\n\n", maxsplit=1)[1].split(
        "\n\n## Sleeve concentration", maxsplit=1
    )[0]
    rows: dict[str, str] = {}
    for line in block.splitlines()[2:]:
        if not line.startswith("|"):
            continue
        _, name, value, _ = (part.strip() for part in line.split("|"))
        assert name not in rows
        rows[name] = value
    return rows


def test_portfolio_report_artifacts_reconcile_to_one_equity_curve(tmp_path: Path) -> None:
    btc, eth, metadata = _load_fixture_returns()
    result = build_buy_and_hold_sleeve_portfolio(
        {"BTC-USDT": btc, "ETH-USDT": eth},
        initial_weights={"BTC-USDT": 0.5, "ETH-USDT": 0.5},
        provenance=_fixture_provenance(metadata),
    )

    paths = write_portfolio_risk_report(result, tmp_path / "portfolio")
    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    persisted = pd.read_csv(paths["returns"])
    timestamps = pd.DatetimeIndex(pd.to_datetime(persisted.pop("timestamp"), utc=True))

    assert timestamps.equals(result.frame.index)
    persisted.index = result.frame.index
    assert list(persisted.columns) == list(result.frame.columns)
    pd.testing.assert_frame_equal(
        persisted,
        result.frame,
        check_exact=False,
        check_freq=False,
        rtol=0.0,
        atol=1e-15,
    )

    contribution_columns = [
        "BTC-USDT_return_contribution",
        "ETH-USDT_return_contribution",
    ]
    contribution_sum = persisted[contribution_columns].sum(axis=1)
    np.testing.assert_allclose(
        contribution_sum.to_numpy(),
        persisted["strategy_return"].to_numpy(),
        rtol=0.0,
        atol=1e-12,
    )

    recomputed_nav = np.cumprod(1.0 + persisted["strategy_return"].to_numpy())
    np.testing.assert_allclose(
        persisted["nav"].to_numpy(),
        recomputed_nav,
        rtol=0.0,
        atol=1e-12,
    )

    summary = payload["data_summary"]
    assert summary["observations"] == len(persisted)
    assert summary["start"] == timestamps[0].isoformat()
    assert summary["end"] == timestamps[-1].isoformat()
    assert summary["sleeves"] == ["BTC-USDT", "ETH-USDT"]
    assert payload["portfolio_metrics"]["total_return"] == pytest.approx(
        recomputed_nav[-1] - 1.0,
        abs=1e-12,
    )

    markdown = paths["markdown"].read_text(encoding="utf-8")
    expected_metrics = {
        name: f"{value:.6f}" if isinstance(value, float) else str(value)
        for name, value in payload["portfolio_metrics"].items()
    }
    assert _markdown_metric_rows(markdown) == expected_metrics
    assert f"Generated at: `{payload['generated_at_utc']}`" in markdown
    assert f"Risk status: **{payload['risk_status']}**" in markdown
