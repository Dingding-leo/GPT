from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

import gpt_quant.portfolio_stress as portfolio_stress_module
from gpt_quant.portfolio import build_buy_and_hold_sleeve_portfolio, load_verified_return_csv
from gpt_quant.portfolio_stress import (
    build_portfolio_stress_correlation_diagnostic,
    write_portfolio_risk_bundle,
    write_portfolio_stress_correlation_report,
)

_SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "run_portfolio_risk.py"
_SCRIPT_SPEC = importlib.util.spec_from_file_location("run_portfolio_risk", _SCRIPT_PATH)
if _SCRIPT_SPEC is None or _SCRIPT_SPEC.loader is None:
    raise RuntimeError(f"unable to load portfolio risk CLI from {_SCRIPT_PATH}")
run_portfolio_risk = importlib.util.module_from_spec(_SCRIPT_SPEC)
_SCRIPT_SPEC.loader.exec_module(run_portfolio_risk)

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "okx" / "btc_eth_oos_20200111_20200219"
_REPORT_FILENAMES = {
    "portfolio_risk.json",
    "portfolio_risk.md",
    "portfolio_returns.csv",
    "portfolio_stress_correlation.json",
}


def _fixture_inputs() -> tuple[dict[str, object], object, object]:
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
    return metadata, btc, eth


def _provenance(metadata: dict[str, object]) -> dict[str, object]:
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
        "--output-dir",
        str(output_dir),
    ]


def test_stress_correlation_is_report_only_and_backed_by_real_returns(tmp_path: Path) -> None:
    metadata, btc, eth = _fixture_inputs()
    result = build_buy_and_hold_sleeve_portfolio(
        {"BTC-USDT": btc, "ETH-USDT": eth},
        initial_weights={"BTC-USDT": 0.5, "ETH-USDT": 0.5},
        provenance=_provenance(metadata),
    )
    original_status = result.risk_status
    original_gate = result.concentration["passes"]

    diagnostic = build_portfolio_stress_correlation_diagnostic(result)
    report_path = write_portfolio_stress_correlation_report(result, tmp_path)
    saved = json.loads(report_path.read_text(encoding="utf-8"))

    assert diagnostic.report_only is True
    assert diagnostic.gate_status == "not_evaluated"
    assert diagnostic.method["threshold"] is None
    assert diagnostic.data_summary["full_window_observations"] == 40
    assert diagnostic.data_summary["stress_window_observations"] == 8
    assert diagnostic.data_summary["stress_timestamps"] == [
        "2020-02-19T00:00:00+00:00",
        "2020-02-15T00:00:00+00:00",
        "2020-02-10T00:00:00+00:00",
        "2020-01-23T00:00:00+00:00",
        "2020-02-17T00:00:00+00:00",
        "2020-02-13T00:00:00+00:00",
        "2020-01-22T00:00:00+00:00",
        "2020-01-19T00:00:00+00:00",
    ]
    pair = diagnostic.pairwise_results[0]
    assert pair["pair"] == ["BTC-USDT", "ETH-USDT"]
    assert pair["full_window_correlation"] == pytest.approx(0.7624497485015764)
    assert pair["stress_window_correlation"] == pytest.approx(0.797368393644667)
    assert pair["stress_minus_full_correlation"] == pytest.approx(0.03491864514309062)
    assert diagnostic.maximum_change_pair == ["BTC-USDT", "ETH-USDT"]
    assert saved["source_provenance"]["source_artifact_id"] == 8499721759
    assert result.risk_status == original_status
    assert result.concentration["passes"] is original_gate


def test_standalone_stress_writer_revalidates_verified_sources(tmp_path: Path) -> None:
    metadata = json.loads((_FIXTURE_DIR / "metadata.json").read_text(encoding="utf-8"))
    instruments = metadata["instruments"]
    btc_path = tmp_path / "btc_usdt_returns.csv"
    eth_path = tmp_path / "eth_usdt_returns.csv"
    btc_path.write_bytes((_FIXTURE_DIR / "btc_usdt_returns.csv").read_bytes())
    eth_path.write_bytes((_FIXTURE_DIR / "eth_usdt_returns.csv").read_bytes())
    btc = load_verified_return_csv(
        btc_path,
        expected_sha256=instruments["BTC-USDT"]["fixture_sha256"],
    )
    eth = load_verified_return_csv(
        eth_path,
        expected_sha256=instruments["ETH-USDT"]["fixture_sha256"],
    )
    result = build_buy_and_hold_sleeve_portfolio(
        {"BTC-USDT": btc, "ETH-USDT": eth},
        initial_weights={"BTC-USDT": 0.5, "ETH-USDT": 0.5},
        provenance=_provenance(metadata),
    )

    btc_path.write_bytes(btc_path.read_bytes() + b"\n")
    output_dir = tmp_path / "stress-report"

    with pytest.raises(ValueError):
        write_portfolio_stress_correlation_report(result, output_dir)

    assert not output_dir.exists()


