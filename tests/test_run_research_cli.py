from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pandas as pd
import pytest

from gpt_quant.reproducibility import file_sha256


def _load_run_research_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_research_cli", "scripts/run_research.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load scripts/run_research.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_run_research_requires_verified_snapshot_manifest() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/run_research.py"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 2
    assert "--snapshot-manifest" in completed.stderr
    assert "required" in completed.stderr


def test_run_research_rejects_legacy_unverified_csv() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/run_research.py", "--csv", "data/prices.csv"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 2
    assert "--csv is no longer accepted" in completed.stderr
    assert "--snapshot-manifest" in completed.stderr


def test_invalid_snapshot_stops_before_research_or_reporting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = tmp_path / "snapshot.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "provider": "OKX",
                "market_type": "spot",
                "instrument_id": "BTC-USDT",
                "timeframe": "1Dutc",
                "schema": {
                    "columns": ["timestamp", "close"],
                    "timestamp_column": "timestamp",
                    "close_column": "close",
                },
                "observations": 60,
                "start": "2018-01-11T00:00:00+00:00",
                "end": "2018-03-11T00:00:00+00:00",
                "data_path": "missing.csv",
                "data_sha256": "0" * 64,
                "provenance": {"source_workflow_run_id": 29841895366},
            }
        ),
        encoding="utf-8",
    )
    module = _load_run_research_module()

    def unexpected_call(*args: object, **kwargs: object) -> None:
        raise AssertionError("research and reporting must not run for an invalid snapshot")

    monkeypatch.setattr(module, "run_holdout_research", unexpected_call)
    monkeypatch.setattr(module, "write_research_report", unexpected_call)

    with pytest.raises(FileNotFoundError, match="missing.csv"):
        module.main(["--snapshot-manifest", str(manifest_path)])


def test_undeclared_csv_fields_stop_before_research_or_reporting(
    tmp_path: Path,
    btc_usdt_prices: pd.Series,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = btc_usdt_prices.iloc[:2]
    data_path = tmp_path / "prices.csv"
    rows = [
        "timestamp,close",
        *(f"{timestamp.isoformat()},{close},undeclared" for timestamp, close in selected.items()),
    ]
    data_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    manifest_path = tmp_path / "snapshot.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "provider": "OKX",
                "market_type": "spot",
                "instrument_id": "BTC-USDT",
                "timeframe": "1Dutc",
                "schema": {
                    "columns": ["timestamp", "close"],
                    "timestamp_column": "timestamp",
                    "close_column": "close",
                },
                "observations": len(selected),
                "start": selected.index[0].isoformat(),
                "end": selected.index[-1].isoformat(),
                "data_path": data_path.name,
                "data_sha256": file_sha256(data_path),
                "provenance": {"source_workflow_run_id": 29841895366},
            }
        ),
        encoding="utf-8",
    )
    module = _load_run_research_module()

    def unexpected_call(*args: object, **kwargs: object) -> None:
        raise AssertionError("research and reporting must not run for an invalid snapshot")

    monkeypatch.setattr(module, "run_holdout_research", unexpected_call)
    monkeypatch.setattr(module, "write_research_report", unexpected_call)

    with pytest.raises(ValueError, match="field count does not match manifest schema"):
        module.main(["--snapshot-manifest", str(manifest_path)])
