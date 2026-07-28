from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from gpt_quant.realized_edge_hysteresis import (
    ANNUALIZATION,
    FEE_ONE_WAY_BPS,
    INNOVATION_LOOKBACK,
    MAD_TO_SIGMA,
    UNCERTAINTY_Z,
    apply_target_innovation_hysteresis,
)

_BOOTSTRAP_BLOCK_HOURS = 168
_BOOTSTRAP_RESAMPLES = 5_000
_BOOTSTRAP_SEED = 20_260_728
_EPSILON = 1e-12


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _max_drawdown(returns: np.ndarray) -> float:
    nav = np.cumprod(1.0 + returns)
    peak = np.maximum.accumulate(nav)
    return float(np.min(nav / peak - 1.0))


def _summarize(
    returns: np.ndarray,
    turnover: np.ndarray,
    position: np.ndarray,
    folds: np.ndarray,
    timestamps: pd.DatetimeIndex,
) -> dict[str, Any]:
    years = len(returns) / ANNUALIZATION
    total_return = float(np.prod(1.0 + returns) - 1.0)
    annualized_mean = float(np.mean(returns) * ANNUALIZATION)
    annualized_volatility = float(np.std(returns, ddof=0) * math.sqrt(ANNUALIZATION))
    sharpe = annualized_mean / annualized_volatility
    cagr = float((1.0 + total_return) ** (1.0 / years) - 1.0)
    max_drawdown = _max_drawdown(returns)
    annualized_turnover = float(np.mean(turnover) * ANNUALIZATION)
    edge_per_turnover = annualized_mean / annualized_turnover
    trade_count = int(np.sum(turnover > _EPSILON))

    fold_returns = {
        str(int(fold)): float(np.prod(1.0 + returns[folds == fold]) - 1.0)
        for fold in np.unique(folds)
    }
    positive_fold_returns = [value for value in fold_returns.values() if value > 0.0]
    maximum_positive_fold_share = (
        max(positive_fold_returns) / sum(positive_fold_returns)
        if positive_fold_returns
        else None
    )
    years_array = timestamps.year.to_numpy()
    year_returns = {
        str(int(year)): float(np.prod(1.0 + returns[years_array == year]) - 1.0)
        for year in np.unique(years_array)
    }

    return {
        "observations": len(returns),
        "net_total_return": total_return,
        "net_annualized_arithmetic_mean": annualized_mean,
        "annualized_volatility": annualized_volatility,
        "sharpe": sharpe,
        "cagr": cagr,
        "max_drawdown": max_drawdown,
        "calmar": cagr / abs(max_drawdown),
        "annualized_turnover": annualized_turnover,
        "net_edge_per_turnover": edge_per_turnover,
        "net_edge_per_turnover_bps": edge_per_turnover * 10_000.0,
        "trade_count": trade_count,
        "average_holding_hours": len(returns) / trade_count,
        "time_in_market": float(np.mean(np.abs(position) > _EPSILON)),
        "exchange_fee_sum": float(np.sum(turnover) * FEE_ONE_WAY_BPS / 10_000.0),
        "profitable_folds": sum(value > 0.0 for value in fold_returns.values()),
        "maximum_positive_fold_share": maximum_positive_fold_share,
        "fold_returns": fold_returns,
        "positive_years": sum(value > 0.0 for value in year_returns.values()),
        "year_returns": year_returns,
    }


def _paired_block_bootstrap(
    difference: np.ndarray,
    folds: np.ndarray,
) -> dict[str, Any]:
    rng = np.random.default_rng(_BOOTSTRAP_SEED)
    fold_values = [difference[folds == fold] for fold in np.unique(folds)]
    estimates = np.empty(_BOOTSTRAP_RESAMPLES, dtype=float)
    for resample in range(_BOOTSTRAP_RESAMPLES):
        sampled_folds: list[np.ndarray] = []
        for values in fold_values:
            sampled_blocks: list[np.ndarray] = []
            sampled_count = 0
            maximum_start = len(values) - _BOOTSTRAP_BLOCK_HOURS
            while sampled_count < len(values):
                start = int(rng.integers(0, maximum_start + 1))
                block = values[start : start + _BOOTSTRAP_BLOCK_HOURS]
                sampled_blocks.append(block)
                sampled_count += len(block)
            sampled_folds.append(np.concatenate(sampled_blocks)[: len(values)])
        sample = np.concatenate(sampled_folds)
        estimates[resample] = float(np.mean(sample) * ANNUALIZATION)

    lower, median, upper = np.quantile(estimates, [0.025, 0.5, 0.975])
    return {
        "endpoint": "annualized_arithmetic_mean_return_difference_H1_minus_H0",
        "point_estimate": float(np.mean(difference) * ANNUALIZATION),
        "confidence_interval_95": [float(lower), float(upper)],
        "bootstrap_median": float(median),
        "one_sided_probability_not_positive": float(np.mean(estimates <= 0.0)),
        "block_hours": _BOOTSTRAP_BLOCK_HOURS,
        "resamples": _BOOTSTRAP_RESAMPLES,
        "seed": _BOOTSTRAP_SEED,
        "blocks_cross_fold_boundaries": False,
    }


