from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

MARKETS = {
    "BTC-USDT": {
        "returns_sha256": "539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73",
        "report_sha256": "eadade3fd883744d6bf9edeb798a0c8ca2bd62b621d936c70717a4e38e11fd9a",
    },
    "ETH-USDT": {
        "returns_sha256": "027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6",
        "report_sha256": "b2bf91d7ed00e016931ffe4d892827d769a44fb0dae8af58bc1d6785a0207067",
    },
}
INITIAL_WEIGHTS = {"BTC-USDT": 0.5, "ETH-USDT": 0.5}
BLOCK_LENGTH = 20
RESAMPLES = 2_000
CONFIDENCE = 0.95
SEED = 20260722
CANONICAL_SIGNATURE = (
    "paired-portfolio-drawdown-diversification-v1|markets=BTC-USDT,ETH-USDT|"
    "portfolio=fixed-initial-weights-50-50-no-rebalancing|"
    "metric=max-drawdown-reduction-vs-each-sleeve|"
    "resampling=paired-noncircular-moving-block|block=20|resamples=2000|"
    "confidence=0.95|seed=20260722|candidate_count=1"
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_report(path: Path, expected_sha256: str) -> None:
    actual_sha256 = file_sha256(path)
    if actual_sha256 != expected_sha256:
        raise RuntimeError(
            f"walk-forward report hash mismatch for {path}: "
            f"expected {expected_sha256}, got {actual_sha256}"
        )

    report = json.loads(path.read_text(encoding="utf-8"))
    settings = report.get("settings")
    if not isinstance(settings, dict):
        raise ValueError("walk-forward report must contain settings")
    base_config = settings.get("base_config")
    if not isinstance(base_config, dict):
        raise ValueError("walk-forward report must contain settings.base_config")

    expected = {
        "annualization": 365,
        "candidate_count": 27,
        "cost_multipliers": [1.0, 2.0, 4.0],
        "non_overlapping_test_folds": True,
        "selection_bars": 730,
        "test_bars": 90,
        "transaction_cost_bps": 10.0,
    }
    observed = {
        "annualization": base_config.get("annualization"),
        "candidate_count": settings.get("candidate_count"),
        "cost_multipliers": settings.get("cost_multipliers"),
        "non_overlapping_test_folds": settings.get("non_overlapping_test_folds"),
        "selection_bars": settings.get("selection_bars"),
        "test_bars": settings.get("test_bars"),
        "transaction_cost_bps": base_config.get("transaction_cost_bps"),
    }
    if observed != expected:
        raise ValueError(
            "walk-forward settings do not match the predeclared portfolio test: "
            f"expected {expected}, got {observed}"
        )


def validate_returns(path: Path, expected_sha256: str) -> pd.DataFrame:
    actual_sha256 = file_sha256(path)
    if actual_sha256 != expected_sha256:
        raise RuntimeError(
            f"returns hash mismatch for {path}: expected {expected_sha256}, got {actual_sha256}"
        )

    frame = pd.read_csv(path)
    required = {"timestamp", "strategy_return"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"missing required columns: {sorted(missing)}")

    timestamps: list[pd.Timestamp] = []
    for value in frame["timestamp"]:
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timestamps must contain explicit timezone information")
        timestamps.append(timestamp)
    parsed = pd.Series(pd.to_datetime(timestamps, utc=True), index=frame.index)
    if parsed.duplicated().any() or not parsed.is_monotonic_increasing:
        raise ValueError("timestamps must be unique and strictly increasing")
    if len(parsed) > 1 and not parsed.diff().iloc[1:].eq(pd.Timedelta(days=1)).all():
        raise ValueError("timestamps must have exact daily cadence")

    returns = pd.to_numeric(frame["strategy_return"], errors="coerce")
    values = returns.to_numpy(dtype=float)
    if returns.isna().any() or not np.isfinite(values).all():
        raise ValueError("strategy_return must contain finite numbers")
    if np.any(values <= -1.0):
        raise ValueError("strategy_return must be greater than -1")

    return pd.DataFrame({"timestamp": parsed, "strategy_return": returns})


def align_sleeves(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    if set(frames) != set(MARKETS):
        raise ValueError("sleeves must exactly match the predeclared markets")
    reference = frames["BTC-USDT"]["timestamp"]
    if not frames["ETH-USDT"]["timestamp"].equals(reference):
        raise ValueError("BTC-USDT and ETH-USDT timestamps must align exactly")
    return pd.DataFrame(
        {market: frames[market]["strategy_return"].to_numpy(dtype=float) for market in MARKETS},
        index=pd.DatetimeIndex(reference),
    )


def no_rebalance_portfolio_returns(
    sleeve_returns: np.ndarray,
    weights: np.ndarray | None = None,
) -> np.ndarray:
    if sleeve_returns.ndim != 2 or sleeve_returns.shape[1] != 2:
        raise ValueError("sleeve_returns must have shape (observations, 2)")
    if len(sleeve_returns) == 0:
        raise ValueError("sleeve_returns cannot be empty")
    if not np.isfinite(sleeve_returns).all() or np.any(sleeve_returns <= -1.0):
        raise ValueError("sleeve returns must be finite and greater than -1")

    allocation = (
        np.array([INITIAL_WEIGHTS[market] for market in MARKETS], dtype=float)
        if weights is None
        else np.asarray(weights, dtype=float)
    )
    if allocation.shape != (2,) or not np.isfinite(allocation).all():
        raise ValueError("weights must contain two finite values")
    if np.any(allocation <= 0.0) or not math.isclose(
        float(allocation.sum()), 1.0, rel_tol=0.0, abs_tol=1e-12
    ):
        raise ValueError("weights must be positive and sum to one")

    sleeve_nav = np.cumprod(1.0 + sleeve_returns, axis=0)
    portfolio_nav = sleeve_nav @ allocation
    portfolio_returns = np.empty(len(portfolio_nav), dtype=float)
    portfolio_returns[0] = portfolio_nav[0] - 1.0
    portfolio_returns[1:] = portfolio_nav[1:] / portfolio_nav[:-1] - 1.0
    return portfolio_returns


def max_drawdown(returns: np.ndarray) -> float:
    values = np.asarray(returns, dtype=float)
    if values.ndim != 1 or len(values) == 0:
        raise ValueError("returns must be a non-empty one-dimensional array")
    if not np.isfinite(values).all() or np.any(values <= -1.0):
        raise ValueError("returns must be finite and greater than -1")
    nav = np.concatenate(([1.0], np.cumprod(1.0 + values)))
    running_peak = np.maximum.accumulate(nav)
    return float(np.min(nav / running_peak - 1.0))


def moving_block_indices(
    observations: int,
    block_length: int,
    rng: np.random.Generator,
) -> np.ndarray:
    if observations < block_length:
        raise ValueError("observations must be at least block_length")
    blocks_needed = math.ceil(observations / block_length)
    latest_start = observations - block_length
    starts = rng.integers(0, latest_start + 1, size=blocks_needed)
    indices = np.concatenate(
        [np.arange(start, start + block_length, dtype=int) for start in starts]
    )
    return indices[:observations]


def analyze_drawdown_diversification(sleeve_returns: np.ndarray) -> dict[str, object]:
    if sleeve_returns.ndim != 2 or sleeve_returns.shape[1] != 2:
        raise ValueError("sleeve_returns must have shape (observations, 2)")
    if len(sleeve_returns) < BLOCK_LENGTH:
        raise ValueError("sleeve returns must contain at least one block")
    if not np.isfinite(sleeve_returns).all() or np.any(sleeve_returns <= -1.0):
        raise ValueError("sleeve returns must be finite and greater than -1")

    portfolio_returns = no_rebalance_portfolio_returns(sleeve_returns)
    portfolio_drawdown = max_drawdown(portfolio_returns)
    sleeve_drawdowns = {
        market: max_drawdown(sleeve_returns[:, index]) for index, market in enumerate(MARKETS)
    }
    point_reductions = {market: portfolio_drawdown - sleeve_drawdowns[market] for market in MARKETS}

    bootstrap_reductions = {market: np.empty(RESAMPLES, dtype=float) for market in MARKETS}
    rng = np.random.default_rng(SEED)
    for sample_number in range(RESAMPLES):
        indices = moving_block_indices(len(sleeve_returns), BLOCK_LENGTH, rng)
        sample = sleeve_returns[indices]
        sample_portfolio_drawdown = max_drawdown(no_rebalance_portfolio_returns(sample))
        for market_index, market in enumerate(MARKETS):
            sample_sleeve_drawdown = max_drawdown(sample[:, market_index])
            bootstrap_reductions[market][sample_number] = (
                sample_portfolio_drawdown - sample_sleeve_drawdown
            )

    alpha = 1.0 - CONFIDENCE
    comparisons: dict[str, dict[str, object]] = {}
    for market in MARKETS:
        values = bootstrap_reductions[market]
        lower, median, upper = np.quantile(
            values,
            [alpha / 2.0, 0.5, 1.0 - alpha / 2.0],
        )
        comparisons[market] = {
            "bootstrap": {
                "ci_lower": float(lower),
                "ci_upper": float(upper),
                "lower_bound_positive": bool(lower > 0.0),
                "median": float(median),
                "probability_positive": float(np.mean(values > 0.0)),
            },
            "drawdown_reduction": float(point_reductions[market]),
            "sleeve_max_drawdown": float(sleeve_drawdowns[market]),
        }

    return {
        "comparisons": comparisons,
        "observations": len(sleeve_returns),
        "portfolio_max_drawdown": float(portfolio_drawdown),
        "portfolio_total_return": float(np.prod(1.0 + portfolio_returns) - 1.0),
        "seed": SEED,
        "sleeve_total_returns": {
            market: float(np.prod(1.0 + sleeve_returns[:, index]) - 1.0)
            for index, market in enumerate(MARKETS)
        },
    }


def build_result(artifact_dir: Path) -> dict[str, object]:
    validated: dict[str, pd.DataFrame] = {}
    for market, metadata in MARKETS.items():
        market_dir = artifact_dir / market
        validate_report(market_dir / "walk_forward.json", str(metadata["report_sha256"]))
        validated[market] = validate_returns(
            market_dir / "walk_forward_returns.csv",
            str(metadata["returns_sha256"]),
        )

    aligned = align_sleeves(validated)
    analysis = analyze_drawdown_diversification(aligned.to_numpy(dtype=float))
    comparisons = analysis["comparisons"]
    joint_supported = all(
        bool(comparisons[market]["bootstrap"]["lower_bound_positive"]) for market in MARKETS
    )
    failure_reasons = [
        f"portfolio drawdown reduction versus {market} lower confidence bound is not positive"
        for market in MARKETS
        if not bool(comparisons[market]["bootstrap"]["lower_bound_positive"])
    ]

    return {
        "candidate_count": 1,
        "canonical_signature": CANONICAL_SIGNATURE,
        "claim_boundary": (
            "This is one predeclared paired-block-bootstrap diagnostic on BTC-USDT and "
            "ETH-USDT development evidence. The portfolio uses fixed 50/50 initial weights "
            "and no rebalancing, matching the repository portfolio construction. It does not "
            "optimize weights, retune signals, alter fees or execution timing, or create a new "
            "holdout. It is not a liquidity, capacity, spread, impact, or live-fill model."
        ),
        "failure_reasons": failure_reasons,
        "hypothesis": (
            "The fixed-initial-weight 50/50 no-rebalancing BTC-USDT/ETH-USDT portfolio has "
            "less severe maximum drawdown than each individual sleeve, with both 95% paired "
            "moving-block-bootstrap lower bounds for drawdown reduction above zero."
        ),
        "joint_supported": joint_supported,
        "portfolio": analysis,
        "provenance": {
            "bar": "1Dutc",
            "instrument_type": "spot",
            "markets": list(MARKETS),
            "provider": "OKX",
            "source_artifact_id": 8515639605,
            "source_artifact_name": "quant-research-426",
            "source_artifact_sha256": (
                "396903281f1ef4ec71edbe0dded7c091c4c3545ffbaa7a502cc15bda4880b478"
            ),
            "source_base_commit": "006df4340a2f0cf73a716255e5148e56856a31cc",
            "source_merge_commit": "8b1003c8b680664f5e96ff6818694c9d30fe1b7f",
            "source_persistent_head": "43d4f8b10d8f654b5fbcf974793493a967e125e4",
            "source_workflow_run_id": 29883451981,
            "walk_forward_report_sha256": {
                market: str(metadata["report_sha256"]) for market, metadata in MARKETS.items()
            },
            "walk_forward_returns_sha256": {
                market: str(metadata["returns_sha256"]) for market, metadata in MARKETS.items()
            },
        },
        "specification": {
            "block_length": BLOCK_LENGTH,
            "confidence": CONFIDENCE,
            "initial_weights": INITIAL_WEIGHTS,
            "metric": "portfolio maximum drawdown minus sleeve maximum drawdown",
            "portfolio_rule": "fixed initial weights; no rebalancing",
            "resamples": RESAMPLES,
            "resampling": "paired non-circular moving-block bootstrap",
            "seed": SEED,
        },
        "verdict": "supported" if joint_supported else "rejected",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Test fixed-weight BTC/ETH portfolio drawdown diversification."
    )
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = build_result(args.artifact_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
