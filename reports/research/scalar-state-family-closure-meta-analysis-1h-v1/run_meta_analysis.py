#!/usr/bin/env python3
"""Deterministic family-cluster closure for terminal scalar-state diagnostics."""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from pathlib import Path
from typing import Any

SEED = 20260801
RESAMPLES = 100_000
FEE_ONE_WAY = 0.0005
VERDICT_REJECT = "reject_scalar_state_gating_architecture_family"
VERDICT_SUPPORT = "retain_scalar_state_gating_architecture_family"

DIAGNOSTICS: tuple[dict[str, Any], ...] = (
    {
        "name": "lag1_self_contained_b1_payoff_memory",
        "issue": 795,
        "pr": 796,
        "source_head": "c6ce3ecc0ee67ca0dd99f86c99866d32beff1c1a",
        "group": "performance_memory",
        "target": "next_week_fee_adjusted_b1_payoff",
        "btc": {"rho": -0.0684, "ci95": [-0.3630, 0.1693], "positive_breadth": [2, 6]},
        "eth": {"rho": -0.0187, "ci95": [-0.2255, 0.1800], "positive_breadth": [2, 6]},
    },
    {
        "name": "trend_boundary_occupancy",
        "issue": 798,
        "pr": 802,
        "source_head": "ed222ce2c1df31f58e64a7d6287c00b07fddbee1",
        "group": "b1_geometry",
        "target": "next_week_b1_gross_opportunity",
        "btc": {"rho": 0.1652, "ci95": [-0.1720, 0.4488], "positive_breadth": [1, 6]},
        "eth": {"rho": 0.1049, "ci95": [-0.1262, 0.3313], "positive_breadth": [2, 6]},
    },
    {
        "name": "signed_168h_path_coherence",
        "issue": 803,
        "pr": 804,
        "source_head": "4611e9323fd9cefdd8a8e7057fba10f1464fecbb",
        "group": "b1_geometry",
        "target": "next_active_week_b1_gross_opportunity",
        "btc": {"rho": 0.0077, "ci95": [-0.4334, 0.4227], "positive_breadth": [2, 6]},
        "eth": {"rho": 0.1204, "ci95": [-0.2171, 0.4738], "positive_breadth": [2, 6]},
    },
    {
        "name": "daily_positive_trend_age",
        "issue": 806,
        "pr": 807,
        "source_head": "1e2cded75fe42e34af7cf4270752bc08da6ecb40",
        "group": "b1_geometry",
        "target": "next_day_active_b1_gross_opportunity",
        "btc": {"rho": 0.0589, "ci95": [-0.0488, 0.1683], "positive_breadth": [1, 6]},
        "eth": {"rho": 0.0247, "ci95": [-0.0847, 0.1189], "positive_breadth": [2, 6]},
    },
    {
        "name": "coinm_basis_compression_resilience",
        "issue": 814,
        "pr": 815,
        "source_head": "cb1e3c400e3f0858a9ff3f9f9524c75cd5fc3ed2",
        "group": "derivatives_exogenous",
        "target": "next_day_spot_gross_opportunity",
        "btc": {"rho": -0.0497, "ci95": [-0.1493, 0.0432], "positive_breadth": [3, 8]},
        "eth": {"rho": 0.0020, "ci95": [-0.1031, 0.1051], "positive_breadth": [6, 8]},
    },
    {
        "name": "range_acceptance_continuation",
        "issue": 817,
        "pr": 818,
        "source_head": "adf36a9ea67d30737f4e40fa1c867f645fbbc757",
        "group": "spot_auction_geometry",
        "target": "next_day_spot_gross_opportunity",
        "btc": {"rho": -0.0076, "ci95": [-0.1194, 0.1091], "positive_breadth": [4, 11]},
        "eth": {"rho": -0.0065, "ci95": [-0.1126, 0.0951], "positive_breadth": [5, 11]},
    },
    {
        "name": "lagged_return_range_response_resilience",
        "issue": 822,
        "pr": 823,
        "source_head": "6bf34008f37afbe36ea7c3310abf0f4fb354cdac",
        "group": "lagged_vol_response",
        "target": "next_day_spot_gross_opportunity",
        "btc": {"rho": 0.0137, "ci95": [-0.0955, 0.1108], "positive_breadth": [3, 11]},
        "eth": {"rho": 0.0656, "ci95": [-0.0402, 0.1740], "positive_breadth": [4, 11]},
    },
)


