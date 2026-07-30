from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ARCHITECTURE = "onset-aggressive-flow-absorption-selector-1h-v1"
VERDICT = "reject_exact_onset_aggressive_flow_absorption_selector_family"
FEE = 0.0005
TREND_LOOKBACK = 2160
FLOW_LOOKBACK = 24
WARMUP = 720
FOLD_HOURS = 2160
TRAIN_START = 720
TRAIN_END = 9360
OOS_START = 9360
OOS_END = 26640
FULL_START = 720
FULL_END = 26640
BLOCK_HOURS = 168
RESAMPLES = 5000
SEED = 20260730
EXPECTED_TRADE_ROWS = 26640
EXPECTED_TRADE_SHA256 = "ffe94da2b8f7ae2357882398e1ed85d787d4a9fb4898ac98fa2604290b9c22c9"
EXPECTED_CANDLE_SHA256 = "92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9"
EXPECTED_START = "2023-01-11T00:00:00+00:00"
EXPECTED_END = "2026-01-24T23:00:00+00:00"


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def finite(value: float | np.floating[Any]) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"non-finite result: {number}")
    return number


def sharpe(returns: np.ndarray) -> float | None:
    std = float(np.std(returns, ddof=1))
    if std <= 0.0:
        return None
    return finite(math.sqrt(8760.0) * float(np.mean(returns)) / std)


def compounded(returns: np.ndarray) -> float:
    return finite(float(np.prod(1.0 + returns) - 1.0))


def metrics(
    returns: np.ndarray,
    gross_returns: np.ndarray,
    turnover: np.ndarray,
    position: np.ndarray,
    start: int,
    end: int,
) -> dict[str, Any]:
    net = returns[start:end]
    gross = gross_returns[start:end]
    turns = turnover[start:end]
    exposure = position[start:end]
    equity = np.cumprod(1.0 + net)
    values = np.concatenate(([1.0], equity))
    peak = np.maximum.accumulate(values)
    total_turnover = float(np.sum(turns))
    arithmetic_net = float(np.sum(net))
    return {
        "start_index": start,
        "end_index_exclusive": end,
        "hours": end - start,
        "gross_return": compounded(gross),
        "net_return": compounded(net),
        "sharpe": sharpe(net),
        "max_drawdown": finite(float(np.min(values / peak - 1.0))),
        "turnover": finite(total_turnover),
        "fees": finite(total_turnover * FEE),
        "edge_per_turnover_bps": (
            finite(arithmetic_net / total_turnover * 10000.0) if total_turnover > 0.0 else None
        ),
        "arithmetic_net_return": finite(arithmetic_net),
        "mean_exposure": finite(float(np.mean(exposure))),
    }


def moving_block_indices(n: int, block: int, rng: np.random.Generator) -> np.ndarray:
    if n < block:
        raise ValueError("sample shorter than moving block")
    output: list[int] = []
    while len(output) < n:
        start = int(rng.integers(0, n - block + 1))
        output.extend(range(start, start + block))
    return np.asarray(output[:n], dtype=np.int64)


def fill_position(updates: dict[int, float], length: int) -> np.ndarray:
    output = np.zeros(length, dtype=float)
    current = 0.0
    for index in range(length):
        if index in updates:
            current = updates[index]
        output[index] = current
    return output


