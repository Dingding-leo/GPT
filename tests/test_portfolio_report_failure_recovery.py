from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pandas as pd
import pytest

from gpt_quant.portfolio import (
    PortfolioRiskResult,
    build_buy_and_hold_sleeve_portfolio,
    load_verified_return_csv,
    write_portfolio_risk_report,
)

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "okx" / "btc_eth_oos_20200111_20200219"
_SOURCE_FILENAMES = {
    "BTC-USDT": "btc_usdt_returns.csv",
    "ETH-USDT": "eth_usdt_returns.csv",
}


def _fixture_metadata() -> dict[str, object]:
    return json.loads((_FIXTURE_DIR / "metadata.json").read_text(encoding="utf-8"))


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


def _build_result_from_copied_sources(
    tmp_path: Path,
    *,
    initial_weights: dict[str, float] | None = None,
) -> tuple[PortfolioRiskResult, dict[str, Path]]:
    metadata = _fixture_metadata()
    instruments = metadata["instruments"]
    source_dir = tmp_path / "verified-sources"
    source_dir.mkdir(exist_ok=True)

    source_paths: dict[str, Path] = {}
    sleeve_returns: dict[str, pd.Series] = {}
    for instrument, filename in _SOURCE_FILENAMES.items():
        source_path = source_dir / filename
        shutil.copyfile(_FIXTURE_DIR / filename, source_path)
        source_paths[instrument] = source_path
        sleeve_returns[instrument] = load_verified_return_csv(
            source_path,
            expected_sha256=instruments[instrument]["fixture_sha256"],
        )

    result = build_buy_and_hold_sleeve_portfolio(
        sleeve_returns,
        initial_weights=initial_weights or {"BTC-USDT": 0.5, "ETH-USDT": 0.5},
        provenance=_fixture_provenance(metadata),
    )
    return result, source_paths


@pytest.mark.parametrize("instrument", sorted(_SOURCE_FILENAMES))
def test_invalid_source_preserves_existing_portfolio_report_set(
    tmp_path: Path,
    instrument: str,
) -> None:
    result, source_paths = _build_result_from_copied_sources(tmp_path)
    output_dir = tmp_path / "portfolio-report"
    paths = write_portfolio_risk_report(result, output_dir)
    original_bytes = {name: path.read_bytes() for name, path in paths.items()}

    source = source_paths[instrument]
    source.write_bytes(source.read_bytes() + b"\n")

    with pytest.raises(ValueError, match="return file hash mismatch"):
        write_portfolio_risk_report(result, output_dir)

    assert {name: path.read_bytes() for name, path in paths.items()} == original_bytes
    assert sorted(path.name for path in output_dir.iterdir()) == sorted(
        path.name for path in paths.values()
    )


@pytest.mark.parametrize("existing_report", [False, True])
def test_mid_commit_failure_never_exposes_partial_portfolio_report_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    existing_report: bool,
) -> None:
    original_result, _ = _build_result_from_copied_sources(tmp_path)
    output_dir = tmp_path / "portfolio-report"
    original_bytes: dict[str, bytes] | None = None
    if existing_report:
        original_paths = write_portfolio_risk_report(original_result, output_dir)
        original_bytes = {name: path.read_bytes() for name, path in original_paths.items()}

    replacement_result, _ = _build_result_from_copied_sources(
        tmp_path,
        initial_weights={"BTC-USDT": 0.6, "ETH-USDT": 0.4},
    )
    assert replacement_result.settings != original_result.settings

    real_replace = os.replace
    committed_replacements = 0
    destination_names = {
        "portfolio_risk.json",
        "portfolio_risk.md",
        "portfolio_returns.csv",
    }

    def fail_second_commit(source: str | Path, destination: str | Path) -> None:
        nonlocal committed_replacements
        source_path = Path(source)
        destination_path = Path(destination)
        if (
            source_path.name in destination_names
            and destination_path.parent == output_dir
            and destination_path.name in destination_names
        ):
            committed_replacements += 1
            if committed_replacements == 2:
                raise OSError("simulated mid-commit portfolio report failure")
        real_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_second_commit)

    with pytest.raises(OSError, match="simulated mid-commit portfolio report failure"):
        write_portfolio_risk_report(replacement_result, output_dir)

    assert committed_replacements == 2
    if original_bytes is None:
        assert not output_dir.exists()
    else:
        assert {name: path.read_bytes() for name, path in original_paths.items()} == original_bytes
        assert sorted(path.name for path in output_dir.iterdir()) == sorted(
            path.name for path in original_paths.values()
        )
