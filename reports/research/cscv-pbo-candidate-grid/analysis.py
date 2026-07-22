from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ANNUALIZATION = 365
MOMENTUM_LOOKBACKS = (30, 90, 180)
REVERSAL_LOOKBACKS = (2, 5, 10)
TREND_WEIGHTS = (0.55, 0.70, 0.85)
VOLATILITY_LOOKBACK = 30
TARGET_VOLATILITY = 0.50
MAX_POSITION = 1.0
MIN_POSITION = 0.0
TRANSACTION_COST_BPS = 10.0
SELECTION_BARS = 730
TEST_BARS = 90
EXPECTED_OBSERVATIONS = 2340
SUBSAMPLES = 12
SUBSAMPLE_LENGTH = EXPECTED_OBSERVATIONS // SUBSAMPLES
PBO_LIMIT = 0.05
SOURCE_WORKFLOW_RUN_ID = 29913443745
SOURCE_ARTIFACT_ID = 8526866832
SOURCE_ARTIFACT_NAME = "quant-research-source-917-attempt-1"
SOURCE_ARTIFACT_SHA256 = "ac6a8811a3d26fc38b954c7e779c0aacb0f0feafb78afaee712a8a2fd64908cb"
SOURCE_HEAD_COMMIT = "1a37205e935f4d1d2544a96c11430b7d05f31295"
SOURCE_BASE_COMMIT = "ba16b693ff4e2812f2f8b89f519a38f564868cbd"
EVALUATION_START = pd.Timestamp("2020-01-11T00:00:00Z")
EVALUATION_END = pd.Timestamp("2026-06-07T00:00:00Z")
MARKETS = {
    "BTC-USDT": {
        "snapshot_sha256": "b0bd7c6c7e30fcc095073169f60bde24559f481b24cc6f4bdfb85349f57974bb",
        "returns_sha256": "539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73",
        "report_sha256": "042652a17ab23b6f2156696225a23595a17e5dce9bef7c0be1b7902e5a208d4f",
    },
    "ETH-USDT": {
        "snapshot_sha256": "78f3bf81d3983e6c894066a1c298fbf14ae06a5eff9ca7326554b0a8933c0df5",
        "returns_sha256": "027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6",
        "report_sha256": "721e7bbdb389c61bf8643e004b2521fff04f80afb3281508d35a65a2f764b5c2",
    },
}
SIGNATURE = (
    "cscv-pbo-selection-score-v1|markets=BTC-USDT,ETH-USDT|"
    "source=immutable-OKX-1Dutc-snapshots|candidate-grid=3x3x3-27|"
    "candidate-path=fixed-parameter-one-bar-delayed-10bps-long-cash|"
    "evaluation=2020-01-11..2026-06-07-2340-bars|subsamples=12x195-contiguous|"
    "splits=choose(12,6)=924|is-selection=repository-score|"
    "oos-ranking=repository-score-average-tie-rank|"
    "omega=ascending-oos-rank/(27+1)|lambda=log(omega/(1-omega))|"
    "pbo=share(lambda<=0)|pass=pbo<=0.05-for-both-markets|candidate_count=1"
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _explicit_daily_utc_index(values: pd.Series, *, label: str) -> pd.DatetimeIndex:
    parsed: list[pd.Timestamp] = []
    for value in values:
        timestamp = pd.Timestamp(value)
        if pd.isna(timestamp) or timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError(f"{label} timestamps must contain explicit timezone information")
        parsed.append(timestamp)
    index = pd.DatetimeIndex(pd.to_datetime(parsed, utc=True))
    if index.has_duplicates or not index.is_monotonic_increasing:
        raise ValueError(f"{label} timestamps must be unique and strictly increasing")
    if len(index) > 1 and not bool(
        ((index[1:] - index[:-1]) == pd.Timedelta(days=1)).all()
    ):
        raise ValueError(f"{label} timestamps must have exact daily cadence")
    return index


def _candidate_key(momentum: int, reversal: int, trend_weight: float) -> str:
    return f"m={momentum}|r={reversal}|trend={trend_weight:.2f}"


def candidate_grid() -> list[tuple[int, int, float]]:
    return list(itertools.product(MOMENTUM_LOOKBACKS, REVERSAL_LOOKBACKS, TREND_WEIGHTS))


def _target_position(
    prices: pd.Series,
    *,
    momentum: int,
    reversal: int,
    trend_weight: float,
) -> pd.Series:
    log_returns = np.log(prices).diff()
    trend_mean = log_returns.rolling(momentum, min_periods=momentum).mean()
    trend_std = log_returns.rolling(momentum, min_periods=momentum).std(ddof=0)
    trend_score = trend_mean / trend_std.replace(0.0, np.nan) * math.sqrt(momentum)
    recent_return = log_returns.rolling(reversal, min_periods=reversal).sum()
    risk_scale = log_returns.rolling(
        VOLATILITY_LOOKBACK,
        min_periods=VOLATILITY_LOOKBACK,
    ).std(ddof=0)
    reversal_score = -recent_return / (
        risk_scale.replace(0.0, np.nan) * math.sqrt(reversal)
    )
    ensemble = (
        trend_weight * trend_score + (1.0 - trend_weight) * reversal_score
    ).clip(-4.0, 4.0)
    directional = pd.Series(np.tanh(ensemble.to_numpy()), index=ensemble.index)
    realized_volatility = risk_scale * math.sqrt(ANNUALIZATION)
    volatility_scalar = (TARGET_VOLATILITY / realized_volatility.replace(0.0, np.nan)).clip(
        lower=0.0,
        upper=MAX_POSITION,
    )
    return (
        (directional * volatility_scalar)
        .clip(MIN_POSITION, MAX_POSITION)
        .replace([np.inf, -np.inf], np.nan)
        .fillna(0.0)
        .rename("target_position")
    )


def build_candidate_frame(
    prices: pd.Series,
    *,
    momentum: int,
    reversal: int,
    trend_weight: float,
) -> pd.DataFrame:
    target = _target_position(
        prices,
        momentum=momentum,
        reversal=reversal,
        trend_weight=trend_weight,
    )
    position = target.shift(1).fillna(0.0).rename("position")
    asset_return = prices.pct_change().fillna(0.0).rename("asset_return")
    turnover = position.diff().abs().fillna(position.abs()).rename("turnover")
    trading_cost = (turnover * TRANSACTION_COST_BPS / 10_000.0).rename("trading_cost")
    strategy_return = (position * asset_return - trading_cost).rename("strategy_return")
    return pd.concat(
        [position, turnover, trading_cost, strategy_return],
        axis=1,
    )


def _max_drawdown(returns: np.ndarray) -> float:
    nav = np.concatenate(([1.0], np.cumprod(1.0 + returns)))
    running_peak = np.maximum.accumulate(nav)
    return float(np.min(nav / running_peak - 1.0))


def selection_score(frame: pd.DataFrame) -> float:
    returns = pd.to_numeric(frame["strategy_return"], errors="raise").to_numpy(dtype=float)
    turnover = pd.to_numeric(frame["turnover"], errors="raise").to_numpy(dtype=float)
    if len(returns) == 0 or not np.isfinite(returns).all() or not np.isfinite(turnover).all():
        raise ValueError("candidate score inputs must be finite and non-empty")
    growth = float(np.prod(1.0 + returns))
    years = len(returns) / ANNUALIZATION
    cagr = growth ** (1.0 / years) - 1.0 if growth > 0.0 else -1.0
    standard_deviation = float(returns.std(ddof=0))
    sharpe = (
        float(returns.mean() / standard_deviation * math.sqrt(ANNUALIZATION))
        if standard_deviation > 0.0
        else 0.0
    )
    drawdown = _max_drawdown(returns)
    calmar = cagr / abs(drawdown) if drawdown < 0.0 else 0.0
    annualized_turnover = float(turnover.mean()) * ANNUALIZATION
    return sharpe + 0.20 * calmar - 0.50 * abs(drawdown) - 0.01 * annualized_turnover


def probability_of_backtest_overfitting(
    candidate_frames: dict[str, pd.DataFrame],
    *,
    subsamples: int,
) -> dict[str, Any]:
    if isinstance(subsamples, bool) or not isinstance(subsamples, int) or subsamples < 4:
        raise ValueError("subsamples must be an even integer of at least four")
    if subsamples % 2:
        raise ValueError("subsamples must be an even integer of at least four")
    if len(candidate_frames) < 2:
        raise ValueError("PBO requires at least two candidate paths")
    names = tuple(candidate_frames)
    first_index = candidate_frames[names[0]].index
    observations = len(first_index)
    if observations % subsamples:
        raise ValueError("observations must divide evenly into contiguous subsamples")
    required_columns = {"strategy_return", "turnover"}
    for name, frame in candidate_frames.items():
        if not required_columns <= set(frame):
            raise ValueError(f"{name} is missing PBO score columns")
        if not frame.index.equals(first_index):
            raise ValueError("candidate paths must have identical indexes")
    block_length = observations // subsamples
    block_ids = np.repeat(np.arange(subsamples), block_length)
    splits: list[dict[str, Any]] = []
    selection_counts: Counter[str] = Counter()
    for in_sample_blocks in itertools.combinations(range(subsamples), subsamples // 2):
        in_sample_mask = np.isin(block_ids, in_sample_blocks)
        in_sample_scores = np.asarray(
            [selection_score(candidate_frames[name].iloc[in_sample_mask]) for name in names]
        )
        out_of_sample_scores = np.asarray(
            [selection_score(candidate_frames[name].iloc[~in_sample_mask]) for name in names]
        )
        selected_index = int(np.argmax(in_sample_scores))
        selected_name = names[selected_index]
        selected_oos_score = float(out_of_sample_scores[selected_index])
        lower_count = int(np.sum(out_of_sample_scores < selected_oos_score))
        equal_count = int(np.sum(out_of_sample_scores == selected_oos_score))
        ascending_rank = 1.0 + lower_count + 0.5 * (equal_count - 1)
        omega = ascending_rank / (len(names) + 1.0)
        logit = math.log(omega / (1.0 - omega))
        selection_counts[selected_name] += 1
        splits.append(
            {
                "in_sample_blocks": list(in_sample_blocks),
                "selected_candidate": selected_name,
                "selected_in_sample_score": float(in_sample_scores[selected_index]),
                "selected_out_of_sample_score": selected_oos_score,
                "out_of_sample_ascending_rank": ascending_rank,
                "omega": omega,
                "logit": logit,
                "overfit": bool(logit <= 0.0),
            }
        )
    logits = np.asarray([split["logit"] for split in splits], dtype=float)
    ranks = np.asarray([split["out_of_sample_ascending_rank"] for split in splits], dtype=float)
    return {
        "observations": observations,
        "candidate_count": len(names),
        "subsamples": subsamples,
        "subsample_length": block_length,
        "cscv_splits": len(splits),
        "overfit_splits": int(np.sum(logits <= 0.0)),
        "non_overfit_splits": int(np.sum(logits > 0.0)),
        "pbo": float(np.mean(logits <= 0.0)),
        "median_logit": float(np.median(logits)),
        "mean_out_of_sample_rank": float(np.mean(ranks)),
        "median_out_of_sample_rank": float(np.median(ranks)),
        "minimum_out_of_sample_rank": float(np.min(ranks)),
        "maximum_out_of_sample_rank": float(np.max(ranks)),
        "selected_candidate_frequencies": {
            name: int(selection_counts.get(name, 0)) for name in names
        },
        "passes": bool(float(np.mean(logits <= 0.0)) <= PBO_LIMIT),
    }


def _load_market_inputs(
    artifact_dir: Path,
    market: str,
) -> tuple[pd.Series, dict[str, Any], pd.DataFrame]:
    evidence = MARKETS[market]
    market_dir = artifact_dir / market
    snapshot_path = market_dir / "snapshot" / f"okx-{market}-1Dutc.csv"
    report_path = market_dir / "walk_forward.json"
    returns_path = market_dir / "walk_forward_returns.csv"
    for path, expected in {
        snapshot_path: evidence["snapshot_sha256"],
        report_path: evidence["report_sha256"],
        returns_path: evidence["returns_sha256"],
    }.items():
        actual = file_sha256(path)
        if actual != expected:
            raise ValueError(f"{path.name} hash mismatch: expected {expected}, actual {actual}")
    snapshot = pd.read_csv(snapshot_path)
    if len(snapshot) != 3114:
        raise ValueError("snapshot observation count changed")
    snapshot_index = _explicit_daily_utc_index(snapshot["timestamp"], label="snapshot")
    closes = pd.to_numeric(snapshot["close"], errors="raise").to_numpy(dtype=float)
    confirms = pd.to_numeric(snapshot["confirm"], errors="raise").to_numpy(dtype=float)
    if not np.isfinite(closes).all() or (closes <= 0.0).any() or not np.equal(confirms, 1.0).all():
        raise ValueError("snapshot must contain positive closes and only confirmed rows")
    prices = pd.Series(closes, index=snapshot_index, name="close")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    settings = report.get("settings")
    if not isinstance(settings, dict):
        raise ValueError("walk-forward settings must be a mapping")
    expected_settings = {
        "candidate_count": 27,
        "selection_bars": SELECTION_BARS,
        "test_bars": TEST_BARS,
        "non_overlapping_test_folds": True,
    }
    for key, expected in expected_settings.items():
        if settings.get(key) != expected:
            raise ValueError(f"walk-forward setting {key} changed")
    base = settings.get("base_config")
    if not isinstance(base, dict) or base.get("annualization") != ANNUALIZATION:
        raise ValueError("walk-forward annualization changed")
    if base.get("transaction_cost_bps") != TRANSACTION_COST_BPS:
        raise ValueError("walk-forward transaction cost changed")
    persisted = pd.read_csv(returns_path)
    persisted.index = _explicit_daily_utc_index(persisted["timestamp"], label="return")
    if len(persisted) != EXPECTED_OBSERVATIONS:
        raise ValueError("walk-forward return observation count changed")
    if persisted.index[0] != EVALUATION_START or persisted.index[-1] != EVALUATION_END:
        raise ValueError("walk-forward evaluation boundary changed")
    return prices, report, persisted


def _validate_selected_path_reproduction(
    prices: pd.Series,
    report: dict[str, Any],
    persisted: pd.DataFrame,
) -> float:
    previous_position = 0.0
    reconstructed: list[pd.DataFrame] = []
    for fold in report["folds"]:
        parameters = fold["selected_parameters"]
        frame = build_candidate_frame(
            prices,
            momentum=int(parameters["momentum_lookback"]),
            reversal=int(parameters["reversal_lookback"]),
            trend_weight=float(parameters["trend_weight"]),
        ).loc[fold["test_start"] : fold["test_end"]].copy()
        first = frame.index[0]
        turnover = abs(float(frame.at[first, "position"]) - previous_position)
        frame.at[first, "turnover"] = turnover
        frame.at[first, "trading_cost"] = turnover * TRANSACTION_COST_BPS / 10_000.0
        frame.at[first, "strategy_return"] = (
            float(frame.at[first, "position"]) * float(prices.pct_change().at[first])
            - float(frame.at[first, "trading_cost"])
        )
        previous_position = float(frame["position"].iloc[-1])
        reconstructed.append(frame)
    combined = pd.concat(reconstructed)
    expected = pd.to_numeric(persisted["strategy_return"], errors="raise").to_numpy(dtype=float)
    actual = combined["strategy_return"].to_numpy(dtype=float)
    if not combined.index.equals(persisted.index):
        raise ValueError("reconstructed selected path index does not match persisted OOS returns")
    maximum_error = float(np.max(np.abs(actual - expected)))
    if maximum_error > 5e-15:
        raise ValueError(f"selected path reconstruction differs by {maximum_error}")
    return maximum_error


def build_result(artifact_dir: Path) -> dict[str, Any]:
    market_results: dict[str, Any] = {}
    grid = candidate_grid()
    for market in MARKETS:
        prices, report, persisted = _load_market_inputs(artifact_dir, market)
        reproduction_error = _validate_selected_path_reproduction(prices, report, persisted)
        frames: dict[str, pd.DataFrame] = {}
        for momentum, reversal, trend_weight in grid:
            key = _candidate_key(momentum, reversal, trend_weight)
            frame = build_candidate_frame(
                prices,
                momentum=momentum,
                reversal=reversal,
                trend_weight=trend_weight,
            ).loc[EVALUATION_START:EVALUATION_END]
            if len(frame) != EXPECTED_OBSERVATIONS:
                raise ValueError(f"{market} candidate path observation count changed")
            frames[key] = frame
        result = probability_of_backtest_overfitting(frames, subsamples=SUBSAMPLES)
        result["selected_path_reproduction_max_abs_error"] = reproduction_error
        market_results[market] = result
    passes = all(bool(result["passes"]) for result in market_results.values())
    return {
        "hypothesis": (
            "The declared 27-configuration BTC-USDT and ETH-USDT candidate grids each "
            "have a Probability of Backtest Overfitting no greater than 5% under "
            "12-subsample CSCV using the repository's exact selection score."
        ),
        "canonical_signature": SIGNATURE,
        "candidate_accounting": {
            "searched": 1,
            "passed": int(passes),
            "rejected": int(not passes),
            "grid_candidates_per_market": len(grid),
            "cscv_splits_per_market": math.comb(SUBSAMPLES, SUBSAMPLES // 2),
        },
        "verdict": "supported" if passes else "rejected",
        "failure_reason": (
            None
            if passes
            else "At least one development market has CSCV PBO above the predeclared 5% limit."
        ),
        "method": {
            "selection_score": (
                "Sharpe + 0.20*Calmar - 0.50*abs(max_drawdown) "
                "- 0.01*annualized_turnover"
            ),
            "annualization": ANNUALIZATION,
            "transaction_cost_bps": TRANSACTION_COST_BPS,
            "execution_delay_bars": 1,
            "candidate_grid": {
                "momentum_lookbacks": list(MOMENTUM_LOOKBACKS),
                "reversal_lookbacks": list(REVERSAL_LOOKBACKS),
                "trend_weights": list(TREND_WEIGHTS),
            },
            "subsamples": SUBSAMPLES,
            "subsample_length": SUBSAMPLE_LENGTH,
            "cscv_splits": math.comb(SUBSAMPLES, SUBSAMPLES // 2),
            "pbo_limit": PBO_LIMIT,
            "development_markets": True,
        },
        "provenance": {
            "provider": "OKX",
            "market_type": "spot",
            "timeframe": "1Dutc",
            "source_workflow_run_id": SOURCE_WORKFLOW_RUN_ID,
            "source_artifact_id": SOURCE_ARTIFACT_ID,
            "source_artifact_name": SOURCE_ARTIFACT_NAME,
            "source_artifact_sha256": SOURCE_ARTIFACT_SHA256,
            "source_head_commit": SOURCE_HEAD_COMMIT,
            "source_base_commit": SOURCE_BASE_COMMIT,
            "oos_observations_per_market": EXPECTED_OBSERVATIONS,
            "oos_start": EVALUATION_START.isoformat(),
            "oos_end": EVALUATION_END.isoformat(),
            "markets": MARKETS,
        },
        "markets": market_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run CSCV/PBO on the declared OKX candidate grid.")
    parser.add_argument("--artifact-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = build_result(args.artifact_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"verdict={result['verdict']}")
    for market, market_result in result["markets"].items():
        print(f"{market}_pbo={market_result['pbo']:.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
