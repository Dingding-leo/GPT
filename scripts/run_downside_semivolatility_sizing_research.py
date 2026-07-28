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
SHORT_HOURS = 24
SLOW_HOURS = 720
BLOCK_HOURS = 168
RESAMPLES = 5000
SEED = 20260728


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_manifest(root: Path) -> dict[str, str]:
    manifest = root / "artifact-manifest.sha256"
    if not manifest.is_file():
        raise ValueError(f"missing artifact manifest: {manifest}")
    verified: dict[str, str] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        expected, relative = line.split("  ", 1)
        path = root / relative
        actual = sha256(path)
        if actual != expected:
            raise ValueError(f"artifact hash mismatch for {relative}")
        verified[relative] = actual
    return verified


def worst_compounded_window(returns: np.ndarray, window: int) -> float:
    log_returns = np.log1p(returns)
    cumulative = np.concatenate(([0.0], np.cumsum(log_returns)))
    compounded = np.exp(cumulative[window:] - cumulative[:-window]) - 1.0
    return float(compounded.min())


def performance_metrics(
    returns: np.ndarray,
    turnover: np.ndarray,
    position: np.ndarray,
) -> dict[str, Any]:
    nav = np.cumprod(1.0 + returns)
    annualized_mean = float(returns.mean() * ANNUAL_HOURS)
    annualized_volatility = float(returns.std(ddof=0) * math.sqrt(ANNUAL_HOURS))
    sharpe = (
        annualized_mean / annualized_volatility
        if annualized_volatility > 0.0
        else 0.0
    )
    nav_with_cash = np.concatenate(([1.0], nav))
    peak = np.maximum.accumulate(nav_with_cash)
    max_drawdown = float((nav_with_cash / peak - 1.0).min())
    cagr = float(nav[-1] ** (ANNUAL_HOURS / len(returns)) - 1.0)
    quantile_1pct = float(np.quantile(returns, 0.01))
    annualized_turnover = float(turnover.mean() * ANNUAL_HOURS)
    adjustment_indices = np.flatnonzero(turnover > 1e-12)
    adjustment_intervals = (
        np.diff(adjustment_indices)
        if len(adjustment_indices) > 1
        else np.array([], dtype=float)
    )
    return {
        "observations": int(len(returns)),
        "total_return": float(nav[-1] - 1.0),
        "annualized_arithmetic_mean": annualized_mean,
        "annualized_volatility": annualized_volatility,
        "sharpe": float(sharpe),
        "cagr": cagr,
        "calmar": float(cagr / abs(max_drawdown)) if max_drawdown < 0.0 else 0.0,
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
        "mean_hours_between_adjustments": (
            float(adjustment_intervals.mean()) if len(adjustment_intervals) else None
        ),
        "median_hours_between_adjustments": (
            float(np.median(adjustment_intervals)) if len(adjustment_intervals) else None
        ),
        "worst_hour": float(returns.min()),
        "var_1pct": quantile_1pct,
        "expected_shortfall_1pct": float(returns[returns <= quantile_1pct].mean()),
        "worst_24h": worst_compounded_window(returns, 24),
        "worst_168h": worst_compounded_window(returns, 168),
    }


def build_feature(snapshot: pd.DataFrame, oos: pd.DataFrame) -> dict[str, np.ndarray | float]:
    snapshot = snapshot.copy()
    snapshot["timestamp"] = pd.to_datetime(snapshot["timestamp"], utc=True)
    if not snapshot["timestamp"].is_monotonic_increasing:
        raise ValueError("snapshot timestamps must be increasing")
    if snapshot["timestamp"].duplicated().any():
        raise ValueError("snapshot timestamps must be unique")
    if not (snapshot["confirm"] == 1).all():
        raise ValueError("snapshot contains incomplete candles")

    close = snapshot["close"].to_numpy(dtype=float)
    returns = np.full(len(close), np.nan)
    returns[1:] = close[1:] / close[:-1] - 1.0
    downside_squared = np.minimum(returns, 0.0) ** 2
    downside_series = pd.Series(downside_squared)
    short_downside = np.sqrt(
        downside_series.rolling(SHORT_HOURS, min_periods=SHORT_HOURS).mean().to_numpy()
    )
    slow_downside = np.sqrt(
        downside_series.rolling(SLOW_HOURS, min_periods=SLOW_HOURS).mean().to_numpy()
    )

    multiplier = np.ones(len(close), dtype=float)
    valid = (
        np.isfinite(short_downside)
        & np.isfinite(slow_downside)
        & (short_downside > 0.0)
    )
    multiplier[valid] = np.minimum(
        1.0,
        slow_downside[valid] / short_downside[valid],
    )

    timestamp_to_index = {
        timestamp: index for index, timestamp in enumerate(snapshot["timestamp"])
    }
    oos_timestamps = pd.to_datetime(oos["timestamp"], utc=True)
    indices = np.array(
        [timestamp_to_index.get(timestamp, -1) for timestamp in oos_timestamps],
        dtype=int,
    )
    if (indices < 0).any():
        raise ValueError("OOS timestamp is absent from the immutable snapshot")

    canonical_returns = oos["asset_return"].to_numpy(dtype=float)
    snapshot_return_error = float(np.max(np.abs(returns[indices] - canonical_returns)))
    if snapshot_return_error > 1e-12:
        raise ValueError(f"snapshot return mismatch: {snapshot_return_error}")

    return {
        "multiplier": multiplier[indices],
        "short_downside": short_downside[indices],
        "slow_downside": slow_downside[indices],
        "snapshot_return_error": snapshot_return_error,
    }


