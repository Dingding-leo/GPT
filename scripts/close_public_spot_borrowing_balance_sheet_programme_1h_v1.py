# ruff: noqa
# fmt: off
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

FAMILY_ID = "causal-public-spot-borrowing-balance-sheet-programme-closure-1h-v1"
VERDICT = "reject_reopening_completed_public_spot_borrowing_balance_sheet_mechanisms_1h_v1"
REPOSITORY_MAIN = "5a0fcc97d1a882f8223656c51f5bb8055f534e38"
ISSUE = 989

NULL_ECONOMICS = {
    "train_net_return": None,
    "train_sharpe": None,
    "oos_net_return": None,
    "oos_sharpe": None,
    "full_net_return": None,
    "full_sharpe": None,
    "e2160_net_return": None,
    "e2160_sharpe": None,
    "always_long_net_return": None,
    "always_long_sharpe": None,
    "turnover": None,
    "modeled_fees": None,
    "maximum_drawdown": None,
    "edge_per_turnover_bps": None,
    "fold_breadth": None,
    "calendar_year_breadth": None,
    "dependence_aware_uncertainty": None,
    "one_hour_delay": None,
}

GROUPS = [
    {
        "group": "A",
        "mechanism": "public spot-borrow demand quantity",
        "family_id": "causal-public-spot-borrow-demand-source-contract-1h-v1",
        "issue": 983,
        "pull_request": 985,
        "exact_evidence_head": "c7b70b0b6c709478f08d4c587104832c21fd2b06",
        "focused_workflow_run": 30757218260,
        "artifact_id": 8836300632,
        "artifact_zip_sha256": "731f6c06ff2a2ca536571b24016731f923d1f4ebd9a1f8247d870444b6f1cd6a",
        "evidence_json_sha256": "069ee865f7d1af840457fde0b6a3dc3a29845f96002db0b5ebd51014f3af1bfc",
        "source_manifest_sha256": "159d7a9ca6cd4aa05fbada6b3ab96c37365ec0baa5070d67a4b5150e435954a0",
        "report_sha256": "43e67be063aa7025adc174eaa59fd8ca247ca5abebc1acfa1fb1369dd1565e22",
        "terminal_verdict": "reject_causal_public_spot_borrow_demand_source_contract_1h_v1",
        "direct_provider_defined_object": True,
        "bilateral_direct_source_feasible": False,
        "bilateral_complete_provider_native_1h": False,
        "target_arms": {
            "BTC": {
                "expected_rows": 24144,
                "observed_numeric_quantity_rows": 0,
                "distinct_count": None,
                "minimum": None,
                "maximum": None,
                "q1": None,
                "q3": None,
                "iqr": None,
                "constant": None,
                "direct_quantity_present": False,
            },
            "ETH": {
                "expected_rows": 24144,
                "observed_numeric_quantity_rows": 0,
                "distinct_count": None,
                "minimum": None,
                "maximum": None,
                "q1": None,
                "q3": None,
                "iqr": None,
                "constant": None,
                "direct_quantity_present": False,
            },
        },
        "both_arms_at_least_30_distinct_and_positive_iqr": False,
        "nonconstant_lagged_state_possible_bilaterally": False,
        "substitution_or_stitching_required_for_rescue": True,
        "admissible_bilateral_mechanism": False,
        "failure": (
            "Provider-declared quantity fields amt, avgAmt and avgAmtUsd are deprecated "
            "and empty; rate cannot be substituted for demand quantity."
        ),
    },
    {
        "group": "B",
        "mechanism": "public spot-borrow rate",
        "family_id": "causal-public-spot-borrow-rate-source-contract-1h-v1",
        "issue": 986,
        "pull_request": 988,
        "exact_evidence_head": "1a8d65ee1fe4b5b70c5f596cc9e3b1509482d5a8",
        "focused_workflow_run": 30759371669,
        "artifact_id": 8837015113,
        "artifact_zip_sha256": "2d5140e1366fb36065eee2faec8b6f0e0f45746be5bef2f3b400025562655358",
        "evidence_json_sha256": "4a2ef84681be435db71af75a21c89ef1684de3b6c24021c168187f346389571f",
        "source_manifest_sha256": "40e301595e15907755fd0b047868c2ece9159d52fa37e85527fcc333c2c14e5c",
        "semantic_contract_sha256": "8f8e2937767cca82f1c87ef9555b9b03d80ed0d65136f6e924943324e5c8fc23",
        "report_sha256": "433326a8a3e152882e35608dcbd389bbc5a8e4d216e67b7b485a4f761b69b974",
        "terminal_verdict": "accept_causal_public_spot_borrow_rate_source_contract_1h_v1",
        "strategy_disposition": (
            "reject_bilateral_spot_borrow_rate_pressure_information_premise_before_target_access"
        ),
        "direct_provider_defined_object": True,
        "bilateral_direct_source_feasible": True,
        "bilateral_complete_provider_native_1h": True,
        "target_arms": {
            "BTC": {
                "expected_rows": 24144,
                "observed_rows": 24144,
                "distinct_count": 1,
                "minimum": 0.01,
                "maximum": 0.01,
                "q1": 0.01,
                "q3": 0.01,
                "iqr": 0.0,
                "constant": True,
                "panel_csv_sha256": (
                    "b7e45de7e70aa428e14324bc152409409933b78277698f4cdd517390932f480c"
                ),
            },
            "ETH": {
                "expected_rows": 24144,
                "observed_rows": 24144,
                "distinct_count": 90,
                "minimum": 0.01,
                "maximum": 0.8,
                "q1": 0.01,
                "q3": 0.015,
                "iqr": 0.005,
                "constant": False,
                "panel_csv_sha256": (
                    "4b25abf51830cc7e716740e53d11e236a61ed469329c3479222181396c865467"
                ),
            },
        },
        "both_arms_at_least_30_distinct_and_positive_iqr": False,
        "nonconstant_lagged_state_possible_bilaterally": False,
        "substitution_or_stitching_required_for_rescue": True,
        "admissible_bilateral_mechanism": False,
        "failure": (
            "BTC rate is exactly 0.01 for all 24,144 frozen hours, so every "
            "own-rate lagged difference, acceleration, normalization or nonlinear "
            "transform is constant; ETH-only promotion is prohibited."
        ),
    },
]

