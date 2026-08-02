# ruff: noqa
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import tempfile
import zipfile
from pathlib import Path
from typing import Any

FAMILY_ID = "causal-public-spot-margin-balance-sheet-crowding-programme-closure-1h-v1"
VERDICT = (
    "reject_reopening_completed_public_spot_margin_balance_sheet_crowding_mechanisms_1h_v1"
)
REPOSITORY_MAIN = "5a0fcc97d1a882f8223656c51f5bb8055f534e38"
ISSUE = 996

ARTIFACTS = {
    "borrow_demand_quantity": {
        "artifact_id": 8836300632,
        "zip_name": "borrow-demand.zip",
        "zip_sha256": "731f6c06ff2a2ca536571b24016731f923d1f4ebd9a1f8247d870444b6f1cd6a",
        "evidence_sha256": "069ee865f7d1af840457fde0b6a3dc3a29845f96002db0b5ebd51014f3af1bfc",
        "report_sha256": "43e67be063aa7025adc174eaa59fd8ca247ca5abebc1acfa1fb1369dd1565e22",
        "family_id": "causal-public-spot-borrow-demand-source-contract-1h-v1",
        "verdict": "reject_causal_public_spot_borrow_demand_source_contract_1h_v1",
        "issue": 983,
        "pr": 985,
        "head": "c7b70b0b6c709478f08d4c587104832c21fd2b06",
        "workflow_run": 30757218260,
    },
    "borrow_rate": {
        "artifact_id": 8837015113,
        "zip_name": "borrow-rate.zip",
        "zip_sha256": "2d5140e1366fb36065eee2faec8b6f0e0f45746be5bef2f3b400025562655358",
        "evidence_sha256": "4a2ef84681be435db71af75a21c89ef1684de3b6c24021c168187f346389571f",
        "report_sha256": "433326a8a3e152882e35608dcbd389bbc5a8e4d216e67b7b485a4f761b69b974",
        "family_id": "causal-public-spot-borrow-rate-source-contract-1h-v1",
        "verdict": "accept_causal_public_spot_borrow_rate_source_contract_1h_v1",
        "issue": 986,
        "pr": 988,
        "head": "1a8d65ee1fe4b5b70c5f596cc9e3b1509482d5a8",
        "workflow_run": 30759371669,
    },
    "borrowing_programme_closure": {
        "artifact_id": 8837581839,
        "zip_name": "borrowing-closure.zip",
        "zip_sha256": "a280c7bd65025ae7a7806abd47a127ecbfaf7f56d4a422aa61da2173f46d221c",
        "evidence_sha256": "0586c603e2040366bf7051153825a18937e71da0e78b8cf7d57dfc18ec6aef73",
        "report_sha256": "f65382465392e8acaec25d5b6e2df6ff01828eb05e60d19af08272e27c215989",
        "family_id": "causal-public-spot-borrowing-balance-sheet-programme-closure-1h-v1",
        "verdict": "reject_reopening_completed_public_spot_borrowing_balance_sheet_mechanisms_1h_v1",
        "issue": 989,
        "pr": 992,
        "head": "5184c94da038ad35b403eca22b0998f260d0e68a",
        "workflow_run": 30761462542,
    },
    "margin_lending_ratio": {
        "artifact_id": 8838313894,
        "zip_name": "margin-ratio.zip",
        "zip_sha256": "1aa9da23b123c0ba5be82fae8ae5eb9e86180e3829bee6307f9b1fbf31c436cd",
        "evidence_sha256": "c5fc6c2af32c275b73f75d10e129855413bf5a8ca7a1813b4cbfbe68b5f97de9",
        "report_sha256": "c730f385266ba496b8a5a789eb233e6a17a4b92d6f80028afa2160ba5186670e",
        "family_id": "causal-public-spot-margin-lending-ratio-source-contract-1h-v1",
        "verdict": "reject_causal_public_spot_margin_lending_ratio_source_contract_1h_v1",
        "issue": 993,
        "pr": 995,
        "head": "9b10939649a0a511e9c207b64e94a94113cf0062",
        "workflow_run": 30763896329,
    },
}

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
    "modeled_fee_drag": None,
    "maximum_drawdown": None,
    "edge_per_turnover_bps": None,
    "fold_breadth": None,
    "calendar_year_breadth": None,
    "dependence_aware_uncertainty": None,
    "one_hour_execution_delay": None,
}

