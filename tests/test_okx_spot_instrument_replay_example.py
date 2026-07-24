from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "examples/okx_spot_instrument_replay.py"
_DOC = Path(__file__).resolve().parents[1] / "docs/OKX_SPOT_INSTRUMENT_GATE.md"
_INSTRUMENT_DIR = (
    Path(__file__).resolve().parent / "fixtures/okx/public_instruments_btc_usdt_20251125"
)
_BOOK_DIR = Path(__file__).resolve().parent / "fixtures/okx/order-book-btc-usdt-docs-20210826"


def _run(output_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_SCRIPT), "--output-dir", str(output_dir)],
        check=False,
        capture_output=True,
        text=True,
    )


def _load_example_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("okx_spot_instrument_replay_example", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_example_executes_current_paper_attempt_gate_deterministically(
    tmp_path: Path,
) -> None:
    first = _run(tmp_path)
    second = _run(tmp_path)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert first.stdout == second.stdout

    summary = json.loads(first.stdout)
    assert summary["account_connectivity"] == "disabled"
    assert summary["order_submission"] == "not_performed"
    assert summary["paper_order_eligible"] is False
    assert summary["canonical_research_economics"] == {
        "additional_execution_costs_in_pnl": "none",
        "exchange_fee_bps_one_way": 5.0,
    }

    instrument = summary["instrument"]
    assert instrument == {
        "archive_idempotent": True,
        "lot_size": "0.00000001",
        "minimum_order_size_base": "0.00001",
        "raw_response_sha256": ("290bd86ecbb1683351993197b0ec18001dfb604b9ba1cb864d9d6d327855f0eb"),
        "state": "live",
        "tick_size": "0.1",
    }
    assert summary["minimum_buy_quote_equivalent_at_observed_ask"] == "0.410068"
    assert (
        summary["minimum_quote_notional_constraint"] == "not_reported_by_public_instrument_endpoint"
    )

    assert summary["constraint_probe"] == {
        "base_quantity": "0.1",
        "limit_price": "41006.8",
        "maximum_instrument_snapshot_age_ms": 1_000,
        "status": "passed",
        "submitted_at_utc": "2026-07-24T00:00:00.450000Z",
    }

    attempt = summary["paper_attempt_probe"]
    assert attempt["status"] == "passed"
    assert attempt["outcome"] == "partial"
    assert attempt["requested_base_quantity"] == "0.1"
    assert attempt["filled_base_quantity"] == "0.04"
    assert attempt["fill_fraction"] == "0.4"
    assert attempt["average_fill_price"] == "41006.8"
    assert attempt["minimum_paper_quote_notional_policy"] == "10"
    assert attempt["requested_quote_notional_at_ask"] == "4100.68"
    assert attempt["visible_same_side_touch_quantity"] == "0.60038921"
    assert attempt["replay_equal"] is True
    assert attempt["reconstructs"] is True
    assert attempt["fill_price_convention"] == "market-vwap-at-touch-or-worse"
    assert len(attempt["target_intent_id"]) == 64
    assert len(attempt["binding_id"]) == 64
    assert len(attempt["attempt_id"]) == 64

    diagnostics = summary["execution_diagnostics"]
    assert Decimal(diagnostics["observed_spread_bps"]) > 0
    assert diagnostics["slippage"] == "not_modeled"
    assert diagnostics["market_impact"] == "not_modeled"
    assert diagnostics["latency"] == "recorded_as_timestamps_only_not_priced"

    assert summary["timeframe_status"] == {
        "current_main_research": "1Dutc_benchmark_only",
        "intraday_15m": "not_implemented",
        "intraday_1h": "not_implemented",
        "this_gate": "timeframe_neutral_offline_constraint_probe",
    }
    assert "one_hour_research_pipeline_not_implemented" in summary["paper_order_blockers"]
    assert "maker_post_only_order_lifecycle_not_implemented" in summary["paper_order_blockers"]

    quote = summary["quote"]
    assert quote["bid_price"] == "41006.3"
    assert quote["ask_price"] == "41006.8"
    assert (
        quote["source_response_sha256"]
        == "7d12a351f8f51320d1c8beee0063557e1c90388d66ac63412bf66ca544aeb3e3"
    )


def test_example_rejects_instrument_fixture_and_sidecar_rewritten_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tampered = tmp_path / "instrument"
    tampered.mkdir()
    raw = (_INSTRUMENT_DIR / "response.json").read_bytes()
    changed = raw.replace(b'"tickSz":"0.1"', b'"tickSz":"0.2"')
    assert changed != raw
    (tampered / "response.json").write_bytes(changed)
    metadata = json.loads((_INSTRUMENT_DIR / "metadata.json").read_text())
    metadata["fixture_sha256"] = hashlib.sha256(changed).hexdigest()
    (tampered / "metadata.json").write_text(json.dumps(metadata))

    module = _load_example_module()
    monkeypatch.setattr(module, "_INSTRUMENT_DIR", tampered)
    monkeypatch.setattr(sys, "argv", [str(_SCRIPT), "--output-dir", str(tmp_path / "out")])
    with pytest.raises(ValueError, match="pinned SHA-256 digest"):
        module.main()


def test_example_rejects_quote_fixture_and_sidecar_rewritten_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tampered = tmp_path / "book"
    tampered.mkdir()
    raw = (_BOOK_DIR / "response.json").read_bytes()
    changed = raw.replace(b'"41006.8"', b'"41006.9"')
    assert changed != raw
    (tampered / "response.json").write_bytes(changed)
    metadata = json.loads((_BOOK_DIR / "metadata.json").read_text())
    metadata["response_sha256"] = hashlib.sha256(changed).hexdigest()
    (tampered / "metadata.json").write_text(json.dumps(metadata))

    module = _load_example_module()
    monkeypatch.setattr(module, "_BOOK_DIR", tampered)
    monkeypatch.setattr(sys, "argv", [str(_SCRIPT), "--output-dir", str(tmp_path / "out")])
    with pytest.raises(ValueError, match="pinned SHA-256 digest"):
        module.main()


def test_example_rejects_off_tick_limit_price(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_example_module()
    original = module.validate_okx_spot_limit_order_constraints

    def off_tick(snapshot, **kwargs):
        kwargs["limit_price"] = "41006.85"
        return original(snapshot, **kwargs)

    monkeypatch.setattr(module, "validate_okx_spot_limit_order_constraints", off_tick)
    monkeypatch.setattr(sys, "argv", [str(_SCRIPT), "--output-dir", str(tmp_path / "out")])
    with pytest.raises(ValueError, match="exact multiple of the OKX tick size"):
        module.main()


def test_example_rejects_off_lot_partial_fill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_example_module()
    monkeypatch.setattr(module, "_FILLED_BASE_QUANTITY", "0.040000005")
    monkeypatch.setattr(sys, "argv", [str(_SCRIPT), "--output-dir", str(tmp_path / "out")])
    with pytest.raises(ValueError, match="filled_base_quantity is not an exact multiple"):
        module.main()


def test_example_rejects_requested_notional_below_declared_paper_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_example_module()
    monkeypatch.setattr(module, "_MINIMUM_PAPER_QUOTE_NOTIONAL", "5000")
    monkeypatch.setattr(sys, "argv", [str(_SCRIPT), "--output-dir", str(tmp_path / "out")])
    with pytest.raises(ValueError, match="below the declared paper minimum"):
        module.main()


def test_documentation_matches_current_executable_boundary() -> None:
    content = _DOC.read_text(encoding="utf-8")
    normalized = " ".join(content.split())

    assert "python examples/okx_spot_instrument_replay.py" in content
    assert "pytest tests/test_okx_spot_instrument_replay_example.py" in content
    assert "rejects_requested_notional_below_declared_paper_floor" in content
    assert "3 passed, 4 deselected" in content
    assert "partial paper-attempt construction and canonical replay" in content
    assert "validate_okx_paper_execution_attempt_constraints()" in content
    assert "10 USDT paper-policy floor" in content
    assert "5 bps one-way exchange fee" in content
    assert "Current `main` still produces canonical research only for `1Dutc`" in content
    assert "There is no implemented, verified `1h` research command" in content
    assert "maker/post-only order lifecycle" in content
    assert "order expiry, queue position, no-fill, timeout, cancel, or requote events" in content
    assert "does not connect to an account" in normalized
    assert "7.5" not in content
    assert "10 bps" not in content
    assert "15 bps" not in content
