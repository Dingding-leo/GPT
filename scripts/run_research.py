#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from gpt_quant import StrategyConfig, run_holdout_research, write_research_report
from gpt_quant.verified_snapshot import load_verified_price_snapshot


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run validation/holdout research on a manifest-verified real-market CSV."
    )
    parser.add_argument("--config", default="config/research.json")
    parser.add_argument(
        "--snapshot-manifest",
        help="JSON manifest binding the external real-market CSV to provenance and SHA-256.",
    )
    parser.add_argument("--csv", help=argparse.SUPPRESS)
    parser.add_argument("--timestamp-col", help=argparse.SUPPRESS)
    parser.add_argument("--close-col", help=argparse.SUPPRESS)
    parser.add_argument("--output-dir", default="reports")
    args = parser.parse_args(argv)
    if args.csv is not None:
        parser.error(
            "--csv is no longer accepted for research; create a verified snapshot manifest "
            "and use --snapshot-manifest"
        )
    if args.timestamp_col is not None or args.close_col is not None:
        parser.error("timestamp and close columns must be declared in the snapshot manifest")
    if args.snapshot_manifest is None:
        parser.error("the following arguments are required: --snapshot-manifest")
    return args


def load_json(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    snapshot = load_verified_price_snapshot(args.snapshot_manifest)
    experiment = load_json(args.config)

    base = StrategyConfig(**experiment.get("strategy", {}))
    search = experiment.get("search", {})
    result = run_holdout_research(
        snapshot.prices,
        base_config=base,
        momentum_lookbacks=search.get("momentum_lookbacks", [21, 63, 126]),
        reversal_lookbacks=search.get("reversal_lookbacks", [3, 5, 10]),
        trend_weights=search.get("trend_weights", [0.55, 0.70, 0.85]),
        validation_fraction=float(search.get("validation_fraction", 0.20)),
        holdout_fraction=float(search.get("holdout_fraction", 0.20)),
        top_candidates=int(search.get("top_candidates", 10)),
    )

    json_path, markdown_path = write_research_report(result, args.output_dir)
    print(
        "data_source=verified-snapshot:"
        f"{snapshot.provider}:{snapshot.market_type}:{snapshot.instrument_id}:{snapshot.timeframe}"
    )
    print(f"snapshot_manifest={snapshot.manifest_path}")
    print(f"data_sha256={snapshot.data_sha256}")
    print(f"selected_parameters={json.dumps(result.selected_parameters, sort_keys=True)}")
    print(f"validation_score={result.selection_score:.6f}")
    print(f"holdout_sharpe={result.holdout_metrics['sharpe']:.6f}")
    print(f"holdout_max_drawdown={result.holdout_metrics['max_drawdown']:.6f}")
    print(f"json_report={json_path}")
    print(f"markdown_report={markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
