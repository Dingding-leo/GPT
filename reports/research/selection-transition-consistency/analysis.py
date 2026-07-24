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
MARKETS = {
    "BTC-USDT": {
        "seed": 20260722,
        "returns_sha256": "539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73",
        "report_sha256": "84b13011e3ffbda1f1d24f2292bacc3a0aa29025671c29f4a74c840190a32494",
    },
    "ETH-USDT": {
        "seed": 20260723,
        "returns_sha256": "027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6",
        "report_sha256": "a64fd72efc64076e003eec7a08f4c4ee5fd19f7995dac13ebbb9f43ce44e4b39",
    },
}
SIGNATURE = (
    "selection-transition-regime-consistency-v1|markets=BTC-USDT,ETH-USDT|"
    "source=persisted-net-rolling-oos-returns-and-selected-parameters|"
    "regimes=selected-parameter-tuple-changed-vs-unchanged-from-prior-fold|"
    "exclude=fold1-no-prior-selection|metric=conditional-annualized-arithmetic-mean-net-return|"
    "annualization=365|resampling=paired-noncircular-moving-block-over-whole-fold-records|"
    "fold-block=3|resamples=2000|confidence=0.95|"
    "seeds=BTC:20260722,ETH:20260723|candidate_count=1"
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _explicit_utc_index(values: pd.Series) -> pd.DatetimeIndex:
    parsed: list[pd.Timestamp] = []
    for value in values:
        timestamp = pd.Timestamp(value)
        if pd.isna(timestamp) or timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timestamps must contain explicit timezone information")
        parsed.append(timestamp)
    index = pd.DatetimeIndex(pd.to_datetime(parsed, utc=True))
    if index.duplicated().any() or not index.is_monotonic_increasing:
        raise ValueError("timestamps must be unique and strictly increasing")
    return index


def _parameter_tuple(value: dict[str, object]) -> tuple[int, int, float]:
    return (
        int(value["momentum_lookback"]),
        int(value["reversal_lookback"]),
        float(value["trend_weight"]),
    )


def classify_parameter_transitions(
    parameters: list[tuple[int, int, float]],
) -> list[bool]:
    if len(parameters) < 2:
        raise ValueError("at least two selected-parameter records are required")
    pairs = zip(parameters[:-1], parameters[1:], strict=True)
    return [current != previous for previous, current in pairs]


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
    required = {
        "timestamp",
        "fold",
        "strategy_return",
        "selected_momentum_lookback",
        "selected_reversal_lookback",
        "selected_trend_weight",
    }
    missing = required - set(frame)
    if missing:
        raise ValueError(f"return file is missing required columns: {sorted(missing)}")
    timestamps = _explicit_utc_index(frame["timestamp"])
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
    if settings["test_bars"] != EXPECTED_TEST_BARS:
        raise ValueError("walk-forward report test length changed")
    if settings["base_config"]["annualization"] != ANNUALIZATION:
        raise ValueError("walk-forward report annualization changed")
    if settings["base_config"]["transaction_cost_bps"] != 10.0:
        raise ValueError("walk-forward report transaction cost changed")

    fold_reports = report["folds"]
    fold_ids = [int(fold["fold"]) for fold in fold_reports]
    if fold_ids != list(range(1, len(fold_ids) + 1)):
        raise ValueError("walk-forward fold identifiers must be consecutive from one")
    parameters = [_parameter_tuple(fold["selected_parameters"]) for fold in fold_reports]
    transitions = classify_parameter_transitions(parameters)

    records: list[dict[str, object]] = []
    for index, fold_report in enumerate(fold_reports):
        fold_id = fold_ids[index]
        fold_frame = frame.loc[frame["fold"] == fold_id]
        if len(fold_frame) != EXPECTED_TEST_BARS:
            raise ValueError(f"fold {fold_id} must contain exactly {EXPECTED_TEST_BARS} rows")
        if (
            fold_frame["timestamp"].iloc[0].isoformat()
            != pd.Timestamp(fold_report["test_start"]).isoformat()
        ):
            raise ValueError(f"fold {fold_id} start does not match its report")
        if (
            fold_frame["timestamp"].iloc[-1].isoformat()
            != pd.Timestamp(fold_report["test_end"]).isoformat()
        ):
            raise ValueError(f"fold {fold_id} end does not match its report")

        expected_parameters = parameters[index]
        observed_parameters = (
            int(fold_frame["selected_momentum_lookback"].iloc[0]),
            int(fold_frame["selected_reversal_lookback"].iloc[0]),
            float(fold_frame["selected_trend_weight"].iloc[0]),
        )
        if observed_parameters != expected_parameters:
            raise ValueError(f"fold {fold_id} selected parameters do not match its report")
        parameter_columns = [
            "selected_momentum_lookback",
            "selected_reversal_lookback",
            "selected_trend_weight",
        ]
        if any(fold_frame[column].nunique(dropna=False) != 1 for column in parameter_columns):
            raise ValueError(f"fold {fold_id} selected parameters change inside the test fold")
        if fold_report["candidates_tested"] != EXPECTED_CANDIDATE_COUNT:
            raise ValueError(f"fold {fold_id} candidate count changed")
        if index == 0:
            continue
        records.append(
            {
                "fold": fold_id,
                "parameters_changed": transitions[index - 1],
                "strategy_returns": fold_frame["strategy_return"].to_numpy(dtype=float),
            }
        )

    if len(records) != len(fold_reports) - 1:
        raise RuntimeError("unexpected classified fold count")
    return records


def moving_block_indices(n: int, *, block_length: int, resamples: int, seed: int) -> np.ndarray:
    if n < block_length:
        raise ValueError("block length cannot exceed fold count")
    rng = np.random.default_rng(seed)
    blocks_per_sample = math.ceil(n / block_length)
    starts = rng.integers(0, n - block_length + 1, size=(resamples, blocks_per_sample))
    offsets = np.arange(block_length)
    indices = starts[..., None] + offsets
    return indices.reshape(resamples, -1)[:, :n]


def conditional_annualized_means(records: list[dict[str, object]]) -> dict[str, float]:
    result: dict[str, float] = {}
    for label, regime in ((True, "changed"), (False, "unchanged")):
        selected = [
            np.asarray(record["strategy_returns"], dtype=float)
            for record in records
            if record["parameters_changed"] is label
        ]
        if not selected:
            raise ValueError(f"resample has no {regime} folds")
        result[regime] = float(np.concatenate(selected).mean() * ANNUALIZATION)
    return result


def analyze_market(records: list[dict[str, object]], *, seed: int) -> dict[str, object]:
    point = conditional_annualized_means(records)
    indices = moving_block_indices(
        len(records),
        block_length=FOLD_BLOCK_LENGTH,
        resamples=RESAMPLES,
        seed=seed,
    )
    distributions = {"changed": np.empty(RESAMPLES), "unchanged": np.empty(RESAMPLES)}
    for sample_index, fold_indices in enumerate(indices):
        sampled = [records[int(index)] for index in fold_indices]
        sample_means = conditional_annualized_means(sampled)
        for regime in distributions:
            distributions[regime][sample_index] = sample_means[regime]

    alpha = (1.0 - CONFIDENCE) / 2.0
    regimes: dict[str, object] = {}
    for regime, distribution in distributions.items():
        lower, upper = np.quantile(distribution, [alpha, 1.0 - alpha])
        fold_count = sum(
            record["parameters_changed"] is (regime == "changed") for record in records
        )
        regimes[regime] = {
            "folds": fold_count,
            "observations": fold_count * EXPECTED_TEST_BARS,
            "annualized_arithmetic_mean": point[regime],
            "confidence_interval": {"lower": float(lower), "upper": float(upper)},
            "probability_mean_positive": float((distribution > 0.0).mean()),
            "passes": bool(lower > 0.0),
        }

    return {
        "classified_folds": len(records),
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
                    f"{market} {regime}-parameter-fold mean 95% lower bound is non-positive: "
                    f"{regime_result['confidence_interval']['lower']:.12f}"
                )

    passed = not failures
    return {
        "canonical_signature": SIGNATURE,
        "candidate_count": 1,
        "candidates": [
            {
                "name": "selected-parameter-transition-regime-consistency",
                "verdict": "pass" if passed else "reject",
                "failure_reasons": failures,
            }
        ],
        "hypothesis": (
            "For both BTC-USDT and ETH-USDT, net rolling OOS returns have a positive "
            "annualized arithmetic mean in folds where the selected parameter tuple changed "
            "from the prior fold and in folds where it remained unchanged, with all four 95% "
            "moving-block-bootstrap lower bounds above zero."
        ),
        "economic_rationale": (
            "A credible adaptive research process should not require either continuous parameter "
            "churn or prolonged parameter stasis to generate returns. Conditioning on observed "
            "selection transitions tests whether performance survives both operating states."
        ),
        "method": {
            "annualization": ANNUALIZATION,
            "fold_block_length": FOLD_BLOCK_LENGTH,
            "fold_block_rationale": (
                "three adjacent 90-day folds preserve roughly nine months of local selection and "
                "return dependence while retaining 23 admissible non-circular block starts"
            ),
            "resamples": RESAMPLES,
            "confidence": CONFIDENCE,
            "candidate_count": 1,
            "parameter_tuple": [
                "selected_momentum_lookback",
                "selected_reversal_lookback",
                "selected_trend_weight",
            ],
            "first_fold_handling": "excluded because no prior selected parameter tuple exists",
            "resampling": (
                "paired non-circular moving blocks over complete observed 90-day fold records; "
                "the original changed/unchanged label remains attached to each observed fold"
            ),
            "metric": "conditional daily net-return arithmetic mean multiplied by 365",
        },
        "provenance": {
            "provider": "OKX",
            "market_type": "spot",
            "timeframe": "1Dutc",
            "source_workflow_run_id": 29895819965,
            "source_workflow_run_attempt": 1,
            "source_artifact_id": 8519944587,
            "source_artifact_name": "quant-research-source-648-attempt-1",
            "source_artifact_sha256": (
                "f755ee85017c881e7fcfde1dc1fcd5c3f0fadbcb67197f1f3a466f1178b3895f"
            ),
            "source_head_sha": "09a6be919bd3733b01f86bfcf8710377ce462455",
            "tested_base_sha": "18ba522be8a7bf3941392a8acfc7f5100172fc91",
            "return_file_sha256": {
                market: specification["returns_sha256"] for market, specification in MARKETS.items()
            },
            "walk_forward_report_sha256": {
                market: specification["report_sha256"] for market, specification in MARKETS.items()
            },
            "observations_per_market": 2340,
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
            "Only 25 folds per market have a prior-fold transition label.",
            (
                "The transition label is an observed fold attribute and is not recomputed across "
                "bootstrap block boundaries."
            ),
            (
                "The experiment diagnoses selection-transition dependence; it does not introduce "
                "a trading rule or retune any strategy parameter."
            ),
            "The analysis does not model capacity, order-book depth, latency, or partial fills.",
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
