from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

from gpt_quant import (
    build_experiment_manifest_entry,
    canonical_json_sha256,
    file_sha256,
)

_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "okx" / "btc-usdt-1dutc"
_CANDLES = _FIXTURE_ROOT / "candles.csv"
_RAW = _FIXTURE_ROOT / "raw.json"
_METADATA = _FIXTURE_ROOT / "metadata.json"


def _load_run_okx_research_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "run_okx_research_cli", "scripts/run_okx_research.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load scripts/run_okx_research.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_effective_config_records_exact_executed_cost_profile() -> None:
    module = _load_run_okx_research_module()
    requested_cost_multipliers = [1.0]
    result_settings = {
        "candidate_count": 1,
        "cost_multipliers": requested_cost_multipliers,
    }

    effective_config = module._build_effective_config(
        data={"inst_id": "BTC-USDT", "bar": "1H"},
        strategy={"transaction_cost_bps": 5.0},
        search={"selection_bars": 17_520, "test_bars": 2_160},
        result_settings=result_settings,
    )

    assert requested_cost_multipliers == [1.0]
    assert effective_config["robustness"]["cost_multipliers"] == [1.0]


def test_effective_config_snapshot_is_canonical_and_manifest_bound(tmp_path: Path) -> None:
    module = _load_run_okx_research_module()
    effective_config = {
        "strategy": {"transaction_cost_bps": 5.0, "annualization": 365},
        "data": {
            "inst_id": "BTC-USDT",
            "bar": "1Dutc",
            "base_url": "https://www.okx.com",
        },
        "robustness": {"cost_multipliers": [1.0, 1.5, 2.0, 3.0]},
        "search": {"selection_bars": 730, "test_bars": 90},
    }

    config_path = module._write_effective_config_snapshot(tmp_path, effective_config)
    expected_bytes = (
        json.dumps(
            effective_config,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    metadata = json.loads(_METADATA.read_text(encoding="utf-8"))
    manifest_entry = build_experiment_manifest_entry(
        effective_config=effective_config,
        data_hashes={
            "normalized_csv": metadata["fixture_normalized_csv_sha256"],
            "raw_pages": metadata["fixture_raw_json_sha256"],
        },
        data_paths={"normalized_csv": _CANDLES, "raw_pages": _RAW},
        artifact_paths={"effective_config": config_path},
        candidate_count=27,
        result_classification="fixture-only provenance test; no performance claim",
        instrument_id="BTC-USDT",
        bar="1Dutc",
        code_commit="c" * 40,
        recorded_at_utc="2026-07-23T13:00:00+00:00",
    )

    assert config_path.name == "effective_config.json"
    assert config_path.read_bytes() == expected_bytes
    assert json.loads(config_path.read_text(encoding="utf-8")) == effective_config
    assert manifest_entry["config_sha256"] == canonical_json_sha256(effective_config)
    assert manifest_entry["artifact_sha256"]["effective_config"] == file_sha256(config_path)
