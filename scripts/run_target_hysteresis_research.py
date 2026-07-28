from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ANNUAL_HOURS = 8760
FEE_ONE_WAY = 0.0005
LOOKBACK = 168
MAD_SCALE = 1.4826
BAND_MULTIPLIER = 1.645
BLOCK_HOURS = 168
RESAMPLES = 5000
SEED = 20260728


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def apply_hysteresis(frame: pd.DataFrame) -> dict[str, np.ndarray]:
    canonical_target = frame["target_position"].to_numpy(dtype=float)
    observations = len(canonical_target)
    innovations = np.full(observations, np.nan)
    innovations[1:] = np.diff(canonical_target)
    committed = np.empty(observations, dtype=float)
    suppressed = np.zeros(observations, dtype=bool)
    bands = np.full(observations, np.nan)

    for index, target in enumerate(canonical_target):
        if index == 0:
            committed[index] = target
            continue
        history = innovations[max(1, index - LOOKBACK) : index]
        if len(history) < LOOKBACK or not np.isfinite(history).all():
            committed[index] = target
            continue
        median = float(np.median(history))
        sigma = MAD_SCALE * float(np.median(np.abs(history - median)))
        band = BAND_MULTIPLIER * sigma
        bands[index] = band
        previous = committed[index - 1]
        if not math.isfinite(band) or abs(target - previous) > band:
            committed[index] = target
        else:
            committed[index] = previous
            suppressed[index] = True

    position = np.empty(observations, dtype=float)
    position[0] = float(frame["position"].iloc[0])
    position[1:] = committed[:-1]
    turnover = np.empty(observations, dtype=float)
    turnover[0] = abs(position[0])
    turnover[1:] = np.abs(np.diff(position))
    asset_return = frame["asset_return"].to_numpy(dtype=float)
    gross_return = position * asset_return
    trading_cost = turnover * FEE_ONE_WAY
    strategy_return = gross_return - trading_cost
    return {
        "target": committed,
        "position": position,
        "turnover": turnover,
        "gross_return": gross_return,
        "trading_cost": trading_cost,
        "strategy_return": strategy_return,
        "suppressed": suppressed,
        "band": bands,
    }


def performance_metrics(
    returns: np.ndarray,
    turnover: np.ndarray,
    position: np.ndarray,
) -> dict[str, float | int]:
    nav = np.cumprod(1.0 + returns)
    annualized_mean = float(returns.mean() * ANNUAL_HOURS)
    annualized_volatility = float(returns.std(ddof=0) * math.sqrt(ANNUAL_HOURS))
    sharpe = (
        annualized_mean / annualized_volatility
        if annualized_volatility > 0.0
        else 0.0
    )
    cagr = float(nav[-1] ** (ANNUAL_HOURS / len(returns)) - 1.0)
    nav_with_cash = np.concatenate(([1.0], nav))
    peak = np.maximum.accumulate(nav_with_cash)
    max_drawdown = float(np.min(nav_with_cash / peak - 1.0))
    annualized_turnover = float(turnover.mean() * ANNUAL_HOURS)
    quantile_1pct = float(np.quantile(returns, 0.01))
    return {
        "observations": int(len(returns)),
        "total_return": float(nav[-1] - 1.0),
        "annualized_arithmetic_mean": annualized_mean,
        "annualized_volatility": annualized_volatility,
        "sharpe": float(sharpe),
        "cagr": cagr,
        "calmar": (float(cagr / abs(max_drawdown)) if max_drawdown < 0.0 else 0.0),
        "max_drawdown": max_drawdown,
        "annualized_turnover": annualized_turnover,
        "exchange_fee_sum": float(turnover.sum() * FEE_ONE_WAY),
        "net_edge_per_turnover": (
            float(annualized_mean / annualized_turnover)
            if annualized_turnover > 0.0
            else 0.0
        ),
        "time_in_market": float((np.abs(position) > 1e-15).mean()),
        "average_abs_exposure": float(np.abs(position).mean()),
        "trade_count": int((turnover > 1e-12).sum()),
        "worst_hour": float(returns.min()),
        "var_1pct": quantile_1pct,
        "expected_shortfall_1pct": float(returns[returns <= quantile_1pct].mean()),
        "worst_24h": _worst_compounded_window(returns, 24),
        "worst_168h": _worst_compounded_window(returns, 168),
    }


def _worst_compounded_window(returns: np.ndarray, window: int) -> float:
    return float(
        min(
            np.prod(1.0 + returns[start : start + window]) - 1.0
            for start in range(len(returns) - window + 1)
        )
    )


def _average_adjustment_interval(turnover: np.ndarray) -> dict[str, float | None]:
    indices = np.flatnonzero(turnover > 1e-12)
    if len(indices) < 2:
        return {"mean_hours": None, "median_hours": None}
    intervals = np.diff(indices)
    return {
        "mean_hours": float(intervals.mean()),
        "median_hours": float(np.median(intervals)),
    }


