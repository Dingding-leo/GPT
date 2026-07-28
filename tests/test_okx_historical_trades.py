from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.mark.skipif(
    not os.environ.get("OKX_BASE_URL"),
    reason="live public OKX checkpoint runs only when OKX_BASE_URL is provided",
)
def test_live_trade_flow_source_schema_checkpoint() -> None:
    output_dir = Path("reports/okx/trade-flow-schema-checkpoint")
    subprocess.run(
        [
            sys.executable,
            "scripts/acquire_okx_historical_trades.py",
            "--output-dir",
            str(output_dir),
            "--base-url",
            os.environ["OKX_BASE_URL"],
        ],
        check=True,
    )
    subprocess.run(
        [
            sys.executable,
            "scripts/stress_okx_trade_flow_checkpoint.py",
            "--output-dir",
            str(output_dir),
        ],
        check=True,
    )

    result_path = output_dir / "result.json"
    result_bytes = result_path.read_bytes()
    result = json.loads(result_bytes)
    stress_bytes = (output_dir / "stress-result.json").read_bytes()
    stress = json.loads(stress_bytes)

    assert result["schema_version"] == "trade-flow-source-schema-checkpoint-v2"
    assert result["architecture_family_id"] == "okx-spot-causal-trade-flow-resilience-v2"
    assert result["candidate_count"] == 2
    assert result["canonical_fee_bps_one_way"] == 5.0
    assert result["performance_inspected"] is False
    assert result["oos_consumed"] is False
    assert result["archive_day_contract"] == {
        "aggregation": "daily",
        "timezone": "UTC+8",
        "hourly_feature_buckets": "UTC",
    }
    assert result["verdict"] == ("trade_flow_source_schema_checkpoint_survived_adversarial_stress")
    assert [market["inst_id"] for market in result["markets"]] == [
        "BTC-USDT",
        "ETH-USDT",
    ]

    for market in result["markets"]:
        assert market["status"] == "checkpoint_passed"
        assert market["archive"]["complete_24h_passed"] is True
        assert market["archive"]["hour_count"] == 24
        assert (
            market["archive"]["expected_end_exclusive_ms"] - market["archive"]["expected_start_ms"]
            == 24 * 3_600_000
        )

        overlap = market["rest_overlap"]
        assert overlap["older_page_rows"] == 100
        assert overlap["newer_page_rows"] == 100
        assert overlap["cross_page_unique_rows"] == 200
        assert overlap["archive_matched_trade_ids"] == 200
        assert overlap["economic_field_mismatch_count"] == 0
        assert overlap["older_cursor_direction_passed"] is True
        assert overlap["newer_cursor_direction_passed"] is True
        assert overlap["archive_adjacent_id_sets_passed"] is True
        assert overlap["equal_millisecond_group_count"] >= 1
        assert overlap["maximum_equal_millisecond_group_size"] >= 2
        assert overlap["parity_passed"] is True

        diagnostic = market["strategy_feature_diagnostic"]
        assert diagnostic["hours"] == 24
        assert diagnostic["same_timestamp_group_count"] > 0
        assert diagnostic["permutation_invariant"] is True
        assert diagnostic["future_suffix_invariant"] is True
        assert diagnostic["trade_id_time_inversion_count"] == 0
        assert diagnostic["exact_byte_replay_passed"] is True
        assert diagnostic["naive_order_changed_hour_count"] > 0

    assert stress["schema_version"] == "trade-flow-checkpoint-adversarial-stress-v2"
    assert stress["architecture_family_id"] == result["architecture_family_id"]
    assert stress["candidate_count"] == 2
    assert stress["canonical_fee_bps_one_way"] == 5.0
    assert stress["performance_inspected"] is False
    assert stress["oos_consumed"] is False
    assert stress["defects"] == []
    assert stress["verdict"] == ("trade_flow_source_schema_checkpoint_survived_adversarial_stress")
    assert result["adversarial_stress"]["verdict"] == stress["verdict"]
    assert result["adversarial_stress"]["defects"] == []
    assert all(market["status"] == "passed" for market in stress["markets"])

    assert (output_dir / "result.sha256").read_text().strip() == sha256(result_bytes)
    assert (output_dir / "stress-result.sha256").read_text().strip() == sha256(stress_bytes)
