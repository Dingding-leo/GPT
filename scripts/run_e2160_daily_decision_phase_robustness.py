from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

FAMILY_ID = "canonical-e2160-daily-decision-phase-robustness-audit-1h-v1"
ISSUE = 1110
RESEARCH_PARENT = "5a0fcc97d1a882f8223656c51f5bb8055f534e38"
BAR = "1H"
FEE = 0.0005
ANNUALIZATION = 8760.0
HORIZON = 2160
PREFIX_ROWS = 43_441
TRAIN = (2_880, 17_520)
OOS = (17_520, 43_440)
FULL = (2_880, 43_440)
FOLD_HOURS = 2_160
FOLD_COUNT = 12
BOOTSTRAP_DRAWS = 5_000
BOOTSTRAP_BLOCK = 168
BOOTSTRAP_SEED = 2026080819
OUTPUT = Path("reports/research/e2160-daily-decision-phase-robustness-audit-1h-v1")
SOURCES = {
    "BTC-USDT": {
        "artifact_id": 8704977298,
        "csv_name": "snapshot/okx-BTC-USDT-1H.csv",
        "csv_sha256": "92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9",
    },
    "ETH-USDT": {
        "artifact_id": 8704978112,
        "csv_name": "snapshot/okx-ETH-USDT-1H.csv",
        "csv_sha256": "2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726",
    },
}
LEGACY_B1 = {
    "BTC-USDT": {
        "training": {
            "net_return": -0.41290619030236553,
            "sharpe": -0.8402669561161515,
            "max_drawdown": -0.5592198563591351,
            "turnover": 28.0,
        },
        "oos": {
            "net_return": 1.1968197962400904,
            "sharpe": 0.953765119416238,
            "max_drawdown": -0.2654678573881635,
            "turnover": 45.0,
        },
        "full": {
            "net_return": 0.2897393033937914,
            "sharpe": 0.3317518863849881,
            "max_drawdown": -0.5592198563591351,
            "turnover": 73.0,
        },
    },
    "ETH-USDT": {
        "training": {
            "net_return": -0.4058878437623247,
            "sharpe": -0.5841780885870211,
            "max_drawdown": -0.5695187578011079,
            "turnover": 23.0,
        },
        "oos": {
            "net_return": 0.7451603410954828,
            "sharpe": 0.6456279607587625,
            "max_drawdown": -0.4776594160762392,
            "turnover": 30.0,
        },
        "full": {
            "net_return": 0.03682097322871436,
            "sharpe": 0.23303476477091944,
            "max_drawdown": -0.5695187578011079,
            "turnover": 53.0,
        },
    },
}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _jsonable(value):
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, np.ndarray):
        return [_jsonable(item) for item in value.tolist()]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def load_artifact(path: Path, instrument: str) -> tuple[pd.DataFrame, dict[str, object]]:
    spec = SOURCES[instrument]
    artifact_raw = path.read_bytes()
    with zipfile.ZipFile(io.BytesIO(artifact_raw)) as archive:
        names = archive.namelist()
        if spec["csv_name"] not in names:
            raise ValueError(f"{instrument}: expected CSV missing from artifact")
        csv_raw = archive.read(spec["csv_name"])
    csv_hash = _sha(csv_raw)
    if csv_hash != spec["csv_sha256"]:
        raise ValueError(f"{instrument}: CSV hash mismatch {csv_hash}")

    frame = pd.read_csv(io.BytesIO(csv_raw), nrows=PREFIX_ROWS)
    if len(frame) != PREFIX_ROWS:
        raise ValueError(f"{instrument}: expected {PREFIX_ROWS} parsed rows")
    required = {"timestamp", "open", "high", "low", "close", "confirm"}
    if not required.issubset(frame.columns):
        raise ValueError(f"{instrument}: missing required source columns")
    timestamps = pd.DatetimeIndex(pd.to_datetime(frame["timestamp"], utc=True))
    expected = pd.date_range(timestamps[0], periods=PREFIX_ROWS, freq="h")
    if not timestamps.equals(expected):
        raise ValueError(f"{instrument}: source is not a contiguous UTC-hour grid")
    if not timestamps.is_unique or not timestamps.is_monotonic_increasing:
        raise ValueError(f"{instrument}: source chronology is not unique and monotonic")
    values = frame[["open", "high", "low", "close"]].to_numpy(dtype=float)
    if not np.isfinite(values).all() or not (values > 0).all():
        raise ValueError(f"{instrument}: non-finite or non-positive OHLC")
    row_max = frame[["open", "close", "low"]].max(axis=1).to_numpy(float)
    row_min = frame[["open", "close", "high"]].min(axis=1).to_numpy(float)
    if not (frame["high"].to_numpy(float) >= row_max).all():
        raise ValueError(f"{instrument}: invalid high ordering")
    if not (frame["low"].to_numpy(float) <= row_min).all():
        raise ValueError(f"{instrument}: invalid low ordering")
    if not frame["confirm"].eq(1).all():
        raise ValueError(f"{instrument}: source contains incomplete candles")
    frame = frame.copy()
    frame.index = timestamps
    return frame, {
        "artifact_id": spec["artifact_id"],
        "artifact_zip_sha256": _sha(artifact_raw),
        "csv_sha256": csv_hash,
        "parsed_prefix_rows": PREFIX_ROWS,
        "prefix_start": timestamps[0].isoformat(),
        "prefix_end": timestamps[-1].isoformat(),
        "provider": "OKX",
        "market_type": "SPOT",
        "bar": BAR,
        "completed_only": True,
        "later_suffix_unparsed_and_unscored": True,
    }


