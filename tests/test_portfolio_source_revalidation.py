from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

import gpt_quant.portfolio as portfolio
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


def _build_result_from_copied_sources(
    tmp_path: Path,
) -> tuple[PortfolioRiskResult, dict[str, Path]]:
    metadata = json.loads((_FIXTURE_DIR / "metadata.json").read_text(encoding="utf-8"))
    instruments = metadata["instruments"]
    source_dir = tmp_path / "verified-sources"
    source_dir.mkdir()

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
    result = build_buy_and_hold_sleeve_portfolio(
        sleeve_returns,
        initial_weights={"BTC-USDT": 0.5, "ETH-USDT": 0.5},
        max_sleeve_weight=0.75,
        provenance=provenance,
    )
    return result, source_paths


def _fail_if_metrics_run(*args: object, **kwargs: object) -> None:
    pytest.fail("portfolio metrics ran after a bound source became invalid")


@pytest.mark.parametrize("instrument", sorted(_SOURCE_FILENAMES))
def test_report_rehashes_bound_source_before_recomputing_metrics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    instrument: str,
) -> None:
    result, source_paths = _build_result_from_copied_sources(tmp_path)
    altered_source = source_paths[instrument]
    altered_source.write_bytes(altered_source.read_bytes() + b"\n")
    output_dir = tmp_path / "report"

    monkeypatch.setattr(portfolio, "performance_metrics", _fail_if_metrics_run)

    with pytest.raises(ValueError, match="return file hash mismatch"):
        write_portfolio_risk_report(result, output_dir)

    assert not output_dir.exists()


@pytest.mark.parametrize("instrument", sorted(_SOURCE_FILENAMES))
def test_report_rejects_missing_bound_source_before_recomputing_metrics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    instrument: str,
) -> None:
    result, source_paths = _build_result_from_copied_sources(tmp_path)
    source_paths[instrument].unlink()
    output_dir = tmp_path / "report"

    monkeypatch.setattr(portfolio, "performance_metrics", _fail_if_metrics_run)

    with pytest.raises(FileNotFoundError):
        write_portfolio_risk_report(result, output_dir)

    assert not output_dir.exists()


@pytest.mark.parametrize(
    ("instrument", "replacement_instrument"),
    (("BTC-USDT", "ETH-USDT"), ("ETH-USDT", "BTC-USDT")),
)
def test_report_rejects_cross_instrument_source_substitution_before_recomputing_metrics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    instrument: str,
    replacement_instrument: str,
) -> None:
    result, source_paths = _build_result_from_copied_sources(tmp_path)
    replacement_bytes = source_paths[replacement_instrument].read_bytes()
    source_paths[instrument].write_bytes(replacement_bytes)
    output_dir = tmp_path / "report"

    monkeypatch.setattr(portfolio, "performance_metrics", _fail_if_metrics_run)

    with pytest.raises(ValueError, match="return file hash mismatch"):
        write_portfolio_risk_report(result, output_dir)

    assert not output_dir.exists()


def test_return_loader_parses_the_exact_bytes_whose_hash_was_verified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata = json.loads((_FIXTURE_DIR / "metadata.json").read_text(encoding="utf-8"))
    source = tmp_path / _SOURCE_FILENAMES["BTC-USDT"]
    shutil.copyfile(_FIXTURE_DIR / source.name, source)

    real_read_csv = pd.read_csv
    original_frame = real_read_csv(source)
    changed_row = int(original_frame.index[original_frame["strategy_return"].ne(0.0)][0])
    original_value = float(original_frame.loc[changed_row, "strategy_return"])
    altered_frame = original_frame.copy()
    altered_frame.loc[changed_row, "strategy_return"] = original_value + 0.25
    altered_bytes = altered_frame.to_csv(index=False).encode("utf-8")

    def replace_source_before_parse(csv_source: object, *args: object, **kwargs: object):
        source.write_bytes(altered_bytes)
        return real_read_csv(csv_source, *args, **kwargs)

    # Parse the accepted byte snapshot even if the path changes before pandas reads it.
    monkeypatch.setattr(portfolio.pd, "read_csv", replace_source_before_parse)

    loaded = load_verified_return_csv(
        source,
        expected_sha256=metadata["instruments"]["BTC-USDT"]["fixture_sha256"],
    )

    assert source.read_bytes() == altered_bytes
    assert loaded.iloc[changed_row] == pytest.approx(original_value)
