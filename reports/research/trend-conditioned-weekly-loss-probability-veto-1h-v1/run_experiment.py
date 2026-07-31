#!/usr/bin/env python3
"""Run the frozen trend-conditioned weekly loss-probability veto experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

FEE = 0.0005
ANNUAL_HOURS = 24 * 365
PREFIX_ROWS = 43_441
TRAIN = (2_880, 17_520)
OOS = (17_520, 43_440)
FULL = (2_880, 43_440)
FOLD_HOURS = 2_160
BLOCK_HOURS = 168
HURDLE = 0.001
MIN_HISTORY = 64
NEIGHBOURS = 32
WILSON_Z = 1.6448536269514722
DEFAULT_SEED = 20_260_731


def canonical_bytes(value: Any) -> bytes:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return (text + "\n").encode()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def finite_or_none(value: float) -> float | None:
    return float(value) if np.isfinite(value) else None


def find_csv(data_root: Path, instrument: str) -> Path:
    candidates = [
        data_root / instrument / "snapshot" / f"okx-{instrument}-1H.normalized.csv",
        data_root / instrument / "snapshot" / f"okx-{instrument}-1H.csv",
        data_root / instrument / "candles.csv",
    ]
    matches = [path for path in candidates if path.is_file()]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one source CSV for {instrument}: {matches}")
    return matches[0]


def load_market(path: Path, instrument: str) -> dict[str, Any]:
    frame = pd.read_csv(path)
    source_rows = len(frame)
    if source_rows < PREFIX_ROWS:
        raise ValueError(f"{instrument} has only {source_rows} rows")
    required = {"timestamp", "open", "close", "confirm"}
    if not required.issubset(frame.columns):
        raise ValueError(f"{instrument} source columns are incomplete")
    frame = frame.iloc[:PREFIX_ROWS].copy()
    timestamps = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
    if timestamps.duplicated().any() or not timestamps.is_monotonic_increasing:
        raise ValueError(f"{instrument} timestamps are not unique and increasing")
    expected = pd.date_range(timestamps.iloc[0], periods=PREFIX_ROWS, freq="1h")
    if not np.array_equal(timestamps.to_numpy(), expected.to_numpy()):
        raise ValueError(f"{instrument} frozen prefix is not contiguous 1H data")
    confirm = pd.to_numeric(frame["confirm"], errors="raise").to_numpy()
    if not np.all(confirm == 1):
        raise ValueError(f"{instrument} includes an unconfirmed bar")
    opens = pd.to_numeric(frame["open"], errors="raise").to_numpy(float)
    closes = pd.to_numeric(frame["close"], errors="raise").to_numpy(float)
    if not np.all(np.isfinite(opens)) or not np.all(opens > 0):
        raise ValueError(f"{instrument} contains invalid opens")
    if not np.all(np.isfinite(closes)) or not np.all(closes > 0):
        raise ValueError(f"{instrument} contains invalid closes")
    return {
        "instrument": instrument,
        "csv_path": str(path),
        "csv_sha256": sha256_file(path),
        "source_rows": source_rows,
        "timestamps": timestamps.reset_index(drop=True),
        "opens": opens,
        "closes": closes,
    }


def features(market: dict[str, Any]) -> np.ndarray:
    close = market["closes"]
    log_close = np.log(close)
    returns = np.diff(log_close, prepend=np.nan)
    output = np.full((len(close), 6), np.nan)
    for column, window in enumerate((168, 720, 2_160)):
        output[window:, column] = log_close[window:] - log_close[:-window]

    squared = np.nan_to_num(returns) ** 2
    downside = np.minimum(np.nan_to_num(returns), 0.0) ** 2
    prefix_squared = np.r_[0.0, np.cumsum(squared)]
    prefix_downside = np.r_[0.0, np.cumsum(downside)]
    rms: dict[int, np.ndarray] = {}
    downside_rms: dict[int, np.ndarray] = {}
    for window in (168, 2_160):
        values = np.full(len(close), np.nan)
        downside_values = np.full(len(close), np.nan)
        index = np.arange(window, len(close))
        values[index] = np.sqrt(
            (prefix_squared[index + 1] - prefix_squared[index + 1 - window]) / window
        )
        downside_values[index] = np.sqrt(
            (prefix_downside[index + 1] - prefix_downside[index + 1 - window]) / window
        )
        rms[window] = values
        downside_rms[window] = downside_values

    valid = (rms[2_160] > 0) & (downside_rms[2_160] > 0)
    output[valid, 3] = rms[168][valid] / rms[2_160][valid] - 1.0
    output[valid, 4] = downside_rms[168][valid] / downside_rms[2_160][valid] - 1.0
    trailing_high = pd.Series(close).rolling(720, min_periods=720).max().to_numpy(float)
    output[:, 5] = close / trailing_high - 1.0
    if not np.all(np.isfinite(output[2_160:])):
        raise ValueError("non-finite frozen feature after 2160H warm-up")
    return output


def wilson_lower(loss_count: int, sample_size: int) -> float:
    if sample_size <= 0 or loss_count < 0 or loss_count > sample_size:
        raise ValueError("invalid Wilson inputs")
    proportion = loss_count / sample_size
    z_squared = WILSON_Z**2
    denominator = 1.0 + z_squared / sample_size
    centre = (proportion + z_squared / (2.0 * sample_size)) / denominator
    half_width = (
        WILSON_Z
        * math.sqrt(
            proportion * (1.0 - proportion) / sample_size
            + z_squared / (4.0 * sample_size**2)
        )
        / denominator
    )
    return centre - half_width


def build_paths(market: dict[str, Any]) -> dict[str, Any]:
    timestamps = market["timestamps"]
    closes = market["closes"]
    opens = market["opens"]
    length = len(closes)
    feature_values = features(market)

    base = np.zeros(length, dtype=np.int8)
    base[2_160:] = (closes[2_160:] > closes[:-2_160]).astype(np.int8)
    daily_b1 = np.zeros(length, dtype=np.int8)
    candidate = np.zeros(length, dtype=np.int8)
    decision_mask = np.zeros(length, dtype=bool)
    history_rows = np.zeros(length, dtype=np.int32)
    neighbor_losses = np.full(length, -1, dtype=np.int16)
    loss_rate = np.full(length, np.nan)
    probability_lower = np.full(length, np.nan)
    realized_label = np.full(length, np.nan)
    weekly_veto = np.zeros(length, dtype=np.int8)

    anchors = np.flatnonzero(
        (timestamps.dt.dayofweek.to_numpy() == 0) & (timestamps.dt.hour.to_numpy() == 0)
    )
    anchor_set = set(int(value) for value in anchors)
    current_b1 = 0
    current_candidate = 0
    current_veto = 0

    for time_index in range(2_160, length):
        if time_index in anchor_set:
            decision_mask[time_index] = True
            eligible = anchors[(anchors >= 2_160) & (anchors + 169 <= time_index)]
            history_rows[time_index] = len(eligible)
            if time_index + 169 < length:
                realized_label[time_index] = (
                    opens[time_index + 169] / opens[time_index + 1] - 1.0
                )
            if len(eligible) >= MIN_HISTORY:
                historical_features = feature_values[eligible]
                centre = np.median(historical_features, axis=0)
                scale = np.median(np.abs(historical_features - centre), axis=0)
                scale[~np.isfinite(scale) | (scale <= 0)] = 1.0
                scaled_history = (historical_features - centre) / scale
                scaled_query = (feature_values[time_index] - centre) / scale
                distance = np.sum((scaled_history - scaled_query) ** 2, axis=1)
                order = np.lexsort((eligible, distance))[:NEIGHBOURS]
                neighbours = eligible[order]
                labels = opens[neighbours + 169] / opens[neighbours + 1] - 1.0
                losses = labels <= HURDLE
                loss_count = int(np.sum(losses))
                lower = wilson_lower(loss_count, NEIGHBOURS)
                neighbor_losses[time_index] = loss_count
                loss_rate[time_index] = loss_count / NEIGHBOURS
                probability_lower[time_index] = lower
                current_veto = int(lower > 0.5)
            else:
                current_veto = 0

        if timestamps.iloc[time_index].hour == 0:
            current_b1 = int(base[time_index])
            current_candidate = int(current_b1 == 1 and current_veto == 0)

        weekly_veto[time_index] = current_veto
        daily_b1[time_index] = current_b1
        candidate[time_index] = current_candidate

    if np.any(candidate > daily_b1):
        raise ValueError("candidate is not a strict subset of daily B1")

    signals = {"candidate": candidate, "B0": base, "B1": daily_b1}
    paths: dict[str, dict[str, np.ndarray]] = {}
    market_return = opens[1:] / opens[:-1] - 1.0
    for name, signal in signals.items():
        position = np.zeros(length - 1, dtype=float)
        position[1:] = signal[:-2]
        changes = np.abs(position - np.r_[0.0, position[:-1]])
        gross = position * market_return
        fee = FEE * changes
        paths[name] = {
            "signal": signal,
            "position": position,
            "changes": changes,
            "gross": gross,
            "fee": fee,
            "net": gross - fee,
        }

    return {
        "paths": paths,
        "decision_mask": decision_mask,
        "history_rows": history_rows,
        "neighbor_losses": neighbor_losses,
        "loss_rate": loss_rate,
        "probability_lower": probability_lower,
        "realized_label": realized_label,
        "weekly_veto": weekly_veto,
    }


def sharpe_value(returns: np.ndarray) -> float:
    if len(returns) < 2:
        return float("nan")
    standard_deviation = float(np.std(returns, ddof=1))
    if not np.isfinite(standard_deviation) or standard_deviation <= 0:
        return float("nan")
    return float(np.mean(returns) / standard_deviation * math.sqrt(ANNUAL_HOURS))


def metrics(path: dict[str, np.ndarray], start: int, end: int) -> dict[str, Any]:
    net = path["net"][start:end]
    gross = path["gross"][start:end]
    fee = path["fee"][start:end]
    changes = path["changes"][start:end]
    position = path["position"][start:end]
    if not (
        len(net) == len(gross) == len(fee) == len(changes) == len(position) == end - start
    ):
        raise ValueError("metric slice length mismatch")
    if np.any(1.0 + net <= 0):
        raise ValueError("non-positive wealth factor")
    wealth = np.cumprod(1.0 + net)
    wealth_with_initial = np.r_[1.0, wealth]
    running_peak = np.maximum.accumulate(wealth_with_initial)
    drawdown = wealth_with_initial / running_peak - 1.0
    turnover = float(np.sum(changes))
    arithmetic_net = float(np.sum(net))
    return {
        "net_return": float(wealth[-1] - 1.0) if len(wealth) else 0.0,
        "gross_arithmetic_return": float(np.sum(gross)),
        "net_arithmetic_return": arithmetic_net,
        "sharpe": finite_or_none(sharpe_value(net)),
        "max_drawdown": float(np.min(drawdown)),
        "turnover": turnover,
        "fees": float(np.sum(fee)),
        "edge_per_turn_bps": (
            finite_or_none(arithmetic_net / turnover * 10_000.0) if turnover > 0 else None
        ),
        "mean_exposure": float(np.mean(position)) if len(position) else 0.0,
    }


def fold_year_diagnostics(
    path: dict[str, np.ndarray], timestamps: pd.Series
) -> dict[str, Any]:
    start, end = OOS
    fold_returns = []
    for fold_start in range(start, end, FOLD_HOURS):
        fold_end = min(fold_start + FOLD_HOURS, end)
        values = path["net"][fold_start:fold_end]
        fold_returns.append(float(np.prod(1.0 + values) - 1.0))
    positive = [value for value in fold_returns if value > 0]
    concentration = None
    if positive:
        concentration = float(max(positive) / sum(positive))

    return_timestamps = timestamps.iloc[1:].reset_index(drop=True)
    years = return_timestamps.iloc[start:end].dt.year.to_numpy()
    oos_net = path["net"][start:end]
    year_returns: dict[str, float] = {}
    for year in sorted(set(int(value) for value in years)):
        values = oos_net[years == year]
        year_returns[str(year)] = float(np.prod(1.0 + values) - 1.0)
    return {
        "fold_returns": fold_returns,
        "profitable_folds": int(sum(value > 0 for value in fold_returns)),
        "positive_fold_concentration": concentration,
        "year_returns": year_returns,
        "profitable_years": int(sum(value > 0 for value in year_returns.values())),
    }


def residual_sharpe(candidate: np.ndarray, benchmark: np.ndarray) -> float | None:
    return finite_or_none(sharpe_value(candidate - benchmark))


def bootstrap_starts(length: int, resamples: int, seed: int) -> np.ndarray:
    if length < BLOCK_HOURS:
        raise ValueError("OOS sample shorter than block length")
    blocks = math.ceil(length / BLOCK_HOURS)
    generator = np.random.default_rng(seed)
    return generator.integers(
        0,
        length - BLOCK_HOURS + 1,
        size=(resamples, blocks),
        endpoint=False,
    )


def sampled_indices(block_starts: np.ndarray, length: int) -> np.ndarray:
    blocks = [np.arange(start, start + BLOCK_HOURS) for start in block_starts]
    return np.concatenate(blocks)[:length]


def paired_bootstrap(
    candidate: np.ndarray, benchmark: np.ndarray, starts: np.ndarray
) -> dict[str, Any]:
    if len(candidate) != len(benchmark):
        raise ValueError("paired bootstrap length mismatch")
    sampled_mean = np.empty(len(starts))
    sampled_sharpe = np.empty(len(starts))
    for index, block_starts in enumerate(starts):
        indices = sampled_indices(block_starts, len(candidate))
        candidate_sample = candidate[indices]
        benchmark_sample = benchmark[indices]
        sampled_mean[index] = float(
            np.mean(candidate_sample - benchmark_sample) * ANNUAL_HOURS
        )
        sampled_sharpe[index] = sharpe_value(candidate_sample) - sharpe_value(
            benchmark_sample
        )
    finite_sharpe = sampled_sharpe[np.isfinite(sampled_sharpe)]
    sharpe_interval = [None, None]
    if len(finite_sharpe):
        sharpe_interval = [
            float(value) for value in np.quantile(finite_sharpe, [0.025, 0.975])
        ]
    return {
        "annualized_mean_delta_point": float(
            np.mean(candidate - benchmark) * ANNUAL_HOURS
        ),
        "annualized_mean_delta_ci95": [
            float(value) for value in np.quantile(sampled_mean, [0.025, 0.975])
        ],
        "sharpe_delta_point": finite_or_none(
            sharpe_value(candidate) - sharpe_value(benchmark)
        ),
        "sharpe_delta_ci95": sharpe_interval,
        "finite_sharpe_resamples": int(len(finite_sharpe)),
    }


def group_labels(mask: np.ndarray, labels: np.ndarray) -> dict[str, Any]:
    values = labels[mask]
    return {
        "count": int(np.sum(mask)),
        "mean_realized_168h": finite_or_none(float(np.mean(values))) if len(values) else None,
        "positive_fraction": float(np.mean(values > 0)) if len(values) else None,
        "fee_hurdle_success_fraction": (
            float(np.mean(values > HURDLE)) if len(values) else None
        ),
        "sum_realized_168h": float(np.sum(values)),
    }


def veto_diagnostics(built: dict[str, Any]) -> dict[str, Any]:
    start, end = OOS
    index = np.arange(len(built["decision_mask"]))
    valid = (
        built["decision_mask"]
        & (index >= start)
        & (index < end)
        & np.isfinite(built["probability_lower"])
        & np.isfinite(built["realized_label"])
    )
    vetoed = valid & (built["probability_lower"] > 0.5)
    allowed = valid & ~vetoed
    lower = built["probability_lower"]
    labels = built["realized_label"]
    realized_loss = labels <= HURDLE
    correlation = None
    if np.sum(valid) > 1 and np.std(lower[valid]) > 0 and np.std(realized_loss[valid]) > 0:
        correlation = finite_or_none(
            float(np.corrcoef(lower[valid], realized_loss[valid].astype(float))[0, 1])
        )

    candidate = built["paths"]["candidate"]
    benchmark = built["paths"]["B1"]
    candidate_position = candidate["position"][start:end]
    benchmark_position = benchmark["position"][start:end]
    candidate_only = (candidate_position == 1) & (benchmark_position == 0)
    benchmark_only = (candidate_position == 0) & (benchmark_position == 1)
    if np.any(candidate_only):
        raise ValueError("candidate-only exposure violates veto architecture")
    gross_timing = float(
        np.sum(candidate["gross"][start:end] - benchmark["gross"][start:end])
    )
    fee_contribution = float(
        np.sum(benchmark["fee"][start:end] - candidate["fee"][start:end])
    )
    net_residual = float(
        np.sum(candidate["net"][start:end] - benchmark["net"][start:end])
    )
    if not np.isclose(gross_timing + fee_contribution, net_residual, atol=1e-12):
        raise ValueError("candidate-minus-B1 decomposition failure")

    valid_lower = lower[valid]
    valid_losses = built["neighbor_losses"][valid]
    return {
        "eligible_oos_weekly_decisions": int(np.sum(valid)),
        "vetoed_weekly_decisions": int(np.sum(vetoed)),
        "veto_frequency": float(np.mean(vetoed[valid])) if np.any(valid) else 0.0,
        "allowed": group_labels(allowed, labels),
        "vetoed": group_labels(vetoed, labels),
        "wilson_lower_min_median_max": (
            [float(np.min(valid_lower)), float(np.median(valid_lower)), float(np.max(valid_lower))]
            if len(valid_lower)
            else [None, None, None]
        ),
        "neighbor_loss_count_min_median_max": (
            [int(np.min(valid_losses)), float(np.median(valid_losses)), int(np.max(valid_losses))]
            if len(valid_losses)
            else [None, None, None]
        ),
        "wilson_lower_realized_loss_correlation": correlation,
        "median_history_rows": (
            float(np.median(built["history_rows"][valid])) if np.any(valid) else None
        ),
        "candidate_only_hours": int(np.sum(candidate_only)),
        "b1_only_hours": int(np.sum(benchmark_only)),
        "gross_timing_residual": gross_timing,
        "fee_contribution": fee_contribution,
        "net_arithmetic_residual": net_residual,
    }


def ci_lower_positive(interval: list[float | None]) -> bool:
    return interval[0] is not None and interval[0] > 0


def evaluate_market(
    instrument: str,
    market: dict[str, Any],
    built: dict[str, Any],
    starts: np.ndarray,
) -> dict[str, Any]:
    paths = built["paths"]
    samples = {"train": TRAIN, "oos": OOS, "full": FULL}
    performance = {
        sample: {
            name: metrics(paths[name], *bounds) for name in ("candidate", "B0", "B1")
        }
        for sample, bounds in samples.items()
    }
    breadth = fold_year_diagnostics(paths["candidate"], market["timestamps"])
    start, end = OOS
    candidate_oos = paths["candidate"]["net"][start:end]
    benchmark_oos = paths["B1"]["net"][start:end]
    bootstrap = paired_bootstrap(candidate_oos, benchmark_oos, starts)
    residual = residual_sharpe(candidate_oos, benchmark_oos)
    candidate_metrics = performance["oos"]["candidate"]
    benchmark_metrics = performance["oos"]["B1"]
    concentration = breadth["positive_fold_concentration"]
    gates = {
        "positive_oos_return": candidate_metrics["net_return"] > 0,
        "return_at_least_B1": (
            candidate_metrics["net_return"] >= benchmark_metrics["net_return"]
        ),
        "sharpe_at_least_B1": (
            candidate_metrics["sharpe"] is not None
            and benchmark_metrics["sharpe"] is not None
            and candidate_metrics["sharpe"] >= benchmark_metrics["sharpe"]
        ),
        "drawdown_no_worse_B1": (
            candidate_metrics["max_drawdown"] >= benchmark_metrics["max_drawdown"]
        ),
        "turnover_no_worse_B1": (
            candidate_metrics["turnover"] <= benchmark_metrics["turnover"]
        ),
        "edge_per_turn_positive_and_at_least_B1": (
            candidate_metrics["edge_per_turn_bps"] is not None
            and benchmark_metrics["edge_per_turn_bps"] is not None
            and candidate_metrics["edge_per_turn_bps"] > 0
            and candidate_metrics["edge_per_turn_bps"]
            >= benchmark_metrics["edge_per_turn_bps"]
        ),
        "profitable_folds_at_least_7": breadth["profitable_folds"] >= 7,
        "profitable_years_at_least_3": breadth["profitable_years"] >= 3,
        "positive_fold_concentration_at_most_0_5": (
            concentration is not None and concentration <= 0.5
        ),
        "positive_residual_sharpe": residual is not None and residual > 0,
        "mean_delta_ci_lower_positive": ci_lower_positive(
            bootstrap["annualized_mean_delta_ci95"]
        ),
        "sharpe_delta_ci_lower_positive": ci_lower_positive(
            bootstrap["sharpe_delta_ci95"]
        ),
        "positive_full_return": performance["full"]["candidate"]["net_return"] > 0,
    }
    return {
        "instrument": instrument,
        "source": {
            "csv_path": market["csv_path"],
            "csv_sha256": market["csv_sha256"],
            "source_rows": market["source_rows"],
            "frozen_prefix_rows": PREFIX_ROWS,
            "frozen_start": market["timestamps"].iloc[0].isoformat(),
            "frozen_end": market["timestamps"].iloc[-1].isoformat(),
        },
        "performance": performance,
        "breadth": breadth,
        "residual_sharpe_vs_B1": residual,
        "bootstrap_vs_B1": bootstrap,
        "veto_diagnostics": veto_diagnostics(built),
        "gates": gates,
        "accepted": all(gates.values()),
    }


def common_bootstrap(
    built_markets: list[dict[str, Any]], starts: np.ndarray
) -> dict[str, Any]:
    start, end = OOS
    point_means = []
    point_sharpes = []
    sampled_mean = np.empty(len(starts))
    sampled_sharpe = np.empty(len(starts))
    for built in built_markets:
        candidate = built["paths"]["candidate"]["net"][start:end]
        benchmark = built["paths"]["B1"]["net"][start:end]
        point_means.append(float(np.mean(candidate - benchmark) * ANNUAL_HOURS))
        point_sharpes.append(sharpe_value(candidate) - sharpe_value(benchmark))
    for sample_index, block_starts in enumerate(starts):
        means = []
        sharpes = []
        for built in built_markets:
            candidate_all = built["paths"]["candidate"]["net"][start:end]
            benchmark_all = built["paths"]["B1"]["net"][start:end]
            indices = sampled_indices(block_starts, len(candidate_all))
            candidate = candidate_all[indices]
            benchmark = benchmark_all[indices]
            means.append(float(np.mean(candidate - benchmark) * ANNUAL_HOURS))
            sharpes.append(sharpe_value(candidate) - sharpe_value(benchmark))
        sampled_mean[sample_index] = float(np.median(means))
        sampled_sharpe[sample_index] = float(np.median(sharpes))
    finite_sharpe = sampled_sharpe[np.isfinite(sampled_sharpe)]
    sharpe_interval: list[float | None] = [None, None]
    if len(finite_sharpe):
        sharpe_interval = [
            float(value) for value in np.quantile(finite_sharpe, [0.025, 0.975])
        ]
    return {
        "annualized_mean_delta_point": float(np.median(point_means)),
        "annualized_mean_delta_ci95": [
            float(value) for value in np.quantile(sampled_mean, [0.025, 0.975])
        ],
        "sharpe_delta_point": finite_or_none(float(np.median(point_sharpes))),
        "sharpe_delta_ci95": sharpe_interval,
        "finite_sharpe_resamples": int(len(finite_sharpe)),
    }


def format_optional(value: float | None, digits: int = 3) -> str:
    return "undefined" if value is None else f"{value:+.{digits}f}"


def report(result: dict[str, Any]) -> str:
    lines = [
        "# Trend-conditioned weekly loss-probability veto evidence",
        "",
        "```text",
        f"Family          {result['family_id']}",
        "Candidate count 1",
        "Parameter grid  0",
        "Fee             exactly 5 bps one way",
        f"Verdict         {result['verdict']}",
        "```",
        "",
    ]
    for item in result["markets"]:
        lines.extend(
            [
                f"## {item['instrument']}",
                "",
                "| Sample | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |",
                "|---|---|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for sample in ("train", "oos", "full"):
            for policy in ("candidate", "B1", "B0"):
                value = item["performance"][sample][policy]
                lines.append(
                    f"| {sample} | {policy} | {value['net_return']:+.2%} | "
                    f"{format_optional(value['sharpe'])} | {value['max_drawdown']:+.2%} | "
                    f"{value['turnover']:.0f} | {value['fees']:.2%} | "
                    f"{format_optional(value['edge_per_turn_bps'], 2)} bps |"
                )
        diagnostics = item["veto_diagnostics"]
        bootstrap = item["bootstrap_vs_B1"]
        lines.extend(
            [
                "",
                f"Breadth: {item['breadth']['profitable_folds']}/12 profitable folds; "
                f"{item['breadth']['profitable_years']}/4 profitable years; residual "
                f"Sharpe {format_optional(item['residual_sharpe_vs_B1'])}.",
                "",
                f"Eligible OOS weekly decisions: "
                f"{diagnostics['eligible_oos_weekly_decisions']}; vetoed "
                f"{diagnostics['vetoed_weekly_decisions']}; veto frequency "
                f"{diagnostics['veto_frequency']:.2%}.",
                "",
                f"Wilson lower min/median/max "
                f"{diagnostics['wilson_lower_min_median_max']}; neighbor-loss count "
                f"min/median/max {diagnostics['neighbor_loss_count_min_median_max']}.",
                "",
                f"Vetoed label sum {diagnostics['vetoed']['sum_realized_168h']:+.2%}; "
                f"allowed label sum {diagnostics['allowed']['sum_realized_168h']:+.2%}. "
                f"Gross timing residual {diagnostics['gross_timing_residual']:+.2%}; "
                f"fee contribution {diagnostics['fee_contribution']:+.2%}; net arithmetic "
                f"residual {diagnostics['net_arithmetic_residual']:+.2%}.",
                "",
                f"Annualised mean delta 95% CI "
                f"{bootstrap['annualized_mean_delta_ci95']}; Sharpe delta 95% CI "
                f"{bootstrap['sharpe_delta_ci95']}.",
                "",
            ]
        )
    lines.extend(
        [
            "## Common-index inference",
            "",
            json.dumps(result["common_bootstrap_vs_B1"], sort_keys=True),
            "",
            f"Markets passing every gate: {result['markets_passing_every_gate']}/2.",
            "",
            "## Verdict",
            "",
            f"`{result['verdict']}`",
            "",
            "No paper or live-trading authority is created.",
            "",
        ]
    )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    raw_markets = []
    built_markets = []
    for instrument in args.instrument:
        market = load_market(find_csv(args.data_root, instrument), instrument)
        built = build_paths(market)
        raw_markets.append((instrument, market))
        built_markets.append(built)
    starts = bootstrap_starts(OOS[1] - OOS[0], args.resamples, args.seed)
    evaluated = [
        evaluate_market(instrument, market, built, starts)
        for (instrument, market), built in zip(
            raw_markets, built_markets, strict=True
        )
    ]
    common = common_bootstrap(built_markets, starts)
    accepted = (
        all(item["accepted"] for item in evaluated)
        and ci_lower_positive(common["annualized_mean_delta_ci95"])
        and ci_lower_positive(common["sharpe_delta_ci95"])
    )
    return {
        "schema_version": 1,
        "family_id": "trend-conditioned-weekly-loss-probability-veto-1h-v1",
        "issue": 779,
        "tested_sha": args.tested_sha,
        "source_workflow_run": args.source_workflow_run,
        "candidate_count": 1,
        "parameter_grid": 0,
        "markets_fixed_preperformance": list(args.instrument),
        "provider": "OKX public confirmed SPOT",
        "bar": "1H",
        "fee_bps_one_way": 5.0,
        "execution": "daily completed 00:00 UTC trend decision; next hourly open",
        "samples": {"train": TRAIN, "oos": OOS, "full": FULL},
        "model": {
            "direction": "daily 2160H endpoint trend",
            "label": "non-overlapping next-open 168H fee-hurdle loss Bernoulli",
            "loss_hurdle": HURDLE,
            "minimum_history": MIN_HISTORY,
            "neighbours": NEIGHBOURS,
            "wilson_z": WILSON_Z,
            "veto_boundary": 0.5,
            "normalization": "causal historical median and MAD",
        },
        "markets": evaluated,
        "common_bootstrap_vs_B1": common,
        "markets_passing_every_gate": int(sum(item["accepted"] for item in evaluated)),
        "accepted": accepted,
        "verdict": (
            "support_trend_conditioned_weekly_loss_probability_veto_research_nomination"
            if accepted
            else "reject_trend_conditioned_weekly_loss_probability_veto_family"
        ),
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--instrument", action="append", required=True)
    parser.add_argument("--resamples", type=int, default=5_000)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--source-workflow-run", default="local")
    parser.add_argument("--tested-sha", default="local")
    args = parser.parse_args()
    if len(args.instrument) != 2 or len(set(args.instrument)) != 2:
        raise ValueError("exactly two distinct fixed instruments are required")
    result = run(args)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    result_path = args.output_dir / "result.json"
    result_path.write_bytes(canonical_bytes(result))
    summary = {
        "family_id": result["family_id"],
        "tested_sha": result["tested_sha"],
        "candidate_count": 1,
        "parameter_grid": 0,
        "markets_passing_every_gate": result["markets_passing_every_gate"],
        "verdict": result["verdict"],
        "result_sha256": sha256_file(result_path),
        "market_headlines": {
            item["instrument"]: {
                "candidate_oos": item["performance"]["oos"]["candidate"],
                "B1_oos": item["performance"]["oos"]["B1"],
                "breadth": item["breadth"],
                "residual_sharpe_vs_B1": item["residual_sharpe_vs_B1"],
                "accepted": item["accepted"],
            }
            for item in result["markets"]
        },
    }
    (args.output_dir / "result-summary.json").write_bytes(canonical_bytes(summary))
    (args.output_dir / "report.md").write_text(report(result), encoding="utf-8")


if __name__ == "__main__":
    main()
