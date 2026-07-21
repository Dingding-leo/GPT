#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from gpt_quant import (
    StrategyConfig,
    load_price_csv,
    run_holdout_research,
    write_research_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run validation/holdout research on an explicit real-market CSV."
    )
    parser.add_argument("--config", default="config/research.json")
    parser.add_argument(
        "--csv",
        required=True,
        help="Real-market timestamp/close CSV. Synthetic or generated inputs are not supported.",
    )
    parser.add_argument("--timestamp-col", default="timestamp")
    parser.add_argument("--close-col", default="close")
    parser.add_argument("--output-dir", default="reports")
    return parser.parse_args()


def load_json(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    args = parse_args()
    experiment = load_json(args.config)
    prices = load_price_csv(
        args.csv,
        timestamp_col=args.timestamp_col,
        close_col=args.close_col,
    )

    base = StrategyConfig(**experiment.get("strategy", {}))
    search = experiment.get("search", {})
    result = run_holdout_research(
        prices,
        base_config=base,
        momentum_lookbacks=search.get("momentum_lookbacks", [21, 63, 126]),
        reversal_lookbacks=search.get("reversal_lookbacks", [3, 5, 10]),
        trend_weights=search.get("trend_weights", [0.55, 0.70, 0.85]),
        validation_fraction=float(search.get("validation_fraction", 0.20)),
        holdout_fraction=float(search.get("holdout_fraction", 0.20)),
        top_candidates=int(search.get("top_candidates", 10)),
    )

    json_path, markdown_path = write_research_report(result, args.output_dir)
    print(f"data_source=csv:{args.csv}")
    print(f"selected_parameters={json.dumps(result.selected_parameters, sort_keys=True)}")
    print(f"validation_score={result.selection_score:.6f}")
    print(f"holdout_sharpe={result.holdout_metrics['sharpe']:.6f}")
    print(f"holdout_max_drawdown={result.holdout_metrics['max_drawdown']:.6f}")
    print(f"json_report={json_path}")
    print(f"markdown_report={markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
