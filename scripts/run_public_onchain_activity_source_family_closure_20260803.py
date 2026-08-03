#!/usr/bin/env python3
"""Deterministically close the completed credential-free public on-chain source family."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FAMILY_ID = "causal-public-onchain-activity-source-family-closure-1h-v2"
ISSUE_NUMBER = 1033
VERDICT = "reject_causal_public_onchain_activity_source_family_1h_v2"
OUT = Path("reports/experiments") / FAMILY_ID

NULL_ECONOMICS: dict[str, Any] = {
    "training_net_return": None,
    "training_sharpe": None,
    "oos_net_return": None,
    "oos_sharpe": None,
    "full_net_return": None,
    "full_sharpe": None,
    "benchmark_return": None,
    "benchmark_residual": None,
    "turnover": None,
    "modeled_fees": None,
    "edge_per_turnover_bps": None,
    "maximum_drawdown": None,
    "fold_year_breadth": None,
    "dependence_aware_uncertainty": None,
    "one_hour_delay_economics": None,
}

GROUPS: tuple[dict[str, Any], ...] = (
    {
        "group_id": "community-txcnt-doge-ltc",
        "metric": "TxCnt",
        "unit": "transaction_count",
        "targets": ["DOGE-USDT", "LTC-USDT"],
        "issue": 891,
        "pull_request": 893,
        "exact_evidence_head": "7f057d8679f1797cd7f8973f962ab37dff41ef22",
        "artifact_id": 8821217482,
        "artifact_sha256": "334241a050405fdd948112dada4af46a6de6c63a939b0569a2c7a110697d2f3d",
        "evidence_sha256": "4e036f804ef1efc9ba20845c18e9f07edf2cb629d63801ec9be26a9262658a38",
        "source_arms_passing": 0,
        "source_arm_count": 2,
        "failure_stage": "doge_primary",
        "provider_status": 400,
        "provider_response_sha256": "40a4a5ffb815160e10c7ee51e0dfe188dd19b6f021b91ab7c9a299d63b49e9f1",
        "credential_free_bilateral_provider_native_1h": False,
        "source_executable_architecture": False,
        "target_returns_accessed": False,
        "performance_accessed": False,
        "oos_accessed": False,
        "verdict": "reject_causal_onchain_transaction_activity_confirmed_e2160_entry_source_contract",
    },
    {
        "group_id": "community-feetotusd-btc-eth",
        "metric": "FeeTotUSD",
        "unit": "usd",
        "targets": ["BTC-USDT", "ETH-USDT"],
        "issue": 924,
        "pull_request": 925,
        "exact_evidence_head": "9a8e89581ba0c2860406bfade7b04f60c2119856",
        "artifact_id": 8825056911,
        "artifact_sha256": "f9353f6cf891cf34abfa3b8822a3376e66ef5399f16392b925e7e2c075b0120a",
        "evidence_sha256": "05edc18af101a59cbfb84245711844b8cf90632407ecee8f2be09e76347579f3",
        "source_arms_passing": 0,
        "source_arm_count": 2,
        "failure_stage": "bilateral_timeseries_access",
        "provider_status": 403,
        "provider_response_sha256": {
            "btc": "140693866bf6ba60fa3bcd4ed98e7c9a3aff1bcbe031708f13c9f486fecafb58",
            "eth": "7b16472e6771e03e5d98246f5a4ca9deb29ff8dc759fba9e920808548a28b20d",
        },
        "credential_free_bilateral_provider_native_1h": False,
        "source_executable_architecture": False,
        "target_returns_accessed": False,
        "performance_accessed": False,
        "oos_accessed": False,
        "verdict": "reject_causal_onchain_fee_pressure_source_contract_1h_v1",
    },
    {
        "group_id": "community-feetotntv-btc-eth",
        "metric": "FeeTotNtv",
        "unit": "native_asset",
        "targets": ["BTC-USDT", "ETH-USDT"],
        "issue": 1030,
        "pull_request": 1032,
        "exact_evidence_head": "4127e10d75166e23b6739e2d3595da59c6c2b0f7",
        "workflow_run": 30791409820,
        "artifact_id": 8847177217,
        "artifact_sha256": "e52083bfcff3c354e1a09ab874ed796215a8fb1292b41adbce9e80ba845c0750",
        "evidence_sha256": "2e4dc94da870be0e7f73070e9793548e41500bd45ee101dc9181163c5a98e849",
        "source_arms_passing": 0,
        "source_arm_count": 2,
        "failure_stage": "btc_primary",
        "provider_status": 403,
        "provider_response_sha256": "643864904bcb86cd03bb167745c3531af396262e0d4d2532b7e3fd58e1be7d01",
        "credential_free_bilateral_provider_native_1h": False,
        "source_executable_architecture": False,
        "target_returns_accessed": False,
        "performance_accessed": False,
        "oos_accessed": False,
        "verdict": "reject_causal_onchain_native_fee_pressure_source_contract_1h_v1",
    },
)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def leave_one_group_out() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for omitted in GROUPS:
        retained = [group for group in GROUPS if group is not omitted]
        rows.append(
            {
                "omitted_group_id": omitted["group_id"],
                "retained_group_ids": [group["group_id"] for group in retained],
                "retained_group_count": len(retained),
                "bilateral_executable_source_contract_present": any(
                    group["credential_free_bilateral_provider_native_1h"]
                    and group["source_executable_architecture"]
                    for group in retained
                ),
                "target_return_access_authorized": any(
                    group["target_returns_accessed"] for group in retained
                ),
                "strategy_economics_present": any(
                    group["performance_accessed"] for group in retained
                ),
                "family_supportive": False,
            }
        )
    return rows


def build_evidence(exact_head: str) -> dict[str, Any]:
    if len(exact_head) != 40 or any(ch not in "0123456789abcdef" for ch in exact_head):
        raise ValueError("exact_head must be a lowercase 40-character commit SHA")
    questions = {
        "bilateral_credential_free_provider_native_1h_source_contract": False,
        "source_executable_causal_lagged_same_instrument_feature": False,
        "target_return_access_authorized": False,
        "bilateral_training_oos_or_full_strategy_economics": False,
        "benchmark_turnover_drawdown_breadth_uncertainty_or_delay_evidence": False,
        "evidence_fee_pressure_or_activity_improves_e2160_at_5bps": False,
    }
    return {
        "schema_version": "public-onchain-activity-family-closure-v2",
        "family_id": FAMILY_ID,
        "issue": ISSUE_NUMBER,
        "exact_head": exact_head,
        "generated_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        "classification": "completed-evidence source-family closure",
        "bar": "1H",
        "canonical_fee_bps_one_way": 5.0,
        "architecture_group_count": len(GROUPS),
        "supportive_group_count": 0,
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "new_market_data_rows": 0,
        "new_target_returns": 0,
        "new_oos_consumed": 0,
        "public_data_only": True,
        "credentials_used": False,
        "private_endpoints_used": False,
        "actual_orders": False,
        "enabled_adapters": False,
        "leverage_or_funds": False,
        "synthetic_data": False,
        "cross_sectional_or_contemporaneous_selection": False,
        "groups": [dict(group) for group in GROUPS],
        "questions": questions,
        "leave_one_group_out": leave_one_group_out(),
        "economics": dict(NULL_ECONOMICS),
        "highest_value_failure": (
            "The expanded family never established one bilateral credential-free "
            "provider-native 1H source contract. TxCnt failed at the first DOGE "
            "request and both USD- and native-unit fee contracts were unavailable "
            "at direct Community 1H resolution without credentials. The failure is "
            "source accessibility and retention, not evidence that on-chain activity "
            "or fee pressure lacks economic information."
        ),
        "closure_boundary": (
            "Close Community TxCnt, FeeTotUSD and FeeTotNtv, including aliases, unit "
            "substitutions, combinations, altered windows, lags, smoothing, signs, "
            "daily expansion, interpolation, shortened calendars and single-market "
            "promotion. A materially different direct public provider-native 1H "
            "object requires a separately preregistered architecture."
        ),
        "correction_authority": False,
        "canonical_strategy_changed": False,
        "observation_epoch_restarted": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "verdict": VERDICT,
    }


def persist(output_dir: Path, evidence: dict[str, Any]) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    evidence_payload = canonical_json(evidence)
    evidence_path = output_dir / "evidence.json"
    evidence_path.write_text(evidence_payload, encoding="utf-8")
    evidence_sha = sha256_bytes(evidence_payload.encode("utf-8"))
    (output_dir / "evidence.sha256").write_text(evidence_sha + "\n", encoding="utf-8")

    report = (
        "# Expanded credential-free public on-chain activity family closure\n\n"
        f"Verdict: `{evidence['verdict']}`\n\n"
        "No completed group established a bilateral anonymous provider-native 1H "
        "source contract. Consequently no causal feature, target-return access, "
        "strategy economics, correction or prospective epoch restart was authorised.\n\n"
        "All unavailable economics are null rather than zero.\n\n"
        f"Evidence SHA-256: `{evidence_sha}`\n"
    )
    report_path = output_dir / "report.md"
    report_path.write_text(report, encoding="utf-8")
    report_sha = sha256_bytes(report.encode("utf-8"))
    (output_dir / "report.sha256").write_text(report_sha + "\n", encoding="utf-8")

    manifest = {
        "family_id": FAMILY_ID,
        "files": {
            "evidence.json": evidence_sha,
            "report.md": report_sha,
        },
    }
    manifest_payload = canonical_json(manifest)
    manifest_path = output_dir / "artifact-manifest.json"
    manifest_path.write_text(manifest_payload, encoding="utf-8")
    manifest_sha = sha256_bytes(manifest_payload.encode("utf-8"))
    (output_dir / "manifest.sha256").write_text(manifest_sha + "\n", encoding="utf-8")
    return {
        "evidence_sha256": evidence_sha,
        "report_sha256": report_sha,
        "manifest_sha256": manifest_sha,
    }


def validate(evidence: dict[str, Any]) -> None:
    assert evidence["family_id"] == FAMILY_ID
    assert evidence["architecture_group_count"] == 3
    assert evidence["supportive_group_count"] == 0
    assert evidence["candidate_count"] == 0
    assert evidence["parameter_grid_count"] == 0
    assert evidence["new_market_data_rows"] == 0
    assert evidence["new_target_returns"] == 0
    assert evidence["new_oos_consumed"] == 0
    assert all(group["source_arms_passing"] == 0 for group in evidence["groups"])
    assert all(not value for value in evidence["questions"].values())
    assert all(row["family_supportive"] is False for row in evidence["leave_one_group_out"])
    assert all(value is None for value in evidence["economics"].values())
    assert evidence["correction_authority"] is False
    assert evidence["canonical_strategy_changed"] is False
    assert evidence["observation_epoch_restarted"] is False
    assert evidence["paper_trading_authorized"] is False
    assert evidence["live_trading_authorized"] is False
    assert evidence["verdict"] == VERDICT


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=OUT)
    args = parser.parse_args()
    exact_head = os.environ.get("GITHUB_SHA", "")
    evidence = build_evidence(exact_head)
    validate(evidence)
    hashes = persist(args.output_dir, evidence)
    print(canonical_json({"evidence": evidence, "hashes": hashes}), end="")


if __name__ == "__main__":
    main()
