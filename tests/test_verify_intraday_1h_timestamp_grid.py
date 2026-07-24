from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
from pathlib import Path
from types import ModuleType

import pandas as pd
import pytest

_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "okx" / "btc-usdt-1h-grid-20260723-20260724"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "verify_intraday_1h_timestamp_grid",
        "scripts/verify_intraday_1h_timestamp_grid.py",
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load intraday timestamp-grid verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_fixture_output(tmp_path: Path) -> Path:
    source = json.loads((_FIXTURE_ROOT / "SOURCE.json").read_text(encoding="utf-8"))
    fixture_bytes = (_FIXTURE_ROOT / "candles.csv").read_bytes()
    assert hashlib.sha256(fixture_bytes).hexdigest() == source["fixture_csv_sha256"]
    assert source["provider"] == "OKX"
    assert source["instrument_id"] == "BTC-USDT"
    assert source["bar"] == "1H"
    output = tmp_path / "BTC-USDT"
    snapshot = output / "snapshot"
    snapshot.mkdir(parents=True)
    shutil.copyfile(_FIXTURE_ROOT / "candles.csv", snapshot / "okx-BTC-USDT-1H.csv")
    shutil.copyfile(
        _FIXTURE_ROOT / "metadata.json",
        snapshot / "okx-BTC-USDT-1H.metadata.json",
    )
    (output / "effective_config.json").write_text(
        json.dumps(
            {
                "data": {"inst_id": "BTC-USDT", "bar": "1H"},
                "strategy": {"transaction_cost_bps": 5.0},
                "robustness": {"cost_multipliers": [1.0]},
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    return output


def test_real_okx_one_hour_fixture_uses_exact_continuous_utc_grid(tmp_path: Path) -> None:
    module = _load_module()
    evidence = module.verify_intraday_1h_timestamp_grid(_write_fixture_output(tmp_path))

    assert evidence["instrument_id"] == "BTC-USDT"
    assert evidence["bar"] == "1H"
    assert evidence["observations"] == 3
    assert evidence["timestamp_grid"] == "exact_utc_hour_continuous"


def test_shifted_but_continuous_one_hour_grid_is_rejected(tmp_path: Path) -> None:
    module = _load_module()
    output = _write_fixture_output(tmp_path)
    csv_path = output / "snapshot" / "okx-BTC-USDT-1H.csv"
    metadata_path = output / "snapshot" / "okx-BTC-USDT-1H.metadata.json"
    frame = pd.read_csv(csv_path)
    shifted = pd.to_datetime(frame["timestamp"], utc=True) + pd.Timedelta(minutes=1)
    frame["timestamp"] = shifted.dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    frame.to_csv(csv_path, index=False, lineterminator="\n")

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["start"] = shifted.iloc[0].isoformat()
    metadata["end"] = shifted.iloc[-1].isoformat()
    metadata["normalized_csv_sha256"] = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="exact UTC-hour"):
        module.verify_intraday_1h_timestamp_grid(output)


def test_canonical_workflow_runs_timestamp_gate_before_report_verification() -> None:
    workflow = Path(".github/workflows/intraday-1h-research.yml").read_text(encoding="utf-8")
    test_command = "tests/test_verify_intraday_1h_timestamp_grid.py"
    verifier_command = "python scripts/verify_intraday_1h_timestamp_grid.py"
    research_command = "python scripts/run_okx_research.py"
    report_command = "python scripts/verify_walk_forward_report.py"

    assert workflow.count(test_command) == 1
    assert workflow.count(verifier_command) == 1
    assert workflow.index(research_command) < workflow.index(verifier_command)
    assert workflow.index(verifier_command) < workflow.index(report_command)
