from __future__ import annotations

import json
from pathlib import Path

from gpt_quant import StrategyConfig

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_DAILY_BARS_PER_YEAR = 365
_HOURLY_BARS_PER_DAY = 24


def _load_config(name: str) -> dict[str, object]:
    path = _REPOSITORY_ROOT / "config" / name
    return json.loads(path.read_text(encoding="utf-8"))


def test_canonical_1h_profile_preserves_daily_horizons_at_five_bps() -> None:
    daily = _load_config("okx_research.json")
    hourly = _load_config("okx_research_1h.json")

    daily_data = daily["data"]
    hourly_data = hourly["data"]
    daily_strategy = daily["strategy"]
    hourly_strategy = hourly["strategy"]
    daily_search = daily["search"]
    hourly_search = hourly["search"]

    assert isinstance(daily_data, dict)
    assert isinstance(hourly_data, dict)
    assert isinstance(daily_strategy, dict)
    assert isinstance(hourly_strategy, dict)
    assert isinstance(daily_search, dict)
    assert isinstance(hourly_search, dict)

    assert hourly_data["bar"] == "1H"
    assert hourly_data["start"] == "2021-07-24T00:00:00Z"
    page_capacity = int(hourly_data["limit"]) * int(hourly_data["max_pages"])
    minimum_five_year_bars = 5 * _DAILY_BARS_PER_YEAR * _HOURLY_BARS_PER_DAY
    assert page_capacity >= minimum_five_year_bars

    validated = StrategyConfig(**hourly_strategy)
    assert validated.transaction_cost_bps == 5.0
    assert validated.annualization == _DAILY_BARS_PER_YEAR * _HOURLY_BARS_PER_DAY

    for key in ("momentum_lookback", "reversal_lookback", "volatility_lookback"):
        expected = int(daily_strategy[key]) * _HOURLY_BARS_PER_DAY
        assert int(hourly_strategy[key]) == expected

    for key in ("momentum_lookbacks", "reversal_lookbacks"):
        expected = [int(value) * _HOURLY_BARS_PER_DAY for value in daily_search[key]]
        assert hourly_search[key] == expected

    expected_selection_bars = int(daily_search["selection_bars"]) * _HOURLY_BARS_PER_DAY
    expected_test_bars = int(daily_search["test_bars"]) * _HOURLY_BARS_PER_DAY
    assert int(hourly_search["selection_bars"]) == expected_selection_bars
    assert int(hourly_search["test_bars"]) == expected_test_bars
    assert hourly["robustness"] == {"cost_multipliers": [1.0]}


def test_workflow_reselects_and_verifies_btc_and_eth_independently() -> None:
    path = _REPOSITORY_ROOT / ".github/workflows/intraday-1h-research.yml"
    workflow = path.read_text(encoding="utf-8")

    research = workflow.index("- name: Run canonical 1h full walk-forward research")
    bind = workflow.index("- name: Bind exchange-time source envelope")
    provenance = workflow.index("- name: Verify replay-bound exact-byte 1h source provenance")
    timestamp_gate = workflow.index("- name: Verify exact persisted UTC-hour timestamp grid")
    research_block = workflow[research:bind]
    provenance_block = workflow[provenance:timestamp_gate]

    assert research < bind < provenance < timestamp_gate
    assert workflow.count("inst_id: [BTC-USDT, ETH-USDT]") == 1
    assert research_block.count("--config config/okx_research_1h.json") == 1
    assert research_block.count('--inst-id "${{ matrix.inst_id }}"') == 1
    assert provenance_block.count("python -m gpt_quant.intraday_1h_source_provenance") == 1
    assert provenance_block.count('--inst-id "${{ matrix.inst_id }}"') == 1
    assert 'REPORT_DIR: "reports/okx/1h/${{ matrix.inst_id }}"' in workflow
    assert 'SOURCE_ROOT: "reports/okx/1h/source/${{ matrix.inst_id }}"' in workflow
    assert workflow.count("experiment-manifest.jsonl") >= 2
    assert "Acquire replay-verifiable exact-byte 1h source" in workflow
    assert "Run canonical 1h full walk-forward research" in workflow
    assert "Verify persisted canonical 1h evidence" in workflow
    assert "Verify exact persisted 5 bps-only profile" in workflow
    assert "Write explicit 1h promotion blockers" in workflow
    assert "Enforce fail-closed 1h research promotion" in workflow
    assert "fail-fast: false" in workflow
    assert "persist-credentials: false" in workflow
    assert "OKX_BASE_URL: https://www.okx.com" in workflow


def test_workflow_replays_exact_byte_source_before_research() -> None:
    path = _REPOSITORY_ROOT / ".github/workflows/intraday-1h-research.yml"
    workflow = path.read_text(encoding="utf-8")

    acquire = workflow.index("- name: Acquire replay-verifiable exact-byte 1h source")
    research = workflow.index("- name: Run canonical 1h full walk-forward research")
    bind = workflow.index("- name: Bind exchange-time source envelope")
    timestamp_gate = workflow.index("- name: Verify exact persisted UTC-hour timestamp grid")
    source_block = workflow[acquire:research]
    research_block = workflow[research:bind]
    bind_block = workflow[bind:timestamp_gate]

    assert acquire < research < bind < timestamp_gate
    assert source_block.count("python scripts/run_okx_1h_coverage.py") == 1
    assert source_block.count('--start "2021-07-24T00:00:00Z"') == 1
    assert source_block.count('--instrument "${{ matrix.inst_id }}"') == 1
    assert research_block.count("python scripts/run_okx_research.py") == 1
    assert research_block.count(
        '--snapshot-dir "$SOURCE_ROOT/${{ matrix.inst_id }}/snapshot"'
    ) == 1
    assert "OKX_BASE_URL" not in research_block
    assert 'cp "$SOURCE_ROOT/coverage-manifest.json"' in bind_block
    assert 'cp "$SOURCE_ROOT/okx-public-time.canonical.json"' in bind_block


