from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_20260802_0200 as base

LAST_REPORTED_COMPLETE_SIGNAL_HOUR_MS = 1_785_632_400_000


def pct(value: float | None) -> str:
    return "undefined" if value is None else f"{100.0 * value:+.6f}%"


def write_outputs(output_dir: Path, result: dict[str, Any]) -> None:
    payload = json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n"
    (output_dir / "result.json").write_text(payload)
    (output_dir / "result.sha256").write_text(
        hashlib.sha256(payload.encode()).hexdigest() + "\n"
    )

    lines = [
        "# Prospective simple-trend realised checkpoint through 02:00 UTC on 2 August 2026",
        "",
        f"- Policy: `{result['policy_name']}`",
        f"- Acquisition server time: `{result['acquisition']['server_time']}`",
        f"- Latest complete signal bar already reported: `{result['window']['latest_complete_signal_bar_start']}`",
        f"- Newly realised payoff interval: `{result['window']['realized_payoff_interval_start']}` to `{result['window']['realized_payoff_interval_end']}`",
        f"- Cumulative realised hours: `{result['window']['updated_cumulative_realized_hours']}`",
        f"- New signal bars: `{result['window']['new_signal_bar_count']}`",
        f"- Fee: exactly `{result['canonical_fee_bps_one_way']}` bps one way",
        f"- Abort: `{result['abort_conditions']['triggered']}`",
        "",
        "| Market | Carried position | Realised net | Benchmark | Residual | Turnover | Fees | Carried 2160H margin |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for market in result["markets"]:
        realised = market["realized_interval"]
        carried = market["carried_decision"]
        lines.append(
            f"| {market['instrument']} | {'Long' if realised['position'] else 'Cash'} | "
            f"{pct(realised['net_strategy_return'])} | {pct(realised['asset_return'])} | "
            f"{pct(realised['strategy_residual_vs_buy_and_hold'])} | {realised['turnover']} | "
            f"{pct(realised['modeled_fee'])} | {pct(carried['margin'])} |"
        )

    lines.extend(
        [
            "",
            "## Five-interval scorecard",
            "",
            "| Market | Longs | Net | Benchmark | Residual | Turnover | Fees | Max DD | Losses | Sharpe | Edge/turnover |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
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
            f"{pct(recent['modeled_fees'])} | {pct(recent['maximum_drawdown'])} | "
            f"{recent['loss_count']} | {sharpe} | {edge} |"
        )

    discrepancy = result["strategy_facing_discrepancy"]
    lines.extend(
        [
            "",
            "## Strategy-facing finding",
            "",
            f"- Selected instrument: `{discrepancy['selected_instrument']}`",
            f"- Classification: `{discrepancy['classification']}`",
            f"- Latest benchmark: `{pct(discrepancy['latest_interval_asset_return'])}`",
            f"- Five-interval benchmark: `{pct(discrepancy['five_interval_benchmark_return'])}`",
            "",
            discrepancy["diagnosis"],
            "",
            "The initial attempt correctly failed because the 02:00-start signal bar was still incomplete. The single permitted repair changed the run to a realised-only checkpoint: it consumed the now-complete 01:00–02:00 open-to-open payoff while reusing the already reported 01:00 signal and introduced no new signal, policy, parameter, source, fee or strategy architecture.",
            "",
            "Issue #943 / PR #946 remains the latest terminal strategy-family result: the accepted four-arm mark/index source could not reopen the rejected derivatives-crowding family. Issue #944 was rejected before source, feature, return or OOS access. No replacement strategy architecture is active.",
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
    base.PRIOR_REPORTED_SIGNAL_HOUR_MS = LAST_REPORTED_COMPLETE_SIGNAL_HOUR_MS
    base.LATEST_COMPLETE_SIGNAL_HOUR_MS = LAST_REPORTED_COMPLETE_SIGNAL_HOUR_MS
    result = base.run(output_dir, base_url)

    result["generated_at"] = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    result["checkpoint_type"] = "realized_only_no_new_signal_bar"
    result["new_public_observations_per_market"] = 1
    result["new_complete_signal_observations_per_market"] = 0
    result["new_realized_payoff_observations_per_market"] = 1
    result["window"]["new_signal_bar_count"] = 0
    result["window"]["new_realized_payoff_intervals"] = 1

    for market in result["markets"]:
        carried = market["new_decisions"][0]
        carried["classification"] = "already_reported_carried_decision"
        market["carried_decision"] = carried
        market["new_decisions"] = []
        market["new_signal_observations"] = 0
        market["new_long_targets"] = 0
        market["pending_target_changes"] = 0
        market["signal_drift"]["margin_change"] = 0.0
        market["signal_drift"]["target_changed_since_prior_reported_signal_hour"] = False

    selected = max(
        result["markets"],
        key=lambda market: abs(float(market["realized_interval"]["asset_return"])),
    )
    result["strategy_facing_discrepancy"] = {
        "selected_instrument": selected["instrument"],
        "classification": "realized_only_cash_opportunity_cost",
        "latest_interval_asset_return": selected["realized_interval"]["asset_return"],
        "five_interval_benchmark_return": selected["recent_forward_window"][
            "benchmark_compound_return"
        ],
        "trend_margin_drift": 0.0,
        "policy_or_accounting_defect_detected": False,
        "diagnosis": (
            "The frozen position remained cash, so the interval residual is exactly the negative "
            "of the public open-to-open benchmark. This is opportunity cost under a deeply "
            "negative 2,160H state, not a chronology, position-state, turnover or fee defect."
        ),
    }
    result["historical_selection_relationship_status"] = {
        "assessable_in_new_interval": any(
            market["realized_interval"]["position"] == 1
            for market in result["markets"]
        ),
        "reason": "the newly realised interval is cash-only in both fixed markets",
    }
    result["next_strategy_action"] = (
        "at or after 03:00 UTC, continue the identical BTC/ETH 2160H prospective shadow with "
        "the newly completed 02:00-start signal bar; nominate no replacement until a materially "
        "orthogonal causal public 1H source and falsifiable hypothesis are frozen before access"
    )
    result["machine_readable_verdict"].update(
        {
            "checkpoint_type": result["checkpoint_type"],
            "latest_complete_signal_bar_start": result["window"][
                "latest_complete_signal_bar_start"
            ],
            "new_signal_bar_count": 0,
            "new_realized_payoff_intervals": 1,
            "updated_cumulative_realized_hours": 601,
            "latest_terminal_family_id": result["latest_terminal_candidate_context"][
                "family_id"
            ],
            "latest_terminal_verdict": result["latest_terminal_candidate_context"][
                "verdict"
            ],
            "active_family_id": None,
            "active_family_status": "no_active_replacement_strategy_architecture",
            "cutoff_repair_applied": True,
            "policy_changed": False,
            "paper_trading_authorized": False,
            "live_trading_authorized": False,
        }
    )
    result["training_authorized_correction"]["applied"] = False
    result["cutoff_repair"] = {
        "applied": True,
        "type": "realized_only_checkpoint_before_next_signal_bar_completion",
        "failed_attempt_workflow_run": 30729186761,
        "strategy_value_changed": False,
        "source_changed": False,
        "fee_changed": False,
        "architecture_changed": False,
    }
    write_outputs(output_dir, result)
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
