from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_1800 as base
import run_prospective_simple_trend_shadow_20260801_0100 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_538_800_000
REALIZED_DECISION_HOUR_MS = 1_785_542_400_000
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_546_000_000
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_549_600_000
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_528_000_000
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "873367c0b2c943b7420f05294e670a9cff608a69df772521d4e1c9239b71ac5a"
PRIOR_ARTIFACT_SHA256 = "e7f48b593b5cc6cf5907574df1d418507db1cfe8dd855a57148b6d6b881182"


def configure() -> None:
    for name in (
        "PREVIOUS_DECISION_HOUR_MS",
        "REALIZED_DECISION_HOUR_MS",
        "PRIOR_REPORTED_SIGNAL_HOUR_MS",
        "LATEST_COMPLETE_SIGNAL_HOUR_MS",
        "RECENT_WINDOW_FIRST_DECISION_HOUR_MS",
        "RECENT_WINDOW_LAST_DECISION_HOUR_MS",
        "PRIOR_RESULT_SHA256",
        "PRIOR_ARTIFACT_SHA256",
    ):
        setattr(prior, name, globals()[name])


def pct(value: float | None) -> str:
    return "undefined" if value is None else f"{100.0 * value:+.6f}%"


def report(output_dir: Path, result: dict[str, Any]) -> None:
    lines = [
        "# Prospective simple-trend shadow through 02:00 UTC on 1 August 2026",
        "",
        f"- Policy: `{result['policy_name']}`",
        f"- Acquisition: `{result['acquisition']['server_time']}`",
        f"- Latest complete signal bar: `{result['window']['latest_complete_signal_bar_start']}`",
        f"- Cumulative realised hours: `{result['window']['updated_cumulative_realized_hours']}`",
        f"- Fee: exactly `{result['canonical_fee_bps_one_way']}` bps one way",
        f"- Abort: `{result['abort_conditions']['triggered']}`",
        "",
        "| Market | Position | New target | Net | Benchmark | Residual | Turnover | Fees | Margin | Drift |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for market in result["markets"]:
        realized = market["realized_interval"]
        lines.append(
            f"| {market['instrument']} | {'Long' if realized['position'] else 'Cash'} | "
            f"{'Long' if market['new_decisions'][0]['target'] else 'Cash'} | "
            f"{pct(realized['net_strategy_return'])} | {pct(realized['asset_return'])} | "
            f"{pct(realized['strategy_residual_vs_buy_and_hold'])} | {realized['turnover']} | "
            f"{pct(realized['modeled_fee'])} | {pct(market['new_decisions'][0]['margin'])} | "
            f"{pct(market['discrepancy_diagnosis']['signal_margin_change'])} |"
        )
    lines.extend(
        [
            "",
            "## Five-interval scorecard",
            "",
            "| Market | Longs | Net | Benchmark | Residual | Turnover | Fees | Max DD | Sharpe | Edge/turnover |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for market in result["markets"]:
        recent = market["recent_forward_window"]
        sharpe = "undefined" if recent["sharpe"] is None else f"{recent['sharpe']:.6f}"
        edge = (
            "undefined"
            if recent["edge_per_turnover_bps"] is None
            else f"{recent['edge_per_turnover_bps']:.6f}"
        )
        longs = sum(int(row["position"]) for row in recent["intervals"])
        lines.append(
            f"| {market['instrument']} | {longs}/{recent['realized_interval_count']} | "
            f"{pct(recent['net_compound_return'])} | {pct(recent['benchmark_compound_return'])} | "
            f"{pct(recent['residual_vs_buy_and_hold'])} | {recent['turnover']} | "
            f"{pct(recent['modeled_fees'])} | {pct(recent['maximum_drawdown'])} | "
            f"{sharpe} | {edge} |"
        )
    drift = result["strategy_facing_discrepancy"]
    lines.extend(
        [
            "",
            "## Drift diagnosis",
            "",
            f"- Instrument: `{drift['selected_instrument']}`",
            f"- Classification: `{drift['classification']}`",
            f"- Latest benchmark: `{pct(drift['latest_interval_asset_return'])}`",
            f"- Five-interval benchmark: `{pct(drift['five_interval_benchmark_return'])}`",
            f"- Margin drift: `{pct(drift['trend_margin_drift'])}`",
            f"- Policy/accounting defect: `{drift['policy_or_accounting_defect_detected']}`",
            "",
            drift["diagnosis"],
            "",
            "## Candidate disposition",
            "",
            "The adaptive temporal-overlay family remains rejected on the frozen source evidence: "
            "the architecture-cluster median candidate-minus-trend net effect was negative, no "
            "architecture had a positive median net or Sharpe effect, no paired market lower bounds "
            "were jointly positive, and no market met the frozen breadth contract. The latest "
            "attestation-only PR head passes committed Ruff state but fails while downloading the first "
            "immutable source artifact with HTTP 401; that transport attestation failure does not "
            "authorise a strategy correction or same-family rescue.",
            "",
            "## Machine-readable verdict",
            "",
            "```json",
            json.dumps(
                {
                    "latest_complete_signal_bar_start": result["window"][
                        "latest_complete_signal_bar_start"
                    ],
                    "updated_cumulative_realized_hours": result["window"][
                        "updated_cumulative_realized_hours"
                    ],
                    "canonical_fee_bps_one_way": result["canonical_fee_bps_one_way"],
                    "correction_permitted": result["training_authorized_correction"]["permitted"],
                    "correction_applied": result["training_authorized_correction"]["applied"],
                    "abort_triggered": result["abort_conditions"]["triggered"],
                    "verdict": result["verdict"],
                    "paper_trading_authorized": result["paper_trading_authorized"],
                    "live_trading_authorized": result["live_trading_authorized"],
                },
                sort_keys=True,
                indent=2,
            ),
            "```",
            "",
            f"Next strategy-facing action: {result['next_strategy_action']}.",
            "",
        ]
    )
    (output_dir / "report.md").write_text("\n".join(lines))


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    configure()
    result = prior.run(output_dir, base_url)
    result["generated_at"] = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    result["elapsed_period_hours"] = 1
    result["new_public_observations_per_market"] = 1
    result["window"]["prior_cumulative_realized_hours"] = 576
    result["window"]["updated_cumulative_realized_hours"] = 577
    result["nomination_status"] = "no_statistically_eligible_frozen_strategy"
    result["active_alpha_context"] = {
        "issue": 841,
        "pull_request": 843,
        "family_id": "adaptive-temporal-overlay-family-closure-1h-v1",
        "status": "terminal_family_rejection_source_evidence_with_attestation_head_red",
        "new_candidate_count": 0,
        "source_candidate_count": 3,
        "parameter_grid_count": 0,
        "correction_permitted": False,
        "source_market_effect_count": 6,
        "source_evidence_head": "b15d3a545093d4125902777b5d87a903a24dbb38",
        "latest_attestation_head": "1b43d299ebe1fc3288f268839a4a6442b83e9c8f",
        "latest_attestation_workflow_run": 30681818156,
        "latest_attestation_status": "failed_source_artifact_download_http_401_after_formatter_pass",
        "artifact_id": 8812238496,
        "artifact_sha256": "aa0b1c136b7d8162c7d716525f8c1193b012f0a2d5b43ab7cae0b4b0a1b3754d",
        "evidence_sha256": "9a628a9c9998cb4828dc88d639391bffd7a9e938f09509796b337dd5df7a264f",
        "verdict": "reject_adaptive_temporal_overlay_architecture_family",
        "architecture_median_mean_hourly_net_delta_bps": -0.181063,
        "architecture_cluster_mean_hourly_net_ci95_bps": [-0.384732, -0.108562],
        "architecture_median_sharpe_delta": -0.241284,
        "architecture_cluster_sharpe_ci95": [-0.358135, -0.176463],
        "positive_market_net_effects": 2,
        "positive_architecture_medians": 0,
        "paired_lower_bounds_positive": 0,
        "breadth_qualified_markets": 0,
        "gates_passed": 1,
        "gates_total": 10,
    }
    result["training_authorized_correction"] = {
        "permitted": False,
        "applied": False,
        "policy_changed": False,
        "observation_epoch_restarted": False,
        "reason": (
            "the frozen adaptive-overlay family evidence rejects all three source architectures; "
            "the latest attestation passes committed formatting but fails on source-artifact HTTP 401, "
            "which cannot authorise mutation"
        ),
    }
    exposed = any(market["realized_interval"]["position"] == 1 for market in result["markets"])
    result["historical_selection_relationship_status"] = {
        "assessable_in_new_interval": exposed,
        "reason": (
            "the new interval contains frozen long exposure"
            if exposed
            else "the new interval is cash-only and cannot validate conditional-long persistence"
        ),
    }
    result["next_strategy_action"] = (
        "continue the identical BTC/ETH 2160H prospective shadow at the next complete public "
        "1H observation; close the rejected adaptive-overlay family only after its attestation "
        "head passes without altering any strategy-facing value"
    )
    base.write_outputs(output_dir, result)
    report(output_dir, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--base-url", default=os.environ.get("OKX_BASE_URL", "https://www.okx.com")
    )
    args = parser.parse_args()
    print(
        json.dumps(
            run(args.output_dir, args.base_url.rstrip("/")),
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
