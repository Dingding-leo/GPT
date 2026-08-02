from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

FAMILY_ID = "causal-own-price-event-clock-renewal-timing-family-closure-1h-v1"
VERDICT = "close_causal_own_price_event_clock_renewal_timing_family_1h_v1"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    raw = args.evidence.read_bytes()
    evidence = json.loads(raw)
    assert evidence["family_id"] == FAMILY_ID
    assert evidence["architecture_group_count"] == 4
    assert evidence["candidate_count"] == 0
    assert evidence["parameter_grid_count"] == 0
    assert evidence["new_market_data"] == 0
    assert evidence["new_target_returns"] == 0
    assert evidence["new_oos_consumed"] == 0
    assert evidence["canonical_fee_bps_one_way"] == 5.0
    assert evidence["closure_gate_pass_count"] == evidence["closure_gate_count"] == 9
    assert all(evidence["closure_gates"].values())
    assert all(item["passes"] for item in evidence["leave_one_group_out"].values())
    assert evidence["economically_executable_groups"] == ["A", "B"]
    assert evidence["information_support_failures"] == ["C", "D"]
    assert evidence["bilateral_promoted_groups"] == []
    assert evidence["bilateral_positive_dependence_lower_bound_groups"] == []
    assert evidence["correction_permitted"] is False
    assert evidence["canonical_policy_changed"] is False
    assert evidence["observation_epoch_restarted"] is False
    assert evidence["paper_trading_authorized"] is False
    assert evidence["live_trading_authorized"] is False
    assert evidence["verdict"] == VERDICT

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "evidence.json").write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    (args.output_dir / "evidence.sha256").write_text(digest + "\n")
    report = args.evidence.with_name("report.md")
    (args.output_dir / "report.md").write_bytes(report.read_bytes())
    print(json.dumps({"evidence_sha256": digest, "verdict": VERDICT}, sort_keys=True))


if __name__ == "__main__":
    main()
