#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_EXPECTED_BAR = "1H"
_EXPECTED_FEE_BPS = 5.0
_EXPECTED_COST_MULTIPLIERS = [1.0]
_EXPECTED_COST_METRIC_KEYS = {"1x"}
_NUMERIC_TOLERANCE = 1e-12


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"required persisted artifact is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"persisted artifact is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"persisted artifact must contain a JSON object: {path}")
    return payload


def _require_mapping(parent: Mapping[str, Any], key: str, *, label: str) -> Mapping[str, Any]:
    value = parent.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"{label}.{key} must be a JSON object")
    return value


def _require_exact_number(value: Any, expected: float, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{label} must equal {expected}")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed != expected:
        raise ValueError(f"{label} must equal {expected}")


def _require_exact_profile(value: Any, *, label: str) -> None:
    if value != _EXPECTED_COST_MULTIPLIERS:
        raise ValueError(f"{label} must equal {_EXPECTED_COST_MULTIPLIERS}")


def _metric_values_match(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return left == right
    if isinstance(left, int | float) and isinstance(right, int | float):
        return math.isclose(
            float(left),
            float(right),
            rel_tol=0.0,
            abs_tol=_NUMERIC_TOLERANCE,
        )
    return left == right


def _require_metric_equivalence(
    aggregate: Mapping[str, Any],
    one_x: Mapping[str, Any],
) -> None:
    if set(aggregate) != set(one_x):
        raise ValueError("walk_forward 1x metric keys must exactly match aggregate metrics")
    for key in aggregate:
        if not _metric_values_match(aggregate[key], one_x[key]):
            raise ValueError(f"walk_forward 1x metric {key} does not match aggregate metrics")


def verify_intraday_1h_profile(output_dir: str | Path) -> dict[str, Any]:
    output = Path(output_dir)
    effective = _load_json_object(output / "effective_config.json")
    report = _load_json_object(output / "walk_forward.json")

    effective_data = _require_mapping(effective, "data", label="effective_config")
    effective_strategy = _require_mapping(effective, "strategy", label="effective_config")
    effective_robustness = _require_mapping(effective, "robustness", label="effective_config")

    if effective_data.get("bar") != _EXPECTED_BAR:
        raise ValueError(f"effective_config.data.bar must equal {_EXPECTED_BAR}")
    _require_exact_number(
        effective_strategy.get("transaction_cost_bps"),
        _EXPECTED_FEE_BPS,
        label="effective_config.strategy.transaction_cost_bps",
    )
    _require_exact_profile(
        effective_robustness.get("cost_multipliers"),
        label="effective_config.robustness.cost_multipliers",
    )

    settings = _require_mapping(report, "settings", label="walk_forward")
    base_config = _require_mapping(settings, "base_config", label="walk_forward.settings")
    _require_exact_number(
        base_config.get("transaction_cost_bps"),
        _EXPECTED_FEE_BPS,
        label="walk_forward.settings.base_config.transaction_cost_bps",
    )
    _require_exact_profile(
        settings.get("cost_multipliers"),
        label="walk_forward.settings.cost_multipliers",
    )

    candidate_count = settings.get("candidate_count")
    if isinstance(candidate_count, bool) or not isinstance(candidate_count, int):
        raise ValueError("walk_forward.settings.candidate_count must be a positive integer")
    if candidate_count <= 0:
        raise ValueError("walk_forward.settings.candidate_count must be a positive integer")

    cost_metrics = _require_mapping(report, "cost_stress_metrics", label="walk_forward")
    if set(cost_metrics) != _EXPECTED_COST_METRIC_KEYS:
        raise ValueError("walk_forward.cost_stress_metrics must contain exactly the 1x path")
    aggregate = _require_mapping(report, "aggregate_metrics", label="walk_forward")
    one_x = _require_mapping(cost_metrics, "1x", label="walk_forward.cost_stress_metrics")
    _require_metric_equivalence(aggregate, one_x)

    instrument_id = effective_data.get("inst_id")
    if not isinstance(instrument_id, str) or not instrument_id:
        raise ValueError("effective_config.data.inst_id must be a non-empty string")

    return {
        "instrument_id": instrument_id,
        "bar": _EXPECTED_BAR,
        "transaction_cost_bps": _EXPECTED_FEE_BPS,
        "cost_multipliers": _EXPECTED_COST_MULTIPLIERS,
        "candidate_count": candidate_count,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fail closed unless persisted canonical 1h evidence uses exactly 5 bps only."
    )
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def main() -> int:
    summary = verify_intraday_1h_profile(parse_args().output_dir)
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
