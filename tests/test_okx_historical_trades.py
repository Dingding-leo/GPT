from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


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
    result = json.loads(result_path.read_text())
    stress = json.loads((output_dir / "stress-result.json").read_text())

    assert result["schema_version"] == "trade-flow-source-schema-checkpoint-v1"
    assert result["architecture_family_id"] == "okx-spot-causal-trade-flow-resilience-v2"
    assert result["candidate_count"] == 2
    assert result["canonical_fee_bps_one_way"] == 5.0
    assert result["performance_inspected"] is False
    assert result["oos_consumed"] is False
    assert [market["inst_id"] for market in result["markets"]] == [
        "BTC-USDT",
        "ETH-USDT",
    ]

    assert stress["schema_version"] == "trade-flow-checkpoint-adversarial-stress-v1"
    assert stress["architecture_family_id"] == result["architecture_family_id"]
    assert stress["candidate_count"] == 2
    assert stress["performance_inspected"] is False
    assert stress["oos_consumed"] is False
    assert stress["verdict"] in {
        "trade_flow_source_schema_checkpoint_blocked_by_adversarial_stress",
        "trade_flow_source_schema_checkpoint_survived_adversarial_stress",
    }
    assert result["adversarial_stress"]["verdict"] == stress["verdict"]
    assert result["verdict"] == stress["verdict"]

    for name in ("result.sha256", "stress-result.sha256"):
        checksum = (output_dir / name).read_text().strip()
        assert len(checksum) == 64
        assert all(character in "0123456789abcdef" for character in checksum)
