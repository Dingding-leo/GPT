from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

MARKETS = ("BTC-USDT", "ETH-USDT")
INITIAL_CAPITAL_USD = 1_000_000.0
PARTICIPATION_LIMIT = 0.001
LIQUIDITY_LOOKBACK = 30
ADJUSTMENT_THRESHOLD = 1e-12
ANNUALIZATION = 365
EXPECTED_OBSERVATIONS = 2_385
EXPECTED_HASHES = {
    "BTC-USDT": {
        "snapshot": "407aeba3d1ad4c8e8682a6a689c1c6327139f42bc7587aaae75c77fce047dec1",
        "returns": "04a0a5257d1e20f1eb88c70b8a0b010d21f0dc35ccb657ba39f14189e9f20790",
    },
    "ETH-USDT": {
        "snapshot": "842b4bbbb0ad7afbe2a1c9ee375443671d818a799266d5dc25cc6a548571ad7f",
        "returns": "4b69db4a44644a5f830e1518aca93356c0eeacf502dc00ba990bd992b9bd387f",
    },
}
SOURCE = {
    "workflow_run_id": 30052415258,
    "artifact_id": 8581531945,
    "artifact_name": "quant-research-source-392-attempt-1",
    "artifact_sha256": "1ccdf6ad90250df0f4cc4cd2d8261f47ff29949b36fe78ab037db94910874cf0",
    "source_head_sha": "d51694df876ddeb0059598fe24b6022c8ae7cbd5",
}
CANONICAL_SIGNATURE = (
    "canonical-5bps-prior-volume-capacity-gate-v1|markets=BTC-USDT,ETH-USDT|"
    "source=verified-OKX-1Dutc-snapshots-and-canonical-5bps-returns|"
    "candidate=initial-capital-usd-1000000|"
    "trade-notional=abs-turnover*prior-nav*initial-capital|"
    "liquidity-proxy=prior-30-session-median-daily-quote-volume|"
    "participation-limit=0.10pct|"
    "claim=every-adjustment-at-or-below-limit-in-both-markets|candidate_count=1"
)
_EXPLICIT_ZONE = re.compile(r"(?:Z|[+-]\d{2}:?\d{2})$")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _timestamps(values: pd.Series) -> pd.DatetimeIndex:
    raw = values.astype("string")
    if not bool(raw.map(lambda value: bool(_EXPLICIT_ZONE.search(str(value)))).all()):
        raise ValueError("timestamps must contain an explicit timezone")
    timestamps = pd.DatetimeIndex(pd.to_datetime(raw, utc=True, errors="raise"))
    if timestamps.has_duplicates or not timestamps.is_monotonic_increasing:
        raise ValueError("timestamps must be unique and strictly increasing")
    if len(timestamps) > 1:
        intervals = timestamps[1:] - timestamps[:-1]
        if not bool((intervals == pd.Timedelta(days=1)).all()):
            raise ValueError("timestamps must have exact daily cadence")
    return timestamps


def load_snapshot(path: Path, expected_sha256: str) -> pd.DataFrame:
    if file_sha256(path) != expected_sha256:
        raise ValueError(f"snapshot SHA-256 mismatch: {path}")
    frame = pd.read_csv(path)
    required = {"timestamp", "volume_quote", "confirm"}
    missing = required - set(frame)
    if missing:
        raise ValueError(f"snapshot missing columns: {sorted(missing)}")
    validated = pd.DataFrame(index=_timestamps(frame["timestamp"]))
    validated["volume_quote"] = pd.to_numeric(
        frame["volume_quote"],
        errors="raise",
    ).to_numpy()
    confirm = pd.to_numeric(frame["confirm"], errors="raise")
    values = validated["volume_quote"].to_numpy(dtype=float)
    if not np.isfinite(values).all() or np.any(values <= 0.0):
        raise ValueError("quote volume must be finite and positive")
    if not bool(confirm.eq(1).all()):
        raise ValueError("snapshot must contain only confirmed candles")
    return validated


