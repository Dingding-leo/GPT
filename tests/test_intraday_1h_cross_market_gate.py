from __future__ import annotations

import hashlib
import importlib.util
import json
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
        "build_intraday_1h_cross_market_gate",
        _SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"


def _verified_fixture(instrument_id: str) -> tuple[Path, dict[str, Any]]:
    fixture = _FIXTURE_ROOT / instrument_id
    source = json.loads((fixture / "SOURCE.json").read_text(encoding="utf-8"))
    assert source["provider"] == "OKX"
    assert source["instrument_id"] == instrument_id
    assert source["bar"] == "1H"
    for evidence in source["fixture_files"].values():
        path = _REPOSITORY_ROOT / evidence["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == evidence["sha256"]
    return fixture, source


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


def _promotion_payload(
    instrument_id: str,
    *,
    eligible: bool,
    research_blockers: list[str],
    source_binding: dict[str, Any],
) -> dict[str, Any]:
    return {
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
        "source_artifacts": source_binding,
        "research_gate": {
            "research_candidate_eligible": eligible,
            "blockers": research_blockers,
        },
        "promotion": {
            "allow_15m_evaluation": eligible,
            "allow_paper_promotion": False,
            "allow_limited_capital": False,
            "paper_blockers": [
                "maker_order_replay_missing",
                "state_recovery_reconciliation_missing",
            ],
        },
    }


def _write_real_artifact(
    artifacts_root: Path,
    instrument_id: str,
    *,
    eligible: bool,
    research_blockers: list[str],
) -> Path:
    fixture, _source = _verified_fixture(instrument_id)
    artifact = artifacts_root / f"canonical-{instrument_id}-1h-42-attempt-1"
    artifact.mkdir(parents=True)
    shutil.copytree(fixture, artifact / "snapshot")
    provenance_path, _ = write_intraday_1h_source_provenance(
        artifact,
        inst_id=instrument_id,
    )
    provenance = verify_intraday_1h_source_provenance(artifact, inst_id=instrument_id)
    payload = _promotion_payload(
        instrument_id,
        eligible=eligible,
        research_blockers=research_blockers,
        source_binding=_source_binding(provenance_path, provenance),
    )
    (artifact / "intraday-promotion-gate.json").write_text(
        _canonical_json(payload),
        encoding="utf-8",
    )
    build_manifest(artifact)
    return artifact


def _write_forged_eligible_gate(artifact: Path, destination: Path) -> None:
    gate = json.loads((artifact / "intraday-promotion-gate.json").read_text(encoding="utf-8"))
    gate["research_gate"] = {
        "research_candidate_eligible": True,
        "blockers": [],
    }
    gate["promotion"]["allow_15m_evaluation"] = True
    destination.write_text(_canonical_json(gate), encoding="utf-8")


def test_cross_market_gate_blocks_15m_when_either_market_is_rejected(
    tmp_path: Path,
) -> None:
    module = _load_module()
    artifacts = tmp_path / "artifacts"
    output = tmp_path / "summary"
    _write_real_artifact(
        artifacts,
        "BTC-USDT",
        eligible=False,
        research_blockers=["fold_stability_rejected"],
    )
    _write_real_artifact(
        artifacts,
        "ETH-USDT",
        eligible=True,
        research_blockers=[],
    )

    first = module.build_intraday_1h_cross_market_gate(
        artifacts,
        output,
        upstream_result="success",
    )
    first_bytes = (output / "intraday-cross-market-gate.json").read_bytes()
    second = module.build_intraday_1h_cross_market_gate(
        artifacts,
        output,
        upstream_result="success",
    )

    assert first == second
    assert (output / "intraday-cross-market-gate.json").read_bytes() == first_bytes
    assert first["evidence_integrity_passes"] is True
    assert first["research_gate"] == {
        "cross_market_candidate_eligible": False,
        "blockers": ["BTC-USDT:fold_stability_rejected"],
    }
    assert first["promotion"]["allow_15m_evaluation"] is False
    assert first["promotion"]["allow_paper_promotion"] is False
    for instrument_id in ("BTC-USDT", "ETH-USDT"):
        market = first["markets"][instrument_id]
        assert market["source_response_count"] == 1
        assert market["observations"] > 0
        assert market["effective_start"] < market["effective_end"]
        assert len(market["source_provenance_sha256"]) == 64
        assert len(market["source_response_inventory_sha256"]) == 64
    assert (
        module.main(
            [
                "--artifacts-root",
                str(artifacts),
                "--output-dir",
                str(output),
                "--upstream-result",
                "success",
                "--enforce-research-promotion",
            ]
        )
        == 1
    )


def test_cross_market_gate_allows_only_15m_research_when_both_markets_pass(
    tmp_path: Path,
) -> None:
    module = _load_module()
    artifacts = tmp_path / "artifacts"
    output = tmp_path / "summary"
    for instrument_id in ("BTC-USDT", "ETH-USDT"):
        _write_real_artifact(
            artifacts,
            instrument_id,
            eligible=True,
            research_blockers=[],
        )

    payload = module.build_intraday_1h_cross_market_gate(
        artifacts,
        output,
        upstream_result="success",
    )

    assert payload["research_gate"]["cross_market_candidate_eligible"] is True
    assert payload["promotion"]["allow_15m_evaluation"] is True
    assert payload["promotion"]["allow_paper_promotion"] is False
    assert payload["promotion"]["allow_limited_capital"] is False
    assert payload["promotion"]["blockers"] == [
        "maker_order_replay_missing",
        "state_recovery_reconciliation_missing",
    ]


@pytest.mark.parametrize("instrument_id", ["BTC-USDT", "ETH-USDT"])
def test_market_artifact_reconstructs_exact_byte_source_provenance(
    tmp_path: Path,
    instrument_id: str,
) -> None:
    module = _load_module()
    artifact = _write_real_artifact(
        tmp_path / "artifacts",
        instrument_id,
        eligible=False,
        research_blockers=["fold_stability_rejected"],
    )

    market = module._validate_market_artifact(artifact, instrument_id)
    _fixture, source = _verified_fixture(instrument_id)

    assert market["source_response_count"] == 1
    assert market["observations"] == source["observations"]
    assert (
        market["source_provenance_sha256"]
        == hashlib.sha256(
            (artifact / "intraday-1h-source-provenance.json").read_bytes()
        ).hexdigest()
    )


def test_market_artifact_rejects_missing_source_provenance(tmp_path: Path) -> None:
    module = _load_module()
    artifact = _write_real_artifact(
        tmp_path / "artifacts",
        "BTC-USDT",
        eligible=False,
        research_blockers=["fold_stability_rejected"],
    )
    (artifact / "intraday-1h-source-provenance.json").unlink()
    build_manifest(artifact)

    with pytest.raises(FileNotFoundError):
        module._validate_market_artifact(artifact, "BTC-USDT")


def test_market_artifact_rejects_self_rehashed_forged_provenance(
    tmp_path: Path,
) -> None:
    module = _load_module()
    artifact = _write_real_artifact(
        tmp_path / "artifacts",
        "BTC-USDT",
        eligible=False,
        research_blockers=["fold_stability_rejected"],
    )
    provenance_path = artifact / "intraday-1h-source-provenance.json"
    forged = json.loads(provenance_path.read_text(encoding="utf-8"))
    forged["offline_replay_verified"] = False
    provenance_path.write_text(_canonical_json(forged), encoding="utf-8")
    gate_path = artifact / "intraday-promotion-gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    gate["source_artifacts"]["source_provenance_sha256"] = hashlib.sha256(
        provenance_path.read_bytes()
    ).hexdigest()
    gate_path.write_text(_canonical_json(gate), encoding="utf-8")
    build_manifest(artifact)

    with pytest.raises(ValueError, match="does not reconstruct exactly"):
        module._validate_market_artifact(artifact, "BTC-USDT")