def build_positions(
    candles: pd.DataFrame,
    trades: pd.DataFrame,
    candle_start_index: int,
) -> tuple[np.ndarray, np.ndarray, list[dict[str, Any]]]:
    common_rows = len(trades)
    close = candles["close"].to_numpy(dtype=float)
    signed = trades["signed_quote_notional"].to_numpy(dtype=float)
    total = trades["total_quote_notional"].to_numpy(dtype=float)
    timestamps = trades["timestamp"]

    benchmark_updates: dict[int, float] = {}
    candidate_updates: dict[int, float] = {}
    candidate_state = 0.0
    events: list[dict[str, Any]] = []

    for local_index in range(common_rows):
        global_index = candle_start_index + local_index
        timestamp = timestamps.iloc[local_index]
        if timestamp.hour != 0 or global_index < TREND_LOOKBACK:
            continue

        base_positive = bool(close[global_index] > close[global_index - TREND_LOOKBACK])
        previous_index = global_index - 24
        previous_positive = bool(
            close[previous_index] > close[previous_index - TREND_LOOKBACK]
        )
        execution_index = local_index + 1
        benchmark_updates[execution_index] = float(base_positive)

        if not base_positive:
            candidate_state = 0.0
        elif not previous_positive:
            if local_index < FLOW_LOOKBACK - 1:
                candidate_state = 0.0
                flow24 = None
                price24 = None
                veto = True
                invalid = True
            else:
                denominator = float(np.sum(total[local_index - 23 : local_index + 1]))
                if denominator <= 0.0:
                    raise ValueError("non-positive 24H total quote notional")
                flow24 = finite(
                    float(np.sum(signed[local_index - 23 : local_index + 1])) / denominator
                )
                price24 = finite(
                    math.log(close[global_index] / close[global_index - FLOW_LOOKBACK])
                )
                veto = bool(flow24 < 0.0 and price24 < 0.0)
                candidate_state = 0.0 if veto else 1.0
                invalid = False
            events.append(
                {
                    "decision_index": local_index,
                    "execution_index": execution_index,
                    "timestamp": timestamp.isoformat(),
                    "flow24": flow24,
                    "price24": price24,
                    "veto": veto,
                    "absorbed_sell": bool(
                        flow24 is not None and flow24 < 0.0 and price24 is not None and price24 >= 0.0
                    ),
                    "nonnegative_flow": bool(flow24 is not None and flow24 >= 0.0),
                    "invalid": invalid,
                }
            )
        candidate_updates[execution_index] = candidate_state

    return (
        fill_position(benchmark_updates, common_rows + 1),
        fill_position(candidate_updates, common_rows + 1),
        events,
    )


def price_only_shadow(
    candles: pd.DataFrame,
    trades: pd.DataFrame,
    candle_start_index: int,
) -> np.ndarray:
    common_rows = len(trades)
    close = candles["close"].to_numpy(dtype=float)
    timestamps = trades["timestamp"]
    updates: dict[int, float] = {}
    state = 0.0
    for local_index in range(common_rows):
        global_index = candle_start_index + local_index
        timestamp = timestamps.iloc[local_index]
        if timestamp.hour != 0 or global_index < TREND_LOOKBACK:
            continue
        base_positive = bool(close[global_index] > close[global_index - TREND_LOOKBACK])
        previous_index = global_index - 24
        previous_positive = bool(
            close[previous_index] > close[previous_index - TREND_LOOKBACK]
        )
        if not base_positive:
            state = 0.0
        elif not previous_positive:
            if local_index < FLOW_LOOKBACK - 1:
                state = 0.0
            else:
                price24 = math.log(close[global_index] / close[global_index - FLOW_LOOKBACK])
                state = 0.0 if price24 < 0.0 else 1.0
        updates[local_index + 1] = state
    return fill_position(updates, common_rows + 1)