def baseline_policy(frame: pd.DataFrame) -> dict[str, np.ndarray]:
    columns = {
        "target": "target_position",
        "position": "position",
        "turnover": "turnover",
        "gross_return": "gross_strategy_return",
        "trading_cost": "trading_cost",
        "strategy_return": "strategy_return",
    }
    return {
        key: frame[column].to_numpy(dtype=float) for key, column in columns.items()
    }


def downside_sizing_policy(
    frame: pd.DataFrame,
    multiplier: np.ndarray,
) -> dict[str, np.ndarray]:
    canonical_target = frame["target_position"].to_numpy(dtype=float)
    candidate_target = canonical_target * multiplier
    folds = frame["fold"].to_numpy(dtype=int)
    canonical_position = frame["position"].to_numpy(dtype=float)

    position = np.empty(len(frame), dtype=float)
    position[0] = canonical_position[0]
    for index in range(1, len(frame)):
        if folds[index] != folds[index - 1]:
            position[index] = canonical_position[index] * multiplier[index - 1]
        else:
            position[index] = candidate_target[index - 1]

    turnover = np.empty(len(frame), dtype=float)
    turnover[0] = abs(position[0])
    turnover[1:] = np.abs(np.diff(position))
    asset_return = frame["asset_return"].to_numpy(dtype=float)
    gross_return = position * asset_return
    trading_cost = turnover * FEE_ONE_WAY
    strategy_return = gross_return - trading_cost
    return {
        "target": candidate_target,
        "position": position,
        "turnover": turnover,
        "gross_return": gross_return,
        "trading_cost": trading_cost,
        "strategy_return": strategy_return,
    }


def validate_baseline(
    frame: pd.DataFrame,
    baseline: dict[str, np.ndarray],
    summary: dict[str, Any],
) -> dict[str, float]:
    same_fold = frame["fold"].to_numpy()[1:] == frame["fold"].to_numpy()[:-1]
    lag_error = baseline["position"][1:] - baseline["target"][:-1]
    errors = {
        "position_target_lag_max_abs": float(np.max(np.abs(lag_error[same_fold]))),
        "turnover_reconstruction_max_abs": float(
            np.max(
                np.abs(
                    baseline["turnover"][1:]
                    - np.abs(np.diff(baseline["position"]))
                )
            )
        ),
        "fee_reconstruction_max_abs": float(
            np.max(
                np.abs(
                    baseline["trading_cost"]
                    - baseline["turnover"] * FEE_ONE_WAY
                )
            )
        ),
        "gross_reconstruction_max_abs": float(
            np.max(
                np.abs(
                    baseline["gross_return"]
                    - baseline["position"]
                    * frame["asset_return"].to_numpy(dtype=float)
                )
            )
        ),
        "net_reconstruction_max_abs": float(
            np.max(
                np.abs(
                    baseline["strategy_return"]
                    - (baseline["gross_return"] - baseline["trading_cost"])
                )
            )
        ),
    }
    metrics = performance_metrics(
        baseline["strategy_return"],
        baseline["turnover"],
        baseline["position"],
    )
    for key in (
        "total_return",
        "sharpe",
        "cagr",
        "max_drawdown",
        "annualized_turnover",
    ):
        errors[f"canonical_{key}_error"] = abs(
            float(metrics[key]) - float(summary["aggregate_metrics"][key])
        )
    if max(errors.values()) > 1e-11:
        raise ValueError(f"baseline validation failed: {errors}")
    return errors


