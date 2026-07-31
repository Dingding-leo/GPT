#!/usr/bin/env python3
"""Frozen EOS/XLM three-observation intraday onset-survival experiment.

Own-instrument public 1H history only. Daily 00:00 UTC B1 is authoritative;
a cash state may enter early only after three consecutive completed positive
2160H endpoint observations. Exactly 5 bps one-way, next-open execution.
"""
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
DEFAULT_SEED = 20_260_731
FAMILY_ID = "three-observation-intraday-onset-survival-1h-v1"
ISSUE = 770


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n").encode()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def finite_or_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): finite_or_none(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [finite_or_none(v) for v in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def find_csv(data_root: Path, instrument: str) -> Path:
    candidates = [
        data_root / instrument / "snapshot" / f"okx-{instrument}-1H.normalized.csv",
        data_root / instrument / "snapshot" / f"okx-{instrument}-1H.csv",
        data_root / instrument / "candles.csv",
        data_root / instrument / "full" / "candles.csv",
    ]
    for path in candidates:
        if path.is_file():
            return path
    matches = list(data_root.glob(f"**/{instrument}/**/candles.csv"))
    matches += list(data_root.glob(f"**/okx-{instrument}-1H.normalized.csv"))
    matches += list(data_root.glob(f"**/okx-{instrument}-1H.csv"))
    matches = sorted(set(matches))
    if len(matches) != 1:
        raise FileNotFoundError(f"expected exactly one candle CSV for {instrument}, got {matches}")
    return matches[0]


def load_market(path: Path, instrument: str) -> dict[str, Any]:
    source = pd.read_csv(path)
    required = {"timestamp", "open", "close", "confirm"}
    if not required.issubset(source.columns):
        raise ValueError(f"{instrument}: missing columns {sorted(required - set(source.columns))}")
    source_rows = len(source)
    if source_rows < PREFIX_ROWS:
        raise ValueError(f"{instrument}: need at least {PREFIX_ROWS} rows, got {source_rows}")
    frame = source.iloc[:PREFIX_ROWS].copy()
    timestamps = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
    expected = pd.date_range(timestamps.iloc[0], periods=PREFIX_ROWS, freq="h", tz="UTC")
    if not np.array_equal(timestamps.array, expected.array):
        raise ValueError(f"{instrument}: first {PREFIX_ROWS} timestamps are not contiguous 1H")
    if timestamps.iloc[0] != pd.Timestamp("2021-07-24T00:00:00Z"):
        raise ValueError(f"{instrument}: unexpected first timestamp {timestamps.iloc[0]}")
    if timestamps.iloc[-1] != pd.Timestamp("2026-07-08T00:00:00Z"):
        raise ValueError(f"{instrument}: unexpected prefix end {timestamps.iloc[-1]}")
    confirm = pd.to_numeric(frame["confirm"], errors="raise").to_numpy()
    if not np.all(confirm == 1):
        raise ValueError(f"{instrument}: incomplete bar in frozen prefix")
    opens = pd.to_numeric(frame["open"], errors="raise").to_numpy(float)
    closes = pd.to_numeric(frame["close"], errors="raise").to_numpy(float)
    if not np.all(np.isfinite(opens)) or np.any(opens <= 0):
        raise ValueError(f"{instrument}: invalid opens")
    if not np.all(np.isfinite(closes)) or np.any(closes <= 0):
        raise ValueError(f"{instrument}: invalid closes")
    return {
        "timestamps": timestamps,
        "opens": opens,
        "closes": closes,
        "csv_path": str(path),
        "csv_sha256": sha256_file(path),
        "source_rows": source_rows,
    }