def percentile(values: list[float], probability: float) -> float:
    if not values:
        raise ValueError("empty percentile input")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def interval(values: list[float]) -> list[float]:
    return [percentile(values, 0.025), percentile(values, 0.975)]


def exact_upper_sign_p(successes: int, trials: int) -> float:
    return sum(math.comb(trials, k) for k in range(successes, trials + 1)) / (2**trials)


def grouped_effects() -> list[dict[str, Any]]:
    names = sorted({item["group"] for item in DIAGNOSTICS})
    output: list[dict[str, Any]] = []
    for name in names:
        members = [item for item in DIAGNOSTICS if item["group"] == name]
        btc = statistics.median(item["btc"]["rho"] for item in members)
        eth = statistics.median(item["eth"]["rho"] for item in members)
        output.append(
            {
                "group": name,
                "members": [item["name"] for item in members],
                "btc_rho": btc,
                "eth_rho": eth,
                "bilateral_mean_rho": (btc + eth) / 2.0,
                "both_markets_positive": btc > 0.0 and eth > 0.0,
            }
        )
    return output


def compute() -> dict[str, Any]:
    groups = grouped_effects()
    rng = random.Random(SEED)
    btc_draws: list[float] = []
    eth_draws: list[float] = []
    bilateral_draws: list[float] = []
    for _ in range(RESAMPLES):
        sample = [groups[rng.randrange(len(groups))] for _ in groups]
        btc_draws.append(statistics.median(item["btc_rho"] for item in sample))
        eth_draws.append(statistics.median(item["eth_rho"] for item in sample))
        bilateral_draws.append(
            statistics.median(item["bilateral_mean_rho"] for item in sample)
        )

    loo: list[dict[str, Any]] = []
    for omitted in groups:
        kept = [item for item in groups if item["group"] != omitted["group"]]
        loo.append(
            {
                "omitted_group": omitted["group"],
                "btc_median_rho": statistics.median(item["btc_rho"] for item in kept),
                "eth_median_rho": statistics.median(item["eth_rho"] for item in kept),
                "bilateral_median_rho": statistics.median(
                    item["bilateral_mean_rho"] for item in kept
                ),
            }
        )

    diagnostic_bilateral_positive = sum(
        item["btc"]["rho"] > 0.0 and item["eth"]["rho"] > 0.0
        for item in DIAGNOSTICS
    )
    positive_lower_bounds = sum(
        item[market]["ci95"][0] > 0.0
        for item in DIAGNOSTICS
        for market in ("btc", "eth")
    )
    grouped_bilateral_positive = sum(item["both_markets_positive"] for item in groups)
    btc_median = statistics.median(item["btc_rho"] for item in groups)
    eth_median = statistics.median(item["eth_rho"] for item in groups)
    bilateral_median = statistics.median(
        item["bilateral_mean_rho"] for item in groups
    )
    btc_ci = interval(btc_draws)
    eth_ci = interval(eth_draws)
    bilateral_ci = interval(bilateral_draws)
    sign_p = exact_upper_sign_p(grouped_bilateral_positive, len(groups))
    min_loo = min(item["bilateral_median_rho"] for item in loo)

    gates = {
        "btc_grouped_median_positive_with_positive_lower_bound": (
            btc_median > 0.0 and btc_ci[0] > 0.0
        ),
        "eth_grouped_median_positive_with_positive_lower_bound": (
            eth_median > 0.0 and eth_ci[0] > 0.0
        ),
        "bilateral_grouped_median_positive_with_positive_lower_bound": (
            bilateral_median > 0.0 and bilateral_ci[0] > 0.0
        ),
        "at_least_4_of_5_groups_bilateral_positive": grouped_bilateral_positive >= 4,
        "at_least_6_of_7_diagnostics_bilateral_positive": (
            diagnostic_bilateral_positive >= 6
        ),
        "at_least_7_of_14_source_lower_bounds_positive": positive_lower_bounds >= 7,
        "all_leave_one_group_out_bilateral_medians_positive": min_loo > 0.0,
        "one_sided_exact_sign_p_below_0_05": sign_p < 0.05,
    }
    verdict = VERDICT_SUPPORT if all(gates.values()) else VERDICT_REJECT

    return {
        "family_id": "scalar-state-family-closure-meta-analysis-1h-v1",
        "classification": "retrospective_architecture_family_closure",
        "research_parent": "5a0fcc97d1a882f8223656c51f5bb8055f534e38",
        "candidate_count": 0,
        "diagnostic_count": 1,
        "parameter_grid_count": 0,
        "new_market_performance_seen": False,
        "oos_accessed": False,
        "fee_one_way": FEE_ONE_WAY,
        "source_diagnostic_count": len(DIAGNOSTICS),
        "source_market_effect_count": 2 * len(DIAGNOSTICS),
        "source_diagnostics": list(DIAGNOSTICS),
        "family_groups": groups,
        "diagnostic_bilateral_positive_count": diagnostic_bilateral_positive,
        "diagnostic_bilateral_positive_fraction": (
            diagnostic_bilateral_positive / len(DIAGNOSTICS)
        ),
        "positive_source_lower_bound_count": positive_lower_bounds,
        "positive_source_lower_bound_fraction": (
            positive_lower_bounds / (2 * len(DIAGNOSTICS))
        ),
        "group_bilateral_positive_count": grouped_bilateral_positive,
        "group_bilateral_positive_fraction": grouped_bilateral_positive / len(groups),
        "grouped_point_estimates": {
            "btc_median_rho": btc_median,
            "eth_median_rho": eth_median,
            "bilateral_median_rho": bilateral_median,
        },
        "family_cluster_bootstrap": {
            "seed": SEED,
            "resamples": RESAMPLES,
            "unit": "paired_information_family_group",
            "btc_median_rho_ci95": btc_ci,
            "eth_median_rho_ci95": eth_ci,
            "bilateral_median_rho_ci95": bilateral_ci,
            "limitation": (
                "Between-family resampling preserves paired markets but cannot remove "
                "dependence from overlapping underlying market samples and targets."
            ),
        },
        "leave_one_group_out": loo,
        "minimum_leave_one_group_out_bilateral_median_rho": min_loo,
        "exact_one_sided_sign_test_p": sign_p,
        "gross_breadth": {
            "btc_positive_segments": sum(
                item["btc"]["positive_breadth"][0] for item in DIAGNOSTICS
            ),
            "btc_total_segments": sum(
                item["btc"]["positive_breadth"][1] for item in DIAGNOSTICS
            ),
            "eth_positive_segments": sum(
                item["eth"]["positive_breadth"][0] for item in DIAGNOSTICS
            ),
            "eth_total_segments": sum(
                item["eth"]["positive_breadth"][1] for item in DIAGNOSTICS
            ),
            "note": (
                "Descriptive only: source segment definitions differ between "
                "folds, years, and months, so no pooled significance is claimed."
            ),
        },
        "gates": gates,
        "gates_passed": sum(gates.values()),
        "gates_total": len(gates),
        "verdict": verdict,
        "strategy_metrics": {
            "train_return": None,
            "train_sharpe": None,
            "oos_return": None,
            "oos_sharpe": None,
            "full_return": None,
            "full_sharpe": None,
            "maximum_drawdown": None,
            "benchmark_comparison": None,
            "turnover": None,
            "edge_per_turnover": None,
            "reason": (
                "Candidate count is zero; this closure aggregates terminal "
                "information diagnostics rather than an executable equity curve."
            ),
        },
        "remaining_blocker": (
            "No tested single scalar state has replicated positive fee-aware "
            "forward-magnitude information across independent information groups."
        ),
        "next_experiment": (
            "One fixed Bayesian online change-point long/cash architecture retaining "
            "the full causal run-length posterior, with one predeclared turnover-aware "
            "decision rule and direct net-performance gates on a fresh immutable cohort."
        ),
    }


