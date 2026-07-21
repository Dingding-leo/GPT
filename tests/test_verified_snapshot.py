from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from gpt_quant.reproducibility import file_sha256
from gpt_quant.verified_snapshot import load_verified_price_snapshot

_SOURCE_METADATA_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "okx"
    / "btc-usdt-1dutc-20180111-20200628"
    / "metadata.json"
)


def _write_snapshot_bundle(
    directory: Path,
    prices: pd.Series,
) -> tuple[Path, Path, dict[str, Any]]:
    directory.mkdir(parents=True, exist_ok=True)
    selected = prices.iloc[:60]
    data_path = directory / "prices.csv"
    frame = pd.DataFrame(
        {
            "timestamp": [timestamp.isoformat() for timestamp in selected.index],
            "close": selected.to_numpy(),
        }
    )
    frame.to_csv(data_path, index=False, lineterminator="\n")

    source = json.loads(_SOURCE_METADATA_PATH.read_text(encoding="utf-8"))
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "provider": source["provider"],
        "market_type": "spot",
        "instrument_id": source["instrument_id"],
        "timeframe": source["bar"],
        "schema": {
            "columns": ["timestamp", "close"],
            "timestamp_column": "timestamp",
            "close_column": "close",
        },
        "observations": len(selected),
        "start": selected.index[0].isoformat(),
        "end": selected.index[-1].isoformat(),
        "data_path": data_path.name,
        "data_sha256": file_sha256(data_path),
        "provenance": {
            "source_workflow_run_id": source["source_workflow_run_id"],
            "source_artifact_id": source["source_artifact_id"],
            "source_artifact_sha256": source["source_artifact_sha256"],
            "source_head_sha": source["source_head_sha"],
        },
    }
    manifest_path = directory / "snapshot.json"
    _write_manifest(manifest_path, manifest)
    return manifest_path, data_path, manifest


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _rewrite_csv(
    data_path: Path, manifest_path: Path, manifest: dict[str, Any], frame: pd.DataFrame
) -> None:
    frame.to_csv(data_path, index=False, lineterminator="\n")
    manifest["data_sha256"] = file_sha256(data_path)
    _write_manifest(manifest_path, manifest)


def test_loads_manifest_bound_real_okx_prices(
    tmp_path: Path,
    btc_usdt_prices: pd.Series,
) -> None:
    manifest_path, _, manifest = _write_snapshot_bundle(tmp_path, btc_usdt_prices)

    snapshot = load_verified_price_snapshot(manifest_path)

    expected = btc_usdt_prices.iloc[:60].rename("close")
    pd.testing.assert_series_equal(snapshot.prices, expected, check_freq=False)
    assert snapshot.provider == "OKX"
    assert snapshot.market_type == "spot"
    assert snapshot.instrument_id == "BTC-USDT"
    assert snapshot.timeframe == "1Dutc"
    assert snapshot.observations == 60
    assert snapshot.data_sha256 == manifest["data_sha256"]


def test_rejects_changed_csv_bytes_before_parsing(
    tmp_path: Path,
    btc_usdt_prices: pd.Series,
) -> None:
    manifest_path, data_path, _ = _write_snapshot_bundle(tmp_path, btc_usdt_prices)
    data_path.write_bytes(data_path.read_bytes() + b"\n")

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        load_verified_price_snapshot(manifest_path)


def test_rejects_undeclared_csv_fields(
    tmp_path: Path,
    btc_usdt_prices: pd.Series,
) -> None:
    manifest_path, data_path, manifest = _write_snapshot_bundle(tmp_path, btc_usdt_prices)
    lines = data_path.read_text(encoding="utf-8").splitlines()
    data_path.write_text(
        "\n".join([lines[0], *(f"{line},undeclared" for line in lines[1:])]) + "\n",
        encoding="utf-8",
    )
    manifest["data_sha256"] = file_sha256(data_path)
    _write_manifest(manifest_path, manifest)

    with pytest.raises(ValueError, match="field count does not match manifest schema"):
        load_verified_price_snapshot(manifest_path)


def test_rejects_timezone_naive_csv_timestamp(
    tmp_path: Path,
    btc_usdt_prices: pd.Series,
) -> None:
    manifest_path, data_path, manifest = _write_snapshot_bundle(tmp_path, btc_usdt_prices)
    frame = pd.read_csv(data_path, dtype=str, keep_default_na=False)
    frame.loc[0, "timestamp"] = "2018-01-11T00:00:00"
    _rewrite_csv(data_path, manifest_path, manifest, frame)

    with pytest.raises(ValueError, match="explicit timezone"):
        load_verified_price_snapshot(manifest_path)


