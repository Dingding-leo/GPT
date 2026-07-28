from __future__ import annotations

import math
from decimal import Decimal
from itertools import pairwise
from typing import Any

import run_large_trade_concentration_diagnostic as diagnostic


def corrected_feature_contract(
    rows: list[dict[str, Any]],
    trades: list[tuple[str, int, str, Decimal, Decimal, int]],
) -> dict[str, Any]:
    """Validate a 24H causal feature grid without unequal strict-zip inputs."""

    hours = [int(row["hour_start_ms"]) for row in rows]
    if len(rows) != 24:
        raise ValueError("diagnostic requires exactly 24 complete feature hours")
    if any(right - left != diagnostic.HOUR_MS for left, right in pairwise(hours)):
        raise ValueError("feature hours are not a complete consecutive UTC grid")

    for row in rows:
        for field in (
            "raw_flow",
            "concentration_direction",
            "candidate_target",
            "raw_flow_target",
        ):
            value = float(row[field])
            if not math.isfinite(value):
                raise ValueError(f"non-finite feature: {field}")
        if not 0.0 <= float(row["candidate_target"]) <= 1.0:
            raise ValueError("candidate target is outside long/cash bounds")
        if not 0.0 <= float(row["raw_flow_target"]) <= 1.0:
            raise ValueError("raw-flow target is outside long/cash bounds")

    cutoff = hours[len(hours) // 2]
    prefix = [trade for trade in trades if trade[5] < cutoff]
    suffix = [trade for trade in trades if trade[5] >= cutoff]
    mutated_suffix = list(suffix)
    changed = list(mutated_suffix[-1])
    changed[3] *= Decimal("1.01")
    mutated_suffix[-1] = tuple(changed)  # type: ignore[assignment]

    original_prefix = [
        row
        for row in diagnostic.feature_rows(prefix + suffix)
        if row["hour_start_ms"] < cutoff
    ]
    changed_prefix = [
        row
        for row in diagnostic.feature_rows(prefix + mutated_suffix)
        if row["hour_start_ms"] < cutoff
    ]
    if original_prefix != changed_prefix:
        raise ValueError("future trade suffix changed an earlier feature")

    return {
        "complete_24h_grid_passed": True,
        "future_suffix_invariance_passed": True,
        "target_bounds_passed": True,
        "strict_zip_length_defect_repaired": True,
    }


diagnostic.assert_feature_contract = corrected_feature_contract


if __name__ == "__main__":
    diagnostic.main()
