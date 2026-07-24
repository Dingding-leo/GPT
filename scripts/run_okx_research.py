#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd

from gpt_quant import (
    OKXCandleSnapshot,
    StrategyConfig,
    append_experiment_manifest,
    build_experiment_manifest_entry,
    fetch_okx_history_candles,
    file_sha256,
    run_walk_forward_research,
    write_okx_snapshot,
    write_walk_forward_report,
)
from gpt_quant.okx_1h import replay_persisted_okx_one_hour_snapshot

_OKX_CANDLE_FIELD_COUNT = 9


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch or replay public OKX candles and run rolling out-of-sample research."
    )
    parser.add_argument("--config", default="config/okx_research.json")
    parser.add_argument("--inst-id")
    parser.add_argument("--bar")
    parser.add_argument("--base-url")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--max-pages", type=int)
    parser.add_argument(
        "--snapshot-dir",
        help=(
            "Replay a persisted exact-byte OKX 1H snapshot instead of making a second "
            "history-candles request."
        ),
    )
    parser.add_argument("--output-dir", default="reports/okx")
    parser.add_argument(
        "--manifest-path",
        help="Append provenance to JSONL; defaults beside the instrument output.",
    )
    return parser.parse_args()


def load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _validate_okx_raw_page_schema(raw_pages: tuple[dict[str, Any], ...]) -> None:
    """Fail closed on candle-row schema drift or conflicting duplicate bars."""

    seen_rows_by_timestamp: dict[str, tuple[Any, ...]] = {}
    for page_index, page in enumerate(raw_pages):
        if not isinstance(page, Mapping):
            raise ValueError(f"OKX raw page {page_index} must be a mapping")
        payload: Mapping[str, Any] = page
        if "payload" in page:
            embedded = page.get("payload")
            if not isinstance(embedded, Mapping):
                raise ValueError(
                    f"OKX exact-byte page {page_index} is missing a mapping-valued payload"
                )
            payload = embedded
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise ValueError(f"OKX raw page {page_index} is missing a list-valued data field")
        for row_index, row in enumerate(rows):
            if not isinstance(row, list) or len(row) != _OKX_CANDLE_FIELD_COUNT:
                raise ValueError(
                    f"OKX raw page {page_index} row {row_index} must contain exactly "
                    f"{_OKX_CANDLE_FIELD_COUNT} fields"
                )
            timestamp = str(row[0])
            normalized_row = tuple(row)
            previous = seen_rows_by_timestamp.get(timestamp)
            if previous is not None and normalized_row != previous:
                raise ValueError(
                    f"OKX raw page {page_index} row {row_index} conflicts with an earlier "
                    f"row for timestamp {timestamp!r}"
                )
            seen_rows_by_timestamp.setdefault(timestamp, normalized_row)


def _utc_timestamp(value: Any, *, field: str) -> pd.Timestamp:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must be a valid timestamp") from exc
    if pd.isna(timestamp):
        raise ValueError(f"{field} must be a valid timestamp")
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _validate_requested_end_coverage(
    snapshot: OKXCandleSnapshot,
    *,
    requested_end: Any,
) -> None:
    """Require an explicit end boundary to be covered by a completed candle."""

    if requested_end is None:
        return
    end_timestamp = _utc_timestamp(requested_end, field="requested end")

    expected_step_seconds = snapshot.metadata.get("expected_step_seconds")
    if (
        isinstance(expected_step_seconds, bool)
        or not isinstance(expected_step_seconds, int)
        or expected_step_seconds <= 0
    ):
        raise ValueError("OKX snapshot is missing a valid expected bar cadence")

    latest = snapshot.candles.index[-1]
    gap = end_timestamp - latest
    if gap < pd.Timedelta(0):
        raise ValueError("OKX snapshot contains a completed candle after the requested end")
    if gap >= pd.Timedelta(seconds=expected_step_seconds):
        raise ValueError("OKX download does not cover the requested end boundary")