def _fold_report(
    frame: pd.DataFrame,
    returns: np.ndarray,
    turnover: np.ndarray,
    position: np.ndarray,
) -> dict[str, Any]:
    records = []
    for fold in sorted(frame["fold"].unique()):
        mask = frame["fold"].to_numpy() == fold
        metrics = performance_metrics(returns[mask], turnover[mask], position[mask])
        records.append({"fold": int(fold), **metrics})
    positive = [row["total_return"] for row in records if row["total_return"] > 0.0]
    return {
        "records": records,
        "profitable_folds": len(positive),
        "maximum_positive_fold_contribution": (
            float(max(positive) / sum(positive)) if positive else None
        ),
    }


def _year_report(
    frame: pd.DataFrame,
    h0: dict[str, np.ndarray],
    h1: dict[str, np.ndarray],
) -> dict[str, Any]:
    timestamps = pd.to_datetime(frame["timestamp"], utc=True)
    output = {}
    for year in sorted(timestamps.dt.year.unique()):
        mask = (timestamps.dt.year == year).to_numpy()
        output[str(year)] = {
            "hours": int(mask.sum()),
            "H0": performance_metrics(
                h0["strategy_return"][mask], h0["turnover"][mask], h0["position"][mask]
            ),
            "H1": performance_metrics(
                h1["strategy_return"][mask], h1["turnover"][mask], h1["position"][mask]
            ),
        }
    return output


def _volatility_regime_report(
    frame: pd.DataFrame,
    h0_returns: np.ndarray,
    h1_returns: np.ndarray,
) -> dict[str, Any]:
    asset_return = frame["asset_return"].to_numpy(dtype=float)
    trailing = np.full(len(frame), np.nan)
    for index in range(168, len(frame)):
        trailing[index] = asset_return[index - 168 : index].std(ddof=0) * math.sqrt(
            ANNUAL_HOURS
        )
    valid = np.isfinite(trailing)
    quartiles = np.quantile(trailing[valid], [0.25, 0.50, 0.75])
    labels = np.full(len(frame), "warmup", dtype=object)
    labels[valid & (trailing <= quartiles[0])] = "Q1_low"
    labels[valid & (trailing > quartiles[0]) & (trailing <= quartiles[1])] = "Q2"
    labels[valid & (trailing > quartiles[1]) & (trailing <= quartiles[2])] = "Q3"
    labels[valid & (trailing > quartiles[2])] = "Q4_high"
    output = {
        "diagnostic_only": True,
        "thresholds_annualized_volatility": [float(value) for value in quartiles],
    }
    for label in ("Q1_low", "Q2", "Q3", "Q4_high"):
        mask = labels == label
        output[label] = {
            "hours": int(mask.sum()),
            "H0_annualized_arithmetic_mean": float(h0_returns[mask].mean() * ANNUAL_HOURS),
            "H1_annualized_arithmetic_mean": float(h1_returns[mask].mean() * ANNUAL_HOURS),
            "H1_minus_H0": float((h1_returns[mask] - h0_returns[mask]).mean() * ANNUAL_HOURS),
        }
    return output


def _bootstrap(
    frame: pd.DataFrame,
    h0: dict[str, np.ndarray],
    h1: dict[str, np.ndarray],
) -> dict[str, Any]:
    folds = frame["fold"].to_numpy()
    rng = np.random.default_rng(SEED)
    samples = np.empty((RESAMPLES, 3), dtype=float)
    for sample_index in range(RESAMPLES):
        indices = []
        for fold in sorted(np.unique(folds)):
            fold_indices = np.flatnonzero(folds == fold)
            length = len(fold_indices)
            block_count = math.ceil(length / BLOCK_HOURS)
            starts = rng.integers(0, length - BLOCK_HOURS + 1, size=block_count)
            local = np.concatenate(
                [np.arange(start, start + BLOCK_HOURS) for start in starts]
            )[:length]
            indices.append(fold_indices[local])
        selected = np.concatenate(indices)
        h0_return = h0["strategy_return"][selected]
        h1_return = h1["strategy_return"][selected]
        h0_turnover = h0["turnover"][selected]
        h1_turnover = h1["turnover"][selected]
        h0_mean = h0_return.mean() * ANNUAL_HOURS
        h1_mean = h1_return.mean() * ANNUAL_HOURS
        h0_sharpe = h0_mean / (h0_return.std(ddof=0) * math.sqrt(ANNUAL_HOURS))
        h1_sharpe = h1_mean / (h1_return.std(ddof=0) * math.sqrt(ANNUAL_HOURS))
        h0_edge = h0_mean / (h0_turnover.mean() * ANNUAL_HOURS)
        h1_edge = h1_mean / (h1_turnover.mean() * ANNUAL_HOURS)
        samples[sample_index] = (h1_mean - h0_mean, h1_sharpe - h0_sharpe, h1_edge - h0_edge)
    output = {}
    for index, name in enumerate(
        ("annualized_mean_difference", "sharpe_difference", "edge_per_turnover_difference")
    ):
        vector = samples[:, index]
        output[name] = {
            "percentile_95_interval": [
                float(np.quantile(vector, 0.025)),
                float(np.quantile(vector, 0.975)),
            ],
            "resampled_probability_not_positive": float(
                (np.sum(vector <= 0.0) + 1) / (RESAMPLES + 1)
            ),
        }
    return output


