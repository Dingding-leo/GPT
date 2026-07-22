from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ANNUALIZATION = 365
FOLD_BLOCK_LENGTH = 3
RESAMPLES = 2000
CONFIDENCE = 0.95
EXPECTED_TEST_BARS = 90
EXPECTED_CANDIDATE_COUNT = 27
EXPECTED_OBSERVATIONS = 2340
MARKETS = {
    "BTC-USDT": {
        "seed": 20260722,
        "returns_sha256": "539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73",
        "report_sha256": "13b3434bec93f015aa72403be6f959588d2607d16c05956edafc61520aa768b1",
    },
    "ETH-USDT": {
        "seed": 20260723,
        "returns_sha256": "027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6",
        "report_sha256": "576ad57dda5d10f987cf63b6fe5fb578bc77ed9d4ec980dc4b3da2a854dde824",
    },
}
SIGNATURE = (
    "prior-fold-performance-regime-consistency-v1|markets=BTC-USDT,ETH-USDT|"
    "source=persisted-net-rolling-oos-fold-returns|"
    "regimes=previous-fold-compounded-return-positive-vs-nonpositive|"
    "exclude=fold1-no-prior-performance|metric=conditional-annualized-arithmetic-mean-net-return|"
    "annualization=365|"
    "resampling=paired-noncircular-moving-block-over-complete-fold-records-with-regimes-recomputed|"
    "fold-block=3|resamples=2000|confidence=0.95|"
    "seeds=BTC:20260722,ETH:20260723|candidate_count=1"
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _explicit_daily_utc_index(values: pd.Series) -> pd.DatetimeIndex:
    parsed: list[pd.Timestamp] = []
    for value in values:
        timestamp = pd.Timestamp(value)
        if pd.isna(timestamp) or timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timestamps must contain explicit timezone information")
        parsed.append(timestamp)
    index = pd.DatetimeIndex(pd.to_datetime(parsed, utc=True))
    if index.duplicated().any() or not index.is_monotonic_increasing:
        raise ValueError("timestamps must be unique and strictly increasing")
    if len(index) > 1:
        intervals = index[1:] - index[:-1]
        if not bool((intervals == pd.Timedelta(days=1)).all()):
            raise ValueError("timestamps must have exact daily cadence")
    return index


def compounded_return(returns: np.ndarray) -> float:
    values = np.asarray(returns, dtype=float)
    if values.ndim != 1 or values.size == 0:
        raise ValueError("fold returns must be a non-empty one-dimensional array")
    if not np.isfinite(values).all() or (values <= -1.0).any():
        raise ValueError("fold returns must be finite and greater than -100%")
    return float(np.prod(1.0 + values) - 1.0)


def load_fold_records(
    artifact_dir: Path,
    *,
    market: str,
    expected_returns_sha256: str,
    expected_report_sha256: str,
) -> list[dict[str, object]]:
    market_dir = artifact_dir / market
    returns_path = market_dir / "walk_forward_returns.csv"
    report_path = market_dir / "walk_forward.json"
    actual_returns_sha256 = file_sha256(returns_path)
    actual_report_sha256 = file_sha256(report_path)
    if actual_returns_sha256 != expected_returns_sha256:
        raise ValueError(
            "return file hash mismatch: "
            f"expected {expected_returns_sha256}, actual {actual_returns_sha256}"
        )
    if actual_report_sha256 != expected_report_sha256:
        raise ValueError(
            "walk-forward report hash mismatch: "
            f"expected {expected_report_sha256}, actual {actual_report_sha256}"
        )

    frame = pd.read_csv(returns_path)
    required = {"timestamp", "fold", "strategy_return"}
    missing = required - set(frame)
    if missing:
        raise ValueError(f"return file is missing required columns: {sorted(missing)}")
    if len(frame) != EXPECTED_OBSERVATIONS:
        raise ValueError(f"return file must contain exactly {EXPECTED_OBSERVATIONS} observations")
    timestamps = _explicit_daily_utc_index(frame["timestamp"])
    returns = pd.to_numeric(frame["strategy_return"], errors="raise").to_numpy(dtype=float)
    if not np.isfinite(returns).all() or (returns <= -1.0).any():
        raise ValueError("strategy returns must be finite and greater than -100%")
    numeric_folds = pd.to_numeric(frame["fold"], errors="raise").to_numpy(dtype=float)
    if (
        not np.isfinite(numeric_folds).all()
        or not np.equal(numeric_folds, np.floor(numeric_folds)).all()
    ):
        raise ValueError("fold identifiers must be finite integers")

    frame = frame.copy()
    frame["timestamp"] = timestamps
    frame["fold"] = numeric_folds.astype(int)
    frame["strategy_return"] = returns

    report = json.loads(report_path.read_text(encoding="utf-8"))
    settings = report["settings"]
    if settings["candidate_count"] != EXPECTED_CANDIDATE_COUNT:
        raise ValueError("walk-forward report candidate count changed")
    if settings["selection_bars"] != 730:
        raise ValueError("walk-forward report selection length changed")
    if settings["test_bars"] != EXPECTED_TEST_BARS:
        raise ValueError("walk-forward report test length changed")
    if settings["base_config"]["annualization"] != ANNUALIZATION:
        raise ValueError("walk-forward report annualization changed")
    if settings["base_config"]["transaction_cost_bps"] != 10.0:
        raise ValueError("walk-forward report transaction cost changed")
    if settings["non_overlapping_test_folds"] is not True:
        raise ValueError("walk-forward report must declare non-overlapping test folds")

    fold_reports = report["folds"]
    fold_ids = [int(fold["fold"]) for fold in fold_reports]
    if fold_ids != list(range(1, len(fold_ids) + 1)):
        raise ValueError("walk-forward fold identifiers must be consecutive from one")

    records: list[dict[str, object]] = []
    prior_end: pd.Timestamp | None = None
    for fold_report, fold_id in zip(fold_reports, fold_ids, strict=True):
        fold_frame = frame.loc[frame["fold"] == fold_id]
        if len(fold_frame) != EXPECTED_TEST_BARS:
            raise ValueError(f"fold {fold_id} must contain exactly {EXPECTED_TEST_BARS} rows")
        start = fold_frame["timestamp"].iloc[0]
        end = fold_frame["timestamp"].iloc[-1]
        if start.isoformat() != pd.Timestamp(fold_report["test_start"]).isoformat():
            raise ValueError(f"fold {fold_id} start does not match its report")
        if end.isoformat() != pd.Timestamp(fold_report["test_end"]).isoformat():
            raise ValueError(f"fold {fold_id} end does not match its report")
        if prior_end is not None and start != prior_end + pd.Timedelta(days=1):
            raise ValueError("walk-forward test folds must be chronologically contiguous")
        prior_end = end
        if fold_report["candidates_tested"] != EXPECTED_CANDIDATE_COUNT:
            raise ValueError(f"fold {fold_id} candidate count changed")
        fold_returns = fold_frame["strategy_return"].to_numpy(dtype=float)
        total_return = compounded_return(fold_returns)
        reported_total_return = float(fold_report["test_metrics"]["total_return"])
        if not math.isclose(total_return, reported_total_return, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError(f"fold {fold_id} total return does not match its persisted rows")
        records.append(
            {
                "fold": fold_id,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "strategy_returns": fold_returns,
                "total_return": total_return,
            }
        )

    if len(records) != len(fold_reports) or len(records) * EXPECTED_TEST_BARS != len(frame):
        raise RuntimeError("unexpected walk-forward fold coverage")
    return records


def classify_by_previous_fold(
    records: list[dict[str, object]],
) -> list[dict[str, object]]:
    if len(records) < 3:
        raise ValueError("at least three complete fold records are required")
    classified: list[dict[str, object]] = []
    for previous, current in zip(records[:-1], records[1:], strict=True):
        previous_total_return = compounded_return(
            np.asarray(previous["strategy_returns"], dtype=float)
        )
        classified.append(
            {
                "fold": current["fold"],
                "previous_fold": previous["fold"],
                "previous_fold_total_return": previous_total_return,
                "previous_fold_positive": previous_total_return > 0.0,
                "strategy_returns": np.asarray(current["strategy_returns"], dtype=float),
            }
        )
    return classified


def conditional_annualized_means(
    classified: list[dict[str, object]],
) -> dict[str, float]:
    results: dict[str, float] = {}
    for positive, regime in ((True, "previous_positive"), (False, "previous_nonpositive")):
        selected = [
            np.asarray(record["strategy_returns"], dtype=float)
            for record in classified
            if record["previous_fold_positive"] == positive
        ]
        if not selected:
            raise ValueError(f"sample has no {regime} current folds")
        results[regime] = float(np.concatenate(selected).mean() * ANNUALIZATION)
    return results


def moving_block_indices(n: int, *, block_length: int, resamples: int, seed: int) -> np.ndarray:
    if n < block_length:
        raise ValueError("block length cannot exceed fold count")
    if block_length < 1 or resamples < 1:
        raise ValueError("block length and resample count must be positive")
    rng = np.random.default_rng(seed)
    blocks_per_sample = math.ceil(n / block_length)
    starts = rng.integers(0, n - block_length + 1, size=(resamples, blocks_per_sample))
    offsets = np.arange(block_length)
    indices = starts[..., None] + offsets
    return indices.reshape(resamples, -1)[:, :n]


def analyze_market(records: list[dict[str, object]], *, seed: int) -> dict[str, object]:
    classified = classify_by_previous_fold(records)
    point = conditional_annualized_means(classified)
    indices = moving_block_indices(
        len(records),
        block_length=FOLD_BLOCK_LENGTH,
        resamples=RESAMPLES,
        seed=seed,
    )
    distributions = {
        "previous_positive": np.empty(RESAMPLES),
        "previous_nonpositive": np.empty(RESAMPLES),
    }
    for sample_index, fold_indices in enumerate(indices):
        sampled_records = [records[int(index)] for index in fold_indices]
        sampled_classified = classify_by_previous_fold(sampled_records)
        sample_means = conditional_annualized_means(sampled_classified)
        for regime in distributions:
            distributions[regime][sample_index] = sample_means[regime]

    alpha = (1.0 - CONFIDENCE) / 2.0
    regimes: dict[str, object] = {}
    for positive, regime in ((True, "previous_positive"), (False, "previous_nonpositive")):
        distribution = distributions[regime]
        lower, upper = np.quantile(distribution, [alpha, 1.0 - alpha])
        selected = [record for record in classified if record["previous_fold_positive"] == positive]
        regimes[regime] = {
            "folds": len(selected),
            "observations": len(selected) * EXPECTED_TEST_BARS,
            "annualized_arithmetic_mean": point[regime],
            "confidence_interval": {"lower": float(lower), "upper": float(upper)},
            "probability_mean_positive": float((distribution > 0.0).mean()),
            "passes": bool(lower > 0.0),
        }

    return {
        "complete_folds": len(records),
        "classified_folds": len(classified),
        "excluded_folds": 1,
        "seed": seed,
        "regimes": regimes,
        "passes": all(regime["passes"] for regime in regimes.values()),
    }


def build_result(artifact_dir: Path) -> dict[str, object]:
    markets: dict[str, object] = {}
    failures: list[str] = []
    for market, specification in MARKETS.items():
        records = load_fold_records(
            artifact_dir,
            market=market,
            expected_returns_sha256=specification["returns_sha256"],
            expected_report_sha256=specification["report_sha256"],
        )
        market_result = analyze_market(records, seed=specification["seed"])
        markets[market] = market_result
        for regime, regime_result in market_result["regimes"].items():
            if not regime_result["passes"]:
                failures.append(
                    f"{market} {regime} current-fold mean 95% lower bound is non-positive: "
                    f"{regime_result['confidence_interval']['lower']:.12f}"
                )

    passed = not failures
    return {
        "canonical_signature": SIGNATURE,
        "candidate_count": 1,
        "candidates": [
            {
                "name": "prior-fold-performance-regime-consistency",
                "verdict": "pass" if passed else "reject",
                "failure_reasons": failures,
            }
        ],
        "hypothesis": (
            "For both BTC-USDT and ETH-USDT, net rolling OOS returns have a positive "
            "annualized arithmetic mean after both a positive and a non-positive immediately "
            "preceding OOS fold, with all four 95% moving-block-bootstrap lower bounds above zero."
        ),
        "economic_rationale": (
            "A credible adaptive research process should not require exclusively favorable or "
            "unfavorable immediately preceding OOS performance. This prior-only regime diagnostic "
            "tests whether current-fold returns persist after both observed operating states."
        ),
        "method": {
            "annualization": ANNUALIZATION,
            "fold_block_length": FOLD_BLOCK_LENGTH,
            "fold_block_rationale": (
                "three adjacent 90-day folds preserve roughly nine months of local OOS dependence "
                "while retaining 24 admissible non-circular block starts"
            ),
            "resamples": RESAMPLES,
            "confidence": CONFIDENCE,
            "candidate_count": 1,
            "previous_fold_metric": "compounded net strategy return",
            "regimes": ["previous_positive", "previous_nonpositive"],
            "first_fold_handling": "excluded because no prior OOS fold exists",
            "resampling": (
                "paired non-circular moving blocks over complete observed 90-day fold records; "
                "previous-fold performance labels are recomputed after block concatenation"
            ),
            "metric": "conditional daily net-return arithmetic mean multiplied by 365",
        },
        "provenance": {
            "provider": "OKX",
            "market_type": "spot",
            "timeframe": "1Dutc",
            "source_workflow_run_id": 29902829833,
            "source_workflow_run_attempt": 1,
            "source_artifact_id": 8522613577,
            "source_artifact_name": "quant-research-source-755-attempt-1",
            "source_artifact_sha256": (
                "9955cfa0f2faefeddf8cb63e3fcf4765e0ccbd32c4c866824733c93ed4160e9c"
            ),
            "source_head_sha": "ef8f0f88df3aa38dfa9992028ba8a75f404f120a",
            "tested_base_sha": "aa594f8cca0769aa7004ac14593025d007d7a537",
            "return_file_sha256": {
                market: specification["returns_sha256"] for market, specification in MARKETS.items()
            },
            "walk_forward_report_sha256": {
                market: specification["report_sha256"] for market, specification in MARKETS.items()
            },
            "observations_per_market": EXPECTED_OBSERVATIONS,
            "evaluation_start": "2020-01-11T00:00:00+00:00",
            "evaluation_end": "2026-06-07T00:00:00+00:00",
            "selection_bars": 730,
            "test_bars": EXPECTED_TEST_BARS,
            "candidate_grid_size": EXPECTED_CANDIDATE_COUNT,
            "transaction_cost_bps": 10.0,
            "execution_delay_bars": 1,
        },
        "markets": markets,
        "verdict": "pass" if passed else "reject",
        "failure_reasons": failures,
        "limitations": [
            "BTC-USDT and ETH-USDT are development markets, not untouched holdouts.",
            "Only 25 current folds per market have an immediately preceding OOS fold.",
            (
                "Moving-block concatenation creates artificial fold joins, although prior-fold "
                "performance labels are recomputed after each join."
            ),
            (
                "The experiment diagnoses dependence on recent OOS performance; it does not "
                "introduce a trading rule or retune any strategy parameter."
            ),
            "The analysis does not model spread, impact, capacity, latency, or partial fills.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build_result(args.artifact_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
