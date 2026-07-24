from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ANNUALIZATION = 8_760
EXPECTED = {
    "artifact": "5770a6f850d81614734d45fe988ba83bc25263a31137877e371e0ee4a75ec46d",
    "returns": "aab10f37c716e1b32b93dcfc95adeceed4e4641495d3e517406346898e26b19d",
    "report": "e9a40524e00f825d9bea71ef3c8e7cce976f84b1158bbbb95fddb521923dfb87",
    "snapshot": "401616ba2a3037bba6adabcc3e44d23617e3d9d034e7d55554e286665964af38",
    "config": "4c57e2bb99f49f4e75005ca2c0d1f6fe605ec127c5c5b9498e6a95284caa192c",
    "verification": "72c245afa8bc7d51b3beed104c962c16291a8199fd8f3e990b378c91e9820516",
}
SOURCE_WORKFLOW_RUN_ID = 30_063_491_425
SOURCE_ARTIFACT_ID = 8_585_425_240
SOURCE_HEAD_SHA = "1d1da8d6f0cfb1cbd99e5533c693da139572bdc3"
CANONICAL_SIGNATURE = (
    "canonical-eth-1h-replication-v1|market=ETH-USDT|provider=OKX-spot|bar=1H|"
    "architecture=daily-horizons-scaled-24x|selection=17520|test=2160|"
    "internal-candidates=27|fee=5bps-one-way|execution=one-bar-delayed-close-return|"
    "claim=all-source-profile-oos-benchmark-fold-month-year-activity-neighbourhood-"
    "tail-capacity-maker-prospective-gates-pass|candidate_count=1"
)


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _compound(values: pd.Series) -> float:
    return float(np.prod(1.0 + values.to_numpy(dtype=float)) - 1.0)


def _expected_shortfall(values: pd.Series, fraction: float = 0.05) -> float:
    ordered = np.sort(values.to_numpy(dtype=float))
    return float(ordered[: math.ceil(len(ordered) * fraction)].mean())


def _artifact_root(path: str | Path) -> Path:
    root = Path(path)
    nested = root / "ETH-USDT"
    return nested if (nested / "walk_forward.json").exists() else root


def load_returns(path: str | Path) -> pd.DataFrame:
    source = Path(path)
    observed = file_sha256(source)
    if observed != EXPECTED["returns"]:
        raise ValueError(f"return SHA-256 mismatch: expected {EXPECTED['returns']}, got {observed}")
    frame = pd.read_csv(source)
    required = {
        "timestamp",
        "position",
        "turnover",
        "gross_strategy_return",
        "trading_cost",
        "strategy_return",
        "fold",
        "benchmark_buy_and_hold_return",
        "benchmark_volatility_targeted_long_return",
        "benchmark_simple_trend_long_cash_return",
    }
    missing = required - set(frame)
    if missing:
        raise ValueError(f"returns file is missing required columns: {sorted(missing)}")
    text = frame["timestamp"].astype("string")
    if not bool(text.str.contains(r"(?:Z|[+-]\d{2}:?\d{2})$", regex=True, na=False).all()):
        raise ValueError("timestamps must include an explicit timezone")
    timestamps = pd.DatetimeIndex(pd.to_datetime(text, utc=True, errors="raise"))
    if timestamps.duplicated().any() or not timestamps.is_monotonic_increasing:
        raise ValueError("timestamps must be unique and strictly increasing")
    if len(timestamps) > 1 and not bool(
        ((timestamps[1:] - timestamps[:-1]) == pd.Timedelta(hours=1)).all()
    ):
        raise ValueError("timestamps must have exact one-hour cadence")
    numeric_columns = sorted(required - {"timestamp"})
    numeric = frame[numeric_columns].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any() or not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise ValueError("required numeric columns must be finite")
    if (numeric["strategy_return"] <= -1.0).any():
        raise ValueError("strategy returns must be greater than -1")
    if (numeric["position"] < 0.0).any() or (numeric["position"] > 1.0).any():
        raise ValueError("spot positions must remain in [0, 1]")
    validated = frame.copy()
    validated["timestamp"] = timestamps
    validated[numeric_columns] = numeric
    return validated


