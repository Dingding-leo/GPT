from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "run_portfolio_risk.py"
_SCRIPT_SPEC = importlib.util.spec_from_file_location("run_portfolio_risk", _SCRIPT_PATH)
if _SCRIPT_SPEC is None or _SCRIPT_SPEC.loader is None:
    raise RuntimeError(f"unable to load portfolio risk CLI from {_SCRIPT_PATH}")
run_portfolio_risk = importlib.util.module_from_spec(_SCRIPT_SPEC)
_SCRIPT_SPEC.loader.exec_module(run_portfolio_risk)

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "okx" / "btc_eth_oos_20200111_20200219"


def _cli_args(output_dir: Path) -> list[str]:
    metadata = json.loads((_FIXTURE_DIR / "metadata.json").read_text(encoding="utf-8"))
    instruments = metadata["instruments"]
    return [
        "--btc-returns",
        str(_FIXTURE_DIR / "btc_usdt_returns.csv"),
        "--eth-returns",
        str(_FIXTURE_DIR / "eth_usdt_returns.csv"),
        "--btc-sha256",
        instruments["BTC-USDT"]["fixture_sha256"],
        "--eth-sha256",
        instruments["ETH-USDT"]["fixture_sha256"],
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
        "--max-sleeve-weight",
        "0.505",
        "--output-dir",
        str(output_dir),
    ]


def test_cli_can_fail_closed_after_persisting_rejected_real_data_report(tmp_path: Path) -> None:
    output_dir = tmp_path / "fail-closed"

    exit_code = run_portfolio_risk.main([*_cli_args(output_dir), "--fail-on-reject"])

    assert exit_code == 1
    payload = json.loads((output_dir / "portfolio_risk.json").read_text(encoding="utf-8"))
    assert payload["concentration"]["passes"] is False
    assert payload["concentration"]["weight_concentration_passes"] is False
    assert payload["risk_status"].startswith("reject:")
    assert "sleeve-weight drift" in payload["risk_status"]
    assert (output_dir / "portfolio_risk.md").is_file()
    assert (output_dir / "portfolio_returns.csv").is_file()


def test_cli_keeps_report_only_mode_for_rejected_real_data_report(tmp_path: Path) -> None:
    output_dir = tmp_path / "report-only"

    exit_code = run_portfolio_risk.main(_cli_args(output_dir))

    assert exit_code == 0
    payload = json.loads((output_dir / "portfolio_risk.json").read_text(encoding="utf-8"))
    assert payload["concentration"]["passes"] is False
