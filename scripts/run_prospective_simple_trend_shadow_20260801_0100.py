from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_1800 as base
import run_prospective_simple_trend_shadow_20260801_0000 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_535_200_000
REALIZED_DECISION_HOUR_MS = 1_785_538_800_000
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_542_400_000
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_546_000_000
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_524_400_000
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "be95690c619a211026b9b6c95b202bbb8328886f9b2dc6c7ec735d491a9c38f2"
PRIOR_ARTIFACT_SHA256 = "874cdea1aa4041aa7dcaa4830b04f6eb908cc643b33952ae9b603388ce90d95e"


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
        "# Prospective simple-trend shadow through 01:00 UTC on 1 August 2026",
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
    lines.extend([
        "",
        "## Five-interval scorecard",
        "",
        "| Market | Longs | Net | Benchmark | Residual | Turnover | Fees | Max DD | Sharpe | Edge/turnover |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for market in result["markets"]:
        recent = market["recent_forward_window"]
        sharpe = "undefined" if recent["sharpe"] is None else f"{recent['sharpe']:.6f}"
        edge = "undefined" if recent["edge_per_turnover_bps"] is None else f"{recent['edge_per_turnover_bps']:.6f}"
        longs = sum(int(row["position"]) for row in recent["intervals"])
        lines.append(
            f"| {market['instrument']} | {longs}/{recent['realized_interval_count']} | "
            f"{pct(recent['net_compound_return'])} | {pct(recent['benchmark_compound_return'])} | "
            f"{pct(recent['residual_vs_buy_and_hold'])} | {recent['turnover']} | "
            f"{pct(recent['modeled_fees'])} | {pct(recent['maximum_drawdown'])} | {sharpe} | {edge} |"
        )
    drift = result["strategy_facing_discrepancy"]
    lines.extend([
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
        "The preregistered transaction-cost-aware online specialist arbiter is rejected. "
        "RUNE OOS was +15.0558% but had only 3/6 positive folds, 74.33% positive-fold "
        "profit concentration, and paired superiority intervals crossing zero. KAVA OOS "
        "was -46.6922% versus +16.12% for static E1440; only 5/16 switches improved the "
        "following 168H utility. Markets accepted: 0/2. No correction or epoch restart.",
        "",
        "## Machine-readable verdict",
        "",
        "```json",
        json.dumps({
            "latest_complete_signal_bar_start": result["window"]["latest_complete_signal_bar_start"],
            "updated_cumulative_realized_hours": result["window"]["updated_cumulative_realized_hours"],
            "canonical_fee_bps_one_way": result["canonical_fee_bps_one_way"],
            "correction_permitted": result["training_authorized_correction"]["permitted"],
            "correction_applied": result["training_authorized_correction"]["applied"],
            "abort_triggered": result["abort_conditions"]["triggered"],
            "verdict": result["verdict"],
            "paper_trading_authorized": result["paper_trading_authorized"],
            "live_trading_authorized": result["live_trading_authorized"],
        }, sort_keys=True, indent=2),
        "```",
        "",
        f"Next strategy-facing action: {result['next_strategy_action']}.",
        "",
    ])
    (output_dir / "report.md").write_text("\n".join(lines))


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    configure()
    result = prior.run(output_dir, base_url)
    result["generated_at"] = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    result["elapsed_period_hours"] = 1
    result["new_public_observations_per_market"] = 1
    result["window"]["prior_cumulative_realized_hours"] = 575
    result["window"]["updated_cumulative_realized_hours"] = 576
    result["nomination_status"] = "no_statistically_eligible_frozen_strategy"
    result["active_alpha_context"] = {
        "issue": 839,
        "pull_request": 840,
        "family_id": "transaction-cost-aware-online-specialist-arbitration-1h-v1",
        "status": "terminal_architecture_rejected",
        "candidate_count": 1,
        "parameter_grid_count": 0,
        "correction_permitted": False,
        "tested_head": "bbb9ddea4edc099e0d1b34ac7eb794514d039725",
        "workflow_run": 30679197384,
        "artifact_id": 8811607454,
        "artifact_sha256": "9879fa5ec89749995ba36d8c0cacdc07230bc6f098da6541c27790ed626e095a",
        "evidence_sha256": "d8cbd139ac3db0bd4a42a944646098f552001d78ca36d338998226524bb0d6af",
        "verdict": "reject_transaction_cost_aware_online_specialist_arbitration_architecture_v1",
        "markets_accepted": 0,
        "market_count": 2,
        "rune_oos_net_return": 0.150558,
        "rune_oos_sharpe": 0.4559,
        "rune_positive_folds": 3,
        "rune_fold_count": 6,
        "rune_positive_fold_profit_concentration": 0.7433,
        "kava_oos_net_return": -0.466922,
        "kava_oos_sharpe": -0.4964,
        "kava_static_e1440_oos_net_return": 0.1612,
        "kava_effective_switches": 5,
        "kava_identity_switches": 16,
    }
    result["training_authorized_correction"] = {
        "permitted": False,
        "applied": False,
        "policy_changed": False,
        "observation_epoch_restarted": False,
        "reason": "zero of two markets passed the frozen bilateral specialist-arbitration gates",
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
        "continue the identical BTC/ETH 2160H prospective shadow at the next complete "
        "public 1H observation; do not rescue lagged realised-utility specialist arbitration"
    )
    base.write_outputs(output_dir, result)
    report(output_dir, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--base-url", default=os.environ.get("OKX_BASE_URL", "https://www.okx.com"))
    args = parser.parse_args()
    print(json.dumps(run(args.output_dir, args.base_url.rstrip("/")), sort_keys=True, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
