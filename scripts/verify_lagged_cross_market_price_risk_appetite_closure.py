#!/usr/bin/env python3
"""Deterministically verify the immutable #1074 closure artifact.

This verifier performs no network or market-data access. It checks only the
persisted evidence contract and terminal adjudication.
"""

from __future__ import annotations

import json
from pathlib import Path


EXPECTED_FAMILY = (
    "causal-lagged-cross-market-price-risk-appetite-programme-closure-1h-v1"
)
EXPECTED_VERDICT = (
    "reject_reopening_completed_lagged_cross_market_price_"
    "risk_appetite_mechanisms_1h_v1"
)
EXPECTED_ISSUES = {877, 963, 1072}


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    evidence_path = root / (
        "reports/research/lagged-cross-market-price-risk-appetite-closure/"
        "evidence.json"
    )
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

    assert evidence["family_id"] == EXPECTED_FAMILY
    assert evidence["candidate_count"] == 0
    assert evidence["parameter_grid_count"] == 0
    assert evidence["new_market_data_rows"] == 0
    assert evidence["new_target_labels"] == 0
    assert evidence["new_oos_access"] == 0
    assert evidence["new_fitting_or_tuning"] == 0
    assert evidence["canonical_mutation"] is False
    assert evidence["paper_trading_authorized"] is False
    assert evidence["live_trading_authorized"] is False

    mechanisms = evidence["mechanisms"]
    assert len(mechanisms) == 3
    assert {item["owner_issue"] for item in mechanisms} == EXPECTED_ISSUES
    assert all(item["independently_admissible"] is False for item in mechanisms)
    assert evidence["independently_admissible_mechanism_count"] == 0
    assert evidence["mechanism_count"] == 3

    loo = evidence["leave_one_mechanism_out"]
    assert set(loo.values()) == {"reject"}
    assert evidence["leave_one_cohort_out"]["result"] == "reject"
    assert evidence["family_transport_supported"] is False
    assert evidence["correction_authority"] is False
    assert evidence["canonical_policy_changed"] is False
    assert evidence["observation_epoch_restarted"] is False
    assert evidence["verdict"] == EXPECTED_VERDICT

    print(EXPECTED_VERDICT)


if __name__ == "__main__":
    main()