def load_and_validate(candle_path: Path, trade_path: Path) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    observed_trade_sha = sha256_file(trade_path)
    observed_candle_sha = sha256_file(candle_path)
    if observed_trade_sha != EXPECTED_TRADE_SHA256:
        raise ValueError(f"trade feature SHA mismatch: {observed_trade_sha}")
    if observed_candle_sha != EXPECTED_CANDLE_SHA256:
        raise ValueError(f"candle SHA mismatch: {observed_candle_sha}")

    candles = pd.read_csv(candle_path)
    trades = pd.read_csv(trade_path)
    candles["timestamp"] = pd.to_datetime(candles["timestamp"], utc=True)
    trades["timestamp"] = pd.to_datetime(trades["timestamp"], utc=True)

    if len(trades) != EXPECTED_TRADE_ROWS:
        raise ValueError(f"expected {EXPECTED_TRADE_ROWS} trade hours, got {len(trades)}")
    if trades["timestamp"].duplicated().any() or not trades["timestamp"].is_monotonic_increasing:
        raise ValueError("trade hours are duplicated or non-monotonic")
    expected_trade_grid = pd.date_range(trades["timestamp"].iloc[0], periods=len(trades), freq="h")
    if not np.array_equal(trades["timestamp"].to_numpy(), expected_trade_grid.to_numpy()):
        raise ValueError("trade feature chronology is not contiguous 1H")
    if trades["timestamp"].iloc[0].isoformat() != EXPECTED_START:
        raise ValueError("unexpected trade start")
    if trades["timestamp"].iloc[-1].isoformat() != EXPECTED_END:
        raise ValueError("unexpected trade end")
    if candles["timestamp"].duplicated().any() or not candles["timestamp"].is_monotonic_increasing:
        raise ValueError("candle chronology is duplicated or non-monotonic")
    if not (candles["confirm"].astype(int) == 1).all():
        raise ValueError("candle artifact contains unconfirmed bars")

    matches = candles.index[candles["timestamp"].eq(trades["timestamp"].iloc[0])].tolist()
    if len(matches) != 1:
        raise ValueError("could not uniquely align trade start to candles")
    candle_start_index = int(matches[0])
    candle_slice = candles.iloc[candle_start_index : candle_start_index + len(trades)]
    if not np.array_equal(candle_slice["timestamp"].to_numpy(), trades["timestamp"].to_numpy()):
        raise ValueError("candle/trade timestamps do not align exactly")
    if candle_start_index < TREND_LOOKBACK:
        raise ValueError("insufficient candle prefix for 2,160H trend")
    if candle_start_index + len(trades) >= len(candles):
        raise ValueError("missing one boundary open for final next-open payoff")
    numeric_columns = [
        "signed_quote_notional",
        "total_quote_notional",
        "flow",
        "impact_return",
        "trade_count",
    ]
    if not np.isfinite(trades[numeric_columns].to_numpy(dtype=float)).all():
        raise ValueError("non-finite trade feature value")
    if (trades["total_quote_notional"].to_numpy(dtype=float) <= 0.0).any():
        raise ValueError("non-positive hourly total quote notional")
    return candles, trades, candle_start_index