def build_paths(market: dict[str, Any]) -> dict[str, Any]:
    ts: pd.Series = market["timestamps"]
    opens: np.ndarray = market["opens"]
    closes: np.ndarray = market["closes"]
    n = len(closes)
    base = np.zeros(n, dtype=np.int8)
    base[2160:] = (closes[2160:] > closes[:-2160]).astype(np.int8)

    b1 = np.zeros(n, dtype=np.int8)
    candidate = np.zeros(n, dtype=np.int8)
    early_entry = np.zeros(n, dtype=bool)
    arm_run = np.zeros(n, dtype=np.int8)
    daily_update = np.zeros(n, dtype=bool)
    current_b1 = 0
    current_candidate = 0
    run = 0

    for t in range(2160, n):
        midnight = ts.iloc[t].hour == 0
        if midnight:
            current_b1 = int(base[t])
            current_candidate = int(base[t])
            run = 0
            daily_update[t] = True
        else:
            if current_candidate == 0:
                if base[t] == 1:
                    run = run + 1 if (t > 2160 and base[t - 1] == 1 and run > 0) else 1
                    if run == 3:
                        current_candidate = 1
                        early_entry[t] = True
                        run = 0
                else:
                    run = 0
            else:
                run = 0
        b1[t] = current_b1
        candidate[t] = current_candidate
        arm_run[t] = run

    midnight_mask = np.array([x.hour == 0 for x in ts], dtype=bool)
    valid_midnight = midnight_mask & (np.arange(n) >= 2160)
    if not np.array_equal(candidate[valid_midnight], base[valid_midnight]):
        raise AssertionError("daily candidate authority identity failed")
    transitions = np.diff(candidate.astype(int), prepend=0)
    non_midnight_exits = np.where((transitions == -1) & ~midnight_mask)[0]
    if non_midnight_exits.size:
        raise AssertionError(f"non-midnight exits detected: {non_midnight_exits[:5]}")
    entry_indices = np.flatnonzero(early_entry)
    for t in entry_indices:
        if midnight_mask[t] or t < 3 or not np.all(base[t - 2 : t + 1] == 1):
            raise AssertionError(f"invalid early-entry sequence at {t}")
        if candidate[t - 1] != 0 or candidate[t] != 1:
            raise AssertionError(f"invalid early-entry transition at {t}")
        if base[t - 3] != 0:
            raise AssertionError(f"early entry was not the third post-recross observation at {t}")

    market_return = opens[1:] / opens[:-1] - 1.0
    paths: dict[str, dict[str, np.ndarray]] = {}
    for name, signal in {"candidate": candidate, "B0": base, "B1": b1}.items():
        position = np.zeros(n - 1, dtype=float)
        position[1:] = signal[:-2]
        changes = np.abs(position - np.r_[0.0, position[:-1]])
        gross = position * market_return
        fee = FEE * changes
        net = gross - fee
        paths[name] = {
            "position": position,
            "changes": changes,
            "gross": gross,
            "fee": fee,
            "net": net,
        }
    return {
        "paths": paths,
        "features": {
            "base": base,
            "b1_signal": b1,
            "candidate_signal": candidate,
            "early_entry": early_entry,
            "arm_run": arm_run,
            "daily_update": daily_update,
        },
    }


def loss_clustering(returns: np.ndarray) -> dict[str, Any]:
    negative = returns < 0
    count = int(np.sum(negative))
    clusters: list[tuple[int, int]] = []
    start: int | None = None
    for i, is_negative in enumerate(negative):
        if is_negative and start is None:
            start = i
        if start is not None and (not is_negative or i == len(negative) - 1):
            end = i if not is_negative else i + 1
            clusters.append((start, end))
            start = None
    compounded = [float(np.prod(1.0 + returns[a:b]) - 1.0) for a, b in clusters]
    lengths = [b - a for a, b in clusters]
    return {
        "negative_hour_count": count,
        "cluster_count": len(clusters),
        "max_consecutive_negative_hours": max(lengths, default=0),
        "worst_negative_cluster_return": min(compounded, default=0.0),
    }


def metrics(path: dict[str, np.ndarray], start: int, end: int) -> dict[str, Any]:
    r = path["net"][start:end]
    gross = path["gross"][start:end]
    fees = path["fee"][start:end]
    changes = path["changes"][start:end]
    position = path["position"][start:end]
    wealth = np.cumprod(1.0 + r)
    curve = np.r_[1.0, wealth]
    drawdown = curve / np.maximum.accumulate(curve) - 1.0
    sd = float(np.std(r, ddof=1))
    turnover = float(np.sum(changes))
    return finite_or_none({
        "net_return": float(wealth[-1] - 1.0),
        "gross_arithmetic_return": float(np.sum(gross)),
        "net_arithmetic_return": float(np.sum(r)),
        "annualized_mean_return": float(np.mean(r) * ANNUAL_HOURS),
        "sharpe": float(np.mean(r) / sd * math.sqrt(ANNUAL_HOURS)) if sd > 0 else math.nan,
        "max_drawdown": float(np.min(drawdown)),
        "turnover": turnover,
        "fees": float(np.sum(fees)),
        "edge_per_turn_bps": float(np.sum(r) / turnover * 10_000) if turnover > 0 else math.nan,
        "mean_exposure": float(np.mean(position)),
        "exposure_hours": int(np.count_nonzero(position)),
        "position_changes": int(np.count_nonzero(changes)),
        "loss_clustering": loss_clustering(r),
    })


