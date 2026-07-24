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
POSITION_THRESHOLD = 1e-12
SOURCE = {
    "workflow_run_id": 30014704624,
    "artifact_id": 8566608828,
    "artifact_name": "quant-research-source-2037-attempt-1",
    "artifact_sha256": "ab0846180ff5b9397de26de8ca8d728ad237be00bdb92ba1612ef6ba243fc149",
    "source_head_sha": "0d9c098f6408f4510bbefb95633e3d695f30dde3",
}
EXPECTED_HASHES = {
    "BTC-USDT": {
        "returns": "78707e21682013d290f10a66e45f78fae18f78e16de9d029c51ba9ff055dec3c",
        "report": "2816ae0c117104eeef748caa21e021e1fec31214ab8bd0ed8797ce62374e4745",
        "config": "8c2ef4414e580d17897223ee25c58fb8113d85328417cd74384ca5a55af6fd0b",
    },
    "ETH-USDT": {
        "returns": "a667b5c6d0081483059ece4e6cef4c87dcdb4e993976487f44fd41bbe772c069",
        "report": "f0d071135fdfe476463f1eb9c16221802ebd6d0234932940b04bccf3bac2992a",
        "config": "abca1b3f0ecb65c199c34f35b1bec70fc2299fc1a03dc90f066ac0bf16bdb413",
    },
}
SIGNATURE = (
    "canonical-5bps-live-gate-inventory-v1|markets=BTC-USDT,ETH-USDT|"
    "source=PR308-artifact-8566608828|baseline=full-reselection-5bps|"
    "costs=5,7.5,10,15bps-fixed-selected-path|candidate_count=1|"
    "claim=all-mandatory-paper-live-gates-pass-in-both-markets"
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def total_return(values: pd.Series) -> float:
    array = values.to_numpy(dtype=float)
    if array.size == 0 or not np.isfinite(array).all() or np.any(array <= -1.0):
        raise ValueError("returns must be finite, non-empty, and greater than -1")
    return float(np.prod(1.0 + array) - 1.0)


def drawdown_stats(values: pd.Series) -> tuple[float, float, int, int]:
    nav = np.concatenate(([1.0], np.cumprod(1.0 + values.to_numpy(dtype=float))))
    drawdowns = nav / np.maximum.accumulate(nav) - 1.0
    longest = run = 0
    for underwater in drawdowns < -1e-15:
        run = run + 1 if underwater else 0
        longest = max(longest, run)
    return float(drawdowns[-1]), float(drawdowns.min()), run, longest


def holding_episode_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    active = frame["position"].abs() > POSITION_THRESHOLD
    episodes: list[dict[str, Any]] = []
    start: int | None = None
    for index, is_active in enumerate(active):
        if is_active and start is None:
            start = index
        if start is not None and (not is_active or index == len(frame) - 1):
            end = index - 1 if not is_active else index
            segment = frame.iloc[start : end + 1]
            episodes.append(
                {
                    "bars": len(segment),
                    "return": total_return(segment["strategy_return"]),
                    "open": bool(index == len(frame) - 1 and is_active),
                }
            )
            start = None
    completed = [episode for episode in episodes if not episode["open"]]
    gains = sum(max(episode["return"], 0.0) for episode in completed)
    losses = sum(min(episode["return"], 0.0) for episode in completed)
    durations = [episode["bars"] for episode in episodes]
    return {
        "count": len(episodes),
        "completed": len(completed),
        "open": len(episodes) - len(completed),
        "average_bars": float(np.mean(durations)) if durations else None,
        "median_bars": float(np.median(durations)) if durations else None,
        "maximum_bars": max(durations, default=None),
        "completed_win_rate": (
            float(np.mean([episode["return"] > 0.0 for episode in completed]))
            if completed
            else None
        ),
        "completed_profit_factor": None if not completed or losses == 0.0 else gains / abs(losses),
    }


def calendar_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    indexed = frame.set_index("timestamp")["strategy_return"]
    month_keys = [indexed.index.year, indexed.index.month]
    months = [total_return(group) for _, group in indexed.groupby(month_keys, sort=True)]
    years = []
    for year, group in indexed.groupby(indexed.index.year, sort=True):
        if group.empty:
            continue
        start, end = group.index[0], group.index[-1]
        years.append(
            {
                "year": int(year),
                "return": total_return(group),
                "partial": not (
                    start.month == 1 and start.day == 1 and end.month == 12 and end.day == 31
                ),
            }
        )
    completed = [record for record in years if not record["partial"]]
    return {
        "month_count": len(months),
        "profitable_months": sum(value > 0.0 for value in months),
        "losing_or_flat_months": sum(value <= 0.0 for value in months),
        "years": years,
        "completed_year_count": len(completed),
        "profitable_completed_years": sum(record["return"] > 0.0 for record in completed),
        "losing_or_flat_completed_years": sum(record["return"] <= 0.0 for record in completed),
    }


def validate_frame(frame: pd.DataFrame) -> pd.DataFrame:
    required = {
        "timestamp",
        "asset_return",
        "position",
        "turnover",
        "trading_cost",
        "strategy_return",
        "fold",
        "benchmark_volatility_targeted_long_return",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
    result = frame.copy()
    result["timestamp"] = pd.to_datetime(result["timestamp"], utc=True, errors="raise")
    if result["timestamp"].duplicated().any() or not result["timestamp"].is_monotonic_increasing:
        raise ValueError("timestamps must be unique and increasing")
    for column in required - {"timestamp"}:
        result[column] = pd.to_numeric(result[column], errors="raise")
    if not np.isfinite(result[list(required - {"timestamp"})].to_numpy(dtype=float)).all():
        raise ValueError("numeric inputs must be finite")
    return result


def market_inventory(
    frame: pd.DataFrame, report: dict[str, Any], config: dict[str, Any]
) -> dict[str, Any]:
    frame = validate_frame(frame)
    net = frame["strategy_return"]
    gross = frame["position"] * frame["asset_return"]
    benchmark_returns = frame["benchmark_volatility_targeted_long_return"]
    observations = len(frame)
    net_total = total_return(net)
    gross_total = total_return(gross)
    volatility = float(net.std(ddof=0) * math.sqrt(ANNUALIZATION))
    sharpe = float(net.mean() * ANNUALIZATION / volatility)
    current_dd, max_dd, current_underwater, longest_underwater = drawdown_stats(net)
    tail_count = math.ceil(0.05 * observations)
    expected_shortfall = float(np.sort(net.to_numpy(dtype=float))[:tail_count].mean())
    benchmark_es = float(np.sort(benchmark_returns.to_numpy(dtype=float))[:tail_count].mean())
    folds = [
        {"fold": int(fold), "return": total_return(group["strategy_return"])}
        for fold, group in frame.groupby("fold", sort=True)
    ]
    calendar = calendar_metrics(frame)
    completed_years = [record for record in calendar["years"] if not record["partial"]]
    cost_scenarios = {
        f"{float(multiplier.rstrip('x')) * 5.0:g}": metrics
        for multiplier, metrics in report["cost_stress_metrics"].items()
    }
    benchmark = report["benchmark_metrics"]["volatility_targeted_long"]
    annualized_turnover = float(frame["turnover"].sum() * ANNUALIZATION / observations)
    result = {
        "evaluation": {
            "start": frame["timestamp"].iloc[0].isoformat(),
            "end": frame["timestamp"].iloc[-1].isoformat(),
            "observations": observations,
            "fold_count": len(folds),
            "candidate_count": report["settings"]["candidate_count"],
        },
        "settings": config,
        "returns": {
            "gross_total_return": gross_total,
            "net_total_return": net_total,
            "net_cagr": float((1.0 + net_total) ** (ANNUALIZATION / observations) - 1.0),
            "annualized_arithmetic_mean": float(net.mean() * ANNUALIZATION),
            "annualized_volatility": volatility,
            "sharpe": sharpe,
            "sortino": report["aggregate_metrics"]["sortino"],
            "calmar": report["aggregate_metrics"]["calmar"],
            "exchange_fee_sum": float(frame["trading_cost"].sum()),
            "compounded_fee_return_drag": gross_total - net_total,
        },
        "turnover": {
            "total_absolute_turnover": float(frame["turnover"].sum()),
            "annualized_turnover": annualized_turnover,
            "adjustment_threshold": POSITION_THRESHOLD,
            "adjustment_count": int((frame["turnover"] > POSITION_THRESHOLD).sum()),
        },
        "episodes": holding_episode_metrics(frame),
        "exposure": {
            "average": float(frame["position"].abs().mean()),
            "current": float(abs(frame["position"].iloc[-1])),
            "maximum": float(frame["position"].abs().max()),
        },
        "calendar": calendar,
        "folds": {
            "profitable": sum(record["return"] > 0.0 for record in folds),
            "ratio": sum(record["return"] > 0.0 for record in folds) / len(folds),
            "best": max(folds, key=lambda record: record["return"]),
            "worst": min(folds, key=lambda record: record["return"]),
            "positive_concentration": report["fold_stability"]["max_positive_fold_share"],
            "repository_gate_passes": report["fold_stability"]["passes"],
        },
        "drawdown_tail": {
            "current_drawdown": current_dd,
            "maximum_drawdown": max_dd,
            "current_underwater_bars": current_underwater,
            "longest_underwater_bars": longest_underwater,
            "expected_shortfall_5pct": expected_shortfall,
            "benchmark_expected_shortfall_5pct": benchmark_es,
            "worst_daily_return": float(net.min()),
        },
        "cost_scenarios_bps": cost_scenarios,
        "benchmark": benchmark,
        "robustness_status": report["robustness_status"],
    }
    profitable_year_ratio = (
        calendar["profitable_completed_years"] / len(completed_years) if completed_years else 0.0
    )
    year_stability = (
        len(completed_years) >= 4
        and profitable_year_ratio >= 0.60
        and min(record["return"] for record in completed_years) > -0.20
    )
    neighbourhood_passes = all(
        metrics["total_return"] > 0.0
        and metrics["sharpe"] > 0.0
        and metrics["max_drawdown"] > -0.40
        for metrics in report["perturbation_metrics"].values()
    )
    result["gates"] = {
        "corrected_5bps_full_reselection": "pass"
        if config["strategy"]["transaction_cost_bps"] == 5.0
        and report["settings"]["candidate_count"] == 27
        else "fail",
        "benchmark_relative_risk_adjusted": "pass"
        if sharpe > benchmark["sharpe"] and result["returns"]["calmar"] > benchmark["calmar"]
        else "fail",
        "fold_stability": "pass" if result["folds"]["repository_gate_passes"] else "fail",
        "year_stability": "pass" if year_stability else "fail",
        "turnover_and_cost_viability": "pass"
        if annualized_turnover <= 20.0
        and cost_scenarios["15"]["total_return"] > 0.0
        and cost_scenarios["15"]["sharpe"] > 0.0
        else "fail",
        "parameter_neighborhood_stability": "pass" if neighbourhood_passes else "fail",
        "tail_risk": "pass"
        if max_dd > benchmark["max_drawdown"]
        and expected_shortfall > benchmark_es
        and max_dd >= -0.35
        else "fail",
        "separate_spread_slippage_impact_latency": "blocked",
        "capacity": "blocked",
        "execution_delay_robustness": "blocked",
        "untouched_market_validation": "blocked",
        "prospective_forward_validation": "blocked",
    }
    return result


def analyze_artifact(artifact_dir: Path) -> dict[str, Any]:
    markets = {}
    for market, expected in EXPECTED_HASHES.items():
        directory = artifact_dir / market
        paths = {
            "returns": directory / "walk_forward_returns.csv",
            "report": directory / "walk_forward.json",
            "config": directory / "effective_config.json",
        }
        observed = {name: file_sha256(path) for name, path in paths.items()}
        if observed != expected:
            raise ValueError(f"{market} artifact hash mismatch")
        report = json.loads(paths["report"].read_text(encoding="utf-8"))
        config = json.loads(paths["config"].read_text(encoding="utf-8"))
        markets[market] = market_inventory(pd.read_csv(paths["returns"]), report, config)
        markets[market]["source_hashes"] = observed
    gate_names = list(next(iter(markets.values()))["gates"])
    joint = {}
    for name in gate_names:
        statuses = [market["gates"][name] for market in markets.values()]
        joint[name] = (
            "blocked"
            if "blocked" in statuses
            else "pass"
            if all(status == "pass" for status in statuses)
            else "fail"
        )
    eligible = all(status == "pass" for status in joint.values())
    return {
        "canonical_signature": SIGNATURE,
        "hypothesis": ("The corrected 5 bps candidate passes every mandatory paper/live gate."),
        "source": SOURCE,
        "candidate_accounting": {
            "searched": 1,
            "passed": int(eligible),
            "rejected": int(not eligible),
        },
        "markets": markets,
        "joint_gates": joint,
        "live_eligible": eligible,
        "verdict": "supported" if eligible else "rejected",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(analyze_artifact(args.artifact_dir), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