def load_returns(path: Path, expected_sha256: str) -> pd.DataFrame:
    if file_sha256(path) != expected_sha256:
        raise ValueError(f"return SHA-256 mismatch: {path}")
    frame = pd.read_csv(path)
    required = {"timestamp", "turnover", "nav", "strategy_return", "fold"}
    missing = required - set(frame)
    if missing:
        raise ValueError(f"returns missing columns: {sorted(missing)}")
    validated = pd.DataFrame(index=_timestamps(frame["timestamp"]))
    for column in ("turnover", "nav", "strategy_return", "fold"):
        validated[column] = pd.to_numeric(
            frame[column],
            errors="raise",
        ).to_numpy()
    values = validated[["turnover", "nav", "strategy_return"]].to_numpy(dtype=float)
    if len(validated) != EXPECTED_OBSERVATIONS:
        raise ValueError(f"expected {EXPECTED_OBSERVATIONS} OOS observations")
    if not np.isfinite(values).all() or np.any(validated["turnover"] < 0.0):
        raise ValueError("returns must contain finite non-negative turnover and finite metrics")
    if np.any(validated["nav"] <= 0.0) or np.any(validated["strategy_return"] <= -1.0):
        raise ValueError("NAV must be positive and returns greater than -100%")
    return validated


def capacity_frame(
    snapshot: pd.DataFrame,
    returns: pd.DataFrame,
) -> pd.DataFrame:
    lagged_liquidity = (
        snapshot["volume_quote"]
        .rolling(LIQUIDITY_LOOKBACK, min_periods=LIQUIDITY_LOOKBACK)
        .median()
        .shift(1)
        .rename("prior_median_quote_volume")
    )
    result = returns.join(lagged_liquidity, how="left")
    result["equity_multiple_before"] = result["nav"].shift(1).fillna(1.0)
    result["trade_notional_usd"] = (
        result["turnover"].abs() * result["equity_multiple_before"] * INITIAL_CAPITAL_USD
    )
    result["participation"] = result["trade_notional_usd"] / result["prior_median_quote_volume"]
    adjustments = result["turnover"].abs() > ADJUSTMENT_THRESHOLD
    if result.loc[adjustments, "prior_median_quote_volume"].isna().any():
        raise ValueError("every adjustment must have a complete prior liquidity window")
    if not np.isfinite(result.loc[adjustments, "participation"].to_numpy(dtype=float)).all():
        raise ValueError("capacity participation must be finite on adjustment days")
    result["capacity_initial_usd"] = np.where(
        adjustments,
        PARTICIPATION_LIMIT
        * result["prior_median_quote_volume"]
        / (result["turnover"].abs() * result["equity_multiple_before"]),
        np.nan,
    )
    return result


def capacity_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    adjustments = frame.loc[frame["turnover"].abs() > ADJUSTMENT_THRESHOLD].copy()
    if adjustments.empty:
        raise ValueError("capacity analysis requires at least one adjustment")
    participation = adjustments["participation"]
    breaches = participation > PARTICIPATION_LIMIT
    max_index = participation.idxmax()
    max_trade_index = adjustments["trade_notional_usd"].idxmax()
    return {
        "adjustment_days": int(len(adjustments)),
        "breach_days": int(breaches.sum()),
        "breach_share": float(breaches.mean()),
        "median_participation": float(participation.median()),
        "p95_participation": float(participation.quantile(0.95)),
        "p99_participation": float(participation.quantile(0.99)),
        "maximum_participation": float(participation.max()),
        "maximum_participation_date": max_index.isoformat(),
        "maximum_trade_notional_usd": float(adjustments["trade_notional_usd"].max()),
        "maximum_trade_notional_date": max_trade_index.isoformat(),
        "minimum_supported_initial_capital_usd": float(adjustments["capacity_initial_usd"].min()),
        "passes": bool(not breaches.any()),
    }


def return_metrics(frame: pd.DataFrame) -> dict[str, float | int]:
    values = frame["strategy_return"].to_numpy(dtype=float)
    growth = float(np.prod(1.0 + values))
    total_return = growth - 1.0
    cagr = growth ** (ANNUALIZATION / len(values)) - 1.0
    mean = float(values.mean())
    standard_deviation = float(values.std(ddof=0))
    downside = np.minimum(values, 0.0)
    downside_deviation = float(np.sqrt(np.mean(np.square(downside))))
    nav = np.concatenate(([1.0], np.cumprod(1.0 + values)))
    drawdown = nav / np.maximum.accumulate(nav) - 1.0
    max_drawdown = float(drawdown.min())
    folds = [
        float((1.0 + group["strategy_return"]).prod() - 1.0)
        for _, group in frame.groupby("fold", sort=True)
    ]
    return {
        "total_return": total_return,
        "cagr": cagr,
        "annualized_arithmetic_mean": mean * ANNUALIZATION,
        "sharpe": mean / standard_deviation * math.sqrt(ANNUALIZATION),
        "sortino": mean / downside_deviation * math.sqrt(ANNUALIZATION),
        "calmar": cagr / abs(max_drawdown),
        "max_drawdown": max_drawdown,
        "annualized_turnover": float(frame["turnover"].mean()) * ANNUALIZATION,
        "profitable_folds": int(sum(value > 0.0 for value in folds)),
        "fold_count": int(len(folds)),
    }


