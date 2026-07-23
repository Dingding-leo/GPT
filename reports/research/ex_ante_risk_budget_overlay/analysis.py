from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

MARKETS = ("BTC-USDT", "ETH-USDT")
RISK_BUDGETS = (0.15, 0.20, 0.25)
ALL_IN_COSTS_BPS = (5.0, 7.5, 10.0, 15.0)
SELECTION_BARS = 730
TEST_BARS = 90
ANNUALIZATION = 365
BASELINE_COST_BPS = 5.0
BLOCK_LENGTH = 20
RESAMPLES = 2_000
CONFIDENCE = 0.95
EXPECTED_OBSERVATIONS = 2_385
EXPECTED_HASHES = {
    "BTC-USDT": {
        "snapshot": "407aeba3d1ad4c8e8682a6a689c1c6327139f42bc7587aaae75c77fce047dec1",
        "returns": "04a0a5257d1e20f1eb88c70b8a0b010d21f0dc35ccb657ba39f14189e9f20790",
    },
    "ETH-USDT": {
        "snapshot": "842b4bbbb0ad7afbe2a1c9ee375443671d818a799266d5dc25cc6a548571ad7f",
        "returns": "4b69db4a44644a5f830e1518aca93356c0eeacf502dc00ba990bd992b9bd387f",
    },
}
SOURCE = {
    "workflow_run_id": 30040842607,
    "artifact_id": 8577163034,
    "artifact_name": "quant-research-source-348-attempt-1",
    "artifact_sha256": "a06f20584f243c4db1420e8ed0b6cacdc13eb11aebddefb72c30cc80176ccd45",
    "source_head_sha": "eea39bc685246209cdb6c0d917fddcc6ef29f34b",
}
CANONICAL_SIGNATURE = (
    "fold-local-ex-ante-strategy-volatility-budget-family-v2|markets=BTC-USDT,ETH-USDT|"
    "development-markets-only=true|source=verified-OKX-1Dutc-snapshots-and-canonical-"
    "5bps-fold-selections|base-path=canonical-market-specific-27-grid-730-selection-90-test|"
    "overlay=per-fold-selected-candidate-gross-strategy-volatility-estimated-on-prior-730-bars|"
    "risk-budgets=15pct,20pct,25pct-annualized|scale=min(1,risk-budget/prior-window-gross-"
    "strategy-volatility)|scale-fixed-through-next-oos-fold|no-leverage=true|fee=5bps-one-way|"
    "all-in-cost-stress=5,7.5,10,15bps-fixed-path|delay-stress=total-delay-2,3-bars-at-all-costs|"
    "benchmark=volatility-targeted-long|inference=paired-noncircular-moving-block-bootstrap-20-"
    "resamples2000-confidence0.95|seed=sha256-canonical-scope-label-market-scenario|"
    "claim=at-least-one-budget-passes-all-BTC-ETH-development-freeze-gates|candidate_count=3"
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def deterministic_seed(scope: str, label: str, market: str, scenario: str = "") -> int:
    payload = f"{CANONICAL_SIGNATURE}|{scope}|{label}|{market}|{scenario}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def estimate_fold_scale(selection_gross_returns: pd.Series, risk_budget: float) -> dict[str, float]:
    values = selection_gross_returns.to_numpy(dtype=float)
    if len(values) != SELECTION_BARS:
        raise ValueError(f"selection window must contain exactly {SELECTION_BARS} observations")
    if not np.isfinite(values).all():
        raise ValueError("selection gross returns must be finite")
    volatility = float(values.std(ddof=0) * math.sqrt(ANNUALIZATION))
    scale = 1.0 if volatility <= 0.0 else min(1.0, float(risk_budget) / volatility)
    return {
        "estimated_annualized_gross_strategy_volatility": volatility,
        "applied_scale": scale,
    }


def _load_prices(path: Path, expected_sha256: str) -> pd.Series:
    if file_sha256(path) != expected_sha256:
        raise ValueError(f"snapshot SHA-256 mismatch: {path}")
    frame = pd.read_csv(path)
    timestamps = pd.DatetimeIndex(pd.to_datetime(frame["timestamp"], utc=True, errors="raise"))
    close = pd.to_numeric(frame["close"], errors="raise")
    confirm = pd.to_numeric(frame["confirm"], errors="raise")
    if timestamps.has_duplicates or not timestamps.is_monotonic_increasing:
        raise ValueError("snapshot timestamps must be unique and increasing")
    if not bool(confirm.eq(1).all()) or (close <= 0.0).any():
        raise ValueError("snapshot must contain positive confirmed closes")
    return pd.Series(close.to_numpy(dtype=float), index=timestamps, name="close")


def _load_folds(path: Path) -> list[dict[str, Any]]:
    folds = json.loads(path.read_text(encoding="utf-8"))["folds"]
    if not isinstance(folds, list) or not folds:
        raise ValueError("walk-forward report must contain folds")
    return folds


def _load_canonical_returns(path: Path, expected_sha256: str) -> pd.DataFrame:
    if file_sha256(path) != expected_sha256:
        raise ValueError(f"return SHA-256 mismatch: {path}")
    frame = pd.read_csv(path)
    timestamps = pd.DatetimeIndex(pd.to_datetime(frame["timestamp"], utc=True, errors="raise"))
    if timestamps.has_duplicates or not timestamps.is_monotonic_increasing:
        raise ValueError("return timestamps must be unique and increasing")
    frame.index = timestamps
    if len(frame) != EXPECTED_OBSERVATIONS:
        raise ValueError(f"expected {EXPECTED_OBSERVATIONS} OOS observations")
    return frame


def _selected_config(record: dict[str, Any]) -> Any:
    from gpt_quant import StrategyConfig

    selected = record["selected_parameters"]
    return StrategyConfig(
        momentum_lookback=int(selected["momentum_lookback"]),
        reversal_lookback=int(selected["reversal_lookback"]),
        trend_weight=float(selected["trend_weight"]),
        reversal_weight=1.0 - float(selected["trend_weight"]),
        volatility_lookback=30,
        target_volatility=0.50,
        max_abs_position=1.0,
        min_position=0.0,
        transaction_cost_bps=BASELINE_COST_BPS,
        annualization=ANNUALIZATION,
    )


def reconstruct_path(
    prices: pd.Series,
    folds: list[dict[str, Any]],
    risk_budget: float,
) -> tuple[pd.DataFrame, list[dict[str, float]]]:
    from gpt_quant import run_backtest

    pieces: list[pd.DataFrame] = []
    scales: list[dict[str, float]] = []
    previous_position = 0.0
    for record in folds:
        frame = run_backtest(prices, _selected_config(record)).frame
        selection = frame.loc[record["selection_start"] : record["selection_end"]]
        scale_record = estimate_fold_scale(selection["gross_strategy_return"], risk_budget)
        scale = scale_record["applied_scale"]
        scales.append(scale_record | {"fold": int(record["fold"])})
        test = frame.loc[record["test_start"] : record["test_end"]].copy()
        test["position"] = test["position"] * scale
        test["target_position"] = test["target_position"] * scale
        test["turnover"] = test["position"].diff().abs()
        test.iloc[0, test.columns.get_loc("turnover")] = abs(
            float(test["position"].iloc[0]) - previous_position
        )
        test["gross_strategy_return"] = test["position"] * test["asset_return"]
        test["trading_cost"] = test["turnover"] * BASELINE_COST_BPS / 10_000.0
        test["strategy_return"] = test["gross_strategy_return"] - test["trading_cost"]
        test["fold"] = int(record["fold"])
        pieces.append(test)
        previous_position = float(test["position"].iloc[-1])
    result = pd.concat(pieces).sort_index()
    if result.index.has_duplicates:
        raise ValueError("OOS folds must not overlap")
    return recompute_nav(result), scales


def recompute_nav(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    returns = pd.to_numeric(result["strategy_return"], errors="coerce")
    if returns.isna().any() or not np.isfinite(returns.to_numpy(dtype=float)).all():
        raise ValueError("strategy returns must be finite before NAV reconstruction")
    if (returns <= -1.0).any():
        raise ValueError("strategy returns must remain greater than -100%")
    result["nav"] = (1.0 + returns).cumprod()
    return result


def reprice(frame: pd.DataFrame, cost_bps: float) -> pd.DataFrame:
    result = frame.copy()
    result["trading_cost"] = result["turnover"] * cost_bps / 10_000.0
    result["strategy_return"] = result["gross_strategy_return"] - result["trading_cost"]
    return recompute_nav(result)


def delay_path(frame: pd.DataFrame, total_delay_bars: int, cost_bps: float) -> pd.DataFrame:
    if total_delay_bars < 1:
        raise ValueError("total_delay_bars must be at least one")
    position = frame["position"].shift(total_delay_bars - 1).fillna(0.0)
    turnover = position.diff().abs()
    turnover.iloc[0] = abs(float(position.iloc[0]))
    gross = position * frame["asset_return"]
    trading_cost = turnover * cost_bps / 10_000.0
    strategy_return = gross - trading_cost
    result = pd.DataFrame(
        {
            "asset_return": frame["asset_return"],
            "position": position,
            "turnover": turnover,
            "gross_strategy_return": gross,
            "trading_cost": trading_cost,
            "strategy_return": strategy_return,
            "fold": frame["fold"],
        },
        index=frame.index,
    )
    return recompute_nav(result)


def return_metrics(returns: pd.Series | np.ndarray) -> dict[str, float | int]:
    values = np.asarray(returns, dtype=float)
    observations = int(values.size)
    if observations == 0 or not np.isfinite(values).all() or np.any(values <= -1.0):
        raise ValueError("returns must be finite, non-empty, and greater than -1")
    growth = float(np.prod(1.0 + values))
    total_return = growth - 1.0
    cagr = growth ** (ANNUALIZATION / observations) - 1.0 if growth > 0.0 else -1.0
    mean = float(values.mean())
    standard_deviation = float(values.std(ddof=0))
    annualized_mean = mean * ANNUALIZATION
    annualized_volatility = standard_deviation * math.sqrt(ANNUALIZATION)
    sharpe = mean / standard_deviation * math.sqrt(ANNUALIZATION) if standard_deviation else 0.0
    downside = np.minimum(values, 0.0)
    downside_deviation = float(np.sqrt(np.mean(np.square(downside))))
    sortino = mean / downside_deviation * math.sqrt(ANNUALIZATION) if downside_deviation else 0.0
    nav = np.concatenate(([1.0], np.cumprod(1.0 + values)))
    drawdown = nav / np.maximum.accumulate(nav) - 1.0
    max_drawdown = float(drawdown.min())
    calmar = cagr / abs(max_drawdown) if max_drawdown < 0.0 else 0.0
    return {
        "observations": observations,
        "total_return": total_return,
        "cagr": cagr,
        "annualized_arithmetic_mean": annualized_mean,
        "annualized_volatility": annualized_volatility,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_drawdown,
        "calmar": calmar,
    }


def frame_metrics(frame: pd.DataFrame) -> dict[str, float | int]:
    values = return_metrics(frame["strategy_return"])
    values.update(
        {
            "annualized_turnover": float(frame["turnover"].mean()) * ANNUALIZATION,
            "average_abs_exposure": float(frame["position"].abs().mean()),
            "exchange_fee_sum": float(frame["trading_cost"].sum()),
        }
    )
    return values


def compact_metrics(metrics: dict[str, float | int]) -> dict[str, float]:
    return {
        key: float(metrics[key])
        for key in (
            "total_return",
            "cagr",
            "annualized_arithmetic_mean",
            "sharpe",
            "sortino",
            "calmar",
            "max_drawdown",
            "annualized_turnover",
            "average_abs_exposure",
            "exchange_fee_sum",
        )
    }


def fold_stability(frame: pd.DataFrame) -> dict[str, Any]:
    records = [
        float((1.0 + group["strategy_return"]).prod() - 1.0)
        for _, group in frame.groupby("fold", sort=True)
    ]
    positive = [value for value in records if value > 0.0]
    positive_total = sum(positive)
    concentration = max(positive) / positive_total if positive_total > 0.0 else 1.0
    minimum_profitable = math.ceil(len(records) / 2)
    return {
        "fold_count": len(records),
        "profitable_folds": len(positive),
        "max_positive_fold_share": concentration,
        "passes": len(positive) >= minimum_profitable and concentration <= 0.50,
    }


def calendar_stability(frame: pd.DataFrame) -> dict[str, Any]:
    returns = frame["strategy_return"]
    complete: list[float] = []
    for _, group in returns.groupby(returns.index.year, sort=True):
        partial = not (
            group.index[0].month == 1
            and group.index[0].day == 1
            and group.index[-1].month == 12
            and group.index[-1].day == 31
        )
        if not partial:
            complete.append(float((1.0 + group).prod() - 1.0))
    profitable = sum(value > 0.0 for value in complete)
    ratio = profitable / len(complete) if complete else 0.0
    minimum_return = min(complete, default=-math.inf)
    return {"passes": len(complete) >= 4 and ratio >= 0.60 and minimum_return > -0.20}


def expected_shortfall_5pct(returns: pd.Series | np.ndarray) -> float:
    values = np.asarray(returns, dtype=float)
    count = math.ceil(0.05 * len(values))
    return float(np.sort(values)[:count].mean())


def noncircular_block_indices(
    observations: int,
    block_length: int,
    rng: np.random.Generator,
) -> np.ndarray:
    blocks_needed = math.ceil(observations / block_length)
    starts = rng.integers(0, observations - block_length + 1, size=blocks_needed)
    return np.concatenate([np.arange(start, start + block_length) for start in starts])[
        :observations
    ]


def paired_metric_delta_bootstrap(
    candidate: pd.Series,
    comparator: pd.Series,
    *,
    seed: int,
) -> dict[str, Any]:
    candidate_values = candidate.to_numpy(dtype=float)
    comparator_values = comparator.to_numpy(dtype=float)
    rng = np.random.default_rng(seed)
    sharpe_deltas = np.empty(RESAMPLES)
    calmar_deltas = np.empty(RESAMPLES)
    for resample in range(RESAMPLES):
        indices = noncircular_block_indices(len(candidate_values), BLOCK_LENGTH, rng)
        candidate_metrics = return_metrics(candidate_values[indices])
        comparator_metrics = return_metrics(comparator_values[indices])
        sharpe_deltas[resample] = float(candidate_metrics["sharpe"]) - float(
            comparator_metrics["sharpe"]
        )
        calmar_deltas[resample] = float(candidate_metrics["calmar"]) - float(
            comparator_metrics["calmar"]
        )
    alpha = (1.0 - CONFIDENCE) / 2.0
    candidate_metrics = return_metrics(candidate_values)
    comparator_metrics = return_metrics(comparator_values)
    return {
        "sharpe_delta": {
            "point": float(candidate_metrics["sharpe"]) - float(comparator_metrics["sharpe"]),
            "lower": float(np.quantile(sharpe_deltas, alpha)),
            "upper": float(np.quantile(sharpe_deltas, 1.0 - alpha)),
            "probability_positive": float(np.mean(sharpe_deltas > 0.0)),
        },
        "calmar_delta": {
            "point": float(candidate_metrics["calmar"]) - float(comparator_metrics["calmar"]),
            "lower": float(np.quantile(calmar_deltas, alpha)),
            "upper": float(np.quantile(calmar_deltas, 1.0 - alpha)),
            "probability_positive": float(np.mean(calmar_deltas > 0.0)),
        },
    }


def absolute_return_bootstrap(returns: pd.Series, *, seed: int) -> dict[str, Any]:
    values = returns.to_numpy(dtype=float)
    rng = np.random.default_rng(seed)
    annualized_means = np.empty(RESAMPLES)
    sharpes = np.empty(RESAMPLES)
    for resample in range(RESAMPLES):
        indices = noncircular_block_indices(len(values), BLOCK_LENGTH, rng)
        metrics = return_metrics(values[indices])
        annualized_means[resample] = float(metrics["annualized_arithmetic_mean"])
        sharpes[resample] = float(metrics["sharpe"])
    alpha = (1.0 - CONFIDENCE) / 2.0
    return {
        "annualized_arithmetic_mean": {
            "lower": float(np.quantile(annualized_means, alpha)),
            "upper": float(np.quantile(annualized_means, 1.0 - alpha)),
            "probability_positive": float(np.mean(annualized_means > 0.0)),
        },
        "sharpe": {
            "lower": float(np.quantile(sharpes, alpha)),
            "upper": float(np.quantile(sharpes, 1.0 - alpha)),
            "probability_positive": float(np.mean(sharpes > 0.0)),
        },
    }


def analyze(artifact_dir: Path) -> dict[str, Any]:
    market_data: dict[str, dict[str, Any]] = {}
    canonical_reference: dict[str, dict[str, float]] = {}
    for market in MARKETS:
        root = artifact_dir / market
        prices = _load_prices(
            root / "snapshot" / f"okx-{market}-1Dutc.csv",
            EXPECTED_HASHES[market]["snapshot"],
        )
        folds = _load_folds(root / "walk_forward.json")
        canonical = _load_canonical_returns(
            root / "walk_forward_returns.csv",
            EXPECTED_HASHES[market]["returns"],
        )
        canonical_metrics = frame_metrics(canonical)
        canonical_reference[market] = {
            key: float(canonical_metrics[key])
            for key in (
                "total_return",
                "cagr",
                "sharpe",
                "sortino",
                "calmar",
                "max_drawdown",
                "annualized_turnover",
            )
        }
        market_data[market] = {
            "prices": prices,
            "folds": folds,
            "canonical": canonical,
            "paths": {},
            "scales": {},
        }
        for budget in RISK_BUDGETS:
            label = f"{int(round(budget * 100))}pct"
            path, scales = reconstruct_path(prices, folds, budget)
            market_data[market]["paths"][label] = path
            market_data[market]["scales"][label] = scales

    candidates: dict[str, Any] = {}
    passed_candidates: list[str] = []
    labels = [f"{int(round(budget * 100))}pct" for budget in RISK_BUDGETS]
    for budget_index, budget in enumerate(RISK_BUDGETS):
        label = labels[budget_index]
        market_results: dict[str, Any] = {}
        market_gates: dict[str, dict[str, str]] = {}
        for market in MARKETS:
            frame = market_data[market]["paths"][label]
            canonical = market_data[market]["canonical"]
            benchmark = canonical["benchmark_volatility_targeted_long_return"]
            metrics = compact_metrics(frame_metrics(frame))
            bootstrap = paired_metric_delta_bootstrap(
                frame["strategy_return"],
                benchmark,
                seed=deterministic_seed("benchmark", label, market),
            )
            fold = fold_stability(frame)
            calendar = calendar_stability(frame)
            scales = market_data[market]["scales"][label]
            scale_values = [float(record["applied_scale"]) for record in scales]
            scaling = {
                "fully_scaled_folds": sum(value < 1.0 for value in scale_values),
                "maximum_scale": max(scale_values),
                "mean_scale": float(np.mean(scale_values)),
                "minimum_scale": min(scale_values),
            }
            cost_passes = True
            for cost_bps in ALL_IN_COSTS_BPS:
                scenario_metrics = frame_metrics(reprice(frame, cost_bps))
                cost_passes &= (
                    float(scenario_metrics["total_return"]) > 0.0
                    and float(scenario_metrics["sharpe"]) > 0.0
                    and float(scenario_metrics["max_drawdown"]) > -0.40
                )
            adjacent_labels: list[str] = []
            if budget_index > 0:
                adjacent_labels.append(labels[budget_index - 1])
            if budget_index + 1 < len(labels):
                adjacent_labels.append(labels[budget_index + 1])
            neighbourhood_passes = all(
                (
                    float(frame_metrics(market_data[market]["paths"][other])["total_return"])
                    > 0.0
                    and float(frame_metrics(market_data[market]["paths"][other])["sharpe"])
                    > 0.0
                    and float(
                        frame_metrics(market_data[market]["paths"][other])["max_drawdown"]
                    )
                    > -0.40
                )
                for other in adjacent_labels
            )
            tail_passes = expected_shortfall_5pct(
                frame["strategy_return"]
            ) > expected_shortfall_5pct(benchmark)
            delay_passes = True
            scenario_index = 0
            for total_delay_bars in (2, 3):
                for cost_bps in ALL_IN_COSTS_BPS:
                    delayed = delay_path(frame, total_delay_bars, cost_bps)
                    delayed_metrics = frame_metrics(delayed)
                    delayed_bootstrap = absolute_return_bootstrap(
                        delayed["strategy_return"],
                        seed=deterministic_seed(
                            "delay",
                            label,
                            market,
                            f"{total_delay_bars}|{cost_bps:g}|{scenario_index}",
                        ),
                    )
                    scenario_index += 1
                    delay_passes &= (
                        float(delayed_metrics["total_return"]) > 0.0
                        and float(delayed_metrics["max_drawdown"]) > -0.40
                        and float(delayed_bootstrap["annualized_arithmetic_mean"]["lower"])
                        > 0.0
                        and float(delayed_bootstrap["sharpe"]["lower"]) > 0.0
                    )
            benchmark_passes = (
                float(bootstrap["sharpe_delta"]["lower"]) > 0.0
                and float(bootstrap["calmar_delta"]["lower"]) > 0.0
            )
            market_gates[market] = {
                "development_benchmark_relative_risk_adjusted": (
                    "pass" if benchmark_passes else "fail"
                ),
                "fold_stability": "pass" if fold["passes"] else "fail",
                "year_stability": "pass" if calendar["passes"] else "fail",
                "turnover_and_5_7.5_10_15bps_viability": "pass" if cost_passes else "fail",
                "parameter_neighbourhood_stability": (
                    "pass" if neighbourhood_passes else "fail"
                ),
                "tail_risk": "pass" if tail_passes else "fail",
                "execution_delay_robustness": "pass" if delay_passes else "fail",
            }
            market_results[market] = {
                "bootstrap_vs_volatility_targeted_long": bootstrap,
                "calendar_stability": calendar,
                "fold_stability": fold,
                "metrics_5bps": metrics,
                "risk_budget_scaling": scaling,
            }

        joint_gates = {
            key: (
                "pass" if all(market_gates[market][key] == "pass" for market in MARKETS) else "fail"
            )
            for key in (
                "development_benchmark_relative_risk_adjusted",
                "fold_stability",
                "year_stability",
                "turnover_and_5_7.5_10_15bps_viability",
                "parameter_neighbourhood_stability",
                "tail_risk",
                "execution_delay_robustness",
            )
        } | {
            "separate_spread_slippage_impact_latency": "blocked",
            "capacity": "blocked",
            "untouched_market_validation": "blocked",
            "prospective_forward_validation": "blocked",
        }
        development_keys = (
            "development_benchmark_relative_risk_adjusted",
            "fold_stability",
            "year_stability",
            "turnover_and_5_7.5_10_15bps_viability",
            "parameter_neighbourhood_stability",
            "tail_risk",
            "execution_delay_robustness",
        )
        freeze_eligible = all(joint_gates[key] == "pass" for key in development_keys)
        if freeze_eligible:
            passed_candidates.append(label)
        candidates[label] = {
            "architecture_freeze_eligible": freeze_eligible,
            "joint_gates": joint_gates,
            "live_eligible": False,
            "markets": market_results,
            "risk_budget": budget,
        }

    accounting = {
        "passed": len(passed_candidates),
        "passed_candidates": passed_candidates,
        "rejected": len(RISK_BUDGETS) - len(passed_candidates),
        "searched": len(RISK_BUDGETS),
    }
    architecture_freeze_eligible = bool(passed_candidates)
    return {
        "architecture_freeze_eligible": architecture_freeze_eligible,
        "candidate_accounting": accounting,
        "candidates": candidates,
        "canonical_5bps_reference": canonical_reference,
        "canonical_signature": CANONICAL_SIGNATURE,
        "economic_rationale": (
            "The canonical selector concentrates returns in a small number of folds and fails "
            "execution-delay robustness. A no-leverage second-stage risk budget uses only each "
            "selected candidate's preceding 730-session gross strategy volatility to reduce "
            "exposure during historically high-risk regimes, while leaving signal direction "
            "and the 27-candidate selection process unchanged."
        ),
        "failure_reasons": [
            "no disclosed risk-budget candidate passes every joint development freeze gate",
            "untouched-market validation remains unavailable for any new architecture",
            "component-level execution friction, capacity, and prospective evidence remain blocked",
        ],
        "hypothesis": (
            "At least one fixed fold-local ex ante strategy-volatility budget overlay from the "
            "disclosed 15%, 20%, and 25% annualized family passes every BTC-USDT/ETH-USDT "
            "development architecture-freeze gate."
        ),
        "limitations": [
            "BTC-USDT and ETH-USDT are development markets, not untouched holdouts.",
            "The disclosed 15%, 20%, and 25% budgets are a three-candidate architecture family.",
            (
                "The overlay estimates strategy volatility from historical close-to-close "
                "gross returns, not executable fills."
            ),
            "Delay stresses shift daily positions rather than model next-open execution.",
            (
                "The 7.5, 10, and 15 bps scenarios are aggregate repricings and do not "
                "separately measure spread, slippage, market impact, or latency."
            ),
            "SOL-USDT is a consumed sealed holdout and was not accessed or used.",
        ],
        "live_eligible": False,
        "method": {
            "all_in_cost_sensitivities_bps": list(ALL_IN_COSTS_BPS),
            "baseline_exchange_fee_bps_one_way": BASELINE_COST_BPS,
            "block_length": BLOCK_LENGTH,
            "confidence": CONFIDENCE,
            "development_markets_only": True,
            "markets": list(MARKETS),
            "no_leverage": True,
            "resamples": RESAMPLES,
            "risk_budgets": list(RISK_BUDGETS),
            "scale_rule": "min(1, risk_budget / prior_window_gross_strategy_volatility)",
            "scale_timing": "estimated on preceding 730 sessions and fixed through next OOS fold",
            "sealed_market_data_used": False,
            "selection_bars": SELECTION_BARS,
            "seed_rule": (
                "sha256(canonical_signature|scope|candidate|market|scenario) first 64 bits"
            ),
            "spread_slippage_impact_latency": "not_modeled_separately",
            "test_bars": TEST_BARS,
        },
        "source": SOURCE,
        "verdict": "supported" if architecture_freeze_eligible else "rejected",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.artifact_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
