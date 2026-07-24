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
EXPECTED_ARTIFACT_SHA256 = (
    "b0ef75175a74331e636bc0f20e5084194746bea82c41b3dd94488d9c5271a9c2"
)
EXPECTED_RETURN_SHA256 = (
    "a10404c8d24dc7899baf382d7695198118d4490065838a3a1d41720da1edba92"
)
EXPECTED_REPORT_SHA256 = (
    "ee6a6f61e59d8511aba0046cc04e7b7fec4a54bb6a35c0a2c38238155aa632a1"
)
EXPECTED_SNAPSHOT_SHA256 = (
    "21f6eba97e0120912cf1c9e5679d2c3132e8ac9cbfe221f9f405aa7b654c2ca7"
)
SOURCE_WORKFLOW_RUN_ID = 30_062_329_424
SOURCE_ARTIFACT_ID = 8_585_012_784
SOURCE_HEAD_SHA = "0f76d9671a009cb8b397ad4ef64c5a311ff35b7b"
CANONICAL_SIGNATURE = (
    "canonical-btc-1h-paper-gate-v1|market=BTC-USDT|provider=OKX-spot|bar=1H|"
    "architecture=daily-horizons-scaled-24x|selection=17520|test=2160|"
    "internal-candidates=27|fee=5bps-one-way|execution=one-bar-delayed-close-return|"
    "claim=all-source-oos-risk-stability-activity-tail-capacity-paper-gates-pass|"
    "candidate_count=1"
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
    count = math.ceil(len(ordered) * fraction)
    return float(ordered[:count].mean())


def load_returns(path: str | Path) -> pd.DataFrame:
    source = Path(path)
    observed_sha256 = file_sha256(source)
    if observed_sha256 != EXPECTED_RETURN_SHA256:
        raise ValueError(
            "BTC-USDT 1h return file SHA-256 mismatch: "
            f"expected {EXPECTED_RETURN_SHA256}, observed {observed_sha256}"
        )

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

    timestamp_text = frame["timestamp"].astype("string")
    has_zone = timestamp_text.str.contains(r"(?:Z|[+-]\d{2}:?\d{2})$", regex=True, na=False)
    if not bool(has_zone.all()):
        raise ValueError("timestamps must include an explicit timezone")

    timestamps = pd.DatetimeIndex(pd.to_datetime(timestamp_text, utc=True, errors="raise"))
    if timestamps.duplicated().any() or not timestamps.is_monotonic_increasing:
        raise ValueError("timestamps must be unique and strictly increasing")
    if len(timestamps) > 1:
        cadence = timestamps[1:] - timestamps[:-1]
        if not bool((cadence == pd.Timedelta(hours=1)).all()):
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
    for column in numeric_columns:
        validated[column] = numeric[column]
    return validated


def calendar_month_diagnostics(frame: pd.DataFrame) -> dict[str, Any]:
    month_keys = frame["timestamp"].dt.strftime("%Y-%m")
    records: list[dict[str, Any]] = []
    for key, group in frame.groupby(month_keys, sort=True):
        start = pd.Timestamp(f"{key}-01T00:00:00Z")
        end = start + pd.offsets.MonthEnd(1) + pd.Timedelta(hours=23)
        expected_count = int((end - start) / pd.Timedelta(hours=1)) + 1
        complete = (
            group["timestamp"].iloc[0] == start
            and group["timestamp"].iloc[-1] == end
            and len(group) == expected_count
        )
        records.append(
            {
                "month": key,
                "complete": bool(complete),
                "observations": len(group),
                "total_return": _compound(group["strategy_return"]),
            }
        )

    complete_records = [record for record in records if record["complete"]]
    positive = [record for record in complete_records if record["total_return"] > 0.0]
    positive_sum = sum(record["total_return"] for record in positive)
    max_positive_share = (
        max(record["total_return"] for record in positive) / positive_sum
        if positive_sum > 0.0
        else None
    )
    ratio = len(positive) / len(complete_records) if complete_records else 0.0
    passes = (
        len(complete_records) >= 24
        and ratio >= 0.5
        and max_positive_share is not None
        and max_positive_share <= 0.5
    )
    return {
        "complete_months": len(complete_records),
        "profitable_complete_months": len(positive),
        "profitable_complete_month_ratio": ratio,
        "max_positive_month_share": max_positive_share,
        "passes": passes,
        "records": records,
    }


def calendar_year_diagnostics(frame: pd.DataFrame) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for year, group in frame.groupby(frame["timestamp"].dt.year, sort=True):
        start = pd.Timestamp(f"{year}-01-01T00:00:00Z")
        end = pd.Timestamp(f"{year}-12-31T23:00:00Z")
        expected_count = int((end - start) / pd.Timedelta(hours=1)) + 1
        complete = (
            group["timestamp"].iloc[0] == start
            and group["timestamp"].iloc[-1] == end
            and len(group) == expected_count
        )
        records.append(
            {
                "year": int(year),
                "complete": bool(complete),
                "observations": len(group),
                "total_return": _compound(group["strategy_return"]),
            }
        )

    complete_records = [record for record in records if record["complete"]]
    profitable = [record for record in complete_records if record["total_return"] > 0.0]
    passes = len(complete_records) >= 3 and len(profitable) == len(complete_records)
    return {
        "complete_years": len(complete_records),
        "profitable_complete_years": len(profitable),
        "passes": passes,
        "records": records,
    }


def activity_diagnostics(frame: pd.DataFrame) -> dict[str, Any]:
    exposed = frame["position"] > 1e-12
    starts = exposed & ~exposed.shift(fill_value=False)
    ends = exposed & ~exposed.shift(-1, fill_value=False)
    start_indices = np.flatnonzero(starts.to_numpy())
    end_indices = np.flatnonzero(ends.to_numpy())

    durations: list[int] = []
    end_cursor = 0
    for start_index in start_indices:
        while end_cursor < len(end_indices) and end_indices[end_cursor] < start_index:
            end_cursor += 1
        end_index = (
            int(end_indices[end_cursor]) if end_cursor < len(end_indices) else len(frame) - 1
        )
        durations.append(end_index - int(start_index) + 1)

    years = len(frame) / ANNUALIZATION
    adjustment_count = int((frame["turnover"] > 1e-12).sum())
    episode_count = len(durations)
    median_holding = float(np.median(durations)) if durations else None
    passes = (
        episode_count >= 100
        and episode_count / years >= 24.0
        and median_holding is not None
        and median_holding <= 72.0
    )
    return {
        "adjustment_count": adjustment_count,
        "annualized_adjustment_count": adjustment_count / years,
        "exposure_episode_count": episode_count,
        "annualized_exposure_episode_count": episode_count / years,
        "median_holding_hours": median_holding,
        "mean_holding_hours": float(np.mean(durations)) if durations else None,
        "maximum_holding_hours": int(max(durations)) if durations else None,
        "annualized_turnover": float(frame["turnover"].sum() / years),
        "annualized_effective_round_trips": float(frame["turnover"].sum() / (2.0 * years)),
        "passes": passes,
    }


def build_result(artifact_dir: str | Path) -> dict[str, Any]:
    root = Path(artifact_dir)
    market_dir = root / "BTC-USDT"
    returns_path = market_dir / "walk_forward_returns.csv"
    report_path = market_dir / "walk_forward.json"
    snapshot_path = market_dir / "snapshot" / "okx-BTC-USDT-1H.csv"

    observed_report_sha256 = file_sha256(report_path)
    observed_snapshot_sha256 = file_sha256(snapshot_path)
    if observed_report_sha256 != EXPECTED_REPORT_SHA256:
        raise ValueError("walk-forward report SHA-256 mismatch")
    if observed_snapshot_sha256 != EXPECTED_SNAPSHOT_SHA256:
        raise ValueError("snapshot SHA-256 mismatch")

    frame = load_returns(returns_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    metrics = report["aggregate_metrics"]
    benchmarks = report["benchmark_metrics"]
    fold_stability = report["fold_stability"]
    perturbations = report["perturbation_metrics"]

    accounting_error = np.max(
        np.abs(
            frame["strategy_return"].to_numpy(dtype=float)
            - (
                frame["gross_strategy_return"].to_numpy(dtype=float)
                - frame["trading_cost"].to_numpy(dtype=float)
            )
        )
    )
    if float(accounting_error) > 1e-15:
        raise ValueError("gross-minus-fee accounting does not reproduce net returns")

    monthly = calendar_month_diagnostics(frame)
    yearly = calendar_year_diagnostics(frame)
    activity = activity_diagnostics(frame)

    benchmark_relative_passes = all(
        float(metrics[key]) > float(benchmarks[name][key])
        for name in ("volatility_targeted_long", "simple_trend_long_cash")
        for key in ("sharpe", "calmar")
    )
    neighbourhood_passes = all(
        float(values["net_total_return"]) > 0.0 and float(values["sharpe"]) > 0.0
        for values in perturbations.values()
    )
    strategy_es = _expected_shortfall(frame["strategy_return"])
    benchmark_es = _expected_shortfall(frame["benchmark_volatility_targeted_long_return"])
    tail_passes = strategy_es > benchmark_es

    gates: dict[str, dict[str, Any]] = {
        "source_complete_and_reproducible": {"status": "pass"},
        "positive_5bps_oos_path": {
            "status": "pass"
            if float(metrics["net_total_return"]) > 0.0 and float(metrics["sharpe"]) > 0.0
            else "fail"
        },
        "benchmark_relative_risk_adjusted": {
            "status": "pass" if benchmark_relative_passes else "fail"
        },
        "fold_stability": {"status": "pass" if fold_stability["passes"] else "fail"},
        "month_stability": {"status": "pass" if monthly["passes"] else "fail"},
        "year_stability": {"status": "pass" if yearly["passes"] else "fail"},
        "turnover_holding_and_trade_sufficiency": {
            "status": "pass" if activity["passes"] else "fail"
        },
        "parameter_neighbourhood_stability": {
            "status": "pass" if neighbourhood_passes else "fail"
        },
        "tail_risk": {"status": "pass" if tail_passes else "fail"},
        "cross_market_replication": {
            "status": "blocked",
            "reason": "ETH-USDT canonical 1h evidence is not present",
        },
        "capacity": {
            "status": "blocked",
            "reason": "no frozen point-in-time 1h capacity protocol is persisted",
        },
        "maker_execution_diagnostics": {
            "status": "blocked",
            "reason": (
                "fill quality, no-fill, partial fill, timeout, adverse selection, and "
                "latency are not present and are not added to PnL"
            ),
        },
        "prospective_paper_evidence": {
            "status": "blocked",
            "reason": "no prospective 1h signal and maker-order replay exists",
        },
    }
    live_eligible = all(value["status"] == "pass" for value in gates.values())

    return {
        "hypothesis": (
            "The canonical BTC-USDT 1h full-reselection strategy clears every minimum "
            "source, OOS, stability, activity, tail, capacity, cross-market, maker, and "
            "prospective paper gate at exactly 5 bps one-way fee."
        ),
        "canonical_signature": CANONICAL_SIGNATURE,
        "candidate_accounting": {
            "architecture_candidates_searched": 1,
            "architecture_candidates_passed": 0 if not live_eligible else 1,
            "architecture_candidates_rejected": 1 if not live_eligible else 0,
            "fold_local_internal_candidates": int(report["settings"]["candidate_count"]),
            "oos_folds": int(fold_stability["fold_count"]),
        },
        "source": {
            "provider": "OKX",
            "market_type": "spot",
            "instrument": "BTC-USDT",
            "bar": "1H",
            "workflow_run_id": SOURCE_WORKFLOW_RUN_ID,
            "artifact_id": SOURCE_ARTIFACT_ID,
            "artifact_sha256": EXPECTED_ARTIFACT_SHA256,
            "source_head_sha": SOURCE_HEAD_SHA,
            "return_sha256": EXPECTED_RETURN_SHA256,
            "report_sha256": observed_report_sha256,
            "snapshot_sha256": observed_snapshot_sha256,
        },
        "design": {
            "fee_bps_one_way": 5.0,
            "modeled_execution": "one-bar-delayed close-to-close return",
            "selection_bars": int(report["settings"]["selection_bars"]),
            "test_bars": int(report["settings"]["test_bars"]),
            "annualization": ANNUALIZATION,
            "evaluation_start": report["data_summary"]["evaluation_start"],
            "evaluation_end": report["data_summary"]["evaluation_end"],
            "oos_observations": int(metrics["observations"]),
            "cost_scenarios_in_pnl": [5.0],
            "separate_execution_diagnostics": [
                "maker_fill_quality",
                "no_fill",
                "partial_fill",
                "timeout",
                "adverse_selection",
                "latency",
            ],
        },
        "metrics_5bps": {
            "net_total_return": float(metrics["net_total_return"]),
            "net_cagr": float(metrics["net_cagr"]),
            "net_annualized_arithmetic_mean": float(metrics["net_annualized_arithmetic_mean"]),
            "sharpe": float(metrics["sharpe"]),
            "sortino": float(metrics["sortino"]),
            "calmar": float(metrics["calmar"]),
            "max_drawdown": float(metrics["max_drawdown"]),
            "annualized_turnover": float(metrics["annualized_turnover"]),
            "average_abs_exposure": float(metrics["average_abs_exposure"]),
            "exchange_fee_sum": float(metrics["exchange_fee_sum"]),
        },
        "benchmark_metrics": {
            name: {
                "net_total_return": float(values["net_total_return"]),
                "sharpe": float(values["sharpe"]),
                "calmar": float(values["calmar"]),
                "max_drawdown": float(values["max_drawdown"]),
            }
            for name, values in benchmarks.items()
        },
        "fold_stability": fold_stability,
        "month_stability": monthly,
        "year_stability": yearly,
        "activity": activity,
        "parameter_stability": report["parameter_stability"],
        "tail_risk": {
            "tail_fraction": 0.05,
            "strategy_expected_shortfall": strategy_es,
            "volatility_targeted_long_expected_shortfall": benchmark_es,
            "passes": tail_passes,
        },
        "accounting": {"maximum_absolute_error": float(accounting_error)},
        "gates": gates,
        "verdict": {
            "status": "rejected" if not live_eligible else "supported",
            "paper_testable": False,
            "live_eligible": live_eligible,
            "reason": (
                "The 1h path is net profitable at 5 bps but lacks benchmark-relative edge, "
                "fold/month/year stability, ETH replication, capacity, maker execution, "
                "and prospective paper evidence."
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
