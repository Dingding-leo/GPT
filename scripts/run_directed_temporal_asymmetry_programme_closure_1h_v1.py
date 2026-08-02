#!/usr/bin/env python3
"""Bind completed directed temporal-asymmetry evidence and close the programme."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

FAMILY_ID = "causal-own-price-directed-temporal-asymmetry-programme-closure-1h-v1"
VERDICT = "reject_reopening_completed_directed_temporal_asymmetry_mechanisms_1h_v1"
MAIN_HEAD = "5a0fcc97d1a882f8223656c51f5bb8055f534e38"
RECORDS_PATH = Path(__file__).with_name(
    "directed_temporal_asymmetry_programme_closure_1h_v1_records.json"
)


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        + "\n"
    ).encode()


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


def load_records() -> dict[str, Any]:
    records = json.loads(RECORDS_PATH.read_text())
    if records["family_id"] != FAMILY_ID:
        raise SystemExit("unexpected family identity")
    if records["canonical_main_head"] != MAIN_HEAD:
        raise SystemExit("unexpected canonical main identity")
    groups = records["groups"]
    if [group["group_id"] for group in groups] != list("ABCDE"):
        raise SystemExit("unexpected group identity or order")
    return records


def group_supportive(group: dict[str, Any]) -> bool:
    return all(
        (
            group["bilateral_economic_support"],
            group["bilateral_risk_support"],
            group["bilateral_dependence_support"],
            group["bilateral_breadth_support"],
            group["bilateral_timing_support"],
            group["bilateral_turnover_efficiency_support"],
        )
    )


def build_leave_one_out(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for omitted in [group["group_id"] for group in groups]:
        retained = [group for group in groups if group["group_id"] != omitted]
        supportive = [
            group["group_id"] for group in retained if group_supportive(group)
        ]
        rows.append(
            {
                "omitted_group": omitted,
                "retained_groups": [group["group_id"] for group in retained],
                "supportive_groups": supportive,
                "supportive": bool(supportive),
            }
        )
    return rows


def build_summary(
    records: dict[str, Any],
    leave_one_out: list[dict[str, Any]],
) -> dict[str, Any]:
    groups = records["groups"]
    return {
        "bound_groups": len(groups),
        "bound_historical_candidates": sum(
            int(group["candidate_count"]) for group in groups
        ),
        "executable_groups": sum(
            group["classification"] == "executable" for group in groups
        ),
        "diagnostic_groups": sum(
            group["classification"] != "executable" for group in groups
        ),
        "supportive_individual_groups": sum(
            group_supportive(group) for group in groups
        ),
        "supportive_leave_one_out_subsets": sum(
            row["supportive"] for row in leave_one_out
        ),
        "closure_candidate_count": records["candidate_count"],
        "parameter_grid_count": records["parameter_grid_count"],
        "new_market_data": records["new_market_data"],
        "new_target_labels": records["new_target_labels"],
        "new_oos_consumed": records["new_oos_consumed"],
        "performance_accessed_in_closure": records[
            "performance_accessed_in_closure"
        ],
    }


def validate(records: dict[str, Any], summary: dict[str, Any]) -> None:
    groups = records["groups"]
    failures = []
    if records["bar"] != "1H" or records["one_way_fee_bps"] != 5.0:
        failures.append("bar or fee boundary")
    if summary["bound_groups"] != 5:
        failures.append("group count")
    if summary["bound_historical_candidates"] != 2:
        failures.append("historical candidate count")
    if summary["executable_groups"] != 2 or summary["diagnostic_groups"] != 3:
        failures.append("group classification count")
    if summary["supportive_individual_groups"] != 0:
        failures.append("individual support")
    if summary["supportive_leave_one_out_subsets"] != 0:
        failures.append("leave-one-out support")
    if any(
        (
            records["candidate_count"],
            records["parameter_grid_count"],
            records["new_market_data"],
            records["new_target_labels"],
            records["new_oos_consumed"],
            records["performance_accessed_in_closure"],
        )
    ):
        failures.append("closure access contract")
    if not all(
        group["terminal_verdict"]
        and group["issue"]
        and group["pull_request"]
        and group["acceptance_failures"]
        for group in groups
    ):
        failures.append("terminal evidence identity")
    if failures:
        raise SystemExit(f"closure validation failed: {failures}")


def build_report(evidence: dict[str, Any]) -> str:
    summary = evidence["summary"]
    lines = [
        "# Directed Temporal-Asymmetry Programme Closure — 1H V1",
        "",
        "## Verdict",
        "",
        f"`{evidence['verdict']}`",
        "",
        (
            "No completed directed temporal-order mechanism independently "
            "satisfies its original bilateral economics, risk, dependence, "
            "breadth, timing, and turnover-efficiency requirements."
        ),
        "",
        "## Frozen accounting",
        "",
        f"- Canonical main: `{evidence['canonical_main_head']}`",
        f"- Exact evidence head: `{evidence['tested_head']}`",
        "- Bar: `1H`",
        "- Modeled fee: exactly `5 bps` one way wherever labels or positions existed",
        f"- Bound groups: `{summary['bound_groups']}`",
        f"- Historical executable candidates: `{summary['bound_historical_candidates']}`",
        "- New candidates / parameter variants: `0 / 0`",
        "- New data / labels / OOS observations: `0 / 0 / 0`",
        "",
        "## Group adjudication",
        "",
        "| Group | Representation | Class | Economic | Risk | Dependence | Breadth | Timing | Turnover |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for group in evidence["groups"]:
        values = [
            "pass" if group[key] else "fail"
            for key in (
                "bilateral_economic_support",
                "bilateral_risk_support",
                "bilateral_dependence_support",
                "bilateral_breadth_support",
                "bilateral_timing_support",
                "bilateral_turnover_efficiency_support",
            )
        ]
        lines.append(
            f"| {group['group_id']} | {group['representation_class']} | "
            f"{group['classification']} | " + " | ".join(values) + " |"
        )
    lines.extend(
        [
            "",
            "## Decisive evidence",
            "",
            (
                "- Bayesian sign-transition change point: zero entries in both "
                "targets, 0/12 profitable OOS folds, and materially negative "
                "paired lower bounds versus E2160."
            ),
            (
                "- Sign-transition entropy overlay: BTC and ETH both raised "
                "turnover and reduced edge per turnover; both paired intervals "
                "crossed zero, with only 5/12 and 6/12 profitable folds."
            ),
            (
                "- Ordinal-transition stability: BTC had a negative net tercile "
                "effect and ETH contradicted the premise; all eight dependence "
                "lower bounds were negative."
            ),
            (
                "- Leverage-effect relaxation: return and adverse-excursion "
                "effects were negative in both targets and remained negative "
                "after one-hour delay."
            ),
            (
                "- Time-reversal asymmetry: BTC bucket effects conflicted with "
                "continuous slopes, ETH bucket effects were negative, all eight "
                "lower bounds were negative, and delay retained no bilateral support."
            ),
            "",
            "## Leave-one-group-out",
            "",
            (
                "All five leave-one-group-out subsets contain zero independently "
                "supportive groups. The closure is therefore not driven by any "
                "single representation or one market sleeve."
            ),
            "",
            "## Strategy-performance access",
            "",
            (
                "The closure created no equity curve. New train, OOS, full, "
                "benchmark, turnover, drawdown, edge-per-turnover, year-breadth, "
                "and uncertainty metrics are null. Existing source metrics are "
                "bound without recomputation."
            ),
            "",
            "## Closed rescue scope",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in evidence["closed_rescue_scope"])
    next_architecture = evidence["next_architecture"]
    lines.extend(
        [
            "",
            "## Next materially orthogonal architecture",
            "",
            f"`{next_architecture['family_id']}`",
            "",
            (
                "Audit direct public BTC and ETH insurance-fund balance history "
                "as a systemic loss-absorption state. This is a provider-defined "
                "balance-sheet object rather than another return-order statistic. "
                "No target return or feature sign is authorised during the source audit."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tested-head", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if not re_full_sha(args.tested_head):
        raise SystemExit("tested head must be a lowercase 40-character git SHA")

    records = load_records()
    groups = records["groups"]
    leave_one_out = build_leave_one_out(groups)
    summary = build_summary(records, leave_one_out)
    validate(records, summary)

    evidence = {
        "family_id": FAMILY_ID,
        "classification": "completed-evidence strategy-family closure",
        "canonical_main_head": MAIN_HEAD,
        "tested_head": args.tested_head,
        "bar": records["bar"],
        "one_way_fee_bps": records["one_way_fee_bps"],
        "summary": summary,
        "groups": groups,
        "leave_one_group_out": leave_one_out,
        "closed_rescue_scope": records["closed_rescue_scope"],
        "next_architecture": records["next_architecture"],
        "verdict": VERDICT,
        "canonical_mutation": False,
        "paper_trading_authority": False,
        "live_trading_authority": False,
    }
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    source_sha = write_json(output_dir / "source_records.json", records)
    evidence_sha = write_json(output_dir / "evidence.json", evidence)
    report_sha = write_text(output_dir / "report.md", build_report(evidence))
    write_text(
        output_dir / "source_records.sha256",
        f"{source_sha}  source_records.json\n",
    )
    write_text(
        output_dir / "evidence.sha256",
        f"{evidence_sha}  evidence.json\n",
    )
    write_text(output_dir / "report.sha256", f"{report_sha}  report.md\n")
    print(
        json.dumps(
            {
                "family_id": FAMILY_ID,
                "summary": summary,
                "verdict": VERDICT,
                "evidence_sha256": evidence_sha,
                "source_records_sha256": source_sha,
                "report_sha256": report_sha,
            },
            indent=2,
            sort_keys=True,
        )
    )


def re_full_sha(value: str) -> bool:
    return len(value) == 40 and all(
        character in "0123456789abcdef" for character in value
    )


if __name__ == "__main__":
    main()
