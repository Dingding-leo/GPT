from __future__ import annotations

import json
from pathlib import Path

from .walk_forward import WalkForwardResult


def _fmt(value: float | int) -> str:
    return str(value) if isinstance(value, int) else f"{value:.6f}"


def write_walk_forward_report(
    result: WalkForwardResult,
    output_dir: str | Path,
) -> dict[str, Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": output / "walk_forward.json",
        "markdown": output / "walk_forward.md",
        "returns": output / "walk_forward_returns.csv",
    }
    paths["json"].write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    returns = result.combined_frame.copy()
    for name, frame in result.benchmark_frames.items():
        returns[f"benchmark_{name}_return"] = frame["strategy_return"].reindex(returns.index)
    returns.reset_index(names="timestamp").to_csv(paths["returns"], index=False)

    provenance = result.data_summary.get("provenance", {})
    lines = [
        "# OKX Walk-Forward Research Report",
        "",
        f"Generated at: `{result.generated_at_utc}`",
        "",
        "> Research only. No API key, account access, or order placement is used.",
        "",
        "## Decision",
        "",
        f"**{result.robustness_status}**",
        "",
        "## Data",
        "",
        f"- Observations: {result.data_summary['observations']}",
        f"- Range: {result.data_summary['start']} to {result.data_summary['end']}",
        f"- OOS range: {result.data_summary['evaluation_start']} to "
        f"{result.data_summary['evaluation_end']}",
    ]
    for key in (
        "provider",
        "instrument_id",
        "bar",
        "normalized_csv_sha256",
        "raw_pages_sha256",
        "incomplete_rows_removed",
        "missing_intervals",
    ):
        if key in provenance:
            lines.append(f"- {key}: `{provenance[key]}`")

    names = ["strategy", *result.benchmark_metrics]
    metrics_by_name = {"strategy": result.aggregate_metrics, **result.benchmark_metrics}
    lines += [
        "",
        "## Rolling out-of-sample performance",
        "",
        "| Metric | " + " | ".join(names) + " |",
        "|---|" + "---:|" * len(names),
    ]
    for metric in ("total_return", "cagr", "sharpe", "max_drawdown", "calmar"):
        lines.append(
            f"| {metric} | "
            + " | ".join(_fmt(metrics_by_name[name][metric]) for name in names)
            + " |"
        )

    lines += [
        "",
        "## Cost and parameter stress",
        "",
        "| Test | Total return | Sharpe | Max drawdown |",
        "|---|---:|---:|---:|",
    ]
    stress = {
        **{f"cost_{name}": value for name, value in result.cost_stress_metrics.items()},
        **{f"parameter_{name}": value for name, value in result.perturbation_metrics.items()},
    }
    for name, metrics in stress.items():
        lines.append(
            f"| {name} | {_fmt(metrics['total_return'])} | {_fmt(metrics['sharpe'])} | "
            f"{_fmt(metrics['max_drawdown'])} |"
        )

    lines += [
        "",
        "## Method notes",
        "",
        "- Only completed OKX candles (`confirm=1`) are used.",
        "- Every fold selects parameters using data ending before its test period.",
        "- Test folds do not overlap; model switches incur boundary turnover costs.",
        "- BTC-USDT spot is long/cash only, with no leverage or synthetic shorting.",
        "- Close-price tests do not reproduce order-book liquidity or guaranteed fills.",
        "",
    ]
    paths["markdown"].write_text("\n".join(lines), encoding="utf-8")
    return paths
