from __future__ import annotations

import json
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_DOC_PATH = _REPOSITORY_ROOT / "docs" / "INTRADAY_1H_RESEARCH_GATE.md"
_CONFIG_PATH = _REPOSITORY_ROOT / "config" / "okx_research_1h.json"
_WORKFLOW_PATH = _REPOSITORY_ROOT / ".github" / "workflows" / "intraday-1h-research.yml"


def test_portable_operator_commands_match_implemented_profile() -> None:
    doc = _DOC_PATH.read_text(encoding="utf-8")
    config = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")

    assert config["data"]["bar"] == "1H"
    assert config["strategy"]["transaction_cost_bps"] == 5.0
    assert config["strategy"]["annualization"] == 8760
    assert config["robustness"]["cost_multipliers"] == [1.0]

    for token in (
        "--config config/okx_research_1h.json",
        "--inst-id BTC-USDT",
        "scripts/verify_walk_forward_report.py",
        "scripts/verify_intraday_1h_profile.py",
        "scripts/build_intraday_1h_promotion_gate.py",
        "cd /tmp/canonical-BTC-USDT-1h",
        "sha256sum --check artifact-manifest.sha256",
        "execution_diagnostics_separate=passed",
    ):
        assert token in doc

    assert "inst_id: [BTC-USDT, ETH-USDT]" in workflow
    assert "persist-credentials: false" in workflow
    assert "Verify exact persisted 5 bps-only profile" in workflow
    assert "Write explicit 1h promotion blockers" in workflow
    assert "gpt_quant.artifact_manifest" in workflow


def test_operator_boundary_is_fail_closed_non_trading_and_portable() -> None:
    doc = _DOC_PATH.read_text(encoding="utf-8")

    for required in (
        "exactly **5 bps one-way exchange fee**",
        "cost_multipliers == [1.0]",
        'verification[field] == "not_modeled"',
        "do not call an\norder endpoint",
        "does not define a\nmaker/post-only order",
        "`1Dutc` benchmark",
        "`15m` is not implemented",
        "artifact-root-relative paths",
        "not paper-trading acceptance",
    ):
        assert required in doc

    assert "reports/okx/1h/BTC-USDT/artifact-manifest.sha256" not in doc
    assert "operator no longer needs to recreate the original Actions workspace path" in doc
    assert "none was silently hidden inside the 5 bps research fee" in doc
