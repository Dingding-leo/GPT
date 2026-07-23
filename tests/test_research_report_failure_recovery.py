from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest

from gpt_quant import StrategyConfig, run_holdout_research, write_research_report

_REPORT_FILENAMES = {"latest.json", "latest.md"}


def _real_result(prices: pd.Series, *, transaction_cost_bps: float):
    return run_holdout_research(
        prices,
        base_config=StrategyConfig(
            transaction_cost_bps=transaction_cost_bps,
            annualization=365,
        ),
        momentum_lookbacks=[21],
        reversal_lookbacks=[3],
        trend_weights=[0.8],
        validation_fraction=0.2,
        holdout_fraction=0.2,
        top_candidates=1,
    )


@pytest.mark.parametrize("existing_report", [False, True])
@pytest.mark.parametrize("failure_point", ["staging", "commit"])
def test_publication_failure_preserves_complete_holdout_report_set(
    btc_usdt_prices: pd.Series,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    existing_report: bool,
    failure_point: str,
) -> None:
    output_dir = tmp_path / "holdout-report"
    original_bytes: dict[str, bytes] = {}
    if existing_report:
        original = _real_result(btc_usdt_prices, transaction_cost_bps=10.0)
        original_paths = write_research_report(original, output_dir)
        original_bytes = {path.name: path.read_bytes() for path in original_paths}

    replacement = _real_result(btc_usdt_prices, transaction_cost_bps=20.0)
    if existing_report:
        assert replacement.to_dict() != original.to_dict()

    failure_message = f"simulated holdout report {failure_point} failure"
    operations = 0

    if failure_point == "staging":
        real_write_bytes = Path.write_bytes

        def fail_second_stage(path: Path, data: bytes) -> int:
            nonlocal operations
            if (
                path.name in _REPORT_FILENAMES
                and path.parent.name.startswith(".research-report-")
                and path.parent.parent == output_dir
            ):
                operations += 1
                if operations == 2:
                    raise OSError(failure_message)
            return real_write_bytes(path, data)

        monkeypatch.setattr(Path, "write_bytes", fail_second_stage)
    else:
        real_replace = os.replace

        def fail_second_commit(source: str | Path, destination: str | Path) -> None:
            nonlocal operations
            source_path = Path(source)
            destination_path = Path(destination)
            if (
                source_path.name in _REPORT_FILENAMES
                and source_path.parent.name.startswith(".research-report-")
                and destination_path.parent == output_dir
                and destination_path.name in _REPORT_FILENAMES
            ):
                operations += 1
                if operations == 2:
                    raise OSError(failure_message)
            real_replace(source, destination)

        monkeypatch.setattr(os, "replace", fail_second_commit)

    with pytest.raises(OSError, match=failure_message):
        write_research_report(replacement, output_dir)

    assert operations == 2
    if existing_report:
        assert {path.name for path in output_dir.iterdir()} == _REPORT_FILENAMES
        assert {path.name: path.read_bytes() for path in output_dir.iterdir()} == original_bytes
    else:
        assert not output_dir.exists()
