from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _REPOSITORY_ROOT / "scripts" / "build_maker_replay_gate.py"
_DOCUMENTATION = _REPOSITORY_ROOT / "docs" / "MAKER_REPLAY_OPERATIONAL_GATE.md"
_RESPONSE = (
    _REPOSITORY_ROOT
    / "tests"
    / "fixtures"
    / "okx"
    / "trades-btc-usdt-docs-20220602"
    / "response.json"
)
_METADATA = _RESPONSE.with_name("metadata.json")
_REQUIRED_FILES = {
    "artifact-manifest.sha256",
    "cancelled-no-fill.json",
    "cancelled-partial.json",
    "maker-order-replay-gate.json",
    "source/metadata.json",
    "source/response.json",
}


def _run(*arguments: str) -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, str(_SCRIPT), *arguments],
        cwd=_REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.stderr == ""
    return json.loads(completed.stdout)


def test_documented_build_and_verify_commands_execute(tmp_path: Path) -> None:
    output_dir = tmp_path / "maker-replay"
    build = _run(
        "--source-response",
        str(_RESPONSE),
        "--source-metadata",
        str(_METADATA),
        "--output-dir",
        str(output_dir),
    )
    verify = _run("--output-dir", str(output_dir), "--verify-only")

    assert build == verify
    assert build["maker_order_replay_passes"] is True
    assert build["replay_equivalent"] is True
    assert build["observed_outcomes"] == ["cancelled_no_fill", "cancelled_partial"]
    manifest_sha256 = build["manifest_sha256"]
    assert isinstance(manifest_sha256, str)
    assert len(manifest_sha256) == 64
    assert all(character in "0123456789abcdef" for character in manifest_sha256)

    inventory = {
        path.relative_to(output_dir).as_posix() for path in output_dir.rglob("*") if path.is_file()
    }
    assert inventory == _REQUIRED_FILES

    gate = json.loads((output_dir / "maker-order-replay-gate.json").read_text())
    assert gate["canonical_timeframe"] == "1H"
    assert gate["benchmark_timeframe"] == "1Dutc"
    assert gate["account_connectivity"] == "disabled"
    assert gate["order_submission"] == "not_performed"
    assert gate["modeled_economics"] == {
        "exchange_fee_one_way_bps": "5",
        "fee_only_modeled_pnl": True,
        "impact": "separate_not_modeled",
        "latency": "separate_not_modeled",
        "slippage": "separate_not_modeled",
        "spread": "separate_not_modeled",
    }


def test_documentation_matches_executable_boundaries() -> None:
    documentation = _DOCUMENTATION.read_text(encoding="utf-8")

    assert "python scripts/build_maker_replay_gate.py" in documentation
    assert "--verify-only" in documentation
    assert "sha256sum --check artifact-manifest.sha256" in documentation
    assert "diff -ru reports/paper/maker-replay /tmp/maker-replay-rebuilt" in documentation
    assert "exactly **5 bps one-way**" in documentation
    assert "Spread, slippage, market impact, and latency" in documentation
    assert "`15m` remains blocked" in documentation
    assert "account_connectivity = disabled" in documentation
    assert "order_submission = not_performed" in documentation
