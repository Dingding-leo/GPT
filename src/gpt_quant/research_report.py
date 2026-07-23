from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ResearchReportInput(Protocol):
    """Structural interface required by holdout report rendering."""

    generated_at_utc: str
    data_summary: Mapping[str, Any]
    selected_parameters: Mapping[str, Any]
    selection_score: float
    candidates_tested: int
    validation_metrics: Mapping[str, float | int]
    holdout_metrics: Mapping[str, float | int]
    benchmark_holdout_metrics: Mapping[str, float | int]
    split: Mapping[str, str]

    def to_dict(self) -> dict[str, Any]: ...


def _format_metric(value: float | int) -> str:
    if isinstance(value, int):
        return str(value)
    return f"{value:.6f}"


def write_research_report(
    result: ResearchReportInput,
    output_dir: str | Path,
) -> tuple[Path, Path]:
    """Persist a holdout result through a reporting-only structural interface."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    json_path = output / "latest.json"
    markdown_path = output / "latest.md"
    json_path.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# Quant Research Report",
        "",
        f"Generated at: `{result.generated_at_utc}`",
        "",
        (
            "> Research-only output. The executable pipeline requires explicit external "
            "market data; provenance must be retained separately."
        ),
        "",
        "## Data and split",
        "",
        f"- Observations: {result.data_summary['observations']}",
        f"- Validation: {result.split['validation_start']} to {result.split['validation_end']}",
        f"- Holdout: {result.split['holdout_start']} to {result.split['holdout_end']}",
        f"- Candidates tested: {result.candidates_tested}",
        "",
        "## Selected parameters",
        "",
        "```json",
        json.dumps(result.selected_parameters, ensure_ascii=False, indent=2, sort_keys=True),
        "```",
        "",
        f"Validation selection score: `{result.selection_score:.6f}`",
        "",
        "## Validation metrics",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ]
    lines.extend(
        f"| {key} | {_format_metric(value)} |" for key, value in result.validation_metrics.items()
    )
    lines.extend(
        [
            "",
            "## Sealed holdout metrics",
            "",
            "| Metric | Strategy | Buy & hold |",
            "|---|---:|---:|",
        ]
    )
    for key, value in result.holdout_metrics.items():
        benchmark = result.benchmark_holdout_metrics.get(key, 0.0)
        lines.append(f"| {key} | {_format_metric(value)} | {_format_metric(benchmark)} |")
    lines.extend(
        [
            "",
            "## Method notes",
            "",
            "- Signals are calculated with information available through close t.",
            "- Positions are delayed one bar before earning returns.",
            "- Each reported validation and holdout window is repriced from cash at entry.",
            "- Strategy and buy-and-hold benchmark use the same transaction-cost assumption.",
            "- Turnover incurs configurable linear transaction costs.",
            "- Candidate selection uses validation data only; the holdout block is reported once.",
            (
                "- A positive holdout result is necessary but not sufficient evidence "
                "of a tradable edge."
            ),
            "",
        ]
    )
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, markdown_path
