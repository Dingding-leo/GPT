from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

_SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "run_portfolio_risk.py"
_SCRIPT_SPEC = importlib.util.spec_from_file_location("run_portfolio_risk", _SCRIPT_PATH)
if _SCRIPT_SPEC is None or _SCRIPT_SPEC.loader is None:
    raise RuntimeError(f"unable to load portfolio risk CLI from {_SCRIPT_PATH}")
run_portfolio_risk = importlib.util.module_from_spec(_SCRIPT_SPEC)
_SCRIPT_SPEC.loader.exec_module(run_portfolio_risk)

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "okx" / "btc_eth_oos_20200111_20200219"


def test_cli_rejects_identical_sleeve_source_bytes_before_loading_returns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata = json.loads((_FIXTURE_DIR / "metadata.json").read_text(encoding="utf-8"))
    eth = metadata["instruments"]["ETH-USDT"]
    source = _FIXTURE_DIR / "eth_usdt_returns.csv"

    def unexpected_load(*args: object, **kwargs: object) -> pd.Series:
        pytest.fail("duplicate sleeve evidence must be rejected before loading returns")

    monkeypatch.setattr(run_portfolio_risk, "load_verified_return_csv", unexpected_load)
    output_dir = tmp_path / "portfolio"

    with pytest.raises(ValueError, match="distinct SHA-256 digests"):
        run_portfolio_risk.main(
            [
                "--btc-returns",
                str(source),
                "--eth-returns",
                str(source),
                "--btc-sha256",
                eth["fixture_sha256"],
                "--eth-sha256",
                eth["fixture_sha256"],
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

    assert not output_dir.exists()
