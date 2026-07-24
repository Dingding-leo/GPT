from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_FIXTURE_ROOT = (
    Path(__file__).parent / "fixtures" / "okx" / "trades-btc-usdt-docs-20220602"
)
_SCRIPT = Path(__file__).parents[1] / "scripts" / "build_maker_replay_gate.py"


def _run(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise AssertionError(result.stderr)
    return result


def _build(output_dir: Path) -> dict[str, object]:
    result = _run(
        "--source-response",
        str(_FIXTURE_ROOT / "response.json"),
        "--source-metadata",
        str(_FIXTURE_ROOT / "metadata.json"),
        "--output-dir",
        str(output_dir),
    )
    summary = json.loads(result.stdout)
    assert summary["maker_order_replay_passes"] is True
    assert summary["replay_equivalent"] is True
    return json.loads((output_dir / "maker-order-replay-gate.json").read_text())


def _verify(output_dir: Path, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return _run("--output-dir", str(output_dir), "--verify-only", check=check)


def _directory_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_maker_replay_gate_is_deterministic_and_offline(tmp_path: Path) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"

    first = _build(first_root)
    second = _build(second_root)

    assert first == second
    assert _directory_bytes(first_root) == _directory_bytes(second_root)
    verification = json.loads(_verify(first_root).stdout)
    assert verification["maker_order_replay_passes"] is True
    assert verification["observed_outcomes"] == ["cancelled_no_fill", "cancelled_partial"]
    assert first["canonical_timeframe"] == "1H"
    assert first["benchmark_timeframe"] == "1Dutc"
    assert first["optional_next_timeframe"] == "15m"
    assert first["observed_outcomes"] == ["cancelled_no_fill", "cancelled_partial"]
    assert first["maker_order_replay_passes"] is True
    assert first["replay_equivalent"] is True
    assert first["account_connectivity"] == "disabled"
    assert first["order_submission"] == "not_performed"
    assert first["blockers"] == []

    assert first["modeled_economics"] == {
        "exchange_fee_one_way_bps": "5",
        "fee_only_modeled_pnl": True,
        "impact": "separate_not_modeled",
        "latency": "separate_not_modeled",
        "slippage": "separate_not_modeled",
        "spread": "separate_not_modeled",
    }

    no_fill = json.loads((first_root / "cancelled-no-fill.json").read_bytes())
    partial_fill = json.loads((first_root / "cancelled-partial.json").read_bytes())
    assert no_fill["filled_base_quantity"] == "0"
    assert no_fill["exchange_fee_quote"] == "0"
    assert partial_fill["filled_base_quantity"] == "0.00001"
    assert partial_fill["unfilled_base_quantity"] == "0.00001"
    assert partial_fill["exchange_fee_one_way_bps"] == "5"
    assert partial_fill["requote_eligible"] is True


def test_maker_replay_gate_rejects_tampered_replay_bytes(tmp_path: Path) -> None:
    output_dir = tmp_path / "evidence"
    _build(output_dir)
    replay_path = output_dir / "cancelled-partial.json"
    replay_path.write_bytes(replay_path.read_bytes().replace(b'"0.00001"', b'"0.00002"', 1))

    result = _verify(output_dir, check=False)
    assert result.returncode != 0
    assert "artifact digest mismatch" in result.stderr


def test_maker_replay_gate_rejects_manifest_inventory_drift(tmp_path: Path) -> None:
    output_dir = tmp_path / "evidence"
    _build(output_dir)
    manifest_path = output_dir / "artifact-manifest.sha256"
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8") + f"{'0' * 64}  unexpected.json\n",
        encoding="utf-8",
    )

    result = _verify(output_dir, check=False)
    assert result.returncode != 0
    assert "inventory is incomplete or unexpected" in result.stderr
