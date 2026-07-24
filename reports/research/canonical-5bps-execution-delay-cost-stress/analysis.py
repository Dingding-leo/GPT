from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ANNUALIZATION = 365
BASELINE_FEE_BPS = 5.0
TOTAL_DELAYS = (1, 2, 3)
ALL_IN_COSTS_BPS = (5.0, 7.5, 10.0, 15.0)
LIVE_CRITICAL_DELAYS = (2, 3)
BLOCK_LENGTH = 20
RESAMPLES = 2_000
CONFIDENCE = 0.95
MAX_DRAWDOWN_FLOOR = -0.40
SOURCE = {
    "workflow_run_id": 30014704624,
    "artifact_id": 8566608828,
    "artifact_name": "quant-research-source-2037-attempt-1",
    "artifact_sha256": "ab0846180ff5b9397de26de8ca8d728ad237be00bdb92ba1612ef6ba243fc149",
    "source_head_sha": "0d9c098f6408f4510bbefb95633e3d695f30dde3",
}
MARKETS = {
    "BTC-USDT": {
        "seed": 2026072401,
        "return_sha256": "78707e21682013d290f10a66e45f78fae18f78e16de9d029c51ba9ff055dec3c",
    },
    "ETH-USDT": {
        "seed": 2026072402,
        "return_sha256": "a667b5c6d0081483059ece4e6cef4c87dcdb4e993976487f44fd41bbe772c069",
    },
}
SIGNATURE = (
    "canonical-5bps-execution-delay-cost-stress-v1|"
    "markets=BTC-USDT,ETH-USDT|source=PR308-artifact-8566608828|"
    "baseline=full-reselection-5bps-one-bar-delay|"
    "stress=total-delay-2,3-bars|all-in-costs-bps=5,7.5,10,15|"
    "position-path=frozen-persisted-selected-path-shifted-by-extra-delay|"
    "resampling=paired-noncircular-moving-block-bootstrap|block-length=20|"
    "resamples=2000|confidence=0.95|"
    "pass=all-stress-scenarios-positive-point-return-and-sharpe,"
    "max-drawdown-at-least-minus-40pct,and-positive-bootstrap-lower-bounds-"
    "for-annualized-mean-and-sharpe-in-both-markets|candidate_count=1"
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_file(path: Path, expected_sha256: str) -> None:
    observed = file_sha256(path)
    if observed != expected_sha256:
        raise ValueError(
            f"SHA-256 mismatch for {path}: expected {expected_sha256}, observed {observed}"
        )


def validate_frame(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"timestamp", "asset_return", "position", "fold"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"returns file is missing columns: {sorted(missing)}")

    raw_timestamp = frame["timestamp"].astype("string")
    explicit_zone = raw_timestamp.str.contains(r"(?:Z|[+-]\d{2}:?\d{2})$", regex=True, na=False)
    if not bool(explicit_zone.all()):
        raise ValueError("timestamps must include an explicit timezone offset")

    result = pd.DataFrame({"timestamp": pd.to_datetime(raw_timestamp, utc=True, errors="raise")})
    if result["timestamp"].duplicated().any() or not result["timestamp"].is_monotonic_increasing:
        raise ValueError("timestamps must be unique and strictly increasing")
    if len(result) > 1:
        cadence = result["timestamp"].diff().iloc[1:]
        if not cadence.eq(pd.Timedelta(days=1)).all():
            raise ValueError("timestamps must have exact daily cadence")

    for column in ("asset_return", "position", "fold"):
        result[column] = pd.to_numeric(frame[column], errors="raise")
    values = result[["asset_return", "position", "fold"]].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("return, position, and fold values must be finite")
    if np.any(result["asset_return"].to_numpy(dtype=float) <= -1.0):
        raise ValueError("asset returns must be greater than -1")
    positions = result["position"].to_numpy(dtype=float)
    if np.any(positions < -1e-12) or np.any(positions > 1.0 + 1e-12):
        raise ValueError("positions must remain within the declared long/cash bounds")
    folds = result["fold"].to_numpy(dtype=float)
    if np.any(folds < 1.0) or not np.equal(folds, np.floor(folds)).all():
        raise ValueError("fold identifiers must be positive integers")
    result["fold"] = result["fold"].astype(int)
    return result


def build_delayed_returns(
    frame: pd.DataFrame,
    *,
    total_delay_bars: int,
    all_in_cost_bps: float,
) -> pd.DataFrame:
    if total_delay_bars not in TOTAL_DELAYS:
        raise ValueError(f"total_delay_bars must be one of {TOTAL_DELAYS}")
    if all_in_cost_bps not in ALL_IN_COSTS_BPS:
        raise ValueError(f"all_in_cost_bps must be one of {ALL_IN_COSTS_BPS}")

    validated = validate_frame(frame)
    extra_delay = total_delay_bars - 1
    delayed_position = validated["position"].shift(extra_delay).fillna(0.0)
    turnover = delayed_position.diff().abs()
    turnover.iloc[0] = abs(delayed_position.iloc[0])
    gross_return = delayed_position * validated["asset_return"]
    cost = turnover * (all_in_cost_bps / 10_000.0)
    net_return = gross_return - cost

    result = validated.copy()
    result["delayed_position"] = delayed_position
    result["turnover"] = turnover
    result["gross_return"] = gross_return
    result["cost"] = cost
    result["net_return"] = net_return
    return result


def compounded_return(values: pd.Series | np.ndarray) -> float:
    array = np.asarray(values, dtype=float)
    if array.size == 0 or not np.isfinite(array).all() or np.any(array <= -1.0):
        raise ValueError("returns must be finite, non-empty, and greater than -1")
    return float(np.prod(1.0 + array) - 1.0)


def scenario_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    returns = frame["net_return"].to_numpy(dtype=float)
    observations = len(returns)
    total_return = compounded_return(returns)
    years = observations / ANNUALIZATION
    annualized_mean = float(returns.mean() * ANNUALIZATION)
    annualized_volatility = float(returns.std(ddof=0) * math.sqrt(ANNUALIZATION))
    sharpe = annualized_mean / annualized_volatility
    nav = np.concatenate(([1.0], np.cumprod(1.0 + returns)))
    drawdown = nav / np.maximum.accumulate(nav) - 1.0
    return {
        "observations": observations,
        "total_return": total_return,
        "cagr": float((1.0 + total_return) ** (1.0 / years) - 1.0),
        "annualized_arithmetic_mean": annualized_mean,
        "annualized_volatility": annualized_volatility,
        "sharpe": sharpe,
        "max_drawdown": float(drawdown.min()),
        "total_absolute_turnover": float(frame["turnover"].sum()),
        "annualized_turnover": float(frame["turnover"].sum() / years),
        "exchange_and_friction_cost_sum": float(frame["cost"].sum()),
    }


def moving_block_indices(
    observations: int,
    *,
    block_length: int,
    rng: np.random.Generator,
) -> np.ndarray:
    if observations < block_length:
        raise ValueError("observations must be at least block_length")
    starts = np.arange(observations - block_length + 1)
    indices: list[int] = []
    while len(indices) < observations:
        start = int(rng.choice(starts))
        indices.extend(range(start, start + block_length))
    return np.asarray(indices[:observations], dtype=int)


def bootstrap_intervals(
    scenario_returns: dict[str, np.ndarray],
    *,
    seed: int,
) -> dict[str, dict[str, list[float]]]:
    names = list(scenario_returns)
    matrix = np.column_stack([scenario_returns[name] for name in names])
    observations = len(matrix)
    rng = np.random.default_rng(seed)
    annualized_means = np.empty((RESAMPLES, len(names)))
    sharpes = np.empty_like(annualized_means)
    for resample in range(RESAMPLES):
        indices = moving_block_indices(
            observations,
            block_length=BLOCK_LENGTH,
            rng=rng,
        )
        sample = matrix[indices]
        annualized_means[resample] = sample.mean(axis=0) * ANNUALIZATION
        volatility = sample.std(axis=0, ddof=0) * math.sqrt(ANNUALIZATION)
        sharpes[resample] = annualized_means[resample] / volatility

    alpha = (1.0 - CONFIDENCE) / 2.0
    result: dict[str, dict[str, list[float]]] = {}
    for index, name in enumerate(names):
        result[name] = {
            "annualized_arithmetic_mean": [
                float(np.quantile(annualized_means[:, index], alpha)),
                float(np.quantile(annualized_means[:, index], 1.0 - alpha)),
            ],
            "sharpe": [
                float(np.quantile(sharpes[:, index], alpha)),
                float(np.quantile(sharpes[:, index], 1.0 - alpha)),
            ],
        }
    return result


def scenario_name(total_delay_bars: int, all_in_cost_bps: float) -> str:
    return f"delay_{total_delay_bars}_bars_cost_{all_in_cost_bps:g}_bps"


def compact_scenario(metrics: dict[str, Any], *, baseline: bool = False) -> dict[str, Any]:
    result = {
        "total_delay_bars": metrics["total_delay_bars"],
        "extra_delay_bars": metrics["extra_delay_bars"],
        "all_in_cost_bps": metrics["all_in_cost_bps"],
        "total_return": metrics["total_return"],
        "sharpe": metrics["sharpe"],
        "max_drawdown": metrics["max_drawdown"],
        "annualized_mean_95pct_lower": metrics["bootstrap_95pct"]["annualized_arithmetic_mean"][0],
        "sharpe_95pct_lower": metrics["bootstrap_95pct"]["sharpe"][0],
        "passes_delay_gate": metrics["passes_delay_gate"],
        "failed_checks": metrics["failed_checks"],
    }
    if baseline:
        result.update(
            {
                "cagr": metrics["cagr"],
                "annualized_arithmetic_mean": metrics["annualized_arithmetic_mean"],
                "annualized_turnover": metrics["annualized_turnover"],
            }
        )
    return result


def analyze_market(frame: pd.DataFrame, *, seed: int) -> dict[str, Any]:
    scenario_specs = [(1, BASELINE_FEE_BPS)] + [
        (delay, cost) for delay in LIVE_CRITICAL_DELAYS for cost in ALL_IN_COSTS_BPS
    ]
    scenario_frames = {
        scenario_name(delay, cost): build_delayed_returns(
            frame,
            total_delay_bars=delay,
            all_in_cost_bps=cost,
        )
        for delay, cost in scenario_specs
    }
    intervals = bootstrap_intervals(
        {
            name: scenario_frame["net_return"].to_numpy(dtype=float)
            for name, scenario_frame in scenario_frames.items()
        },
        seed=seed,
    )

    scenarios: dict[str, Any] = {}
    failed_scenarios: list[dict[str, Any]] = []
    for total_delay, cost_bps in scenario_specs:
        name = scenario_name(total_delay, cost_bps)
        metrics = scenario_metrics(scenario_frames[name])
        metrics["bootstrap_95pct"] = intervals[name]
        live_critical = total_delay in LIVE_CRITICAL_DELAYS
        checks = {
            "positive_point_total_return": metrics["total_return"] > 0.0,
            "positive_point_sharpe": metrics["sharpe"] > 0.0,
            "max_drawdown_floor": metrics["max_drawdown"] >= MAX_DRAWDOWN_FLOOR,
            "positive_mean_lower_bound": (intervals[name]["annualized_arithmetic_mean"][0] > 0.0),
            "positive_sharpe_lower_bound": intervals[name]["sharpe"][0] > 0.0,
        }
        scenario_passes = all(checks.values()) if live_critical else None
        metrics.update(
            {
                "total_delay_bars": total_delay,
                "extra_delay_bars": total_delay - 1,
                "all_in_cost_bps": cost_bps,
                "live_critical": live_critical,
                "passes_delay_gate": scenario_passes,
                "failed_checks": [key for key, passed in checks.items() if not passed],
            }
        )
        scenarios[name] = metrics
        if live_critical and not scenario_passes:
            failed_scenarios.append({"scenario": name, "failed_checks": metrics["failed_checks"]})

    return {
        "baseline_5bps": compact_scenario(
            scenarios[scenario_name(1, BASELINE_FEE_BPS)], baseline=True
        ),
        "stress_scenarios": {
            name: compact_scenario(metrics)
            for name, metrics in scenarios.items()
            if metrics["live_critical"]
        },
        "delay_gate_passes": not failed_scenarios,
        "failed_scenarios": failed_scenarios,
    }


def analyze_artifact(artifact_dir: Path) -> dict[str, Any]:
    markets: dict[str, Any] = {}
    for market, settings in MARKETS.items():
        returns_path = artifact_dir / market / "walk_forward_returns.csv"
        verify_file(returns_path, settings["return_sha256"])
        frame = pd.read_csv(returns_path)
        markets[market] = analyze_market(frame, seed=settings["seed"])

    delay_gate_passes = all(result["delay_gate_passes"] for result in markets.values())
    blockers = {
        "benchmark_relative_risk_adjusted_evidence": "fail",
        "fold_stability": "fail",
        "year_stability": "fail",
        "execution_delay_and_all_in_cost_stress": "pass" if delay_gate_passes else "fail",
        "separate_spread_slippage_impact_latency": "blocked",
        "capacity": "blocked",
        "untouched_market_validation": "blocked",
        "prospective_forward_validation": "blocked",
    }
    live_eligible = all(status == "pass" for status in blockers.values())
    return {
        "hypothesis": (
            "The frozen canonical 5 bps selected path remains reliably profitable and "
            "risk-controlled in BTC-USDT and ETH-USDT under total execution delays of "
            "two and three daily bars and fixed all-in costs of 5, 7.5, 10, and 15 bps."
        ),
        "canonical_signature": SIGNATURE,
        "source": SOURCE,
        "method": {
            "baseline_fee_bps_one_way": BASELINE_FEE_BPS,
            "total_delay_bars": list(TOTAL_DELAYS),
            "live_critical_total_delay_bars": list(LIVE_CRITICAL_DELAYS),
            "all_in_costs_bps": list(ALL_IN_COSTS_BPS),
            "delay_method": (
                "shift the persisted one-bar-delayed selected-path position by total_delay-1 "
                "additional daily rows; recompute turnover and costs from cash"
            ),
            "selection_recomputed": False,
            "candidate_architecture_frozen": True,
            "block_length": BLOCK_LENGTH,
            "resamples": RESAMPLES,
            "confidence": CONFIDENCE,
            "max_drawdown_floor": MAX_DRAWDOWN_FLOOR,
            "pass_rule": (
                "every live-critical market/delay/cost scenario must have positive point "
                "total return and Sharpe, max drawdown >= -40%, and positive 95% moving-"
                "block-bootstrap lower bounds for annualized arithmetic mean and Sharpe"
            ),
            "component_cost_attribution": (
                "blocked: all-in cost totals do not separately identify spread, slippage, "
                "market impact, or latency"
            ),
        },
        "candidate_accounting": {
            "strategy_candidates_searched": 1,
            "stress_scenarios_per_market": len(LIVE_CRITICAL_DELAYS) * len(ALL_IN_COSTS_BPS),
            "live_critical_scenarios_per_market": len(LIVE_CRITICAL_DELAYS) * len(ALL_IN_COSTS_BPS),
            "passed": 1 if delay_gate_passes else 0,
            "rejected": 0 if delay_gate_passes else 1,
        },
        "markets": markets,
        "execution_delay_gate_passes": delay_gate_passes,
        "verdict": "supported" if delay_gate_passes else "rejected",
        "live_gate_status": {
            "live_eligible": live_eligible,
            "gates": blockers,
        },
        "limitations": [
            "BTC-USDT and ETH-USDT are development markets, not untouched holdouts.",
            (
                "The delayed paths shift observed daily positions; they are not executable "
                "next-open fills."
            ),
            (
                "The 7.5/10/15 bps scenarios are all-in totals and do not identify "
                "separate friction components."
            ),
            (
                "Moving-block concatenation creates artificial joins and preserves "
                "dependence only within blocks."
            ),
            (
                "Capacity, partial fills, rejected orders, and prospective paper evidence "
                "remain untested."
            ),
        ],
    }


def rounded_payload(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 12)
    if isinstance(value, dict):
        return {key: rounded_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [rounded_payload(item) for item in value]
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = analyze_artifact(args.artifact_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(rounded_payload(result), indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
