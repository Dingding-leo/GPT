from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pandas as pd

from .backtest import run_backtest
from .config import StrategyConfig
from .walk_forward_verify import verify_walk_forward_report as _verify_report_metrics

_ACCOUNTING_TOLERANCE = 1e-12
_METRIC_TOLERANCE = 1e-9
_BASELINE_FEE_BPS = 5.0
_HEX_DIGITS = frozenset("0123456789abcdef")


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    return value


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    if "/" in value or "\\" in value or value in {".", ".."}:
        raise ValueError(f"{label} contains an unsafe path component")
    return value


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or set(value) - _HEX_DIGITS:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _explicit_utc_timestamp(value: object, label: str) -> pd.Timestamp:
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be a valid timestamp with an explicit UTC offset") from exc
    if pd.isna(parsed) or parsed.tzinfo is None:
        raise ValueError(f"{label} must include an explicit UTC offset")
    offset = parsed.utcoffset()
    if offset is None or offset.total_seconds() != 0.0:
        raise ValueError(f"{label} must include an explicit UTC offset")
    return parsed.tz_convert("UTC")


def _timestamp_index(values: pd.Series, label: str) -> pd.DatetimeIndex:
    index = pd.DatetimeIndex(
        [_explicit_utc_timestamp(value, f"{label} row {row}") for row, value in enumerate(values)],
        name="timestamp",
    )
    if index.has_duplicates or not index.is_monotonic_increasing:
        raise ValueError(f"{label}s must be unique and increasing")
    return index


def _numeric(frame: pd.DataFrame, name: str) -> pd.Series:
    try:
        values = pd.to_numeric(frame[name], errors="raise").astype(float)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"walk-forward returns column {name} must be numeric") from exc
    if not np.isfinite(values.to_numpy(copy=False)).all():
        raise ValueError(f"walk-forward returns column {name} must contain finite values")
    return values


def _assert_accounting(label: str, actual: pd.Series, expected: pd.Series) -> None:
    actual_values = actual.to_numpy(dtype=float, copy=False)
    expected_values = expected.to_numpy(dtype=float, copy=False)
    if np.allclose(
        actual_values,
        expected_values,
        rtol=0.0,
        atol=_ACCOUNTING_TOLERANCE,
    ):
        return
    difference = np.abs(actual_values - expected_values)
    row = int(np.argmax(difference))
    raise ValueError(
        f"{label} does not match persisted return accounting at row {row}; "
        f"absolute error={difference[row]:.3g}"
    )


def _validate_explicit_timestamps(payload: Mapping[str, object], persisted: pd.DataFrame) -> None:
    data_summary = _mapping(payload.get("data_summary"), "data_summary")
    _explicit_utc_timestamp(data_summary.get("evaluation_start"), "evaluation_start")
    _explicit_utc_timestamp(data_summary.get("evaluation_end"), "evaluation_end")

    folds = payload.get("folds")
    if not isinstance(folds, list) or not folds:
        raise ValueError("walk-forward report folds must be a non-empty list")
    for ordinal, fold in enumerate(folds, start=1):
        fold_mapping = _mapping(fold, f"fold {ordinal}")
        _explicit_utc_timestamp(fold_mapping.get("test_start"), f"fold {ordinal} test_start")
        _explicit_utc_timestamp(fold_mapping.get("test_end"), f"fold {ordinal} test_end")

    _timestamp_index(persisted["timestamp"], "walk-forward returns timestamp")


