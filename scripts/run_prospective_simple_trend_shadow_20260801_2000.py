from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_20260801_1900 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_603_600_000
REALIZED_DECISION_HOUR_MS = 1_785_607_200_000
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_610_800_000
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_614_400_000
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_592_800_000
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "f3e0775212e3248dc2f2a009e45e6003764a063b543f7c7dbfe94e288e201991"
PRIOR_ARTIFACT_SHA256 = "1262e67f420c20617967793de70cdf31c134da77202fec9f5fb8bddec8cef1a7"


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


def write_json(output_dir: Path, result: dict[str, Any]) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n"
    digest = hashlib.sha256(payload.encode()).hexdigest()
    (output_dir / "result.json").write_text(payload)
    (output_dir / "result.sha256").write_text(digest + "\n")
    return digest


def write_report(output_dir: Path, result: dict[str, Any]) -> None:
    lines = [
        "# Prospective simple-trend shadow through 20:00 UTC on 1 August 2026",
        "",
        f"- Policy: `{result['policy_name']}`",
        f"- Acquisition server time: `{result['acquisition']['server_time']}`",
        f"- Latest complete signal bar: `{result['window']['latest_complete_signal_bar_start']}`",
        f"- Realised payoff interval: `{result['window']['realized_payoff_interval_start']}` to `{result['window']['realized_payoff_interval_end']}`",
        f"- Cumulative realised hours: `{result['window']['updated_cumulative_realized_hours']}`",
        f"- Fee: exactly `{result['canonical_fee_bps_one_way']}` bps one way",
        f"- Abort: `{result['abort_conditions']['triggered']}`",
        "",
        "| Market | Position | New target | Expected net | Realised net | Benchmark | Residual | Turnover | Fees | 2160H margin | Margin drift |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for market in result["markets"]:
        realised = market["realized_interval"]
        decision = market["new_decisions"][0]
        lines.append(
            f"| {market['instrument']} | {'Long' if realised['position'] else 'Cash'} | "
            f"{'Long' if decision['target'] else 'Cash'} | "
            f"{pct(realised['expected_net_return_under_frozen_decision'])} | "
            f"{pct(realised['net_strategy_return'])} | {pct(realised['asset_return'])} | "
            f"{pct(realised['strategy_residual_vs_buy_and_hold'])} | {realised['turnover']} | "
            f"{pct(realised['modeled_fee'])} | {pct(decision['margin'])} | "
            f"{pct(market['discrepancy_diagnosis']['signal_margin_change'])} |"
        )

    lines.extend(
        [
            "",
            "## Five-interval forward scorecard",
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
            else f"{recent['edge_per_turnover_bps']:.6f} bps"
        )
        lines.append(
            f"| {market['instrument']} | {recent['long_decision_count']}/{recent['realized_interval_count']} | "
            f"{pct(recent['net_compound_return'])} | {pct(recent['benchmark_compound_return'])} | "
            f"{pct(recent['residual_vs_buy_and_hold'])} | {recent['turnover']} | "
            f"{pct(recent['modeled_fees'])} | {pct(recent['maximum_drawdown'])} | {sharpe} | {edge} |"
        )

    drift = result["strategy_facing_discrepancy"]
    terminal = result["latest_terminal_candidate_context"]
    active = result["active_alpha_context"]
    correction = result["training_authorized_correction"]
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
            f"- Policy/accounting defect detected: `{drift['policy_or_accounting_defect_detected']}`",
            "",
            drift["diagnosis"],
            "",
            "## Candidate and correction disposition",
            "",
            f"Issue #{terminal['issue']} / PR #{terminal['pull_request']} terminally rejected "
            f"`{terminal['family_id']}` at the frozen bilateral public-source contract. No target "
            "return, feature, candidate or sealed OOS observation was accessed.",
            "",
            f"Issue #{active['issue']} is the sole active source-contract-first architecture: "
            f"`{active['family_id']}`. It may inspect only direct official BTC/ETH DVOL 1H source "
            "coverage and integrity; it cannot define a regime rule or inspect target performance.",
            "",
            "```text",
            f"Correction permitted          {str(correction['permitted']).lower()}",
            f"Correction applied            {str(correction['applied']).lower()}",
            f"Policy changed                {str(correction['policy_changed']).lower()}",
            f"Observation epoch restarted   {str(correction['observation_epoch_restarted']).lower()}",
            "```",
            "",
            "## Machine-readable verdict",
            "",
            "```json",
            json.dumps(result["machine_readable_verdict"], sort_keys=True, indent=2),
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
    result["window"]["prior_cumulative_realized_hours"] = 594
    result["window"]["updated_cumulative_realized_hours"] = 595
    realised = result["markets"][0]["realized_interval"]
    result["window"]["realized_payoff_interval_start"] = realised["payoff_open_start"]
    result["window"]["realized_payoff_interval_end"] = realised["payoff_open_end"]

    total_intervals = sum(
        market["recent_forward_window"]["realized_interval_count"] for market in result["markets"]
    )
    total_longs = sum(
        market["recent_forward_window"]["long_decision_count"] for market in result["markets"]
    )
    signal_frequency = total_longs / total_intervals if total_intervals else None
    result["aggregate_forward_scorecard"] = {
        "market_count": len(result["markets"]),
        "realized_interval_count": total_intervals,
        "long_decision_count": total_longs,
        "signal_frequency": signal_frequency,
        "no_trade_frequency": None if signal_frequency is None else 1.0 - signal_frequency,
    }
    result["nomination_status"] = "no_statistically_eligible_frozen_strategy"
    result["latest_terminal_candidate_context"] = {
        "issue": 912,
        "pull_request": 913,
        "family_id": "causal-options-implied-downside-skew-confirmed-e2160-entry-1h-v1",
        "status": "terminal_source_contract_rejection_before_feature_or_performance",
        "workflow_run": 30717626149,
        "tested_head": "ddcf0c038d5bcc6d8c6efbe7fe3f5c5aae36409c",
        "artifact_id": 8823829972,
        "artifact_sha256": "a296635cc42fca879424faef620d799668a99a654b1d1cb292802fb0f2dbc417",
        "evidence_sha256": "79016a5372b804e5531ce871bd3439b7fb52a47210ba1afea1d279b03f1b8804",
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "official_docs_retrieved": 6,
        "official_docs_expected": 6,
        "source_arms_passing": 0,
        "source_arm_count": 2,
        "market_data_downloaded": 0,
        "target_returns_accessed": False,
        "performance_accessed": False,
        "oos_accessed": False,
        "verdict": "reject_causal_options_implied_downside_skew_confirmed_e2160_entry_1h_v1_at_source_contract",
        "correction_permitted": False,
    }
    result["active_alpha_context"] = {
        "issue": 914,
        "pull_request": None,
        "family_id": "causal-dvol-regime-adaptive-e2160-sizing-source-contract-1h-v1",
        "classification": "source_contract_first_forward_implied_volatility_information_experiment",
        "status": "preregistered_active_source_only_performance_unseen",
        "fixed_target_arms": ["BTC-USDT", "ETH-USDT"],
        "exogenous_mapping": {"BTC-USDT": "BTC DVOL", "ETH-USDT": "ETH DVOL"},
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "performance_seen": False,
        "oos_accessed": False,
        "target_returns_accessed": False,
        "correction_permitted": False,
        "canonical_mutation_permitted": False,
    }
    result["training_authorized_correction"] = {
        "permitted": False,
        "applied": False,
        "policy_changed": False,
        "observation_epoch_restarted": False,
        "reason": (
            "the downside-skew architecture failed before feature or performance access and issue "
            "#914 is a source-only DVOL feasibility contract with zero candidates"
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
        "continue the identical BTC/ETH 2160H prospective shadow at the next complete public 1H "
        "observation and execute issue #914's bilateral direct-DVOL source contract exactly as "
        "frozen; define no regime mapping, candidate or new observation epoch unless both source "
        "arms pass every preregistered source gate"
    )
    result["machine_readable_verdict"] = {
        "latest_complete_signal_bar_start": result["window"]["latest_complete_signal_bar_start"],
        "updated_cumulative_realized_hours": result["window"]["updated_cumulative_realized_hours"],
        "canonical_fee_bps_one_way": result["canonical_fee_bps_one_way"],
        "signal_frequency": result["aggregate_forward_scorecard"]["signal_frequency"],
        "no_trade_frequency": result["aggregate_forward_scorecard"]["no_trade_frequency"],
        "terminal_candidate_verdict": result["latest_terminal_candidate_context"]["verdict"],
        "active_family_id": result["active_alpha_context"]["family_id"],
        "active_family_status": result["active_alpha_context"]["status"],
        "correction_permitted": result["training_authorized_correction"]["permitted"],
        "correction_applied": result["training_authorized_correction"]["applied"],
        "observation_epoch_restarted": result["training_authorized_correction"][
            "observation_epoch_restarted"
        ],
        "abort_triggered": result["abort_conditions"]["triggered"],
        "verdict": result["verdict"],
        "paper_trading_authorized": result["paper_trading_authorized"],
        "live_trading_authorized": result["live_trading_authorized"],
    }
    write_json(output_dir, result)
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