def _market_result(market: str, path: Path) -> dict[str, Any]:
    source = pd.read_csv(path)
    evaluated, diagnostics = apply_target_innovation_hysteresis(source)
    timestamps = pd.DatetimeIndex(evaluated["timestamp"])
    folds = evaluated["fold"].to_numpy(dtype=int)

    baseline = _summarize(
        evaluated["strategy_return"].to_numpy(dtype=float),
        evaluated["turnover"].to_numpy(dtype=float),
        evaluated["position"].to_numpy(dtype=float),
        folds,
        timestamps,
    )
    candidate = _summarize(
        evaluated["hysteresis_strategy_return"].to_numpy(dtype=float),
        evaluated["hysteresis_turnover"].to_numpy(dtype=float),
        evaluated["hysteresis_position"].to_numpy(dtype=float),
        folds,
        timestamps,
    )
    candidate["suppressed_decisions"] = diagnostics.suppressed_decisions
    candidate["fallback_decisions"] = diagnostics.fallback_decisions
    candidate["no_trade_frequency"] = diagnostics.no_trade_frequency
    candidate["suppression_rate"] = diagnostics.suppression_rate
    candidate["trade_count_reduction"] = 1.0 - (
        candidate["trade_count"] / baseline["trade_count"]
    )

    bootstrap = _paired_block_bootstrap(
        evaluated["hysteresis_strategy_return"].to_numpy(dtype=float)
        - evaluated["strategy_return"].to_numpy(dtype=float),
        folds,
    )
    criteria = {
        "higher_sharpe": candidate["sharpe"] > baseline["sharpe"],
        "higher_edge_per_turnover": (
            candidate["net_edge_per_turnover"] > baseline["net_edge_per_turnover"]
        ),
        "lower_turnover": candidate["annualized_turnover"] < baseline["annualized_turnover"],
        "lower_fee_sum": candidate["exchange_fee_sum"] < baseline["exchange_fee_sum"],
        "positive_net_total_return": candidate["net_total_return"] > 0.0,
        "drawdown_not_worse_by_more_than_2pp": (
            candidate["max_drawdown"] >= baseline["max_drawdown"] - 0.02
        ),
        "profitable_folds_not_reduced": (
            candidate["profitable_folds"] >= baseline["profitable_folds"]
        ),
        "bootstrap_lower_bound_positive": bootstrap["confidence_interval_95"][0] > 0.0,
    }
    return {
        "market": market,
        "input_file": path.name,
        "input_sha256": _sha256(path),
        "period": {
            "start": timestamps[0].isoformat(),
            "end": timestamps[-1].isoformat(),
            "observations": len(evaluated),
        },
        "baseline_H0": baseline,
        "candidate_H1": candidate,
        "paired_uncertainty": bootstrap,
        "acceptance_criteria": criteria,
        "market_passes": all(criteria.values()),
    }


def _parse_market_file(raw: str) -> tuple[str, Path]:
    market, separator, value = raw.partition("=")
    if not separator or not market or not value:
        raise argparse.ArgumentTypeError("--market-file must use MARKET=/path/to/file.csv")
    return market, Path(value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--market-file", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    parsed_market_files = [_parse_market_file(value) for value in arguments.market_file]
    if len({market for market, _ in parsed_market_files}) != len(parsed_market_files):
        raise ValueError("duplicate --market-file market")
    market_files = dict(parsed_market_files)
    if set(market_files) != {"BTC-USDT", "ETH-USDT"}:
        raise ValueError("the frozen experiment requires exactly BTC-USDT and ETH-USDT")

    markets = {
        market: _market_result(market, market_files[market])
        for market in sorted(market_files)
    }
    report: dict[str, Any] = {
        "family_id": "target-innovation-hysteresis-v1",
        "issue": 542,
        "candidate_count": 1,
        "bar": "1H",
        "execution": "spot_long_cash_close_to_close",
        "fee_one_way_bps": FEE_ONE_WAY_BPS,
        "policy": {
            "innovation_lookback_hours": INNOVATION_LOOKBACK,
            "mad_to_sigma": MAD_TO_SIGMA,
            "uncertainty_z": UNCERTAINTY_Z,
            "equality_action": "no_trade",
            "incomplete_history_action": "canonical_target",
            "fold_state_reset": False,
        },
        "execution_diagnostics": {
            "spread": "not_measured",
            "slippage": "not_measured",
            "impact": "not_measured",
            "latency": "not_measured",
            "no_fill": "not_modeled",
            "partial_fill": "not_modeled",
            "adverse_selection": "not_measured",
        },
        "markets": markets,
        "verdict": (
            "overlay_supported_development_only_underlying_strategy_rejected"
            if all(result["market_passes"] for result in markets.values())
            else "rejected"
        ),
        "untouched_replication_consumed": False,
        "prospective_shadow_evidence_consumed": False,
    }
    canonical_body = json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
    report["result_id"] = hashlib.sha256(canonical_body).hexdigest()
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
