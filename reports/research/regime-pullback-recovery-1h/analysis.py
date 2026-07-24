from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np
import pandas as pd

ANNUALIZATION = 8_760
REGIME_LOOKBACK = 720
ZSCORE_LOOKBACK = 24
VOLATILITY_LOOKBACK = 168
ENTRY_Z = -1.5
EXIT_Z = -0.25
MAXIMUM_HOLDING_HOURS = 48
TARGET_VOLATILITY = 0.50
MAX_POSITION = 1.0
TRANSACTION_COST_BPS = 5.0
TEST_BARS = 2_160
EVALUATION_START = pd.Timestamp("2023-07-01T00:00:00Z")
EVALUATION_END = pd.Timestamp("2026-06-14T23:00:00Z")
BLOCK_LENGTH = 168
BOOTSTRAP_RESAMPLES = 2_000
CONFIDENCE = 0.95
TAIL_FRACTION = 0.05
CAPACITY_INITIAL_USD = 1_000_000.0
CAPACITY_PARTICIPATION_LIMIT = 0.001
CAPACITY_LIQUIDITY_LOOKBACK = 720
POSITION_EPSILON = 1e-12

CANONICAL_SIGNATURE = (
    "regime-pullback-recovery-1h-v1|markets=BTC-USDT,ETH-USDT|provider=OKX-spot|"
    "bar=1H|source=portable-canonical-1h-artifacts|"
    "architecture=720h-positive-regime-plus-24h-log-price-zscore-pullback-state-machine|"
    "entry-z=-1.5|exit-z=-0.25|max-hold=48h|"
    "episode-size=frozen-at-entry-50pct-vol-target-using-168h-realized-vol|"
    "max-position=1|fee=5bps-one-way|execution=one-complete-bar-delay|"
    "evaluation=2023-07-01T00:00Z..2026-06-14T23:00Z|fold=2160h|"
    "bootstrap=paired-noncircular-168h-blocks-2000-resamples-95pct|"
    "architecture-candidate-count=1"
)

MARKETS: dict[str, dict[str, Any]] = {
    "BTC-USDT": {
        "artifact_id": 8_586_473_477,
        "artifact_zip_sha256": ("44ef21be41117768f34422bff2458ef3daf1709b6335387c8ddc9d23077ebed7"),
        "artifact_manifest_sha256": (
            "16548b4abd0f2508a4c6646c30a04117fec7686e92b9a95028d142a2f0532216"
        ),
        "snapshot_filename": "okx-BTC-USDT-1H.csv",
        "snapshot_sha256": ("bbba1e9b36e17b03ff6aed237a4de949b4a39b1d17eaf1b4979627794acb909c"),
        "bootstrap_seed": 20_260_724_141,
    },
    "ETH-USDT": {
        "artifact_id": 8_586_463_176,
        "artifact_zip_sha256": ("fa13b5333b4bdfae02fc653351ea25f203e953315dd70d318cb47a82341c528d"),
        "artifact_manifest_sha256": (
            "95d9535f9e4badd736844f3a31e8d43e067032e32b44e406affa0932dc190aa8"
        ),
        "snapshot_filename": "okx-ETH-USDT-1H.csv",
        "snapshot_sha256": ("37f33ce7a55786a10f4c8e0f7ff1c870f331792b6ba1712229008480498ea236"),
        "bootstrap_seed": 20_260_724_142,
    },
}

BENCHMARK_COLUMNS = {
    "buy_and_hold": "benchmark_buy_and_hold_return",
    "volatility_targeted_long": "benchmark_volatility_targeted_long_return",
    "simple_trend_long_cash": "benchmark_simple_trend_long_cash_return",
}