def fold_report(frame: pd.DataFrame, policy: dict[str, np.ndarray]) -> dict[str, Any]:
    folds = frame["fold"].to_numpy(dtype=int)
    records = []
    for fold in sorted(np.unique(folds)):
        mask = folds == fold
        records.append(
            {
                "fold": int(fold),
                **performance_metrics(
                    policy["strategy_return"][mask],
                    policy["turnover"][mask],
                    policy["position"][mask],
                ),
            }
        )
    positive = [row["total_return"] for row in records if row["total_return"] > 0.0]
    return {
        "records": records,
        "profitable_folds": len(positive),
        "maximum_positive_fold_contribution": (
            float(max(positive) / sum(positive)) if positive else None
        ),
    }


def year_report(
    frame: pd.DataFrame,
    baseline: dict[str, np.ndarray],
    candidate: dict[str, np.ndarray],
) -> dict[str, Any]:
    years = pd.to_datetime(frame["timestamp"], utc=True).dt.year.to_numpy()
    output = {}
    for year in sorted(np.unique(years)):
        mask = years == year
        output[str(int(year))] = {
            "hours": int(mask.sum()),
            "D0": performance_metrics(
                baseline["strategy_return"][mask],
                baseline["turnover"][mask],
                baseline["position"][mask],
            ),
            "D1": performance_metrics(
                candidate["strategy_return"][mask],
                candidate["turnover"][mask],
                candidate["position"][mask],
            ),
        }
    return output


def risk_regime_report(
    multiplier: np.ndarray,
    baseline_return: np.ndarray,
    candidate_return: np.ndarray,
) -> dict[str, Any]:
    labels = np.empty(len(multiplier), dtype=object)
    labels[multiplier >= 1.0 - 1e-15] = "not_scaled"
    labels[(multiplier < 1.0) & (multiplier >= 0.75)] = "mild_0.75_to_1"
    labels[(multiplier < 0.75) & (multiplier >= 0.5)] = "moderate_0.5_to_0.75"
    labels[multiplier < 0.5] = "severe_below_0.5"
    output: dict[str, Any] = {"diagnostic_only": True}
    for label in (
        "not_scaled",
        "mild_0.75_to_1",
        "moderate_0.5_to_0.75",
        "severe_below_0.5",
    ):
        mask = labels == label
        output[label] = {
            "hours": int(mask.sum()),
            "occupancy": float(mask.mean()),
            "D0_annualized_mean": (
                float(baseline_return[mask].mean() * ANNUAL_HOURS)
                if mask.any()
                else None
            ),
            "D1_annualized_mean": (
                float(candidate_return[mask].mean() * ANNUAL_HOURS)
                if mask.any()
                else None
            ),
            "D1_minus_D0": (
                float((candidate_return[mask] - baseline_return[mask]).mean() * ANNUAL_HOURS)
                if mask.any()
                else None
            ),
        }
    return output


def endpoint(returns: np.ndarray, name: str) -> float:
    if name == "sharpe":
        annualized_volatility = float(
            returns.std(ddof=0) * math.sqrt(ANNUAL_HOURS)
        )
        return (
            float(returns.mean() * ANNUAL_HOURS / annualized_volatility)
            if annualized_volatility > 0.0
            else 0.0
        )
    if name == "expected_shortfall":
        quantile = np.quantile(returns, 0.01)
        return float(returns[returns <= quantile].mean())
    raise KeyError(name)


def bootstrap(
    frame: pd.DataFrame,
    baseline: dict[str, np.ndarray],
    candidate: dict[str, np.ndarray],
) -> dict[str, Any]:
    folds = frame["fold"].to_numpy(dtype=int)
    random = np.random.default_rng(SEED)
    observed = {
        "sharpe": endpoint(candidate["strategy_return"], "sharpe")
        - endpoint(baseline["strategy_return"], "sharpe"),
        "expected_shortfall": endpoint(
            candidate["strategy_return"], "expected_shortfall"
        )
        - endpoint(baseline["strategy_return"], "expected_shortfall"),
    }
    samples = {name: np.empty(RESAMPLES, dtype=float) for name in observed}
    for sample_index in range(RESAMPLES):
        pieces = []
        for fold in sorted(np.unique(folds)):
            fold_indices = np.flatnonzero(folds == fold)
            length = len(fold_indices)
            block_count = math.ceil(length / BLOCK_HOURS)
            starts = random.integers(
                0,
                length - BLOCK_HOURS + 1,
                size=block_count,
            )
            local = np.concatenate(
                [np.arange(start, start + BLOCK_HOURS) for start in starts]
            )[:length]
            pieces.append(fold_indices[local])
        selected = np.concatenate(pieces)
        for name in observed:
            samples[name][sample_index] = endpoint(
                candidate["strategy_return"][selected],
                name,
            ) - endpoint(baseline["strategy_return"][selected], name)

    output = {}
    for name, observed_difference in observed.items():
        vector = samples[name]
        centered_error = vector - observed_difference
        one_sided_p = (
            float(
                (np.sum(centered_error >= observed_difference) + 1)
                / (RESAMPLES + 1)
            )
            if observed_difference > 0.0
            else 1.0
        )
        output[name] = {
            "observed_difference": float(observed_difference),
            "percentile_95_interval": [
                float(np.quantile(vector, 0.025)),
                float(np.quantile(vector, 0.975)),
            ],
            "basic_one_sided_95_lower_bound": float(
                observed_difference - np.quantile(centered_error, 0.95)
            ),
            "centered_one_sided_p_value": one_sided_p,
        }
    return output


