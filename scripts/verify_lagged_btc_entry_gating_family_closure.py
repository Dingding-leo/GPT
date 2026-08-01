#!/usr/bin/env python3
"""Verify the completed causal lagged-BTC entry-gating family closure."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

FAMILY = "causal-lagged-btc-entry-gating-family-closure-1h-v1"
ROOT = Path("reports/research") / FAMILY
PARENT = "5a0fcc97d1a882f8223656c51f5bb8055f534e38"
EXPECTED = {
    "source_group_a.json": "400600a79b65061e85ff7bb086efb890c6ca5745d3c9ae05f082105181f177af",
    "source_group_b.json": "3d94b5533b6039d4662a30460cebe5e89dca46f4f7b1237a945415426056a0fe",
    "source_group_c.json": "b86f736b43d63999c1d7e74782bd2e6bc264d4c9e2829e49b67ab954757598b8",
    "evidence.json": "c46260f308b9dd49df068f8987e1c0d508bf85144c7780dbe7bb93a0f2443b68",
    "report.md": "5257c6868659428413a5a0bf14301ce950deaf76683ee39614d210e36bc483ee",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(name: str) -> dict[str, Any]:
    path = ROOT / name
    actual = digest(path)
    if actual != EXPECTED[name]:
        raise ValueError(f"{name} expected {EXPECTED[name]}, got {actual}")
    return json.loads(path.read_text())


def finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value)


def source_valid(record: dict[str, Any]) -> bool:
    source = record["source"]
    return (
        record["candidate_count"] == 1
        and record["parameter_grid_count"] == 0
        and source["bar"] == "1H"
        and source["fee_one_way"] == 0.0005
        and source["provider"] == "OKX"
        and source["market_type"] == "SPOT"
        and source["confirmed"] is True
        and source["research_parent"] == PARENT
        and source["sample"]["later_suffix_unread"] is True
        and all(value["observations"] == 43941 for value in source["artifacts"].values())
    )


def group_gates(record: dict[str, Any]) -> dict[str, bool]:
    markets = list(record["markets"].values())
    candidates = [market["candidate"]["oos"] for market in markets]
    benchmarks = [market["benchmark_b1"]["oos"] for market in markets]

    positive = all(
        finite(candidate["net_return"])
        and candidate["net_return"] > 0
        and finite(candidate["sharpe"])
        and candidate["sharpe"] > 0
        for candidate in candidates
    )
    superior = all(
        finite(candidate["net_return"])
        and finite(candidate["sharpe"])
        and candidate["net_return"] > benchmark["net_return"]
        and candidate["sharpe"] > benchmark["sharpe"]
        for candidate, benchmark in zip(candidates, benchmarks, strict=True)
    )
    lower_bounds = all(
        market["uncertainty_vs_b1"]["annualized_mean_delta_l95"] > 0
        and market["uncertainty_vs_b1"]["sharpe_delta_l95"] > 0
        for market in markets
    )
    breadth = all(
        market["breadth"]["profitable_folds"] >= 7
        and market["breadth"]["profitable_years"] >= 3
        and market["breadth"]["positive_fold_concentration"] is not None
        and market["breadth"]["positive_fold_concentration"] <= 0.5
        for market in markets
    )

    architecture = record["architecture_group"]
    if architecture == "lagged_btc_downside_stress_entry_veto":
        transport = all(
            abs(
                market["transport"]["oos_state_rate"]
                - market["transport"]["training_state_rate"]
            )
            <= 0.05
            and market["transport"]["oos_effect_folds"] >= 3
            and market["uncertainty_vs_b1"]["zero_effect_resample_fraction"] < 0.10
            for market in markets
        )
    elif architecture == "lagged_btc_liquidity_stress_recovery_entry":
        state = record["state_transport"]
        transport = (
            state["training_recovery_state_rate"] > 0
            and state["oos_recovery_state_rate"] > 0
            and state["oos_complete_recovery_states"] >= 20
            and 0.5
            <= state["oos_recovery_state_rate"] / state["training_recovery_state_rate"]
            <= 2.0
        )
    else:
        support = record["performance_free_support"]
        transport = (
            support["selector_enabled"] is True
            and support["training_state_decisions"] >= support["minimum_required"]
            and support["unique_training_state_supporting_events"] >= 3
            and support["largest_training_event_concentration"] <= 0.5
        )

    valid = source_valid(record)
    supportive = all([valid, positive, superior, lower_bounds, breadth, transport])
    return {
        "source_executable_causal_immutable_exact_fee_or_valid_fail_closed": valid,
        "bilateral_positive_absolute_oos_net_and_sharpe": positive,
        "bilateral_b1_net_and_sharpe_superiority": superior,
        "bilateral_positive_dependence_lower_bounds": lower_bounds,
        "bilateral_preregistered_fold_year_breadth": breadth,
        "exogenous_state_transport_or_event_support": transport,
        "supportive": supportive,
    }


def main() -> None:
    records = [load(f"source_group_{suffix}.json") for suffix in "abc"]
    evidence = load("evidence.json")
    if digest(ROOT / "report.md") != EXPECTED["report.md"]:
        raise ValueError("report identity mismatch")

    computed = {record["architecture_group"]: group_gates(record) for record in records}
    if computed != evidence["group_gates"]:
        raise ValueError("group gate replay mismatch")
    if sum(int(value["supportive"]) for value in computed.values()) != 0:
        raise ValueError("unexpected supportive group")

    counts = evidence["support_counts_out_of_three"]
    if counts["supportive_groups"] != 0:
        raise ValueError("supportive group count mismatch")
    if counts["bilateral_positive_absolute_oos_net_and_sharpe"] != 1:
        raise ValueError("bilateral positive OOS count mismatch")

    failed = [name for name, passed in evidence["family_gates"].items() if not passed]
    if len(failed) != 6:
        raise ValueError(f"expected six failed family gates, got {failed}")
    if evidence["verdict"] != "reject_causal_lagged_btc_entry_gating_family":
        raise ValueError("verdict mismatch")
    if (
        evidence["new_candidate_count"] != 0
        or evidence["new_oos_consumed"] != 0
        or evidence["new_market_data_consumed"] != 0
    ):
        raise ValueError("closure consumed new research data")

    print(f"family={FAMILY}")
    print("supportive_groups=0/3")
    print("bilateral_positive_oos_groups=1/3")
    print(f"failed_family_gates={len(failed)}/7")
    print(f"verdict={evidence['verdict']}")
    for name, value in EXPECTED.items():
        print(f"{name}={value}")


if __name__ == "__main__":
    main()
