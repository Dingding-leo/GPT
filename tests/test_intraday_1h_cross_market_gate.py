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
_BTC_FIXTURE = Path(__file__).parent / "fixtures" / "okx_1h" / "BTC-USDT"


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


def _write_real_btc_artifact(
    artifacts_root: Path,
    *,
    eligible: bool,
    research_blockers: list[str],
) -> Path:
    artifact = artifacts_root / "canonical-BTC-USDT-1h-42-attempt-1"
    artifact.mkdir(parents=True)
    shutil.copytree(_BTC_FIXTURE, artifact / "snapshot")
    provenance_path, _ = write_intraday_1h_source_provenance(
        artifact,
        inst_id="BTC-USDT",
    )
    provenance = verify_intraday_1h_source_provenance(artifact, inst_id="BTC-USDT")
    payload = _promotion_payload(
        "BTC-USDT",
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


def _eth_stub_provenance() -> dict[str, Any]:
    digest = "1" * 64
    return {
        "schema_version": 1,
        "provider": "OKX",
        "instrument_id": "ETH-USDT",
        "bar": "1H",
        "source_transport": "trusted_okx_https_bounded_exact_bytes",
        "offline_replay_verified": True,
        "source_response_count": 1,
        "source_response_total_bytes": 100,
        "source_response_sha256": [digest],
        "source_response_inventory_sha256": "2" * 64,
        "normalized_csv_sha256": "3" * 64,
        "raw_pages_sha256": "4" * 64,
        "metadata_sha256": "5" * 64,
        "requested_start": "2021-07-24T00:00:00+00:00",
        "requested_end": "2026-07-24T04:00:00+00:00",
        "effective_start": "2021-07-24T00:00:00+00:00",
        "effective_end": "2026-07-24T04:00:00+00:00",
        "observations": 43_829,
        "expected_step_seconds": 3_600,
        "duplicates_removed": 0,
        "incomplete_rows_removed": 1,
        "missing_intervals": 0,
        "economic_boundary": {},
        "safety": {},
    }


def _write_eth_orchestration_artifact(
    artifacts_root: Path,
    *,
    eligible: bool,
    research_blockers: list[str],
) -> Path:
    artifact = artifacts_root / "canonical-ETH-USDT-1h-42-attempt-1"
    artifact.mkdir(parents=True)
    provenance = _eth_stub_provenance()
    provenance_path = artifact / "intraday-1h-source-provenance.json"
    provenance_path.write_text(_canonical_json(provenance), encoding="utf-8")
    payload = _promotion_payload(
        "ETH-USDT",
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


def _install_eth_orchestration_stub(monkeypatch: pytest.MonkeyPatch, module: ModuleType) -> None:
    real_verifier = module.verify_intraday_1h_source_provenance

    def verifier(output_dir: str | Path, *, inst_id: str) -> dict[str, Any]:
        if inst_id == "ETH-USDT":
            return _eth_stub_provenance()
        return real_verifier(output_dir, inst_id=inst_id)

    monkeypatch.setattr(module, "verify_intraday_1h_source_provenance", verifier)


def test_cross_market_gate_blocks_15m_when_either_market_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    _install_eth_orchestration_stub(monkeypatch, module)
    artifacts = tmp_path / "artifacts"
    output = tmp_path / "summary"
    _write_real_btc_artifact(
        artifacts,
        eligible=False,
        research_blockers=["fold_stability_rejected"],
    )
    _write_eth_orchestration_artifact(
        artifacts,
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
    assert first["markets"]["BTC-USDT"]["source_response_count"] == 1
    assert first["markets"]["BTC-USDT"]["observations"] == 2
    assert first["markets"]["ETH-USDT"]["artifact_manifest_sha256"]
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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    _install_eth_orchestration_stub(monkeypatch, module)
    artifacts = tmp_path / "artifacts"
    output = tmp_path / "summary"
    _write_real_btc_artifact(artifacts, eligible=True, research_blockers=[])
    _write_eth_orchestration_artifact(artifacts, eligible=True, research_blockers=[])

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


def test_market_artifact_reconstructs_exact_byte_source_provenance(tmp_path: Path) -> None:
    module = _load_module()
    artifact = _write_real_btc_artifact(
        tmp_path / "artifacts",
        eligible=False,
        research_blockers=["fold_stability_rejected"],
    )

    market = module._validate_market_artifact(artifact, "BTC-USDT")

    assert market["source_response_count"] == 1
    assert market["observations"] == 2
    assert market["source_provenance_sha256"] == hashlib.sha256(
        (artifact / "intraday-1h-source-provenance.json").read_bytes()
    ).hexdigest()


def test_market_artifact_rejects_missing_source_provenance(tmp_path: Path) -> None:
    module = _load_module()
    artifact = _write_real_btc_artifact(
        tmp_path / "artifacts",
        eligible=False,
        research_blockers=["fold_stability_rejected"],
    )
    (artifact / "artifact-manifest.sha256").unlink()
    (artifact / "intraday-1h-source-provenance.json").unlink()
    build_manifest(artifact)

    with pytest.raises(FileNotFoundError):
        module._validate_market_artifact(artifact, "BTC-USDT")


def test_market_artifact_rejects_self_rehashed_forged_provenance(tmp_path: Path) -> None:
    module = _load_module()
    artifact = _write_real_btc_artifact(
        tmp_path / "artifacts",
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
    (artifact / "artifact-manifest.sha256").unlink()
    build_manifest(artifact)

    with pytest.raises(ValueError, match="does not reconstruct exactly"):
        module._validate_market_artifact(artifact, "BTC-USDT")


def test_cross_market_gate_rejects_tampered_manifested_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    _install_eth_orchestration_stub(monkeypatch, module)
    artifacts = tmp_path / "artifacts"
    output = tmp_path / "summary"
    bitcoin = _write_real_btc_artifact(
        artifacts,
        eligible=False,
        research_blockers=["fold_stability_rejected"],
    )
    _write_eth_orchestration_artifact(
        artifacts,
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
