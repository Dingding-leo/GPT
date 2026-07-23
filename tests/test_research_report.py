from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pandas as pd

from gpt_quant import ResearchResult, StrategyConfig, run_holdout_research, write_research_report
from gpt_quant.research import write_research_report as legacy_write_research_report
from gpt_quant.research_report import (
    ResearchReportInput,
)
from gpt_quant.research_report import (
    write_research_report as module_write_research_report,
)


def _real_result(prices: pd.Series) -> ResearchResult:
    return run_holdout_research(
        prices,
        base_config=StrategyConfig(transaction_cost_bps=10.0, annualization=365),
        momentum_lookbacks=[21],
        reversal_lookbacks=[3],
        trend_weights=[0.8],
        validation_fraction=0.2,
        holdout_fraction=0.2,
        top_candidates=1,
    )


def _format_metric(value: float | int) -> str:
    if isinstance(value, int):
        return str(value)
    return f"{value:.6f}"


def _legacy_markdown(result: ResearchResult) -> str:
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
    return "\n".join(lines)


def test_report_writer_keeps_public_and_legacy_imports_compatible() -> None:
    assert write_research_report is module_write_research_report
    assert legacy_write_research_report is module_write_research_report


def test_legacy_writer_does_not_eagerly_load_reporting_module() -> None:
    package_root = Path(__file__).parents[1] / "src" / "gpt_quant"
    script = textwrap.dedent(
        f"""
        import importlib
        import sys
        import types

        package = types.ModuleType("gpt_quant")
        package.__path__ = [{str(package_root)!r}]
        sys.modules["gpt_quant"] = package

        research = importlib.import_module("gpt_quant.research")
        assert "gpt_quant.research_report" not in sys.modules

        from gpt_quant.research import write_research_report as legacy_writer

        report_module = sys.modules["gpt_quant.research_report"]
        assert legacy_writer is report_module.write_research_report

        try:
            research.missing_architecture_attribute
        except AttributeError as error:
            assert "missing_architecture_attribute" in str(error)
        else:
            raise AssertionError("unknown research attributes must fail normally")
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_report_module_has_no_research_engine_import() -> None:
    module_path = Path(__file__).parents[1] / "src" / "gpt_quant" / "research_report.py"
    spec = importlib.util.spec_from_file_location("_isolated_research_report", module_path)

    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert callable(module.write_research_report)
    assert "ResearchResult" not in module.write_research_report.__annotations__["result"]


def test_report_writer_preserves_legacy_output_from_real_okx_result(
    btc_usdt_prices: pd.Series,
    tmp_path: Path,
) -> None:
    result = _real_result(btc_usdt_prices)

    assert isinstance(result, ResearchReportInput)
    json_path, markdown_path = write_research_report(result, tmp_path)

    expected_json = (
        json.dumps(
            result.to_dict(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    assert json_path.read_text(encoding="utf-8") == expected_json
    assert markdown_path.read_text(encoding="utf-8") == _legacy_markdown(result)
