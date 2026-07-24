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
_INSTRUMENT_FIXTURE_DIR = (
    Path(__file__).resolve().parent / "fixtures/okx/public_instruments_btc_usdt_20251125"
)
_QUOTE_FIXTURE_DIR = (
    Path(__file__).resolve().parent / "fixtures/okx/order-book-btc-usdt-docs-20210826"
)


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


def test_example_replays_instrument_and_quote_evidence(tmp_path: Path) -> None:
    first = _run(tmp_path)
    second = _run(tmp_path)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert first.stdout == second.stdout

    summary = json.loads(first.stdout)
    assert summary["account_connectivity"] == "disabled"
    assert summary["order_submission"] == "not_performed"
    assert summary["paper_order_eligible"] is False
    assert summary["instrument_replay_equal"] is True
    assert summary["state"] == "live"
    assert summary["tick_size"] == "0.1"
    assert summary["lot_size"] == "0.00000001"
    assert summary["minimum_order_size_base"] == "0.00001"
    assert (
        summary["instrument_raw_response_sha256"]
        == "290bd86ecbb1683351993197b0ec18001dfb604b9ba1cb864d9d6d327855f0eb"
    )
    assert summary["minimum_buy_quote_equivalent_at_observed_ask"] == "0.410068"
    assert summary["minimum_sell_quote_equivalent_at_observed_bid"] == "0.410063"
    assert (
        summary["minimum_quote_notional_constraint"] == "not_reported_by_public_instrument_endpoint"
    )
    assert summary["exchange_fee_baseline_bps_one_way"] == 5.0
    assert summary["separate_cost_inputs"]["stress_bps_all_in"] == [7.5, 10.0, 15.0]
    assert Decimal(summary["separate_cost_inputs"]["observed_spread_bps"]) > 0
    assert summary["timing_replay_scope"] == "complete_instrument_and_quote_server_time_envelopes"
    assert len(summary["instrument_archive_files"]) == 2

    quote = summary["quote"]
    assert quote["replay_equal"] is True
    assert quote["bid_price"] == "41006.3"
    assert quote["ask_price"] == "41006.8"
    assert (
        quote["source_response_sha256"]
        == "7d12a351f8f51320d1c8beee0063557e1c90388d66ac63412bf66ca544aeb3e3"
    )
    assert (
        quote["server_time_response_sha256"]
        == "2ab44b9abd247acb72cf79b22b30e14c4e80cc00a96384a4535b31a37f6dfeb0"
    )
    assert quote["fixture_scope"].endswith("not_contemporaneous")

    raw_name = next(
        name for name in summary["instrument_archive_files"] if name.endswith(".raw.json")
    )
    raw_path = tmp_path / raw_name
    assert (
        hashlib.sha256(raw_path.read_bytes()).hexdigest()
        == summary["instrument_raw_response_sha256"]
    )


def test_example_rejects_instrument_fixture_and_sidecar_rewritten_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tampered_fixture = tmp_path / "instrument-fixture"
    tampered_fixture.mkdir()
    raw_response = (_INSTRUMENT_FIXTURE_DIR / "response.json").read_bytes()
    tampered_response = raw_response.replace(b'"tickSz":"0.1"', b'"tickSz":"0.2"')
    assert tampered_response != raw_response
    (tampered_fixture / "response.json").write_bytes(tampered_response)

    metadata = json.loads((_INSTRUMENT_FIXTURE_DIR / "metadata.json").read_text())
    metadata["fixture_sha256"] = hashlib.sha256(tampered_response).hexdigest()
    (tampered_fixture / "metadata.json").write_text(json.dumps(metadata))

    module = _load_example_module()
    monkeypatch.setattr(module, "_INSTRUMENT_FIXTURE_DIR", tampered_fixture)
    monkeypatch.setattr(
        sys,
        "argv",
        [str(_SCRIPT), "--output-dir", str(tmp_path / "archive")],
    )

    with pytest.raises(ValueError, match="pinned SHA-256 digest"):
        module.main()


def test_example_rejects_quote_fixture_and_sidecar_rewritten_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tampered_fixture = tmp_path / "quote-fixture"
    tampered_fixture.mkdir()
    raw_response = (_QUOTE_FIXTURE_DIR / "response.json").read_bytes()
    tampered_response = raw_response.replace(b'"41006.8"', b'"41006.9"')
    assert tampered_response != raw_response
    (tampered_fixture / "response.json").write_bytes(tampered_response)

    metadata = json.loads((_QUOTE_FIXTURE_DIR / "metadata.json").read_text())
    metadata["response_sha256"] = hashlib.sha256(tampered_response).hexdigest()
    (tampered_fixture / "metadata.json").write_text(json.dumps(metadata))

    module = _load_example_module()
    monkeypatch.setattr(module, "_QUOTE_FIXTURE_DIR", tampered_fixture)
    monkeypatch.setattr(
        sys,
        "argv",
        [str(_SCRIPT), "--output-dir", str(tmp_path / "archive")],
    )

    with pytest.raises(ValueError, match="quote fixture.*pinned SHA-256 digest"):
        module.main()


def test_documentation_matches_the_executable_current_main_boundary() -> None:
    content = _DOC.read_text(encoding="utf-8")
    normalized = " ".join(content.split())

    assert "python examples/okx_spot_instrument_replay.py" in content
    assert "pinned in the executable" in content
    assert "minimum base-asset quantity" in content
    assert "quote-equivalent arithmetic" in content
    assert "not a minimum quote-notional constraint" in content
    assert "complete instrument and quote server-time envelopes" in content
    assert "5 bps one-way exchange fee" in content
    assert "spread, slippage, market impact, and latency" in content
    assert "does not submit an order" in normalized
