#!/usr/bin/env python3
"""Verify the completed calendar-phase information-family closure artifact."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

FAMILY = "causal-calendar-phase-timing-information-family-closure-1h-v1"
ROOT = Path("reports/research") / FAMILY
EXPECTED = {
    "source_group_a.json": "944e288f9837183e672d821fbe61cfa034371c0b13d177ada3542f1d02f6f8e6",
    "source_group_b.json": "9cce7939e8c7755032dcbc388eda214621fe86f5906df012dbd0c5272b466832",
    "evidence.json": "58951b6bd55e15faa0cd0076bc81d7d3f7e3ef11b90a94fbd0a8cfc5c300fb29",
    "report.md": "15652eb2e308b02abbcd448d8e0fb03ff48544a9bcfb4c2d7d0ad42c48ba4aef",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(name: str) -> dict[str, Any]:
    path = ROOT / name
    actual = sha256(path)
    expected = EXPECTED[name]
    if actual != expected:
        raise ValueError(f"{name}: expected {expected}, got {actual}")
    return json.loads(path.read_text())


def group_gates(record: dict[str, Any]) -> dict[str, bool | None]:
    markets = record["markets"].values()
    candidate = [market["candidate"]["oos"] for market in markets]
    markets = record["markets"].values()
    benchmark = [market["benchmark_e2160_daily"]["oos"] for market in markets]
    positive = all(item["net_return"] > 0 for item in candidate)
    superior = all(
        cand["net_return"] > bench["net_return"] and cand["sharpe"] > bench["sharpe"]
        for cand, bench in zip(candidate, benchmark, strict=True)
    )

    markets = record["markets"].values()
    if record["architecture_group"] == "weekly_phase_conditioned_trend_carry":
        dependence = all(
            market["uncertainty_vs_daily_e2160"]["annualised_mean_delta_l95"] > 0
            and market["uncertainty_vs_daily_e2160"]["sharpe_delta_l95"] > 0
            for market in markets
        )
        markets = record["markets"].values()
        breadth = all(
            market["breadth"]["profitable_folds"] >= 7
            and market["breadth"]["profitable_years"] >= 3
            and market["breadth"]["positive_fold_concentration"] <= 0.5
            for market in markets
        )
        markets = record["markets"].values()
        transport = all(
            market["top_two_overlap"] > 0 and market["phase_transport"]["spearman"] > 0
            for market in markets
        )
        delay = None
    else:
        dependence = all(
            market["uncertainty_vs_e2160"]["mean_net_delta_bp_per_hour_ci95"][0] > 0
            and market["uncertainty_vs_e2160"]["sharpe_delta_ci95"][0] > 0
            for market in markets
        )
        markets = record["markets"].values()
        breadth = all(
            market["breadth"]["positive_relative_folds"] >= 7
            and market["breadth"]["positive_candidate_and_relative_years"] >= 3
            and market["breadth"]["positive_fold_concentration"] <= 0.5
            for market in markets
        )
        markets = record["markets"].values()
        transport = all(
            market["profile_transport"]["correlation"] > 0
            and market["profile_transport"]["ci95"][0] > 0
            for market in markets
        )
        markets = record["markets"].values()
        delay = all(
            market["delayed_oos"]["net_return"] > 0 and market["delayed_oos"]["sharpe"] > 0
            for market in markets
        )

    source_valid = (
        record["bar"] == "1H"
        and record["fee_one_way"] == 0.0005
        and record["source"]["provider"] == "OKX"
        and record["source"]["market_type"] == "SPOT"
        and record["source"]["confirmed"] is True
        and record["research_parent"] == "5a0fcc97d1a882f8223656c51f5bb8055f534e38"
    )
    supportive = all([source_valid, positive, superior, dependence, breadth, transport]) and (
        delay is not False
    )
    return {
        "source_executable_causal_immutable_exact_fee": source_valid,
        "bilateral_positive_absolute_oos_net": positive,
        "bilateral_benchmark_net_and_sharpe_superiority": superior,
        "bilateral_positive_dependence_lower_bounds": dependence,
        "bilateral_preregistered_temporal_breadth": breadth,
        "bilateral_direct_calendar_transport": transport,
        "bilateral_delay_robustness": delay,
        "supportive": supportive,
    }


def main() -> None:
    a = load("source_group_a.json")
    b = load("source_group_b.json")
    evidence = load("evidence.json")
    report_path = ROOT / "report.md"
    if sha256(report_path) != EXPECTED["report.md"]:
        raise ValueError("report.md identity mismatch")

    computed = {
        a["architecture_group"]: group_gates(a),
        b["architecture_group"]: group_gates(b),
    }
    if evidence["group_gates"] != computed:
        raise ValueError("group gate replay mismatch")
    if any(group["supportive"] for group in computed.values()):
        raise ValueError("unexpected supportive calendar-phase architecture")
    if evidence["support_counts_out_of_two"]["supportive_groups"] != 0:
        raise ValueError("support count mismatch")
    if evidence["family_gates"]["both_groups_source_valid"] is not True:
        raise ValueError("source validity gate must pass")
    failed_family_gates = [name for name, passed in evidence["family_gates"].items() if not passed]
    if len(failed_family_gates) != 6:
        raise ValueError(f"expected six failed family gates, got {failed_family_gates}")
    if evidence["verdict"] != "reject_causal_calendar_phase_timing_information_family":
        raise ValueError("terminal verdict mismatch")
    if evidence["new_candidate_count"] != 0 or evidence["new_oos_consumed"] != 0:
        raise ValueError("closure consumed a candidate or OOS")
    print(f"family={FAMILY}")
    print("supportive_groups=0/2")
    print(f"failed_family_gates={len(failed_family_gates)}/7")
    print(f"verdict={evidence['verdict']}")
    for name, digest in EXPECTED.items():
        print(f"{name}={digest}")


if __name__ == "__main__":
    main()
