from __future__ import annotations

import itertools
import math
from collections import Counter
from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from numbers import Integral, Real
from typing import Any

import numpy as np
import pandas as pd

from .backtest import run_backtest
from .benchmarks import (
    buy_and_hold_frame,
    simple_trend_long_cash_frame,
    volatility_targeted_long_frame,
)
from .config import StrategyConfig
from .data import validate_prices
from .metrics import performance_metrics

_MIN_PROVISIONAL_FOLDS = 3
_MAX_POSITIVE_FOLD_SHARE = 0.50


@dataclass(frozen=True, slots=True)
class WalkForwardResult:
    generated_at_utc: str
    data_summary: dict[str, Any]
    settings: dict[str, Any]
    folds: list[dict[str, Any]]
    aggregate_metrics: dict[str, float | int]
    benchmark_metrics: dict[str, dict[str, float | int]]
    benchmark_assessment: dict[str, Any]
    cost_stress_metrics: dict[str, dict[str, float | int]]
    perturbation_metrics: dict[str, dict[str, float | int]]
    parameter_stability: dict[str, Any]
    fold_stability: dict[str, Any]
    robustness_status: str
    combined_frame: pd.DataFrame
    benchmark_frames: dict[str, pd.DataFrame]
    perturbation_frames: dict[str, pd.DataFrame]

    def to_dict(self) -> dict[str, Any]:
        excluded = {"combined_frame", "benchmark_frames", "perturbation_frames"}
        payload = {
            name: deepcopy(getattr(self, name))
            for name in self.__dataclass_fields__
            if name not in excluded
        }
        payload["parameter_stability"] = _validated_parameter_stability_payload(
            self.folds,
            self.parameter_stability,
        )
        return payload


def _score(metrics: Mapping[str, float | int]) -> float:
    return (
        float(metrics["sharpe"])
        + 0.20 * float(metrics["calmar"])
        - 0.50 * abs(float(metrics["max_drawdown"]))
        - 0.01 * float(metrics["annualized_turnover"])
    )


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


