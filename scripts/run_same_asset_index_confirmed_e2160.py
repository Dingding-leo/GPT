#!/usr/bin/env python3
"""Frozen public-data evaluation for issue #889; no accounts, orders, or private APIs."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from same_asset_index_metrics import evaluate_market, support_record
from same_asset_index_source import (
    BAR,
    BASE_URL,
    END_MS,
    EXPECTED_ROWS,
    FAMILY_ID,
    FEE,
    FULL_END,
    HOUR_MS,
    INDEX_ENDPOINT,
    MARKETS,
    OOS_END,
    OUT,
    PROTOCOL_SIGNATURE,
    SOURCE,
    SPOT_ENDPOINT,
    START_MS,
    TRAIN_END,
    WARMUP_END,
    Series,
    SourceContractError,
    acquire_series,
    canonical_bytes,
    sha256_bytes,
    sha256_file,
    utc_iso,
)


def null_market_record(
    target: str, index: str, support: dict[str, Any] | None
) -> dict[str, Any]:
    return {
        "target": target,
        "index": index,
        "training_support": support,
        "performance_accessed": False,
        "strategies": None,
        "oos_folds": None,
        "oos_years": None,
        "paired_uncertainty": None,
        "one_hour_delay_oos": None,
        "gates": None,
        "passes_individual_gates": False,
    }


def write_evidence(evidence: dict[str, Any]) -> str:
    evidence_path = OUT / "evidence.json"
    evidence_path.write_bytes(canonical_bytes(evidence))
    digest = sha256_file(evidence_path)
    (OUT / "evidence.sha256").write_text(digest + "\n")
    return digest


def metric(value: float | None, format_spec: str) -> str:
    if value is None:
        return "undefined"
    return format(value, format_spec)


def make_report(evidence: dict[str, Any]) -> str:
    lines = [
        "# Same-asset composite-index confirmed E2160 entry",
        "",
        f"- Family: `{FAMILY_ID}`",
        f"- Exact head: `{evidence['exact_head']}`",
        f"- Fee: exactly `{FEE * 10_000:.1f}` bps one way",
        f"- Candidate count: `{evidence['candidate_count']}`",
        f"- Parameter grid: `{evidence['parameter_grid_count']}`",
        f"- Verdict: `{evidence['verdict']}`",
        "",
    ]
    if not evidence["source_contract_passed"]:
        lines.extend(
            [
                "## Source-contract rejection",
                "",
                f"`{evidence['source_failure']}`",
                "",
                "Performance fields are null and sealed OOS was not evaluated.",
            ]
        )
        return "\n".join(lines) + "\n"
    if not evidence["bilateral_training_support_passed"]:
        lines.extend(
            [
                "## Training-support rejection",
                "",
                "The preregistered index-veto support gate failed before OOS performance access.",
                "",
            ]
        )
        for market in evidence["markets"]:
            support = market["training_support"]
            lines.append(
                f"- {market['target']}: {support['training_vetoes']} vetoes across "
                f"{support['distinct_veto_quarters']} quarters; pass={support['passes']}."
            )
        return "\n".join(lines) + "\n"

    lines.extend(
        [
            "| Market | Candidate OOS | Sharpe | E2160 OOS | E2160 Sharpe | "
            "Always-long | Turnover | Edge/turn | Max DD | Gates |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for market in evidence["markets"]:
        candidate = market["strategies"]["candidate"]["oos"]
        e2160 = market["strategies"]["e2160"]["oos"]
        always = market["strategies"]["always_long"]["oos"]
        lines.append(
            f"| {market['target']} | {candidate['net_compound_return']:+.4%} | "
            f"{metric(candidate['annualised_hourly_sharpe'], '+.4f')} | "
            f"{e2160['net_compound_return']:+.4%} | "
            f"{metric(e2160['annualised_hourly_sharpe'], '+.4f')} | "
            f"{always['net_compound_return']:+.4%} | "
            f"{candidate['one_way_turnover']:.0f} | "
            f"{metric(candidate['edge_per_turnover_bps'], '+.2f')} bps | "
            f"{candidate['maximum_drawdown']:+.4%} | "
            f"{market['gates_passed_with_bilateral']}/16 |"
        )
    lines.extend(["", "## Highest-value failure", "", evidence["highest_value_failure"]])
    return "\n".join(lines) + "\n"


def source_rejection(
    *, exact_head: str, manifest: list[dict[str, Any]], failure: Exception
) -> dict[str, Any]:
    return {
        "family_id": FAMILY_ID,
        "classification": "executable causal exogenous-information strategy",
        "exact_head": exact_head,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "canonical_fee_bps_one_way": 5.0,
        "bar_interval": "1H",
        "public_data_only": True,
        "credentials_private_endpoints_accounts_orders_adapters_leverage_funds": False,
        "cross_sectional_or_contemporaneous_selection": False,
        "candidate_count": 2,
        "parameter_grid_count": 0,
        "source_contract_passed": False,
        "source_failure": f"{type(failure).__name__}: {failure}",
        "source_manifest_partial": manifest,
        "performance_accessed": False,
        "oos_accessed": False,
        "markets": [
            null_market_record(pair["target"], pair["index"], None)
            for pair in MARKETS
        ],
        "markets_passing_all_gates": 0,
        "verdict": (
            "reject_causal_same_asset_composite_index_confirmed_e2160_entry_"
            "source_contract"
        ),
        "canonical_strategy_changed": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    SOURCE.mkdir(parents=True, exist_ok=True)
    exact_head = os.environ.get("GITHUB_SHA", "local")
    all_manifest: list[dict[str, Any]] = []
    series: dict[str, Series] = {}
    try:
        for pair in MARKETS:
            for inst_id, endpoint in (
                (pair["target"], SPOT_ENDPOINT),
                (pair["index"], INDEX_ENDPOINT),
            ):
                acquired, manifest = acquire_series(inst_id, endpoint)
                series[inst_id] = acquired
                all_manifest.extend(manifest)
        reference = series[MARKETS[0]["target"]].open_ms
        for acquired in series.values():
            if not np.array_equal(reference, acquired.open_ms):
                raise SourceContractError("fixed spot/index calendars do not match")
    except SourceContractError as exc:
        evidence = source_rejection(
            exact_head=exact_head, manifest=all_manifest, failure=exc
        )
        digest = write_evidence(evidence)
        report = make_report(evidence)
        (OUT / "report.md").write_text(report)
        print(report)
        print(f"evidence_sha256={digest}")
        return

    source_contract = {
        "provider": "OKX public market data",
        "base_url": BASE_URL,
        "bar": BAR,
        "requested_start": utc_iso(START_MS),
        "requested_end_inclusive": utc_iso(END_MS - HOUR_MS),
        "expected_rows_per_series": EXPECTED_ROWS,
        "series": [item for market in MARKETS for item in market.values()],
        "page_response_count": len(all_manifest),
        "response_total_bytes": sum(row["response_bytes"] for row in all_manifest),
        "manifest": all_manifest,
    }
    manifest_path = OUT / "source-manifest.json"
    manifest_path.write_bytes(canonical_bytes(source_contract))
    support_by_target = {
        pair["target"]: support_record(
            series[pair["target"]], series[pair["index"]]
        )
        for pair in MARKETS
    }
    freeze = {
        "family_id": FAMILY_ID,
        "protocol_signature": PROTOCOL_SIGNATURE,
        "protocol_sha256": sha256_bytes(PROTOCOL_SIGNATURE.encode()),
        "script_sha256": sha256_file(Path(__file__)),
        "source_module_sha256": sha256_file(
            Path(__file__).with_name("same_asset_index_source.py")
        ),
        "metrics_module_sha256": sha256_file(
            Path(__file__).with_name("same_asset_index_metrics.py")
        ),
        "source_manifest_sha256": sha256_file(manifest_path),
        "exact_head": exact_head,
        "performance_seen_before_freeze": False,
        "oos_accessed_before_freeze": False,
        "training_support": support_by_target,
        "frozen_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    (OUT / "freeze.json").write_bytes(canonical_bytes(freeze))
    bilateral_support = all(record["passes"] for record in support_by_target.values())
    if not bilateral_support:
        markets = [
            null_market_record(
                pair["target"], pair["index"], support_by_target[pair["target"]]
            )
            for pair in MARKETS
        ]
        evidence = {
            "family_id": FAMILY_ID,
            "classification": "executable causal exogenous-information strategy",
            "exact_head": exact_head,
            "generated_at": datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "canonical_fee_bps_one_way": 5.0,
            "bar_interval": "1H",
            "public_data_only": True,
            "credentials_private_endpoints_accounts_orders_adapters_leverage_funds": False,
            "cross_sectional_or_contemporaneous_selection": False,
            "candidate_count": 2,
            "parameter_grid_count": 0,
            "source_contract_passed": True,
            "source_contract": source_contract,
            "freeze": freeze,
            "bilateral_training_support_passed": False,
            "performance_accessed": False,
            "oos_accessed": False,
            "markets": markets,
            "markets_passing_all_gates": 0,
            "highest_value_failure": (
                "The same-asset index did not create the preregistered bilateral "
                "training entry-veto support, so sealed OOS performance remained unread."
            ),
            "verdict": (
                "reject_causal_same_asset_composite_index_confirmed_e2160_entry_1h_v1"
            ),
            "canonical_strategy_changed": False,
            "paper_trading_authorized": False,
            "live_trading_authorized": False,
        }
        digest = write_evidence(evidence)
        report = make_report(evidence)
        (OUT / "report.md").write_text(report)
        print(report)
        print(f"evidence_sha256={digest}")
        return

    markets = [
        evaluate_market(
            series[pair["target"]],
            series[pair["index"]],
            support_by_target[pair["target"]],
        )
        for pair in MARKETS
    ]
    bilateral = all(market["passes_individual_gates"] for market in markets)
    for market in markets:
        market["gates"]["16_bilateral_replication"] = bilateral
        market["gates_passed_with_bilateral"] = sum(market["gates"].values())
        market["passes_all_gates"] = all(market["gates"].values())
        market["performance_accessed"] = True
    accepted = all(market["passes_all_gates"] for market in markets)
    failures = []
    for market in markets:
        candidate = market["strategies"]["candidate"]["oos"]
        e2160 = market["strategies"]["e2160"]["oos"]
        failed = [name for name, passed in market["gates"].items() if not passed]
        failures.append(
            f"{market['target']} failed {len(failed)}/16 gates "
            f"({', '.join(failed)}); candidate OOS net "
            f"{candidate['net_compound_return']:+.4%} versus E2160 "
            f"{e2160['net_compound_return']:+.4%}."
        )
    verdict = (
        "accept_causal_same_asset_composite_index_confirmed_e2160_entry_1h_v1"
        if accepted
        else "reject_causal_same_asset_composite_index_confirmed_e2160_entry_1h_v1"
    )
    evidence = {
        "family_id": FAMILY_ID,
        "classification": "executable causal exogenous-information strategy",
        "exact_head": exact_head,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "canonical_fee_bps_one_way": 5.0,
        "bar_interval": "1H",
        "public_data_only": True,
        "credentials_private_endpoints_accounts_orders_adapters_leverage_funds": False,
        "cross_sectional_or_contemporaneous_selection": False,
        "candidate_count": 2,
        "parameter_grid_count": 0,
        "source_contract_passed": True,
        "source_contract": source_contract,
        "freeze": freeze,
        "bilateral_training_support_passed": True,
        "performance_accessed": True,
        "oos_accessed": True,
        "sample": {
            "warmup": [0, WARMUP_END],
            "training": [WARMUP_END, TRAIN_END],
            "sealed_oos": [TRAIN_END, OOS_END],
            "full_scored": [WARMUP_END, FULL_END],
            "unscored_suffix": [FULL_END, EXPECTED_ROWS],
            "oos_folds": 6,
            "oos_years": 2,
        },
        "markets": markets,
        "markets_passing_all_gates": sum(
            market["passes_all_gates"] for market in markets
        ),
        "highest_value_failure": " ".join(failures),
        "verdict": verdict,
        "canonical_strategy_changed": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "next_strategy_action": (
            "If accepted, freeze an independent prospective shadow epoch before any "
            "promotion. If rejected, close same-asset index entry confirmation on this "
            "cohort and preregister a materially orthogonal temporal information source."
        ),
    }
    digest = write_evidence(evidence)
    report = make_report(evidence)
    (OUT / "report.md").write_text(report)
    print(report)
    print(f"evidence_sha256={digest}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ABORT: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
