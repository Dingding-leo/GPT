from __future__ import annotations

import math
from collections.abc import Mapping
from numbers import Integral

import numpy as np
import pandas as pd

from .config import StrategyConfig
from .features import build_target_position

_SEARCH_PARAMETER_FIELDS = frozenset(
    {
        "momentum_lookback",
        "reversal_lookback",
        "trend_weight",
        "reversal_weight",
    }
)


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    return value


def _positive_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or int(value) <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return int(value)


def _numeric(frame: pd.DataFrame, name: str) -> pd.Series:
    try:
        values = pd.to_numeric(frame[name], errors="raise").astype(float)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"walk-forward returns column {name} must be numeric") from exc
    if not np.isfinite(values.to_numpy(copy=False)).all():
        raise ValueError(f"walk-forward returns column {name} must contain finite values")
    return values


def _strategy_config(value: object, label: str) -> StrategyConfig:
    mapping = _mapping(value, label)
    try:
        return StrategyConfig(**dict(mapping))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must define a valid StrategyConfig") from exc


def _assert_close(
    label: str,
    actual: pd.Series,
    expected: pd.Series,
    *,
    tolerance: float,
) -> None:
    actual_values = actual.to_numpy(dtype=float, copy=False)
    expected_values = expected.to_numpy(dtype=float, copy=False)
    if np.allclose(actual_values, expected_values, rtol=0.0, atol=tolerance):
        return
    difference = np.abs(actual_values - expected_values)
    row = int(np.argmax(difference))
    raise ValueError(
        f"{label} does not match immutable source regeneration at row {row}; "
        f"absolute error={difference[row]:.3g}"
    )


def _require_selected_config_compatibility(
    base: StrategyConfig,
    selected: StrategyConfig,
    *,
    fold_id: int,
) -> None:
    base_values = base.to_dict()
    selected_values = selected.to_dict()
    for name, expected in base_values.items():
        if name in _SEARCH_PARAMETER_FIELDS:
            continue
        if selected_values[name] != expected:
            raise ValueError(f"fold {fold_id} selected_parameters changes non-search field {name}")


def verify_source_bound_position_paths(
    payload: Mapping[str, object],
    persisted: pd.DataFrame,
    *,
    source_close: pd.Series,
    source_positions: np.ndarray,
    tolerance: float,
) -> dict[str, int | str]:
    """Regenerate every selected fold's target and delayed position from immutable closes."""

    if not math.isfinite(tolerance) or tolerance <= 0.0:
        raise ValueError("source position verification tolerance must be finite and positive")
    if len(persisted) != len(source_positions):
        raise ValueError("source position mapping must cover every persisted return row")
    if persisted.empty:
        raise ValueError("source position verification requires persisted return rows")
    if not isinstance(source_close.index, pd.DatetimeIndex):
        raise ValueError("source position verification requires a DatetimeIndex")
    if source_close.index.has_duplicates or not source_close.index.is_monotonic_increasing:
        raise ValueError(
            "source position verification requires unique increasing source timestamps"
        )
    if (source_positions <= 0).any():
        raise ValueError("source position verification requires a preceding signal bar")
    if (source_positions >= len(source_close)).any():
        raise ValueError("source position mapping exceeds the immutable close series")

    settings = _mapping(payload.get("settings"), "walk-forward report settings")
    base_config = _strategy_config(settings.get("base_config"), "walk-forward base_config")
    folds = payload.get("folds")
    if not isinstance(folds, list) or not folds:
        raise ValueError("walk-forward report folds must be a non-empty list")

    fold_values = _numeric(persisted, "fold")
    fold_array = fold_values.to_numpy(copy=False)
    if not np.equal(fold_array, np.floor(fold_array)).all() or (fold_array <= 0.0).any():
        raise ValueError("walk-forward fold identifiers must be positive integers")
    fold_ids = fold_array.astype(int)
    target_position = _numeric(persisted, "target_position")
    position = _numeric(persisted, "position")

    expected_fold_ids: list[int] = []
    selected_identities: list[tuple[object, ...]] = []
    target_rows_verified = 0
    position_rows_verified = 0

    for ordinal, fold_payload in enumerate(folds, start=1):
        fold = _mapping(fold_payload, f"fold {ordinal}")
        fold_id = _positive_integer(fold.get("fold"), f"fold {ordinal} identifier")
        if fold_id in expected_fold_ids:
            raise ValueError(f"walk-forward report contains duplicate fold {fold_id}")
        expected_fold_ids.append(fold_id)

        row_positions = np.flatnonzero(fold_ids == fold_id)
        if not len(row_positions):
            raise ValueError(f"walk-forward returns CSV is missing fold {fold_id}")
        if len(row_positions) > 1 and not np.equal(np.diff(row_positions), 1).all():
            raise ValueError(f"walk-forward returns rows for fold {fold_id} must be contiguous")

        fold_source_positions = source_positions[row_positions]
        if len(fold_source_positions) > 1 and not np.equal(np.diff(fold_source_positions), 1).all():
            raise ValueError(f"immutable source rows for fold {fold_id} must be contiguous")

        selected = _strategy_config(
            fold.get("selected_parameters"),
            f"fold {fold_id} selected_parameters",
        )
        _require_selected_config_compatibility(base_config, selected, fold_id=fold_id)
        selected_values = selected.to_dict()
        selected_identities.append(tuple(selected_values[name] for name in selected_values))

        prefix_end = int(fold_source_positions[-1])
        source_prefix = source_close.iloc[: prefix_end + 1]
        regenerated_target = build_target_position(source_prefix, selected)
        expected_target = regenerated_target.iloc[fold_source_positions].reset_index(drop=True)
        expected_position = regenerated_target.iloc[fold_source_positions - 1].reset_index(
            drop=True
        )

        actual_target = target_position.iloc[row_positions].reset_index(drop=True)
        actual_position = position.iloc[row_positions].reset_index(drop=True)
        _assert_close(
            f"fold {fold_id} source target_position",
            actual_target,
            expected_target,
            tolerance=tolerance,
        )
        _assert_close(
            f"fold {fold_id} source delayed position",
            actual_position,
            expected_position,
            tolerance=tolerance,
        )
        target_rows_verified += len(row_positions)
        position_rows_verified += len(row_positions)

    actual_fold_ids = sorted(set(int(value) for value in fold_ids))
    if actual_fold_ids != sorted(expected_fold_ids):
        raise ValueError("walk-forward report fold identifiers do not match persisted returns")

    model_switches = sum(
        left != right
        for left, right in zip(selected_identities, selected_identities[1:], strict=False)
    )
    return {
        "source_selected_config_folds_verified": len(expected_fold_ids),
        "source_target_position_rows_verified": target_rows_verified,
        "source_delayed_position_rows_verified": position_rows_verified,
        "source_selected_model_switches_verified": model_switches,
        "target_position_source": "immutable_normalized_okx_close_and_persisted_selected_config",
        "executed_position_timing": "selected_config_target_from_immediately_preceding_source_bar",
    }