def annualized_sharpe(values: np.ndarray) -> float | None:
    series = np.asarray(values, dtype=float)
    if len(series) < 2:
        return None
    standard_deviation = float(series.std(ddof=1))
    if not math.isfinite(standard_deviation) or standard_deviation <= 0:
        return None
    return float(math.sqrt(ANNUALIZATION) * series.mean() / standard_deviation)


def _metrics(
    net: np.ndarray,
    gross: np.ndarray,
    position: np.ndarray,
    turnover_by_hour: np.ndarray,
    terminal: bool,
) -> dict[str, object]:
    wealth = np.cumprod(1.0 + net)
    equity = np.r_[1.0, wealth]
    drawdown = equity / np.maximum.accumulate(equity) - 1.0
    turnover = float(turnover_by_hour.sum())
    return {
        "net_return": float(wealth[-1] - 1.0),
        "annualized_arithmetic_mean": float(ANNUALIZATION * net.mean()),
        "sharpe": annualized_sharpe(net),
        "max_drawdown": float(drawdown.min()),
        "exposure": float(position.mean()),
        "turnover": turnover,
        "transition_count": int(round(turnover)),
        "modeled_fee_drag": float(FEE * turnover),
        "arithmetic_gross_sum": float(gross.sum()),
        "arithmetic_net_sum": float(net.sum()),
        "edge_per_turnover_bps": (
            float(net.sum() / turnover * 10_000.0) if turnover > 0 else None
        ),
        "terminal_liquidation": terminal,
    }


