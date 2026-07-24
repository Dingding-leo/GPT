from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "okx_1h" / "BTC-USDT"


def _load_run_okx_research_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "run_okx_research_snapshot_cli", "scripts/run_okx_research.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load scripts/run_okx_research.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_research_replays_exact_byte_one_hour_snapshot_without_network(monkeypatch) -> None:
    research_script = _load_run_okx_research_module()

    def unexpected_fetch(**kwargs):
        pytest.fail(f"exact-byte research attempted a second network fetch: {kwargs}")

    monkeypatch.setattr(research_script, "fetch_okx_history_candles", unexpected_fetch)

    snapshot, source_mode = research_script._load_market_snapshot(
        inst_id="BTC-USDT",
        bar="1H",
        base_url="https://www.okx.com",
        start="2026-07-23T23:00:00Z",
        end="2026-07-24T01:00:00Z",
        limit=100,
        max_pages=3,
        pause_seconds=0.12,
        timeout=20.0,
        snapshot_dir=_FIXTURE_DIR,
    )

    assert source_mode == "persisted_exact_bytes"
    assert snapshot.metadata["source_transport"] == "trusted_okx_https_bounded_exact_bytes"
    assert snapshot.metadata["source_response_count"] == 1
    assert snapshot.metadata["source_response_sha256"] == [
        "4429d72add1f56554b5305cb237a76861e49ffa0203ee7fe0b7233c656567d3e"
    ]
    research_script._validate_okx_raw_page_schema(snapshot.raw_pages)


def test_research_rejects_snapshot_boundary_drift() -> None:
    research_script = _load_run_okx_research_module()

    with pytest.raises(ValueError, match="snapshot start does not match executed config"):
        research_script._load_market_snapshot(
            inst_id="BTC-USDT",
            bar="1H",
            base_url="https://www.okx.com",
            start="2026-07-24T00:00:00Z",
            end="2026-07-24T01:00:00Z",
            limit=100,
            max_pages=3,
            pause_seconds=0.12,
            timeout=20.0,
            snapshot_dir=_FIXTURE_DIR,
        )


def test_research_rejects_exact_byte_snapshot_for_non_hourly_path() -> None:
    research_script = _load_run_okx_research_module()

    with pytest.raises(ValueError, match="supported only for the canonical 1H path"):
        research_script._load_market_snapshot(
            inst_id="BTC-USDT",
            bar="1Dutc",
            base_url="https://www.okx.com",
            start="2026-07-23T23:00:00Z",
            end="2026-07-24T01:00:00Z",
            limit=100,
            max_pages=3,
            pause_seconds=0.12,
            timeout=20.0,
            snapshot_dir=_FIXTURE_DIR,
        )
