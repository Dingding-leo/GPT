from __future__ import annotations

import json
from pathlib import Path

from .walk_forward import WalkForwardResult
from .walk_forward_diagnostics import walk_forward_path_diagnostics


def _fmt(value: float | int) -> str:
    return str(value) if isinstance(value, int) else f"{value:.6f}"


def write_walk_forward_report(
    result: WalkForwardResult,
    output_dir: str | Path,
) -> dict[str, Path]:
    payload = result.to_dict()
    base_config = result.settings["base_config"]
    annualization = int(base_config["annualization"])
    path_diagnostics = walk_forward_path_diagnostics(
        result.combined_frame,
        annualization=annualization,
        minimum_position=float(base_config["min_position"]),
        maximum_absolute_position=float(base_config["max_abs_position"]),
    )
    payload["path_diagnostics"] = path_diagnostics

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": output / "walk_forward.json",
        "markdown": output / "walk_forward.md",
        "returns": output / "walk_forward_returns.csv",
    }
    paths["json"].write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    returns = result.combined_frame.copy()
    for name, frame in result.benchmark_frames.items():
        returns[f"benchmark_{name}_return"] = frame["strategy_return"].reindex(returns.index)
    returns.reset_index(names="timestamp").to_csv(paths["returns"], index=False)

    provenance = result.data_summary.get("provenance", {})
    assessment = result.benchmark_assessment
    fold_stability = result.fold_stability
    buy_hold_flags = assessment["beats_buy_and_hold"]
    buy_hold_differences = assessment["strategy_minus_buy_and_hold"]
    instrument = str(provenance.get("instrument_id", "Instrument"))
    partial_month_labels = (
        ", ".join(str(value) for value in path_diagnostics["partial_month_labels"]) or "none"
    )
    partial_year_labels = (
        ", ".join(str(value) for value in path_diagnostics["partial_year_labels"]) or "none"
    )
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
        "## Benchmark interpretation",
        "",
        f"- Beats buy-and-hold total return: `{buy_hold_flags['total_return']}`",
        f"- Beats buy-and-hold Sharpe: `{buy_hold_flags['sharpe']}`",
        f"- Beats buy-and-hold Calmar: `{buy_hold_flags['calmar']}`",
        f"- Has a smaller maximum drawdown than buy-and-hold: `{buy_hold_flags['max_drawdown']}`",
        f"- Relative drawdown reduction vs buy-and-hold: "
        f"`{assessment['relative_drawdown_reduction_vs_buy_and_hold']:.2%}`",
        f"- CAGR difference vs buy-and-hold: `{buy_hold_differences['cagr']:.2%}`",
        "",
        "## OOS fold concentration",
        "",
        f"- Passes fold-stability gate: `{fold_stability['passes']}`",
        f"- Profitable folds: `{fold_stability['profitable_folds']}` / "
        f"`{fold_stability['fold_count']}`",
        f"- Positive-fold ratio: `{fold_stability['positive_fold_ratio']:.2%}`",
        f"- Largest share of positive fold return: "
        f"`{fold_stability['max_positive_fold_share']:.2%}`",
        f"- Allowed maximum positive-fold share: "
        f"`{fold_stability['maximum_allowed_positive_fold_share']:.2%}`",
        f"- Best fold total return: `{fold_stability['best_fold_total_return']:.2%}`",
        f"- Worst fold total return: `{fold_stability['worst_fold_total_return']:.2%}`",
    ]
    if fold_stability["failure_reasons"]:
        lines.append(
            "- Failure reasons: "
            + "; ".join(str(item) for item in fold_stability["failure_reasons"])
        )

    lines += [
        "",
        "## Data",
        "",
        f"- Observations: {result.data_summary['observations']}",
        f"- Range: {result.data_summary['start']} to {result.data_summary['end']}",
        f"- OOS range: {result.data_summary['evaluation_start']} to "
        f"{result.data_summary['evaluation_end']}",
        f"- Unscored tail bars: {result.data_summary['unscored_tail_bars']}",
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

    strategy_metrics = result.aggregate_metrics
    fee_bps = float(result.settings["base_config"]["transaction_cost_bps"])
    lines += [
        "",
        "## Gross, net and exchange-fee decomposition",
        "",
        f"- Gross compounded return: `{strategy_metrics['gross_total_return']:.6f}`",
        f"- Net compounded return: `{strategy_metrics['net_total_return']:.6f}`",
        f"- Compounded exchange-fee drag: `{strategy_metrics['compounded_exchange_fee_drag']:.6f}`",
        f"- Sum of per-bar exchange-fee deductions: `{strategy_metrics['exchange_fee_sum']:.6f}`",
        f"- Gross annualized arithmetic mean: "
        f"`{strategy_metrics['gross_annualized_arithmetic_mean']:.6f}`",
        f"- Net annualized arithmetic mean: "
        f"`{strategy_metrics['net_annualized_arithmetic_mean']:.6f}`",
        f"- Declared one-way exchange fee: `{fee_bps:g} bps` per unit of absolute turnover",
        "",
        "## Position-path diagnostics",
        "",
        f"- Evaluation range: `{path_diagnostics['evaluation_start']}` to "
        f"`{path_diagnostics['evaluation_end']}`",
        f"- Configured position limits pass: `{path_diagnostics['position_limit_passes']}`; "
        f"allowed range "
        f"`[{path_diagnostics['declared_minimum_position']:.6f}, "
        f"{path_diagnostics['declared_maximum_absolute_position']:.6f}]`",
        f"- Total absolute underlying turnover: "
        f"`{path_diagnostics['total_absolute_turnover']:.6f}`",
        f"- Annualized underlying turnover: "
        f"`{path_diagnostics['annualized_instrument_turnover']:.6f}`",
        f"- Position adjustments above "
        f"`{path_diagnostics['position_adjustment_threshold']:.1e}`: "
        f"`{path_diagnostics['position_adjustment_count']}`",
        f"- Material position adjustments above "
        f"`{path_diagnostics['material_position_adjustment_threshold']:.2f}`: "
        f"`{path_diagnostics['material_position_adjustment_count']}`",
        f"- Holding episodes (completed/open): "
        f"`{path_diagnostics['holding_episode_count']}` "
        f"(`{path_diagnostics['completed_holding_episode_count']}` / "
        f"`{path_diagnostics['open_holding_episode_count']}`)",
        f"- Average / median / maximum holding duration in bars: "
        f"`{path_diagnostics['average_holding_duration_bars']:.3f}` / "
        f"`{path_diagnostics['median_holding_duration_bars']:.3f}` / "
        f"`{path_diagnostics['maximum_holding_duration_bars']}`",
        f"- Non-zero-return bar hit rate: `{path_diagnostics['bar_hit_rate']:.2%}`",
        f"- Completed holding-episode win rate: "
        f"`{path_diagnostics['completed_holding_episode_win_rate']:.2%}`",
        f"- Completed holding-episode profit factor: "
        f"`{path_diagnostics['completed_holding_episode_profit_factor']}`",
        f"- Average / current / maximum absolute exposure: "
        f"`{path_diagnostics['average_absolute_exposure']:.6f}` / "
        f"`{path_diagnostics['current_absolute_exposure']:.6f}` / "
        f"`{path_diagnostics['maximum_absolute_exposure']:.6f}`",
        f"- Worst observation return: `{path_diagnostics['worst_observation_return']:.6f}`",
        f"- 95% expected shortfall ({path_diagnostics['expected_shortfall_tail_observations']} "
        f"tail observations): `{path_diagnostics['expected_shortfall_95']:.6f}`",
        f"- Current / maximum drawdown: `{path_diagnostics['current_drawdown']:.6f}` / "
        f"`{path_diagnostics['recomputed_maximum_drawdown']:.6f}`",
        f"- Current / longest underwater duration in bars: "
        f"`{path_diagnostics['current_underwater_duration_bars']}` / "
        f"`{path_diagnostics['longest_underwater_duration_bars']}`",
        f"- Profitable / losing / flat UTC calendar months: "
        f"`{path_diagnostics['profitable_month_count']}` / "
        f"`{path_diagnostics['losing_month_count']}` / "
        f"`{path_diagnostics['flat_month_count']}`",
        f"- Partial UTC calendar months: `{path_diagnostics['partial_month_count']}` "
        f"(`{partial_month_labels}`)",
        f"- Profitable / losing / flat UTC calendar years: "
        f"`{path_diagnostics['profitable_year_count']}` / "
        f"`{path_diagnostics['losing_year_count']}` / "
        f"`{path_diagnostics['flat_year_count']}`",
        f"- Partial UTC calendar years: `{path_diagnostics['partial_year_count']}` "
        f"(`{partial_year_labels}`)",
        f"- Calendar-period return basis: `{path_diagnostics['calendar_period_return_basis']}`",
        "- These are inferred position-path transitions, not exchange orders or fills.",
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
        "- OOS fold results are used only as a post-evaluation robustness gate, not for selection.",
        f"- {instrument} is tested long/cash only, with no leverage or synthetic shorting.",
        "- Gross return is executed position multiplied by close-to-close asset return "
        "before fees.",
        "- Net return subtracts the declared exchange fee from gross return on each bar.",
        "- Compounded fee drag is gross compounded return minus net compounded return; "
        "it is not the arithmetic fee sum.",
        "- Close-price tests do not reproduce spread, slippage, impact, latency, "
        "order-book liquidity or guaranteed fills.",
        "",
    ]
    paths["markdown"].write_text("\n".join(lines), encoding="utf-8")
    return paths
