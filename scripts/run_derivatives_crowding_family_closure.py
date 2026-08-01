from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

FAMILY = "causal-derivatives-crowding-information-family-closure-1h-v1"
REJECT = "reject_causal_derivatives_crowding_information_family"
MAIN_SHA = "5a0fcc97d1a882f8223656c51f5bb8055f534e38"
DIMENSIONS = (
    "source_complete_causal",
    "bilateral_absolute_fee_clearing",
    "bilateral_return_adverse_information",
    "dependence_aware_support",
    "temporal_breadth",
    "mechanism_or_latency",
)


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate(source: dict[str, Any]) -> None:
    assert source["architecture_family_id"] == FAMILY
    assert source["frozen_at_main"] == MAIN_SHA
    assert source["new_candidates"] == source["parameter_grid_count"] == 0
    assert source["new_oos_consumed"] == source["new_market_data_acquired"] == 0
    assert source["fee_one_way"] == 0.0005

    groups = source["groups"]
    assert [group["group_id"] for group in groups] == [
        "continuous_basis_compression_resilience",
        "settled_funding_positive_run_reset",
    ]

    for group in groups:
        votes = group["dimension_votes"]
        assert set(votes) == set(DIMENSIONS)
        assert all(vote in {"pass", "fail"} for vote in votes.values())
        assert group["supportive"] is all(vote == "pass" for vote in votes.values())
        assert group["candidate_count"] == 0
        assert group["diagnostic_count"] == 1
        assert group["markets_evaluated"] == group["markets_required"]
        assert group["terminal_verdict"]
        assert group["failure_mechanisms"]
        assert group["closed_rescue_paths"]

    by_id = {group["group_id"]: group for group in groups}
    basis = by_id["continuous_basis_compression_resilience"]
    funding = by_id["settled_funding_positive_run_reset"]

    assert basis["sample"]["verified_archive_checksum_pairs"] == 36
    assert basis["sample"]["decisions_per_market"] == 242
    assert basis["metrics"]["BTCUSDT"]["gross_rho"] == -0.0497
    assert basis["metrics"]["BTCUSDT"]["adverse_rho"] == -0.0731
    assert basis["metrics"]["ETHUSDT"]["gross_rho"] == 0.002
    assert basis["metrics"]["ETHUSDT"]["adverse_rho"] == -0.0171
    assert basis["metrics"]["BTCUSDT"]["mean_net_label"] == 0.001173
    assert basis["metrics"]["ETHUSDT"]["mean_net_label"] == 0.000193
    assert basis["metrics"]["common_calendar_median_market_gross_rho_95"][0] < 0
    assert basis["metrics"]["common_calendar_median_market_adverse_rho_95"][0] < 0

    assert funding["sample"]["funding_observations_per_market"] == 264
    assert funding["sample"]["confirmed_spot_rows_per_market"] == 2161
    assert funding["metrics"]["BTC-USDT"]["event_mean_net_24h"] == -0.00315561
    assert funding["metrics"]["ETH-USDT"]["event_mean_net_24h"] == -0.00005974
    assert funding["metrics"]["BTC-USDT"]["net_effect_95_bps"][0] < 0
    assert funding["metrics"]["ETH-USDT"]["net_effect_95_bps"][0] < 0
    assert funding["metrics"]["BTC-USDT"]["delayed_event_mean_net_24h"] < 0
    assert funding["metrics"]["ETH-USDT"]["delayed_event_mean_net_24h"] < 0