def test_rejects_duplicate_csv_timestamps(
    tmp_path: Path,
    btc_usdt_prices: pd.Series,
) -> None:
    manifest_path, data_path, manifest = _write_snapshot_bundle(tmp_path, btc_usdt_prices)
    frame = pd.read_csv(data_path, dtype=str, keep_default_na=False)
    frame.loc[1, "timestamp"] = frame.loc[0, "timestamp"]
    _rewrite_csv(data_path, manifest_path, manifest, frame)

    with pytest.raises(ValueError, match="timestamps must be unique"):
        load_verified_price_snapshot(manifest_path)


def test_rejects_non_increasing_csv_timestamps(
    tmp_path: Path,
    btc_usdt_prices: pd.Series,
) -> None:
    manifest_path, data_path, manifest = _write_snapshot_bundle(tmp_path, btc_usdt_prices)
    frame = pd.read_csv(data_path, dtype=str, keep_default_na=False)
    first = frame.loc[0, "timestamp"]
    frame.loc[0, "timestamp"] = frame.loc[1, "timestamp"]
    frame.loc[1, "timestamp"] = first
    _rewrite_csv(data_path, manifest_path, manifest, frame)

    with pytest.raises(ValueError, match="strictly increasing"):
        load_verified_price_snapshot(manifest_path)


@pytest.mark.parametrize("invalid_close", ["NaN", "inf", "-inf"])
def test_rejects_non_finite_csv_closes(
    tmp_path: Path,
    btc_usdt_prices: pd.Series,
    invalid_close: str,
) -> None:
    manifest_path, data_path, manifest = _write_snapshot_bundle(tmp_path, btc_usdt_prices)
    frame = pd.read_csv(data_path, dtype=str, keep_default_na=False)
    frame.loc[10, "close"] = invalid_close
    _rewrite_csv(data_path, manifest_path, manifest, frame)

    with pytest.raises(ValueError, match="closes must be finite"):
        load_verified_price_snapshot(manifest_path)


@pytest.mark.parametrize("invalid_close", ["0", "-1"])
def test_rejects_non_positive_csv_closes(
    tmp_path: Path,
    btc_usdt_prices: pd.Series,
    invalid_close: str,
) -> None:
    manifest_path, data_path, manifest = _write_snapshot_bundle(tmp_path, btc_usdt_prices)
    frame = pd.read_csv(data_path, dtype=str, keep_default_na=False)
    frame.loc[10, "close"] = invalid_close
    _rewrite_csv(data_path, manifest_path, manifest, frame)

    with pytest.raises(ValueError, match="strictly positive"):
        load_verified_price_snapshot(manifest_path)


def test_rejects_observation_count_drift(
    tmp_path: Path,
    btc_usdt_prices: pd.Series,
) -> None:
    manifest_path, _, manifest = _write_snapshot_bundle(tmp_path, btc_usdt_prices)
    manifest["observations"] += 1
    _write_manifest(manifest_path, manifest)

    with pytest.raises(ValueError, match="observation count mismatch"):
        load_verified_price_snapshot(manifest_path)


def test_rejects_timestamp_boundary_drift(
    tmp_path: Path,
    btc_usdt_prices: pd.Series,
) -> None:
    manifest_path, _, manifest = _write_snapshot_bundle(tmp_path, btc_usdt_prices)
    manifest["start"] = btc_usdt_prices.index[1].isoformat()
    _write_manifest(manifest_path, manifest)

    with pytest.raises(ValueError, match="first timestamp"):
        load_verified_price_snapshot(manifest_path)


def test_rejects_schema_drift(
    tmp_path: Path,
    btc_usdt_prices: pd.Series,
) -> None:
    manifest_path, _, manifest = _write_snapshot_bundle(tmp_path, btc_usdt_prices)
    manifest["schema"]["columns"] = ["close", "timestamp"]
    _write_manifest(manifest_path, manifest)

    with pytest.raises(ValueError, match="columns do not match"):
        load_verified_price_snapshot(manifest_path)


def test_rejects_parent_traversal(
    tmp_path: Path,
    btc_usdt_prices: pd.Series,
) -> None:
    bundle = tmp_path / "bundle"
    manifest_path, _, manifest = _write_snapshot_bundle(bundle, btc_usdt_prices)
    manifest["data_path"] = "../prices.csv"
    _write_manifest(manifest_path, manifest)

    with pytest.raises(ValueError, match="parent traversal"):
        load_verified_price_snapshot(manifest_path)


def test_rejects_symlink_escape(
    tmp_path: Path,
    btc_usdt_prices: pd.Series,
) -> None:
    bundle = tmp_path / "bundle"
    manifest_path, data_path, _ = _write_snapshot_bundle(bundle, btc_usdt_prices)
    outside_path = tmp_path / "outside.csv"
    data_path.replace(outside_path)
    data_path.symlink_to(outside_path)

    with pytest.raises(ValueError, match="outside the manifest directory"):
        load_verified_price_snapshot(manifest_path)
