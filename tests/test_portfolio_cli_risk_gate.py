from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "run_portfolio_risk.py"
_SCRIPT_SPEC = importlib.util.spec_from_file_location("run_portfolio_risk", _SCRIPT_PATH)
if _SCRIPT_SPEC is None or _SCRIPT_SPEC.loader is None:
    raise RuntimeError(f"unable to load portfolio risk CLI from {_SCRIPT_PATH}")
run_portfolio_risk = importlib.util.module_from_spec(_SCRIPT_SPEC)
_SCRIPT_SPEC.loader.exec_module(run_portfolio_risk)

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "okx" / "btc_eth_oos_20200111_20200219"
_CONTROL_PATHS = {
    "weight_concentration_passes": ("concentration", "weight_concentration_passes"),
    "variance_contribution_passes": ("concentration", "variance_contribution_passes"),
    "correlation_control_passes": ("dependence", "correlation_control_passes"),
}
_FAILURE_FRAGMENTS = {
    "weight_concentration_passes": "sleeve-weight drift",
    "variance_contribution_passes": "variance contribution",
    "correlation_control_passes": "pairwise return correlation",
}
_REJECTION_CASES = [
    (("--max-sleeve-weight", "0.505"), "weight_concentration_passes"),
    (("--max-variance-contribution", "0.70"), "variance_contribution_passes"),
    (("--max-pairwise-correlation", "0.75"), "correlation_control_passes"),
]
_REPORT_FILENAMES = (
    "portfolio_risk.json",
    "portfolio_risk.md",
    "portfolio_returns.csv",
)


def _cli_args(output_dir: Path, *risk_args: str) -> list[str]:
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
        *risk_args,
        "--output-dir",
        str(output_dir),
    ]


def _assert_isolated_rejection(payload: dict[str, object], failed_control: str) -> None:
    assert payload["concentration"]["passes"] is False
    control_states = {
        name: payload[section][key] for name, (section, key) in _CONTROL_PATHS.items()
    }
    assert control_states == {name: name != failed_control for name in _CONTROL_PATHS}
    assert payload["risk_status"].startswith("reject:")
    for control, fragment in _FAILURE_FRAGMENTS.items():
        assert (fragment in payload["risk_status"]) is (control == failed_control)


def _markdown_without_generation_time(output_dir: Path) -> list[str]:
    return [
        line
        for line in (output_dir / "portfolio_risk.md").read_text(encoding="utf-8").splitlines()
        if not line.startswith("Generated at: ")
    ]


@pytest.mark.parametrize(("risk_args", "failed_control"), _REJECTION_CASES)
def test_cli_modes_preserve_identical_rejected_risk_evidence(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    risk_args: tuple[str, str],
    failed_control: str,
) -> None:
    fail_closed_dir = tmp_path / f"fail-closed-{failed_control}"
    report_only_dir = tmp_path / f"report-only-{failed_control}"

    fail_closed_exit = run_portfolio_risk.main(
        [*_cli_args(fail_closed_dir, *risk_args), "--fail-on-reject"]
    )
    fail_closed_stdout = capsys.readouterr().out
    report_only_exit = run_portfolio_risk.main(_cli_args(report_only_dir, *risk_args))
    report_only_stdout = capsys.readouterr().out

    assert fail_closed_exit == 1
    assert report_only_exit == 0
    assert "risk_gate_passes=false" in fail_closed_stdout
    assert "risk_gate_passes=false" in report_only_stdout

    fail_closed_payload = json.loads(
        (fail_closed_dir / "portfolio_risk.json").read_text(encoding="utf-8")
    )
    report_only_payload = json.loads(
        (report_only_dir / "portfolio_risk.json").read_text(encoding="utf-8")
    )
    _assert_isolated_rejection(fail_closed_payload, failed_control)
    _assert_isolated_rejection(report_only_payload, failed_control)

    fail_closed_payload.pop("generated_at_utc")
    report_only_payload.pop("generated_at_utc")
    assert fail_closed_payload == report_only_payload
    assert _markdown_without_generation_time(fail_closed_dir) == _markdown_without_generation_time(
        report_only_dir
    )
    assert (fail_closed_dir / "portfolio_returns.csv").read_bytes() == (
        report_only_dir / "portfolio_returns.csv"
    ).read_bytes()
    for filename in _REPORT_FILENAMES:
        assert (fail_closed_dir / filename).is_file()
        assert (report_only_dir / filename).is_file()