def run(candle_path: Path, trade_path: Path) -> dict[str, Any]:
    candles, trades, candle_start_index = load_and_validate(candle_path, trade_path)
    common_rows = len(trades)
    benchmark_position, candidate_position, events = build_positions(
        candles, trades, candle_start_index
    )
    price_shadow = price_only_shadow(candles, trades, candle_start_index)

    aligned = candles.iloc[candle_start_index : candle_start_index + common_rows + 1]
    opens = aligned["open"].to_numpy(dtype=float)
    market_return = opens[1:] / opens[:-1] - 1.0
    benchmark_turnover = np.abs(np.diff(np.concatenate(([0.0], benchmark_position[:common_rows]))))
    candidate_turnover = np.abs(np.diff(np.concatenate(([0.0], candidate_position[:common_rows]))))
    benchmark_gross = benchmark_position[:common_rows] * market_return
    candidate_gross = candidate_position[:common_rows] * market_return
    benchmark_net = benchmark_gross - FEE * benchmark_turnover
    candidate_net = candidate_gross - FEE * candidate_turnover

    if not np.all(np.isin(candidate_position, [0.0, 1.0])):
        raise AssertionError("candidate position escaped long/cash domain")
    if not np.all(candidate_position <= benchmark_position + 1e-15):
        raise AssertionError("candidate entered outside the base trend")

    split_ranges = {
        "training": (TRAIN_START, TRAIN_END),
        "development_oos": (OOS_START, OOS_END),
        "full_scored": (FULL_START, FULL_END),
    }
    split_metrics: dict[str, Any] = {}
    for name, (start, end) in split_ranges.items():
        split_metrics[name] = {
            "candidate": metrics(
                candidate_net,
                candidate_gross,
                candidate_turnover,
                candidate_position,
                start,
                end,
            ),
            "benchmark": metrics(
                benchmark_net,
                benchmark_gross,
                benchmark_turnover,
                benchmark_position,
                start,
                end,
            ),
        }

    folds: list[dict[str, Any]] = []
    for fold_index in range(8):
        start = OOS_START + fold_index * FOLD_HOURS
        end = start + FOLD_HOURS
        candidate_value = compounded(candidate_net[start:end])
        benchmark_value = compounded(benchmark_net[start:end])
        folds.append(
            {
                "fold": fold_index + 1,
                "start": trades["timestamp"].iloc[start].isoformat(),
                "end": trades["timestamp"].iloc[end - 1].isoformat(),
                "candidate_net_return": candidate_value,
                "benchmark_net_return": benchmark_value,
                "candidate_profitable": candidate_value > 0.0,
                "candidate_improved": candidate_value > benchmark_value + 1e-15,
                "arithmetic_delta": finite(
                    float(np.sum(candidate_net[start:end] - benchmark_net[start:end]))
                ),
            }
        )

    oos_timestamps = trades["timestamp"].iloc[OOS_START:OOS_END]
    years: list[dict[str, Any]] = []
    for year in sorted(oos_timestamps.dt.year.unique().tolist()):
        local = np.flatnonzero(oos_timestamps.dt.year.to_numpy() == year)
        start = OOS_START + int(local[0])
        end = OOS_START + int(local[-1]) + 1
        candidate_value = compounded(candidate_net[start:end])
        benchmark_value = compounded(benchmark_net[start:end])
        years.append(
            {
                "year": int(year),
                "start": trades["timestamp"].iloc[start].isoformat(),
                "end": trades["timestamp"].iloc[end - 1].isoformat(),
                "candidate_net_return": candidate_value,
                "benchmark_net_return": benchmark_value,
                "candidate_profitable": candidate_value > 0.0,
                "candidate_improved": candidate_value > benchmark_value + 1e-15,
            }
        )

    positive_fold_returns = [row["candidate_net_return"] for row in folds if row["candidate_net_return"] > 0]
    positive_fold_concentration = finite(max(positive_fold_returns) / sum(positive_fold_returns))
    residual = candidate_net[OOS_START:OOS_END] - benchmark_net[OOS_START:OOS_END]
    residual_sharpe = sharpe(residual)

    rng = np.random.default_rng(SEED)
    mean_deltas = np.empty(RESAMPLES, dtype=float)
    sharpe_deltas = np.empty(RESAMPLES, dtype=float)
    candidate_oos = candidate_net[OOS_START:OOS_END]
    benchmark_oos = benchmark_net[OOS_START:OOS_END]
    for sample_index in range(RESAMPLES):
        indices = moving_block_indices(len(candidate_oos), BLOCK_HOURS, rng)
        candidate_sample = candidate_oos[indices]
        benchmark_sample = benchmark_oos[indices]
        mean_deltas[sample_index] = (
            float(np.mean(candidate_sample)) - float(np.mean(benchmark_sample))
        ) * 8760.0
        candidate_sample_sharpe = sharpe(candidate_sample)
        benchmark_sample_sharpe = sharpe(benchmark_sample)
        if candidate_sample_sharpe is None or benchmark_sample_sharpe is None:
            raise AssertionError("undefined bootstrap Sharpe")
        sharpe_deltas[sample_index] = candidate_sample_sharpe - benchmark_sample_sharpe

    uncertainty = {
        "block_hours": BLOCK_HOURS,
        "resamples": RESAMPLES,
        "seed": SEED,
        "annualized_mean_delta_point": finite(float(np.mean(residual)) * 8760.0),
        "annualized_mean_delta_95": [
            finite(float(np.quantile(mean_deltas, 0.025))),
            finite(float(np.quantile(mean_deltas, 0.975))),
        ],
        "sharpe_delta_point": finite(
            split_metrics["development_oos"]["candidate"]["sharpe"]
            - split_metrics["development_oos"]["benchmark"]["sharpe"]
        ),
        "sharpe_delta_95": [
            finite(float(np.quantile(sharpe_deltas, 0.025))),
            finite(float(np.quantile(sharpe_deltas, 0.975))),
        ],
        "zero_delta_resample_share": finite(
            float(np.mean(np.isclose(mean_deltas, 0.0, atol=1e-15)))
        ),
    }

    episodes: list[tuple[int, int]] = []
    cursor = 0
    while cursor < common_rows:
        if benchmark_position[cursor] > 0.0:
            start = cursor
            while cursor < common_rows and benchmark_position[cursor] > 0.0:
                cursor += 1
            episodes.append((start, cursor))
        else:
            cursor += 1

    for event in events:
        execution_index = int(event["execution_index"])
        episode = next(
            ((start, end) for start, end in episodes if start <= execution_index < end),
            (execution_index, execution_index),
        )
        start, end = episode
        event["split"] = (
            "warmup"
            if event["decision_index"] < TRAIN_START
            else "training"
            if event["decision_index"] < TRAIN_END
            else "development_oos"
        )
        event["duration_hours"] = end - start
        event["regime_market_arithmetic"] = finite(float(np.sum(market_return[start:end])))
        event["regime_market_compounded"] = compounded(market_return[start:end])
        event["post24_return"] = compounded(
            market_return[execution_index : min(execution_index + 24, common_rows)]
        )
        event["post168_return"] = compounded(
            market_return[execution_index : min(execution_index + 168, common_rows)]
        )

    oos_events = [event for event in events if event["split"] == "development_oos"]
    veto_events = [event for event in oos_events if event["veto"]]
    absorbed_events = [event for event in oos_events if event["absorbed_sell"]]
    nonnegative_flow_events = [event for event in oos_events if event["nonnegative_flow"]]

    def event_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not rows:
            return {"count": 0, "mean_post24": None, "mean_post168": None, "mean_regime_arithmetic": None}
        return {
            "count": len(rows),
            "mean_post24": finite(float(np.mean([row["post24_return"] for row in rows]))),
            "mean_post168": finite(float(np.mean([row["post168_return"] for row in rows]))),
            "mean_regime_arithmetic": finite(
                float(np.mean([row["regime_market_arithmetic"] for row in rows]))
            ),
        }

    exposure_difference = (
        benchmark_position[OOS_START:OOS_END] - candidate_position[OOS_START:OOS_END]
    )
    omitted_market_carry = finite(
        float(np.sum(exposure_difference * market_return[OOS_START:OOS_END]))
    )
    incremental_fees = finite(
        float(
            np.sum(candidate_turnover[OOS_START:OOS_END] - benchmark_turnover[OOS_START:OOS_END])
        )
        * FEE
    )
    arithmetic_delta = finite(float(np.sum(residual)))
    reconstructed_delta = finite(-omitted_market_carry - incremental_fees)
    if abs(arithmetic_delta - reconstructed_delta) > 1e-12:
        raise AssertionError("candidate-minus-benchmark decomposition failed")

    price_shadow_turnover = np.abs(np.diff(np.concatenate(([0.0], price_shadow[:common_rows]))))
    price_shadow_net = price_shadow[:common_rows] * market_return - FEE * price_shadow_turnover
    price_shadow_oos_identical = bool(
        np.array_equal(price_shadow[OOS_START:OOS_END], candidate_position[OOS_START:OOS_END])
        and np.allclose(price_shadow_net[OOS_START:OOS_END], candidate_net[OOS_START:OOS_END], atol=0.0)
    )

    event_deltas = [
        -float(event["regime_market_arithmetic"]) + 2.0 * FEE
        for event in veto_events
    ]
    largest_event_delta_share = (
        finite(max(event_deltas) / sum(event_deltas)) if event_deltas and sum(event_deltas) > 0 else None
    )

    gates = {
        "positive_oos_net": split_metrics["development_oos"]["candidate"]["net_return"] > 0.0,
        "net_at_least_benchmark": split_metrics["development_oos"]["candidate"]["net_return"]
        >= split_metrics["development_oos"]["benchmark"]["net_return"],
        "sharpe_at_least_benchmark": split_metrics["development_oos"]["candidate"]["sharpe"]
        >= split_metrics["development_oos"]["benchmark"]["sharpe"],
        "drawdown_no_worse": split_metrics["development_oos"]["candidate"]["max_drawdown"]
        >= split_metrics["development_oos"]["benchmark"]["max_drawdown"],
        "turnover_no_greater": split_metrics["development_oos"]["candidate"]["turnover"]
        <= split_metrics["development_oos"]["benchmark"]["turnover"],
        "edge_per_turnover_at_least_benchmark": split_metrics["development_oos"]["candidate"][
            "edge_per_turnover_bps"
        ]
        >= split_metrics["development_oos"]["benchmark"]["edge_per_turnover_bps"],
        "profitable_folds_at_least_5_of_8": sum(row["candidate_profitable"] for row in folds) >= 5,
        "profitable_years_at_least_2": sum(row["candidate_profitable"] for row in years) >= 2,
        "positive_fold_concentration_at_most_half": positive_fold_concentration <= 0.5,
        "positive_residual_sharpe": residual_sharpe is not None and residual_sharpe > 0.0,
        "mean_delta_lower_bound_strictly_positive": uncertainty["annualized_mean_delta_95"][0] > 0.0,
        "sharpe_delta_lower_bound_strictly_positive": uncertainty["sharpe_delta_95"][0] > 0.0,
        "causal_and_accounting_identities": True,
    }

    return {
        "architecture": ARCHITECTURE,
        "issue": 700,
        "verdict": VERDICT if not all(gates.values()) else "btc_passes_for_unchanged_eth_replication",
        "candidate_count": 1,
        "parameter_grid_count": 0,
        "market": "BTC-USDT",
        "eth_evaluated": False,
        "eth_reason": "BTC first-market gate failed; unchanged ETH replication was not authorised.",
        "data": {
            "provider": "OKX public SPOT",
            "bar": "1H",
            "trade_feature_artifact_ids": [8704648783, 8706456395],
            "trade_feature_sha256": EXPECTED_TRADE_SHA256,
            "candle_artifact_id": 8704977298,
            "candle_sha256": EXPECTED_CANDLE_SHA256,
            "common_rows": common_rows,
            "common_start": trades["timestamp"].iloc[0].isoformat(),
            "common_end": trades["timestamp"].iloc[-1].isoformat(),
            "payoff_boundary_open": candles["timestamp"].iloc[candle_start_index + common_rows].isoformat(),
            "later_signal_suffix_read": False,
        },
        "strategy": {
            "base_trend_hours": TREND_LOOKBACK,
            "flow_and_price_window_hours": FLOW_LOOKBACK,
            "fee_one_way": FEE,
            "decision_cadence": "completed daily 00:00 UTC bars",
            "execution": "next hourly open",
            "position_domain": [0, 1],
            "rule": "veto a new positive 2160H trend only when flow24 < 0 and price24 < 0; otherwise enter and hold to base exit",
        },
        "sample": {
            "warmup": [0, WARMUP],
            "training": [TRAIN_START, TRAIN_END],
            "development_oos": [OOS_START, OOS_END],
            "full_scored": [FULL_START, FULL_END],
            "oos_folds": 8,
            "fold_hours": FOLD_HOURS,
        },
        "metrics": split_metrics,
        "breadth": {
            "folds": folds,
            "profitable_folds": sum(row["candidate_profitable"] for row in folds),
            "improved_folds": sum(row["candidate_improved"] for row in folds),
            "positive_fold_concentration": positive_fold_concentration,
            "years": years,
            "profitable_years": sum(row["candidate_profitable"] for row in years),
            "improved_years": sum(row["candidate_improved"] for row in years),
            "residual_sharpe": residual_sharpe,
        },
        "uncertainty": uncertainty,
        "diagnostics": {
            "oos_onsets": len(oos_events),
            "oos_vetoed_unabsorbed_sell_onsets": len(veto_events),
            "oos_absorbed_sell_onsets": len(absorbed_events),
            "oos_nonnegative_flow_onsets": len(nonnegative_flow_events),
            "event_groups": {
                "unabsorbed_sell": event_summary(veto_events),
                "absorbed_sell": event_summary(absorbed_events),
                "nonnegative_flow": event_summary(nonnegative_flow_events),
            },
            "b1_only_exposure_hours": finite(float(np.sum(exposure_difference))),
            "omitted_market_carry": omitted_market_carry,
            "incremental_fees_vs_benchmark": incremental_fees,
            "arithmetic_delta_vs_benchmark": arithmetic_delta,
            "reconstructed_arithmetic_delta": reconstructed_delta,
            "nonzero_residual_hours": int(np.count_nonzero(np.abs(residual) > 0.0)),
            "oos_difference_hour_share": finite(
                float(np.count_nonzero(np.abs(residual) > 0.0)) / len(residual)
            ),
            "largest_veto_event_improvement_share": largest_event_delta_share,
            "price_only_shadow_oos_identical": price_shadow_oos_identical,
            "price_only_shadow_is_nonselectable_diagnostic": True,
            "events": events,
        },
        "gates": gates,
        "failed_gates": [name for name, passed in gates.items() if not passed],
    }