def _validate_source_returns(
    output: Path,
    payload: Mapping[str, object],
    persisted: pd.DataFrame,
) -> tuple[str, str, pd.Series]:
    data_summary = _mapping(payload.get("data_summary"), "data_summary")
    provenance = _mapping(data_summary.get("provenance"), "data_summary.provenance")
    if provenance.get("provider") != "OKX":
        raise ValueError("walk-forward source verification requires OKX provenance")
    instrument_id = _required_text(provenance.get("instrument_id"), "instrument_id")
    bar = _required_text(provenance.get("bar"), "bar")
    expected_sha256 = _sha256_digest(
        provenance.get("normalized_csv_sha256"),
        "normalized_csv_sha256",
    )
    snapshot_path = output / "snapshot" / f"okx-{instrument_id}-{bar}.csv"
    if not snapshot_path.is_file():
        raise ValueError("walk-forward source verification requires the normalized OKX snapshot")
    snapshot_bytes = snapshot_path.read_bytes()
    snapshot_sha256 = _sha256_bytes(snapshot_bytes)
    if snapshot_sha256 != expected_sha256:
        raise ValueError("normalized OKX snapshot hash does not match report provenance")

    try:
        snapshot = pd.read_csv(snapshot_path, float_precision="round_trip")
    except (OSError, UnicodeError, pd.errors.ParserError) as exc:
        raise ValueError("normalized OKX snapshot is unreadable") from exc
    missing = sorted({"timestamp", "close", "confirm"} - set(snapshot.columns))
    if missing:
        raise ValueError(f"normalized OKX snapshot is missing required columns: {missing}")
    if snapshot.empty:
        raise ValueError("normalized OKX snapshot cannot be empty")

    snapshot_index = _timestamp_index(snapshot["timestamp"], "normalized OKX snapshot timestamp")
    persisted_index = _timestamp_index(persisted["timestamp"], "walk-forward returns timestamp")
    snapshot_close = pd.to_numeric(snapshot["close"], errors="raise").astype(float)
    if not np.isfinite(snapshot_close.to_numpy(copy=False)).all() or (snapshot_close <= 0.0).any():
        raise ValueError("normalized OKX snapshot close must contain finite positive values")
    confirm = pd.to_numeric(snapshot["confirm"], errors="raise")
    if not confirm.eq(1).all():
        raise ValueError("normalized OKX snapshot must contain completed candles only")

    source_close = pd.Series(
        snapshot_close.to_numpy(copy=False), index=snapshot_index, name="close"
    )
    source_positions = snapshot_index.get_indexer(persisted_index)
    if (source_positions < 0).any():
        raise ValueError(
            "walk-forward timestamps are not fully covered by the normalized OKX snapshot"
        )
    if (source_positions == 0).any():
        raise ValueError("normalized OKX snapshot lacks the preceding close for an asset return")
    if len(source_positions) > 1 and not np.equal(np.diff(source_positions), 1).all():
        raise ValueError("walk-forward returns must cover contiguous normalized OKX snapshot rows")

    aligned_close = source_close.iloc[source_positions]
    expected_asset_return = source_close.pct_change().iloc[source_positions]
    persisted_close = _numeric(persisted, "close")
    persisted_asset_return = _numeric(persisted, "asset_return")
    _assert_accounting(
        "close from immutable normalized OKX snapshot",
        persisted_close,
        aligned_close.reset_index(drop=True),
    )
    _assert_accounting(
        "asset_return from immutable normalized OKX snapshot",
        persisted_asset_return,
        expected_asset_return.reset_index(drop=True),
    )
    predecessor = snapshot_index[int(source_positions[0]) - 1].isoformat()
    return snapshot_sha256, predecessor, source_close


def _validate_selected_position_paths(
    payload: Mapping[str, object],
    persisted: pd.DataFrame,
    source_close: pd.Series,
) -> tuple[int, int]:
    folds = payload.get("folds")
    if not isinstance(folds, list) or not folds:
        raise ValueError("walk-forward report folds must be a non-empty list")

    persisted_index = _timestamp_index(
        persisted["timestamp"],
        "walk-forward returns timestamp",
    )
    fold_values = _numeric(persisted, "fold")
    if (fold_values <= 0.0).any() or not np.equal(fold_values, np.floor(fold_values)).all():
        raise ValueError("walk-forward fold identifiers must be positive integers")

    indexed = persisted.copy()
    indexed.index = persisted_index
    indexed["fold"] = fold_values.to_numpy(dtype=int, copy=False)
    indexed["target_position"] = _numeric(persisted, "target_position").to_numpy(copy=False)
    indexed["position"] = _numeric(persisted, "position").to_numpy(copy=False)

    expected_fold_ids: list[int] = []
    verified_rows = 0
    for ordinal, fold in enumerate(folds, start=1):
        fold_mapping = _mapping(fold, f"fold {ordinal}")
        fold_id_value = fold_mapping.get("fold")
        if isinstance(fold_id_value, bool) or not isinstance(fold_id_value, int):
            raise ValueError(f"fold {ordinal} identifier must be a positive integer")
        fold_id = int(fold_id_value)
        if fold_id <= 0:
            raise ValueError(f"fold {ordinal} identifier must be a positive integer")
        if fold_id in expected_fold_ids:
            raise ValueError(f"walk-forward report contains duplicate fold {fold_id}")
        expected_fold_ids.append(fold_id)

        fold_frame = indexed.loc[indexed["fold"] == fold_id]
        if fold_frame.empty:
            raise ValueError(f"walk-forward returns CSV is missing fold {fold_id}")
        test_start = _explicit_utc_timestamp(
            fold_mapping.get("test_start"),
            f"fold {fold_id} test_start",
        )
        test_end = _explicit_utc_timestamp(
            fold_mapping.get("test_end"),
            f"fold {fold_id} test_end",
        )
        if fold_frame.index[0] != test_start or fold_frame.index[-1] != test_end:
            raise ValueError(f"fold {fold_id} test boundaries do not match persisted returns")

        selected_parameters = _mapping(
            fold_mapping.get("selected_parameters"),
            f"fold {fold_id} selected_parameters",
        )
        try:
            selected_config = StrategyConfig(**dict(selected_parameters))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"fold {fold_id} selected_parameters are invalid") from exc
        if not math.isclose(
            selected_config.transaction_cost_bps,
            _BASELINE_FEE_BPS,
            rel_tol=0.0,
            abs_tol=_ACCOUNTING_TOLERANCE,
        ):
            raise ValueError(f"fold {fold_id} selected fee must match the canonical baseline")

        expected_fold = run_backtest(
            source_close.loc[:test_end],
            selected_config,
            start=test_start,
            end=test_end,
        ).frame
        if not expected_fold.index.equals(fold_frame.index):
            raise ValueError(f"fold {fold_id} source timestamps do not match persisted returns")
        _assert_accounting(
            f"fold {fold_id} source target_position",
            fold_frame["target_position"],
            expected_fold["target_position"],
        )
        _assert_accounting(
            f"fold {fold_id} source position",
            fold_frame["position"],
            expected_fold["position"],
        )
        verified_rows += len(fold_frame)

    actual_fold_ids = sorted(int(value) for value in indexed["fold"].unique())
    if actual_fold_ids != sorted(expected_fold_ids):
        raise ValueError("walk-forward report fold identifiers do not match persisted returns")
    return len(expected_fold_ids), verified_rows