def build(source: dict[str, Any], source_sha256: str) -> dict[str, Any]:
    groups = source["groups"]
    supportive_group_count = sum(group["supportive"] for group in groups)
    dimension_pass_counts = {
        dimension: sum(
            group["dimension_votes"][dimension] == "pass" for group in groups
        )
        for dimension in DIMENSIONS
    }
    leave_one_group_out = [
        {
            "omitted_group": omitted["group_id"],
            "retained_supportive_groups": sum(
                group["supportive"] for group in groups if group is not omitted
            ),
        }
        for omitted in groups
    ]

    family_gates = {
        "at_least_one_fully_supportive_group": supportive_group_count >= 1,
        "supportive_group_is_bilateral_without_market_subset": any(
            group["supportive"]
            and group["markets_evaluated"] == group["markets_required"]
            for group in groups
        ),
        "supportive_group_has_positive_bilateral_dependence_bounds": any(
            group["supportive"]
            and group["dimension_votes"]["dependence_aware_support"] == "pass"
            for group in groups
        ),
        "supportive_group_clears_exact_fee_contract": any(
            group["supportive"]
            and group["dimension_votes"]["bilateral_absolute_fee_clearing"] == "pass"
            for group in groups
        ),
        "leave_one_group_out_not_isolated": all(
            row["retained_supportive_groups"] >= 1 for row in leave_one_group_out
        ),
    }
    accepted = all(family_gates.values())

    return {
        "architecture_family_id": FAMILY,
        "classification": "completed-evidence architecture-family closure",
        "frozen_at_main": source["frozen_at_main"],
        "source_records_sha256": source_sha256,
        "architecture_group_count": len(groups),
        "candidate_count": 0,
        "diagnostic_count": len(groups),
        "parameter_grid_count": 0,
        "new_oos_consumed": 0,
        "new_market_data_acquired": 0,
        "fee_one_way_in_source_economics": source["fee_one_way"],
        "group_audit": [
            {
                "group_id": group["group_id"],
                "family_id": group["family_id"],
                "source_issues": group["source_issues"],
                "terminal_verdict": group["terminal_verdict"],
                "markets_required": group["markets_required"],
                "markets_evaluated": group["markets_evaluated"],
                "dimension_votes": group["dimension_votes"],
                "supportive": group["supportive"],
                "failure_mechanisms": group["failure_mechanisms"],
            }
            for group in groups
        ],
        "dimension_pass_counts": dimension_pass_counts,
        "supportive_group_count": supportive_group_count,
        "leave_one_group_out": leave_one_group_out,
        "family_gates": family_gates,
        "accepted": accepted,
        "verdict": (
            "retain_causal_derivatives_crowding_information_family"
            if accepted
            else REJECT
        ),
        "executable_performance": {
            "available": False,
            "reason": (
                "Both frozen source groups are overlapping-label information "
                "diagnostics with candidate_count=0, so continuous train/OOS/full "
                "return, Sharpe, drawdown, benchmark equity comparison, executable "
                "turnover and edge-per-turnover are not defined."
            ),
        },
        "closed_hypothesis_paths": [
            "continuous basis-compression and spot-resilience scalar states",
            "basis weights, lookbacks, robust scales, thresholds, and contract rescue",
            "settled-funding positive-run reset length, sign, magnitude, and subset rescue",
            "alternate fee, horizon, delay, control, or funding-field rescue",
            "combining basis and funding after observing results",
            "post-hoc BTC-only or ETH-only promotion",
        ],
        "next_strategy_issue": 866,
        "next_strategy_family": (
            "causal-week-phase-deseasonalized-endpoint-trend-1h-v1"
        ),
        "no_recomputation_or_selection": True,
    }


def _vote(value: str) -> str:
    return "pass" if value == "pass" else "fail"