def simulate_isolated_segment(
    frame: pd.DataFrame,
    phase: int,
    start: int,
    end: int,
    latency_hours: int = 0,
) -> dict[str, object]:
    if phase not in range(24) or latency_hours not in (0, 1):
        raise ValueError("invalid phase or latency")
    if not HORIZON <= start < end <= len(frame) - 1:
        raise ValueError("segment outside frozen source")
    close = frame["close"].to_numpy(dtype=float)
    open_price = frame["open"].to_numpy(dtype=float)
    hours = frame.index.hour.to_numpy(dtype=np.int8)
    size = end - start
    position = np.zeros(size, dtype=float)
    turnover = np.zeros(size, dtype=float)

    signal_lo = max(HORIZON, start - 1 - latency_hours)
    signal_hi = end - 1 - latency_hours
    candidates = np.arange(signal_lo, signal_hi + 1, dtype=int)
    signals = candidates[hours[candidates] == phase]
    executions = signals + 1 + latency_hours
    keep = (executions >= start) & (executions < end)
    signals = signals[keep]
    executions = executions[keep]
    targets = (close[signals] > close[signals - HORIZON]).astype(float)

    current = 0.0
    cursor = start
    for execution_index, target in zip(executions.tolist(), targets.tolist(), strict=True):
        if execution_index > cursor:
            position[cursor - start : execution_index - start] = current
        local = execution_index - start
        if target != current:
            turnover[local] += abs(target - current)
            current = target
        cursor = execution_index
    if cursor < end:
        position[cursor - start :] = current

    market = open_price[start + 1 : end + 1] / open_price[start:end] - 1.0
    gross = position * market
    net = gross - FEE * turnover
    terminal = bool(current == 1.0)
    if terminal:
        turnover[-1] += 1.0
        net[-1] -= FEE
    if not np.allclose(net, gross - FEE * turnover, rtol=0.0, atol=1e-15):
        raise ValueError("exact five-basis-point fee identity failed")
    if np.any((position != 0.0) & (position != 1.0)):
        raise ValueError("position domain left unlevered long/cash")
    return {
        "net": net,
        "gross": gross,
        "position": position,
        "turnover_by_hour": turnover,
        "terminal_liquidation": terminal,
    }


def legacy_continuous_phase0(frame: pd.DataFrame) -> dict[str, dict[str, object]]:
    close = frame["close"].to_numpy(dtype=float)
    open_price = frame["open"].to_numpy(dtype=float)
    position = np.zeros(len(frame) - 1, dtype=float)
    current = 0.0
    pending: dict[int, float] = {}
    for index in range(len(position)):
        if index in pending:
            current = pending[index]
        position[index] = current
        if index >= HORIZON and frame.index[index].hour == 0:
            execution_index = index + 1
            if execution_index < len(position):
                pending[execution_index] = float(close[index] > close[index - HORIZON])
    market = open_price[1:] / open_price[:-1] - 1.0
    turnover = np.r_[abs(position[0]), np.abs(np.diff(position))]
    gross = position * market
    net = gross - FEE * turnover
    if not np.allclose(net, gross - FEE * turnover, rtol=0.0, atol=1e-15):
        raise ValueError("legacy comparator fee identity failed")
    result = {}
    for label, (start, end) in {
        "training": TRAIN,
        "oos": OOS,
        "full": FULL,
    }.items():
        result[label] = _metrics(
            net[start:end],
            gross[start:end],
            position[start:end],
            turnover[start:end],
            False,
        )
    return result


def verify_legacy_parity(
    instrument: str,
    observed: dict[str, dict[str, object]],
) -> dict[str, object]:
    checks = {}
    for segment, expected in LEGACY_B1[instrument].items():
        segment_checks = {}
        for field, expected_value in expected.items():
            observed_value = observed[segment][field]
            segment_checks[field] = bool(
                math.isclose(
                    float(observed_value),
                    float(expected_value),
                    rel_tol=0.0,
                    abs_tol=1e-12,
                )
            )
        checks[segment] = segment_checks
    return {
        "checks": checks,
        "passes": bool(all(all(item.values()) for item in checks.values())),
    }


def phase_metrics(
    frame: pd.DataFrame,
    phase: int,
    latency_hours: int,
) -> tuple[dict[str, dict[str, object]], dict[str, dict[str, object]]]:
    metrics = {}
    paths = {}
    for label, span in {
        "training": TRAIN,
        "oos": OOS,
        "full": FULL,
    }.items():
        path = simulate_isolated_segment(
            frame,
            phase,
            *span,
            latency_hours=latency_hours,
        )
        paths[label] = path
        metrics[label] = _metrics(
            path["net"],
            path["gross"],
            path["position"],
            path["turnover_by_hour"],
            bool(path["terminal_liquidation"]),
        )
    return metrics, paths