def _validate_accounting(payload: Mapping[str, object], persisted: pd.DataFrame) -> None:
    settings = _mapping(payload.get("settings"), "walk-forward report settings")
    base_config = _mapping(settings.get("base_config"), "walk-forward base_config")
    fee_value = base_config.get("transaction_cost_bps")
    if isinstance(fee_value, bool) or not isinstance(fee_value, int | float):
        raise ValueError("transaction_cost_bps must be numeric")
    fee_bps = float(fee_value)
    if not math.isfinite(fee_bps) or not math.isclose(
        fee_bps,
        _BASELINE_FEE_BPS,
        rel_tol=0.0,
        abs_tol=_ACCOUNTING_TOLERANCE,
    ):
        raise ValueError("walk-forward verification requires the canonical 5 bps baseline")

    position = _numeric(persisted, "position")
    asset_return = _numeric(persisted, "asset_return")
    turnover = _numeric(persisted, "turnover")
    trading_cost = _numeric(persisted, "trading_cost")
    gross_return = _numeric(persisted, "gross_strategy_return")
    strategy_return = _numeric(persisted, "strategy_return")

    previous_position = position.shift(1, fill_value=0.0)
    expected_turnover = (position - previous_position).abs()
    expected_gross = position * asset_return
    expected_fee = expected_turnover * fee_bps / 10_000.0
    expected_net = expected_gross - expected_fee

    _assert_accounting("turnover", turnover, expected_turnover)
    _assert_accounting("gross_strategy_return", gross_return, expected_gross)
    _assert_accounting("exchange fee", trading_cost, expected_fee)
    _assert_accounting("strategy_return", strategy_return, expected_net)


def verify_walk_forward_report(output_dir: str | Path) -> dict[str, float | int | str]:
    """Fail closed on persisted 5 bps source, accounting, timestamp, metric, and hash drift."""

    output = Path(output_dir)
    report_path = output / "walk_forward.json"
    returns_path = output / "walk_forward_returns.csv"
    report_bytes = report_path.read_bytes()
    returns_bytes = returns_path.read_bytes()
    try:
        payload = json.loads(report_bytes.decode("utf-8"))
        persisted = pd.read_csv(returns_path, float_precision="round_trip")
    except (UnicodeError, json.JSONDecodeError, pd.errors.ParserError) as exc:
        raise ValueError("persisted walk-forward evidence is unreadable") from exc
    payload_mapping = _mapping(payload, "walk-forward report")

    _validate_explicit_timestamps(payload_mapping, persisted)
    (
        source_snapshot_sha256,
        source_preceding_close_timestamp,
        source_close,
    ) = _validate_source_returns(output, payload_mapping, persisted)
    selected_folds_verified, selected_rows_verified = _validate_selected_position_paths(
        payload_mapping,
        persisted,
        source_close,
    )
    _validate_accounting(payload_mapping, persisted)
    verification = _verify_report_metrics(output, tolerance=_METRIC_TOLERANCE)

    if report_bytes != report_path.read_bytes() or returns_bytes != returns_path.read_bytes():
        raise ValueError("persisted walk-forward evidence changed during verification")
    if verification["report_json_sha256"] != _sha256_bytes(report_bytes):
        raise ValueError("walk-forward report hash does not match verified bytes")
    if verification["returns_csv_sha256"] != _sha256_bytes(returns_bytes):
        raise ValueError("walk-forward returns hash does not match verified bytes")

    verification["accounting_tolerance"] = _ACCOUNTING_TOLERANCE
    verification["metric_tolerance"] = _METRIC_TOLERANCE
    verification["source_snapshot_sha256"] = source_snapshot_sha256
    verification["source_price_rows_verified"] = len(persisted)
    verification["source_preceding_close_timestamp"] = source_preceding_close_timestamp
    verification["asset_return_source"] = "immutable_normalized_okx_close_pct_change"
    verification["selected_folds_verified"] = selected_folds_verified
    verification["selected_target_rows_verified"] = selected_rows_verified
    verification["selected_position_rows_verified"] = selected_rows_verified
    verification["target_position_source"] = (
        "immutable_normalized_okx_close_and_persisted_selected_config"
    )
    return verification
