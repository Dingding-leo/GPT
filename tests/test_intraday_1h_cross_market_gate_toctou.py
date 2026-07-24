from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from gpt_quant.artifact_manifest import build_manifest
from gpt_quant.intraday_1h_source_provenance import (
    verify_intraday_1h_source_provenance,
    write_intraday_1h_source_provenance,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT_PATH = _REPOSITORY_ROOT / "scripts" / "build_intraday_1h_cross_market_gate.py"
_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "okx_1h"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "build_intraday_1h_cross_market_gate_toctou",
        _SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"


def _source_binding(path: Path, provenance: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_provenance_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "source_response_inventory_sha256": provenance["source_response_inventory_sha256"],
        "source_response_count": provenance["source_response_count"],
        "source_response_total_bytes": provenance["source_response_total_bytes"],
        "normalized_csv_sha256": provenance["normalized_csv_sha256"],
        "raw_pages_sha256": provenance["raw_pages_sha256"],
        "metadata_sha256": provenance["metadata_sha256"],
        "effective_start": provenance["effective_start"],
        "effective_end": provenance["effective_end"],
        "observations": provenance["observations"],
    }


def _write_real_artifact(artifacts_root: Path) -> Path:
    instrument_id = "BTC-USDT"
    fixture = _FIXTURE_ROOT / instrument_id
    source = json.loads((fixture / "SOURCE.json").read_text(encoding="utf-8"))
    assert source["provider"] == "OKX"
    assert source["instrument_id"] == instrument_id
    assert source["bar"] == "1H"
    for evidence in source["fixture_files"].values():
        path = _REPOSITORY_ROOT / evidence["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == evidence["sha256"]

    artifact = artifacts_root / f"canonical-{instrument_id}-1h-42-attempt-1"
    artifact.mkdir(parents=True)
    shutil.copytree(fixture, artifact / "snapshot")
    provenance_path, _ = write_intraday_1h_source_provenance(
        artifact,
        inst_id=instrument_id,
    )
    provenance = verify_intraday_1h_source_provenance(
        artifact,
        inst_id=instrument_id,
    )
    gate = {
        "schema_version": 1,
        "instrument_id": instrument_id,
        "bar": "1H",
        "modeled_economics": {
            "one_way_exchange_fee_bps": 5.0,
            "cost_multipliers": [1.0],
            "spread": "separate_not_modeled",
            "slippage": "separate_not_modeled",
            "market_impact": "separate_not_modeled",
            "latency": "separate_not_modeled",
        },
        "source_artifacts": _source_binding(provenance_path, provenance),
        "research_gate": {
            "research_candidate_eligible": False,
            "blockers": ["fold_stability_rejected"],
        },
        "promotion": {
            "allow_15m_evaluation": False,
            "allow_paper_promotion": False,
            "allow_limited_capital": False,
            "paper_blockers": [
                "maker_order_replay_missing",
                "state_recovery_reconciliation_missing",
            ],
        },
    }
    (artifact / "intraday-promotion-gate.json").write_text(
        _canonical_json(gate),
        encoding="utf-8",
    )
    build_manifest(artifact)
    return artifact


@pytest.mark.parametrize("substitution", ["symlink", "atomic_rename"])
def test_market_artifact_rejects_post_manifest_path_substitution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    substitution: str,
) -> None:
    module = _load_module()
    artifact = _write_real_artifact(tmp_path / "artifacts")
    gate_path = artifact / "intraday-promotion-gate.json"
    replacement_path = tmp_path / f"forged-{substitution}.json"
    forged = json.loads(gate_path.read_text(encoding="utf-8"))
    forged["research_gate"] = {
        "research_candidate_eligible": True,
        "blockers": [],
    }
    forged["promotion"]["allow_15m_evaluation"] = True
    replacement_path.write_text(_canonical_json(forged), encoding="utf-8")

    original_verify_manifest = module.verify_manifest
    substituted = False

    def verify_then_substitute(root: str | Path, *args: Any, **kwargs: Any) -> None:
        nonlocal substituted
        original_verify_manifest(root, *args, **kwargs)
        if substituted or Path(root).resolve() != artifact.resolve():
            return
        substituted = True
        if substitution == "symlink":
            gate_path.unlink()
            gate_path.symlink_to(replacement_path)
        else:
            os.replace(replacement_path, gate_path)

    monkeypatch.setattr(module, "verify_manifest", verify_then_substitute)

    with pytest.raises(
        ValueError,
        match="artifact path changed|digest mismatch|changed during secure open",
    ):
        module._validate_market_artifact(artifact, "BTC-USDT")

    assert substituted is True
