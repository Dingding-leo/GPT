from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

from gpt_quant.artifact_manifest import build_manifest

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT_PATH = _REPOSITORY_ROOT / "scripts" / "build_intraday_1h_cross_market_gate.py"


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


def _write_market_artifact(
    artifacts_root: Path,
    instrument_id: str,
    *,
    eligible: bool,
    research_blockers: list[str],
) -> Path:
    artifact = artifacts_root / f"canonical-{instrument_id}-1h-42-attempt-1"
    artifact.mkdir(parents=True)
    payload = {
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
    (artifact / "intraday-promotion-gate.json").write_text(
        json.dumps(payload, sort_keys=True),
        encoding="utf-8",
    )
    (artifact / "source-evidence.txt").write_text(instrument_id, encoding="utf-8")
    build_manifest(artifact)
    return artifact


def test_cross_market_gate_blocks_15m_when_either_market_is_rejected(tmp_path: Path) -> None:
    module = _load_module()
    artifacts = tmp_path / "artifacts"
    output = tmp_path / "summary"
    _write_market_artifact(
        artifacts,
        "BTC-USDT",
        eligible=False,
        research_blockers=["fold_stability_rejected"],
    )
    _write_market_artifact(
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
    assert first["markets"]["BTC-USDT"]["artifact_manifest_sha256"]
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
) -> None:
    module = _load_module()
    artifacts = tmp_path / "artifacts"
    output = tmp_path / "summary"
    for instrument_id in ("BTC-USDT", "ETH-USDT"):
        _write_market_artifact(
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


def test_cross_market_gate_rejects_tampered_manifested_evidence(tmp_path: Path) -> None:
    module = _load_module()
    artifacts = tmp_path / "artifacts"
    output = tmp_path / "summary"
    bitcoin = _write_market_artifact(
        artifacts,
        "BTC-USDT",
        eligible=False,
        research_blockers=["fold_stability_rejected"],
    )
    _write_market_artifact(
        artifacts,
        "ETH-USDT",
        eligible=False,
        research_blockers=["fold_stability_rejected"],
    )
    (bitcoin / "source-evidence.txt").write_text("tampered", encoding="utf-8")

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