def oos_breadth(frame: pd.DataFrame, phase: int, latency_hours: int) -> dict[str, object]:
    fold_returns = []
    for fold_index in range(FOLD_COUNT):
        start = OOS[0] + fold_index * FOLD_HOURS
        end = start + FOLD_HOURS
        path = simulate_isolated_segment(
            frame,
            phase,
            start,
            end,
            latency_hours=latency_hours,
        )
        fold_returns.append(
            _metrics(
                path["net"],
                path["gross"],
                path["position"],
                path["turnover_by_hour"],
                bool(path["terminal_liquidation"]),
            )["net_return"]
        )
    positive = [float(value) for value in fold_returns if value > 0]
    concentration = max(positive) / sum(positive) if positive and sum(positive) > 0 else None

    source_indices = np.arange(len(frame))
    years = {}
    for year in sorted(set(frame.index[OOS[0] : OOS[1]].year)):
        matching = np.flatnonzero(
            (frame.index.year == year)
            & (source_indices >= OOS[0])
            & (source_indices < OOS[1])
        )
        start = int(matching[0])
        end = int(matching[-1]) + 1
        path = simulate_isolated_segment(
            frame,
            phase,
            start,
            end,
            latency_hours=latency_hours,
        )
        years[str(int(year))] = _metrics(
            path["net"],
            path["gross"],
            path["position"],
            path["turnover_by_hour"],
            bool(path["terminal_liquidation"]),
        )["net_return"]
    return {
        "fold_returns": [float(value) for value in fold_returns],
        "profitable_folds": int(sum(value > 0 for value in fold_returns)),
        "positive_fold_concentration": (
            float(concentration) if concentration is not None else None
        ),
        "year_returns": years,
        "profitable_years": int(sum(value > 0 for value in years.values())),
    }


def percentile_rank(values: np.ndarray, index: int) -> float:
    target = values[index]
    less = int(np.sum(values < target))
    equal = int(np.sum(values == target))
    return float((less + 0.5 * equal) / len(values))


def cross_phase_summary(records: dict[int, dict[str, object]]) -> dict[str, object]:
    oos_return = np.asarray(
        [records[phase]["metrics"]["oos"]["net_return"] for phase in range(24)],
        dtype=float,
    )
    oos_sharpe = np.asarray(
        [records[phase]["metrics"]["oos"]["sharpe"] for phase in range(24)],
        dtype=float,
    )
    oos_turnover = np.asarray(
        [records[phase]["metrics"]["oos"]["turnover"] for phase in range(24)],
        dtype=float,
    )
    oos_edge = np.asarray(
        [
            records[phase]["metrics"]["oos"]["edge_per_turnover_bps"]
            for phase in range(24)
        ],
        dtype=float,
    )
    drawdown_severity = np.asarray(
        [-records[phase]["metrics"]["oos"]["max_drawdown"] for phase in range(24)],
        dtype=float,
    )
    full_return = np.asarray(
        [records[phase]["metrics"]["full"]["net_return"] for phase in range(24)],
        dtype=float,
    )
    full_sharpe = np.asarray(
        [records[phase]["metrics"]["full"]["sharpe"] for phase in range(24)],
        dtype=float,
    )
    quantiles = (0.10, 0.25, 0.50, 0.75, 0.90)
    return {
        "oos_net_return_quantiles": {
            f"q{int(q * 100):02d}": float(np.quantile(oos_return, q)) for q in quantiles
        },
        "oos_sharpe_quantiles": {
            f"q{int(q * 100):02d}": float(np.quantile(oos_sharpe, q)) for q in quantiles
        },
        "oos_median_turnover": float(np.median(oos_turnover)),
        "oos_median_edge_per_turnover_bps": float(np.median(oos_edge)),
        "oos_median_drawdown_severity": float(np.median(drawdown_severity)),
        "oos_q75_drawdown_severity": float(np.quantile(drawdown_severity, 0.75)),
        "positive_oos_return_and_sharpe_phases": int(
            np.sum((oos_return > 0) & (oos_sharpe > 0))
        ),
        "positive_oos_return_phases": int(np.sum(oos_return > 0)),
        "fold_breadth_phases_7_of_12": int(
            sum(records[phase]["breadth"]["profitable_folds"] >= 7 for phase in range(24))
        ),
        "year_breadth_phases_3_of_4": int(
            sum(records[phase]["breadth"]["profitable_years"] >= 3 for phase in range(24))
        ),
        "phase0_oos_return_percentile_rank": percentile_rank(oos_return, 0),
        "phase0_oos_sharpe_percentile_rank": percentile_rank(oos_sharpe, 0),
        "full_median_net_return": float(np.median(full_return)),
        "full_median_sharpe": float(np.median(full_sharpe)),
    }