def test_cli_publishes_stress_diagnostic_without_changing_risk_gate(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_status = run_portfolio_risk.main(_cli_args(tmp_path))
    stdout = capsys.readouterr().out
    stress_path = tmp_path / "portfolio_stress_correlation.json"
    payload = json.loads(stress_path.read_text(encoding="utf-8"))

    assert exit_status == 0
    assert "risk_gate_passes=true" in stdout
    assert f"stress_correlation_path={stress_path}" in stdout
    assert payload["report_only"] is True
    assert payload["gate_status"] == "not_evaluated"
    assert payload["source_risk_status"].startswith("pass:")


@pytest.mark.parametrize("failure_mode", ["stress-staging", "bundle-commit"])
def test_bundle_failure_preserves_prior_generation_and_caller_owned_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_mode: str,
) -> None:
    metadata, btc, eth = _fixture_inputs()
    original_result = build_buy_and_hold_sleeve_portfolio(
        {"BTC-USDT": btc, "ETH-USDT": eth},
        initial_weights={"BTC-USDT": 0.5, "ETH-USDT": 0.5},
        provenance=_provenance(metadata),
    )
    output_dir = tmp_path / "portfolio-report"
    original_paths = write_portfolio_risk_bundle(original_result, output_dir)
    original_payloads = {name: path.read_bytes() for name, path in original_paths.items()}
    sentinel = output_dir / "operator-notes.txt"
    sentinel_payload = b"preserve caller-owned evidence\n"
    sentinel.write_bytes(sentinel_payload)

    replacement_result = build_buy_and_hold_sleeve_portfolio(
        {"BTC-USDT": btc, "ETH-USDT": eth},
        initial_weights={"BTC-USDT": 0.6, "ETH-USDT": 0.4},
        provenance=_provenance(metadata),
    )
    assert replacement_result.settings != original_result.settings

    if failure_mode == "stress-staging":
        real_named_temporary_file = portfolio_stress_module.NamedTemporaryFile

        def fail_stress_staging(*args: object, **kwargs: object):
            directory = Path(str(kwargs["dir"]))
            if directory.parent == output_dir and directory.name.startswith(
                ".portfolio-risk-bundle-"
            ):
                raise OSError("simulated stress diagnostic staging failure")
            return real_named_temporary_file(*args, **kwargs)

        monkeypatch.setattr(
            portfolio_stress_module,
            "NamedTemporaryFile",
            fail_stress_staging,
        )
        expected_error = "simulated stress diagnostic staging failure"
    else:
        real_replace = portfolio_stress_module.os.replace
        final_replacements = 0

        def fail_stress_commit(source: str | Path, destination: str | Path) -> None:
            nonlocal final_replacements
            destination_path = Path(destination)
            if destination_path.parent == output_dir and destination_path.name in _REPORT_FILENAMES:
                final_replacements += 1
                if final_replacements == 4:
                    raise OSError("simulated stress diagnostic bundle commit failure")
            real_replace(source, destination)

        monkeypatch.setattr(portfolio_stress_module.os, "replace", fail_stress_commit)
        expected_error = "simulated stress diagnostic bundle commit failure"

    with pytest.raises(OSError, match=expected_error):
        write_portfolio_risk_bundle(replacement_result, output_dir)

    assert {path.name for path in output_dir.iterdir()} == {
        *_REPORT_FILENAMES,
        sentinel.name,
    }
    assert not any(path.name.startswith(".portfolio-risk-bundle-") for path in output_dir.iterdir())
    assert sentinel.read_bytes() == sentinel_payload
    for name, path in original_paths.items():
        assert path.read_bytes() == original_payloads[name]
