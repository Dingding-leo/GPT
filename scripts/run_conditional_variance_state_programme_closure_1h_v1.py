#!/usr/bin/env python3
"""Close completed conditional-variance-state mechanisms from immutable evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

FAMILY_ID = "causal-own-price-conditional-variance-state-programme-closure-1h-v1"
VERDICT = "reject_reopening_completed_conditional_variance_state_mechanisms_1h_v1"
MAIN_HEAD = "5a0fcc97d1a882f8223656c51f5bb8055f534e38"
BAR = "1H"
ONE_WAY_FEE_BPS = 5.0
RECORDS_PATH = Path(__file__).with_name(
    "conditional_variance_state_programme_closure_1h_v1_records.json"
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
    if records["family_id"] != FAMILY_ID:
        raise SystemExit("unexpected closure family identity")
    if records["canonical_main_head"] != MAIN_HEAD:
        raise SystemExit("unexpected canonical main identity")
    groups = records["groups"]
    if [group["group_id"] for group in groups] != list("ABCDEFGH"):
        raise SystemExit("unexpected evidence-group identity or order")
    return groups


def group_supportive(group: dict[str, Any]) -> bool:
    return all(
        (
            group["bilateral_benchmark_support"],
            group["bilateral_adverse_or_drawdown_support"],
            group["bilateral_dependence_support"],
            group["bilateral_breadth_and_delay_support"],
        )
    )


def build_leave_one_out(
    groups: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for omitted in [group["group_id"] for group in groups]:
        retained = [group for group in groups if group["group_id"] != omitted]
        supportive_groups = [
            group["group_id"] for group in retained if group_supportive(group)
        ]
        rows.append(
            {
                "omitted_group": omitted,
                "retained_groups": [group["group_id"] for group in retained],
                "supportive_groups": supportive_groups,
                "supportive": bool(supportive_groups),
            }
        )
    return rows


def build_summary(
    groups: list[dict[str, Any]],
    leave_one_out: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "bound_groups": len(groups),
        "source_feasible_groups": sum(
            bool(group["source_contract"]["direct_public_1h_feasible"])
            for group in groups
        ),
        "executable_economics_groups": sum(
            bool(group["executable_economics"]) for group in groups
        ),
        "bilateral_benchmark_supported_groups": sum(
            bool(group["bilateral_benchmark_support"]) for group in groups
        ),
        "bilateral_adverse_or_drawdown_supported_groups": sum(
            bool(group["bilateral_adverse_or_drawdown_support"])
            for group in groups
        ),
        "bilateral_dependence_supported_groups": sum(
            bool(group["bilateral_dependence_support"]) for group in groups
        ),
        "bilateral_breadth_and_delay_supported_groups": sum(
            bool(group["bilateral_breadth_and_delay_support"])
            for group in groups
        ),
        "supportive_groups": sum(group_supportive(group) for group in groups),
        "supportive_leave_one_out_subsets": sum(
            bool(row["supportive"]) for row in leave_one_out
        ),
        "closure_candidate_count": 0,
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
    terminal_identities_bound = all(
        family["terminal_verdict"]
        and family["issues"]
        and family["target_arms"]
        for group in groups
        for family in group["families"]
    )
    exact_fee_boundary = all(
        group["source_contract"].get("exactly_5bps_one_way", False)
        or group["source_contract"].get(
            "exactly_5bps_one_way_in_labels",
            False,
        )
        for group in groups
    )
    return {
        "all_eight_group_identities_bound": (
            len(groups) == 8
            and [group["group_id"] for group in groups] == list("ABCDEFGH")
        ),
        "all_terminal_family_records_bound": terminal_identities_bound,
        "causal_1h_and_exact_5bps_boundary_preserved": (
            BAR == "1H" and ONE_WAY_FEE_BPS == 5.0 and exact_fee_boundary
        ),
        "all_source_contracts_feasible": (
            summary["source_feasible_groups"] == summary["bound_groups"]
        ),
        "zero_bilateral_benchmark_supported_groups": (
            summary["bilateral_benchmark_supported_groups"] == 0
        ),
        "zero_bilateral_adverse_or_drawdown_supported_groups": (
            summary["bilateral_adverse_or_drawdown_supported_groups"] == 0
        ),
        "zero_bilateral_dependence_supported_groups": (
            summary["bilateral_dependence_supported_groups"] == 0
        ),
        "zero_bilateral_breadth_and_delay_supported_groups": (
            summary["bilateral_breadth_and_delay_supported_groups"] == 0
        ),
        "zero_supportive_groups": summary["supportive_groups"] == 0,
        "leave_one_group_out_zero_support": (
            summary["supportive_leave_one_out_subsets"] == 0
        ),
        "closure_scope_limited_to_consumed_mechanisms": True,
    }


def strongest_single_market_result(
    groups: list[dict[str, Any]],
) -> str:
    group = next(group for group in groups if group["group_id"] == "G")
    return str(group["strongest_single_market_result"])


def build_report(evidence: dict[str, Any]) -> str:
    summary = evidence["summary"]
    lines = [
        "# Conditional-Variance State Programme Closure — 1H V1",
        "",
        "## Verdict",
        "",
        f"`{evidence['verdict']}`",
        "",
        (
            "No completed conditional-variance-state group satisfies the frozen "
            "bilateral support definition. Reopening the consumed mechanism "
            "through another window, estimator, threshold, sizing wrapper, "
            "cadence rule, sign reversal, or single-market promotion is rejected."
        ),
        "",
        "## Frozen scope",
        "",
        f"- Tested head: `{evidence['tested_head']}`",
        f"- Canonical main: `{evidence['canonical_main_head']}`",
        f"- Bar: `{evidence['bar']}`",
        (
            "- Modeled fee: exactly "
            f"`{evidence['one_way_fee_bps']:.1f}` bps one way wherever "
            "economic labels or positions existed"
        ),
        f"- Bound groups: `{summary['bound_groups']}`",
        "- Closure candidate count and parameter grid: `0` and `0`",
        "- New market data, target returns, and OOS observations: `0`",
        "",
        "## Closure scorecard",
        "",
        "| Quantity | Count |",
        "|---|---:|",
        (
            "| Source-feasible groups | "
            f"{summary['source_feasible_groups']}/{summary['bound_groups']} |"
        ),
        (
            "| Groups with executable economics | "
            f"{summary['executable_economics_groups']}/"
            f"{summary['bound_groups']} |"
        ),
        (
            "| Bilateral benchmark-supported groups | "
            f"{summary['bilateral_benchmark_supported_groups']}/"
            f"{summary['bound_groups']} |"
        ),
        (
            "| Bilateral adverse/drawdown-supported groups | "
            f"{summary['bilateral_adverse_or_drawdown_supported_groups']}/"
            f"{summary['bound_groups']} |"
        ),
        (
            "| Bilateral dependence-supported groups | "
            f"{summary['bilateral_dependence_supported_groups']}/"
            f"{summary['bound_groups']} |"
        ),
        (
            "| Bilateral breadth-plus-delay-supported groups | "
            f"{summary['bilateral_breadth_and_delay_supported_groups']}/"
            f"{summary['bound_groups']} |"
        ),
        (
            "| Supportive leave-one-group-out subsets | "
            f"{summary['supportive_leave_one_out_subsets']}/"
            f"{summary['bound_groups']} |"
        ),
        "",
        "## Evidence-group matrix",
        "",
        (
            "| Group | Mechanism | Source | Economics | Benchmark | "
            "Risk | Dependence | Breadth/delay |"
        ),
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for group in evidence["groups"]:
        source = (
            "pass"
            if group["source_contract"]["direct_public_1h_feasible"]
            else "fail"
        )
        economics = "yes" if group["executable_economics"] else "diagnostic"
        benchmark = "pass" if group["bilateral_benchmark_support"] else "fail"
        risk = (
            "pass"
            if group["bilateral_adverse_or_drawdown_support"]
            else "fail"
        )
        dependence = (
            "pass" if group["bilateral_dependence_support"] else "fail"
        )
        breadth = (
            "pass"
            if group["bilateral_breadth_and_delay_support"]
            else "fail"
        )
        lines.append(
            f"| {group['group_id']} | {group['mechanism']} | {source} | "
            f"{economics} | {benchmark} | {risk} | {dependence} | "
            f"{breadth} |"
        )

    lines.extend(
        [
            "",
            "## Strongest apparently favourable single-market result",
            "",
            evidence["strongest_single_market_result"],
            "",
            (
                "That ETH point result cannot be promoted: every frozen "
                "dependence-aware lower bound remained below zero, BTC failed "
                "the intended adverse-excursion mechanism, and the protocol "
                "required bilateral support."
            ),
            "",
            "## Representative executable failures",
            "",
            (
                "- Volatility compression/acceleration: BTC returned +22.47% "
                "OOS versus +120.22% for daily E2160; ETH returned -31.16% "
                "versus +74.52%. Both paired lower bounds were negative."
            ),
            (
                "- Downside-semivariance persistence: ETH improved point return "
                "and drawdown, but its mean-delta interval was "
                "[-17.84%, +18.09%], its Sharpe-delta interval was "
                "[-0.171, +0.550], and edge per turnover remained below E2160."
            ),
            (
                "- Variance-ratio risk state: candidate return remained below "
                "E2160 in both markets, turnover increased, breadth was only "
                "5/12 and 6/12 folds, and strict dependence gates failed."
            ),
            (
                "- Bipower jump concentration: both targets underperformed "
                "E2160, raised turnover, and had negative uncertainty lower "
                "bounds."
            ),
            (
                "- Volatility-state expert switching: annualized turnover rose "
                "to 144.12 in BTC and 174.21 in ETH; BTC remained below the "
                "simple trend and ETH failed replication."
            ),
            "",
            "## Leave-one-group-out adjudication",
            "",
            (
                "Removing any one group leaves zero supportive groups. The "
                "terminal closure therefore does not depend on a single "
                "negative family or one market sleeve."
            ),
            "",
            "## Strategy-performance access",
            "",
            (
                "Groups F and G were zero-candidate training-information "
                "diagnostics. Their training/OOS/full strategy return, Sharpe, "
                "turnover, fee drag, drawdown, edge per turnover, and year "
                "breadth remain null rather than zero. Their sealed OOS was "
                "not accessed."
            ),
            "",
            "## Canonical disposition",
            "",
            (
                "No canonical mutation, paper-trading authority, or live-trading "
                "authority is created. The evidence branch must close without "
                "merge after exact-head publication."
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
        character not in "0123456789abcdef"
        for character in args.tested_head
    ):
        raise SystemExit(
            "tested head must be a lowercase 40-character git SHA"
        )

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
        "classification": "completed-evidence strategy-family closure",
        "canonical_main_head": MAIN_HEAD,
        "tested_head": args.tested_head,
        "bar": BAR,
        "one_way_fee_bps": ONE_WAY_FEE_BPS,
        "hard_boundary": {
            "same_instrument_future_long_cash": True,
            "cross_sectional_ranking_or_selection": False,
            "pairs_spreads_cointegration_or_stat_arb": False,
            "market_neutral_or_long_short": False,
            "post_hoc_asset_filtering": False,
            "credentials_private_endpoints_accounts_or_orders": False,
            "leverage": False,
            "synthetic_data": False,
            "non_1h_or_15m": False,
        },
        "summary": summary,
        "groups": groups,
        "leave_one_group_out": leave_one_out,
        "gates": gates,
        "strongest_single_market_result": strongest_single_market_result(
            groups
        ),
        "closed_rescue_surface": [
            "alternative rolling windows lags smoothing scaling or clipping",
            "squared versus absolute returns or rank versus Pearson correlation",
            "alternate realized-volatility semivariance or jump estimators",
            "threshold quantile veto sizing cadence or expert-switch wrappers",
            "sign reversal favourable-period deletion or target replacement",
            "single-market promotion or positive-point-estimate promotion",
        ],
        "scope_limit": (
            "This verdict closes the exact completed conditional-variance-state "
            "mechanisms. It does not assert that all possible risk information "
            "is uninformative."
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
