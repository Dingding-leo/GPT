from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np

SOURCE = Path(__file__).with_name(
    "run_horizontal_visibility_path_simplification_opportunity_1h_v1.py"
)


def _load_source() -> ModuleType:
    spec = importlib.util.spec_from_file_location("horizontal_visibility_source", SOURCE)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load frozen horizontal-visibility source")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _eligible_opportunity_folds(
    module: ModuleType, records: list[dict[str, float]]
) -> dict[str, Any]:
    index_folds = np.array_split(np.arange(len(records)), 4)
    fold_results: list[dict[str, Any]] = []
    for fold_number, indices in enumerate(index_folds, start=1):
        subset = [records[int(index)] for index in indices]
        x = np.array([record["feature"] for record in subset])
        net = np.array([record["net_return"] for record in subset])
        adverse = np.array([record["adverse_excursion"] for record in subset])
        fold_results.append(
            {
                "fold": fold_number,
                "anchor_start": int(subset[0]["anchor"]),
                "anchor_end_exclusive": int(subset[-1]["anchor"] + module.DECISION_STEP),
                "opportunities": len(subset),
                "net_slope": module._standardized_slope(x, net),
                "adverse_slope": module._standardized_slope(x, adverse),
            }
        )
    net_positive = [max(0.0, fold["net_slope"]) for fold in fold_results]
    positive_sum = sum(net_positive)
    concentration = max(net_positive) / positive_sum if positive_sum > 0 else 1.0
    return {
        "folds": fold_results,
        "positive_net_slope_folds": sum(fold["net_slope"] > 0 for fold in fold_results),
        "positive_adverse_slope_folds": sum(
            fold["adverse_slope"] > 0 for fold in fold_results
        ),
        "largest_positive_net_fold_share": module._float(concentration),
        "fold_definition": "four fixed contiguous eligible-opportunity blocks",
    }


def main() -> None:
    module = _load_source()
    module._fold_breadth = lambda records: _eligible_opportunity_folds(module, records)
    module.main()


if __name__ == "__main__":
    main()
