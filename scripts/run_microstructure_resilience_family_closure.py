from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

FAMILY = "causal-microstructure-resilience-family-closure-1h-v1"
REJECT = "reject_causal_microstructure_resilience_family"
DIMENSIONS = (
    "source_executable",
    "positive_economics_or_information",
    "dependence_aware_support",
    "temporal_breadth",
    "replication_or_latency",
)


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate(source: dict[str, Any]) -> None:
    assert source["architecture_family_id"] == FAMILY
    assert source["frozen_at_main"] == "5a0fcc97d1a882f8223656c51f5bb8055f534e38"
    assert source["new_candidates"] == source["parameter_grid_count"] == 0
    assert source["new_oos_consumed"] == source["new_market_data_acquired"] == 0
    assert source["fee_one_way"] == 0.0005
    groups = source["groups"]
    assert [g["group_id"] for g in groups] == [
        "aggregate_taker_flow_residual",
        "individual_trade_flow_response_residual",
        "onset_aggressive_flow_absorption",
        "l2_bid_replenishment_resilience",
    ]
    for group in groups:
        assert set(group["dimension_votes"]) == set(DIMENSIONS)
        assert all(v in {"pass", "fail", "not_applicable"} for v in group["dimension_votes"].values())
        assert group["supportive"] is all(v != "fail" for v in group["dimension_votes"].values())
        assert group["terminal_verdict"] and group["failure_mechanisms"]

    by_id = {g["group_id"]: g for g in groups}
    assert by_id["aggregate_taker_flow_residual"]["metrics"] == {
        "candidate_market_evaluations": 0,
        "expected_rows": 720,
        "in_window_rows": 716,
        "performance_computed": False,
    }
    v2 = by_id["individual_trade_flow_response_residual"]["metrics"]
    assert v2["net_return"] == -0.6902880178320328
    assert v2["benchmark_net_return"] == 1.846613363294384
    assert v2["residual_sharpe_vs_trend"] == -2.4403088029779063
    onset = by_id["onset_aggressive_flow_absorption"]["metrics"]
    assert onset["mean_delta_95"][0] == onset["sharpe_delta_95"][0] == 0.0
    assert onset["largest_event_share"] > 0.5 and onset["price_only_shadow_identical"] is True
    l2 = by_id["l2_bid_replenishment_resilience"]["metrics"]
    assert l2["primary"]["ETH-USDT"]["net_rho"] < 0
    for market in ("BTC-USDT", "ETH-USDT"):
        for name in ("net_rho_95", "adverse_rho_95", "net_slope_95", "adverse_slope_95"):
            assert l2["primary"][market][name][0] <= 0
            assert l2["one_hour_delay"][market][name][0] <= 0


def build(source: dict[str, Any], source_sha: str) -> dict[str, Any]:
    groups = source["groups"]
    supportive = sum(g["supportive"] for g in groups)
    counts = {d: sum(g["dimension_votes"][d] == "pass" for g in groups) for d in DIMENSIONS}
    leave_one_out = [
        {
            "omitted_group": omitted["group_id"],
            "retained_supportive_groups": sum(g["supportive"] for g in groups if g is not omitted),
        }
        for omitted in groups
    ]
    v2 = next(g for g in groups if g["group_id"] == "individual_trade_flow_response_residual")["metrics"]
    onset = next(g for g in groups if g["group_id"] == "onset_aggressive_flow_absorption")["metrics"]
    gates = {
        "supportive_groups_at_least_3_of_4": supportive >= 3,
        "dependence_support_at_least_3_of_4": counts["dependence_aware_support"] >= 3,
        "temporal_breadth_at_least_3_of_4": counts["temporal_breadth"] >= 3,
        "replication_latency_at_least_3_of_4": counts["replication_or_latency"] >= 3,
        "no_material_negative_executable_evidence": not (
            v2["net_return"] - v2["benchmark_net_return"] < -0.25
            and v2["residual_sharpe_vs_trend"] < 0
        ),
        "all_leave_one_out_retain_two_supportive": all(x["retained_supportive_groups"] >= 2 for x in leave_one_out),
        "not_shadow_or_single_event_explained": not (
            onset["price_only_shadow_identical"] or onset["largest_event_share"] > 0.5
        ),
    }
    accepted = all(gates.values())
    return {
        "architecture_family_id": FAMILY,
        "classification": "completed-evidence architecture-family closure",
        "frozen_at_main": source["frozen_at_main"],
        "source_records_sha256": source_sha,
        "architecture_group_count": 4,
        "new_candidates": 0,
        "parameter_grid_count": 0,
        "new_oos_consumed": 0,
        "new_market_data_acquired": 0,
        "fee_one_way_where_executable": 0.0005,
        "group_audit": [
            {
                "group_id": g["group_id"],
                "family_id": g["family_id"],
                "source_issues": g["source_issues"],
                "terminal_verdict": g["terminal_verdict"],
                "markets_required": g["markets_required"],
                "markets_evaluated": g["markets_evaluated"],
                "dimension_votes": g["dimension_votes"],
                "supportive": g["supportive"],
                "failure_mechanisms": g["failure_mechanisms"],
            }
            for g in groups
        ],
        "dimension_pass_counts": counts,
        "supportive_group_count": supportive,
        "leave_one_group_out": leave_one_out,
        "family_gates": gates,
        "accepted": accepted,
        "verdict": "accept_causal_microstructure_resilience_family_for_one_fresh_replication" if accepted else REJECT,
        "closed_hypothesis_paths": [
            "aggregate taker-flow residuals",
            "individual-trade signed-flow persistence and linear flow/price residuals",
            "onset-only aggressive-flow absorption vetoes",
            "near-touch L2 bid-replenishment endpoints",
            "same-family threshold/window/smoothing/sign/nonlinear relabelling",
            "post-hoc market-subset rescue",
        ],
        "open_hypothesis_paths": [
            "materially different same-instrument temporal information architectures outside resilience/absorption"
        ],
        "no_recomputation_or_selection": True,
    }