def fold_year_diagnostics(path: dict[str, np.ndarray], timestamps: pd.Series) -> dict[str, Any]:
    start, end = OOS
    folds: list[float] = []
    for left in range(start, end, FOLD_HOURS):
        right = left + FOLD_HOURS
        folds.append(float(np.prod(1.0 + path["net"][left:right]) - 1.0))
    positive = [x for x in folds if x > 0]
    concentration = max(positive) / sum(positive) if positive else math.inf
    years: dict[str, float] = {}
    interval_year = timestamps.iloc[:-1].dt.year.to_numpy()
    for year in sorted(set(interval_year[start:end])):
        mask = interval_year[start:end] == year
        years[str(int(year))] = float(np.prod(1.0 + path["net"][start:end][mask]) - 1.0)
    return finite_or_none({
        "fold_returns": folds,
        "profitable_folds": int(sum(x > 0 for x in folds)),
        "positive_fold_concentration": concentration,
        "year_returns": years,
        "profitable_years": int(sum(x > 0 for x in years.values())),
    })


def annualized_sharpe(values: np.ndarray) -> float:
    sd = float(np.std(values, ddof=1))
    return float(np.mean(values) / sd * math.sqrt(ANNUAL_HOURS)) if sd > 0 else math.nan


def paired_bootstrap(candidate: np.ndarray, benchmark: np.ndarray, *, resamples: int, seed: int) -> dict[str, Any]:
    n = len(candidate)
    rng = np.random.default_rng(seed)
    blocks = math.ceil(n / BLOCK_HOURS)
    mean_delta = np.empty(resamples)
    sharpe_delta = np.empty(resamples)
    for k in range(resamples):
        starts = rng.integers(0, n - BLOCK_HOURS + 1, size=blocks)
        idx = np.concatenate([np.arange(s, s + BLOCK_HOURS) for s in starts])[:n]
        a = candidate[idx]
        b = benchmark[idx]
        mean_delta[k] = float(np.mean(a - b) * ANNUAL_HOURS)
        sharpe_delta[k] = annualized_sharpe(a) - annualized_sharpe(b)
    result = {
        "method": "paired_non_circular_moving_block",
        "block_hours": BLOCK_HOURS,
        "resamples": resamples,
        "seed": seed,
        "annualized_mean_delta_point": float(np.mean(candidate - benchmark) * ANNUAL_HOURS),
        "annualized_mean_delta_ci95": [float(x) for x in np.quantile(mean_delta, [0.025, 0.975])],
        "sharpe_delta_point": annualized_sharpe(candidate) - annualized_sharpe(benchmark),
        "sharpe_delta_ci95": [float(x) for x in np.quantile(sharpe_delta, [0.025, 0.975])],
    }
    return finite_or_none(result)


def common_bootstrap(series: list[tuple[np.ndarray, np.ndarray]], *, resamples: int, seed: int) -> dict[str, Any]:
    n = len(series[0][0])
    if any(len(a) != n or len(b) != n for a, b in series):
        raise ValueError("common bootstrap arrays differ in length")
    rng = np.random.default_rng(seed)
    blocks = math.ceil(n / BLOCK_HOURS)
    median_mean = np.empty(resamples)
    median_sharpe = np.empty(resamples)
    for k in range(resamples):
        starts = rng.integers(0, n - BLOCK_HOURS + 1, size=blocks)
        idx = np.concatenate([np.arange(s, s + BLOCK_HOURS) for s in starts])[:n]
        means: list[float] = []
        sharpes: list[float] = []
        for candidate, benchmark in series:
            a = candidate[idx]
            b = benchmark[idx]
            means.append(float(np.mean(a - b) * ANNUAL_HOURS))
            sharpes.append(annualized_sharpe(a) - annualized_sharpe(b))
        median_mean[k] = float(np.median(means))
        median_sharpe[k] = float(np.median(sharpes))
    return finite_or_none({
        "method": "common_index_paired_non_circular_moving_block",
        "block_hours": BLOCK_HOURS,
        "resamples": resamples,
        "seed": seed,
        "median_annualized_mean_delta_ci95": [float(x) for x in np.quantile(median_mean, [0.025, 0.975])],
        "median_sharpe_delta_ci95": [float(x) for x in np.quantile(median_sharpe, [0.025, 0.975])],
    })


