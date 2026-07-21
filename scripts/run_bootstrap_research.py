#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from gpt_quant.bootstrap import paired_moving_block_bootstrap

BENCHMARK_COLUMNS = {
    "buy_and_hold": "benchmark_buy_and_hold_return",
    "volatility_targeted_long": "benchmark_volatility_targeted_long_return",
    "simple_trend_long_cash": "benchmark_simple_trend_long_cash_return",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run paired moving-block bootstrap inference on walk-forward returns."
    )
    parser.add_argument("--returns-csv", required=True)
    parser.add_argument("--instrument", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--block-length", type=int, default=20)
    parser.add_argument("--resamples", type=int, default=2_000)
    parser.add_argument("--confidence", type=float, default=0.95)
    parser.add_argument("--annualization", type=int, default=365)
    parser.add_argument("--seed", type=int, default=20260722)
    parser.add_argument("--source-run-id")
    parser.add_argument("--source-artifact-id")
    parser.add_argument("--source-head-sha")
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# Paired moving-block bootstrap: {payload['instrument']}",
        "",
        "## Hypothesis",
        "",
        (
            "The walk-forward strategy improves both Calmar and maximum drawdown versus every "
            "tested benchmark after preserving serial dependence with paired moving-block "
            "resampling."
        ),
        "",
        f"**Verdict:** `{payload['result']['hypothesis']['verdict']}`",
        "",
        "## Provenance",
        "",
        f"- returns CSV SHA-256: `{payload['provenance']['returns_csv_sha256']}`",
        f"- source workflow run: `{payload['provenance']['source_run_id']}`",
        f"- source artifact: `{payload['provenance']['source_artifact_id']}`",
        f"- source head SHA: `{payload['provenance']['source_head_sha']}`",
        "",
        "## Bootstrap settings",
        "",
        f"- observations: {payload['result']['settings']['observations']}",
        f"- block length: {payload['result']['settings']['block_length']}",
        f"- paired resamples: {payload['result']['settings']['resamples']}",
        f"- confidence level: {payload['result']['settings']['confidence']:.3f}",
        f"- seed: {payload['result']['settings']['seed']}",
        "",
        "## Benchmark-relative uncertainty",
        "",
        "| Benchmark | Metric | Observed delta | CI lower | CI upper | P(delta > 0) | Supported |",
        "|---|---:|---:|---:|---:|---:|:---:|",
    ]
    comparisons = payload["result"]["comparisons"]
    for benchmark, metrics in comparisons.items():
        for metric in ("calmar", "max_drawdown", "cagr", "sharpe"):
            values = metrics[metric]
            lines.append(
                "| {benchmark} | {metric} | {observed_delta:.6f} | {ci_lower:.6f} | "
                "{ci_upper:.6f} | {probability_positive:.3f} | {supported} |".format(
                    benchmark=benchmark,
                    metric=metric,
                    supported="yes" if values["lower_bound_positive"] else "no",
                    **values,
                )
            )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            payload["interpretation"],
            "",
            "BTC-USDT and ETH-USDT are development markets. This analysis quantifies uncertainty "
            "for existing evidence and does not restore untouched-holdout status.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    returns_path = Path(args.returns_csv)
    frame = pd.read_csv(returns_path)
    result = paired_moving_block_bootstrap(
        frame,
        strategy_column="strategy_return",
        benchmark_columns=BENCHMARK_COLUMNS,
        block_length=args.block_length,
        resamples=args.resamples,
        confidence=args.confidence,
        annualization=args.annualization,
        seed=args.seed,
    )
    support = result.hypothesis["metric_support"]
    if support["max_drawdown"] and not support["calmar"]:
        interpretation = (
            "The lower-drawdown result survives the paired block bootstrap against all tested "
            "benchmarks, but the Calmar advantage does not. The existing risk-control label is "
            "therefore only partially supported and must not be strengthened to a statistically "
            "confirmed Calmar advantage."
        )
    elif result.hypothesis["verdict"] == "supported":
        interpretation = (
            "Both lower drawdown and higher Calmar have positive lower confidence bounds against "
            "all tested benchmarks under the declared block-bootstrap specification."
        )
    else:
        interpretation = (
            "The joint lower-drawdown and higher-Calmar hypothesis is not supported against every "
            "tested benchmark under the declared block-bootstrap specification."
        )

    payload = {
        "instrument": args.instrument,
        "hypothesis_signature": (
            "paired-mbb-v1|development-market|strategy-vs-three-benchmarks|"
            f"metrics=calmar,max_drawdown|block={args.block_length}|"
            f"resamples={args.resamples}|seed={args.seed}"
        ),
        "provenance": {
            "returns_csv": str(returns_path),
            "returns_csv_sha256": _sha256(returns_path),
            "source_run_id": args.source_run_id,
            "source_artifact_id": args.source_artifact_id,
            "source_head_sha": args.source_head_sha,
        },
        "result": result.to_dict(),
        "interpretation": interpretation,
    }

    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / "bootstrap.json"
    markdown_path = output / "bootstrap.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(_markdown(payload), encoding="utf-8")

    print(f"instrument={args.instrument}")
    print(f"hypothesis_verdict={result.hypothesis['verdict']}")
    print(f"bootstrap_json_path={json_path}")
    print(f"bootstrap_markdown_path={markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