NEIGHBOURHOOD: dict[str, dict[str, float | int]] = {
    "shallower_entry": {"entry_z": -1.25},
    "deeper_entry": {"entry_z": -1.75},
    "shorter_timeout": {"maximum_holding_hours": 36},
    "longer_timeout": {"maximum_holding_hours": 60},
}


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_artifact_manifest(root: str | Path, expected_sha256: str) -> dict[str, str]:
    artifact_root = Path(root)
    manifest = artifact_root / "artifact-manifest.sha256"
    observed_manifest_sha256 = file_sha256(manifest)
    if observed_manifest_sha256 != expected_sha256:
        raise ValueError(
            "artifact manifest SHA-256 mismatch: "
            f"expected {expected_sha256}, observed {observed_manifest_sha256}"
        )

    records: dict[str, str] = {}
    previous_path: str | None = None
    for line_number, raw_line in enumerate(
        manifest.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not raw_line:
            raise ValueError(f"artifact manifest line {line_number} is empty")
        try:
            digest, relative_path = raw_line.split("  ", maxsplit=1)
        except ValueError as exc:
            raise ValueError(f"artifact manifest line {line_number} is malformed") from exc
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError(f"artifact manifest line {line_number} has an invalid digest")
        parsed_path = PurePosixPath(relative_path)
        if (
            parsed_path.is_absolute()
            or ".." in parsed_path.parts
            or relative_path != str(parsed_path)
        ):
            raise ValueError(f"artifact manifest line {line_number} has an unsafe path")
        if relative_path in records:
            raise ValueError(f"artifact manifest line {line_number} duplicates {relative_path}")
        if previous_path is not None and relative_path <= previous_path:
            raise ValueError("artifact manifest paths must be strictly sorted")
        target = artifact_root.joinpath(*parsed_path.parts)
        if target.is_symlink() or not target.is_file():
            raise ValueError(f"artifact manifest target is unavailable: {relative_path}")
        observed = file_sha256(target)
        if observed != digest:
            raise ValueError(
                f"artifact file SHA-256 mismatch for {relative_path}: "
                f"expected {digest}, observed {observed}"
            )
        records[relative_path] = digest
        previous_path = relative_path
    if not records:
        raise ValueError("artifact manifest cannot be empty")
    return records


def _validated_hourly_index(values: pd.Series) -> pd.DatetimeIndex:
    raw = values.astype("string")
    explicit_zone = raw.str.contains(r"(?:Z|[+-]\d{2}:?\d{2})$", regex=True, na=False)
    if not bool(explicit_zone.all()):
        raise ValueError("timestamps must include an explicit timezone offset")
    timestamps = pd.DatetimeIndex(pd.to_datetime(raw, utc=True, errors="raise"))
    if timestamps.duplicated().any() or not timestamps.is_monotonic_increasing:
        raise ValueError("timestamps must be unique and strictly increasing")
    if len(timestamps) > 1:
        intervals = timestamps[1:] - timestamps[:-1]
        if not bool((intervals == pd.Timedelta(hours=1)).all()):
            raise ValueError("timestamps must have exact hourly cadence")
    return timestamps


def load_snapshot(path: str | Path) -> pd.DataFrame:
    snapshot = pd.read_csv(path)
    required = {"timestamp", "open", "high", "low", "close", "volume_quote", "confirm"}
    missing = required - set(snapshot.columns)
    if missing:
        raise ValueError(f"snapshot is missing columns: {sorted(missing)}")
    snapshot.index = _validated_hourly_index(snapshot["timestamp"])
    snapshot = snapshot.drop(columns="timestamp")
    numeric_columns = ["open", "high", "low", "close", "volume_quote"]
    numeric = snapshot[numeric_columns].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any() or not np.isfinite(numeric.to_numpy()).all():
        raise ValueError("snapshot numeric columns must be finite")
    if (numeric[["open", "high", "low", "close"]] <= 0.0).any().any():
        raise ValueError("snapshot prices must be positive")
    if (numeric["volume_quote"] < 0.0).any():
        raise ValueError("snapshot quote volume must be non-negative")
    if not bool(pd.to_numeric(snapshot["confirm"], errors="coerce").eq(1).all()):
        raise ValueError("snapshot must contain only completed candles")
    snapshot[numeric_columns] = numeric
    return snapshot


def load_market_artifact(
    root: str | Path,
    market: str,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    if market not in MARKETS:
        raise ValueError(f"unsupported market: {market}")
    details = MARKETS[market]
    artifact_root = Path(root)
    manifest_records = verify_artifact_manifest(
        artifact_root,
        str(details["artifact_manifest_sha256"]),
    )
    snapshot_relative = f"snapshot/{details['snapshot_filename']}"
    if manifest_records.get(snapshot_relative) != details["snapshot_sha256"]:
        raise ValueError(f"artifact manifest does not bind the expected {market} snapshot")
    snapshot_path = artifact_root / snapshot_relative
    if file_sha256(snapshot_path) != details["snapshot_sha256"]:
        raise ValueError(f"{market} snapshot SHA-256 mismatch")

    effective = json.loads((artifact_root / "effective_config.json").read_text(encoding="utf-8"))
    report = json.loads((artifact_root / "walk_forward.json").read_text(encoding="utf-8"))
    if effective["data"]["bar"] != "1H":
        raise ValueError("effective artifact bar must be 1H")
    if float(effective["strategy"]["transaction_cost_bps"]) != TRANSACTION_COST_BPS:
        raise ValueError("effective artifact transaction cost must be exactly 5 bps")
    if effective["robustness"]["cost_multipliers"] != [1.0]:
        raise ValueError("effective artifact must persist only the 1x cost profile")
    if float(report["settings"]["base_config"]["transaction_cost_bps"]) != TRANSACTION_COST_BPS:
        raise ValueError("walk-forward report transaction cost must be exactly 5 bps")
    if report["settings"]["cost_multipliers"] != [1.0]:
        raise ValueError("walk-forward report must persist only the 1x cost profile")
    if set(report["cost_stress_metrics"]) != {"1x"}:
        raise ValueError("walk-forward report must contain only the selected 1x path")

    snapshot = load_snapshot(snapshot_path)
    returns = pd.read_csv(artifact_root / "walk_forward_returns.csv")
    required_returns = {"timestamp", *BENCHMARK_COLUMNS.values()}
    missing_returns = required_returns - set(returns.columns)
    if missing_returns:
        raise ValueError(f"walk-forward returns are missing columns: {sorted(missing_returns)}")
    returns.index = _validated_hourly_index(returns["timestamp"])
    returns = returns.drop(columns="timestamp")
    for column in BENCHMARK_COLUMNS.values():
        returns[column] = pd.to_numeric(returns[column], errors="coerce")
    benchmark_values = returns[list(BENCHMARK_COLUMNS.values())].to_numpy(dtype=float)
    if not np.isfinite(benchmark_values).all() or np.any(benchmark_values <= -1.0):
        raise ValueError("benchmark returns must be finite and solvent")
    if returns.index[0] != EVALUATION_START or returns.index[-1] != EVALUATION_END:
        raise ValueError("walk-forward benchmark evaluation bounds do not match predeclaration")
    if len(returns) != 25_920:
        raise ValueError("walk-forward benchmark must contain exactly 25,920 OOS observations")

    return (
        snapshot,
        returns,
        {
            "artifact_id": int(details["artifact_id"]),
            "artifact_zip_sha256": str(details["artifact_zip_sha256"]),
            "artifact_manifest_sha256": str(details["artifact_manifest_sha256"]),
            "snapshot_sha256": str(details["snapshot_sha256"]),
            "manifest_entries": len(manifest_records),
            "source_start": snapshot.index[0].isoformat(),
            "source_end": snapshot.index[-1].isoformat(),
            "source_observations": len(snapshot),
        },
    )


def build_pullback_frame(
    snapshot: pd.DataFrame,
    *,
    entry_z: float = ENTRY_Z,
    exit_z: float = EXIT_Z,
    maximum_holding_hours: int = MAXIMUM_HOLDING_HOURS,
) -> pd.DataFrame:
    if not math.isfinite(entry_z) or not math.isfinite(exit_z) or entry_z >= exit_z:
        raise ValueError("entry_z and exit_z must be finite with entry_z below exit_z")
    if maximum_holding_hours < 1:
        raise ValueError("maximum_holding_hours must be positive")

    close = snapshot["close"].astype(float)
    log_close = np.log(close)
    log_returns = log_close.diff()
    rolling_mean = log_close.rolling(
        ZSCORE_LOOKBACK,
        min_periods=ZSCORE_LOOKBACK,
    ).mean()
    rolling_std = log_close.rolling(
        ZSCORE_LOOKBACK,
        min_periods=ZSCORE_LOOKBACK,
    ).std(ddof=0)
    pullback_z = (log_close - rolling_mean) / rolling_std.replace(0.0, np.nan)
    regime_return = close.pct_change(REGIME_LOOKBACK)
    realized_volatility = log_returns.rolling(
        VOLATILITY_LOOKBACK,
        min_periods=VOLATILITY_LOOKBACK,
    ).std(ddof=0) * math.sqrt(ANNUALIZATION)

    target_values = np.zeros(len(snapshot), dtype=float)
    episode_size = 0.0
    episode_age = 0
    z_values = pullback_z.to_numpy(dtype=float)
    regime_values = regime_return.to_numpy(dtype=float)
    volatility_values = realized_volatility.to_numpy(dtype=float)
    for row in range(len(snapshot)):
        if episode_size <= POSITION_EPSILON:
            if (
                math.isfinite(regime_values[row])
                and math.isfinite(z_values[row])
                and math.isfinite(volatility_values[row])
                and regime_values[row] > 0.0
                and z_values[row] <= entry_z
                and volatility_values[row] > 0.0
            ):
                episode_size = min(
                    MAX_POSITION,
                    TARGET_VOLATILITY / volatility_values[row],
                )
                episode_age = 0
        else:
            episode_age += 1
            if (
                not math.isfinite(regime_values[row])
                or not math.isfinite(z_values[row])
                or regime_values[row] <= 0.0
                or z_values[row] >= exit_z
                or episode_age >= maximum_holding_hours
            ):
                episode_size = 0.0
                episode_age = 0
        target_values[row] = episode_size

    target_position = pd.Series(
        target_values,
        index=snapshot.index,
        name="target_position",
    )
    position = target_position.shift(1).fillna(0.0).rename("position")
    asset_return = close.pct_change().fillna(0.0).rename("asset_return")
    turnover = position.diff().abs().fillna(position.abs()).rename("turnover")
    gross_return = (position * asset_return).rename("gross_strategy_return")
    trading_cost = (turnover * TRANSACTION_COST_BPS / 10_000.0).rename("trading_cost")
    strategy_return = (gross_return - trading_cost).rename("strategy_return")
    frame = pd.concat(
        [
            close.rename("close"),
            asset_return,
            target_position,
            position,
            turnover,
            gross_return,
            trading_cost,
            strategy_return,
        ],
        axis=1,
    )
    frame["nav"] = (1.0 + frame["strategy_return"]).cumprod()
    return frame


def max_drawdown(returns: Sequence[float]) -> float:
    values = np.asarray(returns, dtype=float)
    nav = np.concatenate(([1.0], np.cumprod(1.0 + values)))
    running_peak = np.maximum.accumulate(nav)
    return float(np.min(nav / running_peak - 1.0))


def metrics_from_returns(returns: Sequence[float]) -> dict[str, float]:
    values = np.asarray(returns, dtype=float)
    observations = len(values)
    years = observations / ANNUALIZATION
    growth = float(np.prod(1.0 + values))
    cagr = growth ** (1.0 / years) - 1.0 if growth > 0.0 else -1.0
    mean_return = float(np.mean(values))
    return_std = float(np.std(values, ddof=0))
    sharpe = mean_return / return_std * math.sqrt(ANNUALIZATION) if return_std > 0.0 else 0.0
    drawdown = max_drawdown(values)
    calmar = cagr / abs(drawdown) if drawdown < 0.0 else 0.0
    return {
        "net_total_return": growth - 1.0,
        "cagr": cagr,
        "sharpe": sharpe,
        "max_drawdown": drawdown,
        "calmar": calmar,
    }


def performance_metrics(frame: pd.DataFrame) -> dict[str, float | int]:
    returns = frame["strategy_return"].to_numpy(dtype=float)
    if len(returns) == 0 or not np.isfinite(returns).all() or np.any(returns <= -1.0):
        raise ValueError("strategy returns must be finite, solvent, and non-empty")
    base = metrics_from_returns(returns)
    mean_return = float(np.mean(returns))
    return_std = float(np.std(returns, ddof=0))
    downside = float(np.sqrt(np.mean(np.square(np.minimum(returns, 0.0)))))
    gross_returns = frame["gross_strategy_return"].to_numpy(dtype=float)
    return {
        **base,
        "observations": len(returns),
        "gross_total_return": float(np.prod(1.0 + gross_returns) - 1.0),
        "annualized_arithmetic_mean": mean_return * ANNUALIZATION,
        "annualized_volatility": return_std * math.sqrt(ANNUALIZATION),
        "sortino": (mean_return / downside * math.sqrt(ANNUALIZATION) if downside > 0.0 else 0.0),
        "annualized_turnover": float(frame["turnover"].mean()) * ANNUALIZATION,
        "turnover_sum": float(frame["turnover"].sum()),
        "average_abs_exposure": float(frame["position"].abs().mean()),
        "exchange_fee_sum": float(frame["trading_cost"].sum()),
    }


def fold_stability(frame: pd.DataFrame) -> dict[str, Any]:
    fold_returns = [
        float(np.prod(1.0 + frame["strategy_return"].iloc[start : start + TEST_BARS]) - 1.0)
        for start in range(0, len(frame), TEST_BARS)
    ]
    positive = [value for value in fold_returns if value > 0.0]
    positive_total = sum(positive)
    maximum_share = max(positive) / positive_total if positive_total > 0.0 else 1.0
    return {
        "fold_count": len(fold_returns),
        "profitable_folds": len(positive),
        "minimum_profitable_folds": 7,
        "positive_fold_ratio": len(positive) / len(fold_returns),
        "best_fold_total_return": max(fold_returns),
        "worst_fold_total_return": min(fold_returns),
        "max_positive_fold_share": maximum_share,
        "maximum_allowed_positive_fold_share": 0.50,
        "fold_returns": fold_returns,
        "passes": len(positive) >= 7 and maximum_share <= 0.50,
    }


def calendar_stability(
    frame: pd.DataFrame,
    frequency: str,
    required_profitable: int,
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    periods = frame.index.tz_convert(None).to_period(frequency)
    for period in periods.unique():
        subset = frame.loc[periods == period]
        start = period.start_time.tz_localize("UTC")
        end = period.end_time.floor("h").tz_localize("UTC")
        expected = int((end - start) / pd.Timedelta(hours=1)) + 1
        complete = len(subset) == expected and subset.index[0] == start and subset.index[-1] == end
        records.append(
            {
                "period": str(period),
                "observations": len(subset),
                "expected_observations": expected,
                "complete": complete,
                "total_return": float(np.prod(1.0 + subset["strategy_return"].to_numpy()) - 1.0),
            }
        )
    complete_records = [record for record in records if bool(record["complete"])]
    profitable = [record for record in complete_records if float(record["total_return"]) > 0.0]
    return {
        "records": records,
        "complete_periods": len(complete_records),
        "profitable_complete_periods": len(profitable),
        "required_profitable_complete_periods": required_profitable,
        "passes": (
            len(complete_records) >= required_profitable and len(profitable) >= required_profitable
        ),
    }


def activity_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    position = frame["position"].to_numpy(dtype=float)
    active = position > POSITION_EPSILON
    starts = np.flatnonzero(active & ~np.concatenate(([False], active[:-1])))
    ends = np.flatnonzero(~active & np.concatenate(([False], active[:-1])))
    durations: list[int] = []
    episode_returns: list[float] = []
    for start in starts:
        later_ends = ends[ends > start]
        if len(later_ends):
            end = int(later_ends[0])
            durations.append(end - int(start))
            episode_returns.append(
                float(
                    np.prod(1.0 + frame["strategy_return"].iloc[int(start) : end + 1].to_numpy())
                    - 1.0
                )
            )
    positive_total = sum(value for value in episode_returns if value > 0.0)
    negative_total = -sum(value for value in episode_returns if value < 0.0)
    profit_factor = (
        positive_total / negative_total
        if negative_total > 0.0
        else (math.inf if positive_total > 0.0 else 0.0)
    )
    years = len(frame) / ANNUALIZATION
    episodes_per_year = len(durations) / years
    median_holding = float(np.median(durations)) if durations else 0.0
    annualized_turnover = float(frame["turnover"].mean()) * ANNUALIZATION
    return {
        "exposure_episodes": len(starts),
        "completed_exposure_episodes": len(durations),
        "episodes_per_year": episodes_per_year,
        "median_holding_hours": median_holding,
        "maximum_holding_hours": max(durations) if durations else 0,
        "completed_episode_profit_factor": profit_factor,
        "completed_episode_win_rate": (
            sum(value > 0.0 for value in episode_returns) / len(episode_returns)
            if episode_returns
            else 0.0
        ),
        "annualized_turnover": annualized_turnover,
        "passes": (
            12.0 <= annualized_turnover <= 150.0
            and episodes_per_year >= 24.0
            and 4.0 <= median_holding <= 48.0
            and profit_factor > 1.0
        ),
    }


def expected_shortfall(returns: Sequence[float]) -> float:
    values = np.sort(np.asarray(returns, dtype=float))
    tail_count = math.ceil(len(values) * TAIL_FRACTION)
    return float(np.mean(values[:tail_count]))


def capacity_metrics(snapshot: pd.DataFrame, frame: pd.DataFrame) -> dict[str, Any]:
    lagged_liquidity = (
        snapshot["volume_quote"]
        .rolling(
            CAPACITY_LIQUIDITY_LOOKBACK,
            min_periods=CAPACITY_LIQUIDITY_LOOKBACK,
        )
        .median()
        .shift(1)
        .reindex(frame.index)
        .to_numpy(dtype=float)
    )
    returns = frame["strategy_return"].to_numpy(dtype=float)
    prior_nav = np.concatenate(([1.0], np.cumprod(1.0 + returns)[:-1]))
    turnover = frame["turnover"].to_numpy(dtype=float)
    adjustment = turnover > POSITION_EPSILON
    trade_notional = CAPACITY_INITIAL_USD * prior_nav * turnover
    participation = np.divide(
        trade_notional,
        lagged_liquidity,
        out=np.full(len(frame), np.nan),
        where=lagged_liquidity > 0.0,
    )
    supported_capital = np.divide(
        CAPACITY_PARTICIPATION_LIMIT * lagged_liquidity,
        prior_nav * turnover,
        out=np.full(len(frame), np.nan),
        where=(prior_nav * turnover) > 0.0,
    )
    breach = adjustment & (participation > CAPACITY_PARTICIPATION_LIMIT)
    return {
        "initial_capital_usd": CAPACITY_INITIAL_USD,
        "participation_limit": CAPACITY_PARTICIPATION_LIMIT,
        "lagged_liquidity_lookback_hours": CAPACITY_LIQUIDITY_LOOKBACK,
        "adjustment_observations": int(adjustment.sum()),
        "breach_observations": int(breach.sum()),
        "breach_share": float(breach.sum() / max(1, adjustment.sum())),
        "maximum_participation": float(np.nanmax(participation[adjustment])),
        "maximum_supported_initial_capital_usd": float(np.nanmin(supported_capital[adjustment])),
        "passes": int(breach.sum()) == 0,
    }


def paired_bootstrap(
    candidate_returns: np.ndarray,
    benchmark_returns: pd.DataFrame,
    *,
    seed: int,
) -> dict[str, Any]:
    observations = len(candidate_returns)
    starts_available = observations - BLOCK_LENGTH + 1
    blocks_required = math.ceil(observations / BLOCK_LENGTH)
    rng = np.random.default_rng(seed)
    observed_candidate = metrics_from_returns(candidate_returns)
    distributions = {benchmark: {"sharpe": [], "calmar": []} for benchmark in BENCHMARK_COLUMNS}
    observed_deltas: dict[str, dict[str, float]] = {}
    for benchmark, column in BENCHMARK_COLUMNS.items():
        benchmark_metrics = metrics_from_returns(benchmark_returns[column].to_numpy(dtype=float))
        observed_deltas[benchmark] = {
            metric: observed_candidate[metric] - benchmark_metrics[metric]
            for metric in ("sharpe", "calmar")
        }

    for _ in range(BOOTSTRAP_RESAMPLES):
        block_starts = rng.integers(0, starts_available, size=blocks_required)
        indices = np.concatenate(
            [np.arange(start, start + BLOCK_LENGTH) for start in block_starts]
        )[:observations]
        candidate_metrics = metrics_from_returns(candidate_returns[indices])
        for benchmark, column in BENCHMARK_COLUMNS.items():
            benchmark_metrics = metrics_from_returns(
                benchmark_returns[column].to_numpy(dtype=float)[indices]
            )
            for metric in ("sharpe", "calmar"):
                distributions[benchmark][metric].append(
                    candidate_metrics[metric] - benchmark_metrics[metric]
                )

    alpha = 1.0 - CONFIDENCE
    result: dict[str, Any] = {}
    for benchmark in BENCHMARK_COLUMNS:
        result[benchmark] = {}
        for metric in ("sharpe", "calmar"):
            values = np.asarray(distributions[benchmark][metric], dtype=float)
            result[benchmark][metric] = {
                "point_delta": observed_deltas[benchmark][metric],
                "lower": float(np.quantile(values, alpha / 2.0)),
                "upper": float(np.quantile(values, 1.0 - alpha / 2.0)),
                "probability_positive": float(np.mean(values > 0.0)),
            }
    result["passes"] = all(
        float(result[benchmark][metric]["lower"]) > 0.0
        for benchmark in BENCHMARK_COLUMNS
        for metric in ("sharpe", "calmar")
    )
    return result


def evaluate_market(root: str | Path, market: str) -> dict[str, Any]:
    snapshot, benchmark_returns, provenance = load_market_artifact(root, market)
    frame = build_pullback_frame(snapshot).loc[EVALUATION_START:EVALUATION_END].copy()
    if not frame.index.equals(benchmark_returns.index):
        raise ValueError(f"{market} candidate and benchmark timestamps do not align")

    metrics = performance_metrics(frame)
    folds = fold_stability(frame)
    months = calendar_stability(frame, "M", 18)
    years = calendar_stability(frame, "Y", 2)
    activity = activity_metrics(frame)
    capacity = capacity_metrics(snapshot, frame)
    bootstrap = paired_bootstrap(
        frame["strategy_return"].to_numpy(dtype=float),
        benchmark_returns,
        seed=int(MARKETS[market]["bootstrap_seed"]),
    )

    benchmark_metrics = {
        benchmark: metrics_from_returns(benchmark_returns[column].to_numpy(dtype=float))
        for benchmark, column in BENCHMARK_COLUMNS.items()
    }
    benchmark_tail = {
        benchmark: expected_shortfall(benchmark_returns[column].to_numpy(dtype=float))
        for benchmark, column in BENCHMARK_COLUMNS.items()
    }
    candidate_tail = expected_shortfall(frame["strategy_return"].to_numpy(dtype=float))

    neighbourhood: dict[str, Any] = {}
    for name, parameters in NEIGHBOURHOOD.items():
        variant = build_pullback_frame(snapshot, **parameters).loc[EVALUATION_START:EVALUATION_END]
        neighbourhood[name] = performance_metrics(variant)
    neighbourhood_passes = all(
        float(details["net_total_return"]) > 0.0 and float(details["sharpe"]) > 0.50
        for details in neighbourhood.values()
    )

    retrospective_gates = {
        "source_and_exact_5bps": True,
        "net_viability": (
            float(metrics["net_total_return"]) > 0.0 and float(metrics["sharpe"]) > 0.0
        ),
        "benchmark_relative_sharpe_and_calmar": bool(bootstrap["passes"]),
        "fold_stability": bool(folds["passes"]),
        "month_stability": bool(months["passes"]),
        "year_stability": bool(years["passes"]),
        "activity": bool(activity["passes"]),
        "parameter_neighbourhood": neighbourhood_passes,
        "tail_risk": candidate_tail > benchmark_tail["volatility_targeted_long"],
        "capacity": bool(capacity["passes"]),
    }
    return {
        "market": market,
        "provenance": provenance,
        "metrics": metrics,
        "benchmark_metrics": benchmark_metrics,
        "benchmark_bootstrap": bootstrap,
        "fold_stability": folds,
        "month_stability": months,
        "year_stability": years,
        "activity": activity,
        "neighbourhood": {
            "variants": neighbourhood,
            "passes": neighbourhood_passes,
        },
        "tail_risk": {
            "tail_fraction": TAIL_FRACTION,
            "strategy_expected_shortfall": candidate_tail,
            "benchmark_expected_shortfall": benchmark_tail,
            "passes": retrospective_gates["tail_risk"],
        },
        "capacity": capacity,
        "retrospective_gates": retrospective_gates,
        "retrospective_passes": all(retrospective_gates.values()),
    }


def build_result(btc_root: str | Path, eth_root: str | Path) -> dict[str, Any]:
    markets = {
        "BTC-USDT": evaluate_market(btc_root, "BTC-USDT"),
        "ETH-USDT": evaluate_market(eth_root, "ETH-USDT"),
    }
    joint_retrospective = all(bool(details["retrospective_passes"]) for details in markets.values())
    prospective_diagnostics = {
        "maker_fill_quality": "blocked_no_prospective_attempts",
        "no_fill_rate": "blocked_no_prospective_attempts",
        "partial_fill_rate": "blocked_no_prospective_attempts",
        "timeout_rate": "blocked_no_prospective_attempts",
        "adverse_selection": "blocked_no_prospective_attempts",
        "latency": "blocked_no_prospective_attempts",
        "prospective_paper_performance": "blocked_no_prospective_attempts",
    }
    return {
        "canonical_signature": CANONICAL_SIGNATURE,
        "hypothesis": (
            "A fixed 1H regime-conditioned pullback-recovery architecture clears every "
            "retrospective architecture-freeze gate in BTC-USDT and ETH-USDT at exactly "
            "5 bps one-way and is eligible for prospective post-only paper evaluation."
        ),
        "candidate_accounting": {
            "architecture_candidates_searched": 1,
            "architecture_candidates_passed": int(joint_retrospective),
            "architecture_candidates_rejected": int(not joint_retrospective),
            "parameter_neighbourhood_paths": len(NEIGHBOURHOOD),
            "bootstrap_resamples_per_market": BOOTSTRAP_RESAMPLES,
        },
        "fixed_architecture": {
            "regime_lookback_hours": REGIME_LOOKBACK,
            "zscore_lookback_hours": ZSCORE_LOOKBACK,
            "entry_z": ENTRY_Z,
            "exit_z": EXIT_Z,
            "maximum_holding_hours": MAXIMUM_HOLDING_HOURS,
            "volatility_lookback_hours": VOLATILITY_LOOKBACK,
            "target_annualized_volatility": TARGET_VOLATILITY,
            "episode_size": "frozen_at_entry",
            "maximum_position": MAX_POSITION,
            "execution_delay_bars": 1,
            "transaction_cost_bps_one_way": TRANSACTION_COST_BPS,
            "modeled_cost_paths": ["5bps_one_way_only"],
        },
        "evaluation": {
            "bar": "1H",
            "annualization": ANNUALIZATION,
            "start": EVALUATION_START.isoformat(),
            "end": EVALUATION_END.isoformat(),
            "observations_per_market": 25_920,
            "fold_bars": TEST_BARS,
            "bootstrap_block_hours": BLOCK_LENGTH,
            "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
            "confidence": CONFIDENCE,
        },
        "markets": markets,
        "joint_retrospective_passes": joint_retrospective,
        "prospective_execution_diagnostics": prospective_diagnostics,
        "paper_testable": joint_retrospective,
        "live_eligible": False,
        "verdict": "supported" if joint_retrospective else "rejected",
        "rejection_reasons": [
            f"{market}:{gate}"
            for market, details in markets.items()
            for gate, passes in details["retrospective_gates"].items()
            if not passes
        ]
        + ["prospective maker fill and paper-performance evidence is absent"],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--btc-artifact-dir", required=True)
    parser.add_argument("--eth-artifact-dir", required=True)
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args(argv)
    result = build_result(arguments.btc_artifact_dir, arguments.eth_artifact_dir)
    output = Path(arguments.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