def test_workflow_gates_persisted_fee_profile_before_artifact_hashing() -> None:
    path = _REPOSITORY_ROOT / ".github/workflows/intraday-1h-research.yml"
    workflow = path.read_text(encoding="utf-8")

    report_verification = workflow.index("- name: Verify persisted canonical 1h evidence")
    profile_verification = workflow.index("- name: Verify exact persisted 5 bps-only profile")
    blocker_summary = workflow.index("- name: Write explicit 1h promotion blockers")
    enforcement = workflow.index("- name: Enforce fail-closed 1h research promotion")
    manifest = workflow.index("- name: Build and verify immutable canonical 1h manifest")
    upload = workflow.index("- name: Upload immutable canonical 1h evidence")
    profile_block = workflow[profile_verification:blocker_summary]
    summary_block = workflow[blocker_summary:enforcement]
    enforcement_block = workflow[enforcement:manifest]
    manifest_block = workflow[manifest:upload]

    assert (
        report_verification
        < profile_verification
        < blocker_summary
        < enforcement
        < manifest
        < upload
    )
    assert profile_block.count("python scripts/verify_intraday_1h_profile.py") == 1
    assert profile_block.count('--output-dir "$REPORT_DIR"') == 1
    assert summary_block.count("python scripts/build_intraday_1h_promotion_gate.py") == 1
    assert "--enforce-research-promotion" not in summary_block
    assert enforcement_block.count("python scripts/build_intraday_1h_promotion_gate.py") == 1
    assert enforcement_block.count("--enforce-research-promotion") == 1
    assert "inputs.enforce_intraday_research_promotion" in enforcement_block
    assert "id: artifact_manifest" in manifest_block
    assert "set -euo pipefail" in manifest_block
    for required_file in (
        "effective_config.json",
        "walk_forward.json",
        "walk_forward_returns.csv",
        "experiment-manifest.jsonl",
        "intraday-promotion-gate.json",
        "source-coverage-manifest.json",
        "source-public-time.canonical.json",
    ):
        assert f'test -s "$REPORT_DIR/{required_file}"' in manifest_block
    assert 'python -m gpt_quant.artifact_manifest --root "$REPORT_DIR"' in manifest_block
    assert '[[ "$manifest_sha256" =~ ^[0-9a-f]{64}$ ]]' in manifest_block
    assert 'cd "$REPORT_DIR"' in manifest_block
    assert "sha256sum --check artifact-manifest.sha256" in manifest_block
    assert 'sha256sum --check "$temporary_manifest"' not in manifest_block
    assert "manifest_sha256=%s" in manifest_block


def test_workflow_exposes_explicit_manual_research_promotion_enforcement() -> None:
    path = _REPOSITORY_ROOT / ".github/workflows/intraday-1h-research.yml"
    workflow = path.read_text(encoding="utf-8")

    dispatch = workflow.index("workflow_dispatch:")
    push = workflow.index("  push:")
    dispatch_block = workflow[dispatch:push]

    assert dispatch_block.count("enforce_intraday_research_promotion:") == 1
    assert "required: false" in dispatch_block
    assert "default: false" in dispatch_block
    assert "type: boolean" in dispatch_block


def test_workflow_aggregates_verified_markets_before_cross_market_promotion() -> None:
    path = _REPOSITORY_ROOT / ".github/workflows/intraday-1h-research.yml"
    workflow = path.read_text(encoding="utf-8")

    cross_market_job = workflow.index("  cross_market_gate:")
    install = workflow.index("- name: Install cross-market verifier")
    download = workflow.index("- name: Download immutable canonical 1h evidence")
    build = workflow.index("- name: Build deterministic cross-market launch blockers")
    upload = workflow.index("- name: Upload cross-market launch-blocker evidence")
    integrity = workflow.index("- name: Enforce cross-market evidence integrity")
    promotion = workflow.index("- name: Enforce fail-closed cross-market research promotion")
    block = workflow[cross_market_job:]

    assert cross_market_job < install < download < build < upload < integrity < promotion
    assert "if: ${{ always() }}" in block
    assert "needs: research" in block
    assert "UPSTREAM_RESEARCH_RESULT: ${{ needs.research.result }}" in block
    assert block.count('python -m pip install "pip==${PIP_BOOTSTRAP_VERSION}"') == 1
    assert block.count("python -m pip install -e .") == 1
    assert block.count("python -m pip check") == 1
    assert "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c" in block
    assert (
        "pattern: canonical-*-1h-${{ github.run_number }}-attempt-${{ github.run_attempt }}"
        in block
    )
    assert "merge-multiple: false" in block
    assert "continue-on-error: true" in block
    assert block.count("python scripts/build_intraday_1h_cross_market_gate.py") == 2
    assert "PYTHONPATH=src" not in block
    assert "intraday-cross-market-gate.json" in block
    assert "CROSS_MARKET_GATE_OUTCOME: ${{ steps.cross_market_gate.outcome }}" in block
    assert 'test "$CROSS_MARKET_GATE_OUTCOME" = success' in block
    assert "inputs.enforce_intraday_research_promotion" in block
    assert "persist-credentials: false" in block