def moving_block_inference(oos_paths: list[np.ndarray]) -> dict[str, object]:
    matrix = np.vstack(oos_paths)
    median_path = np.median(matrix, axis=0)
    sample_size = len(median_path)
    block_count = math.ceil(sample_size / BOOTSTRAP_BLOCK)
    offsets = np.arange(BOOTSTRAP_BLOCK)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    means = np.empty(BOOTSTRAP_DRAWS, dtype=float)
    sharpes = np.empty(BOOTSTRAP_DRAWS, dtype=float)
    for start in range(0, BOOTSTRAP_DRAWS, 100):
        stop = min(BOOTSTRAP_DRAWS, start + 100)
        block_starts = rng.integers(
            0,
            sample_size - BOOTSTRAP_BLOCK + 1,
            size=(stop - start, block_count),
        )
        indices = (block_starts[:, :, None] + offsets).reshape(stop - start, -1)[
            :, :sample_size
        ]
        sample = median_path[indices]
        means[start:stop] = ANNUALIZATION * sample.mean(axis=1)
        standard_deviation = sample.std(axis=1, ddof=1)
        sharpes[start:stop] = (
            math.sqrt(ANNUALIZATION) * sample.mean(axis=1) / standard_deviation
        )
    return {
        "method": (
            "non-circular moving-block resample of aligned 24-phase hourly "
            "median net-return series"
        ),
        "block_hours": BOOTSTRAP_BLOCK,
        "draws": BOOTSTRAP_DRAWS,
        "seed": BOOTSTRAP_SEED,
        "median_path_net_return": float(np.prod(1.0 + median_path) - 1.0),
        "median_path_annualized_arithmetic_mean": float(
            ANNUALIZATION * median_path.mean()
        ),
        "median_path_sharpe": annualized_sharpe(median_path),
        "annualized_mean_ci95": [
            float(np.quantile(means, 0.025)),
            float(np.quantile(means, 0.975)),
        ],
        "sharpe_ci95": [
            float(np.quantile(sharpes, 0.025)),
            float(np.quantile(sharpes, 0.975)),
        ],
    }


def market_audit(frame: pd.DataFrame, instrument: str) -> dict[str, object]:
    legacy = legacy_continuous_phase0(frame)
    parity = verify_legacy_parity(instrument, legacy)
    if not parity["passes"]:
        raise ValueError(f"{instrument}: frozen phase-0 comparator parity failed")

    standard: dict[int, dict[str, object]] = {}
    delayed: dict[int, dict[str, object]] = {}
    standard_oos_paths = []
    for phase in range(24):
        metrics, paths = phase_metrics(frame, phase, 0)
        standard[phase] = {
            "metrics": metrics,
            "breadth": oos_breadth(frame, phase, 0),
        }
        standard_oos_paths.append(paths["oos"]["net"])
        delayed_metrics, _ = phase_metrics(frame, phase, 1)
        delayed[phase] = {
            "metrics": delayed_metrics,
            "breadth": oos_breadth(frame, phase, 1),
        }

    summary = cross_phase_summary(standard)
    delayed_summary = cross_phase_summary(delayed)
    inference = moving_block_inference(standard_oos_paths)
    phase0 = standard[0]["metrics"]["oos"]
    return {
        "legacy_phase0_comparator": legacy,
        "legacy_phase0_parity": parity,
        "phase0_isolated_accounting": standard[0],
        "phases": standard,
        "latency_plus_1h_phases": delayed,
        "cross_phase": summary,
        "latency_plus_1h_cross_phase": delayed_summary,
        "cross_phase_median_inference": inference,
        "benchmark_comparison": {
            "benchmark": "phase 0 canonical daily E2160",
            "median_oos_net_return_delta": float(
                summary["oos_net_return_quantiles"]["q50"] - phase0["net_return"]
            ),
            "median_oos_sharpe_delta": float(
                summary["oos_sharpe_quantiles"]["q50"] - phase0["sharpe"]
            ),
            "median_oos_turnover_ratio": float(
                summary["oos_median_turnover"] / phase0["turnover"]
            ),
            "q75_drawdown_severity_delta": float(
                summary["oos_q75_drawdown_severity"] + phase0["max_drawdown"]
            ),
        },
    }