def analyze(artifact_dir: Path) -> dict[str, Any]:
    market_results: dict[str, Any] = {}
    baseline_metrics: dict[str, Any] = {}
    for market in MARKETS:
        root = artifact_dir / market
        snapshot = load_snapshot(
            root / "snapshot" / f"okx-{market}-1Dutc.csv",
            EXPECTED_HASHES[market]["snapshot"],
        )
        returns = load_returns(
            root / "walk_forward_returns.csv",
            EXPECTED_HASHES[market]["returns"],
        )
        frame = capacity_frame(snapshot, returns)
        market_results[market] = capacity_metrics(frame)
        baseline_metrics[market] = return_metrics(returns)

    candidate_passes = all(market_results[market]["passes"] for market in MARKETS)
    return {
        "canonical_signature": CANONICAL_SIGNATURE,
        "hypothesis": (
            "A USD 1,000,000 canonical 5 bps account can execute every "
            "BTC-USDT and ETH-USDT OOS position adjustment at no more than "
            "0.10% of the strictly lagged 30-session median daily quote volume."
        ),
        "verdict": "supported" if candidate_passes else "rejected",
        "candidate_accounting": {
            "searched": 1,
            "passed": int(candidate_passes),
            "rejected": int(not candidate_passes),
        },
        "live_eligible": False,
        "method": {
            "initial_capital_usd": INITIAL_CAPITAL_USD,
            "participation_limit": PARTICIPATION_LIMIT,
            "liquidity_lookback_sessions": LIQUIDITY_LOOKBACK,
            "liquidity_estimator": ("prior-session-shifted rolling median of daily quote volume"),
            "trade_notional": ("absolute turnover * prior NAV multiple * initial capital"),
            "adjustment_threshold": ADJUSTMENT_THRESHOLD,
            "baseline_exchange_fee_bps_one_way": 5.0,
            "all_in_cost_sensitivities_bps": [5.0, 7.5, 10.0, 15.0],
            "sealed_market_data_used": False,
        },
        "source": SOURCE
        | {
            "provider": "OKX",
            "market_type": "spot",
            "timeframe": "1Dutc",
            "period_start": "2020-01-11T00:00:00+00:00",
            "period_end": "2026-07-22T00:00:00+00:00",
            "observations_per_market": EXPECTED_OBSERVATIONS,
            "file_sha256": EXPECTED_HASHES,
        },
        "canonical_5bps_metrics": baseline_metrics,
        "capacity_candidate": {
            "label": "initial-capital-usd-1000000",
            "passes": candidate_passes,
            "markets": market_results,
        },
        "live_gates": {
            "corrected_5bps_full_walk_forward": "pass",
            "benchmark_relative_risk_adjusted": "fail",
            "fold_stability": "fail",
            "year_stability": "fail",
            "turnover_and_5_7.5_10_15bps_viability": "pass",
            "parameter_neighbourhood_stability": "pass",
            "tail_risk": "pass",
            "execution_delay_robustness": "fail",
            "capacity": "pass" if candidate_passes else "fail",
            "separate_spread_slippage_impact_latency": "blocked",
            "untouched_market_validation": "fail",
            "prospective_forward_validation": "blocked",
            "overall_live_eligibility": "false",
        },
        "limitations": [
            (
                "Daily quote volume is a retrospective capacity proxy, not "
                "executable top-of-book depth."
            ),
            (
                "The 0.10% limit is applied to a strictly lagged 30-session "
                "median, but it does not model intraday concentration or "
                "partial fills."
            ),
            (
                "BTC-USDT and ETH-USDT are development markets; SOL-USDT is a "
                "consumed holdout and was not used."
            ),
            ("Spread, slippage, market impact, and latency remain separately unmeasured."),
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.artifact_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
