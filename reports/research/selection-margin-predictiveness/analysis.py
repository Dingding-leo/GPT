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
        "report_sha256": "8c68767eeba6d6ecdc3716f194dc9cf3d48cb0a51fea49f6a4e10f771c03914b",
        "seed": 20260722,
    },
    "ETH-USDT": {
        "report_sha256": "792de43822f91b9475885f511d23fd68e002473b8fcc67ec8eb4a867e320ac99",
        "seed": 20260723,
    },
}
BLOCK_LENGTH = 9
RESAMPLES = 2_000
CONFIDENCE = 0.95
CANDIDATE_COUNT = 1
CANONICAL_SIGNATURE = (
    "selection-margin-predictiveness-v1|markets=BTC-USDT,ETH-USDT|"
    "predictor=runner-up-selection-score-gap|outcome=subsequent-test-fold-total-return|"
    "metric=spearman-rank-correlation|resampling=paired-noncircular-moving-block-over-folds|"
    "block=9|block-rationale=ceil(730-selection-bars/90-test-bars)|resamples=2000|"
    "confidence=0.95|seeds=BTC-USDT:20260722,ETH-USDT:20260723|candidate_count=1"
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _explicit_utc(value: object, *, label: str) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError(f"{label} must contain explicit timezone information")
    return timestamp.tz_convert("UTC")


def load_fold_evidence(path: Path, expected_sha256: str) -> list[dict[str, object]]:
    actual = file_sha256(path)
    if actual != expected_sha256:
        context = f"walk-forward report hash mismatch for {path}"
        raise RuntimeError(f"{context}: expected {expected_sha256}, got {actual}")
    report = json.loads(path.read_text(encoding="utf-8"))
    settings = report.get("settings")
    if not isinstance(settings, dict) or not isinstance(settings.get("base_config"), dict):
        raise ValueError("walk-forward report must contain settings.base_config")
    base = settings["base_config"]
    observed_settings = {
        "annualization": base.get("annualization"),
        "candidate_count": settings.get("candidate_count"),
        "non_overlapping_test_folds": settings.get("non_overlapping_test_folds"),
        "selection_bars": settings.get("selection_bars"),
        "test_bars": settings.get("test_bars"),
        "transaction_cost_bps": base.get("transaction_cost_bps"),
    }
    expected_settings = {
        "annualization": 365,
        "candidate_count": 27,
        "non_overlapping_test_folds": True,
        "selection_bars": 730,
        "test_bars": 90,
        "transaction_cost_bps": 10.0,
    }
    if observed_settings != expected_settings:
        raise ValueError(
            "walk-forward settings do not match the predeclared test: "
            f"expected {expected_settings}, got {observed_settings}"
        )

    folds = report.get("folds")
    if not isinstance(folds, list) or len(folds) < BLOCK_LENGTH:
        raise ValueError(
            "walk-forward report must contain enough folds for the declared block length"
        )

    evidence: list[dict[str, object]] = []
    previous_test_end: pd.Timestamp | None = None
    for expected_fold, fold in enumerate(folds, start=1):
        if not isinstance(fold, dict) or fold.get("fold") != expected_fold:
            raise ValueError("fold identifiers must be contiguous and one-indexed")
        if fold.get("candidates_tested") != 27:
            raise ValueError("each fold must record all 27 tested candidates")
        selection_end = _explicit_utc(fold.get("selection_end"), label="selection_end")
        test_start = _explicit_utc(fold.get("test_start"), label="test_start")
        test_end = _explicit_utc(fold.get("test_end"), label="test_end")
        if not selection_end < test_start <= test_end:
            raise ValueError("selection and test timestamps must be strictly chronological")
        if previous_test_end is not None and test_start != previous_test_end + pd.Timedelta(days=1):
            raise ValueError("test folds must be non-overlapping and contiguous")
        previous_test_end = test_end

        gap = float(fold.get("runner_up_score_gap"))
        test_metrics = fold.get("test_metrics")
        if not isinstance(test_metrics, dict):
            raise ValueError("fold must contain test_metrics")
        test_return = float(test_metrics.get("total_return"))
        if not math.isfinite(gap) or gap < 0.0 or not math.isfinite(test_return):
            raise ValueError("selection gaps and test returns must be finite")
        evidence.append(
            {
                "fold": expected_fold,
                "runner_up_score_gap": gap,
                "selection_end": selection_end.isoformat(),
                "test_end": test_end.isoformat(),
                "test_start": test_start.isoformat(),
                "test_total_return": test_return,
            }
        )
    return evidence


def spearman_rank_correlation(predictor: np.ndarray, outcome: np.ndarray) -> float:
    x = np.asarray(predictor, dtype=float)
    y = np.asarray(outcome, dtype=float)
    if x.ndim != 1 or y.ndim != 1 or len(x) != len(y) or len(x) < 2:
        raise ValueError("predictor and outcome must be equal-length one-dimensional arrays")
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError("predictor and outcome must be finite")
    x_rank = pd.Series(x).rank(method="average").to_numpy(dtype=float)
    y_rank = pd.Series(y).rank(method="average").to_numpy(dtype=float)
    x_scale = float(x_rank.std(ddof=0))
    y_scale = float(y_rank.std(ddof=0))
    if x_scale == 0.0 or y_scale == 0.0:
        raise ValueError("Spearman correlation is undefined for a constant input")
    return float(np.mean((x_rank - x_rank.mean()) * (y_rank - y_rank.mean())) / (x_scale * y_scale))


def moving_block_indices(observations: int, rng: np.random.Generator) -> np.ndarray:
    if observations < BLOCK_LENGTH:
        raise ValueError("observations must be at least BLOCK_LENGTH")
    starts = rng.integers(
        0,
        observations - BLOCK_LENGTH + 1,
        size=math.ceil(observations / BLOCK_LENGTH),
    )
    indices = np.concatenate(
        [np.arange(start, start + BLOCK_LENGTH, dtype=int) for start in starts]
    )
    return indices[:observations]


def analyze_market(evidence: list[dict[str, object]], *, seed: int) -> dict[str, object]:
    gaps = np.array([row["runner_up_score_gap"] for row in evidence], dtype=float)
    returns = np.array([row["test_total_return"] for row in evidence], dtype=float)
    point = spearman_rank_correlation(gaps, returns)
    rng = np.random.default_rng(seed)
    bootstrap = np.empty(RESAMPLES, dtype=float)
    for sample_number in range(RESAMPLES):
        indices = moving_block_indices(len(evidence), rng)
        bootstrap[sample_number] = spearman_rank_correlation(gaps[indices], returns[indices])
    alpha = 1.0 - CONFIDENCE
    lower, median, upper = np.quantile(
        bootstrap,
        [alpha / 2.0, 0.5, 1.0 - alpha / 2.0],
    )
    return {
        "bootstrap": {
            "ci_lower": float(lower),
            "ci_upper": float(upper),
            "lower_bound_positive": bool(lower > 0.0),
            "median": float(median),
            "probability_positive": float(np.mean(bootstrap > 0.0)),
        },
        "fold_count": len(evidence),
        "point_spearman": point,
        "seed": seed,
    }


def build_result(artifact_dir: Path) -> dict[str, object]:
    markets: dict[str, dict[str, object]] = {}
    all_pass = True
    for market, metadata in MARKETS.items():
        report_path = artifact_dir / market / "walk_forward.json"
        evidence = load_fold_evidence(report_path, str(metadata["report_sha256"]))
        analysis = analyze_market(evidence, seed=int(metadata["seed"]))
        analysis["fold_inputs"] = {
            "folds": [row["fold"] for row in evidence],
            "runner_up_score_gaps": [row["runner_up_score_gap"] for row in evidence],
            "test_total_returns": [row["test_total_return"] for row in evidence],
        }
        analysis["walk_forward_report_sha256"] = metadata["report_sha256"]
        markets[market] = analysis
        all_pass = all_pass and bool(analysis["bootstrap"]["lower_bound_positive"])

    verdict = (
        "supported: wider selection margins predict stronger subsequent OOS fold returns"
        if all_pass
        else "rejected: selection-score margins do not reliably predict subsequent OOS fold returns"
    )
    hypothesis = " ".join(
        [
            "For both BTC-USDT and ETH-USDT,",
            "the runner-up selection-score gap has a positive Spearman rank correlation",
            "with the immediately subsequent OOS fold total return,",
            "with both 95% moving-block-bootstrap lower bounds above zero.",
        ]
    )
    return {
        "candidate_accounting": {
            "candidate_count": CANDIDATE_COUNT,
            "searched_alternatives": [],
        },
        "canonical_signature": CANONICAL_SIGNATURE,
        "data_provenance": {
            "artifact_id": 8515812291,
            "artifact_name": "quant-research-429",
            "artifact_sha256": "9d3cfe6e86ad93dc6ed068d2a69029a099abf7a07b05de6b9abfa79c7e7710e6",
            "provider": "OKX",
            "source_base_sha": "e51ac7733597484fdc6e27c39e6eb534b7a11fd5",
            "source_head_sha": "4d8cfb358e2799290f7fa048c6c04177e63676f7",
            "source_tested_merge_sha": "7ce09c5b1b42e6e4ed5ceea113960b6fa5132fbd",
            "source_workflow_run_id": 29883888690,
            "timeframe": "1Dutc",
        },
        "hypothesis": hypothesis,
        "markets": markets,
        "method": {
            "block_length_folds": BLOCK_LENGTH,
            "block_rationale": (
                "ceil(730 selection bars / 90 test bars) = 9 folds, preserving dependence "
                "created by overlapping selection windows"
            ),
            "confidence": CONFIDENCE,
            "metric": "Spearman rank correlation",
            "resamples": RESAMPLES,
            "resampling": "paired non-circular moving blocks over ordered folds",
        },
        "verdict": verdict,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Test whether walk-forward selection-score margins predict OOS fold returns."
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
    print(f"verdict={result['verdict']}")
    for market, values in result["markets"].items():
        bootstrap = values["bootstrap"]
        print(
            f"{market}: spearman={values['point_spearman']:.6f}, "
            f"ci=[{bootstrap['ci_lower']:.6f}, {bootstrap['ci_upper']:.6f}], "
            f"p_positive={bootstrap['probability_positive']:.4f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