def report(evidence: dict[str, Any], source: dict[str, Any]) -> str:
    groups = {group["group_id"]: group for group in source["groups"]}
    basis = groups["continuous_basis_compression_resilience"]
    funding = groups["settled_funding_positive_run_reset"]
    b_btc = basis["metrics"]["BTCUSDT"]
    b_eth = basis["metrics"]["ETHUSDT"]
    f_btc = funding["metrics"]["BTC-USDT"]
    f_eth = funding["metrics"]["ETH-USDT"]

    lines = [
        "# Causal derivatives-crowding information family closure",
        "",
        f"Verdict: `{evidence['verdict']}`",
        "",
        (
            "| Group | Source/causal | Fee-clearing | Return/adverse | "
            "Dependence | Breadth | Mechanism/latency | Supportive |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for group in evidence["group_audit"]:
        votes = group["dimension_votes"]
        lines.append(
            f"| {group['group_id']} | {_vote(votes['source_complete_causal'])} | "
            f"{_vote(votes['bilateral_absolute_fee_clearing'])} | "
            f"{_vote(votes['bilateral_return_adverse_information'])} | "
            f"{_vote(votes['dependence_aware_support'])} | "
            f"{_vote(votes['temporal_breadth'])} | "
            f"{_vote(votes['mechanism_or_latency'])} | "
            f"{'yes' if group['supportive'] else 'no'} |"
        )

    counts = evidence["dimension_pass_counts"]
    lines += [
        "",
        (
            f"Supportive groups: `{evidence['supportive_group_count']}/2`; "
            f"bilateral fee-clearing: "
            f"`{counts['bilateral_absolute_fee_clearing']}/2`; "
            f"bilateral return/adverse information: "
            f"`{counts['bilateral_return_adverse_information']}/2`; "
            f"dependence support: `{counts['dependence_aware_support']}/2`; "
            f"breadth: `{counts['temporal_breadth']}/2`; "
            f"mechanism/latency: `{counts['mechanism_or_latency']}/2`."
        ),
        "",
        "## Continuous basis-compression/resilience state",
        "",
        (
            "BTC: gross rho "
            f"`{b_btc['gross_rho']:+.4f}` "
            f"`[{b_btc['gross_rho_95'][0]:+.4f},"
            f"{b_btc['gross_rho_95'][1]:+.4f}]`; adverse rho "
            f"`{b_btc['adverse_rho']:+.4f}` "
            f"`[{b_btc['adverse_rho_95'][0]:+.4f},"
            f"{b_btc['adverse_rho_95'][1]:+.4f}]`; "
            f"mean independent-label net `{b_btc['mean_net_label']:.4%}`."
        ),
        (
            "ETH: gross rho "
            f"`{b_eth['gross_rho']:+.4f}` "
            f"`[{b_eth['gross_rho_95'][0]:+.4f},"
            f"{b_eth['gross_rho_95'][1]:+.4f}]`; adverse rho "
            f"`{b_eth['adverse_rho']:+.4f}` "
            f"`[{b_eth['adverse_rho_95'][0]:+.4f},"
            f"{b_eth['adverse_rho_95'][1]:+.4f}]`; "
            f"mean independent-label net `{b_eth['mean_net_label']:.4%}`."
        ),
        (
            "The state failed monotonicity: ascending-state gross-return quintiles "
            "were hump-shaped in both markets. Common-calendar lower bounds for "
            "median-market gross and adverse rho were negative."
        ),
        "",
        "## Settled-funding positive-run reset",
        "",
        (
            "BTC event mean gross/net: "
            f"`{f_btc['event_mean_gross_24h']:.4%}` / "
            f"`{f_btc['event_mean_net_24h']:.4%}`; "
            f"event-minus-control net `{f_btc['event_minus_control_net_bps']:+.4f} bp`; "
            "95% interval "
            f"`[{f_btc['net_effect_95_bps'][0]:+.4f},"
            f"{f_btc['net_effect_95_bps'][1]:+.4f}] bp`."
        ),
        (
            "ETH event mean gross/net: "
            f"`{f_eth['event_mean_gross_24h']:.4%}` / "
            f"`{f_eth['event_mean_net_24h']:.4%}`; "
            f"event-minus-control net `{f_eth['event_minus_control_net_bps']:+.4f} bp`; "
            "95% interval "
            f"`[{f_eth['net_effect_95_bps'][0]:+.4f},"
            f"{f_eth['net_effect_95_bps'][1]:+.4f}] bp`."
        ),
        (
            "Both additional-one-hour event mean net returns remained negative: "
            f"BTC `{f_btc['delayed_event_mean_net_24h']:.4%}`, "
            f"ETH `{f_eth['delayed_event_mean_net_24h']:.4%}`."
        ),
        "",
        "## Executable strategy fields",
        "",
        (
            "Candidate count is zero in both source groups. The labels overlap and "
            "do not define a continuous equity path, so train/OOS/full compounded "
            "return, Sharpe, maximum drawdown, benchmark equity residual, executable "
            "turnover and edge per turnover are intentionally not computed."
        ),
        "",
        (
            "No new candidate, market data, OOS observation, parameter, market "
            "filter, sign reversal, metric recomputation or source reweighting "
            "entered this closure."
        ),
        (
            "The derivatives-crowding channel is closed. The next active experiment "
            "is issue #866, a materially different own-history week-phase "
            "deseasonalized endpoint-trend representation."
        ),
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    source_bytes = args.source.read_bytes()
    source = json.loads(source_bytes)
    validate(source)
    evidence = build(source, digest(source_bytes))

    args.output_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "source-records.json": source_bytes,
        "evidence.json": canonical(evidence),
        "report.md": report(evidence, source).encode(),
    }
    for name, data in files.items():
        (args.output_dir / name).write_bytes(data)

    sha256sums = {name: digest(data) for name, data in files.items()}
    (args.output_dir / "sha256sums.json").write_bytes(canonical(sha256sums))
    print(
        json.dumps(
            {"verdict": evidence["verdict"], "sha256": sha256sums},
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