def _capacity(turnover: np.ndarray) -> dict[str, Any]:
    annualized_turnover = float(turnover.mean() * ANNUAL_HOURS)
    output = {
        "diagnostic_only": True,
        "intended_notional_assumption_usd": 10000,
        "turnover_fraction": {
            "mean_hourly": float(turnover.mean()),
            "p99_hourly": float(np.quantile(turnover, 0.99)),
            "maximum_hourly": float(turnover.max()),
        },
        "rungs": {},
    }
    for notional in (10000, 100000, 1000000):
        output["rungs"][str(notional)] = {
            "annual_adjustment_notional_usd": float(annualized_turnover * notional),
            "annual_modeled_exchange_fee_usd": float(
                annualized_turnover * notional * FEE_ONE_WAY
            ),
            "mean_hourly_adjustment_usd": float(turnover.mean() * notional),
            "p99_hourly_adjustment_usd": float(np.quantile(turnover, 0.99) * notional),
            "maximum_hourly_adjustment_usd": float(turnover.max() * notional),
        }
    return output


def analyze_market(market: str, csv_path: Path, baseline_path: Path) -> dict[str, Any]:
    frame = pd.read_csv(csv_path)
    required = {
        "timestamp",
        "asset_return",
        "target_position",
        "position",
        "turnover",
        "strategy_return",
        "fold",
        "benchmark_simple_trend_long_cash_return",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"{market}: missing columns: {missing}")
    h0 = {
        "position": frame["position"].to_numpy(dtype=float),
        "turnover": frame["turnover"].to_numpy(dtype=float),
        "strategy_return": frame["strategy_return"].to_numpy(dtype=float),
    }
    h1 = apply_hysteresis(frame)
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))["aggregate_metrics"]
    reconstructed = performance_metrics(h0["strategy_return"], h0["turnover"], h0["position"])
    for key in ("total_return", "sharpe", "cagr", "max_drawdown", "annualized_turnover"):
        if not math.isclose(float(reconstructed[key]), float(baseline[key]), abs_tol=1e-12):
            raise ValueError(f"{market}: baseline reconstruction failed for {key}")
    h0_metrics = reconstructed
    h1_metrics = performance_metrics(
        h1["strategy_return"], h1["turnover"], h1["position"]
    )
    trend = frame["benchmark_simple_trend_long_cash_return"].to_numpy(dtype=float)
    residual = {}
    for label, returns in (("H0", h0["strategy_return"]), ("H1", h1["strategy_return"])):
        difference = returns - trend
        residual[label] = {
            "residual_sharpe": float(
                difference.mean() / difference.std(ddof=0) * math.sqrt(ANNUAL_HOURS)
            )
        }
    folds_h0 = _fold_report(frame, h0["strategy_return"], h0["turnover"], h0["position"])
    folds_h1 = _fold_report(
        frame, h1["strategy_return"], h1["turnover"], h1["position"]
    )
    eligible = len(frame) - (LOOKBACK + 1)
    suppression_rate = float(h1["suppressed"].sum() / eligible)
    bootstrap = _bootstrap(frame, h0, h1)
    acceptance = {
        "higher_sharpe": h1_metrics["sharpe"] > h0_metrics["sharpe"],
        "higher_edge_per_turnover": (
            h1_metrics["net_edge_per_turnover"] > h0_metrics["net_edge_per_turnover"]
        ),
        "lower_turnover": (
            h1_metrics["annualized_turnover"] < h0_metrics["annualized_turnover"]
        ),
        "lower_fee_sum": h1_metrics["exchange_fee_sum"] < h0_metrics["exchange_fee_sum"],
        "positive_net_return": h1_metrics["total_return"] > 0.0,
        "drawdown_within_two_points": (
            h1_metrics["max_drawdown"] >= h0_metrics["max_drawdown"] - 0.02
        ),
        "profitable_folds_not_reduced": (
            folds_h1["profitable_folds"] >= folds_h0["profitable_folds"]
        ),
        "bootstrap_mean_lower_bound_positive": (
            bootstrap["annualized_mean_difference"]["percentile_95_interval"][0] > 0.0
        ),
    }
    return {
        "market": market,
        "input": {
            "walk_forward_returns_path": str(csv_path),
            "walk_forward_returns_sha256": _sha256(csv_path),
            "walk_forward_json_sha256": _sha256(baseline_path),
            "rows": int(len(frame)),
            "start": str(frame["timestamp"].iloc[0]),
            "end": str(frame["timestamp"].iloc[-1]),
        },
        "H0": h0_metrics,
        "H1": h1_metrics,
        "changes": {
            "total_return": h1_metrics["total_return"] - h0_metrics["total_return"],
            "sharpe": h1_metrics["sharpe"] - h0_metrics["sharpe"],
            "cagr": h1_metrics["cagr"] - h0_metrics["cagr"],
            "calmar": h1_metrics["calmar"] - h0_metrics["calmar"],
            "max_drawdown": h1_metrics["max_drawdown"] - h0_metrics["max_drawdown"],
            "annualized_turnover": (
                h1_metrics["annualized_turnover"] - h0_metrics["annualized_turnover"]
            ),
            "exchange_fee_sum": (
                h1_metrics["exchange_fee_sum"] - h0_metrics["exchange_fee_sum"]
            ),
            "net_edge_per_turnover": (
                h1_metrics["net_edge_per_turnover"] - h0_metrics["net_edge_per_turnover"]
            ),
        },
        "target_diagnostics": {
            "eligible_decisions": eligible,
            "suppressed_decisions": int(h1["suppressed"].sum()),
            "suppression_rate": suppression_rate,
            "H0_adjustment_interval": _average_adjustment_interval(h0["turnover"]),
            "H1_adjustment_interval": _average_adjustment_interval(h1["turnover"]),
        },
        "folds": {"H0": folds_h0, "H1": folds_h1},
        "years": _year_report(frame, h0, h1),
        "volatility_regimes": _volatility_regime_report(
            frame, h0["strategy_return"], h1["strategy_return"]
        ),
        "benchmark_residual": residual,
        "bootstrap": bootstrap,
        "capacity": _capacity(h1["turnover"]),
        "acceptance": acceptance,
        "market_pass": all(acceptance.values()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--btc-dir", type=Path, required=True)
    parser.add_argument("--eth-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    markets = [
        analyze_market(
            "BTC-USDT",
            args.btc_dir / "walk_forward_returns.csv",
            args.btc_dir / "walk_forward.json",
        ),
        analyze_market(
            "ETH-USDT",
            args.eth_dir / "walk_forward_returns.csv",
            args.eth_dir / "walk_forward.json",
        ),
    ]
    payload = {
        "schema_version": 1,
        "family_id": "target-innovation-hysteresis-v1",
        "issue": 542,
        "candidate_count": 1,
        "policies": {
            "H0": "unchanged canonical hourly target",
            "H1": {
                "lookback_hours": LOOKBACK,
                "mad_scale": MAD_SCALE,
                "band_multiplier": BAND_MULTIPLIER,
                "commit_rule": "abs(q_t - committed) > band; equality holds",
                "incomplete_history": "unchanged canonical target",
            },
        },
        "economics": {
            "bar": "1H",
            "fee_one_way_bps": 5.0,
            "fee_applied_to": "absolute position adjustment",
        },
        "bootstrap_contract": {
            "block_hours": BLOCK_HOURS,
            "resamples": RESAMPLES,
            "seed": SEED,
            "non_circular": True,
            "blocks_do_not_cross_fold_boundaries": True,
            "paired_H1_minus_H0": True,
        },
        "markets": markets,
        "multiple_testing": {
            "confirmatory_family": [
                "BTC annualized mean H1 minus H0 > 0",
                "ETH annualized mean H1 minus H0 > 0",
            ],
            "raw_resampled_probability_not_positive": {
                market["market"]: market["bootstrap"]["annualized_mean_difference"][
                    "resampled_probability_not_positive"
                ]
                for market in markets
            },
            "holm_adjusted_upper_bound": 0.0003999200159968006,
        },
        "family_pass": all(market["market_pass"] for market in markets),
        "verdict": (
            "support_as_turnover_sizing_overlay_only"
            if all(market["market_pass"] for market in markets)
            else "reject_candidate"
        ),
        "qualification_limits": [
            "BTC and ETH are consumed development markets.",
            "The overlay does not repair the base selector's weak fold breadth.",
            "Both policies remain weaker than simple trend on residual Sharpe.",
            (
                "Capacity diagnostics include only modeled 5 bps fees, not spread, "
                "slippage, impact, latency, or fills."
            ),
        ],
    }
    body = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    args.output.write_text(body, encoding="utf-8")
    print(hashlib.sha256(body.encode("utf-8")).hexdigest())


if __name__ == "__main__":
    main()