def _validated_window_bars(value: object, *, label: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise ValueError(f"{label} must be an integer")
    parsed = int(value)
    if parsed < minimum:
        raise ValueError(f"{label} must be >= {minimum}")
    return parsed


def _validated_cost_multiplier(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("cost multipliers must be finite and positive")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0.0:
        raise ValueError("cost multipliers must be finite and positive")
    return parsed


def _candidates(
    base: StrategyConfig,
    momentum: Iterable[int],
    reversal: Iterable[int],
    trend_weights: Iterable[float],
) -> list[StrategyConfig]:
    unique: dict[tuple[int, int, float], StrategyConfig] = {}
    for m, r, weight in itertools.product(momentum, reversal, trend_weights):
        key = (
            _validated_candidate_lookback(
                m,
                label="momentum lookback",
                minimum=2,
            ),
            _validated_candidate_lookback(
                r,
                label="reversal lookback",
                minimum=1,
            ),
            _validated_trend_weight(weight),
        )
        unique[key] = base.with_overrides(
            momentum_lookback=key[0],
            reversal_lookback=key[1],
            trend_weight=key[2],
            reversal_weight=round(1.0 - key[2], 10),
        )
    if not unique:
        raise ValueError("candidate grid cannot be empty")
    return list(unique.values())


def _parameter_stability(selected: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    identities = [
        (
            int(item["momentum_lookback"]),
            int(item["reversal_lookback"]),
            float(item["trend_weight"]),
        )
        for item in selected
    ]
    base_labels = {
        identity: f"m={identity[0]}|r={identity[1]}|trend={identity[2]:.4f}"
        for identity in set(identities)
    }
    label_counts = Counter(base_labels.values())
    display_labels = {
        identity: (
            base_labels[identity]
            if label_counts[base_labels[identity]] == 1
            else f"m={identity[0]}|r={identity[1]}|trend={identity[2]!r}"
        )
        for identity in set(identities)
    }
    parameter_keys = [display_labels[identity] for identity in identities]
    switches = sum(left != right for left, right in zip(identities, identities[1:], strict=False))
    return {
        "selection_frequency": dict(Counter(parameter_keys).most_common()),
        "parameter_switches": switches,
        "parameter_switch_rate": switches / max(1, len(identities) - 1),
        "unique_parameter_sets": len(set(identities)),
    }


def _selected_parameter_identity(
    fold: Mapping[str, Any],
    *,
    fold_number: int,
) -> tuple[int, int, float]:
    if not isinstance(fold, Mapping):
        raise ValueError(f"fold {fold_number} must be a mapping")
    parameters = fold.get("selected_parameters")
    if not isinstance(parameters, Mapping):
        raise ValueError(f"fold {fold_number} must contain selected_parameters")

    momentum = parameters.get("momentum_lookback")
    reversal = parameters.get("reversal_lookback")
    trend_weight = parameters.get("trend_weight")
    if isinstance(momentum, bool) or not isinstance(momentum, Integral):
        raise ValueError(f"fold {fold_number} momentum_lookback must be an integer")
    if isinstance(reversal, bool) or not isinstance(reversal, Integral):
        raise ValueError(f"fold {fold_number} reversal_lookback must be an integer")
    if (
        isinstance(trend_weight, bool)
        or not isinstance(trend_weight, Real)
        or not math.isfinite(float(trend_weight))
    ):
        raise ValueError(f"fold {fold_number} trend_weight must be a finite real number")
    return int(momentum), int(reversal), float(trend_weight)


def _selected_parameter_records(
    folds: Iterable[Mapping[str, Any]],
) -> list[dict[str, float | int]]:
    return [
        {
            "momentum_lookback": identity[0],
            "reversal_lookback": identity[1],
            "trend_weight": identity[2],
        }
        for fold_number, fold in enumerate(folds, start=1)
        for identity in [_selected_parameter_identity(fold, fold_number=fold_number)]
    ]


def _selection_frequency_records(
    folds: Iterable[Mapping[str, Any]],
) -> list[dict[str, float | int]]:
    identities = [
        (
            int(parameters["momentum_lookback"]),
            int(parameters["reversal_lookback"]),
            float(parameters["trend_weight"]),
        )
        for parameters in _selected_parameter_records(folds)
    ]
    return [
        {
            "momentum_lookback": identity[0],
            "reversal_lookback": identity[1],
            "trend_weight": identity[2],
            "selections": count,
        }
        for identity, count in Counter(identities).most_common()
    ]


def _validated_parameter_stability_payload(
    folds: Iterable[Mapping[str, Any]],
    parameter_stability: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(parameter_stability, Mapping):
        raise ValueError("parameter_stability must be a mapping")

    fold_list = list(folds)
    selected = _selected_parameter_records(fold_list)
    expected = _parameter_stability(selected)
    for key, expected_value in expected.items():
        if parameter_stability.get(key) != expected_value:
            raise ValueError(f"parameter_stability {key} does not match selected fold parameters")

    payload = deepcopy(dict(parameter_stability))
    payload["selection_frequency_records"] = _selection_frequency_records(fold_list)
    return payload


def _rebase_test_window(
    frame: pd.DataFrame,
    config: StrategyConfig,
    previous_position: float,
) -> pd.DataFrame:
    frame = frame.copy()
    if frame.empty:
        raise ValueError("requested backtest window is empty")

    position = frame["position"].to_numpy(copy=False)
    turnover = frame["turnover"].to_numpy(copy=False)
    trading_cost = frame["trading_cost"].to_numpy(copy=False)
    asset_return = frame["asset_return"].to_numpy(copy=False)
    strategy_return = frame["strategy_return"].to_numpy(copy=False)

    turnover[0] = abs(float(position[0]) - previous_position)
    trading_cost[0] = turnover[0] * config.transaction_cost_bps / 10_000.0
    strategy_return[0] = position[0] * asset_return[0] - trading_cost[0]
    frame["nav"] = np.cumprod(1.0 + strategy_return)
    return frame


def _run_test_window(
    history: pd.Series,
    config: StrategyConfig,
    start: pd.Timestamp,
    end: pd.Timestamp,
    previous_position: float,
) -> pd.DataFrame:
    frame = run_backtest(history, config, start=start, end=end).frame
    return _rebase_test_window(frame, config, previous_position)


def _run_cached_candidate_window(
    point_in_time_history: pd.Series,
    complete_history: pd.Series,
    cache: dict[StrategyConfig, pd.DataFrame],
    config: StrategyConfig,
    start: pd.Timestamp,
    end: pd.Timestamp,
    previous_position: float,
) -> pd.DataFrame:
    """Reuse one causal full-history backtest for repeated candidate windows."""

    del point_in_time_history  # Retained for exact legacy benchmark substitution.
    template = cache.get(config)
    if template is None:
        template = run_backtest(complete_history, config).frame.drop(columns="nav")
        cache[config] = template
    return _rebase_test_window(template.loc[start:end], config, previous_position)


def _longer_lookbacks(config: StrategyConfig) -> tuple[int, int]:
    return (
        max(2, round(config.momentum_lookback * 1.2)),
        max(1, round(config.reversal_lookback * 1.2)),
    )


def _perturb(config: StrategyConfig) -> dict[str, StrategyConfig]:
    lower_weight = max(0.0, config.trend_weight - 0.05)
    higher_weight = min(1.0, config.trend_weight + 0.05)
    longer_momentum, longer_reversal = _longer_lookbacks(config)
    return {
        "shorter_lookbacks": config.with_overrides(
            momentum_lookback=max(2, round(config.momentum_lookback * 0.8)),
            reversal_lookback=max(1, round(config.reversal_lookback * 0.8)),
        ),
        "longer_lookbacks": config.with_overrides(
            momentum_lookback=longer_momentum,
            reversal_lookback=longer_reversal,
        ),
        "less_trend_weight": config.with_overrides(
            trend_weight=lower_weight,
            reversal_weight=round(1.0 - lower_weight, 10),
        ),
        "more_trend_weight": config.with_overrides(
            trend_weight=higher_weight,
            reversal_weight=round(1.0 - higher_weight, 10),
        ),
    }


def _stitch(frames: list[pd.DataFrame]) -> pd.DataFrame:
    if not frames:
        raise RuntimeError("walk-forward evaluation produced no test folds")
    combined = pd.concat(frames).sort_index()
    if combined.index.duplicated().any():
        raise RuntimeError("walk-forward test folds overlap")
    combined["nav"] = (1.0 + combined["strategy_return"]).cumprod()
    return combined


def _reprice(frame: pd.DataFrame, cost_bps: float) -> pd.DataFrame:
    stressed = frame.copy()
    stressed["trading_cost"] = stressed["turnover"] * cost_bps / 10_000.0
    stressed["strategy_return"] = (
        stressed["position"] * stressed["asset_return"] - stressed["trading_cost"]
    )
    stressed["nav"] = (1.0 + stressed["strategy_return"]).cumprod()
    return stressed


def _assess_benchmarks(
    strategy: Mapping[str, float | int],
    benchmarks: Mapping[str, Mapping[str, float | int]],
) -> dict[str, Any]:
    buy_and_hold = benchmarks["buy_and_hold"]
    best: dict[str, dict[str, float | str]] = {}
    for metric in ("total_return", "cagr", "sharpe", "calmar", "max_drawdown"):
        name, metrics = max(benchmarks.items(), key=lambda item: float(item[1][metric]))
        best[metric] = {"name": name, "value": float(metrics[metric])}

    buy_hold_drawdown = abs(float(buy_and_hold["max_drawdown"]))
    strategy_drawdown = abs(float(strategy["max_drawdown"]))
    drawdown_reduction = (
        1.0 - strategy_drawdown / buy_hold_drawdown if buy_hold_drawdown > 0 else 0.0
    )
    return {
        "beats_buy_and_hold": {
            "total_return": float(strategy["total_return"]) > float(buy_and_hold["total_return"]),
            "cagr": float(strategy["cagr"]) > float(buy_and_hold["cagr"]),
            "sharpe": float(strategy["sharpe"]) > float(buy_and_hold["sharpe"]),
            "calmar": float(strategy["calmar"]) > float(buy_and_hold["calmar"]),
            "max_drawdown": float(strategy["max_drawdown"]) > float(buy_and_hold["max_drawdown"]),
        },
        "beats_all_benchmarks": {
            metric: float(strategy[metric]) > float(details["value"])
            for metric, details in best.items()
        },
        "strategy_minus_buy_and_hold": {
            metric: float(strategy[metric]) - float(buy_and_hold[metric])
            for metric in ("total_return", "cagr", "sharpe", "calmar", "max_drawdown")
        },
        "relative_drawdown_reduction_vs_buy_and_hold": drawdown_reduction,
        "best_benchmark_by_metric": best,
    }


def _assess_fold_stability(folds: list[dict[str, Any]]) -> dict[str, Any]:
    """Measure whether OOS gains are broad enough to support provisional classification."""

    fold_returns = [float(fold["test_metrics"]["total_return"]) for fold in folds]
    if not fold_returns or not all(np.isfinite(value) for value in fold_returns):
        raise RuntimeError("walk-forward fold returns must be finite and non-empty")

    positive_returns = [value for value in fold_returns if value > 0.0]
    positive_total = sum(positive_returns)
    max_positive_share = max(positive_returns) / positive_total if positive_total > 0.0 else 1.0
    minimum_profitable_folds = math.ceil(len(fold_returns) / 2)
    reasons: list[str] = []
    if len(fold_returns) < _MIN_PROVISIONAL_FOLDS:
        reasons.append(f"requires at least {_MIN_PROVISIONAL_FOLDS} out-of-sample folds")
    if len(positive_returns) < minimum_profitable_folds:
        reasons.append("fewer than half of out-of-sample folds are profitable")
    if max_positive_share > _MAX_POSITIVE_FOLD_SHARE:
        reasons.append("one fold contributes more than half of positive fold return")

    return {
        "fold_count": len(fold_returns),
        "profitable_folds": len(positive_returns),
        "losing_or_flat_folds": len(fold_returns) - len(positive_returns),
        "positive_fold_ratio": len(positive_returns) / len(fold_returns),
        "best_fold_total_return": max(fold_returns),
        "worst_fold_total_return": min(fold_returns),
        "max_positive_fold_share": max_positive_share,
        "minimum_profitable_folds": minimum_profitable_folds,
        "minimum_required_folds": _MIN_PROVISIONAL_FOLDS,
        "maximum_allowed_positive_fold_share": _MAX_POSITIVE_FOLD_SHARE,
        "passes": not reasons,
        "failure_reasons": reasons,
    }


def _classify_robustness(
    *,
    aggregate: Mapping[str, float | int],
    doubled_cost: Mapping[str, float | int] | None,
    perturbation_metrics: Mapping[str, Mapping[str, float | int]],
    benchmark_assessment: Mapping[str, Any],
    fold_stability: Mapping[str, Any],
) -> str:
    positive_variants = sum(
        float(metrics["total_return"]) > 0.0 for metrics in perturbation_metrics.values()
    )
    if float(aggregate["total_return"]) <= 0 or float(aggregate["sharpe"]) <= 0:
        return "reject: non-positive aggregate out-of-sample result"
    if doubled_cost is not None and float(doubled_cost["total_return"]) <= 0:
        return "reject: result does not survive at least 2x transaction costs"
    if positive_variants < max(1, len(perturbation_metrics) - 1):
        return "reject: result is unstable under modest parameter perturbations"
    if not bool(fold_stability["passes"]):
        return "reject: out-of-sample fold profits are too concentrated"
    if (
        benchmark_assessment["beats_all_benchmarks"]["total_return"]
        and benchmark_assessment["beats_all_benchmarks"]["sharpe"]
    ):
        return "provisional alpha candidate: beats tested benchmarks on return and Sharpe"
    if (
        benchmark_assessment["beats_all_benchmarks"]["calmar"]
        and benchmark_assessment["beats_all_benchmarks"]["max_drawdown"]
    ):
        return (
            "provisional risk-control candidate: improves Calmar and drawdown, "
            "but not benchmark return/Sharpe"
        )
    return "reject: no benchmark-relative return, Sharpe, or Calmar advantage"


def run_walk_forward_research(
    prices: pd.Series,
    *,
    base_config: StrategyConfig,
    momentum_lookbacks: Iterable[int],
    reversal_lookbacks: Iterable[int],
    trend_weights: Iterable[float],
    selection_bars: int = 730,
    test_bars: int = 90,
    cost_multipliers: Iterable[float] = (1.0, 2.0, 4.0),
    provenance: Mapping[str, Any] | None = None,
) -> WalkForwardResult:
    """Select parameters before each non-overlapping out-of-sample test fold."""

    selection_bars = _validated_window_bars(
        selection_bars,
        label="selection_bars",
        minimum=100,
    )
    test_bars = _validated_window_bars(
        test_bars,
        label="test_bars",
        minimum=20,
    )
    multipliers = sorted({_validated_cost_multiplier(value) for value in cost_multipliers})
    if not multipliers:
        raise ValueError("cost multipliers cannot be empty")
    if 1.0 not in multipliers:
        raise ValueError("cost multipliers must include the 1x fee baseline")
    clean = validate_prices(prices, minimum_rows=selection_bars + test_bars)
    candidates = _candidates(
        base_config,
        momentum_lookbacks,
        reversal_lookbacks,
        trend_weights,
    )
    candidate_frame_cache: dict[StrategyConfig, pd.DataFrame] = {}
    longest_lookback = max(
        max(candidate.volatility_lookback, *_longer_lookbacks(candidate))
        for candidate in candidates
    )
    if longest_lookback > selection_bars - 2:
        raise ValueError(
            "selection_bars must provide at least one one-bar-delayed "
            "selection-window observation after every candidate lookback "
            "and longer-lookback perturbation"
        )

    folds: list[dict[str, Any]] = []
    base_frames: list[pd.DataFrame] = []
    variant_names = tuple(_perturb(base_config))
    variant_frames: dict[str, list[pd.DataFrame]] = {name: [] for name in variant_names}
    previous = {"base": 0.0, **dict.fromkeys(variant_names, 0.0)}
    selected: list[dict[str, Any]] = []

    for fold_number, test_start_index in enumerate(
        range(selection_bars, len(clean), test_bars),
        start=1,
    ):
        test_end_index = min(test_start_index + test_bars, len(clean)) - 1
        if test_end_index - test_start_index + 1 < max(20, test_bars // 2):
            break
        selection_end_index = test_start_index - 1
        selection_start_index = selection_end_index - selection_bars + 1
        selection_start = clean.index[selection_start_index]
        selection_end = clean.index[selection_end_index]
        test_start = clean.index[test_start_index]
        test_end = clean.index[test_end_index]
        selection_history = clean.iloc[: selection_end_index + 1]

        ranked: list[tuple[float, StrategyConfig, dict[str, float | int]]] = []
        for candidate in candidates:
            selection_frame = _run_cached_candidate_window(
                selection_history,
                clean,
                candidate_frame_cache,
                candidate,
                selection_start,
                selection_end,
                previous_position=0.0,
            )
            metrics = performance_metrics(
                selection_frame,
                annualization=candidate.annualization,
            )
            score = _score(metrics)
            if np.isfinite(score):
                ranked.append((score, candidate, metrics))
        if not ranked:
            raise RuntimeError(f"fold {fold_number} produced no finite candidate scores")
        ranked.sort(key=lambda item: item[0], reverse=True)
        best_score, best, selection_metrics = ranked[0]
        parameters = best.to_dict()
        selected.append(parameters)

        test_history = clean.iloc[: test_end_index + 1]
        base = _run_cached_candidate_window(
            test_history,
            clean,
            candidate_frame_cache,
            best,
            test_start,
            test_end,
            previous["base"],
        )
        base["fold"] = fold_number
        base["selected_momentum_lookback"] = best.momentum_lookback
        base["selected_reversal_lookback"] = best.reversal_lookback
        base["selected_trend_weight"] = best.trend_weight
        previous["base"] = float(base["position"].iloc[-1])
        base_frames.append(base)

        for name, variant in _perturb(best).items():
            frame = _run_cached_candidate_window(
                test_history,
                clean,
                candidate_frame_cache,
                variant,
                test_start,
                test_end,
                previous[name],
            )
            frame["fold"] = fold_number
            previous[name] = float(frame["position"].iloc[-1])
            variant_frames[name].append(frame)

        folds.append(
            {
                "fold": fold_number,
                "selection_start": selection_start.isoformat(),
                "selection_end": selection_end.isoformat(),
                "test_start": test_start.isoformat(),
                "test_end": test_end.isoformat(),
                "candidates_tested": len(ranked),
                "selected_parameters": parameters,
                "selection_score": best_score,
                "runner_up_score_gap": best_score - ranked[1][0] if len(ranked) > 1 else None,
                "selection_metrics": selection_metrics,
                "test_metrics": performance_metrics(base, annualization=base_config.annualization),
            }
        )

    combined = _stitch(base_frames)
    stitched_variants = {name: _stitch(frames) for name, frames in variant_frames.items()}
    aggregate = performance_metrics(combined, annualization=base_config.annualization)
    perturbation_metrics = {
        name: performance_metrics(frame, annualization=base_config.annualization)
        for name, frame in stitched_variants.items()
    }
    cost_metrics = {
        f"{multiple:g}x": performance_metrics(
            _reprice(combined, base_config.transaction_cost_bps * multiple),
            annualization=base_config.annualization,
        )
        for multiple in multipliers
    }

    start, end = combined.index[[0, -1]]
    median_momentum = int(np.median([candidate.momentum_lookback for candidate in candidates]))
    benchmarks = {
        "buy_and_hold": buy_and_hold_frame(
            clean,
            transaction_cost_bps=base_config.transaction_cost_bps,
            start=start,
            end=end,
        ),
        "volatility_targeted_long": volatility_targeted_long_frame(
            clean,
            volatility_lookback=base_config.volatility_lookback,
            target_volatility=base_config.target_volatility,
            max_position=base_config.max_abs_position,
            annualization=base_config.annualization,
            transaction_cost_bps=base_config.transaction_cost_bps,
            start=start,
            end=end,
        ),
        "simple_trend_long_cash": simple_trend_long_cash_frame(
            clean,
            lookback=max(2, median_momentum),
            transaction_cost_bps=base_config.transaction_cost_bps,
            start=start,
            end=end,
        ),
    }
    benchmark_metrics = {
        name: performance_metrics(frame, annualization=base_config.annualization)
        for name, frame in benchmarks.items()
    }
    benchmark_assessment = _assess_benchmarks(aggregate, benchmark_metrics)

    stability = _parameter_stability(selected)
    fold_stability = _assess_fold_stability(folds)

    status = _classify_robustness(
        aggregate=aggregate,
        doubled_cost=cost_metrics.get("2x"),
        perturbation_metrics=perturbation_metrics,
        benchmark_assessment=benchmark_assessment,
        fold_stability=fold_stability,
    )

    evaluation_end_index = clean.index.get_loc(end)
    unscored_tail_bars = len(clean) - evaluation_end_index - 1

    return WalkForwardResult(
        generated_at_utc=datetime.now(UTC).isoformat(),
        data_summary={
            "observations": len(clean),
            "start": clean.index[0].isoformat(),
            "end": clean.index[-1].isoformat(),
            "evaluation_start": start.isoformat(),
            "evaluation_end": end.isoformat(),
            "unscored_tail_bars": unscored_tail_bars,
            "provenance": dict(provenance or {}),
        },
        settings={
            "selection_bars": selection_bars,
            "test_bars": test_bars,
            "non_overlapping_test_folds": True,
            "candidate_count": len(candidates),
            "cost_multipliers": multipliers,
            "base_config": base_config.to_dict(),
        },
        folds=folds,
        aggregate_metrics=aggregate,
        benchmark_metrics=benchmark_metrics,
        benchmark_assessment=benchmark_assessment,
        cost_stress_metrics=cost_metrics,
        perturbation_metrics=perturbation_metrics,
        parameter_stability=stability,
        fold_stability=fold_stability,
        robustness_status=status,
        combined_frame=combined,
        benchmark_frames=benchmarks,
        perturbation_frames=stitched_variants,
    )
