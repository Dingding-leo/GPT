from __future__ import annotations

import hashlib
import io
import json
import math
from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pandas as pd

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

    for row, value in enumerate(persisted["timestamp"]):
        _explicit_utc_timestamp(value, f"walk-forward returns timestamp row {row}")


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


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or set(value) - _HEX_DIGITS:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _git_sha(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 40 or set(value) - _HEX_DIGITS:
        raise ValueError(f"{label} must be a lowercase 40-character Git SHA")
    return value


def _single_snapshot_path(output: Path, suffix: str) -> Path:
    snapshot = output / "snapshot"
    matches = sorted(snapshot.glob(f"*{suffix}")) if snapshot.is_dir() else []
    if len(matches) != 1 or not matches[0].is_file():
        raise ValueError(f"walk-forward verification requires exactly one snapshot {suffix} file")
    return matches[0]


def _manifest_record(
    output: Path,
    *,
    instrument_id: str,
    bar: str,
    report_sha256: str,
    returns_sha256: str,
    normalized_csv_sha256: str,
    metadata_sha256: str,
) -> tuple[Path, bytes, Mapping[str, object], bytes]:
    manifest_path = output.parent / "experiment-manifest.jsonl"
    effective_config_path = output / "effective_config.json"
    if not manifest_path.is_file() or not effective_config_path.is_file():
        raise ValueError("source-bound verification requires manifest and effective configuration")
    manifest_bytes = manifest_path.read_bytes()
    effective_config_bytes = effective_config_path.read_bytes()

    records: list[Mapping[str, object]] = []
    try:
        for line_number, line in enumerate(manifest_bytes.decode("utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            records.append(_mapping(json.loads(line), f"manifest line {line_number}"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("experiment manifest is unreadable") from exc

    matches: list[Mapping[str, object]] = []
    for record in records:
        if record.get("instrument_id") != instrument_id or record.get("bar") != bar:
            continue
        artifacts = _mapping(record.get("artifact_sha256"), "manifest artifact_sha256")
        if artifacts.get("json") == report_sha256 and artifacts.get("returns") == returns_sha256:
            matches.append(record)
    if len(matches) != 1:
        raise ValueError("experiment manifest must contain exactly one matching report record")

    record = matches[0]
    data_hashes = _mapping(record.get("data_sha256"), "manifest data_sha256")
    artifact_hashes = _mapping(record.get("artifact_sha256"), "manifest artifact_sha256")
    if data_hashes.get("normalized_csv") != normalized_csv_sha256:
        raise ValueError("manifest normalized-data hash does not match source snapshot")
    if artifact_hashes.get("candles") != normalized_csv_sha256:
        raise ValueError("manifest candle artifact hash does not match source snapshot")
    if artifact_hashes.get("metadata") != metadata_sha256:
        raise ValueError("manifest metadata artifact hash does not match source snapshot")

    config_sha256 = _sha256_bytes(effective_config_bytes)
    if _sha256_digest(record.get("config_sha256"), "manifest config_sha256") != config_sha256:
        raise ValueError("manifest configuration hash does not match effective configuration")
    if artifact_hashes.get("effective_config") != config_sha256:
        raise ValueError("manifest effective-config artifact hash does not match configuration")
    _git_sha(record.get("code_commit"), "manifest code_commit")
    return manifest_path, manifest_bytes, record, effective_config_bytes


def _validate_source_returns(
    output: Path,
    payload: Mapping[str, object],
    persisted: pd.DataFrame,
    *,
    report_sha256: str,
    returns_sha256: str,
) -> dict[str, int | str]:
    data_summary = _mapping(payload.get("data_summary"), "data_summary")
    provenance = _mapping(data_summary.get("provenance"), "data_summary.provenance")
    provider = provenance.get("provider")
    if provider != "OKX":
        raise ValueError("source-bound verification requires OKX provenance")
    instrument_id = _required_text(provenance.get("instrument_id"), "instrument_id")
    bar = _required_text(provenance.get("bar"), "bar")

    metadata_path = _single_snapshot_path(output, ".metadata.json")
    candles_path = metadata_path.with_name(
        f"{metadata_path.name.removesuffix('.metadata.json')}.csv"
    )
    if not candles_path.is_file():
        raise ValueError("source-bound verification requires the normalized OKX snapshot CSV")
    metadata_bytes = metadata_path.read_bytes()
    candles_bytes = candles_path.read_bytes()
    try:
        metadata = _mapping(
            json.loads(metadata_bytes.decode("utf-8")),
            "OKX snapshot metadata",
        )
        source = pd.read_csv(io.BytesIO(candles_bytes))
    except (UnicodeError, json.JSONDecodeError, pd.errors.ParserError) as exc:
        raise ValueError("OKX source snapshot is unreadable") from exc

    normalized_csv_sha256 = _sha256_bytes(candles_bytes)
    metadata_sha256 = _sha256_bytes(metadata_bytes)
    if metadata.get("provider") != "OKX":
        raise ValueError("OKX snapshot metadata provider is invalid")
    if metadata.get("instrument_id") != instrument_id or metadata.get("bar") != bar:
        raise ValueError("OKX snapshot metadata does not match report provenance")
    if (
        _sha256_digest(
            metadata.get("normalized_csv_sha256"),
            "OKX metadata normalized_csv_sha256",
        )
        != normalized_csv_sha256
    ):
        raise ValueError("OKX snapshot metadata hash does not match normalized CSV bytes")
    if (
        _sha256_digest(
            provenance.get("normalized_csv_sha256"),
            "report provenance normalized_csv_sha256",
        )
        != normalized_csv_sha256
    ):
        raise ValueError("report provenance hash does not match normalized OKX snapshot")

    missing_columns = sorted({"timestamp", "close", "confirm"} - set(source.columns))
    if missing_columns:
        raise ValueError(
            f"normalized OKX snapshot is missing required columns: {missing_columns}"
        )
    source_timestamps = [
        _explicit_utc_timestamp(value, f"OKX snapshot timestamp row {row}")
        for row, value in enumerate(source["timestamp"])
    ]
    source_index = pd.DatetimeIndex(source_timestamps, name="timestamp")
    if source_index.has_duplicates or not source_index.is_monotonic_increasing:
        raise ValueError("normalized OKX snapshot timestamps must be unique and increasing")
    expected_step = metadata.get("expected_step_seconds")
    if isinstance(expected_step, bool) or not isinstance(expected_step, int) or expected_step <= 0:
        raise ValueError("OKX snapshot metadata expected_step_seconds must be positive")
    if len(source_index) > 1:
        source_deltas = source_index.to_series().diff().iloc[1:].dt.total_seconds()
        if not source_deltas.eq(float(expected_step)).all():
            raise ValueError("normalized OKX snapshot timestamps violate the declared cadence")
    if metadata.get("missing_intervals") != 0:
        raise ValueError("OKX snapshot metadata must declare zero missing intervals")
    source_close = _numeric(source, "close")
    if (source_close <= 0.0).any():
        raise ValueError("normalized OKX snapshot closes must be strictly positive")
    source_confirm = _numeric(source, "confirm")
    if not source_confirm.eq(1.0).all():
        raise ValueError("normalized OKX snapshot must contain completed candles only")
    source_close.index = source_index

    persisted_index = pd.DatetimeIndex(
        [
            _explicit_utc_timestamp(value, f"walk-forward returns timestamp row {row}")
            for row, value in enumerate(persisted["timestamp"])
        ],
        name="timestamp",
    )
    source_positions = source_index.get_indexer(persisted_index)
    if (source_positions < 0).any():
        raise ValueError("persisted returns contain timestamps absent from the OKX snapshot")
    if (source_positions == 0).any():
        raise ValueError("OKX snapshot lacks the preceding close for a persisted asset return")

    aligned_close = source_close.iloc[source_positions]
    aligned_close.index = persisted.index
    expected_asset_return = source_close.pct_change().iloc[source_positions]
    expected_asset_return.index = persisted.index
    _assert_accounting(
        "close from immutable OKX snapshot",
        _numeric(persisted, "close"),
        aligned_close,
    )
    _assert_accounting(
        "asset_return from immutable OKX closes",
        _numeric(persisted, "asset_return"),
        expected_asset_return,
    )

    manifest_path, manifest_bytes, record, effective_config_bytes = _manifest_record(
        output,
        instrument_id=instrument_id,
        bar=bar,
        report_sha256=report_sha256,
        returns_sha256=returns_sha256,
        normalized_csv_sha256=normalized_csv_sha256,
        metadata_sha256=metadata_sha256,
    )
    if candles_bytes != candles_path.read_bytes() or metadata_bytes != metadata_path.read_bytes():
        raise ValueError("OKX source snapshot changed during verification")
    if manifest_bytes != manifest_path.read_bytes():
        raise ValueError("experiment manifest changed during verification")
    if effective_config_bytes != (output / "effective_config.json").read_bytes():
        raise ValueError("effective configuration changed during verification")

    first_source_position = int(source_positions[0])
    return {
        "source_provider": "OKX",
        "source_instrument_id": instrument_id,
        "source_bar": bar,
        "source_normalized_csv_sha256": normalized_csv_sha256,
        "source_metadata_sha256": metadata_sha256,
        "source_manifest_sha256": _sha256_bytes(manifest_bytes),
        "source_config_sha256": str(record["config_sha256"]),
        "source_code_commit": str(record["code_commit"]),
        "source_close_observations": len(source_close),
        "source_price_rows_verified": len(persisted),
        "source_return_rows_verified": len(persisted),
        "asset_return_source": "immutable_normalized_okx_close_pct_change",
        "source_preceding_close_timestamp": source_index[first_source_position - 1].isoformat(),
    }


def verify_walk_forward_report(output_dir: str | Path) -> dict[str, float | int | str]:
    """Fail closed on source-bound 5 bps accounting, metric, timestamp, and hash drift."""

    output = Path(output_dir)
    report_path = output / "walk_forward.json"
    returns_path = output / "walk_forward_returns.csv"
    report_bytes = report_path.read_bytes()
    returns_bytes = returns_path.read_bytes()
    try:
        payload = json.loads(report_bytes.decode("utf-8"))
        persisted = pd.read_csv(io.BytesIO(returns_bytes))
    except (UnicodeError, json.JSONDecodeError, pd.errors.ParserError) as exc:
        raise ValueError("persisted walk-forward evidence is unreadable") from exc
    payload_mapping = _mapping(payload, "walk-forward report")

    _validate_explicit_timestamps(payload_mapping, persisted)
    _validate_accounting(payload_mapping, persisted)
    verification = _verify_report_metrics(output, tolerance=_METRIC_TOLERANCE)
    source_verification = _validate_source_returns(
        output,
        payload_mapping,
        persisted,
        report_sha256=_sha256_bytes(report_bytes),
        returns_sha256=_sha256_bytes(returns_bytes),
    )

    if report_bytes != report_path.read_bytes() or returns_bytes != returns_path.read_bytes():
        raise ValueError("persisted walk-forward evidence changed during verification")
    if verification["report_json_sha256"] != _sha256_bytes(report_bytes):
        raise ValueError("walk-forward report hash does not match verified bytes")
    if verification["returns_csv_sha256"] != _sha256_bytes(returns_bytes):
        raise ValueError("walk-forward returns hash does not match verified bytes")

    verification.update(source_verification)
    verification["accounting_tolerance"] = _ACCOUNTING_TOLERANCE
    verification["metric_tolerance"] = _METRIC_TOLERANCE
    return verification