def report(evidence: dict[str, Any], source: dict[str, Any]) -> str:
    groups = {g["group_id"]: g for g in source["groups"]}
    v2 = groups["individual_trade_flow_response_residual"]["metrics"]
    onset = groups["onset_aggressive_flow_absorption"]["metrics"]
    lines = [
        "# Causal microstructure-resilience family closure",
        "",
        f"Verdict: `{evidence['verdict']}`",
        "",
        "| Group | Source | Positive | Dependence | Breadth | Replication/latency | Supportive |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for g in evidence["group_audit"]:
        v = g["dimension_votes"]
        lines.append(f"| {g['group_id']} | {v['source_executable']} | {v['positive_economics_or_information']} | {v['dependence_aware_support']} | {v['temporal_breadth']} | {v['replication_or_latency']} | {'yes' if g['supportive'] else 'no'} |")
    lines += [
        "",
        f"Supportive groups: `{evidence['supportive_group_count']}/4`; dependence support: `{evidence['dimension_pass_counts']['dependence_aware_support']}/4`; breadth: `{evidence['dimension_pass_counts']['temporal_breadth']}/4`; replication/latency: `{evidence['dimension_pass_counts']['replication_or_latency']}/4`.",
        "",
        f"V2 BTC: net `{v2['net_return']:.4%}`, Sharpe `{v2['sharpe']:.4f}`, drawdown `{v2['max_drawdown']:.4%}`, turnover `{v2['turnover']:.4f}`, edge/turn `{v2['edge_per_turnover_bps']:.4f} bps`; trend benchmark net `{v2['benchmark_net_return']:.4%}`, Sharpe `{v2['benchmark_sharpe']:.4f}`.",
        f"Onset veto BTC OOS: net `{onset['oos']['candidate_net_return']:.4%}`, Sharpe `{onset['oos']['candidate_sharpe']:.4f}`, drawdown `{onset['oos']['candidate_max_drawdown']:.4%}`, turnover `{onset['oos']['candidate_turnover']:.0f}`, edge/turn `{onset['oos']['candidate_edge_per_turnover_bps']:.4f} bps`; both lower confidence bounds were zero, the price-only shadow was identical, and one event supplied `{onset['largest_event_share']:.2%}` of improvement.",
        "Aggregate flow failed source feasibility before performance. L2 replenishment had no executable candidate and failed bilateral uncertainty, breadth, monotonicity and one-hour-delay gates.",
        "",
        "No new performance, candidate, OOS interval, market data, filtering, parameter search, family reweighting or sign reversal occurred.",
        "The resilience/absorption family is closed; the next experiment must use a materially different causal temporal representation.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    a = p.parse_args()
    source_bytes = a.source.read_bytes()
    source = json.loads(source_bytes)
    validate(source)
    evidence = build(source, digest(source_bytes))
    a.output_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "source-records.json": source_bytes,
        "evidence.json": canonical(evidence),
        "report.md": report(evidence, source).encode(),
    }
    for name, data in files.items():
        (a.output_dir / name).write_bytes(data)
    sums = {name: digest(data) for name, data in files.items()}
    (a.output_dir / "sha256sums.json").write_bytes(canonical(sums))
    print(json.dumps({"verdict": evidence["verdict"], "sha256": sums}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
