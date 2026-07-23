from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .core import (
    ADAPTIVE_SEEDS,
    ALL_IN_COSTS_BPS,
    BASELINE_COST_BPS,
    BENCHMARK_SEEDS,
    BLOCK_LENGTH,
    CANONICAL_SIGNATURE,
    CONFIDENCE,
    DELAY_SEED_BASE,
    EXPECTED_HASHES,
    MARKETS,
    NEIGHBOUR_TOP_K,
    RESAMPLES,
    SELECTION_BARS,
    SOURCE,
    TEST_BARS,
    TOP_K,
    candidate_grid,
    load_canonical_returns,
    load_snapshot,
)
from .stats import (
    absolute_return_bootstrap,
    build_top_k_path,
    calendar_stability,
    delay_path,
    expected_shortfall_5pct,
    fold_stability,
    frame_metrics,
    noncircular_block_indices,
    paired_metric_delta_bootstrap,
    reprice,
    return_metrics,
)


def analyze_market(artifact_dir: Path, market: str) -> dict[str, Any]:
    prices = load_snapshot(
        artifact_dir / market / "snapshot" / f"okx-{market}-1Dutc.csv",
        market,
    )
    canonical = load_canonical_returns(
        artifact_dir / market / "walk_forward_returns.csv",
        market,
    )
    candidate, fold_records = build_top_k_path(prices, top_k=TOP_K)
    if not candidate.index.equals(canonical.index):
        raise ValueError("candidate and canonical evaluation timestamps must match")
    baseline_metrics = frame_metrics(candidate)
    benchmark_returns = canonical["benchmark_volatility_targeted_long_return"]
    adaptive_returns = canonical["strategy_return"]
    benchmark_metrics = return_metrics(benchmark_returns)
    adaptive_metrics = return_metrics(adaptive_returns)
    benchmark_inference = paired_metric_delta_bootstrap(
        candidate["strategy_return"],
        benchmark_returns,
        seed=BENCHMARK_SEEDS[market],
    )
    adaptive_inference = paired_metric_delta_bootstrap(
        candidate["strategy_return"],
        adaptive_returns,
        seed=ADAPTIVE_SEEDS[market],
    )
    folds = fold_stability(candidate)
    calendar = calendar_stability(candidate)
    costs = {
        f"{cost:g}": frame_metrics(reprice(candidate, cost)) for cost in ALL_IN_COSTS_BPS
    }
    neighbourhood = {}
    for top_k in NEIGHBOUR_TOP_K:
        frame, _ = build_top_k_path(prices, top_k=top_k)
        neighbourhood[f"top_{top_k}"] = frame_metrics(frame)
    neighbourhood_passes = all(
        float(metrics["total_return"]) > 0.0
        and float(metrics["sharpe"]) > 0.0
        and float(metrics["max_drawdown"]) >= -0.40
        for metrics in neighbourhood.values()
    )
    tail = {
        "expected_shortfall_5pct": expected_shortfall_5pct(candidate["strategy_return"]),
        "benchmark_expected_shortfall_5pct": expected_shortfall_5pct(benchmark_returns),
    }
    tail_passes = (
        float(baseline_metrics["max_drawdown"]) > float(benchmark_metrics["max_drawdown"])
        and tail["expected_shortfall_5pct"] > tail["benchmark_expected_shortfall_5pct"]
        and float(baseline_metrics["max_drawdown"]) >= -0.35
    )
    delay_scenarios: dict[str, Any] = {}
    scenario_index = 0
    for total_delay in (2, 3):
        for cost in ALL_IN_COSTS_BPS:
            delayed = delay_path(candidate, total_delay, cost)
            metrics = frame_metrics(delayed)
            bootstrap = absolute_return_bootstrap(
                delayed["strategy_return"],
                seed=DELAY_SEED_BASE[market] + scenario_index,
            )
            checks = {
                "positive_total_return": float(metrics["total_return"]) > 0.0,
                "positive_sharpe": float(metrics["sharpe"]) > 0.0,
                "max_drawdown_floor": float(metrics["max_drawdown"]) >= -0.40,
                "positive_mean_lower_bound": bootstrap["annualized_mean_lower"] > 0.0,
                "positive_sharpe_lower_bound": bootstrap["sharpe_lower"] > 0.0,
            }
            key = f"delay_{total_delay}_bars_cost_{cost:g}_bps"
            delay_scenarios[key] = {
                "total_delay_bars": total_delay,
                "all_in_cost_bps": cost,
                "metrics": metrics,
                "bootstrap": bootstrap,
                "passes": all(checks.values()),
                "failed_checks": [name for name, passed in checks.items() if not passed],
            }
            scenario_index += 1
    delay_passes = all(details["passes"] for details in delay_scenarios.values())
    benchmark_gate = (
        float(baseline_metrics["sharpe"]) > float(benchmark_metrics["sharpe"])
        and float(baseline_metrics["calmar"]) > float(benchmark_metrics["calmar"])
        and benchmark_inference["sharpe_delta"]["lower"] > 0.0
        and benchmark_inference["calmar_delta"]["lower"] > 0.0
    )
    cost_gate = (
        float(baseline_metrics["annualized_turnover"]) <= 20.0
        and float(costs["15"]["total_return"]) > 0.0
        and float(costs["15"]["sharpe"]) > 0.0
    )
    compact_metric_names = (
        "total_return",
        "sharpe",
        "max_drawdown",
        "annualized_turnover",
    )
    compact_costs = {
        name: {key: metrics[key] for key in compact_metric_names}
        for name, metrics in costs.items()
    }
    compact_neighbourhood = {
        name: {key: metrics[key] for key in compact_metric_names}
        for name, metrics in neighbourhood.items()
    }
    compact_delays = {
        "scenarios_tested": len(delay_scenarios),
        "scenario_results": [
            {
                "scenario": name,
                "passes": details["passes"],
                "failed_checks": details["failed_checks"],
            }
            for name, details in sorted(delay_scenarios.items())
        ],
        "minimum_total_return": min(
            details["metrics"]["total_return"] for details in delay_scenarios.values()
        ),
        "minimum_sharpe": min(
            details["metrics"]["sharpe"] for details in delay_scenarios.values()
        ),
        "worst_max_drawdown": min(
            details["metrics"]["max_drawdown"] for details in delay_scenarios.values()
        ),
        "minimum_annualized_mean_95pct_lower": min(
            details["bootstrap"]["annualized_mean_lower"]
            for details in delay_scenarios.values()
        ),
        "minimum_sharpe_95pct_lower": min(
            details["bootstrap"]["sharpe_lower"]
            for details in delay_scenarios.values()
        ),
        "passes": delay_passes,
    }
    gates = {
        "development_benchmark_relative_risk_adjusted": "pass" if benchmark_gate else "fail",
        "fold_stability": "pass" if folds["passes"] else "fail",
        "year_stability": "pass" if calendar["passes"] else "fail",
        "turnover_and_5_7.5_10_15bps_viability": "pass" if cost_gate else "fail",
        "parameter_neighbourhood_stability": "pass" if neighbourhood_passes else "fail",
        "tail_risk": "pass" if tail_passes else "fail",
        "execution_delay_robustness": "pass" if delay_passes else "fail",
        "separate_spread_slippage_impact_latency": "blocked",
        "capacity": "blocked",
        "untouched_market_validation": "blocked",
        "prospective_forward_validation": "blocked",
    }
    return {
        "evaluation": {
            "start": candidate.index[0].isoformat(),
            "end": candidate.index[-1].isoformat(),
            "observations": len(candidate),
            "fold_count": len(fold_records),
            "candidate_grid_size": len(candidate_grid()),
            "selected_ensemble_size": TOP_K,
        },
        "metrics_5bps": baseline_metrics,
        "volatility_targeted_long": benchmark_metrics,
        "canonical_adaptive": adaptive_metrics,
        "bootstrap_vs_volatility_targeted_long": benchmark_inference,
        "bootstrap_vs_canonical_adaptive": adaptive_inference,
        "fold_stability": folds,
        "calendar_stability": calendar,
        "cost_scenarios_bps": compact_costs,
        "parameter_neighbourhood": compact_neighbourhood,
        "tail_risk": tail,
        "execution_delay_scenarios": compact_delays,
        "fold_selection_summary": {
            "records_sha256": hashlib.sha256(
                json.dumps(
                    fold_records,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest(),
            "folds": len(fold_records),
            "candidates_tested_per_fold": len(candidate_grid()),
            "selected_members_per_fold": TOP_K,
            "selection_frequency": dict(
                sorted(
                    {
                        (
                            f"m={record['momentum_lookback']}|"
                            f"r={record['reversal_lookback']}|"
                            f"trend={record['trend_weight']:.2f}"
                        ): sum(
                            selected["momentum_lookback"]
                            == record["momentum_lookback"]
                            and selected["reversal_lookback"]
                            == record["reversal_lookback"]
                            and selected["trend_weight"] == record["trend_weight"]
                            for fold in fold_records
                            for selected in fold["selected"]
                        )
                        for record in [
                            {
                                "momentum_lookback": momentum,
                                "reversal_lookback": reversal,
                                "trend_weight": trend_weight,
                            }
                            for momentum, reversal, trend_weight in candidate_grid()
                        ]
                    }.items()
                )
            ),
        },
        "gates": gates,
    }


def analyze_artifact(artifact_dir: Path) -> dict[str, Any]:
    markets = {market: analyze_market(artifact_dir, market) for market in MARKETS}
    all_market_gates = {
        gate: (
            "pass"
            if all(details["gates"][gate] == "pass" for details in markets.values())
            else "blocked"
            if any(details["gates"][gate] == "blocked" for details in markets.values())
            else "fail"
        )
        for gate in next(iter(markets.values()))["gates"]
    }
    freeze_required = (
        "development_benchmark_relative_risk_adjusted",
        "fold_stability",
        "year_stability",
        "turnover_and_5_7.5_10_15bps_viability",
        "parameter_neighbourhood_stability",
        "tail_risk",
        "execution_delay_robustness",
    )
    architecture_freeze_eligible = all(all_market_gates[gate] == "pass" for gate in freeze_required)
    live_eligible = architecture_freeze_eligible and all(
        status == "pass" for status in all_market_gates.values()
    )
    verdict = "supported" if live_eligible else "rejected"
    return {
        "hypothesis": (
            "A fold-local equal-weight ensemble of the top three candidates selected by the "
            "canonical prior-window score reduces fold concentration and passes every BTC/ETH "
            "development-stage architecture-freeze and deployment gate."
        ),
        "economic_rationale": (
            "Winner-take-all parameter selection can amplify estimation noise and concentrate "
            "profits in a few folds. Averaging only the three strongest prior-window candidates "
            "retains selection information while diversifying model-selection error."
        ),
        "canonical_signature": CANONICAL_SIGNATURE,
        "candidate_accounting": {
            "architecture_candidates_searched": 1,
            "passed": 1 if live_eligible else 0,
            "rejected": 0 if live_eligible else 1,
            "declared_grid_members_scored_per_fold": len(candidate_grid()),
            "neighbourhood_stresses": ["top_2", "top_4"],
            "cost_stresses_bps": list(ALL_IN_COSTS_BPS),
            "delay_stresses_total_bars": [2, 3],
        },
        "source": SOURCE,
        "expected_hashes": EXPECTED_HASHES,
        "method": {
            "baseline_fee_bps_one_way": BASELINE_COST_BPS,
            "selection_bars": SELECTION_BARS,
            "test_bars": TEST_BARS,
            "top_k": TOP_K,
            "ensemble_weighting": "equal weight across the top three selection-score candidates",
            "execution": "one-bar delayed candidate positions averaged within each fold",
            "fold_boundary": "aggregate prior position carried into next fold turnover",
            "all_in_cost_stresses_bps": list(ALL_IN_COSTS_BPS),
            "separate_execution_friction": "not measured; blocked",
            "bootstrap": {
                "method": "paired non-circular moving blocks over observed daily returns",
                "block_length": BLOCK_LENGTH,
                "resamples": RESAMPLES,
                "confidence": CONFIDENCE,
            },
            "no_sol_tuning": True,
        },
        "markets": markets,
        "joint_gates": all_market_gates,
        "architecture_freeze_eligible": architecture_freeze_eligible,
        "live_eligible": live_eligible,
        "verdict": verdict,
        "limitations": [
            (
                "BTC-USDT and ETH-USDT are development markets and may be used only "
                "for architecture design."
            ),
            (
                "SOL-USDT was not read or used by this analysis and remains prohibited "
                "for same-market tuning."
            ),
            (
                "Top-2 and top-4 are neighbourhood stresses, not separately selected "
                "candidate architectures."
            ),
            (
                "Moving-block resampling creates artificial joins and preserves "
                "dependence only within blocks."
            ),
            (
                "The delayed paths shift observed daily positions and are not executable "
                "next-open fills."
            ),
            (
                "The 7.5/10/15 bps scenarios are aggregate all-in repricings, not "
                "measured friction components."
            ),
            "Capacity and prospective paper evidence remain unavailable.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = analyze_artifact(args.artifact_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