SEMANTICS = {
    "borrow_demand_quantity": (
        "Provider-defined amount or utilization quantity; the audited public amount fields "
        "amt, avgAmt and avgAmtUsd are deprecated and empty."
    ),
    "borrowing_rate": "rate is the provider-defined annual borrowing interest rate.",
    "lending_rate": (
        "lendingRate is the provider-defined annual lending interest rate and is a distinct "
        "adjacent field, not a substitute for rate or demand quantity."
    ),
}

CLOSED_RESCUE_PATHS = [
    "reconstruct quantity from rates, lending balances, account liabilities, user loans or order books",
    "substitute lendingRate, avgRate, preRate, estRate, perpetual funding or margin interest for rate",
    "apply differences, acceleration, z-scores, ratios, thresholds or nonlinear transforms to constant BTC rate",
    "change rate units after inspection",
    "stitch providers or venues after a bilateral arm fails",
    "interpolate, convert cadence, expand daily data or aggregate local events",
    "delete favourable periods, replace targets or promote only ETH",
    "use credentials, private endpoints, accounts, balances, orders, leverage or enabled adapters",
]


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode() + b"\n"


def sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def write_hashed(root: Path, name: str, body: bytes) -> str:
    path = root / name
    path.write_bytes(body)
    digest = sha256(body)
    path.with_name(f"{path.name}.sha256").write_text(f"{digest}\n")
    return digest


def build_evidence(tested_head: str) -> dict[str, Any]:
    if len(tested_head) != 40 or any(character not in "0123456789abcdef" for character in tested_head):
        raise ValueError("tested head must be a lowercase 40-character SHA")

    identity_reconciliation = {
        "groups_reconciled": 2,
        "all_exact_heads_match_prior_records": True,
        "all_artifact_ids_match_prior_records": True,
        "all_available_hashes_match_downloaded_artifacts": True,
        "all_prior_terminal_verdicts_preserved": True,
        "closed_prs_unmerged": True,
    }
    gate_vector = {
        "one_group_has_direct_bilateral_public_source_feasibility": any(
            group["bilateral_direct_source_feasible"] for group in GROUPS
        ),
        "same_group_has_complete_provider_native_1h_bilaterally": any(
            group["bilateral_direct_source_feasible"]
            and group["bilateral_complete_provider_native_1h"]
            for group in GROUPS
        ),
        "both_arms_have_30_distinct_values_and_positive_iqr": any(
            group["both_arms_at_least_30_distinct_and_positive_iqr"] for group in GROUPS
        ),
        "nonconstant_target_specific_lagged_state_exists_bilaterally": any(
            group["nonconstant_lagged_state_possible_bilaterally"] for group in GROUPS
        ),
        "no_field_substitution_provider_stitching_or_market_subset_needed": any(
            group["admissible_bilateral_mechanism"]
            and not group["substitution_or_stitching_required_for_rescue"]
            for group in GROUPS
        ),
        "leave_one_group_out_always_retains_one_admissible_mechanism": False,
        "source_identities_and_terminal_verdicts_reconcile": all(identity_reconciliation.values()),
    }
    leave_one_group_out = [
        {
            "removed_group": group["group"],
            "remaining_groups": [other["group"] for other in GROUPS if other is not group],
            "remaining_admissible_mechanisms": sum(
                bool(other["admissible_bilateral_mechanism"])
                for other in GROUPS
                if other is not group
            ),
            "programme_admissible": False,
        }
        for group in GROUPS
    ]
    return {
        "family_id": FAMILY_ID,
        "issue": ISSUE,
        "tested_head": tested_head,
        "repository_main": REPOSITORY_MAIN,
        "classification": "zero-candidate strategy-family evidence closure",
        "bar": "1H",
        "sample_start": "2023-04-01T00:00:00Z",
        "sample_end": "2025-12-31T23:00:00Z",
        "canonical_fee_bps_one_way": 5.0,
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "new_market_data_rows": 0,
        "new_target_return_rows": 0,
        "new_oos_observations": 0,
        "performance_accessed": False,
        "oos_accessed": False,
        "target_prices_accessed": False,
        "canonical_strategy_changed": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "credentials_or_private_endpoints_used": False,
        "accounts_orders_leverage_or_adapters_used": False,
        "synthetic_or_non_1h_data_used": False,
        "cross_sectional_or_relative_rank_used": False,
        "pairs_spreads_cointegration_or_market_neutral_used": False,
        "post_hoc_filtering_used": False,
        "semantic_distinctions": SEMANTICS,
        "groups": GROUPS,
        "identity_reconciliation": identity_reconciliation,
        "acceptance_gates": gate_vector,
        "gates_passing": sum(gate_vector.values()),
        "gates_total": len(gate_vector),
        "admissible_groups": sum(bool(group["admissible_bilateral_mechanism"]) for group in GROUPS),
        "leave_one_group_out": leave_one_group_out,
        "economics": dict(NULL_ECONOMICS),
        "closed_rescue_paths": CLOSED_RESCUE_PATHS,
        "highest_value_failure": (
            "The only complete bilateral public object is the borrow-rate panel, but BTC has "
            "zero temporal variation; the direct quantity object is absent. No included group "
            "can define a nonconstant bilateral causal state before target-return access."
        ),
        "verdict": VERDICT,
    }


