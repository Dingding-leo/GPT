#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from gpt_quant import (
    StrategyConfig,
    fetch_okx_history_candles,
    run_walk_forward_research,
    write_okx_snapshot,
    write_walk_forward_report,
)


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
    return parser.parse_args()


def load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


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

    snapshot = fetch_okx_history_candles(
        inst_id=inst_id,
        bar=bar,
        start=start,
        end=end,
        base_url=base_url,
        limit=int(data.get("limit", 100)),
        max_pages=max_pages,
        pause_seconds=float(data.get("pause_seconds", 0.12)),
        timeout=float(data.get("timeout", 20.0)),
    )
    output = Path(args.output_dir)
    snapshot_paths = write_okx_snapshot(snapshot, output / "snapshot")

    base_config = StrategyConfig(**experiment.get("strategy", {}))
    search = experiment.get("search", {})
    robustness = experiment.get("robustness", {})
    result = run_walk_forward_research(
        snapshot.close,
        base_config=base_config,
        momentum_lookbacks=search.get("momentum_lookbacks", [30, 90, 180]),
        reversal_lookbacks=search.get("reversal_lookbacks", [2, 5, 10]),
        trend_weights=search.get("trend_weights", [0.55, 0.70, 0.85]),
        selection_bars=int(search.get("selection_bars", 730)),
        test_bars=int(search.get("test_bars", 90)),
        cost_multipliers=robustness.get("cost_multipliers", [1.0, 2.0, 4.0]),
        provenance=snapshot.metadata,
    )
    report_paths = write_walk_forward_report(result, output)

    print(f"okx_base_url={base_url}")
    print(f"instrument_id={inst_id}")
    print(f"bar={bar}")
    print(f"observations={len(snapshot.candles)}")
    print(f"data_sha256={snapshot.metadata['normalized_csv_sha256']}")
    print(f"walk_forward_folds={len(result.folds)}")
    print(f"aggregate_sharpe={result.aggregate_metrics['sharpe']:.6f}")
    print(f"aggregate_max_drawdown={result.aggregate_metrics['max_drawdown']:.6f}")
    print(f"robustness_status={result.robustness_status}")
    for name, path in {**snapshot_paths, **report_paths}.items():
        print(f"{name}_path={path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