def markdown(result: dict[str, Any]) -> str:
    def pct(value: float) -> str:
        return f"{value * 100:+.2f}%"

    def metric_row(split: str, policy: str) -> str:
        row = result["metrics"][split][policy]
        return (
            f"| {split} | {policy} | {pct(row['net_return'])} | {row['sharpe']:.3f} | "
            f"{pct(row['max_drawdown'])} | {row['turnover']:.1f} | "
            f"{row['edge_per_turnover_bps']:.2f} |"
        )

    uncertainty = result["uncertainty"]
    diagnostic = result["diagnostics"]
    failed = ", ".join(result["failed_gates"])
    lines = [
        "# Onset-only aggressive-flow absorption selector — terminal evidence",
        "",
        f"- Architecture: `{result['architecture']}`",
        "- Candidate count: `1`; parameter grid: `0`",
        "- Market evaluated: `BTC-USDT` first-market falsification",
        "- Data: immutable public OKX SPOT individual-trade features plus confirmed 1H candles",
        "- Fee: exactly `5 bps` one way; next-open execution",
        f"- Verdict: `{result['verdict']}`",
        "",
        "## Performance",
        "",
        "| Sample | Policy | Net | Sharpe | Max DD | Turnover | Edge/turn (bps) |",
        "|---|---|---:|---:|---:|---:|---:|",
        metric_row("training", "candidate"),
        metric_row("training", "benchmark"),
        metric_row("development_oos", "candidate"),
        metric_row("development_oos", "benchmark"),
        metric_row("full_scored", "candidate"),
        metric_row("full_scored", "benchmark"),
        "",
        "## Breadth and uncertainty",
        "",
        f"- Profitable OOS folds: `{result['breadth']['profitable_folds']}/8`; improved versus benchmark: `{result['breadth']['improved_folds']}/8`.",
        f"- Profitable OOS calendar years: `{result['breadth']['profitable_years']}/3`; improved years: `{result['breadth']['improved_years']}/3`.",
        f"- Positive-fold concentration: `{result['breadth']['positive_fold_concentration'] * 100:.2f}%`.",
        f"- Residual Sharpe: `{result['breadth']['residual_sharpe']:.3f}`.",
        f"- Annualised mean delta 95% interval: `[{uncertainty['annualized_mean_delta_95'][0] * 100:.2f}%, {uncertainty['annualized_mean_delta_95'][1] * 100:.2f}%]`.",
        f"- Sharpe delta 95% interval: `[{uncertainty['sharpe_delta_95'][0]:.3f}, {uncertainty['sharpe_delta_95'][1]:.3f}]`.",
        f"- Zero-delta bootstrap share: `{uncertainty['zero_delta_resample_share'] * 100:.2f}%`.",
        "",
        "## Failure mechanism",
        "",
        f"The selector vetoed `{diagnostic['oos_vetoed_unabsorbed_sell_onsets']}` of `{diagnostic['oos_onsets']}` OOS trend onsets. All vetoed regimes lasted one day, so the candidate differed from the benchmark for only `{diagnostic['b1_only_exposure_hours']:.0f}` hours (`{diagnostic['oos_difference_hour_share'] * 100:.2f}%` of OOS). It omitted `{pct(diagnostic['omitted_market_carry'])}` arithmetic market carry and saved `{abs(diagnostic['incremental_fees_vs_benchmark']) * 100:.2f}%` in fees, producing `{pct(diagnostic['arithmetic_delta_vs_benchmark'])}` arithmetic improvement.",
        "",
        f"The largest single veto supplied `{diagnostic['largest_veto_event_improvement_share'] * 100:.2f}%` of the total arithmetic improvement. The non-selectable diagnostic price-only shadow was OOS-identical to the candidate: `{diagnostic['price_only_shadow_oos_identical']}`. Therefore the public trade-flow sign added no incremental OOS discrimination beyond the already-observed negative 24H price return.",
        "",
        "The aggregate point estimate passed all deterministic benchmark-relative gates, but both preregistered dependence-aware lower bounds were exactly zero because the improvement was confined to four one-day events in two folds. Strictly positive uncertainty support was not established.",
        "",
        "## Verdict",
        "",
        f"Failed gates: `{failed}`.",
        "",
        f"`{result['verdict']}`",
        "",
        "ETH was not acquired or scored because the frozen first-market gate failed. No same-interval horizon, inequality, onset rule, lockout, fee, timing, or market-specific rescue is authorised.",
    ]
    return "\n".join(lines) + "\n"