def holm_adjust(tests: list[tuple[str, float]]) -> dict[str, float]:
    ordered = sorted(range(len(tests)), key=lambda index: tests[index][1])
    adjusted = [0.0] * len(tests)
    running = 0.0
    for rank, index in enumerate(ordered):
        value = min(1.0, (len(tests) - rank) * tests[index][1])
        running = max(running, value)
        adjusted[index] = running
    return {tests[index][0]: float(adjusted[index]) for index in range(len(tests))}


def capacity(turnover: np.ndarray) -> dict[str, Any]:
    annualized_turnover = float(turnover.mean() * ANNUAL_HOURS)
    output: dict[str, Any] = {"diagnostic_only": True, "rungs": {}}
    for notional in (10_000, 100_000, 1_000_000):
        output["rungs"][str(notional)] = {
            "annual_adjustment_notional_usd": annualized_turnover * notional,
            "annual_modeled_exchange_fee_usd": (
                annualized_turnover * notional * FEE_ONE_WAY
            ),
            "mean_hourly_adjustment_usd": float(turnover.mean() * notional),
            "p99_hourly_adjustment_usd": float(
                np.quantile(turnover, 0.99) * notional
            ),
            "maximum_hourly_adjustment_usd": float(turnover.max() * notional),
        }
    return output