def render_report(evidence: dict[str, Any]) -> str:
    point = evidence["grouped_point_estimates"]
    bootstrap = evidence["family_cluster_bootstrap"]
    breadth = evidence["gross_breadth"]
    lines = [
        "# Scalar-state family closure meta-analysis",
        "",
        "```text",
        f"Family          {evidence['family_id']}",
        f"Candidate count {evidence['candidate_count']}",
        f"Diagnostics     {evidence['source_diagnostic_count']} source / 1 closure",
        f"Parameter grid  {evidence['parameter_grid_count']}",
        "Markets         BTC and ETH independently",
        "Bar             Immutable public 1H source evidence only",
        "Fee             Exactly 5 bps one way in every source contract",
        f"OOS accessed    {str(evidence['oos_accessed']).lower()}",
        f"Verdict         {evidence['verdict']}",
        "```",
        "",
        "## Included diagnostic effects",
        "",
        "| Source | Group | BTC rho [95% CI] | ETH rho [95% CI] | Both positive |",
        "|---|---|---:|---:|---:|",
    ]
    for item in evidence["source_diagnostics"]:
        b = item["btc"]
        e = item["eth"]
        lines.append(
            f"| #{item['issue']} {item['name']} | {item['group']} | "
            f"{b['rho']:+.4f} [{b['ci95'][0]:+.4f},{b['ci95'][1]:+.4f}] | "
            f"{e['rho']:+.4f} [{e['ci95'][0]:+.4f},{e['ci95'][1]:+.4f}] | "
            f"{'yes' if b['rho'] > 0 and e['rho'] > 0 else 'no'} |"
        )
    lines.extend(
        [
            "",
            "## Family-cluster result",
            "",
            "| Independent information group | BTC rho | ETH rho | Bilateral mean | Both positive |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for item in evidence["family_groups"]:
        lines.append(
            f"| {item['group']} | {item['btc_rho']:+.4f} | "
            f"{item['eth_rho']:+.4f} | {item['bilateral_mean_rho']:+.4f} | "
            f"{'yes' if item['both_markets_positive'] else 'no'} |"
        )
    lines.extend(
        [
            "",
            "```text",
            f"BTC grouped median rho        {point['btc_median_rho']:+.4f}",
            f"BTC family-bootstrap 95% CI   [{bootstrap['btc_median_rho_ci95'][0]:+.4f},{bootstrap['btc_median_rho_ci95'][1]:+.4f}]",
            f"ETH grouped median rho        {point['eth_median_rho']:+.4f}",
            f"ETH family-bootstrap 95% CI   [{bootstrap['eth_median_rho_ci95'][0]:+.4f},{bootstrap['eth_median_rho_ci95'][1]:+.4f}]",
            f"Bilateral grouped median      {point['bilateral_median_rho']:+.4f}",
            f"Bilateral bootstrap 95% CI    [{bootstrap['bilateral_median_rho_ci95'][0]:+.4f},{bootstrap['bilateral_median_rho_ci95'][1]:+.4f}]",
            f"Bilateral-positive groups      {evidence['group_bilateral_positive_count']}/5",
            f"Bilateral-positive diagnostics {evidence['diagnostic_bilateral_positive_count']}/7",
            f"Positive source lower bounds   {evidence['positive_source_lower_bound_count']}/14",
            f"Exact one-sided sign p         {evidence['exact_one_sided_sign_test_p']:.4f}",
            f"Minimum leave-one-group-out    {evidence['minimum_leave_one_group_out_bilateral_median_rho']:+.4f}",
            "```",
            "",
            "Every source interval lower bound is non-positive. Group clustering changes the "
            "unclustered positive median into a slightly negative bilateral median because the "
            "three related B1 geometry variants no longer receive triple weight.",
            "",
            "## Temporal breadth",
            "",
            f"Descriptive positive gross segments were {breadth['btc_positive_segments']}/"
            f"{breadth['btc_total_segments']} for BTC and {breadth['eth_positive_segments']}/"
            f"{breadth['eth_total_segments']} for ETH. Segment definitions differ across source "
            "experiments, so these counts are breadth diagnostics rather than a pooled test.",
            "",
            "## Gate verdict",
            "",
            "| Gate | Pass |",
            "|---|---:|",
        ]
    )
    for name, passed in evidence["gates"].items():
        lines.append(f"| `{name}` | {'yes' if passed else 'no'} |")
    lines.extend(
        [
            "",
            f"Only {evidence['gates_passed']}/{evidence['gates_total']} frozen gates passed. "
            f"Verdict: `{evidence['verdict']}`.",
            "",
            "## Strategy-performance fields",
            "",
            "No executable candidate was evaluated. Train, OOS and full return/Sharpe, maximum "
            "drawdown, benchmark residual, turnover and edge per turnover are therefore not "
            "computed. Source target-label turnover is not summed because horizons and label "
            "construction differ.",
            "",
            "## Limitation",
            "",
            bootstrap["limitation"]
            + " The analysis is retrospective closure evidence, not a new independent alpha test.",
            "",
            "## Disposition",
            "",
            "Further single-scalar gates, indicator renaming, family reweighting and same-sample "
            "threshold rescue are closed. The canonical strategy remains unchanged.",
            "",
            f"**Remaining blocker:** {evidence['remaining_blocker']}",
            "",
            f"**Next experiment:** {evidence['next_experiment']}",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    evidence = compute()
    evidence_text = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    report_text = render_report(evidence)
    (args.output_dir / "evidence.json").write_text(evidence_text, encoding="utf-8")
    (args.output_dir / "report.md").write_text(report_text, encoding="utf-8")


if __name__ == "__main__":
    main()
