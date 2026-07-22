from __future__ import annotations

import itertools
import json
import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from numbers import Integral, Real
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .backtest import run_backtest
from .benchmarks import buy_and_hold_frame
from .config import StrategyConfig
from .data import validate_prices
from .metrics import performance_metrics


@dataclass(frozen=True, slots=True)
class ResearchResult:
    generated_at_utc: str
    data_summary: dict[str, Any]
    selected_parameters: dict[str, Any]
    selection_score: float
    candidates_tested: int
    validation_metrics: dict[str, float | int]
    holdout_metrics: dict[str, float | int]
    benchmark_holdout_metrics: dict[str, float | int]
    split: dict[str, str]
    candidate_ranking: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at_utc": self.generated_at_utc,
            "data_summary": self.data_summary,
            "selected_parameters": self.selected_parameters,
            "selection_score": self.selection_score,
            "candidates_tested": self.candidates_tested,
            "validation_metrics": self.validation_metrics,
            "holdout_metrics": self.holdout_metrics,
            "benchmark_holdout_metrics": self.benchmark_holdout_metrics,
            "split": self.split,
            "candidate_ranking": self.candidate_ranking,
        }


def _selection_score(metrics: dict[str, float | int]) -> float:
    """Penalized validation score; used only for model selection."""

    sharpe = float(metrics["sharpe"])
    calmar = float(metrics["calmar"])
    drawdown = abs(float(metrics["max_drawdown"]))
    turnover = float(metrics["annualized_turnover"])
    return sharpe + 0.20 * calmar - 0.50 * drawdown - 0.01 * turnover


