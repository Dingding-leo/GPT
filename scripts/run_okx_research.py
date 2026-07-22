#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from gpt_quant import (
    StrategyConfig,
    append_experiment_manifest,
    build_experiment_manifest_entry,
    fetch_okx_history_candles,
    file_sha256,
    run_walk_forward_research,
    write_okx_snapshot,
    write_walk_forward_report,
)

_OKX_CANDLE_FIELD_COUNT = 9


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch public OKX candles and run rolling out-of-sample research."
    )
    parser.add_argument("--config", default="config/okx_research.json")
    parser.add_argument("--inst-id")
    parser.add_argument("--bar")
    parser.add_argument("--base-url")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--max-pages", type=int)
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
        rows = page.get("data")
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
    _validate_okx_raw_page_schema(snapshot.raw_pages)
    output = Path(args.output_dir)
    snapshot_paths = write_okx_snapshot(snapshot, output / "snapshot")

    base_config = StrategyConfig(**experiment.get("strategy", {}))
    search = experiment.get("search", {})
    robustness = experiment.get("robustness", {})
    momentum_lookbacks = [int(value) for value in search.get("momentum_lookbacks", [30, 90, 180])]
    reversal_lookbacks = [int(value) for value in search.get("reversal_lookbacks", [2, 5, 10])]
    trend_weights = [float(value) for value in search.get("trend_weights", [0.55, 0.70, 0.85])]
    selection_bars = int(search.get("selection_bars", 730))
    test_bars = int(search.get("test_bars", 90))
    cost_multipliers = [
        float(value) for value in robustness.get("cost_multipliers", [1.0, 2.0, 4.0])
    ]
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

    effective_config = _build_effective_config(
        data={
            "inst_id": inst_id,
            "bar": bar,
            "base_url": base_url.rstrip("/"),
            "start": start,
            "end": end,
            "limit": limit,
            "max_pages": max_pages,
            "pause_seconds": pause_seconds,
            "timeout": timeout,
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
    artifacts = {**snapshot_paths, **report_paths}
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
