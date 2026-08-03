#!/usr/bin/env python3
"""Close completed own-price jump/discontinuity mechanisms from immutable records."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

FAMILY_ID = "causal-own-price-jump-discontinuity-programme-closure-1h-v1"
VERDICT = "reject_reopening_completed_own_price_jump_discontinuity_mechanisms_1h_v1"
MAIN_HEAD = "5a0fcc97d1a882f8223656c51f5bb8055f534e38"
BAR = "1H"
FEE_BPS_ONE_WAY = 5.0
RECORDS_PATH = Path(__file__).with_name(
    "jump_discontinuity_programme_closure_1h_v1_records.json"
)


def canonical_bytes(value: Any) -> bytes:
    text = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return f"{text}\n".encode()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def write_json(path: Path, value: Any) -> str:
    payload = canonical_bytes(value)
    path.write_bytes(payload)
    return sha256_bytes(payload)


def write_text(path: Path, value: str) -> str:
    payload = value.encode()
    path.write_bytes(payload)
    return sha256_bytes(payload)


def load_records() -> dict[str, Any]:
    records = json.loads(RECORDS_PATH.read_text())
    if records["family_id"] != FAMILY_ID:
        raise SystemExit("unexpected family identity")
    if records["canonical_main_head"] != MAIN_HEAD:
        raise SystemExit("unexpected canonical main identity")
    if [group["group_id"] for group in records["groups"]] != ["A", "B"]:
        raise SystemExit("unexpected evidence-group identity or order")
    return records


def validate_records(records: dict[str, Any]) -> None:
    group_a, group_b = records["groups"]
    if sum(int(group["candidate_count"]) for group in records["groups"]) != 1:
        raise SystemExit("historical candidate accounting changed")
    if any(group["fee_bps_one_way"] != FEE_BPS_ONE_WAY for group in records["groups"]):
        raise SystemExit("fee boundary changed")
    if any(group["admissible"] for group in records["groups"]):
        raise SystemExit("a rejected group was marked admissible")
    for target in ("BTC-USDT", "ETH-USDT"):
        train = group_a["training"][target]
        row = group_a["oos"][target]
        if train["net_return_pct"] >= 0 or train["sharpe"] >= 0:
            raise SystemExit(f"{target} training failure changed")
        if row["candidate"]["net_return_pct"] >= row["benchmark"]["net_return_pct"]:
            raise SystemExit(f"{target} return ordering changed")
        if row["candidate"]["sharpe"] >= row["benchmark"]["sharpe"]:
            raise SystemExit(f"{target} Sharpe ordering changed")
        if row["candidate"]["turnover"] <= row["benchmark"]["turnover"]:
            raise SystemExit(f"{target} turnover ordering changed")
        if row["candidate"]["edge_per_turnover_bps"] >= row["benchmark"][
            "edge_per_turnover_bps"
        ]:
            raise SystemExit(f"{target} edge-per-turnover ordering changed")
        if row["mean_delta_ci_pct"][0] >= 0 or row["sharpe_delta_ci"][0] >= 0:
            raise SystemExit(f"{target} uncertainty failure changed")
    near = group_b["targets"]["NEAR-USDT"]
    apt = group_b["targets"]["APT-USDT"]
    if near["net_tercile_effect_bps"] >= 0 or near["delayed_net_tercile_effect_bps"] >= 0:
        raise SystemExit("NEAR continuation contradiction changed")
    if apt["valid_opportunities"] >= 180:
        raise SystemExit("APT support failure changed")
    for target in group_b["target_arms"]:
        lowers = group_b["targets"][target]["bootstrap_lower_95"]
        if any(float(value) >= 0 for value in lowers.values()):
            raise SystemExit(f"{target} dependence failure changed")
    if records["prior_programme_closure"]["summary"]["supportive_groups"] != 0:
        raise SystemExit("prior closure support changed")


def group_supportive(group: dict[str, Any]) -> bool:
    return all(
        (
            group["admissible"],
            group["bilateral_benchmark_support"],
            group["bilateral_risk_support"],
            group["bilateral_dependence_support"],
            group["bilateral_breadth_support"],
        )
    )


def build_leave_one_out(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for omitted in groups:
        retained = [group for group in groups if group["group_id"] != omitted["group_id"]]
        supportive = [group["group_id"] for group in retained if group_supportive(group)]
        rows.append(
            {
                "omitted_group": omitted["group_id"],
                "retained_groups": [group["group_id"] for group in retained],
                "supportive_groups": supportive,
                "subset_supportive": bool(supportive),
            }
        )
    return rows


def build_summary(
    records: dict[str, Any],
    leave_one_out: list[dict[str, Any]],
) -> dict[str, Any]:
    groups = records["groups"]
    supportive = [group["group_id"] for group in groups if group_supportive(group)]
    return {
        "bound_mechanism_count": len(groups),
        "closure_candidate_count": 0,
        "historical_candidate_count": sum(int(group["candidate_count"]) for group in groups),
        "parameter_grid_count": 0,
        "target_arm_count": sum(len(group["target_arms"]) for group in groups),
        "cohort_count": len(groups),
        "supportive_mechanisms": supportive,
        "supportive_mechanism_count": len(supportive),
        "supportive_leave_one_mechanism_out_subsets": sum(
            bool(row["subset_supportive"]) for row in leave_one_out
        ),
        "new_market_data_rows": 0,
        "new_target_labels": 0,
        "new_oos_observations": 0,
        "closure_performance_accessed": False,
        "closure_oos_accessed": False,
    }


def build_gates(
    records: dict[str, Any],
    summary: dict[str, Any],
    leave_one_out: list[dict[str, Any]],
) -> dict[str, bool]:
    groups = records["groups"]
    return {
        "exact_terminal_identities_bound": all(
            group["family_id"]
            and group["issues"]
            and group["pull_requests"]
            and group["target_arms"]
            and group["source"]
            and group["sample"]
            for group in groups
        ),
        "causal_public_1h_boundary_preserved": BAR == "1H",
        "exactly_5bps_one_way_preserved": all(
            group["fee_bps_one_way"] == FEE_BPS_ONE_WAY for group in groups
        ),
        "historical_candidate_count_exactly_one": summary["historical_candidate_count"] == 1,
        "zero_independently_admissible_mechanisms": summary["supportive_mechanism_count"] == 0,
        "all_leave_one_out_subsets_have_zero_support": all(
            not row["subset_supportive"] for row in leave_one_out
        ),
        "btc_eth_development_cohort_not_supportive": not group_supportive(groups[0]),
        "near_apt_external_cohort_not_supportive": not group_supportive(groups[1]),
        "prior_conditional_variance_closure_has_zero_support": (
            records["prior_programme_closure"]["summary"]["supportive_groups"] == 0
        ),
        "no_new_data_labels_oos_or_strategy_paths": (
            summary["new_market_data_rows"] == 0
            and summary["new_target_labels"] == 0
            and summary["new_oos_observations"] == 0
            and not summary["closure_performance_accessed"]
        ),
    }


def build_report(evidence: dict[str, Any]) -> str:
    group_a, group_b = evidence["groups"]
    btc = group_a["oos"]["BTC-USDT"]
    eth = group_a["oos"]["ETH-USDT"]
    near = group_b["targets"]["NEAR-USDT"]
    apt = group_b["targets"]["APT-USDT"]
    summary = evidence["summary"]
    return "\n".join(
        [
            "# Own-Price Jump/Discontinuity Programme Closure — 1H V1",
            "",
            "## Verdict",
            "",
            f"`{evidence['verdict']}`",
            "",
            (
                "No completed scalar own-price jump/discontinuity mechanism independently "
                "demonstrates transferable net alpha after exactly 5 bps one way."
            ),
            "",
            "## Frozen scope",
            "",
            f"- Tested head: `{evidence['tested_head']}`",
            f"- Canonical main: `{evidence['canonical_main_head']}`",
            f"- Bound mechanisms / targets: `{summary['bound_mechanism_count']}` / "
            f"`{summary['target_arm_count']}`",
            f"- Historical candidates: `{summary['historical_candidate_count']}`",
            "- New market rows / labels / OOS: `0 / 0 / 0`",
            "",
            "## Executable BTC/ETH mechanism",
            "",
            "| Target | Train net/Sharpe | OOS candidate | OOS E2160 | Turnover cand/base | Edge/turn cand/base | DD cand/base | Folds | Years |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
            (
                f"| BTC | {group_a['training']['BTC-USDT']['net_return_pct']:.2f}% / "
                f"{group_a['training']['BTC-USDT']['sharpe']:.3f} | "
                f"{btc['candidate']['net_return_pct']:.2f}% / "
                f"{btc['candidate']['sharpe']:.3f} | "
                f"{btc['benchmark']['net_return_pct']:.2f}% / "
                f"{btc['benchmark']['sharpe']:.3f} | "
                f"{btc['candidate']['turnover']:.1f}/{btc['benchmark']['turnover']:.1f} | "
                f"{btc['candidate']['edge_per_turnover_bps']:.2f}/"
                f"{btc['benchmark']['edge_per_turnover_bps']:.2f} bp | "
                f"{btc['candidate']['max_drawdown_pct']:.2f}%/"
                f"{btc['benchmark']['max_drawdown_pct']:.2f}% | "
                f"{btc['profitable_folds']} | {btc['profitable_years']} |"
            ),
            (
                f"| ETH | {group_a['training']['ETH-USDT']['net_return_pct']:.2f}% / "
                f"{group_a['training']['ETH-USDT']['sharpe']:.3f} | "
                f"{eth['candidate']['net_return_pct']:.2f}% / "
                f"{eth['candidate']['sharpe']:.3f} | "
                f"{eth['benchmark']['net_return_pct']:.2f}% / "
                f"{eth['benchmark']['sharpe']:.3f} | "
                f"{eth['candidate']['turnover']:.1f}/{eth['benchmark']['turnover']:.1f} | "
                f"{eth['candidate']['edge_per_turnover_bps']:.2f}/"
                f"{eth['benchmark']['edge_per_turnover_bps']:.2f} bp | "
                f"{eth['candidate']['max_drawdown_pct']:.2f}%/"
                f"{eth['benchmark']['max_drawdown_pct']:.2f}% | "
                f"{eth['profitable_folds']} | {eth['profitable_years']} |"
            ),
            "",
            (
                f"BTC mean/Sharpe delta intervals: {btc['mean_delta_ci_pct']} and "
                f"{btc['sharpe_delta_ci']}; ETH: {eth['mean_delta_ci_pct']} and "
                f"{eth['sharpe_delta_ci']}."
            ),
            "",
            "## External NEAR/APT information diagnostic",
            "",
            "| Target | Opportunities | Net slope | Net tercile | Adverse slope | Net/adverse folds | Concentration | Delayed net tercile |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
            (
                f"| NEAR | {near['valid_opportunities']} | {near['net_slope']:.6f} | "
                f"{near['net_tercile_effect_bps']:.2f} bp | "
                f"{near['adverse_slope']:.6f} | "
                f"{near['positive_net_slope_folds']}/"
                f"{near['positive_adverse_slope_folds']} | "
                f"{near['largest_positive_net_fold_share']:.2%} | "
                f"{near['delayed_net_tercile_effect_bps']:.2f} bp |"
            ),
            (
                f"| APT | {apt['valid_opportunities']} | {apt['net_slope']:.6f} | "
                f"{apt['net_tercile_effect_bps']:.2f} bp | "
                f"{apt['adverse_slope']:.6f} | "
                f"{apt['positive_net_slope_folds']}/"
                f"{apt['positive_adverse_slope_folds']} | "
                f"{apt['largest_positive_net_fold_share']:.2%} | "
                f"{apt['delayed_net_tercile_effect_bps']:.2f} bp |"
            ),
            "",
            (
                "NEAR contradicted continuation. APT's favourable return effect was "
                "under-supported, adverse-slope negative, dependence-unsupported, "
                "narrow on adverse folds, and above the concentration cap."
            ),
            "",
            "## Closure adjudication",
            "",
            (
                "Every individual, leave-one-mechanism-out and leave-one-cohort-out "
                "test retains zero independently admissible mechanisms. Closure-level "
                "train/OOS/full economics remain null rather than zero."
            ),
            "",
            "## Remaining blocker",
            "",
            evidence["remaining_blocker"],
            "",
            "## Next sole architecture",
            "",
            f"`{evidence['next_strategy_architecture']}`",
            "",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tested-head", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    if len(args.tested_head) != 40 or any(
        char not in "0123456789abcdef" for char in args.tested_head
    ):
        raise SystemExit("tested head must be a lowercase 40-character git SHA")

    records = load_records()
    validate_records(records)
    leave_one_out = build_leave_one_out(records["groups"])
    summary = build_summary(records, leave_one_out)
    gates = build_gates(records, summary, leave_one_out)
    failed = [name for name, passed in gates.items() if not passed]
    if failed:
        raise SystemExit(f"closure gates failed: {failed}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    source_records = {
        "family_id": FAMILY_ID,
        "canonical_main_head": MAIN_HEAD,
        "tested_head": args.tested_head,
        "records": records,
    }
    source_sha = write_json(args.output_dir / "source_records.json", source_records)
    write_text(args.output_dir / "source_records.sha256", f"{source_sha}  source_records.json\n")

    evidence = {
        "family_id": FAMILY_ID,
        "classification": "zero-candidate completed-family strategy evidence closure",
        "canonical_main_head": MAIN_HEAD,
        "tested_head": args.tested_head,
        "bar": BAR,
        "fee_bps_one_way": FEE_BPS_ONE_WAY,
        "groups": records["groups"],
        "prior_programme_closure": records["prior_programme_closure"],
        "summary": summary,
        "leave_one_mechanism_out": leave_one_out,
        "leave_one_cohort_out": leave_one_out,
        "gates": gates,
        "hard_boundary": {
            "same_instrument_lagged_history_to_same_instrument_long_cash": True,
            "cross_sectional_ranking_or_selection": False,
            "pairs_spreads_cointegration_or_statistical_arbitrage": False,
            "market_neutral_or_long_short": False,
            "post_hoc_asset_filtering": False,
            "credentials_private_endpoints_accounts_orders_or_leverage": False,
            "synthetic_data": False,
            "non_1h_or_15m": False,
        },
        "economics": {
            "training_return": None,
            "training_sharpe": None,
            "oos_return": None,
            "oos_sharpe": None,
            "full_return": None,
            "full_sharpe": None,
            "benchmark_comparison": None,
            "turnover": None,
            "fee_drag": None,
            "maximum_drawdown": None,
            "edge_per_turnover": None,
            "fold_breadth": None,
            "calendar_year_breadth": None,
        },
        "remaining_blocker": (
            "Scalar jump-versus-continuous variation can reduce exposure or look "
            "favourable in one target, but no completed mechanism jointly improves "
            "fee-adjusted return, Sharpe, downside, turnover efficiency, breadth and "
            "dependence-supported transport across independent markets."
        ),
        "next_strategy_architecture": "causal-own-price-ridge-lag-strip-utility-selector-1h-v1",
        "canonical_mutation_authorized": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "verdict": VERDICT,
        "source_records_sha256": source_sha,
    }
    evidence_sha = write_json(args.output_dir / "evidence.json", evidence)
    write_text(args.output_dir / "evidence.sha256", f"{evidence_sha}  evidence.json\n")
    report_sha = write_text(args.output_dir / "report.md", build_report(evidence))
    write_text(args.output_dir / "report.sha256", f"{report_sha}  report.md\n")
    manifest = {
        "evidence_sha256": evidence_sha,
        "report_sha256": report_sha,
        "source_records_sha256": source_sha,
        "tested_head": args.tested_head,
        "verdict": VERDICT,
    }
    manifest_sha = write_json(args.output_dir / "manifest.json", manifest)
    write_text(args.output_dir / "manifest.sha256", f"{manifest_sha}  manifest.json\n")
    print(json.dumps({**manifest, "manifest_sha256": manifest_sha}, sort_keys=True))


if __name__ == "__main__":
    main()
