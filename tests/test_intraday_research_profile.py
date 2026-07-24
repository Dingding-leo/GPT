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

    assert workflow.count("inst_id: [BTC-USDT, ETH-USDT]") == 1
    assert workflow.count("--config config/okx_research_1h.json") == 1
    assert workflow.count('--inst-id "${{ matrix.inst_id }}"') == 1
    assert workflow.count("reports/okx/1h/${{ matrix.inst_id }}") >= 10
    assert workflow.count("experiment-manifest.jsonl") >= 2
    assert "Run canonical 1h full walk-forward research" in workflow
    assert "Verify persisted canonical 1h evidence" in workflow
    assert "Verify exact persisted 5 bps-only profile" in workflow
    assert "Write explicit 1h promotion blockers" in workflow
    assert "Enforce fail-closed 1h research promotion" in workflow
    assert "fail-fast: false" in workflow
    assert "persist-credentials: false" in workflow
    assert "OKX_BASE_URL: https://www.okx.com" in workflow


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

    assert report_verification < profile_verification < blocker_summary < enforcement < manifest < upload
    assert profile_block.count("python scripts/verify_intraday_1h_profile.py") == 1
    assert profile_block.count('--output-dir "reports/okx/1h/${{ matrix.inst_id }}"') == 1
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
    ):
        assert f'test -s "$report_dir/{required_file}"' in manifest_block
    assert 'python -m gpt_quant.artifact_manifest --root "$report_dir"' in manifest_block
    assert '[[ "$manifest_sha256" =~ ^[0-9a-f]{64}$ ]]' in manifest_block
    assert 'cd "$report_dir"' in manifest_block
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
