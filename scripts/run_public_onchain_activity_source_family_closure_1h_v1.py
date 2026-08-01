from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FAMILY_ID = "causal-public-onchain-activity-source-family-closure-1h-v1"
VERDICT = "reject_causal_public_onchain_activity_source_family_1h_v1"
REPOSITORY_MAIN = "5a0fcc97d1a882f8223656c51f5bb8055f534e38"

NULL_ECONOMICS = {
    "train_net_return": None,
    "train_sharpe": None,
    "oos_net_return": None,
    "oos_sharpe": None,
    "full_net_return": None,
    "full_sharpe": None,
    "benchmark_net_return": None,
    "benchmark_sharpe": None,
    "turnover": None,
    "modeled_fees": None,
    "edge_per_turnover_bps": None,
    "maximum_drawdown": None,
    "fold_breadth": None,
    "calendar_breadth": None,
    "dependence_aware_uncertainty": None,
    "one_hour_delay": None,
}


def canonical(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build(tested_head: str) -> dict[str, Any]:
    groups = [
        {
            "group_id": "coinmetrics_community_txcnt_direct_1h",
            "issue": 891,
            "pull_request": 893,
            "tested_head": "7f057d8679f1797cd7f8973f962ab37dff41ef22",
            "workflow_run": 30708866223,
            "artifact_id": 8821217482,
            "evidence_sha256": "4e036f804ef1efc9ba20845c18e9f07edf2cb629d63801ec9be26a9262658a38",
            "report_sha256": "62dd8c1253a9601d3fabd5c19eed96064041e8ee0cdeb1bfaf4b198639260392",
            "metric": "TxCnt",
            "fixed_assets": ["doge", "ltc"],
            "requested_frequency": "1h",
            "source_contract_passed": False,
            "source_arms_passing": 0,
            "source_arm_count": 2,
            "failure": (
                "The frozen credential-free doge/TxCnt/1h request returned HTTP 400 under both "
                "10,000-row and 2,000-row page sizes with identical response-body identity."
            ),
            "response_body_sha256": "40a4a5ffb815160e10c7ee51e0dfe188dd19b6f021b91ab7c9a299d63b49e9f1",
            "feature_defined": False,
            "target_returns_accessed": False,
            "performance_accessed": False,
            "oos_accessed": False,
            "economics": dict(NULL_ECONOMICS),
            "terminal_verdict": (
                "reject_causal_onchain_transaction_activity_confirmed_e2160_entry_source_contract"
            ),
        },
        {
            "group_id": "coinmetrics_community_feetotusd_direct_1h",
            "issue": 924,
            "pull_request": 925,
            "tested_head": "9a8e89581ba0c2860406bfade7b04f60c2119856",
            "workflow_run": 30721703761,
            "artifact_id": 8825056911,
            "artifact_sha256": "f9353f6cf891cf34abfa3b8822a3376e66ef5399f16392b925e7e2c075b0120a",
            "metric": "FeeTotUSD",
            "fixed_assets": ["btc", "eth"],
            "requested_frequency": "1h",
            "official_semantics_verified": True,
            "source_contract_passed": False,
            "source_arms_passing": 0,
            "source_arm_count": 2,
            "failure": (
                "Both fixed credential-free direct-1H requests returned HTTP 403 stating that "
                "the requested metric/frequency was unavailable."
            ),
            "feature_defined": False,
            "target_returns_accessed": False,
            "performance_accessed": False,
            "oos_accessed": False,
            "economics": dict(NULL_ECONOMICS),
            "terminal_verdict": "reject_causal_onchain_fee_pressure_source_contract_1h_v1",
        },
    ]
    gates = {
        "published_evidence_identities_bound": True,
        "zero_new_candidates_data_returns_or_oos": True,
        "bilateral_direct_public_1h_source_contract": False,
        "source_executable_architecture_present": False,
        "causal_lagged_feature_authorized": False,
        "target_return_access_authorized": False,
        "bilateral_strategy_economics_available": False,
        "temporal_breadth_uncertainty_and_delay_available": False,
        "training_authorized_correction_present": False,
        "leave_one_group_out_support": False,
    }
    return {
        "schema_version": "public-onchain-activity-source-family-closure-1h-v1",
        "family_id": FAMILY_ID,
        "tested_head": tested_head,
        "repository_main": REPOSITORY_MAIN,
        "generated_at_utc": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        "bar": "1H",
        "canonical_fee_bps_one_way": 5.0,
        "architecture_group_count": len(groups),
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "new_market_data": 0,
        "new_target_returns": 0,
        "new_oos_consumed": 0,
        "credentials_used": False,
        "private_endpoints_used": False,
        "accounts_or_orders": False,
        "enabled_adapters": False,
        "leverage_or_funds": False,
        "synthetic_data_used": False,
        "non_1h_input_used": False,
        "cross_sectional_selection": False,
        "pairs_or_spreads": False,
        "market_neutral_or_long_short": False,
        "source_groups": groups,
        "family_gates": gates,
        "family_gate_pass_count": sum(gates.values()),
        "family_gate_count": len(gates),
        "source_valid_group_count": sum(group["source_contract_passed"] for group in groups),
        "source_executable_group_count": 0,
        "performance_authorized_group_count": 0,
        "economically_supportive_group_count": 0,
        "leave_one_group_out_support_count": 0,
        "highest_value_failure_mechanism": (
            "The family failed before strategy construction: official metric semantics existed, "
            "but the credential-free Community API did not expose the frozen direct 1H metric "
            "contracts. This is a provider-access/source-frequency rejection, not evidence of "
            "economic underperformance."
        ),
        "closed_rescue_paths": [
            "alternate TxCnt or FeeTotUSD windows, lags, thresholds or smoothing",
            "daily-to-hourly expansion or local sub-hour aggregation",
            "single-market promotion or target substitution",
            "metric aliases, provider switching, keyed or paid endpoints",
            "interpolation, forward fill, zero fill or calendar shortening",
            "combining the two failed contracts into an ensemble",
        ],
        "training_authorized_correction": {
            "permitted": False,
            "applied": False,
            "canonical_policy_changed": False,
            "observation_epoch_restarted": False,
            "reason": "no source group reached an executable causal feature or target-return gate",
        },
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "verdict": VERDICT,
    }


def write(output_dir: Path, evidence: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = canonical(evidence)
    evidence_sha = digest(payload)
    (output_dir / "evidence.json").write_bytes(payload)
    (output_dir / "evidence.sha256").write_text(evidence_sha + "\n")

    lines = [
        "# Credential-free public on-chain activity source-family closure",
        "",
        f"- Family: `{FAMILY_ID}`",
        f"- Architecture groups: `{evidence['architecture_group_count']}`",
        f"- Source-valid groups: `{evidence['source_valid_group_count']}`",
        f"- Family gates passed: `{evidence['family_gate_pass_count']}/{evidence['family_gate_count']}`",
        f"- New candidates/data/returns/OOS: `0 / 0 / 0 / 0`",
        f"- Verdict: `{VERDICT}`",
        "",
        "| Group | Metric | Fixed arms | Source result | Feature/performance/OOS |",
        "|---|---|---|---|---|",
    ]
    for group in evidence["source_groups"]:
        lines.append(
            f"| {group['group_id']} | {group['metric']} | {', '.join(group['fixed_assets'])} | "
            f"{group['source_arms_passing']}/{group['source_arm_count']} pass | "
            f"false / false / false |"
        )
    lines.extend(
        [
            "",
            "All return, Sharpe, benchmark, turnover, fee, drawdown, edge-per-turnover, fold, "
            "calendar, uncertainty and delayed-execution fields remain null because neither "
            "architecture passed its frozen bilateral source contract.",
            "",
            "Highest-value failure mechanism: " + evidence["highest_value_failure_mechanism"],
            "",
            "No correction, canonical mutation, observation-epoch restart, paper authority or "
            "live authority is permitted.",
            "",
            f"Evidence SHA-256: `{evidence_sha}`",
            "",
        ]
    )
    report = "\n".join(lines)
    (output_dir / "report.md").write_text(report)
    (output_dir / "report.sha256").write_text(digest(report.encode()) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tested-head", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    evidence = build(args.tested_head)
    write(args.output_dir, evidence)
    print(json.dumps(evidence, sort_keys=True, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