def _load_market_snapshot(
    *,
    inst_id: str,
    bar: str,
    base_url: str,
    start: Any,
    end: Any,
    limit: int,
    max_pages: int,
    pause_seconds: float,
    timeout: float,
    snapshot_dir: str | Path | None,
) -> tuple[OKXCandleSnapshot, str]:
    if snapshot_dir is None:
        snapshot = fetch_okx_history_candles(
            inst_id=inst_id,
            bar=bar,
            start=start,
            end=end,
            base_url=base_url,
            limit=limit,
            max_pages=max_pages,
            pause_seconds=pause_seconds,
            timeout=timeout,
        )
        return snapshot, "public_network_fetch"

    if bar != "1H":
        raise ValueError("--snapshot-dir is supported only for the canonical 1H path")
    snapshot = replay_persisted_okx_one_hour_snapshot(snapshot_dir, inst_id=inst_id)
    metadata = snapshot.metadata
    persisted_base_url = metadata.get("base_url")
    if not isinstance(persisted_base_url, str) or persisted_base_url.rstrip("/") != base_url.rstrip(
        "/"
    ):
        raise ValueError("persisted OKX 1H snapshot base URL does not match executed config")
    if start is not None and snapshot.candles.index[0] != _utc_timestamp(start, field="start"):
        raise ValueError("persisted OKX 1H snapshot start does not match executed config")
    if end is not None and snapshot.candles.index[-1] != _utc_timestamp(end, field="end"):
        raise ValueError("persisted OKX 1H snapshot end does not match executed config")
    return snapshot, "persisted_exact_bytes"


def _json_array(mapping: dict[str, Any], key: str, default: list[Any]) -> list[Any]:
    value = mapping.get(key, default)
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a JSON array")
    return value


def _build_effective_config(
    *,
    data: dict[str, Any],
    strategy: dict[str, Any],
    search: dict[str, Any],
    result_settings: dict[str, Any],
) -> dict[str, Any]:
    return {
        "data": data,
        "strategy": strategy,
        "search": search,
        "robustness": {
            "cost_multipliers": [float(value) for value in result_settings["cost_multipliers"]]
        },
    }