def event_diagnostics(market: dict[str, Any], built: dict[str, Any]) -> dict[str, Any]:
    ts: pd.Series = market["timestamps"]
    opens: np.ndarray = market["opens"]
    features = built["features"]
    paths = built["paths"]
    base: np.ndarray = features["base"]
    early_indices = np.flatnonzero(features["early_entry"])
    events: list[dict[str, Any]] = []
    horizons = (1, 3, 6, 12, 24)
    for t in early_indices:
        next_midnight = next((u for u in range(t + 1, min(t + 25, len(ts))) if ts.iloc[u].hour == 0), None)
        if next_midnight is None:
            continue
        start = t + 1
        end_fee = min(next_midnight + 1, len(paths["candidate"]["net"]) - 1)
        residual_slice = slice(start, end_fee + 1)
        decay: dict[str, float | None] = {}
        for horizon in horizons:
            if start + horizon < len(opens):
                decay[str(horizon)] = float(opens[start + horizon] / opens[start] - 1.0)
            else:
                decay[str(horizon)] = None
        events.append({
            "signal_bar": ts.iloc[t].isoformat(),
            "execution_open": ts.iloc[start].isoformat(),
            "next_daily_decision": ts.iloc[next_midnight].isoformat(),
            "survival_hours_to_daily_decision": int(next_midnight - t),
            "daily_confirmed": bool(base[next_midnight] == 1),
            "gross_residual_vs_B1": float(np.sum(paths["candidate"]["gross"][residual_slice] - paths["B1"]["gross"][residual_slice])),
            "fee_residual_vs_B1": float(np.sum(paths["candidate"]["fee"][residual_slice] - paths["B1"]["fee"][residual_slice])),
            "net_residual_vs_B1": float(np.sum(paths["candidate"]["net"][residual_slice] - paths["B1"]["net"][residual_slice])),
            "forward_open_returns": decay,
            "execution_interval_index": int(start),
        })

    def subset_stats(items: list[dict[str, Any]]) -> dict[str, Any]:
        residuals = [x["net_residual_vs_B1"] for x in items]
        return finite_or_none({
            "count": len(items),
            "mean_net_residual_vs_B1": float(np.mean(residuals)) if residuals else math.nan,
            "compound_event_residual": float(np.prod(1.0 + np.array(residuals)) - 1.0) if residuals else math.nan,
            "positive_event_fraction": float(np.mean(np.array(residuals) > 0)) if residuals else math.nan,
            "mean_forward_open_return_by_horizon": {
                str(h): float(np.mean([x["forward_open_returns"][str(h)] for x in items if x["forward_open_returns"][str(h)] is not None]))
                if any(x["forward_open_returns"][str(h)] is not None for x in items)
                else math.nan
                for h in horizons
            },
        })

    train_events = [x for x in events if TRAIN[0] <= x["execution_interval_index"] < TRAIN[1]]
    oos_events = [x for x in events if OOS[0] <= x["execution_interval_index"] < OOS[1]]
    train_stats = subset_stats(train_events)
    oos_stats = subset_stats(oos_events)
    confirmed = subset_stats([x for x in oos_events if x["daily_confirmed"]])
    failed = subset_stats([x for x in oos_events if not x["daily_confirmed"]])
    expected = train_stats["mean_net_residual_vs_B1"]
    realized = oos_stats["mean_net_residual_vs_B1"]
    calibration_gap = None if expected is None or realized is None else float(realized - expected)
    return {
        "event_count_full": len(events),
        "train": train_stats,
        "oos": oos_stats,
        "oos_daily_confirmed": confirmed,
        "oos_failed_before_daily_confirmation": failed,
        "expected_vs_realized": {
            "training_mean_event_residual": expected,
            "oos_mean_event_residual": realized,
            "calibration_gap": calibration_gap,
        },
        "events": events,
    }