def _run_window_from_cash(
    prices: pd.Series,
    config: StrategyConfig,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Retain signal warmup while repricing the reported window from cash."""

    frame = run_backtest(prices, config, start=start, end=end).frame.copy()
    first = frame.index[0]
    entry_turnover = abs(float(frame.at[first, "position"]))
    frame.at[first, "turnover"] = entry_turnover
    frame.at[first, "trading_cost"] = entry_turnover * config.transaction_cost_bps / 10_000.0
    frame.at[first, "strategy_return"] = float(frame.at[first, "position"]) * float(
        frame.at[first, "asset_return"]
    ) - float(frame.at[first, "trading_cost"])
    frame["nav"] = (1.0 + frame["strategy_return"]).cumprod()
    return frame


def _validated_candidate_lookback(
    value: object,
    *,
    label: str,
    minimum: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise ValueError(f"{label} candidates must be integers")
    parsed = int(value)
    if parsed < minimum:
        raise ValueError(f"{label} candidates must be at least {minimum}")
    return parsed


def _validated_trend_weight(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("trend weight candidates must be finite real numbers")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("trend weight candidates must be finite real numbers")
    if not 0.0 <= parsed <= 1.0:
        raise ValueError("trend weights must be in [0, 1]")
    return parsed


def _validated_candidate_grid(
    momentum_lookbacks: Iterable[int],
    reversal_lookbacks: Iterable[int],
    trend_weights: Iterable[float],
) -> tuple[list[int], list[int], list[float]]:
    momentum = [
        _validated_candidate_lookback(
            value,
            label="momentum lookback",
            minimum=2,
        )
        for value in momentum_lookbacks
    ]
    reversal = [
        _validated_candidate_lookback(
            value,
            label="reversal lookback",
            minimum=1,
        )
        for value in reversal_lookbacks
    ]
    weights = [_validated_trend_weight(value) for value in trend_weights]
    if not momentum or not reversal or not weights:
        raise ValueError("candidate grid cannot be empty")
    return momentum, reversal, weights


def _validated_top_candidates(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise ValueError("top_candidates must be a positive integer")
    parsed = int(value)
    if parsed < 1:
        raise ValueError("top_candidates must be a positive integer")
    return parsed


def run_holdout_research(
    prices: pd.Series,
    *,
    base_config: StrategyConfig,
    momentum_lookbacks: Iterable[int],
    reversal_lookbacks: Iterable[int],
    trend_weights: Iterable[float],
    validation_fraction: float = 0.20,
    holdout_fraction: float = 0.20,
    top_candidates: int = 10,
) -> ResearchResult:
    """Select on a validation block and evaluate once on a sealed holdout block."""

    validated_top_candidates = _validated_top_candidates(top_candidates)
    clean = validate_prices(prices, minimum_rows=600)
    if not 0.05 <= validation_fraction <= 0.40:
        raise ValueError("validation_fraction must be in [0.05, 0.40]")
    if not 0.05 <= holdout_fraction <= 0.40:
        raise ValueError("holdout_fraction must be in [0.05, 0.40]")
    if validation_fraction + holdout_fraction >= 0.80:
        raise ValueError("validation and holdout fractions leave too little history")

    validated_momentum, validated_reversal, validated_weights = _validated_candidate_grid(
        momentum_lookbacks,
        reversal_lookbacks,
        trend_weights,
    )

    n = len(clean)
    holdout_start_idx = int(n * (1.0 - holdout_fraction))
    validation_start_idx = int(n * (1.0 - holdout_fraction - validation_fraction))
    validation_start = clean.index[validation_start_idx]
    validation_end = clean.index[holdout_start_idx - 1]
    holdout_start = clean.index[holdout_start_idx]

    candidates: list[tuple[float, StrategyConfig, dict[str, float | int]]] = []
    for momentum, reversal, trend_weight in itertools.product(
        validated_momentum,
        validated_reversal,
        validated_weights,
    ):
        config = base_config.with_overrides(
            momentum_lookback=momentum,
            reversal_lookback=reversal,
            trend_weight=trend_weight,
            reversal_weight=round(1.0 - trend_weight, 10),
        )
        validation_frame = _run_window_from_cash(
            clean,
            config,
            start=validation_start,
            end=validation_end,
        )
        metrics = performance_metrics(validation_frame, annualization=config.annualization)
        score = _selection_score(metrics)
        if np.isfinite(score):
            candidates.append((float(score), config, metrics))

    if not candidates:
        raise RuntimeError("no finite candidate scores were produced")

    candidates.sort(key=lambda item: item[0], reverse=True)
    best_score, best_config, best_validation_metrics = candidates[0]

    holdout_frame = _run_window_from_cash(clean, best_config, start=holdout_start)
    holdout_metrics = performance_metrics(
        holdout_frame,
        annualization=best_config.annualization,
    )
    benchmark_frame = buy_and_hold_frame(
        clean,
        transaction_cost_bps=best_config.transaction_cost_bps,
        start=holdout_start,
    )
    benchmark_metrics = performance_metrics(
        benchmark_frame,
        annualization=best_config.annualization,
    )

    ranking = [
        {
            "rank": rank,
            "score": score,
            "parameters": config.to_dict(),
            "validation_metrics": metrics,
        }
        for rank, (score, config, metrics) in enumerate(
            candidates[:validated_top_candidates],
            start=1,
        )
    ]

    return ResearchResult(
        generated_at_utc=datetime.now(UTC).isoformat(),
        data_summary={
            "observations": n,
            "start": clean.index[0].isoformat(),
            "end": clean.index[-1].isoformat(),
            "price_name": str(clean.name),
        },
        selected_parameters=best_config.to_dict(),
        selection_score=best_score,
        candidates_tested=len(candidates),
        validation_metrics=best_validation_metrics,
        holdout_metrics=holdout_metrics,
        benchmark_holdout_metrics=benchmark_metrics,
        split={
            "validation_start": validation_start.isoformat(),
            "validation_end": validation_end.isoformat(),
            "holdout_start": holdout_start.isoformat(),
            "holdout_end": clean.index[-1].isoformat(),
        },
        candidate_ranking=ranking,
    )


def _format_metric(value: float | int) -> str:
    if isinstance(value, int):
        return str(value)
    return f"{value:.6f}"


def write_research_report(result: ResearchResult, output_dir: str | Path) -> tuple[Path, Path]:
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
