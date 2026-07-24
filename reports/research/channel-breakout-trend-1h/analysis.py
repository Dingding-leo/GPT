from __future__ import annotations

import argparse
import json
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from architecture import (
    ANNUALIZATION,
    BENCHMARKS,
    BLOCK,
    CAPITAL,
    CHANNEL,
    END,
    EPSILON,
    LIQUIDITY_WINDOW,
    MARKETS,
    NEIGHBOURS,
    PARTICIPATION,
    REGIME,
    RESAMPLES,
    SIGNATURE,
    START,
    TAIL,
    TARGET_VOLATILITY,
    TEST_BARS,
    VOLATILITY,
    build_frame,
    load_artifact,
)


def core_metrics(returns: Sequence[float]) -> dict[str, float]:
    values = np.asarray(returns, dtype=float)
    growth = float(np.prod(1.0 + values))
    years = len(values) / ANNUALIZATION
    cagr = growth ** (1.0 / years) - 1.0 if growth > 0 else -1.0
    standard = float(np.std(values, ddof=0))
    nav = np.concatenate(([1.0], np.cumprod(1.0 + values)))
    drawdown = float(np.min(nav / np.maximum.accumulate(nav) - 1.0))
    sharpe = float(np.mean(values)) / standard * math.sqrt(ANNUALIZATION) if standard else 0.0
    return {
        "net_total_return": growth - 1.0,
        "cagr": cagr,
        "sharpe": sharpe,
        "max_drawdown": drawdown,
        "calmar": cagr / abs(drawdown) if drawdown < 0 else 0.0,
    }


def performance(frame: pd.DataFrame) -> dict[str, float | int]:
    returns = frame["strategy_return"].to_numpy(float)
    downside = float(np.sqrt(np.mean(np.square(np.minimum(returns, 0.0)))))
    result: dict[str, float | int] = core_metrics(returns)
    result.update(
        {
            "observations": len(frame),
            "gross_total_return": float(np.prod(1.0 + frame["gross_strategy_return"]) - 1.0),
            "annualized_arithmetic_mean": float(np.mean(returns)) * ANNUALIZATION,
            "sortino": (
                float(np.mean(returns)) / downside * math.sqrt(ANNUALIZATION) if downside else 0.0
            ),
            "annualized_turnover": float(frame["turnover"].mean()) * ANNUALIZATION,
            "average_abs_exposure": float(frame["position"].abs().mean()),
            "exchange_fee_sum": float(frame["trading_cost"].sum()),
        }
    )
    return result


def fold_gate(frame: pd.DataFrame) -> dict[str, Any]:
    values = [
        float(np.prod(1 + frame["strategy_return"].iloc[start : start + TEST_BARS]) - 1)
        for start in range(0, len(frame), TEST_BARS)
    ]
    positive = [value for value in values if value > 0]
    share = max(positive) / sum(positive) if positive else 1.0
    return {
        "fold_count": len(values),
        "profitable_folds": len(positive),
        "best_fold_total_return": max(values),
        "worst_fold_total_return": min(values),
        "max_positive_fold_share": share,
        "passes": len(positive) >= 7 and share <= 0.5,
    }


def calendar_gate(frame: pd.DataFrame, frequency: str, required: int) -> dict[str, Any]:
    periods = frame.index.tz_convert(None).to_period(frequency)
    records = []
    for period in periods.unique():
        subset = frame.loc[periods == period]
        start = period.start_time.tz_localize("UTC")
        end = period.end_time.floor("h").tz_localize("UTC")
        expected = int((end - start) / pd.Timedelta(hours=1)) + 1
        complete = len(subset) == expected and subset.index[0] == start and subset.index[-1] == end
        records.append(
            {
                "period": str(period),
                "complete": complete,
                "total_return": float(np.prod(1 + subset["strategy_return"]) - 1),
            }
        )
    complete = [record for record in records if record["complete"]]
    profitable = [record for record in complete if record["total_return"] > 0]
    return {
        "complete_periods": len(complete),
        "profitable_complete_periods": len(profitable),
        "records": records if frequency == "Y" else [],
        "passes": len(complete) >= required and len(profitable) >= required,
    }


