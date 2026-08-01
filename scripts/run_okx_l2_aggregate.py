from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

import run_okx_l2_bid_replenishment_diagnostic as core

_ORIGINAL_FETCH = core.fetch_okx_one_hour_candles


def _fetch_with_extended_safety(**kwargs: Any):
    """Fetch the frozen 1H label interval with a non-economic page margin.

    The canonical OKX reader starts at the provider's newest completed candle
    and walks backward. The requested timestamps, venue, bar, values and exact
    response evidence are unchanged; the larger bound only allows traversal
    across post-sample history before reaching the frozen January 2025 start.
    """

    kwargs["safety_pages"] = 256
    return _ORIGINAL_FETCH(**kwargs)


def _bucket_analysis(state: np.ndarray, target: np.ndarray) -> dict[str, Any]:
    """Evaluate the five frozen equal-count state buckets in adjacent order."""

    order = np.argsort(state, kind="mergesort")
    bucket = np.empty(len(state), dtype=int)
    for rank, position in enumerate(order):
        bucket[position] = min(4, rank * 5 // len(state))
    means = [float(np.mean(target[bucket == index])) for index in range(5)]
    favourable = sum(right > left for left, right in zip(means, means[1:]))
    return {
        "means": means,
        "favourable_adjacent_changes": favourable,
        "bucket_index_correlation": core.correlation(
            np.arange(5, dtype=float), np.asarray(means)
        ),
        "counts": [int((bucket == index).sum()) for index in range(5)],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest-path", type=Path, required=True)
    parser.add_argument("--days-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    core.fetch_okx_one_hour_candles = _fetch_with_extended_safety
    core.bucket_analysis = _bucket_analysis
    result = core.aggregate(args.manifest_path, args.days_root, args.output_dir)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