def test_market_artifact_rejects_symlink_substitution_after_materialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    artifact = _write_real_artifact(
        tmp_path / "artifacts",
        "BTC-USDT",
        eligible=False,
        research_blockers=["fold_stability_rejected"],
    )
    forged_gate = tmp_path / "forged-promotion-gate.json"
    _write_forged_eligible_gate(artifact, forged_gate)
    real_materialize = module._materialize_verified_artifact

    def materialize_then_substitute(source: Path, destination: Path) -> str:
        digest = real_materialize(source, destination)
        gate_path = source / "intraday-promotion-gate.json"
        gate_path.unlink()
        gate_path.symlink_to(forged_gate)
        return digest

    monkeypatch.setattr(module, "_materialize_verified_artifact", materialize_then_substitute)

    with pytest.raises(ValueError, match="symlink|unsafe"):
        module._validate_market_artifact(artifact, "BTC-USDT")


def test_market_artifact_rejects_atomic_rename_after_materialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    artifact = _write_real_artifact(
        tmp_path / "artifacts",
        "BTC-USDT",
        eligible=False,
        research_blockers=["fold_stability_rejected"],
    )
    forged_gate = tmp_path / "forged-promotion-gate.json"
    _write_forged_eligible_gate(artifact, forged_gate)
    real_materialize = module._materialize_verified_artifact

    def materialize_then_replace(source: Path, destination: Path) -> str:
        digest = real_materialize(source, destination)
        forged_gate.replace(source / "intraday-promotion-gate.json")
        return digest

    monkeypatch.setattr(module, "_materialize_verified_artifact", materialize_then_replace)

    with pytest.raises(ValueError, match="digest mismatch"):
        module._validate_market_artifact(artifact, "BTC-USDT")


def test_cross_market_gate_rejects_tampered_manifested_evidence(
    tmp_path: Path,
) -> None:
    module = _load_module()
    artifacts = tmp_path / "artifacts"
    output = tmp_path / "summary"
    bitcoin = _write_real_artifact(
        artifacts,
        "BTC-USDT",
        eligible=False,
        research_blockers=["fold_stability_rejected"],
    )
    _write_real_artifact(
        artifacts,
        "ETH-USDT",
        eligible=False,
        research_blockers=["fold_stability_rejected"],
    )
    metadata_path = next((bitcoin / "snapshot").glob("*.metadata.json"))
    metadata_path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="digest mismatch"):
        module.build_intraday_1h_cross_market_gate(
            artifacts,
            output,
            upstream_result="success",
        )

    assert (
        module.main(
            [
                "--artifacts-root",
                str(artifacts),
                "--output-dir",
                str(output),
                "--upstream-result",
                "success",
            ]
        )
        == 2
    )
    failure = json.loads((output / "intraday-cross-market-gate.json").read_text())
    assert failure["evidence_integrity_passes"] is False
    assert failure["promotion"]["allow_15m_evaluation"] is False
    assert failure["research_gate"]["blockers"] == ["cross_market_evidence_validation_failed"]


def test_cross_market_gate_records_failed_upstream_research_without_artifacts(
    tmp_path: Path,
) -> None:
    module = _load_module()
    output = tmp_path / "summary"

    payload = module.build_intraday_1h_cross_market_gate(
        tmp_path / "missing",
        output,
        upstream_result="failure",
    )

    assert payload["upstream_research_result"] == "failure"
    assert payload["evidence_integrity_passes"] is False
    assert payload["research_gate"]["blockers"] == ["canonical_1h_research_failure"]
    assert payload["promotion"]["allow_15m_evaluation"] is False
    assert payload["promotion"]["allow_paper_promotion"] is False
