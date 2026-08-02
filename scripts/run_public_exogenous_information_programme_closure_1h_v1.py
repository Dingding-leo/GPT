#!/usr/bin/env python3
"""Close completed public-exogenous 1H mechanisms from immutable evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

FAMILY_ID = "causal-public-exogenous-information-programme-closure-1h-v1"
VERDICT = (
    "reject_reopening_completed_public_exogenous_information_mechanisms_1h_v1"
)
MAIN_HEAD = "5a0fcc97d1a882f8223656c51f5bb8055f534e38"
BAR = "1H"
ONE_WAY_FEE_BPS = 5.0
RECORDS_PATH = Path(__file__).with_name(
    "public_exogenous_information_programme_closure_1h_v1_records.json"
)


def canonical_bytes(value: Any) -> bytes:
    text = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return f"{text}\n".encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def write_json(path: Path, value: Any) -> str:
    payload = canonical_bytes(value)
    path.write_bytes(payload)
    return sha256_bytes(payload)


def write_text(path: Path, value: str) -> str:
    payload = value.encode()
    path.write_bytes(payload)
    return sha256_bytes(payload)


def load_groups() -> list[dict[str, Any]]:
    records = json.loads(RECORDS_PATH.read_text())
    groups = records["groups"]
    if [group["group_id"] for group in groups] != list("ABCDEFGH"):
        raise SystemExit("unexpected evidence-group identity or order")
    return groups


def build_leave_one_out(
    groups: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for omitted in [group["group_id"] for group in groups]:
        retained = [group for group in groups if group["group_id"] != omitted]
        benchmark_support = sum(
            bool(group["bilateral_benchmark_relative_support"])
            for group in retained
        )
        dependence_support = sum(
            bool(group["bilateral_dependence_support"])
            for group in retained
        )
        rows.append(
            {
                "omitted_group": omitted,
                "retained_groups": [group["group_id"] for group in retained],
                "bilateral_benchmark_relative_support_groups": (
                    benchmark_support
                ),
                "bilateral_dependence_support_groups": dependence_support,
                "supportive": bool(benchmark_support or dependence_support),
            }
        )
    return rows


def build_summary(
    groups: list[dict[str, Any]],
    leave_one_out: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "architecture_groups": len(groups),
        "direct_source_feasible_groups": sum(
            bool(group["source_contract"]["direct_public_1h_feasible"])
            for group in groups
        ),
        "source_blocked_groups": sum(
            not bool(group["source_contract"]["direct_public_1h_feasible"])
            for group in groups
        ),
        "adjudicated_groups": sum(
            bool(group["reached_temporal_or_economic_adjudication"])
            for group in groups
        ),
        "executable_economics_groups": sum(
            bool(group["executable_economics_accessed"])
            for group in groups
        ),
        "bilateral_benchmark_relative_support_groups": sum(
            bool(group["bilateral_benchmark_relative_support"])
            for group in groups
        ),
        "bilateral_dependence_support_groups": sum(
            bool(group["bilateral_dependence_support"])
            for group in groups
        ),
        "bilateral_breadth_and_delay_support_groups": sum(
            bool(group["bilateral_breadth_and_delay_support"])
            for group in groups
        ),
        "supportive_leave_one_out_subsets": sum(
            bool(row["supportive"]) for row in leave_one_out
        ),
        "candidate_count": 0,
        "bound_historical_candidate_paths": sum(
            int(group["candidate_count"]) for group in groups
        ),
        "parameter_grid_count": 0,
        "new_market_data": 0,
        "new_target_returns": 0,
        "new_oos_consumed": 0,
        "performance_accessed_in_closure": False,
        "oos_accessed_in_closure": False,
    }


def build_gates(
    groups: list[dict[str, Any]],
    summary: dict[str, Any],
) -> dict[str, bool]:
    source_only_nonvoting = all(
        group["source_contract"]["direct_public_1h_feasible"]
        or not group["executable_economics_accessed"]
        for group in groups
    )
    return {
        "all_eight_terminal_identity_records_bound": (
            len(groups) == 8
            and all(group["terminal_identity"] for group in groups)
            and all(not group["pr_merged"] for group in groups)
        ),
        "causal_1h_and_exact_5bps_boundary_preserved": (
            BAR == "1H"
            and ONE_WAY_FEE_BPS == 5.0
            and all(group["parameter_grid_count"] == 0 for group in groups)
        ),
        "at_least_three_direct_source_feasible_groups": (
            summary["direct_source_feasible_groups"] >= 3
        ),
        "at_least_two_source_feasible_groups_adjudicated": (
            summary["adjudicated_groups"] >= 2
        ),
        "zero_bilateral_benchmark_relative_support_groups": (
            summary["bilateral_benchmark_relative_support_groups"] == 0
        ),
        "zero_bilateral_dependence_support_groups": (
            summary["bilateral_dependence_support_groups"] == 0
        ),
        "zero_bilateral_breadth_and_delay_support_groups": (
            summary["bilateral_breadth_and_delay_support_groups"] == 0
        ),
        "source_only_results_economically_nonvoting": source_only_nonvoting,
        "leave_one_group_out_zero_support": (
            summary["supportive_leave_one_out_subsets"] == 0
        ),
        "closure_scope_limited_to_exact_consumed_mechanisms": True,
    }


def build_report(evidence: dict[str, Any]) -> str:
    summary = evidence["summary"]
    lines = [
        "# Completed Public-Exogenous Information Programme Closure — 1H V1",
        "",
        "## Verdict",
        "",
        f"`{evidence['verdict']}`",
        "",
        (
            "The completed record supports closing the exact eight consumed "
            "public-exogenous mechanisms against renamed provider, tenor, "
            "threshold, venue and transform rescue. It does not claim that "
            "every possible exogenous signal is uninformative."
        ),
        "",
        "## Frozen scope",
        "",
        f"- Tested head: `{evidence['tested_head']}`",
        f"- Canonical main: `{evidence['canonical_main_head']}`",
        f"- Bar: `{evidence['bar']}`",
        (
            "- Modeled fee: exactly "
            f"`{evidence['one_way_fee_bps']:.1f}` bps one way whenever "
            "economics existed"
        ),
        f"- Architecture groups: `{summary['architecture_groups']}`",
        "- Closure candidate count and parameter grid: `0` and `0`",
        "- New market data, returns and OOS observations: `0`",
        "",
        "## Closure scorecard",
        "",
        "| Quantity | Count |",
        "|---|---:|",
        (
            "| Direct-source-feasible groups | "
            f"{summary['direct_source_feasible_groups']}/"
            f"{summary['architecture_groups']} |"
        ),
        (
            "| Source-feasible groups reaching adjudication | "
            f"{summary['adjudicated_groups']}/"
            f"{summary['architecture_groups']} |"
        ),
        (
            "| Groups with executable strategy economics | "
            f"{summary['executable_economics_groups']}/"
            f"{summary['architecture_groups']} |"
        ),
        (
            "| Bilateral benchmark-relative support | "
            f"{summary['bilateral_benchmark_relative_support_groups']}/"
            f"{summary['architecture_groups']} |"
        ),
        (
            "| Bilateral dependence support | "
            f"{summary['bilateral_dependence_support_groups']}/"
            f"{summary['architecture_groups']} |"
        ),
        (
            "| Bilateral breadth plus delay support | "
            f"{summary['bilateral_breadth_and_delay_support_groups']}/"
            f"{summary['architecture_groups']} |"
        ),
        (
            "| Supportive leave-one-group-out subsets | "
            f"{summary['supportive_leave_one_out_subsets']}/"
            f"{summary['architecture_groups']} |"
        ),
        "",
        "## Group matrix",
        "",
        (
            "| Group | Mechanism | Source | Adjudication | Economics | "
            "Terminal result |"
        ),
        "|---|---|---|---|---|---|",
    ]
    for group in evidence["groups"]:
        source = (
            "pass"
            if group["source_contract"]["direct_public_1h_feasible"]
            else "fail"
        )
        adjudication = (
            "yes"
            if group["reached_temporal_or_economic_adjudication"]
            else "no"
        )
        economics = "yes" if group["executable_economics_accessed"] else "no"
        lines.append(
            f"| {group['group_id']} | {group['mechanism']} | {source} | "
            f"{adjudication} | {economics} | "
            f"`{group['terminal_verdict']}` |"
        )
    lines.extend(
        [
            "",
            "## Only executable economics",
            "",
            (
                "The aggregate-DVOL group was the only group that created a "
                "continuous candidate equity curve. On training, BTC candidate "
                "net return/Sharpe were -16.17597%/-0.10508 versus E2160 "
                "-0.81324%/+0.17080; ETH candidate net return/Sharpe were "
                "-15.50842%/-0.01531 versus E2160 -26.68357%/-0.05199. "
                "Candidate edge per turnover was negative in both markets. "
                "OOS and full economics stayed sealed."
            ),
            "",
            "## Independent information failures",
            "",
            (
                "Stablecoin dislocation passed source acquisition but its "
                "entry changes were concentrated in two quarters: the largest "
                "quarter supplied 72.7273% of BTC vetoes and 86.3636% of ETH "
                "vetoes. Mark/index source feasibility likewise did not repair "
                "the prior basis diagnostic: every dependence interval crossed "
                "zero and the derivatives-crowding closure had zero supportive "
                "groups."
            ),
            "",
            "## Source-blocked mechanisms",
            "",
            (
                "Options skew, on-chain fees, forward/realised IV, venue "
                "fragmentation and direct options term structure failed their "
                "exact anonymous immutable 1H source contracts. Their economic "
                "fields remain null rather than zero."
            ),
            "",
            "## Leave-one-group-out robustness",
            "",
            (
                "Removing any one evidence group leaves zero bilateral "
                "benchmark-relative groups and zero bilateral "
                "dependence-supported groups. Source-only passes remain "
                "economically non-voting in every subset."
            ),
            "",
            "## Canonical disposition",
            "",
            (
                "No canonical strategy mutation, paper-trading authority or "
                "live-trading authority is created. The evidence branch is "
                "intended to close without merge."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tested-head", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    if len(args.tested_head) != 40 or any(
        character not in "0123456789abcdef" for character in args.tested_head
    ):
        raise SystemExit("tested head must be a lowercase 40-character git SHA")

    groups = load_groups()
    leave_one_out = build_leave_one_out(groups)
    summary = build_summary(groups, leave_one_out)
    gates = build_gates(groups, summary)
    failed_gates = [name for name, passed in gates.items() if not passed]
    if failed_gates:
        raise SystemExit(f"closure gates failed: {failed_gates}")

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    source_records = {
        "family_id": FAMILY_ID,
        "canonical_main_head": MAIN_HEAD,
        "tested_head": args.tested_head,
        "groups": groups,
    }
    source_records_sha = write_json(
        output_dir / "source_records.json",
        source_records,
    )
    write_text(
        output_dir / "source_records.sha256",
        f"{source_records_sha}  source_records.json\n",
    )

    evidence = {
        "family_id": FAMILY_ID,
        "classification": "completed-evidence architecture closure",
        "canonical_main_head": MAIN_HEAD,
        "tested_head": args.tested_head,
        "bar": BAR,
        "one_way_fee_bps": ONE_WAY_FEE_BPS,
        "hard_boundary": {
            "same_instrument_future_long_cash": True,
            "cross_sectional_ranking": False,
            "pairs_or_spreads": False,
            "cointegration_or_statistical_arbitrage": False,
            "market_neutral_or_long_short": False,
            "post_hoc_asset_filtering": False,
            "credentials_or_private_endpoints": False,
            "accounts_orders_or_leverage": False,
            "synthetic_data": False,
            "non_1h_or_15m": False,
        },
        "summary": summary,
        "groups": groups,
        "leave_one_group_out": leave_one_out,
        "gates": gates,
        "closed_rescue_surface": [
            "alternate providers or endpoints for the same eight objects",
            "alternate tenors lags windows thresholds signs scales or norms",
            "alternate E2160 veto or reauthorisation rules",
            "option-chain reconstruction represented as a direct source",
            "venue quote-currency or panel substitution after inspection",
            "single-market promotion or favourable-quarter deletion",
            "repaired rows shorter calendars or source-as-alpha claims",
        ],
        "scope_limit": (
            "This verdict closes only the exact completed mechanisms and "
            "rescue surfaces; it does not claim every possible exogenous "
            "signal is impossible."
        ),
        "canonical_mutation": False,
        "paper_trading_authority": False,
        "live_trading_authority": False,
        "verdict": VERDICT,
        "source_records_sha256": source_records_sha,
    }

    evidence_sha = write_json(output_dir / "evidence.json", evidence)
    write_text(
        output_dir / "evidence.sha256",
        f"{evidence_sha}  evidence.json\n",
    )
    report_sha = write_text(
        output_dir / "report.md",
        build_report(evidence),
    )
    write_text(
        output_dir / "report.sha256",
        f"{report_sha}  report.md\n",
    )

    print(
        json.dumps(
            {
                "verdict": VERDICT,
                "evidence_sha256": evidence_sha,
                "source_records_sha256": source_records_sha,
                "report_sha256": report_sha,
                "summary": summary,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
