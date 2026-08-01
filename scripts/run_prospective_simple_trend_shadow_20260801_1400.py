from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_20260801_1300 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_582_000_000
REALIZED_DECISION_HOUR_MS = 1_785_585_600_000
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_589_200_000
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_592_800_000
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_571_200_000
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "a5e8c6f64ce26e7f395967b2026b07280eeaa76a5efd23e5c5a627a241f47656"
PRIOR_ARTIFACT_SHA256 = "14fcbb2cff193a3718ced968c40eb6f9d4cd49cfb6218cf5f2dd9911b40e3558"


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


def rewrite_result(output_dir: Path, result: dict[str, Any]) -> None:
    payload = (
        json.dumps(result, sort_keys=True, indent=2, allow_nan=False).encode("utf-8")
        + b"\n"
    )
    (output_dir / "result.json").write_bytes(payload)
    (output_dir / "result.sha256").write_text(hashlib.sha256(payload).hexdigest() + "\n")


def write_report(output_dir: Path, result: dict[str, Any]) -> None:
    lines = [
        "# Prospective simple-trend shadow through 14:00 UTC on 1 August 2026",
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
    rejected = result["latest_terminal_candidate_context"]
    active = result["active_alpha_context"]
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
            "## Strategy-correction disposition",
            "",
            f"Issue #{rejected['issue']} / PR #{rejected['pull_request']} terminally rejected `{rejected['family_id']}` with 0/2 markets passing. The candidate's attractive ICX point estimate did not survive dependence, breadth, full-sample or bilateral replication gates, while ONT remained economically negative.",
            "",
            f"Issue #{active['issue']} / PR #{active['pull_request']} is the sole active evidence-only architecture-family closure: `{active['family_id']}`. It consumes no new market data or OOS and cannot authorise a policy correction or epoch restart.",
            "",
            "## Machine-readable verdict",
            "",
            "```json",
            json.dumps(
                {
                    "latest_complete_signal_bar_start": result["window"]["latest_complete_signal_bar_start"],
                    "updated_cumulative_realized_hours": result["window"]["updated_cumulative_realized_hours"],
                    "canonical_fee_bps_one_way": result["canonical_fee_bps_one_way"],
                    "candidate_verdict": rejected["verdict"],
                    "active_family_id": active["family_id"],
                    "active_family_status": active["status"],
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
    result["window"]["prior_cumulative_realized_hours"] = 588
    result["window"]["updated_cumulative_realized_hours"] = 589
    result["nomination_status"] = "no_statistically_eligible_frozen_strategy"
    result["latest_terminal_candidate_context"] = {
        "issue": 882,
        "pull_request": 884,
        "family_id": "causal-temporal-stochastic-dominance-trend-1h-v1",
        "status": "terminal_performance_rejection",
        "workflow_run": 30704188150,
        "tested_head": "f9c71b89e816d88049dd819eb0a30caa61f4e3ac",
        "artifact_id": 8819797922,
        "artifact_sha256": "a6589d2666fb4a634e5f3949cbfb527d78e5b07c25e83935572bd94baaa5da55",
        "evidence_sha256": "025f3a155189fe0f27c47d287db087439b231c3bb671b3aece35e17874d80680",
        "candidate_count": 2,
        "parameter_grid_count": 0,
        "performance_accessed": True,
        "markets_passing_all_gates": 0,
        "market_summary": {
            "ICXUSDT": {
                "oos_net_return": 0.155290,
                "oos_sharpe": 0.4675,
                "e2160_net_return": -0.107057,
                "turnover": 4,
                "gates_passed": 8,
                "gates_total": 14,
            },
            "ONTUSDT": {
                "oos_net_return": -0.285309,
                "oos_sharpe": -0.0433,
                "e2160_net_return": -0.381605,
                "turnover": 6,
                "gates_passed": 6,
                "gates_total": 14,
            },
        },
        "verdict": "reject_causal_temporal_stochastic_dominance_trend_1h_v1",
        "correction_permitted": False,
    }
    result["active_alpha_context"] = {
        "issue": 886,
        "pull_request": 887,
        "family_id": "causal-distributed-slow-trend-representation-family-closure-1h-v1",
        "classification": "completed_evidence_architecture_family_closure",
        "status": "preregistered_active_zero_new_oos",
        "candidate_count": 0,
        "diagnostic_count": 1,
        "parameter_grid_count": 0,
        "architecture_groups": 4,
        "new_market_data": 0,
        "new_oos_consumed_by_this_forward_run": 0,
        "correction_permitted": False,
        "canonical_mutation_permitted": False,
    }
    result["training_authorized_correction"] = {
        "permitted": False,
        "applied": False,
        "policy_changed": False,
        "observation_epoch_restarted": False,
        "reason": "the temporal stochastic-dominance candidate failed its frozen bilateral gates and the sole active distributed slow-trend family closure creates no executable candidate or correction authority",
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
        "continue the identical BTC/ETH 2160H prospective shadow at the next complete public 1H observation and complete the unchanged distributed slow-trend representation family closure; permit a new observation epoch only if a separately frozen executable rule passes every bilateral gate"
    )
    rewrite_result(output_dir, result)
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