def _calendar_summary(frame: pd.DataFrame, period: str) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    if period == "month":
        keys = frame["timestamp"].dt.strftime("%Y-%m")
    elif period == "year":
        keys = frame["timestamp"].dt.year
    else:
        raise ValueError("period must be month or year")
    for key, group in frame.groupby(keys, sort=True):
        if period == "month":
            start = pd.Timestamp(f"{key}-01T00:00:00Z")
            end = start + pd.offsets.MonthEnd(1) + pd.Timedelta(hours=23)
        else:
            start = pd.Timestamp(f"{key}-01-01T00:00:00Z")
            end = pd.Timestamp(f"{key}-12-31T23:00:00Z")
        expected = int((end - start) / pd.Timedelta(hours=1)) + 1
        complete = (
            group["timestamp"].iloc[0] == start
            and group["timestamp"].iloc[-1] == end
            and len(group) == expected
        )
        records.append({"complete": complete, "return": _compound(group["strategy_return"])})
    complete = [record for record in records if record["complete"]]
    positive = [record for record in complete if record["return"] > 0.0]
    ratio = len(positive) / len(complete) if complete else 0.0
    positive_sum = sum(record["return"] for record in positive)
    share = max((record["return"] for record in positive), default=0.0) / positive_sum \
        if positive_sum > 0.0 else None
    passes = (
        len(complete) >= (24 if period == "month" else 3)
        and ratio >= 0.5
        and (period == "month" or len(positive) == len(complete))
        and (period == "year" or (share is not None and share <= 0.5))
    )
    return {
        f"complete_{period}s": len(complete),
        f"profitable_complete_{period}s": len(positive),
        f"profitable_complete_{period}_ratio": ratio,
        "max_positive_share": share,
        "passes": passes,
    }


def _activity(frame: pd.DataFrame) -> dict[str, Any]:
    exposed = frame["position"] > 1e-12
    starts = np.flatnonzero((exposed & ~exposed.shift(fill_value=False)).to_numpy())
    ends = np.flatnonzero((exposed & ~exposed.shift(-1, fill_value=False)).to_numpy())
    durations: list[int] = []
    cursor = 0
    for start in starts:
        while cursor < len(ends) and ends[cursor] < start:
            cursor += 1
        end = int(ends[cursor]) if cursor < len(ends) else len(frame) - 1
        durations.append(end - int(start) + 1)
    years = len(frame) / ANNUALIZATION
    episodes = len(durations)
    median = float(np.median(durations)) if durations else None
    return {
        "adjustment_count": int((frame["turnover"] > 1e-12).sum()),
        "annualized_adjustment_count": float((frame["turnover"] > 1e-12).sum() / years),
        "exposure_episode_count": episodes,
        "annualized_exposure_episode_count": episodes / years,
        "median_holding_hours": median,
        "mean_holding_hours": float(np.mean(durations)) if durations else None,
        "maximum_holding_hours": int(max(durations)) if durations else None,
        "annualized_effective_round_trips": float(frame["turnover"].sum() / (2.0 * years)),
        "passes": bool(
            episodes >= 100
            and episodes / years >= 24
            and median is not None
            and median <= 72
        ),
    }