def evaluate_market(instrument: str, market: dict[str, Any], built: dict[str, Any], resamples: int, seed: int) -> dict[str, Any]:
    paths = built["paths"]
    samples = {"train": TRAIN, "oos": OOS, "full": FULL}
    performance = {
        sample: {name: metrics(paths[name], *bounds) for name in ("candidate", "B0", "B1")}
        for sample, bounds in samples.items()
    }
    breadth = fold_year_diagnostics(paths["candidate"], market["timestamps"])
    candidate_oos = paths["candidate"]["net"][OOS[0] : OOS[1]]
    b1_oos = paths["B1"]["net"][OOS[0] : OOS[1]]
    residual = candidate_oos - b1_oos
    bootstrap = paired_bootstrap(candidate_oos, b1_oos, resamples=resamples, seed=seed)
    residual_sharpe = annualized_sharpe(residual)
    c = performance["oos"]["candidate"]
    b0 = performance["oos"]["B0"]
    b1 = performance["oos"]["B1"]
    gates = {
        "positive_oos_return": c["net_return"] > 0,
        "positive_oos_sharpe": c["sharpe"] is not None and c["sharpe"] > 0,
        "return_at_least_B1": c["net_return"] >= b1["net_return"],
        "sharpe_at_least_B1": c["sharpe"] is not None and b1["sharpe"] is not None and c["sharpe"] >= b1["sharpe"],
        "drawdown_no_worse_B1": c["max_drawdown"] >= b1["max_drawdown"] - 1e-12,
        "turnover_no_greater_B1": c["turnover"] <= b1["turnover"] + 1e-12,
        "turnover_below_B0": c["turnover"] < b0["turnover"],
        "edge_per_turn_at_least_B1": c["edge_per_turn_bps"] is not None and b1["edge_per_turn_bps"] is not None and c["edge_per_turn_bps"] >= b1["edge_per_turn_bps"],
        "profitable_folds_at_least_7": breadth["profitable_folds"] >= 7,
        "profitable_years_at_least_3": breadth["profitable_years"] >= 3,
        "positive_fold_concentration_at_most_0_5": breadth["positive_fold_concentration"] is not None and breadth["positive_fold_concentration"] <= 0.5,
        "positive_residual_sharpe": math.isfinite(residual_sharpe) and residual_sharpe > 0,
        "mean_delta_ci_lower_positive": bootstrap["annualized_mean_delta_ci95"][0] > 0,
        "sharpe_delta_ci_lower_positive": bootstrap["sharpe_delta_ci95"][0] > 0,
        "positive_full_return": performance["full"]["candidate"]["net_return"] > 0,
    }
    candidate_pos = paths["candidate"]["position"][OOS[0] : OOS[1]]
    b1_pos = paths["B1"]["position"][OOS[0] : OOS[1]]
    candidate_only = candidate_pos > b1_pos
    b1_only = b1_pos > candidate_pos
    onset = event_diagnostics(market, built)
    early_signal = built["features"]["early_entry"]
    diagnostics = {
        "oos_signal_frequency": float(np.mean(candidate_pos > 0)),
        "oos_no_trade_frequency": float(np.mean(candidate_pos == 0)),
        "oos_early_entry_signal_count": int(np.sum(early_signal[OOS[0] : OOS[1]])),
        "oos_candidate_only_hours": int(np.sum(candidate_only)),
        "oos_B1_only_hours": int(np.sum(b1_only)),
        "oos_candidate_only_gross_contribution": float(np.sum(paths["candidate"]["gross"][OOS[0] : OOS[1]][candidate_only] - paths["B1"]["gross"][OOS[0] : OOS[1]][candidate_only])),
        "oos_total_net_residual_vs_B1": float(np.sum(residual)),
        "oos_fee_delta_vs_B1": float(np.sum(paths["candidate"]["fee"][OOS[0] : OOS[1]] - paths["B1"]["fee"][OOS[0] : OOS[1]])),
        "onset_events": onset,
    }
    return finite_or_none({
        "instrument": instrument,
        "source": {
            "csv_path": market["csv_path"],
            "csv_sha256": market["csv_sha256"],
            "source_rows": market["source_rows"],
            "frozen_prefix_rows": PREFIX_ROWS,
            "frozen_start": market["timestamps"].iloc[0].isoformat(),
            "frozen_end": market["timestamps"].iloc[-1].isoformat(),
            "future_suffix_rows_unread_for_scoring": max(0, market["source_rows"] - PREFIX_ROWS),
        },
        "performance": performance,
        "breadth": breadth,
        "residual_sharpe_vs_B1": residual_sharpe,
        "bootstrap_vs_B1": bootstrap,
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "diagnostics": diagnostics,
    })