def activity_gate(frame: pd.DataFrame) -> dict[str, Any]:
    active = frame["position"].to_numpy(float) > EPSILON
    starts = np.flatnonzero(active & ~np.concatenate(([False], active[:-1])))
    ends = np.flatnonzero(~active & np.concatenate(([False], active[:-1])))
    durations, episode_returns = [], []
    for start in starts:
        later = ends[ends > start]
        if len(later):
            end = int(later[0])
            durations.append(end - int(start))
            episode_returns.append(
                float(np.prod(1 + frame["strategy_return"].iloc[int(start) : end + 1]) - 1)
            )
    gains = sum(value for value in episode_returns if value > 0)
    losses = -sum(value for value in episode_returns if value < 0)
    profit_factor = gains / losses if losses else (math.inf if gains else 0.0)
    turnover = float(frame["turnover"].mean()) * ANNUALIZATION
    episodes_per_year = len(durations) / (len(frame) / ANNUALIZATION)
    median = float(np.median(durations)) if durations else 0.0
    return {
        "completed_exposure_episodes": len(durations),
        "episodes_per_year": episodes_per_year,
        "median_holding_hours": median,
        "completed_episode_profit_factor": profit_factor,
        "annualized_turnover": turnover,
        "passes": (
            0 < turnover <= 100
            and episodes_per_year >= 20
            and 1 <= median <= 168
            and profit_factor > 1
        ),
    }


def expected_shortfall(values: Sequence[float]) -> float:
    ordered = np.sort(np.asarray(values, dtype=float))
    return float(np.mean(ordered[: math.ceil(len(ordered) * TAIL)]))


def capacity_gate(candles: pd.DataFrame, frame: pd.DataFrame) -> dict[str, Any]:
    liquidity = candles["volume_quote"].rolling(
        LIQUIDITY_WINDOW,
        min_periods=LIQUIDITY_WINDOW,
    )
    liquidity = liquidity.median().shift(1).reindex(frame.index).to_numpy(float)
    returns = frame["strategy_return"].to_numpy(float)
    prior_nav = np.concatenate(([1.0], np.cumprod(1.0 + returns)[:-1]))
    turnover = frame["turnover"].to_numpy(float)
    adjustment = turnover > EPSILON
    observed_participation = np.divide(
        CAPITAL * prior_nav * turnover,
        liquidity,
        out=np.full(len(frame), np.nan),
        where=liquidity > 0,
    )
    supported = np.divide(
        PARTICIPATION * liquidity,
        prior_nav * turnover,
        out=np.full(len(frame), np.nan),
        where=prior_nav * turnover > 0,
    )
    breaches = adjustment & (observed_participation > PARTICIPATION)
    return {
        "adjustment_observations": int(adjustment.sum()),
        "breach_observations": int(breaches.sum()),
        "maximum_participation": float(np.nanmax(observed_participation[adjustment])),
        "maximum_supported_initial_capital_usd": float(np.nanmin(supported[adjustment])),
        "passes": not breaches.any(),
    }


def bootstrap(
    candidate: np.ndarray,
    benchmarks: pd.DataFrame,
    seed: int,
) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    blocks = math.ceil(len(candidate) / BLOCK)
    observed = core_metrics(candidate)
    distributions = {name: {metric: [] for metric in ("sharpe", "calmar")} for name in BENCHMARKS}
    points = {}
    for name, column in BENCHMARKS.items():
        benchmark = core_metrics(benchmarks[column].to_numpy(float))
        points[name] = {
            metric: observed[metric] - benchmark[metric] for metric in ("sharpe", "calmar")
        }
    for _ in range(RESAMPLES):
        starts = rng.integers(0, len(candidate) - BLOCK + 1, size=blocks)
        index = np.concatenate([np.arange(start, start + BLOCK) for start in starts])[
            : len(candidate)
        ]
        sampled = core_metrics(candidate[index])
        for name, column in BENCHMARKS.items():
            benchmark = core_metrics(benchmarks[column].to_numpy(float)[index])
            for metric in ("sharpe", "calmar"):
                distributions[name][metric].append(sampled[metric] - benchmark[metric])
    result = {}
    for name in BENCHMARKS:
        result[name] = {}
        for metric in ("sharpe", "calmar"):
            values = np.asarray(distributions[name][metric])
            result[name][metric] = {
                "point_delta": points[name][metric],
                "lower": float(np.quantile(values, 0.025)),
                "upper": float(np.quantile(values, 0.975)),
            }
    result["passes"] = all(
        result[name][metric]["lower"] > 0 for name in BENCHMARKS for metric in ("sharpe", "calmar")
    )
    return result


