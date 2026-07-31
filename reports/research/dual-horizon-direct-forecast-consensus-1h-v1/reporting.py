"""Terminal Markdown rendering for the frozen experiment."""

from __future__ import annotations

import json
from typing import Any


def report_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Dual-horizon direct forecast consensus — terminal report",
        "",
        "```text",
        f"family          {result['family_id']}",
        f"candidate count {result['candidate_count']}",
        f"parameter grid  {result['parameter_grid']}",
        f"fee             {result['fee_bps_one_way']} bps one way",
        f"verdict         {result['verdict']}",
        "```",
        "",
        "## Strategy",
        "",
        (
            "At each completed daily 00:00 UTC bar, two rolling own-history ridge "
            "models forecast the next 24H and 168H open-to-open log returns. The "
            "candidate is long only when both forecasts are strictly positive; "
            "disagreement maps to cash. Positions execute at the next hourly open."
        ),
        "",
        "## Metrics",
        "",
    ]
    for market in result["markets"]:
        lines.extend([f"### {market['instrument']}", ""])
        lines.append("| Sample | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |")
        lines.append("|---|---|---:|---:|---:|---:|---:|---:|")
        for sample in ("train", "oos", "full"):
            for policy in ("candidate", "B1", "B0"):
                item = market["performance"][sample][policy]
                sharpe = "undefined" if item["sharpe"] is None else f"{item['sharpe']:.3f}"
                edge = (
                    "undefined"
                    if item["edge_per_turn_bps"] is None
                    else f"{item['edge_per_turn_bps']:.2f} bps"
                )
                lines.append(
                    f"| {sample} | {policy} | {item['net_return']:.2%} | {sharpe} | "
                    f"{item['max_drawdown']:.2%} | {item['turnover']:.3f} | "
                    f"{item['fees']:.2%} | {edge} |"
                )
        lines.extend(
            [
                "",
                f"Profitable OOS folds: {market['breadth']['profitable_folds']}/12; "
                f"profitable years: {market['breadth']['profitable_years']}; "
                "positive-fold concentration: "
                f"{market['breadth']['positive_fold_concentration']}.",
                "",
                f"Residual Sharpe versus B1: {market['residual_sharpe_vs_B1']}.",
                "",
                f"Accepted gates: {sum(market['gates'].values())}/{len(market['gates'])}.",
                "",
            ]
        )
    lines.extend(
        [
            "## Common uncertainty",
            "",
            "```json",
            json.dumps(result["common_bootstrap_vs_B1"], indent=2, sort_keys=True),
            "```",
            "",
            "## Verdict",
            "",
            f"`{result['verdict']}`",
            "",
            "No same-cohort rescue or retuning is authorized.",
        ]
    )
    return "\n".join(lines) + "\n"
