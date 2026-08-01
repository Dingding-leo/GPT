from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_1800 as base
import run_prospective_simple_trend_shadow_20260801_0600 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_556_800_000
REALIZED_DECISION_HOUR_MS = 1_785_560_400_000
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_564_000_000
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_567_600_000
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_546_000_000
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "a5721e6d85c54c7944b6e599596c7084a16cfe3a175e1348a817be06c952fd3d"
PRIOR_ARTIFACT_SHA256 = "8b858d0a3c820f301f666922c871b66f4e59698aef77489fe495d055761ff41c"


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
        "# Prospective simple-trend shadow through 07:00 UTC on 1 August 2026",
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
        lines.append(
            f"| {market['instrument']} | {recent['long_decision_count']}/{recent['realized_interval_count']} | "
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
        "The preregistered `okx-l2-bid-replenishment-resilience-opportunity-diagnostic-1h-v1` information premise is terminally rejected. It produced 276/288 valid observations per market, but all primary dependence-aware lower bounds crossed zero. Positive anchor-day breadth was only 3/12 for both BTC targets, 1/12 for ETH net and 2/12 for ETH adverse excursion; ordered buckets were non-monotonic and every delayed lower bound also crossed zero. Candidate count remained zero and no executable policy correction was formed.",
        "",
        "Issues #860 and #861 are preregistered diagnostic/family-closure work with zero executable candidates and no authority to alter this frozen policy or observation epoch before their own terminal evidence passes all frozen gates.",
        "",
        "## Machine-readable verdict",
        "",
        "```json",
        json.dumps({
            "latest_complete_signal_bar_start": result["window"]["latest_complete_signal_bar_start"],
            "updated_cumulative_realized_hours": result["window"]["updated_cumulative_realized_hours"],
            "canonical_fee_bps_one_way": result["canonical_fee_bps_one_way"],
            "candidate_verdict": result["active_alpha_context"]["verdict"],
            "candidate_markets_passing": result["active_alpha_context"]["markets_passing_all_gates"],
            "correction_permitted": result["training_authorized_correction"]["permitted"],
            "correction_applied": result["training_authorized_correction"]["applied"],
            "observation_epoch_restarted": result["training_authorized_correction"]["observation_epoch_restarted"],
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
    result["window"]["prior_cumulative_realized_hours"] = 581
    result["window"]["updated_cumulative_realized_hours"] = 582
    result["nomination_status"] = "no_statistically_eligible_frozen_strategy"
    result["active_alpha_context"] = {
        "issue": 854,
        "pull_request": 858,
        "family_id": "okx-l2-bid-replenishment-resilience-opportunity-diagnostic-1h-v1",
        "classification": "training_only_information_diagnostic",
        "status": "terminal_rejection",
        "candidate_count": 0,
        "diagnostic_count": 1,
        "parameter_grid_count": 0,
        "markets_passing_all_gates": 0,
        "correction_permitted": False,
        "exact_head": "026c00e825540ca9229c39deb69a374fd8515460",
        "workflow_run": 30689936742,
        "artifact_id": 8815335758,
        "artifact_sha256": "d38561a8daa6f60d8b4cd6ef730495062aa9b114a9925e2e1a412b65a1f9d024",
        "evidence_sha256": "30b83fa62995b241680ff07a9f19a56564f1434382aad7f5e729777e8d706afc",
        "valid_scored_observations_per_market": 276,
        "required_scored_observations_per_market": 288,
        "btc_positive_day_breadth_net": 3,
        "btc_positive_day_breadth_adverse": 3,
        "eth_positive_day_breadth_net": 1,
        "eth_positive_day_breadth_adverse": 2,
        "required_positive_day_breadth": 8,
        "verdict": "reject_okx_l2_bid_replenishment_resilience_information_premise",
        "next_information_issue": 860,
        "next_information_family": "okx-l2-persistent-near-touch-concentration-asymmetry-1h-v1",
        "next_information_candidate_count": 0,
        "family_closure_issue": 861,
        "family_closure_family": "causal-microstructure-resilience-family-closure-1h-v1",
        "family_closure_candidate_count": 0,
    }
    result["training_authorized_correction"] = {
        "permitted": False,
        "applied": False,
        "policy_changed": False,
        "observation_epoch_restarted": False,
        "reason": "the L2 bid-replenishment premise failed bilateral confidence, day-breadth, bucket-order and delay gates; the open concentration diagnostic and microstructure-family closure have zero executable candidates",
    }
    exposed = any(market["realized_interval"]["position"] == 1 for market in result["markets"])
    result["historical_selection_relationship_status"] = {
        "assessable_in_new_interval": exposed,
        "reason": "the new interval contains frozen long exposure" if exposed else "the new interval is cash-only and cannot validate conditional-long persistence",
    }
    result["next_strategy_action"] = "continue the identical BTC/ETH 2160H prospective shadow at the next complete public 1H observation; keep the rejected L2 bid-replenishment premise closed, and grant no correction or epoch restart unless a separately frozen executable temporal rule later passes every bilateral gate"
    base.write_outputs(output_dir, result)
    write_report(output_dir, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--base-url", default=os.environ.get("OKX_BASE_URL", "https://www.okx.com"))
    args = parser.parse_args()
    print(json.dumps(run(args.output_dir, args.base_url.rstrip("/")), sort_keys=True, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