def acceptance(market: dict[str, object]) -> dict[str, bool]:
    summary = market["cross_phase"]
    delayed = market["latency_plus_1h_cross_phase"]
    inference = market["cross_phase_median_inference"]
    phase0 = market["phase0_isolated_accounting"]["metrics"]["oos"]
    return {
        "source_fee_next_open_and_phase0_parity": bool(
            market["legacy_phase0_parity"]["passes"]
        ),
        "oos_cross_phase_median_positive": bool(
            summary["oos_net_return_quantiles"]["q50"] > 0
            and summary["oos_sharpe_quantiles"]["q50"] > 0
        ),
        "at_least_18_of_24_positive_return_and_sharpe": bool(
            summary["positive_oos_return_and_sharpe_phases"] >= 18
        ),
        "at_least_18_of_24_have_7_of_12_profitable_folds": bool(
            summary["fold_breadth_phases_7_of_12"] >= 18
        ),
        "at_least_18_of_24_have_3_profitable_years": bool(
            summary["year_breadth_phases_3_of_4"] >= 18
        ),
        "phase0_between_10th_and_90th_percentiles": bool(
            0.10 <= summary["phase0_oos_return_percentile_rank"] <= 0.90
            and 0.10 <= summary["phase0_oos_sharpe_percentile_rank"] <= 0.90
        ),
        "oos_q25_return_and_sharpe_positive": bool(
            summary["oos_net_return_quantiles"]["q25"] > 0
            and summary["oos_sharpe_quantiles"]["q25"] > 0
        ),
        "median_path_moving_block_lower_bounds_positive": bool(
            inference["annualized_mean_ci95"][0] > 0
            and inference["sharpe_ci95"][0] > 0
        ),
        "median_edge_per_turnover_retains_75pct_phase0": bool(
            summary["oos_median_edge_per_turnover_bps"] > 0
            and summary["oos_median_edge_per_turnover_bps"]
            >= 0.75 * phase0["edge_per_turnover_bps"]
        ),
        "q75_drawdown_severity_within_5pct_phase0": bool(
            summary["oos_q75_drawdown_severity"] <= -phase0["max_drawdown"] + 0.05
        ),
        "plus_1h_latency_breadth": bool(
            delayed["oos_net_return_quantiles"]["q50"] > 0
            and delayed["oos_sharpe_quantiles"]["q50"] > 0
            and delayed["positive_oos_return_phases"] >= 18
        ),
        "full_cross_phase_median_positive": bool(
            summary["full_median_net_return"] > 0
            and summary["full_median_sharpe"] > 0
        ),
        "no_phase_or_market_selection": True,
    }


