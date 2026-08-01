from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_20260801_1000 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_571_200_000
REALIZED_DECISION_HOUR_MS = 1_785_574_800_000
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_578_400_000
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_582_000_000
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_560_400_000
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "452ceb26d854001fe9dc3da96ad113978eaf7934a1268bea80a5740d53ba9f09"
PRIOR_ARTIFACT_SHA256 = "2b143beed260a8c4b84bc2139aa74ae70b34fb4d970bdd8dc395779cfbff5664"


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


def write_report(output_dir: Path, result: dict[str, Any]) -> None:
    lines = [
        "# Prospective simple-trend shadow through 11:00 UTC on 1 August 2026",
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
        realised = market["realized_interval"]
        lines.append(
            f"| {market['instrument']} | {'Long' if realised['position'] else 'Cash'} | "
            f"{'Long' if market['new_decisions'][0]['target'] else 'Cash'} | "
            f"{pct(realised['net_strategy_return'])} | {pct(realised['asset_return'])} | "
            f"{pct(realised['strategy_residual_vs_buy_and_hold'])} | {realised['turnover']} | "
            f"{pct(realised['modeled_fee'])} | {pct(market['new_decisions'][0]['margin'])} | "
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
        lines.append(
            f"| {market['instrument']} | {recent['long_decision_count']}/{recent['realized_interval_count']} | "
            f"{pct(recent['net_compound_return'])} | {pct(recent['benchmark_compound_return'])} | "
            f"{pct(recent['residual_vs_buy_and_hold'])} | {recent['turnover']} | "
            f"{pct(recent['modeled_fees'])} | {pct(recent['maximum_drawdown'])} | {sharpe} | {edge} |"
        )
    drift = result["strategy_facing_discrepancy"]
    candidate = result["latest_terminal_candidate_context"]
    closure = result["latest_family_closure_context"]
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
            "## Candidate and family disposition",
            "",
            "The preregistered week-phase-deseasonalized endpoint-trend candidate is terminally rejected. SUSHI-USDT returned -41.6741% OOS versus -38.4121% for E2160; CRV-USDT returned -56.8127% versus -56.8792%. Both markets failed positive OOS, benchmark superiority, dependence-aware uncertainty, temporal breadth, profile transport and one-hour-delay gates.",
            "",
            "The completed two-group calendar-phase family closure found 0/2 supportive architectures, zero bilateral positive-OOS groups, zero bilateral E2160-superior groups, zero positive-dependence groups, zero breadth/transport groups, and no leave-one-group-out support. Deterministic UTC calendar timing is therefore closed as a same-family rescue path on the consumed cohorts.",
            "",
            f"Candidate artifact: `{candidate['artifact_id']}` / `{candidate['artifact_sha256']}`.",
            f"Family-closure artifact: `{closure['artifact_id']}` / `{closure['artifact_sha256']}`.",
            "",
            "## Machine-readable verdict",
            "",
            "```json",
            json.dumps(
                {
                    "latest_complete_signal_bar_start": result["window"]["latest_complete_signal_bar_start"],
                    "updated_cumulative_realized_hours": result["window"]["updated_cumulative_realized_hours"],
                    "canonical_fee_bps_one_way": result["canonical_fee_bps_one_way"],
                    "candidate_verdict": candidate["verdict"],
                    "family_verdict": closure["verdict"],
                    "correction_permitted": result["training_authorized_correction"]["permitted"],
                    "correction_applied": result["training_authorized_correction"]["applied"],
                    "observation_epoch_restarted": result["training_authorized_correction"]["observation_epoch_restarted"],
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
    result["window"]["prior_cumulative_realized_hours"] = 585
    result["window"]["updated_cumulative_realized_hours"] = 586
    result["nomination_status"] = "no_statistically_eligible_frozen_strategy"
    result["latest_terminal_candidate_context"] = {
        "issue": 866,
        "pull_request": 873,
        "family_id": "causal-week-phase-deseasonalized-endpoint-trend-1h-v1",
        "status": "terminal_rejection_evidence_closed_unmerged",
        "workflow_run": 30698370997,
        "artifact_id": 8818043573,
        "artifact_sha256": "f5437948d72ea677e96084a29f9acf0c1d35dbd2182676b9550c7b402df87071",
        "evidence_sha256": "b2e596c695f519d32229d4b7c90f47d616c2669a069dabee35bf6f6f20c1302c",
        "candidate_count": 2,
        "parameter_grid_count": 0,
        "markets_passing_all_gates": 0,
        "verdict": "reject_causal_week_phase_deseasonalized_endpoint_trend_1h_v1",
        "correction_permitted": False,
        "prospective_performance_consumed": False,
        "market_summary": {
            "SUSHI-USDT": {
                "oos_candidate_net_return": -0.4167412774034051,
                "oos_candidate_sharpe": 0.1676939641883595,
                "oos_e2160_net_return": -0.38412109754070406,
                "oos_e2160_sharpe": 0.19585119159957073,
                "turnover": 56.0,
                "passed_gates": 4,
                "total_gates": 14,
            },
            "CRV-USDT": {
                "oos_candidate_net_return": -0.5681270410331434,
                "oos_candidate_sharpe": 0.023987695623920034,
                "oos_e2160_net_return": -0.5687916655939622,
                "oos_e2160_sharpe": 0.024347666492795447,
                "turnover": 42.0,
                "passed_gates": 3,
                "total_gates": 14,
            },
        },
    }
    result["latest_family_closure_context"] = {
        "issue": 874,
        "pull_request": 875,
        "family_id": "causal-calendar-phase-timing-information-family-closure-1h-v1",
        "status": "terminal_rejection_exact_head_evidence_published",
        "workflow_run": 30699243320,
        "tested_head": "5b1609edf878b4be51d8d4993ca6fc9bda83adce",
        "artifact_id": 8818257149,
        "artifact_sha256": "cb652314cc23c38ec0c0646c91732d89278b6b04ce49985f0aac8e8cdb494b9a",
        "architecture_group_count": 2,
        "supportive_group_count": 0,
        "bilateral_positive_oos_groups": 0,
        "bilateral_benchmark_superior_groups": 0,
        "bilateral_positive_dependence_groups": 0,
        "bilateral_temporal_breadth_groups": 0,
        "bilateral_calendar_transport_groups": 0,
        "leave_one_group_out_support": 0,
        "new_candidate_count": 0,
        "new_oos_consumed": 0,
        "verdict": "reject_causal_calendar_phase_timing_information_family",
    }
    result["active_alpha_context"] = {
        "issue": 874,
        "pull_request": 875,
        "family_id": "causal-calendar-phase-timing-information-family-closure-1h-v1",
        "classification": "completed_evidence_family_closure",
        "status": "terminal_rejection_exact_head_evidence_published",
        "candidate_count": 0,
        "diagnostic_count": 0,
        "parameter_grid_count": 0,
        "architecture_group_count": 2,
        "supportive_group_count": 0,
        "new_oos_consumed_by_this_forward_run": 0,
        "correction_permitted": False,
        "canonical_mutation_permitted": False,
        "verdict": "reject_causal_calendar_phase_timing_information_family",
        "next_candidate_family_id": "lagged-btc-market-impulse-veto-trend-carry-1h-v1",
    }
    result["training_authorized_correction"] = {
        "permitted": False,
        "applied": False,
        "policy_changed": False,
        "observation_epoch_restarted": False,
        "reason": "the sole preregistered week-phase candidate and its calendar-phase information family are terminally rejected; no training-authorized correction exists",
    }
    exposed = any(
        market["realized_interval"]["position"] == 1 for market in result["markets"]
    )
    result["historical_selection_relationship_status"] = {
        "assessable_in_new_interval": exposed,
        "reason": (
            "the new interval contains frozen long exposure"
            if exposed
            else "the new interval is cash-only and cannot validate conditional-long persistence"
        ),
    }
    result["next_strategy_action"] = (
        "continue the identical BTC/ETH 2160H prospective shadow at the next complete public 1H observation; keep the calendar-phase family closed, and separately preregister the materially distinct lagged-BTC downside-impulse entry-veto candidate before any performance access"
    )
    prior.rewrite_result(output_dir, result)
    write_report(output_dir, result)
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
