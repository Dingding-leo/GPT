from __future__ import annotations

import json
import os
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Protocol, runtime_checkable

_RESEARCH_REPORT_FILENAMES = {
    "json": "latest.json",
    "markdown": "latest.md",
}


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


def _publish_research_report_payloads(
    output: Path,
    payloads: Mapping[str, bytes],
) -> tuple[Path, Path]:
    paths = {name: output / filename for name, filename in _RESEARCH_REPORT_FILENAMES.items()}
    if set(payloads) != set(paths):
        raise ValueError("research report payloads must exactly match the report file set")

    output_preexisted = output.exists()
    output.mkdir(parents=True, exist_ok=True)
    previous_payloads = {
        name: path.read_bytes() if path.exists() else None for name, path in paths.items()
    }

    try:
        with TemporaryDirectory(prefix=".research-report-", dir=output) as staging_name:
            staging = Path(staging_name)
            staged_paths = {name: staging / path.name for name, path in paths.items()}
            for name, staged_path in staged_paths.items():
                staged_path.write_bytes(payloads[name])

            replaced: list[str] = []
            try:
                for name in ("json", "markdown"):
                    os.replace(staged_paths[name], paths[name])
                    replaced.append(name)
            except BaseException as commit_error:
                rollback_errors: list[str] = []
                for name in reversed(replaced):
                    destination = paths[name]
                    previous_payload = previous_payloads[name]
                    try:
                        if previous_payload is None:
                            destination.unlink(missing_ok=True)
                        else:
                            restore_path = staging / f"restore-{destination.name}"
                            restore_path.write_bytes(previous_payload)
                            os.replace(restore_path, destination)
                    except OSError as rollback_error:
                        rollback_errors.append(f"{name}: {rollback_error}")
                if rollback_errors:
                    details = "; ".join(rollback_errors)
                    raise RuntimeError(
                        f"research report commit failed and rollback was incomplete: {details}"
                    ) from commit_error
                raise
    except BaseException:
        if not output_preexisted:
            with suppress(OSError):
                output.rmdir()
        raise

    return paths["json"], paths["markdown"]


def write_research_report(
    result: ResearchReportInput,
    output_dir: str | Path,
) -> tuple[Path, Path]:
    """Persist a holdout result through a reporting-only structural interface."""

    json_payload = (
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

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
    markdown_payload = "\n".join(lines).encode("utf-8")

    return _publish_research_report_payloads(
        Path(output_dir),
        {"json": json_payload, "markdown": markdown_payload},
    )
