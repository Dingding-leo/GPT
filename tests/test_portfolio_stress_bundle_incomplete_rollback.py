from __future__ import annotations

import json
from pathlib import Path

import pytest

import gpt_quant.portfolio_stress as portfolio_stress_module
from gpt_quant.portfolio import build_buy_and_hold_sleeve_portfolio, load_verified_return_csv
from gpt_quant.portfolio_stress import write_portfolio_risk_bundle

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "okx" / "btc_eth_oos_20200111_20200219"
_REPORT_FILENAMES = {
    "portfolio_risk.json",
    "portfolio_risk.md",
    "portfolio_returns.csv",
    "portfolio_stress_correlation.json",
}


def _build_result(*, btc_weight: float, eth_weight: float):
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
        initial_weights={"BTC-USDT": btc_weight, "ETH-USDT": eth_weight},
        provenance=provenance,
    )


def test_incomplete_bundle_rollback_is_reported_and_caller_files_survive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "portfolio-report"
    original_paths = write_portfolio_risk_bundle(
        _build_result(btc_weight=0.5, eth_weight=0.5),
        output_dir,
    )
    original_payloads = {name: path.read_bytes() for name, path in original_paths.items()}
    sentinel = output_dir / "operator-notes.txt"
    sentinel_payload = b"preserve caller-owned evidence\n"
    sentinel.write_bytes(sentinel_payload)

    replacement_result = _build_result(btc_weight=0.6, eth_weight=0.4)
    real_replace = portfolio_stress_module.os.replace
    final_replacements = 0

    def fail_commit_and_one_restore(source: str | Path, destination: str | Path) -> None:
        nonlocal final_replacements
        source_path = Path(source)
        destination_path = Path(destination)
        is_report_destination = (
            destination_path.parent == output_dir
            and destination_path.name in _REPORT_FILENAMES
        )
        is_restore = source_path.name.startswith("restore-")
        if (
            is_report_destination
            and is_restore
            and destination_path.name == "portfolio_returns.csv"
        ):
            raise OSError("simulated portfolio bundle rollback failure")
        if is_report_destination and not is_restore:
            final_replacements += 1
            if final_replacements == 4:
                raise OSError("simulated portfolio bundle commit failure")
        real_replace(source, destination)

    monkeypatch.setattr(portfolio_stress_module.os, "replace", fail_commit_and_one_restore)

    with pytest.raises(
        RuntimeError,
        match=(
            "portfolio bundle commit failed and rollback was incomplete: "
            "returns: simulated portfolio bundle rollback failure"
        ),
    ) as exc_info:
        write_portfolio_risk_bundle(replacement_result, output_dir)

    assert isinstance(exc_info.value.__cause__, OSError)
    assert "simulated portfolio bundle commit failure" in str(exc_info.value.__cause__)
    assert {path.name for path in output_dir.iterdir()} == {
        *_REPORT_FILENAMES,
        sentinel.name,
    }
    assert sentinel.read_bytes() == sentinel_payload
    assert original_paths["json"].read_bytes() == original_payloads["json"]
    assert original_paths["markdown"].read_bytes() == original_payloads["markdown"]
    assert original_paths["stress_correlation"].read_bytes() == original_payloads[
        "stress_correlation"
    ]
    assert original_paths["returns"].read_bytes() != original_payloads["returns"]