def _write_effective_config_snapshot(
    output: str | Path,
    effective_config: dict[str, Any],
) -> Path:
    """Persist the exact executed configuration using deterministic canonical JSON."""

    output_path = Path(output)
    output_path.mkdir(parents=True, exist_ok=True)
    config_path = output_path / "effective_config.json"
    payload = (
        json.dumps(
            effective_config,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    config_path.write_text(payload, encoding="utf-8")
    return config_path


def main() -> int:
    args = parse_args()
    experiment = load_json(args.config)
    data = experiment.get("data", {})
    inst_id = args.inst_id or str(data.get("inst_id", "BTC-USDT"))
    bar = args.bar or str(data.get("bar", "1Dutc"))
    base_url = (
        args.base_url
        or os.environ.get("OKX_BASE_URL")
        or str(data.get("base_url", "https://www.okx.com"))
    )
    start = args.start or data.get("start")
    end = args.end or data.get("end")
    max_pages = args.max_pages or int(data.get("max_pages", 40))
    limit = int(data.get("limit", 100))
    pause_seconds = float(data.get("pause_seconds", 0.12))
    timeout = float(data.get("timeout", 20.0))

    snapshot, source_mode = _load_market_snapshot(
        inst_id=inst_id,
        bar=bar,
        base_url=base_url,
        start=start,
        end=end,
        limit=limit,
        max_pages=max_pages,
        pause_seconds=pause_seconds,
        timeout=timeout,
        snapshot_dir=getattr(args, "snapshot_dir", None),
    )
    _validate_okx_raw_page_schema(snapshot.raw_pages)
    _validate_requested_end_coverage(snapshot, requested_end=end)
    output = Path(args.output_dir)
    snapshot_paths = write_okx_snapshot(snapshot, output / "snapshot")

    base_config = StrategyConfig(**experiment.get("strategy", {}))
    search = experiment.get("search", {})
    robustness = experiment.get("robustness", {})
    momentum_lookbacks = _json_array(search, "momentum_lookbacks", [30, 90, 180])
    reversal_lookbacks = _json_array(search, "reversal_lookbacks", [2, 5, 10])
    trend_weights = _json_array(search, "trend_weights", [0.55, 0.70, 0.85])
    selection_bars = search.get("selection_bars", 730)
    test_bars = search.get("test_bars", 90)
    cost_multipliers = _json_array(
        robustness,
        "cost_multipliers",
        [1.0, 2.0, 4.0],
    )
    result = run_walk_forward_research(
        snapshot.close,
        base_config=base_config,
        momentum_lookbacks=momentum_lookbacks,
        reversal_lookbacks=reversal_lookbacks,
        trend_weights=trend_weights,
        selection_bars=selection_bars,
        test_bars=test_bars,
        cost_multipliers=cost_multipliers,
        provenance=snapshot.metadata,
    )
    report_paths = write_walk_forward_report(result, output)

    metadata = snapshot.metadata
    effective_config = _build_effective_config(
        data={
            "inst_id": inst_id,
            "bar": bar,
            "base_url": str(metadata.get("base_url", base_url)).rstrip("/"),
            "start": metadata.get("requested_start", start),
            "end": metadata.get("requested_end", end),
            "limit": metadata.get("limit", limit),
            "max_pages": metadata.get("max_pages", max_pages),
            "pause_seconds": pause_seconds,
            "timeout": timeout,
            "source_mode": source_mode,
            "source_transport": metadata.get("source_transport"),
            "source_response_count": metadata.get("source_response_count"),
        },
        strategy=base_config.to_dict(),
        search={
            "momentum_lookbacks": momentum_lookbacks,
            "reversal_lookbacks": reversal_lookbacks,
            "trend_weights": trend_weights,
            "selection_bars": selection_bars,
            "test_bars": test_bars,
        },
        result_settings=result.settings,
    )
    effective_config_path = _write_effective_config_snapshot(output, effective_config)
    artifacts = {
        **snapshot_paths,
        **report_paths,
        "effective_config": effective_config_path,
    }
    manifest_entry = build_experiment_manifest_entry(
        effective_config=effective_config,
        data_hashes={
            "normalized_csv": snapshot.metadata["normalized_csv_sha256"],
            "raw_pages": snapshot.metadata["raw_pages_sha256"],
        },
        data_paths={
            "normalized_csv": snapshot_paths["candles"],
            "raw_pages": snapshot_paths["raw"],
        },
        artifact_paths=artifacts,
        candidate_count=int(result.settings["candidate_count"]),
        result_classification=result.robustness_status,
        instrument_id=inst_id,
        bar=bar,
    )
    manifest_path = (
        Path(args.manifest_path)
        if args.manifest_path
        else output.parent / "experiment-manifest.jsonl"
    )
    manifest_path, manifest_appended = append_experiment_manifest(manifest_path, manifest_entry)

    print(f"okx_base_url={base_url}")
    print(f"instrument_id={inst_id}")
    print(f"bar={bar}")
    print(f"source_mode={source_mode}")
    print(f"observations={len(snapshot.candles)}")
    print(f"data_sha256={snapshot.metadata['normalized_csv_sha256']}")
    print(f"walk_forward_folds={len(result.folds)}")
    print(f"aggregate_sharpe={result.aggregate_metrics['sharpe']:.6f}")
    print(f"aggregate_max_drawdown={result.aggregate_metrics['max_drawdown']:.6f}")
    print(f"robustness_status={result.robustness_status}")
    print(f"experiment_id={manifest_entry['experiment_id']}")
    print(f"run_id={manifest_entry['run_id']}")
    print(f"manifest_appended={str(manifest_appended).lower()}")
    print(f"manifest_path={manifest_path}")
    print(f"manifest_sha256={file_sha256(manifest_path)}")
    for name, path in artifacts.items():
        print(f"{name}_path={path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