def analyze_market(market: str, root: Path) -> dict[str, Any]:
    manifest = verify_manifest(root)
    frame = pd.read_csv(root / "walk_forward_returns.csv")
    summary = json.loads((root / "walk_forward.json").read_text(encoding="utf-8"))
    snapshot_path = next((root / "snapshot").glob("*.csv"))
    snapshot = pd.read_csv(snapshot_path)

    baseline = baseline_policy(frame)
    validation = validate_baseline(frame, baseline, summary)
    feature = build_feature(snapshot, frame)
    multiplier = np.asarray(feature["multiplier"], dtype=float)
    candidate = downside_sizing_policy(frame, multiplier)

    baseline_metrics = performance_metrics(
        baseline["strategy_return"],
        baseline["turnover"],
        baseline["position"],
    )
    candidate_metrics = performance_metrics(
        candidate["strategy_return"],
        candidate["turnover"],
        candidate["position"],
    )
    folds = {
        "D0": fold_report(frame, baseline),
        "D1": fold_report(frame, candidate),
    }
    simple_trend = frame["benchmark_simple_trend_long_cash_return"].to_numpy(
        dtype=float
    )
    acceptance = {
        "higher_sharpe": candidate_metrics["sharpe"] > baseline_metrics["sharpe"],
        "higher_calmar": candidate_metrics["calmar"] > baseline_metrics["calmar"],
        "max_drawdown_no_worse": (
            candidate_metrics["max_drawdown"] >= baseline_metrics["max_drawdown"]
        ),
        "expected_shortfall_improved": (
            candidate_metrics["expected_shortfall_1pct"]
            > baseline_metrics["expected_shortfall_1pct"]
        ),
        "positive_total_return": candidate_metrics["total_return"] > 0.0,
        "edge_per_turnover_no_lower": (
            candidate_metrics["net_edge_per_turnover"]
            >= baseline_metrics["net_edge_per_turnover"]
        ),
        "profitable_folds_not_reduced": (
            folds["D1"]["profitable_folds"] >= folds["D0"]["profitable_folds"]
        ),
        "turnover_within_125pct": (
            candidate_metrics["annualized_turnover"]
            <= 1.25 * baseline_metrics["annualized_turnover"]
        ),
    }
    return {
        "market": market,
        "input": {
            "artifact_manifest_sha256": sha256(root / "artifact-manifest.sha256"),
            "manifest_entries": len(manifest),
            "returns_csv_sha256": sha256(root / "walk_forward_returns.csv"),
            "summary_json_sha256": sha256(root / "walk_forward.json"),
            "snapshot_csv_sha256": sha256(snapshot_path),
            "oos_rows": len(frame),
            "period": [str(frame["timestamp"].iloc[0]), str(frame["timestamp"].iloc[-1])],
        },
        "validation": {
            **validation,
            "snapshot_return_error": float(feature["snapshot_return_error"]),
        },
        "feature": {
            "short_hours": SHORT_HOURS,
            "slow_hours": SLOW_HOURS,
            "mean_multiplier": float(multiplier.mean()),
            "median_multiplier": float(np.median(multiplier)),
            "minimum_multiplier": float(multiplier.min()),
            "scaled_hour_fraction": float((multiplier < 1.0 - 1e-15).mean()),
        },
        "D0": baseline_metrics,
        "D1": candidate_metrics,
        "folds": folds,
        "years": year_report(frame, baseline, candidate),
        "risk_regimes": risk_regime_report(
            multiplier,
            baseline["strategy_return"],
            candidate["strategy_return"],
        ),
        "benchmark_residual_sharpe": {
            "D0": endpoint(baseline["strategy_return"] - simple_trend, "sharpe"),
            "D1": endpoint(candidate["strategy_return"] - simple_trend, "sharpe"),
        },
        "bootstrap": bootstrap(frame, baseline, candidate),
        "capacity": {
            "D0": capacity(baseline["turnover"]),
            "D1": capacity(candidate["turnover"]),
        },
        "acceptance_deterministic": acceptance,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--btc-root", type=Path, required=True)
    parser.add_argument("--eth-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    markets = [
        analyze_market("BTC-USDT", args.btc_root),
        analyze_market("ETH-USDT", args.eth_root),
    ]
    tests = []
    for market in markets:
        tests.extend(
            [
                (
                    f"{market['market']}_sharpe",
                    market["bootstrap"]["sharpe"]["centered_one_sided_p_value"],
                ),
                (
                    f"{market['market']}_expected_shortfall",
                    market["bootstrap"]["expected_shortfall"]
                    ["centered_one_sided_p_value"],
                ),
            ]
        )
    adjusted = holm_adjust(tests)
    for market in markets:
        sharpe_p = adjusted[f"{market['market']}_sharpe"]
        expected_shortfall_p = adjusted[
            f"{market['market']}_expected_shortfall"
        ]
        market["acceptance_statistical"] = {
            "sharpe_holm_p": sharpe_p,
            "expected_shortfall_holm_p": expected_shortfall_p,
            "both_pass": sharpe_p < 0.05 and expected_shortfall_p < 0.05,
        }

    family_pass = all(
        all(market["acceptance_deterministic"].values())
        and market["acceptance_statistical"]["both_pass"]
        for market in markets
    )
    payload = {
        "family_id": "downside-semivolatility-sizing-v1",
        "issue": 546,
        "candidate_count": 1,
        "policy_contract": {
            "D0": "canonical target",
            "D1": "target * min(1, downside_semivol_720h / downside_semivol_24h)",
            "short_hours": SHORT_HOURS,
            "slow_hours": SLOW_HOURS,
            "fallback": "canonical target",
            "no_exposure_increase": True,
        },
        "economics": {
            "bar": "1H",
            "fee_one_way_bps": 5.0,
            "fee_applied_to": "absolute position adjustment",
        },
        "bootstrap_contract": {
            "block_hours": BLOCK_HOURS,
            "non_circular": True,
            "within_fold": True,
            "resamples": RESAMPLES,
            "seed": SEED,
            "confirmatory_endpoints": [
                "Sharpe improvement",
                "1% expected-shortfall improvement",
            ],
            "holm_hypotheses": 4,
        },
        "markets": markets,
        "holm_adjusted_p_values": adjusted,
        "family_pass": family_pass,
        "verdict": (
            "support_as_risk_sizing_overlay_only"
            if family_pass
            else "reject_exact_family_cooldown"
        ),
        "untouched_replication_consumed": False,
        "prospective_evidence_consumed": False,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(serialized, encoding="utf-8")
    print(json.dumps(payload, indent=2))
    print("PAYLOAD_SHA256", hashlib.sha256(serialized.encode()).hexdigest())


if __name__ == "__main__":
    main()
