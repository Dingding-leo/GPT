from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

MARKET = "SOL-USDT"
BENCHMARK = "volatility_targeted_long"
ANNUALIZATION = 365
TAIL_FRACTION = 0.05
SIGNATURE = (
    "canonical-5bps-sol-sealed-holdout-v1|market=SOL-USDT|"
    "architecture-base=9ab1bafddcc67ac78d4c42cd1bfb9e6e96b97449|"
    "source=public-OKX-spot-1Dutc|data-cutoff=2026-07-22T00:00:00Z|"
    "baseline=full-reselection-5bps|grid=27-declared-candidates|"
    "selection=730|test=90-nonoverlapping|execution=one-bar-delay|"
    "costs=5,7.5,10,15bps-fixed-selected-path|"
    "benchmark=volatility-targeted-long|"
    "benchmark-evidence=paired-noncircular-moving-block-bootstrap-"
    "sharpe-and-calmar-lower-bounds-positive|"
    "block=20|resamples=2000|confidence=0.95|seed=2026072405|"
    "fold-stability=repository-gate|"
    "year-stability=at-least-4-complete-years-and-60pct-profitable-"
    "and-worst-year-above-minus20pct|"
    "turnover=max20-and-15bps-total-return-and-sharpe-positive|"
    "neighbourhood=all-perturbations-positive-return-and-sharpe-and-dd-above-minus40pct|"
    "tail=maxdd-better-than-benchmark-and-above-minus35pct-and-es-better|"
    "candidate-count=1|no-same-market-retuning=true"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate the frozen SOL-USDT sealed architecture holdout."
    )
    parser.add_argument("--report-json", required=True)
    parser.add_argument("--returns-csv", required=True)
    parser.add_argument("--bootstrap-json", required=True)
    parser.add_argument("--effective-config", required=True)
    parser.add_argument("--freeze-head", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def total_return(values: pd.Series) -> float:
    array = values.to_numpy(dtype=float)
    if array.size == 0 or not np.isfinite(array).all() or np.any(array <= -1.0):
        raise ValueError("returns must be finite, non-empty, and greater than -1")
    return float(np.prod(1.0 + array) - 1.0)


def load_returns(path: str | Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    required = {
        "timestamp",
        "strategy_return",
        "benchmark_volatility_targeted_long_return",
        "fold",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"returns file is missing required columns: {sorted(missing)}")

    parsed_timestamps: list[pd.Timestamp] = []
    for value in frame["timestamp"]:
        timestamp = pd.Timestamp(value)
        if pd.isna(timestamp) or timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timestamps must contain explicit timezone information")
        parsed_timestamps.append(timestamp)
    timestamps = pd.Series(pd.to_datetime(parsed_timestamps, utc=True), index=frame.index)
    if timestamps.duplicated().any() or not timestamps.is_monotonic_increasing:
        raise ValueError("timestamps must be unique and strictly increasing")
    if len(timestamps) > 1 and not timestamps.diff().iloc[1:].eq(pd.Timedelta(days=1)).all():
        raise ValueError("timestamps must have exact daily cadence")

    numeric_columns = required - {"timestamp"}
    numeric = frame[list(numeric_columns)].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any() or not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise ValueError("required return columns must contain finite numeric values")
    return frame.assign(timestamp=timestamps, **{column: numeric[column] for column in numeric})


def expected_shortfall(values: pd.Series, fraction: float = TAIL_FRACTION) -> float:
    count = math.ceil(len(values) * fraction)
    return float(np.sort(values.to_numpy(dtype=float))[:count].mean())


def calendar_years(frame: pd.DataFrame) -> list[dict[str, Any]]:
    indexed = frame.set_index("timestamp")["strategy_return"]
    records: list[dict[str, Any]] = []
    for year, group in indexed.groupby(indexed.index.year, sort=True):
        start = group.index[0]
        end = group.index[-1]
        records.append(
            {
                "year": int(year),
                "return": total_return(group),
                "partial": not (
                    start.month == 1 and start.day == 1 and end.month == 12 and end.day == 31
                ),
            }
        )
    return records


def _markdown(payload: dict[str, Any]) -> str:
    metrics = payload["metrics_5bps"]
    benchmark = payload["benchmark"]
    gates = payload["gates"]
    cost_rows = []
    for cost, values in payload["cost_stress"].items():
        cost_rows.append(
            f"| {cost} | {values['total_return']:.6%} | {values['sharpe']:.6f} | "
            f"{values['max_drawdown']:.6%} |"
        )
    gate_rows = [f"| {name} | **{status}** |" for name, status in gates.items()]
    return "\n".join(
        [
            "# SOL-USDT sealed architecture holdout",
            "",
            "## Hypothesis",
            "",
            (
                "The frozen canonical 5 bps full-reselection architecture passes every "
                "predeclared retrospective untouched-market gate on SOL-USDT without "
                "same-market retuning."
            ),
            "",
            f"**Verdict:** `{payload['verdict']}`",
            "",
            "## Exact 5 bps metrics",
            "",
            "| Metric | Strategy | Volatility-targeted long |",
            "|---|---:|---:|",
            (
                f"| Net total return | {metrics['net_total_return']:.6%} | "
                f"{benchmark['total_return']:.6%} |"
            ),
            f"| CAGR | {metrics['cagr']:.6%} | {benchmark['cagr']:.6%} |",
            f"| Sharpe | {metrics['sharpe']:.6f} | {benchmark['sharpe']:.6f} |",
            f"| Sortino | {metrics['sortino']:.6f} | {benchmark['sortino']:.6f} |",
            f"| Calmar | {metrics['calmar']:.6f} | {benchmark['calmar']:.6f} |",
            (
                f"| Maximum drawdown | {metrics['max_drawdown']:.6%} | "
                f"{benchmark['max_drawdown']:.6%} |"
            ),
            (
                f"| Annualized turnover | {metrics['annualized_turnover']:.6f} | "
                f"{benchmark['annualized_turnover']:.6f} |"
            ),
            (
                f"| Average absolute exposure | "
                f"{metrics['average_abs_exposure']:.6%} | "
                f"{benchmark['average_abs_exposure']:.6%} |"
            ),
            "",
            "## Fixed selected-path cost stress",
            "",
            "| All-in cost | Total return | Sharpe | Maximum drawdown |",
            "|---:|---:|---:|---:|",
            *cost_rows,
            "",
            "## Gate status",
            "",
            "| Gate | Status |",
            "|---|---|",
            *gate_rows,
            "",
            "## Candidate accounting",
            "",
            f"- searched: {payload['candidate_accounting']['searched']}",
            f"- passed: {payload['candidate_accounting']['passed']}",
            f"- rejected: {payload['candidate_accounting']['rejected']}",
            "",
            "## Interpretation",
            "",
            payload["interpretation"],
            "",
            (
                "This one-shot result does not permit SOL-USDT retuning. Capacity, separately "
                "measured spread/slippage/impact/latency, and prospective forward evidence "
                "remain mandatory before paper/live eligibility."
            ),
            "",
        ]
    )


def evaluate(
    *,
    report: dict[str, Any],
    bootstrap: dict[str, Any],
    config: dict[str, Any],
    frame: pd.DataFrame,
    freeze_head: str,
    paths: dict[str, Path],
) -> dict[str, Any]:
    sealed = config.get("sealed_holdout")
    if not isinstance(sealed, dict):
        raise ValueError("effective configuration is missing sealed_holdout metadata")
    if config["data"]["inst_id"] != MARKET or sealed["untouched_market"] != MARKET:
        raise ValueError("sealed holdout configuration must be bound to SOL-USDT")
    if sealed["architecture_base_sha"] != "9ab1bafddcc67ac78d4c42cd1bfb9e6e96b97449":
        raise ValueError("sealed architecture base SHA changed after predeclaration")
    if not bool(sealed["no_same_market_retuning"]):
        raise ValueError("sealed holdout must prohibit same-market retuning")
    if report["data_summary"]["provenance"]["instrument_id"] != MARKET:
        raise ValueError("report provenance is not bound to SOL-USDT")
    if report["settings"]["candidate_count"] != 27:
        raise ValueError("sealed holdout must evaluate the declared 27-candidate grid")

    aggregate = report["aggregate_metrics"]
    benchmark = report["benchmark_metrics"][BENCHMARK]
    comparison = bootstrap["result"]["comparisons"][BENCHMARK]
    years = calendar_years(frame)
    complete_years = [record for record in years if not record["partial"]]
    profitable_year_ratio = (
        sum(record["return"] > 0.0 for record in complete_years) / len(complete_years)
        if complete_years
        else 0.0
    )
    thresholds = sealed["gates"]
    year_stability = (
        len(complete_years) >= int(thresholds["complete_years_min"])
        and profitable_year_ratio >= float(thresholds["profitable_complete_year_ratio_min"])
        and min((record["return"] for record in complete_years), default=-math.inf)
        > float(thresholds["worst_complete_year_floor"])
    )
    cost_stress = {
        f"{float(multiplier.rstrip('x')) * 5.0:g} bps": {
            "total_return": float(values["total_return"]),
            "sharpe": float(values["sharpe"]),
            "max_drawdown": float(values["max_drawdown"]),
        }
        for multiplier, values in report["cost_stress_metrics"].items()
    }
    benchmark_es = expected_shortfall(frame["benchmark_volatility_targeted_long_return"])
    strategy_es = expected_shortfall(frame["strategy_return"])
    baseline_integrity = (
        float(config["strategy"]["transaction_cost_bps"]) == 5.0
        and report["settings"]["candidate_count"] == 27
        and report["settings"]["selection_bars"] == 730
        and report["settings"]["test_bars"] == 90
        and sealed["candidate_count"] == 1
    )
    benchmark_relative = bool(
        comparison["sharpe"]["lower_bound_positive"]
        and comparison["calmar"]["lower_bound_positive"]
    )
    fold_stability = bool(report["fold_stability"]["passes"])
    turnover_cost = (
        float(aggregate["annualized_turnover"]) <= float(thresholds["annualized_turnover_max"])
        and cost_stress["15 bps"]["total_return"] > 0.0
        and cost_stress["15 bps"]["sharpe"] > 0.0
    )
    neighbourhood = all(
        float(values["total_return"]) > 0.0
        and float(values["sharpe"]) > 0.0
        and float(values["max_drawdown"]) > -0.40
        for values in report["perturbation_metrics"].values()
    )
    tail_risk = (
        float(aggregate["max_drawdown"]) > float(benchmark["max_drawdown"])
        and float(aggregate["max_drawdown"]) >= float(thresholds["maximum_drawdown_floor"])
        and strategy_es > benchmark_es
    )
    retrospective_checks = {
        "frozen_architecture_and_5bps_baseline": baseline_integrity,
        "benchmark_relative_risk_adjusted": benchmark_relative,
        "fold_stability": fold_stability,
        "year_stability": year_stability,
        "turnover_and_cost_viability": turnover_cost,
        "parameter_neighborhood_stability": neighbourhood,
        "tail_risk": tail_risk,
    }
    retrospective_pass = all(retrospective_checks.values())
    gates = {
        **{name: "pass" if passed else "fail" for name, passed in retrospective_checks.items()},
        "untouched_market_validation": "pass" if retrospective_pass else "fail",
        "separate_spread_slippage_impact_latency": "blocked",
        "capacity": "blocked",
        "prospective_forward_validation": "blocked",
        "overall_live_eligibility": "fail",
    }
    failed = [name for name, status in gates.items() if status != "pass"]
    verdict = "supported" if retrospective_pass else "rejected"
    interpretation = (
        "The frozen architecture passed every predeclared retrospective SOL-USDT holdout "
        "gate, but it is still not paper/live eligible because execution-component, capacity, "
        "and prospective-forward gates are blocked."
        if retrospective_pass
        else "The frozen architecture failed one or more predeclared retrospective SOL-USDT "
        "holdout gates. The result is rejected and SOL-USDT must not be used for same-market "
        "retuning."
    )
    return {
        "canonical_signature": SIGNATURE,
        "hypothesis": (
            "The frozen canonical 5 bps full-reselection architecture passes every "
            "predeclared retrospective untouched-market gate on SOL-USDT without "
            "same-market retuning."
        ),
        "verdict": verdict,
        "candidate_accounting": {
            "searched": 1,
            "passed": int(retrospective_pass),
            "rejected": int(not retrospective_pass),
        },
        "freeze": {
            "architecture_base_sha": sealed["architecture_base_sha"],
            "pre_result_branch_head_sha": freeze_head,
            "data_cutoff_utc": sealed["data_cutoff_utc"],
            "no_same_market_retuning": True,
        },
        "provenance": {
            "market": MARKET,
            "provider": report["data_summary"]["provenance"]["provider"],
            "timeframe": report["data_summary"]["provenance"]["bar"],
            "evaluation_start": report["data_summary"]["evaluation_start"],
            "evaluation_end": report["data_summary"]["evaluation_end"],
            "observations": int(aggregate["observations"]),
            "report_sha256": file_sha256(paths["report"]),
            "returns_sha256": file_sha256(paths["returns"]),
            "bootstrap_sha256": file_sha256(paths["bootstrap"]),
            "effective_config_sha256": file_sha256(paths["config"]),
            "snapshot_sha256": report["data_summary"]["provenance"]["normalized_csv_sha256"],
        },
        "metrics_5bps": {
            "gross_total_return": float(aggregate["gross_total_return"]),
            "net_total_return": float(aggregate["net_total_return"]),
            "cagr": float(aggregate["cagr"]),
            "annualized_arithmetic_mean": float(aggregate["annualized_arithmetic_mean"]),
            "sharpe": float(aggregate["sharpe"]),
            "sortino": float(aggregate["sortino"]),
            "calmar": float(aggregate["calmar"]),
            "max_drawdown": float(aggregate["max_drawdown"]),
            "annualized_turnover": float(aggregate["annualized_turnover"]),
            "average_abs_exposure": float(aggregate["average_abs_exposure"]),
            "exchange_fee_sum": float(aggregate["exchange_fee_sum"]),
        },
        "benchmark": {key: float(value) for key, value in benchmark.items()},
        "benchmark_bootstrap": {metric: comparison[metric] for metric in ("sharpe", "calmar")},
        "fold_stability": report["fold_stability"],
        "calendar_years": years,
        "cost_stress": cost_stress,
        "parameter_perturbations": report["perturbation_metrics"],
        "tail_risk": {
            "strategy_expected_shortfall_5pct": strategy_es,
            "benchmark_expected_shortfall_5pct": benchmark_es,
        },
        "gates": gates,
        "blockers": failed,
        "overall_live_eligible": False,
        "interpretation": interpretation,
    }


def main() -> int:
    args = parse_args()
    paths = {
        "report": Path(args.report_json),
        "returns": Path(args.returns_csv),
        "bootstrap": Path(args.bootstrap_json),
        "config": Path(args.effective_config),
    }
    report = json.loads(paths["report"].read_text(encoding="utf-8"))
    bootstrap = json.loads(paths["bootstrap"].read_text(encoding="utf-8"))
    config = json.loads(paths["config"].read_text(encoding="utf-8"))
    frame = load_returns(paths["returns"])
    payload = evaluate(
        report=report,
        bootstrap=bootstrap,
        config=config,
        frame=frame,
        freeze_head=args.freeze_head,
        paths=paths,
    )
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    result_path = output / "result.json"
    report_path = output / "REPORT.md"
    result_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(_markdown(payload), encoding="utf-8")
    print(f"holdout_verdict={payload['verdict']}")
    print(f"overall_live_eligible={str(payload['overall_live_eligible']).lower()}")
    print(f"result_path={result_path}")
    print(f"report_path={report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