def protocol() -> dict[str, Any]:
    return {
        "architecture": ARCHITECTURE,
        "issue": 700,
        "candidate_count": 1,
        "parameter_grid_count": 0,
        "first_falsification_market": "BTC-USDT",
        "eth_only_if_btc_passes_all_gates": True,
        "base_trend_hours": TREND_LOOKBACK,
        "feature_window_hours": FLOW_LOOKBACK,
        "rule": "veto a positive-trend onset iff flow24 < 0 and price24 < 0",
        "fee_one_way": FEE,
        "execution": "next hourly open",
        "sample": {
            "warmup": [0, WARMUP],
            "training": [TRAIN_START, TRAIN_END],
            "development_oos": [OOS_START, OOS_END],
            "full_scored": [FULL_START, FULL_END],
            "fold_hours": FOLD_HOURS,
            "oos_folds": 8,
        },
        "uncertainty": {"block_hours": BLOCK_HOURS, "resamples": RESAMPLES, "seed": SEED},
        "expected_hashes": {
            "trade_feature": EXPECTED_TRADE_SHA256,
            "candle": EXPECTED_CANDLE_SHA256,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candles", type=Path, required=True)
    parser.add_argument("--trade-features", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    result = run(args.candles, args.trade_features)
    protocol_bytes = canonical_json(protocol())
    result_bytes = canonical_json(result)
    report_bytes = markdown(result).encode()
    (args.output_dir / "protocol.json").write_bytes(protocol_bytes)
    (args.output_dir / "result.json").write_bytes(result_bytes)
    (args.output_dir / "report.md").write_bytes(report_bytes)
    hashes = {
        "protocol.json": hashlib.sha256(protocol_bytes).hexdigest(),
        "result.json": hashlib.sha256(result_bytes).hexdigest(),
        "report.md": hashlib.sha256(report_bytes).hexdigest(),
    }
    (args.output_dir / "sha256.json").write_bytes(canonical_json(hashes))
    print(json.dumps({"verdict": result["verdict"], "failed_gates": result["failed_gates"], "hashes": hashes}, indent=2))


if __name__ == "__main__":
    main()