def build_report(evidence: dict[str, object]) -> str:
    lines = [
        "# Canonical E2160 Daily Decision-Phase Robustness Audit — Terminal Report",
        "",
        (
            f"Family: `{FAMILY_ID}`. Candidate count **0**; parameter grid **0**. "
            "All 24 UTC phases are mandatory robustness perturbations, never selectable strategies."
        ),
        "",
        "## Frozen data and accounting",
        "",
        (
            "Public immutable confirmed OKX SPOT 1H BTC-USDT / ETH-USDT artifacts "
            "were reused with exact CSV SHA-256 verification. The parsed prefix is exactly "
            "43,441 rows. Training is `[2880,17520)`, development OOS `[17520,43440)`, "
            "and full scored is `[2880,43440)`. Every scored segment starts from cash, "
            "executes each phase signal at the next hourly open, charges exactly 5 bps on "
            "every one-way position change, and liquidates at the exclusive segment end "
            "when still long."
        ),
        "",
        (
            "The historical continuous-accounting phase-0 comparator was reproduced exactly "
            "before the isolated 24-phase audit. Later source suffix rows were not parsed or scored."
        ),
        "",
        "## OOS phase robustness",
        "",
        (
            "| Market | Phase 0 net / Sharpe | 24-phase q25 net / Sharpe | "
            "24-phase median net / Sharpe | Positive phases | Fold breadth >=7/12 | "
            "Year breadth >=3/4 | Median turnover | Median edge/turn | q75 DD severity |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for instrument, market in evidence["markets"].items():
        p0 = market["phase0_isolated_accounting"]["metrics"]["oos"]
        summary = market["cross_phase"]
        lines.append(
            f"| {instrument} | {p0['net_return']:+.4%} / {p0['sharpe']:+.3f} | "
            f"{summary['oos_net_return_quantiles']['q25']:+.4%} / "
            f"{summary['oos_sharpe_quantiles']['q25']:+.3f} | "
            f"{summary['oos_net_return_quantiles']['q50']:+.4%} / "
            f"{summary['oos_sharpe_quantiles']['q50']:+.3f} | "
            f"{summary['positive_oos_return_and_sharpe_phases']}/24 | "
            f"{summary['fold_breadth_phases_7_of_12']}/24 | "
            f"{summary['year_breadth_phases_3_of_4']}/24 | "
            f"{summary['oos_median_turnover']:.0f} | "
            f"{summary['oos_median_edge_per_turnover_bps']:+.2f} bp | "
            f"{summary['oos_q75_drawdown_severity']:.2%} |"
        )
    lines += [
        "",
        "## Dependence-aware uncertainty",
        "",
        (
            "| Market | Median-path annualised mean | Mean 95% CI | "
            "Median-path Sharpe | Sharpe 95% CI |"
        ),
        "|---|---:|---:|---:|---:|",
    ]
    for instrument, market in evidence["markets"].items():
        inference = market["cross_phase_median_inference"]
        lines.append(
            f"| {instrument} | {inference['median_path_annualized_arithmetic_mean']:+.4f} | "
            f"[{inference['annualized_mean_ci95'][0]:+.4f}, "
            f"{inference['annualized_mean_ci95'][1]:+.4f}] | "
            f"{inference['median_path_sharpe']:+.3f} | "
            f"[{inference['sharpe_ci95'][0]:+.3f}, "
            f"{inference['sharpe_ci95'][1]:+.3f}] |"
        )
    lines += [
        "",
        (
            "Both markets show broad positive point estimates across all 24 phase perturbations, "
            "so 00:00 UTC is not a uniquely lucky origin. The robustness contract nevertheless "
            "rejects the benchmark because no phase in either market reaches 7/12 profitable "
            "self-contained OOS folds, and the dependence-aware lower bounds for the "
            "inference-only median phase path cross zero in both markets."
        ),
        "",
        "## +1H latency stress",
        "",
        "| Market | Delayed median net / Sharpe | Positive-return phases | Median turnover |",
        "|---|---:|---:|---:|",
    ]
    for instrument, market in evidence["markets"].items():
        delayed = market["latency_plus_1h_cross_phase"]
        lines.append(
            f"| {instrument} | {delayed['oos_net_return_quantiles']['q50']:+.4%} / "
            f"{delayed['oos_sharpe_quantiles']['q50']:+.3f} | "
            f"{delayed['positive_oos_return_phases']}/24 | "
            f"{delayed['oos_median_turnover']:.0f} |"
        )
    lines += [
        "",
        "Latency transport itself is strong; it does not rescue the failed fold-breadth and dependence gates.",
        "",
        "## Acceptance",
        "",
    ]
    for instrument, gates in evidence["market_acceptance"].items():
        failed = [name for name, passed in gates.items() if not passed]
        lines.append(f"- **{instrument}: REJECT** — failed `{', '.join(failed)}`.")
    lines += [
        "",
        f"Terminal verdict: `{evidence['verdict']}`.",
        "",
        (
            "No phase can be selected, averaged into an executable position, or promoted from "
            "this audit. Canonical main, paper authority and live authority remain unchanged."
        ),
        "",
    ]
    return "\n".join(lines)


def run(btc_artifact: Path, eth_artifact: Path, code_head: str) -> dict[str, object]:
    inputs = {"BTC-USDT": btc_artifact, "ETH-USDT": eth_artifact}
    markets = {}
    source = {}
    for instrument, path in inputs.items():
        frame, source_record = load_artifact(path, instrument)
        source[instrument] = source_record
        markets[instrument] = market_audit(frame, instrument)

    market_acceptance = {
        instrument: acceptance(market) for instrument, market in markets.items()
    }
    bilateral = bool(
        all(all(gates.values()) for gates in market_acceptance.values())
    )
    verdict = (
        "support_canonical_e2160_daily_decision_phase_robustness_1h_v1"
        if bilateral
        else "reject_canonical_e2160_daily_decision_phase_robustness_1h_v1"
    )
    return _jsonable(
        {
            "family_id": FAMILY_ID,
            "issue": ISSUE,
            "code_head": code_head,
            "research_parent": RESEARCH_PARENT,
            "bar": BAR,
            "candidate_count": 0,
            "parameter_grid_count": 0,
            "mandatory_phase_stress_count": 24,
            "fee_bps_one_way": 5.0,
            "position_domain": [0, 1],
            "horizon_hours": HORIZON,
            "decision_cadence_hours": 24,
            "source": source,
            "sample": {
                "warmup": [0, TRAIN[0]],
                "training": list(TRAIN),
                "development_oos": list(OOS),
                "full_scored": list(FULL),
                "parsed_prefix_rows": PREFIX_ROWS,
                "later_suffix_unparsed_and_unscored": True,
            },
            "uncertainty": {
                "method": "non-circular moving-block",
                "draws": BOOTSTRAP_DRAWS,
                "block_hours": BOOTSTRAP_BLOCK,
                "seed": BOOTSTRAP_SEED,
            },
            "markets": markets,
            "market_acceptance": market_acceptance,
            "bilateral_acceptance": bilateral,
            "verdict": verdict,
            "canonical_mutation": False,
            "paper_trading_authorized": False,
            "live_trading_authorized": False,
            "phase_selection_authorized": False,
            "phase_aggregation_authorized": False,
        }
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--btc-artifact", type=Path, required=True)
    parser.add_argument("--eth-artifact", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    parser.add_argument(
        "--code-head",
        default=os.environ.get("RESEARCH_HEAD_SHA", "local-unbound"),
    )
    args = parser.parse_args()
    evidence = run(args.btc_artifact, args.eth_artifact, args.code_head)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = args.output_dir / "evidence.json"
    evidence_bytes = (
        json.dumps(evidence, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode()
    evidence_path.write_bytes(evidence_bytes)
    report = build_report(evidence)
    report_path = args.output_dir / "report.md"
    report_path.write_text(report)
    manifest = {
        "family_id": FAMILY_ID,
        "code_head": args.code_head,
        "evidence_sha256": _sha(evidence_bytes),
        "report_sha256": _sha(report.encode()),
        "source_csv_sha256": {
            instrument: spec["csv_sha256"] for instrument, spec in SOURCES.items()
        },
        "verdict": evidence["verdict"],
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    print(
        json.dumps(
            {
                "verdict": evidence["verdict"],
                "market_acceptance": evidence["market_acceptance"],
                "manifest": manifest,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