def fmt_pct(value: float | None) -> str:
    return "undefined" if value is None else f"{100 * value:+.2f}%"


def fmt_num(value: float | None, digits: int = 3) -> str:
    return "undefined" if value is None else f"{value:.{digits}f}"


def write_report(output_dir: Path, result: dict[str, Any]) -> None:
    verdict = result["verdict"]
    lines = [
        "# Three-observation intraday onset survival — terminal evidence",
        "",
        "## Frozen protocol",
        "",
        f"- Family: `{FAMILY_ID}`",
        "- Markets: EOS-USDT and XLM-USDT, evaluated independently",
        "- Signal: own completed 1H close versus its own 2,160H-lagged close",
        "- Daily 00:00 UTC B1 state is authoritative; non-midnight cash-to-long requires three consecutive positive endpoint observations",
        "- Non-midnight exit is prohibited; next-open execution; exactly 5 bps one way",
        "- Candidate count `1`; parameter grid `0`; no credentials, accounts, orders, leverage, synthetic data, 15m, cross-sectional selection, pairs, spreads, or post-hoc filtering",
        "",
        "## Development-OOS scorecard",
        "",
        "| Market | Candidate net | B1 net | Candidate Sharpe | B1 Sharpe | Candidate DD | B1 DD | Turnover | B1 turnover | Fees | Edge/turn | Residual Sharpe | Folds | Years | Pass |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for market in result["markets"]:
        c = market["performance"]["oos"]["candidate"]
        b1 = market["performance"]["oos"]["B1"]
        lines.append(
            f"| {market['instrument']} | {fmt_pct(c['net_return'])} | {fmt_pct(b1['net_return'])} | "
            f"{fmt_num(c['sharpe'])} | {fmt_num(b1['sharpe'])} | {fmt_pct(c['max_drawdown'])} | "
            f"{fmt_pct(b1['max_drawdown'])} | {c['turnover']:.1f} | {b1['turnover']:.1f} | "
            f"{fmt_pct(c['fees'])} | {fmt_num(c['edge_per_turn_bps'], 2)} bps | "
            f"{fmt_num(market['residual_sharpe_vs_B1'])} | {market['breadth']['profitable_folds']}/12 | "
            f"{market['breadth']['profitable_years']}/4 | {market['all_gates_passed']} |"
        )
    lines += ["", "## Onset survival, calibration and decay", ""]
    for market in result["markets"]:
        d = market["diagnostics"]
        e = d["onset_events"]
        lines += [
            f"### {market['instrument']}",
            "",
            f"- OOS early entries: `{d['oos_early_entry_signal_count']}`; candidate-only exposure: `{d['oos_candidate_only_hours']}` hours; B1-only exposure: `{d['oos_B1_only_hours']}` hours.",
            f"- OOS signal frequency: `{100*d['oos_signal_frequency']:.2f}%`; no-trade frequency: `{100*d['oos_no_trade_frequency']:.2f}%`.",
            f"- Training expected mean event residual: `{fmt_pct(e['expected_vs_realized']['training_mean_event_residual'])}`; OOS realised: `{fmt_pct(e['expected_vs_realized']['oos_mean_event_residual'])}`; calibration gap: `{fmt_pct(e['expected_vs_realized']['calibration_gap'])}`.",
            f"- Daily-confirmed OOS onsets: `{e['oos_daily_confirmed']['count']}`, mean residual `{fmt_pct(e['oos_daily_confirmed']['mean_net_residual_vs_B1'])}`; failed onsets: `{e['oos_failed_before_daily_confirmation']['count']}`, mean residual `{fmt_pct(e['oos_failed_before_daily_confirmation']['mean_net_residual_vs_B1'])}`.",
            f"- Total OOS net residual versus B1: `{fmt_pct(d['oos_total_net_residual_vs_B1'])}`; fee delta: `{fmt_pct(d['oos_fee_delta_vs_B1'])}`.",
            "",
        ]
    lines += ["## Dependence-aware uncertainty", ""]
    for market in result["markets"]:
        boot = market["bootstrap_vs_B1"]
        lines.append(
            f"- {market['instrument']}: annualised mean delta 95% CI `{boot['annualized_mean_delta_ci95']}`; Sharpe delta 95% CI `{boot['sharpe_delta_ci95']}`."
        )
    common = result["common_bootstrap_vs_B1"]
    lines += [
        f"- Common-index median annualised mean delta 95% CI: `{common['median_annualized_mean_delta_ci95']}`.",
        f"- Common-index median Sharpe delta 95% CI: `{common['median_sharpe_delta_ci95']}`.",
        "",
        "## Strategy-facing discrepancy",
        "",
        result["strategy_facing_discrepancy"]["diagnosis"],
        "",
        "## Verdict",
        "",
        f"`{verdict}`",
        "",
        f"Both markets passed every gate: `{result['bilateral_all_gates_passed']}`.",
        "This result is research evidence only and does not authorise paper or live trading.",
        "",
        "## Next strategy-facing action",
        "",
        result["next_strategy_action"],
        "",
    ]
    (output_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--instrument", action="append", required=True)
    parser.add_argument("--resamples", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--source-workflow-run", required=True)
    parser.add_argument("--tested-sha", required=True)
    args = parser.parse_args()
    if args.instrument != ["EOS-USDT", "XLM-USDT"]:
        raise ValueError("frozen instrument order must be EOS-USDT then XLM-USDT")
    if args.resamples != 5000 or args.seed != DEFAULT_SEED:
        raise ValueError("frozen bootstrap contract changed")

    built_all: list[dict[str, Any]] = []
    evaluated: list[dict[str, Any]] = []
    for offset, instrument in enumerate(args.instrument):
        market = load_market(find_csv(args.data_root, instrument), instrument)
        built = build_paths(market)
        evaluation = evaluate_market(instrument, market, built, args.resamples, args.seed + offset)
        built_all.append(built)
        evaluated.append(evaluation)

    common_series = [
        (
            built["paths"]["candidate"]["net"][OOS[0] : OOS[1]],
            built["paths"]["B1"]["net"][OOS[0] : OOS[1]],
        )
        for built in built_all
    ]
    common = common_bootstrap(common_series, resamples=args.resamples, seed=args.seed)
    bilateral = all(x["all_gates_passed"] for x in evaluated)
    common_pass = (
        common["median_annualized_mean_delta_ci95"][0] > 0
        and common["median_sharpe_delta_ci95"][0] > 0
    )
    accepted = bilateral and common_pass
    verdict = (
        "accept_three_observation_intraday_onset_survival_family_shadow_only"
        if accepted
        else "reject_three_observation_intraday_onset_survival_family"
    )

    failures = []
    for market in evaluated:
        failed_names = [name for name, passed in market["gates"].items() if not passed]
        failures.append((market, failed_names))
    selected, failed_gates = max(failures, key=lambda item: len(item[1]))
    onset = selected["diagnostics"]["onset_events"]
    confirmed = onset["oos_daily_confirmed"]
    failed = onset["oos_failed_before_daily_confirmation"]
    if selected["performance"]["oos"]["candidate"]["turnover"] > selected["performance"]["oos"]["B1"]["turnover"]:
        diagnosis = (
            f"{selected['instrument']} violated the frozen B1-turnover gate. Three-observation confirmation still produced "
            f"{failed['count']} OOS onsets that failed before the next daily decision versus {confirmed['count']} that were daily-confirmed. "
            f"Failed onsets averaged {fmt_pct(failed['mean_net_residual_vs_B1'])} net residual and the total fee delta was "
            f"{fmt_pct(selected['diagnostics']['oos_fee_delta_vs_B1'])}. The discrepancy is residual onset false-start clustering, "
            "not chronology, next-open timing, fee identity, cross-sectional selection, or source integrity."
        )
        classification = "three_observation_false_onset_turnover_discrepancy"
    else:
        diagnosis = (
            f"{selected['instrument']} failed gates {failed_gates}. Daily-confirmed onsets averaged "
            f"{fmt_pct(confirmed['mean_net_residual_vs_B1'])} versus {fmt_pct(failed['mean_net_residual_vs_B1'])} for failed onsets. "
            "The discrepancy is economic timing transportability, not a data, chronology, next-open, state, or fee defect."
        )
        classification = "onset_timing_transportability_discrepancy"

    result = finite_or_none({
        "schema_version": 1,
        "family_id": FAMILY_ID,
        "issue": ISSUE,
        "tested_sha": args.tested_sha,
        "source_workflow_run": str(args.source_workflow_run),
        "provider": "OKX public unauthenticated SPOT candles",
        "bar": "1H",
        "canonical_fee_bps_one_way": 5.0,
        "candidate_count": 1,
        "parameter_grid_count": 0,
        "markets_independent": True,
        "cross_sectional_selection": False,
        "pairs_spreads_cointegration": False,
        "credentials_used": False,
        "private_endpoints_used": False,
        "actual_orders": False,
        "leverage": False,
        "synthetic_data": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "sample": {
            "prefix_rows": PREFIX_ROWS,
            "start": "2021-07-24T00:00:00Z",
            "end": "2026-07-08T00:00:00Z",
            "train": list(TRAIN),
            "development_oos": list(OOS),
            "full": list(FULL),
            "oos_folds": 12,
            "fold_hours": FOLD_HOURS,
        },
        "rule": {
            "base": "close[t] > close[t-2160H]",
            "daily_authority": "completed 00:00 UTC bar sets candidate exactly to base and clears arm",
            "early_entry": "while cash, enter after three consecutive completed positive non-midnight base observations",
            "non_midnight_exit": False,
            "execution": "next hourly open",
            "fee": "0.0005 * abs(exposure change)",
        },
        "markets": evaluated,
        "common_bootstrap_vs_B1": common,
        "bilateral_all_gates_passed": bilateral,
        "common_uncertainty_gates_passed": common_pass,
        "strategy_facing_discrepancy": {
            "classification": classification,
            "selected_instrument": selected["instrument"],
            "failed_gates": failed_gates,
            "diagnosis": diagnosis,
            "policy_or_accounting_defect_detected": False,
        },
        "training_authorized_correction": {
            "permitted": False,
            "applied": False,
            "reason": "issue #770 freezes run length, horizon, markets, cadence, fee, execution and gates; same-cohort rescue is prohibited",
        },
        "verdict": verdict,
        "next_strategy_action": (
            "retain the candidate only as shadow research evidence on a fully fresh future epoch; do not alter the nominated BTC/ETH policy or authorise trading"
            if accepted
            else "terminally reject this exact EOS/XLM family, do not rescue the run length or cohort, and continue the immutable BTC/ETH prospective shadow"
        ),
    })

    args.output_dir.mkdir(parents=True, exist_ok=True)
    result_path = args.output_dir / "result.json"
    result_path.write_bytes(canonical_bytes(result))
    digest = sha256_file(result_path)
    (args.output_dir / "result.sha256").write_text(digest + "\n", encoding="utf-8")
    summary = {
        "family_id": FAMILY_ID,
        "tested_sha": args.tested_sha,
        "result_sha256": digest,
        "verdict": verdict,
        "bilateral_all_gates_passed": bilateral,
        "common_uncertainty_gates_passed": common_pass,
        "markets": [
            {
                "instrument": x["instrument"],
                "all_gates_passed": x["all_gates_passed"],
                "oos_candidate": x["performance"]["oos"]["candidate"],
                "oos_B1": x["performance"]["oos"]["B1"],
                "residual_sharpe_vs_B1": x["residual_sharpe_vs_B1"],
                "failed_gates": [name for name, passed in x["gates"].items() if not passed],
            }
            for x in evaluated
        ],
    }
    (args.output_dir / "result-summary.json").write_bytes(canonical_bytes(summary))
    write_report(args.output_dir, result)
    print(json.dumps(summary, sort_keys=True, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
