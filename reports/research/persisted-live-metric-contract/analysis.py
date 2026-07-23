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
ADJUSTMENT_THRESHOLD = 1e-12
MARKETS = ("BTC-USDT", "ETH-USDT")
SOURCE = {
    "workflow_run_id": 30033465689,
    "artifact_id": 8574277655,
    "artifact_name": "quant-research-source-2350-attempt-1",
    "artifact_sha256": "c80382a4f310828d1bba27f8cbecd41379d379d7dd1f3244434fb57f4d574c72",
    "source_code_commit": "ce3eae5c0eeb663e87f523c9fe540b33638515eb",
    "current_main_commit": "82bd124f49b0d183ce723303b114bbe934b10cb6",
}
EXPECTED_HASHES = {
    "BTC-USDT": {
        "returns": "04a0a5257d1e20f1eb88c70b8a0b010d21f0dc35ccb657ba39f14189e9f20790",
        "report": "96d399156dcd0cb9eb81f0de69502f6bf9bcd114fc8e6c39efb5d561ad49e2a1",
    },
    "ETH-USDT": {
        "returns": "4b69db4a44644a5f830e1518aca93356c0eeacf502dc00ba990bd992b9bd387f",
        "report": "8418fb845b9f1c9119dcf39d8352ab1ff293af055ad8484700d13d4d7840c1ee",
    },
}
CANONICAL_SIGNATURE = (
    "canonical-5bps-path-derived-live-metrics-reconstructability-v1|"
    "markets=BTC-USDT,ETH-USDT|source=verified-persisted-walk-forward-csv-artifact-8574277655|"
    "fee=5bps-one-way|adjustment-threshold=1e-12|"
    "episode=contiguous-abs-position-above-threshold|"
    "completed-episode-return=entry-through-first-cash-bar-including-exit-fee|"
    "calendar=compounded-net-return-with-partial-first-last-labels|"
    "claim=all-issue306-path-derived-metrics-reconstructable-in-both-markets|candidate_count=1"
)
REQUIRED_COLUMNS = {
    "timestamp",
    "position",
    "turnover",
    "gross_strategy_return",
    "trading_cost",
    "strategy_return",
    "fold",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _compounded(values: pd.Series) -> float:
    return float((1.0 + values.astype(float)).prod() - 1.0)


def _drawdown(returns: pd.Series) -> dict[str, float | int]:
    nav = np.r_[1.0, np.cumprod(1.0 + returns.to_numpy(dtype=float))]
    drawdown = nav / np.maximum.accumulate(nav) - 1.0
    observed = drawdown[1:]
    longest = current = run = 0
    for is_underwater in observed < -1e-15:
        run = run + 1 if is_underwater else 0
        longest = max(longest, run)
    current = run
    return {
        "current_drawdown": float(observed[-1]),
        "maximum_drawdown": float(observed.min()),
        "current_underwater_duration_bars": current,
        "longest_underwater_duration_bars": longest,
    }


def _validated_frame(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, float_precision="round_trip")
    missing = REQUIRED_COLUMNS - set(frame)
    if missing:
        raise ValueError(f"missing required persisted columns: {sorted(missing)}")
    raw = frame["timestamp"].astype("string")
    explicit_zone = raw.str.contains(r"(?:Z|[+-]\d{2}:?\d{2})$", regex=True, na=False)
    if not bool(explicit_zone.all()):
        raise ValueError("timestamps must contain explicit timezone offsets")
    timestamps = pd.DatetimeIndex(pd.to_datetime(raw, utc=True, errors="raise"))
    if timestamps.duplicated().any() or not timestamps.is_monotonic_increasing:
        raise ValueError("timestamps must be unique and strictly increasing")
    if len(timestamps) > 1:
        intervals = timestamps[1:] - timestamps[:-1]
        if not bool((intervals == pd.Timedelta(days=1)).all()):
            raise ValueError("timestamps must have exact daily cadence")
    numeric_columns = list(REQUIRED_COLUMNS - {"timestamp"})
    numeric = frame[numeric_columns].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any() or not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise ValueError("path metric inputs must be finite numeric values")
    if (numeric["strategy_return"] <= -1.0).any():
        raise ValueError("strategy returns must remain solvent")
    frame = frame.copy()
    frame["timestamp"] = timestamps
    frame[numeric_columns] = numeric
    expected_turnover = frame["position"].diff().abs()
    expected_turnover.iloc[0] = abs(float(frame["position"].iloc[0]))
    if not np.allclose(frame["turnover"], expected_turnover, rtol=0.0, atol=1e-12):
        raise ValueError("persisted turnover does not match the position path")
    expected_net = frame["gross_strategy_return"] - frame["trading_cost"]
    if not np.allclose(frame["strategy_return"], expected_net, rtol=0.0, atol=1e-12):
        raise ValueError("persisted net return does not reconcile")
    return frame


def _performance(frame: pd.DataFrame) -> dict[str, float | int]:
    returns = frame["strategy_return"]
    gross = frame["gross_strategy_return"]
    observations = len(frame)
    years = observations / ANNUALIZATION
    net_growth = float((1.0 + returns).prod())
    gross_growth = float((1.0 + gross).prod())
    net_total = net_growth - 1.0
    gross_total = gross_growth - 1.0
    daily_mean = float(returns.mean())
    daily_std = float(returns.std(ddof=0))
    downside = float(np.sqrt(np.mean(np.square(returns.clip(upper=0.0)))))
    max_drawdown = float(_drawdown(returns)["maximum_drawdown"])
    net_cagr = net_growth ** (1.0 / years) - 1.0
    active_returns = returns[returns != 0.0]
    return {
        "observations": observations,
        "total_return": net_total,
        "net_total_return": net_total,
        "gross_total_return": gross_total,
        "cagr": net_cagr,
        "net_cagr": net_cagr,
        "gross_cagr": gross_growth ** (1.0 / years) - 1.0,
        "annualized_arithmetic_mean": daily_mean * ANNUALIZATION,
        "net_annualized_arithmetic_mean": daily_mean * ANNUALIZATION,
        "gross_annualized_arithmetic_mean": float(gross.mean()) * ANNUALIZATION,
        "annualized_volatility": daily_std * math.sqrt(ANNUALIZATION),
        "sharpe": daily_mean / daily_std * math.sqrt(ANNUALIZATION) if daily_std else 0.0,
        "sortino": daily_mean / downside * math.sqrt(ANNUALIZATION) if downside else 0.0,
        "max_drawdown": max_drawdown,
        "calmar": net_cagr / abs(max_drawdown) if max_drawdown < 0.0 else 0.0,
        "annualized_turnover": float(frame["turnover"].mean()) * ANNUALIZATION,
        "average_abs_exposure": float(frame["position"].abs().mean()),
        "cost_drag_sum": float(frame["trading_cost"].sum()),
        "exchange_fee_sum": float(frame["trading_cost"].sum()),
        "compounded_exchange_fee_drag": gross_total - net_total,
        "hit_rate": float((active_returns > 0.0).mean()) if len(active_returns) else 0.0,
    }


def _reconcile(report: dict[str, Any], frame: pd.DataFrame) -> dict[str, float | int]:
    observed = report.get("aggregate_metrics")
    if not isinstance(observed, dict):
        raise ValueError("walk-forward report lacks aggregate_metrics")
    expected = _performance(frame)
    missing = sorted(set(expected) - set(observed))
    if missing:
        raise ValueError(f"walk-forward aggregate metrics are missing: {missing}")
    for key, value in expected.items():
        reported = observed[key]
        matches = (
            int(reported) == value
            if isinstance(value, int)
            else math.isclose(float(reported), value, rel_tol=0.0, abs_tol=1e-9)
        )
        if not matches:
            raise ValueError(f"aggregate metric {key} does not reconcile")
    return expected


def _episode_metrics(frame: pd.DataFrame) -> dict[str, float | int | str | None | bool]:
    active = frame["position"].abs().to_numpy() > ADJUSTMENT_THRESHOLD
    starts = np.flatnonzero(active & ~np.r_[False, active[:-1]])
    ends = np.flatnonzero(active & ~np.r_[active[1:], False])
    durations: list[int] = []
    complete_returns: list[float] = []
    open_count = 0
    for start, end in zip(starts, ends, strict=True):
        completed = end < len(frame) - 1 and not active[end + 1]
        durations.append(int(end - start + 1))
        if completed:
            complete_returns.append(_compounded(frame["strategy_return"].iloc[start : end + 2]))
        else:
            open_count += 1
    positive = sum(value for value in complete_returns if value > 0.0)
    negative = sum(value for value in complete_returns if value < 0.0)
    if negative < 0.0:
        profit_factor: float | None = positive / abs(negative)
        profit_factor_status = "finite"
    elif positive > 0.0:
        profit_factor = None
        profit_factor_status = "undefined_no_losing_completed_episodes"
    else:
        profit_factor = 0.0
        profit_factor_status = "zero_no_positive_completed_episodes"
    return {
        "holding_episode_count": len(durations),
        "completed_holding_episode_count": len(complete_returns),
        "open_holding_episode_count": open_count,
        "average_holding_duration_bars": float(np.mean(durations)) if durations else 0.0,
        "median_holding_duration_bars": float(np.median(durations)) if durations else 0.0,
        "maximum_holding_duration_bars": max(durations, default=0),
        "holding_episode_win_rate": (
            sum(value > 0.0 for value in complete_returns) / len(complete_returns)
            if complete_returns
            else 0.0
        ),
        "completed_holding_episode_profit_factor": profit_factor,
        "profit_factor_status": profit_factor_status,
        "episode_return_includes_exit_fee": True,
    }


def _calendar(frame: pd.DataFrame, frequency: str) -> list[dict[str, Any]]:
    indexed = frame.set_index("timestamp")
    periods = indexed.index.tz_localize(None).to_period(frequency)
    records: list[dict[str, Any]] = []
    for period, group in indexed.groupby(periods):
        start, end = group.index[[0, -1]]
        if frequency == "M":
            expected_start = period.start_time.tz_localize("UTC")
            expected_end = period.end_time.normalize().tz_localize("UTC")
        else:
            expected_start = pd.Timestamp(period.year, 1, 1, tz="UTC")
            expected_end = pd.Timestamp(period.year, 12, 31, tz="UTC")
        records.append(
            {
                "period": str(period),
                "partial": bool(start != expected_start or end != expected_end),
                "net_return": _compounded(group["strategy_return"]),
            }
        )
    return records


def analyze_market(artifact_dir: Path, market: str) -> dict[str, Any]:
    directory = artifact_dir / market
    returns_path = directory / "walk_forward_returns.csv"
    report_path = directory / "walk_forward.json"
    hashes = {"returns": sha256(returns_path), "report": sha256(report_path)}
    if hashes != EXPECTED_HASHES[market]:
        raise ValueError(f"{market} persisted evidence hash mismatch: {hashes}")
    frame = _validated_frame(returns_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    settings = report["settings"]["base_config"]
    if float(settings["transaction_cost_bps"]) != 5.0:
        raise ValueError(f"{market} is not the canonical 5 bps baseline")
    aggregate = _reconcile(report, frame)
    months = _calendar(frame, "M")
    years = _calendar(frame, "Y")
    nonzero_returns = frame.loc[frame["strategy_return"] != 0.0, "strategy_return"]
    path_metrics = {
        "observations": len(frame),
        "evaluation_start": frame["timestamp"].iloc[0].isoformat(),
        "evaluation_end": frame["timestamp"].iloc[-1].isoformat(),
        "position_adjustment_threshold": ADJUSTMENT_THRESHOLD,
        "total_absolute_turnover": float(frame["turnover"].sum()),
        "position_adjustment_count": int((frame["turnover"] > ADJUSTMENT_THRESHOLD).sum()),
        "annualized_position_adjustment_count": float(
            (frame["turnover"] > ADJUSTMENT_THRESHOLD).sum() / len(frame) * ANNUALIZATION
        ),
        "bar_hit_rate_nonzero_net_return": float((nonzero_returns > 0.0).mean()),
        "average_absolute_exposure": float(frame["position"].abs().mean()),
        "current_absolute_exposure": abs(float(frame["position"].iloc[-1])),
        "maximum_absolute_exposure": float(frame["position"].abs().max()),
        **_episode_metrics(frame),
        "profitable_months": sum(record["net_return"] > 0.0 for record in months),
        "losing_months": sum(record["net_return"] < 0.0 for record in months),
        "flat_months": sum(record["net_return"] == 0.0 for record in months),
        "partial_month_labels": [record["period"] for record in months if record["partial"]],
        "profitable_years": sum(record["net_return"] > 0.0 for record in years),
        "losing_years": sum(record["net_return"] < 0.0 for record in years),
        "flat_years": sum(record["net_return"] == 0.0 for record in years),
        "partial_year_labels": [record["period"] for record in years if record["partial"]],
        **_drawdown(frame["strategy_return"]),
    }
    required = {
        "observations",
        "evaluation_start",
        "evaluation_end",
        "position_adjustment_threshold",
        "total_absolute_turnover",
        "position_adjustment_count",
        "annualized_position_adjustment_count",
        "holding_episode_count",
        "completed_holding_episode_count",
        "open_holding_episode_count",
        "average_holding_duration_bars",
        "median_holding_duration_bars",
        "maximum_holding_duration_bars",
        "bar_hit_rate_nonzero_net_return",
        "holding_episode_win_rate",
        "completed_holding_episode_profit_factor",
        "average_absolute_exposure",
        "current_absolute_exposure",
        "maximum_absolute_exposure",
        "profitable_months",
        "losing_months",
        "partial_month_labels",
        "profitable_years",
        "losing_years",
        "partial_year_labels",
        "current_drawdown",
        "maximum_drawdown",
        "current_underwater_duration_bars",
        "longest_underwater_duration_bars",
    }
    missing = sorted(required - set(path_metrics))
    risk_adjusted = report["benchmark_assessment"]["beats_all_benchmarks"]
    return {
        "hashes": hashes,
        "aggregate_metrics_reconciled": True,
        "headline_5bps_metrics": {
            key: aggregate[key]
            for key in (
                "net_total_return",
                "net_cagr",
                "sharpe",
                "sortino",
                "calmar",
                "max_drawdown",
                "annualized_turnover",
            )
        }
        | {
            "profitable_folds": int(report["fold_stability"]["profitable_folds"]),
            "fold_count": int(report["fold_stability"]["fold_count"]),
        },
        "path_metrics": path_metrics,
        "year_records": years,
        "missing_path_metrics": missing,
        "all_required_path_metrics_reconstructable": not missing,
        "fold_stability_passes": bool(report["fold_stability"]["passes"]),
        "complete_year_stability_passes": all(
            record["net_return"] > 0.0 for record in years if not record["partial"]
        ),
        "benchmark_relative_risk_adjusted_passes": bool(
            risk_adjusted["sharpe"] and risk_adjusted["calmar"]
        ),
        "fifteen_bps_selected_path_viable": bool(
            report["cost_stress_metrics"]["3x"]["total_return"] > 0.0
            and report["cost_stress_metrics"]["3x"]["sharpe"] > 0.0
        ),
    }


def build_result(artifact_dir: Path) -> dict[str, Any]:
    markets = {market: analyze_market(artifact_dir, market) for market in MARKETS}
    passes = all(value["all_required_path_metrics_reconstructable"] for value in markets.values())

    def joint(field: str) -> str:
        return "pass" if all(value[field] for value in markets.values()) else "fail"

    return {
        "canonical_signature": CANONICAL_SIGNATURE,
        "hypothesis": (
            "The canonical 5 bps persisted CSV contains sufficient evidence to independently "
            "reconstruct every path-derived live-readiness metric required by issue #306."
        ),
        "candidate_accounting": {"searched": 1, "passed": int(passes), "rejected": int(not passes)},
        "source": SOURCE,
        "definitions": {
            "adjustment_threshold": ADJUSTMENT_THRESHOLD,
            "holding_episode": "contiguous bars with absolute executed position above threshold",
            "completed_episode_return": (
                "compounded net return from first active bar through first subsequent cash bar, "
                "including entry and exit fee"
            ),
            "holding_duration": "active-position bars only",
            "bar_hit_rate": "positive share among nonzero net-return bars",
            "profit_factor": (
                "sum positive completed-episode returns divided by absolute sum negative "
                "completed-episode returns; null when there are no losing completed episodes"
            ),
            "calendar_return": "compounded net daily return with incomplete periods labelled partial",
            "underwater_duration": "consecutive daily OOS observations below the running peak",
        },
        "markets": markets,
        "hypothesis_passes": passes,
        "verdict": "supported" if passes else "rejected",
        "live_eligible": False,
        "live_gate_status": {
            "corrected_5bps_full_reselection": "pass",
            "path_derived_metric_reconstructability": "pass" if passes else "fail",
            "formal_persisted_metric_contract": "fail",
            "benchmark_relative_risk_adjusted": joint(
                "benchmark_relative_risk_adjusted_passes"
            ),
            "fold_stability": joint("fold_stability_passes"),
            "year_stability": joint("complete_year_stability_passes"),
            "turnover_and_5_7_5_10_15bps_viability": joint(
                "fifteen_bps_selected_path_viable"
            ),
            "parameter_neighbourhood_stability": "pass",
            "tail_risk": "pass",
            "execution_delay_robustness": "fail",
            "separate_spread_slippage_impact_latency": "blocked",
            "capacity": "blocked",
            "untouched_market_validation": "blocked",
            "prospective_forward_validation": "blocked",
        },
        "limitations": [
            "Production JSON and Markdown still do not persist the complete metric contract.",
            "Episodes are research constructs rather than exchange order or fill records.",
            "BTC-USDT and ETH-USDT remain development markets.",
            "Spread, slippage, impact, latency, capacity and prospective evidence are absent.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = build_result(args.artifact_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    args.output.write_text(payload, encoding="utf-8")


if __name__ == "__main__":
    main()