def build_report(evidence: dict[str, Any]) -> str:
    groups = evidence["groups"]
    gates = evidence["acceptance_gates"]
    return f"""# Public spot-borrowing balance-sheet programme closure 1H v1

```text
family                  {evidence['family_id']}
canonical main          {evidence['repository_main']}
exact evidence head     {evidence['tested_head']}
completed groups        {len(groups)}
admissible groups       {evidence['admissible_groups']}
new candidates          {evidence['candidate_count']}
new parameters          {evidence['parameter_grid_count']}
new market/OOS rows     {evidence['new_market_data_rows']}/{evidence['new_oos_observations']}
verdict                 {evidence['verdict']}
```

## Frozen evidence result

| Group | Direct bilateral source | Complete 1H | BTC support | ETH support | Admissible |
|---|---:|---:|---|---|---:|
| A — borrow-demand quantity | no | no | quantity absent | quantity absent | no |
| B — borrow rate | yes | yes | 1 value; IQR 0 | 90 values; IQR 0.005 | no |

Group A failed because the provider-declared amount fields are deprecated and empty. Group B passed the anonymous direct 24,144-hour source contract, but BTC was exactly 0.01 for every hour. A constant input cannot produce a nonconstant lagged own-rate state. ETH-only promotion is prohibited.

## Acceptance scorecard

{chr(10).join(f'- {name}: **{"pass" if value else "fail"}**' for name, value in gates.items())}

Both leave-one-group-out subsets contain zero admissible mechanisms. Removing Group A leaves the constant-BTC rate failure. Removing Group B leaves the absent quantity failure.

## Economics

No target price, return, benchmark, candidate or OOS value was accessed. Train, OOS and full return/Sharpe; E2160 and always-long comparison; turnover; modeled fee drag; maximum drawdown; edge per turnover; fold/year breadth; dependence-aware uncertainty; and one-hour-delay economics are null rather than zero. Exactly 5 bps one way remains mandatory for any separately authorised executable strategy.

## Terminal disposition

The completed direct-public spot-borrowing programme is closed against quantity reconstruction, field substitution, transforms of the constant BTC rate, provider stitching, interpolation, unit rescue, period deletion and single-market promotion. This rejects the completed implementation programme, not the possible economic relevance of private or proprietary borrowing information.
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tested-head", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    root = args.output_dir
    root.mkdir(parents=True, exist_ok=True)
    evidence = build_evidence(args.tested_head)

    evidence_digest = write_hashed(root, "evidence.json", canonical(evidence))
    records = {
        "family_id": FAMILY_ID,
        "tested_head": args.tested_head,
        "input_groups": GROUPS,
        "artifact_verification_method": (
            "Exact GitHub artifact ZIP SHA-256 and every embedded sidecar hash were verified "
            "before this deterministic closure was created."
        ),
    }
    records_digest = write_hashed(root, "source_records.json", canonical(records))
    report_digest = write_hashed(root, "report.md", build_report(evidence).encode())
    summary = {
        "family_id": FAMILY_ID,
        "tested_head": args.tested_head,
        "verdict": VERDICT,
        "candidate_count": 0,
        "admissible_groups": 0,
        "evidence_json_sha256": evidence_digest,
        "source_records_sha256": records_digest,
        "report_sha256": report_digest,
    }
    write_hashed(root, "artifact_summary.json", canonical(summary))


if __name__ == "__main__":
    main()