def build_result(artifact_dir: str | Path) -> dict[str, Any]:
    root = _artifact_root(artifact_dir)
    paths = {
        "returns": root / "walk_forward_returns.csv",
        "report": root / "walk_forward.json",
        "snapshot": root / "snapshot" / "okx-ETH-USDT-1H.csv",
        "config": root / "effective_config.json",
        "verification": root / "walk_forward_verification.json",
    }
    for name, path in paths.items():
        observed = file_sha256(path)
        if observed != EXPECTED[name]:
            raise ValueError(f"{name} SHA-256 mismatch: expected {EXPECTED[name]}, got {observed}")
    frame = load_returns(paths["returns"])
    report = json.loads(paths["report"].read_text(encoding="utf-8"))
    config = json.loads(paths["config"].read_text(encoding="utf-8"))
    verification = json.loads(paths["verification"].read_text(encoding="utf-8"))
    metrics = report["aggregate_metrics"]
    benchmarks = report["benchmark_metrics"]
    folds = report["fold_stability"]
    monthly = _calendar_summary(frame, "month")
    yearly = _calendar_summary(frame, "year")
    activity = _activity(frame)
    accounting_error = float(
        (frame["strategy_return"] - frame["gross_strategy_return"] + frame["trading_cost"])
        .abs()
        .max()
    )
    if accounting_error > 1e-15:
        raise ValueError("gross-minus-fee accounting does not reproduce net returns")
    benchmark_pass = all(
        float(metrics[key]) > float(benchmarks[name][key])
        for name in ("volatility_targeted_long", "simple_trend_long_cash")
        for key in ("sharpe", "calmar")
    )
    neighbourhood_pass = all(
        float(values["net_total_return"]) > 0 and float(values["sharpe"]) > 0
        for values in report["perturbation_metrics"].values()
    )
    strategy_es = _expected_shortfall(frame["strategy_return"])
    benchmark_es = _expected_shortfall(frame["benchmark_volatility_targeted_long_return"])
    executed_profile = list(config["robustness"]["cost_multipliers"])
    report_profile = list(report["settings"]["cost_multipliers"])
    exact_profile = executed_profile == [1.0] and report_profile == [1.0]
    source_pass = (
        verification["status"] == "passed"
        and verification["transaction_cost_bps"] == 5.0
        and verification["selection_candidate_evaluations_verified"] == 324
    )
    gates = {
        "source_data_and_reselection_reproducible": "pass" if source_pass else "fail",
        "exact_5bps_profile_fidelity": "pass" if exact_profile else "fail",
        "positive_5bps_oos_path": (
            "pass"
            if metrics["net_total_return"] > 0 and metrics["sharpe"] > 0
            else "fail"
        ),
        "benchmark_relative_risk_adjusted": "pass" if benchmark_pass else "fail",
        "fold_stability": "pass" if folds["passes"] else "fail",
        "month_stability": "pass" if monthly["passes"] else "fail",
        "year_stability": "pass" if yearly["passes"] else "fail",
        "turnover_holding_and_trade_sufficiency": "pass" if activity["passes"] else "fail",
        "parameter_neighbourhood_stability": "pass" if neighbourhood_pass else "fail",
        "tail_risk": "pass" if strategy_es > benchmark_es else "fail",
        "capacity": "blocked",
        "maker_execution_diagnostics": "blocked",
        "prospective_paper_evidence": "blocked",
    }
    replication_names = tuple(name for name in gates if gates[name] not in {"blocked"})
    gates["cross_market_replication"] = (
        "pass" if all(gates[name] == "pass" for name in replication_names) else "fail"
    )
    live_eligible = all(status == "pass" for status in gates.values())
    return {
        "hypothesis": "The frozen canonical ETH-USDT 1h replication clears all paper/live gates.",
        "canonical_signature": CANONICAL_SIGNATURE,
        "candidate_accounting": {
            "architecture_candidates_searched": 1,
            "architecture_candidates_passed": int(live_eligible),
            "architecture_candidates_rejected": int(not live_eligible),
            "fold_local_internal_candidates": report["settings"]["candidate_count"],
            "oos_folds": folds["fold_count"],
            "candidate_evaluations": verification["selection_candidate_evaluations_verified"],
        },
        "source": {
            "provider": "OKX",
            "instrument": "ETH-USDT",
            "bar": "1H",
            "workflow_run_id": SOURCE_WORKFLOW_RUN_ID,
            "artifact_id": SOURCE_ARTIFACT_ID,
            "artifact_sha256": EXPECTED["artifact"],
            "source_head_sha": SOURCE_HEAD_SHA,
            **{f"{name}_sha256": digest for name, digest in EXPECTED.items() if name != "artifact"},
        },
        "design": {
            "fee_bps_one_way": 5.0,
            "canonical_cost_scenarios_in_pnl": [5.0],
            "undeclared_artifact_diagnostics_excluded_from_claims": [10.0],
            "selection_bars": report["settings"]["selection_bars"],
            "test_bars": report["settings"]["test_bars"],
            "annualization": ANNUALIZATION,
            "oos_observations": metrics["observations"],
            "evaluation_start": report["data_summary"]["evaluation_start"],
            "evaluation_end": report["data_summary"]["evaluation_end"],
            "separate_execution_diagnostics": [
                "maker_fill_quality", "no_fill", "partial_fill", "timeout",
                "adverse_selection", "latency",
            ],
        },
        "metrics_5bps": {
            key: float(metrics[key])
            for key in (
                "gross_total_return", "net_total_return", "net_cagr",
                "net_annualized_arithmetic_mean", "sharpe", "sortino", "calmar",
                "max_drawdown", "annualized_turnover", "average_abs_exposure",
                "exchange_fee_sum",
            )
        },
        "benchmark_metrics": {
            name: {
                key: float(values[key])
                for key in ("net_total_return", "sharpe", "calmar", "max_drawdown")
            }
            for name, values in benchmarks.items()
        },
        "fold_stability": folds,
        "month_stability": monthly,
        "year_stability": yearly,
        "activity": activity,
        "tail_risk": {
            "strategy_expected_shortfall": strategy_es,
            "volatility_targeted_long_expected_shortfall": benchmark_es,
            "passes": strategy_es > benchmark_es,
        },
        "cost_profile": {
            "declared": [1.0],
            "executed": executed_profile,
            "reported": report_profile,
            "passes": exact_profile,
        },
        "accounting_maximum_absolute_error": accounting_error,
        "gates": gates,
        "verdict": {
            "status": "supported" if live_eligible else "rejected",
            "paper_testable": False,
            "live_eligible": live_eligible,
            "reason": (
                "ETH is positive at 5 bps but fails profile, benchmark, fold, month, "
                "year, capacity, maker, and prospective gates."
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = build_result(args.artifact_dir)
    Path(args.output).write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
