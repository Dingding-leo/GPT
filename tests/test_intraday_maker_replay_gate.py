from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _REPOSITORY_ROOT / "scripts" / "build_intraday_maker_replay_gate.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_intraday_maker_replay_gate", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _economics() -> dict[str, object]:
    return {
        "one_way_exchange_fee_bps": 5.0,
        "cost_multipliers": [1.0],
        "spread": "separate_not_modeled",
        "slippage": "separate_not_modeled",
        "market_impact": "separate_not_modeled",
        "latency": "separate_not_modeled",
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_manifest(root: Path) -> None:
    lines = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "artifact-manifest.sha256":
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            lines.append(f"{digest}  {path.relative_to(root).as_posix()}\n")
    (root / "artifact-manifest.sha256").write_text("".join(lines), encoding="utf-8")


def _write_evidence(root: Path) -> Path:
    root.mkdir(parents=True)
    gate = {
        "schema_version": 1,
        "modeled_economics": _economics(),
        "evidence_integrity_passes": True,
        "maker_order_replay_passes": True,
        "replay_equivalent": True,
        "observed_outcomes": ["no_fill", "partial_fill"],
        "account_connectivity": "disabled",
        "order_submission": "not_performed",
        "blockers": [],
    }
    (root / "maker-order-replay-gate.json").write_text(
        json.dumps(gate, sort_keys=True),
        encoding="utf-8",
    )
    (root / "paper-events.jsonl").write_text(
        '{"outcome":"no_fill"}\n{"outcome":"partial_fill"}\n',
        encoding="utf-8",
    )
    _write_manifest(root)
    return root


def test_missing_replay_evidence_is_deterministic_and_fail_closed(tmp_path: Path) -> None:
    module = _load_module()
    output = tmp_path / "output"

    first = module.build_gate(output)
    first_bytes = (output / "intraday-maker-replay-gate.json").read_bytes()
    second = module.build_gate(output)

    assert first == second
    assert (output / "intraday-maker-replay-gate.json").read_bytes() == first_bytes
    assert first["modeled_economics"] == _economics()
    assert first["maker_replay"]["maker_order_replay_passes"] is False
    assert first["maker_replay"]["account_connectivity"] == "disabled"
    assert first["maker_replay"]["order_submission"] == "not_performed"
    assert first["promotion"]["allow_paper_promotion"] is False
    assert first["promotion"]["blockers"] == [
        "maker_order_replay_missing",
        "no_fill_partial_fill_replay_missing",
    ]
    assert module.main(["--output-dir", str(output), "--enforce-maker-replay"]) == 1


def test_verified_replay_requires_a_trusted_external_manifest_digest(tmp_path: Path) -> None:
    module = _load_module()
    evidence = _write_evidence(tmp_path / "evidence")

    with pytest.raises(ValueError, match="lowercase SHA-256"):
        module.build_gate(tmp_path / "output", evidence_root=evidence)


def test_verified_no_fill_and_partial_fill_replay_moves_only_the_maker_gate(tmp_path: Path) -> None:
    module = _load_module()
    evidence = _write_evidence(tmp_path / "evidence")
    manifest_sha256 = _sha256(evidence / "artifact-manifest.sha256")

    payload = module.build_gate(
        tmp_path / "output",
        evidence_root=evidence,
        expected_manifest_sha256=manifest_sha256,
    )

    assert payload["maker_replay"]["evidence_integrity_passes"] is True
    assert payload["maker_replay"]["maker_order_replay_passes"] is True
    assert payload["maker_replay"]["replay_equivalent"] is True
    assert payload["maker_replay"]["observed_outcomes"] == ["no_fill", "partial_fill"]
    assert payload["maker_replay"]["artifact_manifest_sha256"] == manifest_sha256
    assert payload["maker_replay"]["replay_gate_sha256"]
    assert payload["promotion"] == {
        "allow_paper_promotion": False,
        "allow_limited_capital": False,
        "blockers": ["state_recovery_reconciliation_missing"],
    }


def test_tampered_replay_evidence_is_rejected(tmp_path: Path) -> None:
    module = _load_module()
    evidence = _write_evidence(tmp_path / "evidence")
    manifest_sha256 = _sha256(evidence / "artifact-manifest.sha256")
    (evidence / "paper-events.jsonl").write_text("tampered\n", encoding="utf-8")

    with pytest.raises(ValueError, match="digest mismatch"):
        module.build_gate(
            tmp_path / "output",
            evidence_root=evidence,
            expected_manifest_sha256=manifest_sha256,
        )


def test_rewritten_evidence_and_manifest_cannot_clear_the_gate(tmp_path: Path) -> None:
    module = _load_module()
    evidence = _write_evidence(tmp_path / "evidence")
    trusted_manifest_sha256 = _sha256(evidence / "artifact-manifest.sha256")
    (evidence / "paper-events.jsonl").write_text(
        '{"outcome":"no_fill"}\n{"outcome":"partial_fill","forged":true}\n',
        encoding="utf-8",
    )
    _write_manifest(evidence)

    with pytest.raises(ValueError, match="trusted SHA-256"):
        module.build_gate(
            tmp_path / "output",
            evidence_root=evidence,
            expected_manifest_sha256=trusted_manifest_sha256,
        )
