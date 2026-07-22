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
        "report_sha256": "36c13d611e09ddeb65788ea2f597979e763aa797ef79b0fd341ef9aba33b3eca",
    },
    "ETH-USDT": {
        "returns_sha256": "027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6",
        "report_sha256": "d51ee25fe582da2ffd1a234372758b8eee5c05bdfdce3a4021716bc9e781628e",
    },
}
INITIAL_WEIGHTS = {"BTC-USDT": 0.5, "ETH-USDT": 0.5}
TAIL_FRACTION = 0.05
BLOCK_LENGTH = 20
RESAMPLES = 2_000
CONFIDENCE = 0.95
SEED = 20260722
CANONICAL_SIGNATURE = (
    "paired-portfolio-expected-shortfall-diversification-v1|"
    "markets=BTC-USDT,ETH-USDT|portfolio=fixed-initial-weights-50-50-no-rebalancing|"
    "metric=expected-shortfall-5pct-reduction-vs-each-sleeve|tail_fraction=0.05|"
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


def expected_shortfall(returns: np.ndarray, tail_fraction: float = TAIL_FRACTION) -> float:
    values = np.asarray(returns, dtype=float)
    if values.ndim != 1 or len(values) == 0:
        raise ValueError("returns must be a non-empty one-dimensional array")
    if not np.isfinite(values).all() or np.any(values <= -1.0):
        raise ValueError("returns must be finite and greater than -1")
    if not 0.0 < tail_fraction < 1.0:
        raise ValueError("tail_fraction must be in (0, 1)")
    tail_observations = math.ceil(len(values) * tail_fraction)
    return float(np.partition(values, tail_observations - 1)[:tail_observations].mean())


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


def analyze_expected_shortfall_diversification(
    sleeve_returns: np.ndarray,
) -> dict[str, object]:
    if sleeve_returns.ndim != 2 or sleeve_returns.shape[1] != 2:
        raise ValueError("sleeve_returns must have shape (observations, 2)")
    if len(sleeve_returns) < BLOCK_LENGTH:
        raise ValueError("sleeve returns must contain at least one block")
    if not np.isfinite(sleeve_returns).all() or np.any(sleeve_returns <= -1.0):
        raise ValueError("sleeve returns must be finite and greater than -1")

    portfolio_returns = no_rebalance_portfolio_returns(sleeve_returns)
    portfolio_expected_shortfall = expected_shortfall(portfolio_returns)
    sleeve_expected_shortfalls = {
        market: expected_shortfall(sleeve_returns[:, index])
        for index, market in enumerate(MARKETS)
    }
    point_reductions = {
        market: portfolio_expected_shortfall - sleeve_expected_shortfalls[market]
        for market in MARKETS
    }

    bootstrap_reductions = {market: np.empty(RESAMPLES, dtype=float) for market in MARKETS}
    rng = np.random.default_rng(SEED)
    for sample_number in range(RESAMPLES):
        indices = moving_block_indices(len(sleeve_returns), BLOCK_LENGTH, rng)
        sample = sleeve_returns[indices]
        sample_portfolio_expected_shortfall = expected_shortfall(
            no_rebalance_portfolio_returns(sample)
        )
        for market_index, market in enumerate(MARKETS):
            sample_sleeve_expected_shortfall = expected_shortfall(sample[:, market_index])
            bootstrap_reductions[market][sample_number] = (
                sample_portfolio_expected_shortfall - sample_sleeve_expected_shortfall
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
            "expected_shortfall_reduction": float(point_reductions[market]),
            "sleeve_expected_shortfall": float(sleeve_expected_shortfalls[market]),
        }

    return {
        "comparisons": comparisons,
        "observations": len(sleeve_returns),
        "portfolio_expected_shortfall": float(portfolio_expected_shortfall),
        "portfolio_total_return": float(np.prod(1.0 + portfolio_returns) - 1.0),
        "seed": SEED,
        "sleeve_total_returns": {
            market: float(np.prod(1.0 + sleeve_returns[:, index]) - 1.0)
            for index, market in enumerate(MARKETS)
        },
        "tail_fraction": TAIL_FRACTION,
        "tail_observations": math.ceil(len(sleeve_returns) * TAIL_FRACTION),
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
    analysis = analyze_expected_shortfall_diversification(aligned.to_numpy(dtype=float))
    comparisons = analysis["comparisons"]
    joint_supported = all(
        bool(comparisons[market]["bootstrap"]["lower_bound_positive"]) for market in MARKETS
    )
    failure_reasons = [
        f"portfolio expected-shortfall reduction versus {market} lower confidence bound "
        "is not positive"
        for market in MARKETS
        if not bool(comparisons[market]["bootstrap"]["lower_bound_positive"])
    ]

    return {
        "candidate_count": 1,
        "canonical_signature": CANONICAL_SIGNATURE,
        "claim_boundary": (
            "This is one predeclared paired-block-bootstrap diagnostic on BTC-USDT and "
            "ETH-USDT development evidence. The portfolio uses fixed 50/50 initial weights "
            "and no rebalancing, matching the repository portfolio construction. Expected "
            "shortfall is the arithmetic mean of the worst ceil(5%) observed net returns. "
            "The experiment does not optimize weights, retune signals, alter fees or execution "
            "timing, or create a new holdout. It is not a liquidity, capacity, spread, impact, "
            "or live-fill model."
        ),
        "failure_reasons": failure_reasons,
        "hypothesis": (
            "The fixed-initial-weight 50/50 no-rebalancing BTC-USDT/ETH-USDT portfolio has "
            "less severe 5% expected shortfall than each individual sleeve, with both 95% "
            "paired moving-block-bootstrap lower bounds for expected-shortfall reduction "
            "above zero."
        ),
        "joint_supported": joint_supported,
        "portfolio": analysis,
        "provenance": {
            "bar": "1Dutc",
            "instrument_type": "spot",
            "markets": list(MARKETS),
            "provider": "OKX",
            "source_artifact_id": 8516824262,
            "source_artifact_name": "quant-research-484",
            "source_artifact_sha256": (
                "b1f271e4267cc1c1007bbccd11c53c1a59d3f1e3fe3f1e3f07423c6907b83605"
            ),
            "source_code_head": "cfc0a08048ac584a375f15e4ed146c00266e2e17",
            "source_workflow_run_id": 29886881484,
            "walk_forward_report_sha256": {
                market: metadata["report_sha256"] for market, metadata in MARKETS.items()
            },
            "walk_forward_returns_sha256": {
                market: metadata["returns_sha256"] for market, metadata in MARKETS.items()
            },
        },
        "resampling": {
            "block_length": BLOCK_LENGTH,
            "confidence": CONFIDENCE,
            "method": "paired non-circular moving-block bootstrap",
            "resamples": RESAMPLES,
            "seed": SEED,
        },
        "verdict": "supported" if joint_supported else "rejected",
    }


def write_report(result: dict[str, object], path: Path) -> None:
    portfolio = result["portfolio"]
    comparisons = portfolio["comparisons"]
    lines = [
        "# Portfolio Expected-Shortfall Diversification",
        "",
        "## Hypothesis",
        "",
        str(result["hypothesis"]),
        "",
        "## Predeclared specification",
        "",
        f"- Canonical signature: `{result['canonical_signature']}`",
        "- Candidate count: 1",
        "- Portfolio: 50/50 initial BTC-USDT and ETH-USDT weights, no rebalancing",
        "- Tail metric: mean of the worst `ceil(5% × observations)` net returns",
        "- Resampling: paired non-circular 20-day moving blocks",
        "- Resamples: 2,000",
        "- Confidence: 95%",
        "- Seed: 20260722",
        "",
        "## Result",
        "",
        f"- Verdict: **{result['verdict']}**",
        f"- Observations: {portfolio['observations']}",
        f"- Tail observations: {portfolio['tail_observations']}",
        (
            "- Portfolio 5% expected shortfall: "
            f"{portfolio['portfolio_expected_shortfall']:.6%}"
        ),
        "",
        "| Sleeve comparison | Sleeve ES | Portfolio minus sleeve ES | 95% interval | P(reduction > 0) |",
        "|---|---:|---:|---:|---:|",
    ]
    for market in MARKETS:
        comparison = comparisons[market]
        bootstrap = comparison["bootstrap"]
        lines.append(
            f"| {market} | {comparison['sleeve_expected_shortfall']:.6%} | "
            f"{comparison['expected_shortfall_reduction']:.6%} | "
            f"[{bootstrap['ci_lower']:.6%}, {bootstrap['ci_upper']:.6%}] | "
            f"{bootstrap['probability_positive']:.2%} |"
        )
    lines.extend(
        [
            "",
            "The joint hypothesis requires both lower confidence bounds to be positive. "
            "Failure on either comparison rejects the claim.",
            "",
            "## Failure accounting",
            "",
        ]
    )
    if result["failure_reasons"]:
        lines.extend(f"- {reason}" for reason in result["failure_reasons"])
    else:
        lines.append("- None.")
    lines.extend(
        [
            "",
            "## Evidence boundary",
            "",
            str(result["claim_boundary"]),
            "",
            "BTC-USDT and ETH-USDT are development markets, not untouched holdouts.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Test fixed-weight portfolio expected-shortfall diversification."
    )
    parser.add_argument("--artifact-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = build_result(args.artifact_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    write_report(result, args.output.with_name("REPORT.md"))
    print(f"verdict={result['verdict']}")
    print(f"candidate_count={result['candidate_count']}")
    for market, comparison in result["portfolio"]["comparisons"].items():
        bootstrap = comparison["bootstrap"]
        print(
            f"{market}: reduction={comparison['expected_shortfall_reduction']:.12f}, "
            f"ci=[{bootstrap['ci_lower']:.12f}, {bootstrap['ci_upper']:.12f}], "
            f"p_positive={bootstrap['probability_positive']:.6f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
