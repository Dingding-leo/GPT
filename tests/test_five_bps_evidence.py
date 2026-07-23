import hashlib
import json
from pathlib import Path

import pytest

from gpt_quant.five_bps_evidence import (
    build_five_bps_walk_forward_evidence,
    write_five_bps_walk_forward_evidence,
)

_TESTED_SHA = "1" * 40
_SOURCE_SHA = "2" * 40


def _verification(instrument: str) -> dict[str, object]:
    suffix = "a" if instrument == "BTC-USDT" else "b"
    return {
        "effective_config_sha256": suffix * 64,
        "folds": 27,
        "latency_model": "not_modeled",
        "manifest_code_commit": _TESTED_SHA,
        "manifest_config_sha256": suffix * 64,
        "manifest_normalized_csv_sha256": ("c" if suffix == "a" else "d") * 64,
        "manifest_run_id": f"run-{suffix * 24}",
        "market_impact_model": "not_modeled",
        "observations": 2385,
        "report_json_sha256": ("e" if suffix == "a" else "f") * 64,
        "returns_csv_sha256": ("0" if suffix == "a" else "1") * 64,
        "selected_folds_verified": 27,
        "selected_position_rows_verified": 2385,
        "selected_target_rows_verified": 2385,
        "selection_candidate_evaluations_verified": 729,
        "selection_candidates_per_fold": 27,
        "selection_folds_verified": 27,
        "selection_source": (
            "immutable_normalized_okx_close_and_effective_config_full_5bps_reselection"
        ),
        "slippage_model": "not_modeled",
        "source_price_rows_verified": 2385,
        "source_snapshot_sha256": ("c" if suffix == "a" else "d") * 64,
        "spread_model": "not_modeled",
        "status": "passed",
        "transaction_cost_bps": 5.0,
        "verification_schema": "persisted_walk_forward_v1",
    }


def _write_reports(root: Path) -> None:
    for instrument in ("BTC-USDT", "ETH-USDT"):
        path = root / instrument / "walk_forward_verification.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(_verification(instrument), sort_keys=True), encoding="utf-8")


def test_builds_deterministic_source_and_tested_revision_bound_evidence(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    _write_reports(reports)

    payload = build_five_bps_walk_forward_evidence(
        reports,
        source_head_sha=_SOURCE_SHA,
        tested_sha=_TESTED_SHA,
    )
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first_hash = write_five_bps_walk_forward_evidence(payload, first)
    second_hash = write_five_bps_walk_forward_evidence(payload, second)

    assert first.read_bytes() == second.read_bytes()
    assert first_hash == second_hash == hashlib.sha256(first.read_bytes()).hexdigest()
    assert payload["status"] == "pass"
    assert payload["fee_bps_one_way"] == 5.0
    assert payload["selection_recomputed"] is True
    assert payload["head_sha"] == _SOURCE_SHA
    assert payload["tested_sha"] == _TESTED_SHA
    assert payload["instruments"] == ["BTC-USDT", "ETH-USDT"]
    assert all(row["observations_verified"] == 2385 for row in payload["instrument_evidence"])


def test_rejects_fixed_path_or_conflated_execution_cost_claims(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    _write_reports(reports)
    btc_path = reports / "BTC-USDT" / "walk_forward_verification.json"
    btc = json.loads(btc_path.read_text(encoding="utf-8"))
    btc["selection_source"] = "fixed_selected_path_repricing"
    btc["spread_model"] = "included_in_fee"
    btc_path.write_text(json.dumps(btc, sort_keys=True), encoding="utf-8")

    with pytest.raises(ValueError, match="full 5 bps fold reselection"):
        build_five_bps_walk_forward_evidence(
            reports,
            source_head_sha=_SOURCE_SHA,
            tested_sha=_TESTED_SHA,
        )


def test_rejects_verification_from_a_different_tested_revision(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    _write_reports(reports)

    with pytest.raises(ValueError, match="not bound to tested revision"):
        build_five_bps_walk_forward_evidence(
            reports,
            source_head_sha=_SOURCE_SHA,
            tested_sha="3" * 40,
        )