def evaluate(root: Path, market: str) -> dict[str, Any]:
    candles, benchmarks, provenance = load_artifact(root, market)
    frame = build_frame(candles)
    metrics = performance(frame)
    folds = fold_gate(frame)
    months = calendar_gate(frame, "M", 18)
    years = calendar_gate(frame, "Y", 2)
    activity = activity_gate(frame)
    capacity = capacity_gate(candles, frame)
    inference = bootstrap(
        frame["strategy_return"].to_numpy(float),
        benchmarks,
        MARKETS[market]["seed"],
    )
    neighbourhood = {
        name: performance(build_frame(candles, **parameters))
        for name, parameters in NEIGHBOURS.items()
    }
    neighbourhood_pass = all(
        value["net_total_return"] > 0 and value["sharpe"] > 0 for value in neighbourhood.values()
    )
    candidate_tail = expected_shortfall(frame["strategy_return"])
    benchmark_tail = expected_shortfall(benchmarks[BENCHMARKS["volatility_targeted_long"]])
    gates = {
        "source_and_exact_5bps": True,
        "net_viability": (metrics["net_total_return"] > 0 and metrics["sharpe"] >= 0.5),
        "benchmark_relative_sharpe_and_calmar": inference["passes"],
        "fold_stability": folds["passes"],
        "month_stability": months["passes"],
        "year_stability": years["passes"],
        "activity": activity["passes"],
        "parameter_neighbourhood": neighbourhood_pass,
        "tail_risk": candidate_tail > benchmark_tail,
        "capacity": capacity["passes"],
    }
    return {
        "market": market,
        "provenance": provenance,
        "metrics": metrics,
        "benchmark_bootstrap": inference,
        "fold_stability": folds,
        "month_stability": months,
        "year_stability": years,
        "activity": activity,
        "neighbourhood": {
            "variants": neighbourhood,
            "passes": neighbourhood_pass,
        },
        "tail_risk": {
            "strategy_expected_shortfall": candidate_tail,
            "volatility_benchmark_expected_shortfall": benchmark_tail,
            "passes": gates["tail_risk"],
        },
        "capacity": capacity,
        "retrospective_gates": gates,
        "retrospective_passes": all(gates.values()),
    }


def build_result(btc_root: Path, eth_root: Path) -> dict[str, Any]:
    markets = {
        "BTC-USDT": evaluate(btc_root, "BTC-USDT"),
        "ETH-USDT": evaluate(eth_root, "ETH-USDT"),
    }
    joint = all(value["retrospective_passes"] for value in markets.values())
    return {
        "canonical_signature": SIGNATURE,
        "hypothesis": (
            "The fixed 1H channel-breakout architecture clears every "
            "retrospective gate in BTC and ETH."
        ),
        "candidate_accounting": {
            "architecture_candidates_searched": 1,
            "architecture_candidates_passed": int(joint),
            "architecture_candidates_rejected": int(not joint),
            "neighbourhood_paths": len(NEIGHBOURS),
            "bootstrap_resamples_per_market": RESAMPLES,
        },
        "fixed_architecture": {
            "channel_lookback_hours": CHANNEL,
            "regime_lookback_hours": REGIME,
            "volatility_lookback_hours": VOLATILITY,
            "target_annualized_volatility": TARGET_VOLATILITY,
            "execution_delay_bars": 1,
            "transaction_cost_bps_one_way": 5.0,
            "modeled_cost_paths": ["5bps_one_way_only"],
        },
        "evaluation": {
            "bar": "1H",
            "start": START.isoformat(),
            "end": END.isoformat(),
            "observations_per_market": 25_920,
            "fold_bars": TEST_BARS,
            "bootstrap_block_hours": BLOCK,
            "bootstrap_resamples": RESAMPLES,
        },
        "markets": markets,
        "joint_retrospective_passes": joint,
        "prospective_execution_diagnostics": {
            key: "blocked_no_prospective_attempts"
            for key in (
                "maker_fill_quality",
                "no_fill_rate",
                "partial_fill_rate",
                "timeout_rate",
                "adverse_selection",
                "latency",
                "prospective_paper_performance",
            )
        },
        "paper_testable": joint,
        "live_eligible": False,
        "verdict": "supported" if joint else "rejected",
        "rejection_reasons": [
            f"{market}:{gate}"
            for market, details in markets.items()
            for gate, passed in details["retrospective_gates"].items()
            if not passed
        ]
        + ["prospective maker and paper evidence is absent"],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--btc-artifact-dir", type=Path, required=True)
    parser.add_argument("--eth-artifact-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = build_result(args.btc_artifact_dir, args.eth_artifact_dir)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