CLOSED_RESCUE_PATHS = [
    "reconstruct demand quantity from rates, balances, liabilities, loans or order books",
    "substitute lendingRate, funding, open interest, margin interest or another adjacent field",
    "transform the constant BTC borrow rate with differences, z-scores, thresholds or nonlinear maps",
    "shorten the frozen calendar to fit currently accessible margin-ratio history",
    "aggregate, interpolate, forward-fill or locally reconstruct provider-native 1H observations",
    "stitch providers or venues after a bilateral arm fails",
    "select only ETH, replace a target or delete unfavourable periods",
    "use credentials, private endpoints, accounts, balances, orders, leverage or enabled adapters",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode() + b"\n"


def write_hashed(root: Path, name: str, body: bytes) -> str:
    path = root / name
    path.write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    path.with_name(f"{name}.sha256").write_text(f"{digest}\n")
    return digest


def percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("cannot calculate percentile of empty values")
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def extract_and_verify(prior_dir: Path, workspace: Path) -> dict[str, dict[str, Any]]:
    loaded: dict[str, dict[str, Any]] = {}
    for key, contract in ARTIFACTS.items():
        zip_path = prior_dir / str(contract["zip_name"])
        if not zip_path.is_file():
            raise FileNotFoundError(f"missing prior artifact: {zip_path}")
        observed_zip_hash = sha256_file(zip_path)
        if observed_zip_hash != contract["zip_sha256"]:
            raise ValueError(f"artifact ZIP hash mismatch for {key}: {observed_zip_hash}")
        target = workspace / key
        target.mkdir(parents=True)
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(target)
        evidence_path = target / "evidence.json"
        report_path = target / "report.md"
        if sha256_file(evidence_path) != contract["evidence_sha256"]:
            raise ValueError(f"evidence hash mismatch for {key}")
        if sha256_file(report_path) != contract["report_sha256"]:
            raise ValueError(f"report hash mismatch for {key}")
        evidence = json.loads(evidence_path.read_text())
        if evidence["family_id"] != contract["family_id"]:
            raise ValueError(f"family mismatch for {key}")
        if evidence["verdict"] != contract["verdict"]:
            raise ValueError(f"verdict mismatch for {key}")
        if evidence["issue"] != contract["issue"]:
            raise ValueError(f"issue mismatch for {key}")
        if evidence["tested_head"] != contract["head"]:
            raise ValueError(f"head mismatch for {key}")
        if evidence["repository_main"] != REPOSITORY_MAIN:
            raise ValueError(f"canonical main mismatch for {key}")
        if evidence["candidate_count"] != 0 or evidence["parameter_grid_count"] != 0:
            raise ValueError(f"unexpected candidate or parameter count for {key}")
        loaded[key] = {
            "contract": contract,
            "evidence": evidence,
            "root": target,
            "observed_zip_sha256": observed_zip_hash,
        }
    return loaded


def rate_distribution(root: Path, asset: str) -> dict[str, Any]:
    path = root / "panels" / f"{asset.lower()}-borrow-rate-1h.csv"
    values: list[float] = []
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            values.append(float(row["rate"]))
    q1 = percentile(values, 0.25)
    q3 = percentile(values, 0.75)
    differences = [right - left for left, right in zip(values, values[1:])]
    return {
        "observed_rows": len(values),
        "distinct_count": len(set(values)),
        "minimum": min(values),
        "maximum": max(values),
        "median": statistics.median(values),
        "q1": q1,
        "q3": q3,
        "iqr": q3 - q1,
        "constant": len(set(values)) == 1,
        "positive_first_differences": sum(value > 0 for value in differences),
        "negative_first_differences": sum(value < 0 for value in differences),
        "zero_first_differences": sum(value == 0 for value in differences),
        "panel_csv_sha256": sha256_file(path),
    }


def build_groups(loaded: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    demand = loaded["borrow_demand_quantity"]["evidence"]
    rate = loaded["borrow_rate"]["evidence"]
    margin = loaded["margin_lending_ratio"]["evidence"]
    rate_root = loaded["borrow_rate"]["root"]

    demand_arms = {row["asset"]: row for row in demand["source_arms"]}
    rate_arms = {row["asset"]: row for row in rate["source_arms"]}
    margin_arms = {row["asset"]: row for row in margin["source_arms"]}
    distributions = {asset: rate_distribution(rate_root, asset) for asset in ("BTC", "ETH")}

    group_a = {
        "group": "A",
        "mechanism": "public spot-borrow demand quantity",
        "prior": ARTIFACTS["borrow_demand_quantity"],
        "direct_provider_defined_object": True,
        "anonymous_public": True,
        "bilateral_source_feasible": False,
        "complete_native_1h_frozen_sample": False,
        "both_arms_at_least_30_distinct_and_positive_iqr": False,
        "nonconstant_bilateral_lagged_state": False,
        "admissible": False,
        "target_arms": {
            asset: {
                "expected_rows": demand_arms[asset]["expected_rows"],
                "numeric_quantity_rows": demand_arms[asset]["history_amount_numeric_rows"],
                "direct_quantity_present": demand_arms[asset][
                    "direct_provider_defined_quantity_present"
                ],
                "complete_native_1h": demand_arms[asset][
                    "complete_provider_native_1h_quantity_history"
                ],
            }
            for asset in ("BTC", "ETH")
        },
        "failure": (
            "Provider-defined amount fields amt, avgAmt and avgAmtUsd are deprecated and empty "
            "for both assets; a borrowing price cannot be substituted for demand quantity."
        ),
    }
    group_b = {
        "group": "B",
        "mechanism": "public spot-borrow rate",
        "prior": ARTIFACTS["borrow_rate"],
        "direct_provider_defined_object": True,
        "anonymous_public": True,
        "bilateral_source_feasible": all(rate_arms[a]["source_contract_passed"] for a in ("BTC", "ETH")),
        "complete_native_1h_frozen_sample": all(
            rate_arms[a]["observed_rows"] == 24144 for a in ("BTC", "ETH")
        ),
        "both_arms_at_least_30_distinct_and_positive_iqr": all(
            distributions[a]["distinct_count"] >= 30 and distributions[a]["iqr"] > 0
            for a in ("BTC", "ETH")
        ),
        "nonconstant_bilateral_lagged_state": all(
            not distributions[a]["constant"] for a in ("BTC", "ETH")
        ),
        "admissible": False,
        "target_arms": distributions,
        "failure": (
            "BTC is exactly 0.01 in all 24,144 hours, making every causal own-rate lagged "
            "difference, acceleration, normalization and nonlinear transform constant."
        ),
    }
    group_c = {
        "group": "C",
        "mechanism": "public spot-margin lending ratio",
        "prior": ARTIFACTS["margin_lending_ratio"],
        "direct_provider_defined_object": True,
        "anonymous_public": True,
        "bilateral_source_feasible": False,
        "complete_native_1h_frozen_sample": False,
        "both_arms_at_least_30_distinct_and_positive_iqr": False,
        "nonconstant_bilateral_lagged_state": False,
        "admissible": False,
        "target_arms": {
            asset: {
                "expected_rows": margin["expected_rows_per_arm"],
                "observed_rows": margin_arms[asset]["observed_rows"],
                "full_acquisition_attempted": margin_arms[asset]["full_acquisition_attempted"],
                "probe_windows": {
                    name: {
                        "row_count": window["row_count"],
                        "exact_requested_grid": window["exact_requested_grid"],
                        "http_status": window["meta"]["status"],
                        "provider_error": window["error"],
                    }
                    for name, window in margin_arms[asset]["probe"]["windows"].items()
                },
            }
            for asset in ("BTC", "ETH")
        },
        "failure": (
            "All six preregistered start, middle and end probes returned HTTP 200 with provider "
            "code 50030, 'Illegal time range', empty data and zero exact-grid rows."
        ),
    }
    return [group_a, group_b, group_c]


def build_evidence(tested_head: str, loaded: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if len(tested_head) != 40 or any(character not in "0123456789abcdef" for character in tested_head):
        raise ValueError("tested head must be a lowercase 40-character SHA")
    groups = build_groups(loaded)
    prior_closure = loaded["borrowing_programme_closure"]["evidence"]
    reconciliation = {
        "four_exact_artifact_zip_hashes_verified": True,
        "four_exact_evidence_hashes_verified": True,
        "four_exact_report_hashes_verified": True,
        "four_family_issue_head_and_verdict_identities_verified": True,
        "intermediate_two_group_closure_has_zero_admissible_groups": (
            prior_closure["admissible_groups"] == 0
        ),
        "intermediate_groups_match_quantity_and_rate": (
            [row["family_id"] for row in prior_closure["groups"]]
            == [
                ARTIFACTS["borrow_demand_quantity"]["family_id"],
                ARTIFACTS["borrow_rate"]["family_id"],
            ]
        ),
    }
    acceptance = {
        "at_least_one_direct_provider_defined_anonymous_public_object": any(
            group["direct_provider_defined_object"] and group["anonymous_public"]
            for group in groups
        ),
        "at_least_one_bilateral_source_feasible_object": any(
            group["bilateral_source_feasible"] for group in groups
        ),
        "same_object_has_complete_native_1h_frozen_sample": any(
            group["bilateral_source_feasible"] and group["complete_native_1h_frozen_sample"]
            for group in groups
        ),
        "same_object_has_30_distinct_values_and_positive_iqr_in_both_arms": any(
            group["both_arms_at_least_30_distinct_and_positive_iqr"] for group in groups
        ),
        "same_object_supports_nonconstant_bilateral_lagged_state": any(
            group["nonconstant_bilateral_lagged_state"] for group in groups
        ),
        "at_least_one_admissible_bilateral_mechanism": any(group["admissible"] for group in groups),
        "all_prior_identities_and_hashes_reconcile": all(reconciliation.values()),
    }
    leave_one_out = []
    for removed in groups:
        remaining = [group for group in groups if group["group"] != removed["group"]]
        leave_one_out.append(
            {
                "removed_group": removed["group"],
                "remaining_groups": [group["group"] for group in remaining],
                "remaining_admissible_mechanisms": sum(group["admissible"] for group in remaining),
                "programme_admissible": any(group["admissible"] for group in remaining),
            }
        )
    return {
        "family_id": FAMILY_ID,
        "issue": ISSUE,
        "classification": "zero-candidate strategy-family evidence closure",
        "tested_head": tested_head,
        "repository_main": REPOSITORY_MAIN,
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
        "credentials_private_endpoints_accounts_orders_leverage_or_adapters_used": False,
        "synthetic_or_non_1h_data_used": False,
        "cross_sectional_relative_rank_pairs_spreads_or_market_neutral_used": False,
        "post_hoc_asset_filtering_used": False,
        "groups": groups,
        "completed_group_count": len(groups),
        "admissible_group_count": sum(group["admissible"] for group in groups),
        "artifact_reconciliation": reconciliation,
        "acceptance_gates": acceptance,
        "gates_passing": sum(acceptance.values()),
        "gates_total": len(acceptance),
        "leave_one_group_out": leave_one_out,
        "economics": dict(NULL_ECONOMICS),
        "closed_rescue_paths": CLOSED_RESCUE_PATHS,
        "highest_value_failure": (
            "The only complete bilateral public object is borrow rate, but its BTC arm has zero "
            "temporal variation. Demand quantity is absent and the margin lending ratio cannot "
            "supply the exact frozen 2023-2025 native-hour calendar."
        ),
        "verdict": VERDICT,
    }


def build_report(evidence: dict[str, Any]) -> str:
    groups = evidence["groups"]
    rate = groups[1]["target_arms"]
    return f"""# Public spot-margin balance-sheet crowding programme closure 1H v1

```text
family                  {evidence['family_id']}
canonical main          {evidence['repository_main']}
exact evidence head     {evidence['tested_head']}
completed groups        {evidence['completed_group_count']}
admissible groups       {evidence['admissible_group_count']}
candidate count         {evidence['candidate_count']}
parameter grid          {evidence['parameter_grid_count']}
new market/OOS rows     {evidence['new_market_data_rows']}/{evidence['new_oos_observations']}
verdict                 {evidence['verdict']}
```

## Strategy-facing closure

| Mechanism | BTC result | ETH result | Bilaterally admissible |
|---|---|---|---:|
| Borrow-demand quantity | direct amount absent | direct amount absent | no |
| Borrow rate | {rate['BTC']['distinct_count']} value; IQR {rate['BTC']['iqr']:.3f} | {rate['ETH']['distinct_count']} values; IQR {rate['ETH']['iqr']:.3f} | no |
| Spot-margin lending ratio | 0 rows in three frozen probes | 0 rows in three frozen probes | no |

The quantity fields are deprecated and empty. The borrow-rate panel is complete for 24,144 hours per asset, but BTC is exactly 0.01 throughout. All six margin-ratio probes returned provider code 50030 (`Illegal time range`) with empty data. No completed mechanism can define a nonconstant bilateral causal state under the frozen source contract.

## Frozen acceptance gates

{chr(10).join(f'- {name}: **{"pass" if value else "fail"}**' for name, value in evidence['acceptance_gates'].items())}

Every leave-one-group-out subset retains zero admissible mechanisms. The prior two-group borrowing closure was independently rebound and reconciled before adding the margin-ratio evidence.

## Economics

No target prices, returns, E2160 states, candidates, benchmark paths or OOS observations were accessed. Train/OOS/full return and Sharpe, benchmark comparison, turnover, fee drag, maximum drawdown, edge per turnover, fold/year breadth, dependence-aware uncertainty and one-hour-delay economics are null rather than zero. Exactly 5 bps one way remains mandatory for any separately authorised executable strategy.

## Verdict

**{evidence['verdict']}**

The completed direct-public spot-margin balance-sheet crowding programme is closed against quantity reconstruction, adjacent-field substitution, transforms of the constant BTC rate, shortened history, interpolation, provider stitching, target replacement, single-market promotion, private/account data and post-hoc filtering.
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tested-head", required=True)
    parser.add_argument("--prior-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp_dir:
        loaded = extract_and_verify(args.prior_dir, Path(temp_dir))
        evidence = build_evidence(args.tested_head, loaded)
    evidence_hash = write_hashed(args.output_dir, "evidence.json", canonical(evidence))
    records = {
        key: {
            "artifact_id": value["artifact_id"],
            "artifact_zip_sha256": value["zip_sha256"],
            "evidence_json_sha256": value["evidence_sha256"],
            "report_sha256": value["report_sha256"],
            "family_id": value["family_id"],
            "verdict": value["verdict"],
            "issue": value["issue"],
            "pull_request": value["pr"],
            "exact_evidence_head": value["head"],
            "focused_workflow_run": value["workflow_run"],
        }
        for key, value in ARTIFACTS.items()
    }
    records_hash = write_hashed(args.output_dir, "source_records.json", canonical(records))
    report_hash = write_hashed(args.output_dir, "report.md", build_report(evidence).encode())
    summary = {
        "family_id": FAMILY_ID,
        "tested_head": args.tested_head,
        "evidence_json_sha256": evidence_hash,
        "source_records_json_sha256": records_hash,
        "report_sha256": report_hash,
        "verdict": VERDICT,
    }
    write_hashed(args.output_dir, "artifact_summary.json", canonical(summary))


if __name__ == "__main__":
    main()
