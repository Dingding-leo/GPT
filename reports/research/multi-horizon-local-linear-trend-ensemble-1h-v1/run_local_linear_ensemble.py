from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

FAMILY_ID = "multi-horizon-local-linear-trend-ensemble-1h-v1"
VERDICT_REJECT = "reject_multi_horizon_local_linear_trend_ensemble_architecture_v1"
PROVIDER = "Binance public monthly SPOT archives"
BASE_URL = "https://data.binance.vision/data/spot/monthly/klines"
SYMBOLS = ("XTZUSDT", "ZECUSDT")
START_YEAR = 2023
START_MONTH = 4
END_YEAR = 2025
END_MONTH = 12
EXPECTED_ROWS = 24_144
WARMUP_END = 2_160
TRAIN_START = 2_160
TRAIN_END = 10_800
OOS_START = 10_800
OOS_END = 23_760
FULL_START = TRAIN_START
FULL_END = OOS_END
SOURCE_END = EXPECTED_ROWS
FOLD_HOURS = 2_160
HORIZONS = np.asarray([24.0, 168.0, 720.0], dtype=np.float64)
FEE = 0.0005
ENTRY_HURDLE = 0.001
MIN_HOLD_HOURS = 24
ANNUAL_HOURS = 8_760.0
BOOTSTRAP_DRAWS = 5_000
BOOTSTRAP_BLOCK = 168
BOOTSTRAP_SEED = 20_260_801
EXPECTED_START_MS = 1_680_307_200_000
EXPECTED_END_MS = 1_767_225_200_000
MAX_DOWNLOAD_BYTES = 128 * 1024 * 1024
USER_AGENT = "Dingding-leo-GPT-immutable-1h-research/1.0"


@dataclass(frozen=True)
class MarketData:
    symbol: str
    open_ms: np.ndarray
    opens: np.ndarray
    highs: np.ndarray
    lows: np.ndarray
    closes: np.ndarray
    volumes: np.ndarray
    source: dict[str, Any]


@dataclass(frozen=True)
class PathResult:
    metrics: dict[str, Any]
    positions: np.ndarray
    gross_returns: np.ndarray
    net_returns: np.ndarray
    fee_units: np.ndarray


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    return parser.parse_args()


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def month_sequence() -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    year = START_YEAR
    month = START_MONTH
    while (year, month) <= (END_YEAR, END_MONTH):
        result.append((year, month))
        month += 1
        if month == 13:
            year += 1
            month = 1
    return result


def expected_month_hours(year: int, month: int) -> int:
    if month == 12:
        next_dt = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        next_dt = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    current_dt = datetime(year, month, 1, tzinfo=timezone.utc)
    return int((next_dt - current_dt).total_seconds() // 3_600)


def fetch_bytes(url: str, destination: Path, retries: int = 4) -> bytes:
    if destination.exists():
        payload = destination.read_bytes()
        if payload:
            return payload
    destination.parent.mkdir(parents=True, exist_ok=True)
    last_error: BaseException | None = None
    for attempt in range(retries):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = response.read(MAX_DOWNLOAD_BYTES + 1)
                if len(payload) > MAX_DOWNLOAD_BYTES:
                    raise RuntimeError(f"download exceeded byte limit: {url}")
                if not payload:
                    raise RuntimeError(f"empty download: {url}")
                destination.write_bytes(payload)
                return payload
        except (urllib.error.URLError, TimeoutError, OSError, RuntimeError) as error:
            last_error = error
            if attempt + 1 < retries:
                time.sleep(2**attempt)
    raise RuntimeError(f"failed to download {url}: {last_error}")


def parse_checksum(payload: bytes, expected_filename: str) -> str:
    text = payload.decode("ascii").strip()
    match = re.fullmatch(r"([0-9a-fA-F]{64})\s+\*?(.+)", text)
    if match is None:
        raise RuntimeError(f"invalid checksum payload for {expected_filename}: {text!r}")
    filename = match.group(2).strip()
    if filename != expected_filename:
        raise RuntimeError(f"checksum filename mismatch: {filename!r} != {expected_filename!r}")
    return match.group(1).lower()


def parse_archive(symbol: str, year: int, month: int, payload: bytes) -> tuple[list[list[str]], str]:
    expected_member = f"{symbol}-1h-{year:04d}-{month:02d}.csv"
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        members = [info for info in archive.infolist() if not info.is_dir()]
        if len(members) != 1 or members[0].filename != expected_member:
            raise RuntimeError(
                f"unexpected archive members for {symbol} {year:04d}-{month:02d}: "
                f"{[item.filename for item in members]}"
            )
        raw_csv = archive.read(members[0])
    digest = sha256_bytes(raw_csv)
    rows = list(csv.reader(io.StringIO(raw_csv.decode("utf-8"))))
    expected_rows = expected_month_hours(year, month)
    if len(rows) != expected_rows:
        raise RuntimeError(
            f"row count mismatch for {symbol} {year:04d}-{month:02d}: "
            f"{len(rows)} != {expected_rows}"
        )
    if any(len(row) != 12 for row in rows):
        widths = sorted({len(row) for row in rows})
        raise RuntimeError(f"unexpected CSV widths for {symbol} {year:04d}-{month:02d}: {widths}")
    return rows, digest


def normalize_timestamp(value: str) -> int:
    raw = int(value)
    if raw >= 10**15:
        raw //= 1_000
    if raw < 10**12 or raw >= 10**14:
        raise RuntimeError(f"invalid timestamp magnitude: {value}")
    return raw


def decimal_float(value: str, field: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise RuntimeError(f"non-finite {field}: {value}")
    return parsed


def load_market(symbol: str, cache_dir: Path) -> MarketData:
    rows_all: list[list[str]] = []
    source_objects: list[dict[str, Any]] = []
    for year, month in month_sequence():
        stem = f"{symbol}-1h-{year:04d}-{month:02d}"
        zip_name = f"{stem}.zip"
        checksum_name = f"{zip_name}.CHECKSUM"
        zip_url = f"{BASE_URL}/{symbol}/1h/{zip_name}"
        checksum_url = f"{zip_url}.CHECKSUM"
        checksum_payload = fetch_bytes(checksum_url, cache_dir / symbol / checksum_name)
        zip_payload = fetch_bytes(zip_url, cache_dir / symbol / zip_name)
        expected_sha = parse_checksum(checksum_payload, zip_name)
        observed_sha = sha256_bytes(zip_payload)
        if observed_sha != expected_sha:
            raise RuntimeError(
                f"archive checksum mismatch for {zip_name}: {observed_sha} != {expected_sha}"
            )
        rows, csv_sha = parse_archive(symbol, year, month, zip_payload)
        rows_all.extend(rows)
        source_objects.append(
            {
                "month": f"{year:04d}-{month:02d}",
                "archive_url": zip_url,
                "checksum_url": checksum_url,
                "archive_bytes": len(zip_payload),
                "checksum_bytes": len(checksum_payload),
                "archive_sha256": observed_sha,
                "checksum_sha256": sha256_bytes(checksum_payload),
                "csv_sha256": csv_sha,
                "rows": len(rows),
            }
        )
    if len(rows_all) != EXPECTED_ROWS:
        raise RuntimeError(f"full row count mismatch for {symbol}: {len(rows_all)} != {EXPECTED_ROWS}")

    open_ms = np.empty(EXPECTED_ROWS, dtype=np.int64)
    opens = np.empty(EXPECTED_ROWS, dtype=np.float64)
    highs = np.empty(EXPECTED_ROWS, dtype=np.float64)
    lows = np.empty(EXPECTED_ROWS, dtype=np.float64)
    closes = np.empty(EXPECTED_ROWS, dtype=np.float64)
    volumes = np.empty(EXPECTED_ROWS, dtype=np.float64)
    close_ms = np.empty(EXPECTED_ROWS, dtype=np.int64)

    normalized_rows: list[list[Any]] = []
    for index, row in enumerate(rows_all):
        open_ms[index] = normalize_timestamp(row[0])
        opens[index] = decimal_float(row[1], "open")
        highs[index] = decimal_float(row[2], "high")
        lows[index] = decimal_float(row[3], "low")
        closes[index] = decimal_float(row[4], "close")
        volumes[index] = decimal_float(row[5], "volume")
        close_ms[index] = normalize_timestamp(row[6])
        if min(opens[index], highs[index], lows[index], closes[index]) <= 0:
            raise RuntimeError(f"non-positive OHLC at {symbol} row {index}")
        if volumes[index] < 0:
            raise RuntimeError(f"negative volume at {symbol} row {index}")
        if highs[index] < max(opens[index], closes[index]) or lows[index] > min(
            opens[index], closes[index]
        ):
            raise RuntimeError(f"invalid OHLC ordering at {symbol} row {index}")
        if highs[index] < lows[index]:
            raise RuntimeError(f"high below low at {symbol} row {index}")
        if close_ms[index] < open_ms[index] or close_ms[index] >= open_ms[index] + 3_600_000:
            raise RuntimeError(f"invalid close timestamp at {symbol} row {index}")
        normalized_rows.append(
            [
                int(open_ms[index]),
                float(opens[index]),
                float(highs[index]),
                float(lows[index]),
                float(closes[index]),
                float(volumes[index]),
            ]
        )

    if open_ms[0] != EXPECTED_START_MS or open_ms[-1] != EXPECTED_END_MS:
        raise RuntimeError(
            f"source boundary mismatch for {symbol}: {open_ms[0]}..{open_ms[-1]}"
        )
    differences = np.diff(open_ms)
    if not np.all(differences == 3_600_000):
        bad = np.flatnonzero(differences != 3_600_000)
        raise RuntimeError(f"non-contiguous 1H source for {symbol} at indices {bad[:10].tolist()}")
    if len(np.unique(open_ms)) != EXPECTED_ROWS:
        raise RuntimeError(f"duplicate timestamps for {symbol}")

    normalized_bytes = canonical_json_bytes(normalized_rows)
    source = {
        "provider": PROVIDER,
        "symbol": symbol,
        "bar": "1h",
        "start": datetime.fromtimestamp(open_ms[0] / 1000, tz=timezone.utc).isoformat(),
        "end": datetime.fromtimestamp(open_ms[-1] / 1000, tz=timezone.utc).isoformat(),
        "rows": EXPECTED_ROWS,
        "objects": len(source_objects),
        "object_manifest": source_objects,
        "object_manifest_sha256": sha256_bytes(canonical_json_bytes(source_objects)),
        "normalized_rows_sha256": sha256_bytes(normalized_bytes),
    }
    return MarketData(symbol, open_ms, opens, highs, lows, closes, volumes, source)


def compute_filter_forecasts(closes: np.ndarray) -> np.ndarray:
    if np.any(closes <= 0) or not np.all(np.isfinite(closes)):
        raise RuntimeError("invalid closes")
    observations = np.log(closes)
    count = len(observations)
    forecasts = np.zeros((count, len(HORIZONS)), dtype=np.float64)
    levels = np.full(len(HORIZONS), observations[0], dtype=np.float64)
    slopes = np.zeros(len(HORIZONS), dtype=np.float64)
    lambdas = np.exp(-1.0 / HORIZONS)
    alphas = 1.0 - lambdas**2
    betas = (1.0 - lambdas) ** 2
    for index in range(1, count):
        level_predictions = levels + slopes
        innovations = observations[index] - level_predictions
        levels = level_predictions + alphas * innovations
        slopes = slopes + betas * innovations
        forecasts[index] = 24.0 * slopes
    if not np.all(np.isfinite(forecasts)):
        raise RuntimeError("non-finite filter forecast")
    return forecasts


def daily_anchor_indices(open_ms: np.ndarray) -> np.ndarray:
    hours = (open_ms // 3_600_000) % 24
    anchors = np.flatnonzero(hours == 0).astype(np.int64)
    if len(anchors) == 0:
        raise RuntimeError("no daily anchors")
    return anchors


def label_for_anchor(opens: np.ndarray, anchor: int) -> float:
    return float(math.log(opens[anchor + 25] / opens[anchor + 1]))


def eligible_prediction_anchors(anchors: np.ndarray, start: int, end: int) -> np.ndarray:
    eligible = anchors[(anchors >= start) & ((anchors + 25) < end)]
    if len(eligible) == 0:
        raise RuntimeError(f"no eligible anchors in [{start},{end})")
    return eligible


def fit_weights(forecasts: np.ndarray, opens: np.ndarray, anchors: np.ndarray) -> dict[str, Any]:
    labels = np.asarray([label_for_anchor(opens, int(anchor)) for anchor in anchors], dtype=np.float64)
    expert = forecasts[anchors]
    errors = labels[:, None] - expert
    variances = np.mean(errors**2, axis=0)
    if np.any(variances <= 0) or not np.all(np.isfinite(variances)):
        raise RuntimeError("invalid expert residual variance")
    scores = 0.5 * (np.log(2.0 * math.pi * variances) + np.mean(errors**2, axis=0) / variances)
    raw = np.exp(-scores - np.max(-scores))
    weights = raw / np.sum(raw)
    if np.any(weights <= 0) or not np.all(np.isfinite(weights)) or not math.isclose(
        float(np.sum(weights)), 1.0, rel_tol=0, abs_tol=1e-12
    ):
        raise RuntimeError("invalid weights")
    weighted = expert @ weights
    equal = np.mean(expert, axis=1)
    weighted_variance = float(np.mean((labels - weighted) ** 2))
    equal_variance = float(np.mean((labels - equal) ** 2))
    if min(weighted_variance, equal_variance) <= 0 or not all(
        math.isfinite(x) for x in (weighted_variance, equal_variance)
    ):
        raise RuntimeError("invalid ensemble residual variance")
    return {
        "anchors": anchors,
        "labels": labels,
        "expert_variances": variances,
        "expert_scores": scores,
        "weights": weights,
        "weighted_training_variance": weighted_variance,
        "equal_training_variance": equal_variance,
    }


def correlation(x: np.ndarray, y: np.ndarray) -> float | None:
    if len(x) < 2:
        return None
    x_std = float(np.std(x, ddof=1))
    y_std = float(np.std(y, ddof=1))
    if x_std <= 0 or y_std <= 0:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def forecast_diagnostics(
    forecasts: np.ndarray,
    opens: np.ndarray,
    anchors: np.ndarray,
    weights: np.ndarray,
    expert_variances: np.ndarray,
    weighted_variance: float,
    equal_variance: float,
) -> dict[str, Any]:
    labels = np.asarray([label_for_anchor(opens, int(anchor)) for anchor in anchors], dtype=np.float64)
    expert = forecasts[anchors]
    weighted = expert @ weights
    equal = np.mean(expert, axis=1)

    def summarize(prediction: np.ndarray, variance: float) -> dict[str, Any]:
        residual = labels - prediction
        return {
            "count": int(len(labels)),
            "rmse": float(math.sqrt(float(np.mean(residual**2)))),
            "gaussian_log_score": float(
                0.5 * (math.log(2.0 * math.pi * variance) + float(np.mean(residual**2)) / variance)
            ),
            "sign_accuracy": float(np.mean(np.signbit(prediction) == np.signbit(labels))),
            "forecast_label_correlation": correlation(prediction, labels),
            "prediction_mean": float(np.mean(prediction)),
            "prediction_std": float(np.std(prediction, ddof=1)),
            "label_mean": float(np.mean(labels)),
            "label_std": float(np.std(labels, ddof=1)),
            "fixed_training_variance": float(variance),
        }

    return {
        "weighted": summarize(weighted, weighted_variance),
        "equal_weight": summarize(equal, equal_variance),
        "experts": {
            str(int(horizon)): summarize(expert[:, index], float(expert_variances[index]))
            for index, horizon in enumerate(HORIZONS)
        },
    }


def build_forecast_map(anchors: np.ndarray, values: np.ndarray) -> dict[int, float]:
    return {int(anchor) + 1: float(value) for anchor, value in zip(anchors, values, strict=True)}


def build_target_map(anchors: np.ndarray, values: np.ndarray) -> dict[int, int]:
    return {int(anchor) + 1: int(value) for anchor, value in zip(anchors, values, strict=True)}


def episode_statistics(positions: np.ndarray) -> dict[str, Any]:
    if len(positions) == 0:
        return {
            "entries": 0,
            "exits": 0,
            "long_episodes": 0,
            "cash_episodes": 0,
            "median_long_hours": 0.0,
            "median_cash_hours": 0.0,
            "longest_long_hours": 0,
            "longest_cash_hours": 0,
        }
    entries = int(positions[0] == 1) + int(np.sum((positions[1:] == 1) & (positions[:-1] == 0)))
    exits = int(np.sum((positions[1:] == 0) & (positions[:-1] == 1))) + int(positions[-1] == 1)
    runs: list[tuple[int, int]] = []
    current = int(positions[0])
    length = 1
    for value in positions[1:]:
        integer = int(value)
        if integer == current:
            length += 1
        else:
            runs.append((current, length))
            current = integer
            length = 1
    runs.append((current, length))
    long_runs = [length for state, length in runs if state == 1]
    cash_runs = [length for state, length in runs if state == 0]
    return {
        "entries": entries,
        "exits": exits,
        "long_episodes": len(long_runs),
        "cash_episodes": len(cash_runs),
        "median_long_hours": float(statistics.median(long_runs)) if long_runs else 0.0,
        "median_cash_hours": float(statistics.median(cash_runs)) if cash_runs else 0.0,
        "longest_long_hours": max(long_runs, default=0),
        "longest_cash_hours": max(cash_runs, default=0),
    }


def path_metrics(
    gross_returns: np.ndarray,
    net_returns: np.ndarray,
    positions: np.ndarray,
    fee_units: np.ndarray,
) -> dict[str, Any]:
    if not (
        len(gross_returns) == len(net_returns) == len(positions) == len(fee_units)
        and len(net_returns) > 1
    ):
        raise RuntimeError("invalid path arrays")
    gross_equity = np.cumprod(1.0 + gross_returns)
    net_equity = np.cumprod(1.0 + net_returns)
    running_peak = np.maximum.accumulate(np.concatenate(([1.0], net_equity)))
    equity_with_initial = np.concatenate(([1.0], net_equity))
    drawdown = equity_with_initial / running_peak - 1.0
    std = float(np.std(net_returns, ddof=1))
    annualised_mean = float(np.mean(net_returns) * ANNUAL_HOURS)
    sharpe = float(np.mean(net_returns) / std * math.sqrt(ANNUAL_HOURS)) if std > 0 else 0.0
    turnover = float(np.sum(fee_units))
    net_total = float(net_equity[-1] - 1.0)
    gross_total = float(gross_equity[-1] - 1.0)
    fee_drag = gross_total - net_total
    return {
        "hours": len(net_returns),
        "gross_total_return": gross_total,
        "net_total_return": net_total,
        "annualised_arithmetic_mean": annualised_mean,
        "annualised_sharpe": sharpe,
        "maximum_drawdown": float(np.min(drawdown)),
        "exposure_fraction": float(np.mean(positions)),
        "one_way_turnover": turnover,
        "transition_count": int(np.count_nonzero(fee_units)),
        "fee_drag": float(fee_drag),
        "edge_per_turnover": float(net_total / turnover) if turnover > 0 else 0.0,
        **episode_statistics(positions),
    }


def metrics_from_path(
    opens: np.ndarray,
    start: int,
    end: int,
    positions: np.ndarray,
    fee_units: np.ndarray,
    terminal_liquidation: bool = True,
) -> PathResult:
    if len(positions) != end - start or len(fee_units) != end - start:
        raise RuntimeError("path length mismatch")
    if np.any((positions != 0) & (positions != 1)):
        raise RuntimeError("invalid position")
    fee_units = fee_units.astype(np.float64, copy=True)
    if terminal_liquidation and positions[-1] == 1:
        fee_units[-1] += 1.0
    open_returns = opens[start + 1 : end + 1] / opens[start:end] - 1.0
    gross_factors = 1.0 + positions * open_returns
    fee_factors = 1.0 - FEE * fee_units
    if np.any(fee_factors <= 0):
        raise RuntimeError("invalid fee factor")
    net_factors = gross_factors * fee_factors
    gross_returns = gross_factors - 1.0
    net_returns = net_factors - 1.0
    return PathResult(
        path_metrics(gross_returns, net_returns, positions, fee_units),
        positions,
        gross_returns,
        net_returns,
        fee_units,
    )


def simulate_forecast_rule(
    opens: np.ndarray,
    start: int,
    end: int,
    forecast_by_execution: dict[int, float],
) -> PathResult:
    positions = np.zeros(end - start, dtype=np.int8)
    fees = np.zeros(end - start, dtype=np.float64)
    position = 0
    held = 0
    for execution in range(start, end):
        if execution in forecast_by_execution:
            forecast = forecast_by_execution[execution]
            target = position
            if position == 0 and forecast > ENTRY_HURDLE:
                target = 1
            elif position == 1 and forecast < 0.0 and held >= MIN_HOLD_HOURS:
                target = 0
            if target != position:
                fees[execution - start] = abs(target - position)
                position = target
                held = 0
        positions[execution - start] = position
        held = held + 1 if position == 1 else 0
    return metrics_from_path(opens, start, end, positions, fees)


def simulate_target_rule(
    opens: np.ndarray,
    start: int,
    end: int,
    target_by_execution: dict[int, int],
) -> PathResult:
    positions = np.zeros(end - start, dtype=np.int8)
    fees = np.zeros(end - start, dtype=np.float64)
    position = 0
    for execution in range(start, end):
        if execution in target_by_execution:
            target = int(target_by_execution[execution])
            if target not in (0, 1):
                raise RuntimeError("invalid target")
            if target != position:
                fees[execution - start] = abs(target - position)
                position = target
        positions[execution - start] = position
    return metrics_from_path(opens, start, end, positions, fees)


def simulate_buy_hold(opens: np.ndarray, start: int, end: int) -> PathResult:
    positions = np.ones(end - start, dtype=np.int8)
    fees = np.zeros(end - start, dtype=np.float64)
    fees[0] = 1.0
    return metrics_from_path(opens, start, end, positions, fees)


def simulate_cash(opens: np.ndarray, start: int, end: int) -> PathResult:
    positions = np.zeros(end - start, dtype=np.int8)
    fees = np.zeros(end - start, dtype=np.float64)
    return metrics_from_path(opens, start, end, positions, fees, terminal_liquidation=False)


def simulate_delayed(opens: np.ndarray, start: int, end: int, original: PathResult) -> PathResult:
    schedule: dict[int, int] = {}
    previous = 0
    for offset, value in enumerate(original.positions):
        current = int(value)
        if current != previous:
            delayed_execution = start + offset + 1
            if delayed_execution < end:
                schedule[delayed_execution] = current
            previous = current
    return simulate_target_rule(opens, start, end, schedule)


def path_bundle(
    data: MarketData,
    start: int,
    end: int,
    weighted_map: dict[int, float],
    equal_map: dict[int, float],
    trend_map: dict[int, int],
) -> dict[str, PathResult]:
    return {
        "cash": simulate_cash(data.opens, start, end),
        "buy_hold": simulate_buy_hold(data.opens, start, end),
        "trend": simulate_target_rule(data.opens, start, end, trend_map),
        "equal_weight": simulate_forecast_rule(data.opens, start, end, equal_map),
        "candidate": simulate_forecast_rule(data.opens, start, end, weighted_map),
    }


def annualised_sharpe(values: np.ndarray) -> float:
    std = float(np.std(values, ddof=1))
    if std <= 0:
        return 0.0
    return float(np.mean(values) / std * math.sqrt(ANNUAL_HOURS))


def bootstrap_differences(candidate: np.ndarray, trend: np.ndarray, equal: np.ndarray) -> dict[str, Any]:
    if not (len(candidate) == len(trend) == len(equal)):
        raise RuntimeError("bootstrap paths are not aligned")
    n = len(candidate)
    blocks = math.ceil(n / BOOTSTRAP_BLOCK)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    mean_vs_trend = np.empty(BOOTSTRAP_DRAWS, dtype=np.float64)
    sharpe_vs_trend = np.empty(BOOTSTRAP_DRAWS, dtype=np.float64)
    mean_vs_equal = np.empty(BOOTSTRAP_DRAWS, dtype=np.float64)
    sharpe_vs_equal = np.empty(BOOTSTRAP_DRAWS, dtype=np.float64)
    offsets = np.arange(BOOTSTRAP_BLOCK, dtype=np.int64)
    for draw in range(BOOTSTRAP_DRAWS):
        starts = rng.integers(0, n - BOOTSTRAP_BLOCK + 1, size=blocks)
        indices = (starts[:, None] + offsets[None, :]).reshape(-1)[:n]
        c = candidate[indices]
        t = trend[indices]
        e = equal[indices]
        mean_vs_trend[draw] = float(np.mean(c - t))
        mean_vs_equal[draw] = float(np.mean(c - e))
        sharpe_vs_trend[draw] = annualised_sharpe(c) - annualised_sharpe(t)
        sharpe_vs_equal[draw] = annualised_sharpe(c) - annualised_sharpe(e)

    def interval(values: np.ndarray) -> list[float]:
        return [float(item) for item in np.percentile(values, [2.5, 97.5])]

    return {
        "draws": BOOTSTRAP_DRAWS,
        "block_hours": BOOTSTRAP_BLOCK,
        "seed": BOOTSTRAP_SEED,
        "candidate_minus_trend": {
            "mean_hourly_net_return": float(np.mean(candidate - trend)),
            "mean_hourly_net_return_bps": float(np.mean(candidate - trend) * 10_000.0),
            "mean_ci": interval(mean_vs_trend),
            "mean_ci_bps": [value * 10_000.0 for value in interval(mean_vs_trend)],
            "sharpe_difference": annualised_sharpe(candidate) - annualised_sharpe(trend),
            "sharpe_ci": interval(sharpe_vs_trend),
        },
        "candidate_minus_equal_weight": {
            "mean_hourly_net_return": float(np.mean(candidate - equal)),
            "mean_hourly_net_return_bps": float(np.mean(candidate - equal) * 10_000.0),
            "mean_ci": interval(mean_vs_equal),
            "mean_ci_bps": [value * 10_000.0 for value in interval(mean_vs_equal)],
            "sharpe_difference": annualised_sharpe(candidate) - annualised_sharpe(equal),
            "sharpe_ci": interval(sharpe_vs_equal),
        },
    }


def metric_dict(bundle: dict[str, PathResult]) -> dict[str, dict[str, Any]]:
    return {name: result.metrics for name, result in bundle.items()}


def fold_and_year_breadth(data: MarketData, weighted_map: dict[int, float]) -> dict[str, Any]:
    folds: list[dict[str, Any]] = []
    for fold_index in range(6):
        start = OOS_START + fold_index * FOLD_HOURS
        end = start + FOLD_HOURS
        result = simulate_forecast_rule(data.opens, start, end, weighted_map)
        folds.append({"fold": fold_index + 1, **result.metrics})
    positive_values = [max(0.0, fold["net_total_return"]) for fold in folds]
    positive_sum = sum(positive_values)
    positive_fold_concentration = max(positive_values, default=0.0) / positive_sum if positive_sum > 0 else 1.0

    years: list[dict[str, Any]] = []
    year_values = np.asarray(
        [datetime.fromtimestamp(value / 1000, tz=timezone.utc).year for value in data.open_ms[OOS_START:OOS_END]],
        dtype=np.int64,
    )
    for year in sorted(set(int(value) for value in year_values)):
        local = np.flatnonzero(year_values == year)
        start = OOS_START + int(local[0])
        end = OOS_START + int(local[-1]) + 1
        result = simulate_forecast_rule(data.opens, start, end, weighted_map)
        years.append({"year": year, **result.metrics})
    return {
        "folds": folds,
        "positive_folds": sum(fold["net_total_return"] > 0 for fold in folds),
        "positive_fold_concentration": float(positive_fold_concentration),
        "years": years,
        "positive_years": sum(year["net_total_return"] > 0 for year in years),
        "year_count": len(years),
    }


def evaluate_market(data: MarketData) -> dict[str, Any]:
    forecasts = compute_filter_forecasts(data.closes)
    anchors = daily_anchor_indices(data.open_ms)
    training_anchors = eligible_prediction_anchors(anchors, TRAIN_START, TRAIN_END)
    oos_prediction_anchors = eligible_prediction_anchors(anchors, OOS_START, OOS_END)
    fit = fit_weights(forecasts, data.opens, training_anchors)
    weights = fit["weights"]
    weighted_forecast = forecasts @ weights
    equal_forecast = np.mean(forecasts, axis=1)
    all_action_anchors = anchors[(anchors >= TRAIN_START) & ((anchors + 1) < FULL_END)]
    weighted_map = build_forecast_map(all_action_anchors, weighted_forecast[all_action_anchors])
    equal_map = build_forecast_map(all_action_anchors, equal_forecast[all_action_anchors])
    trend_anchors = anchors[(anchors >= 2_160) & ((anchors + 1) < FULL_END)]
    trend_values = data.closes[trend_anchors] > data.closes[trend_anchors - 2_160]
    trend_map = build_target_map(trend_anchors, trend_values.astype(np.int8))

    segments = {
        "train": path_bundle(data, TRAIN_START, TRAIN_END, weighted_map, equal_map, trend_map),
        "oos": path_bundle(data, OOS_START, OOS_END, weighted_map, equal_map, trend_map),
        "full": path_bundle(data, FULL_START, FULL_END, weighted_map, equal_map, trend_map),
    }
    breadth = fold_and_year_breadth(data, weighted_map)
    oos_candidate = segments["oos"]["candidate"]
    oos_trend = segments["oos"]["trend"]
    oos_equal = segments["oos"]["equal_weight"]
    bootstrap = bootstrap_differences(
        oos_candidate.net_returns, oos_trend.net_returns, oos_equal.net_returns
    )
    delayed = simulate_delayed(data.opens, OOS_START, OOS_END, oos_candidate)

    training_diagnostics = forecast_diagnostics(
        forecasts,
        data.opens,
        training_anchors,
        weights,
        fit["expert_variances"],
        fit["weighted_training_variance"],
        fit["equal_training_variance"],
    )
    oos_diagnostics = forecast_diagnostics(
        forecasts,
        data.opens,
        oos_prediction_anchors,
        weights,
        fit["expert_variances"],
        fit["weighted_training_variance"],
        fit["equal_training_variance"],
    )

    prefix_forecasts = compute_filter_forecasts(data.closes[:FULL_END])
    suffix_invariant = np.array_equal(prefix_forecasts, forecasts[:FULL_END])
    replay_forecasts = compute_filter_forecasts(data.closes)
    deterministic_replay = np.array_equal(replay_forecasts, forecasts)
    anchor_set = {int(item) for item in anchors}
    daily_only = all((execution - 1) in anchor_set for execution in weighted_map)
    next_open_timing = all(int(anchor) + 1 in weighted_map for anchor in all_action_anchors)
    training_excludes_oos = bool(np.max(training_anchors + 25) < TRAIN_END)
    source_integrity = (
        data.source["rows"] == SOURCE_END
        and data.open_ms[0] == EXPECTED_START_MS
        and data.open_ms[-1] == EXPECTED_END_MS
        and np.all(np.diff(data.open_ms) == 3_600_000)
    )
    integrity = bool(
        source_integrity
        and suffix_invariant
        and deterministic_replay
        and daily_only
        and next_open_timing
        and training_excludes_oos
    )

    candidate_metrics = segments["oos"]["candidate"].metrics
    trend_metrics = segments["oos"]["trend"].metrics
    equal_metrics = segments["oos"]["equal_weight"].metrics
    mean_ci = bootstrap["candidate_minus_trend"]["mean_ci"]
    sharpe_ci = bootstrap["candidate_minus_trend"]["sharpe_ci"]
    gates = {
        "oos_positive": candidate_metrics["net_total_return"] > 0,
        "return_above_trend_and_equal": candidate_metrics["net_total_return"]
        > max(trend_metrics["net_total_return"], equal_metrics["net_total_return"]),
        "sharpe_above_trend_and_equal": candidate_metrics["annualised_sharpe"]
        > max(trend_metrics["annualised_sharpe"], equal_metrics["annualised_sharpe"]),
        "drawdown_better_than_trend": candidate_metrics["maximum_drawdown"]
        > trend_metrics["maximum_drawdown"],
        "edge_per_turnover": candidate_metrics["edge_per_turnover"] > 0
        and candidate_metrics["edge_per_turnover"] > trend_metrics["edge_per_turnover"],
        "breadth": breadth["positive_folds"] >= 4 and breadth["positive_years"] >= 2,
        "positive_fold_concentration": breadth["positive_fold_concentration"] <= 0.50,
        "bootstrap_lower_bounds": mean_ci[0] > 0 and sharpe_ci[0] > 0,
        "turnover_bounded": candidate_metrics["one_way_turnover"]
        <= 2.0 * trend_metrics["one_way_turnover"]
        and candidate_metrics["one_way_turnover"] <= (OOS_END - OOS_START) / 48.0,
        "delay_positive": delayed.metrics["net_total_return"] > 0,
        "full_positive": segments["full"]["candidate"].metrics["net_total_return"] > 0,
        "proper_score_weighting": oos_diagnostics["weighted"]["gaussian_log_score"]
        < oos_diagnostics["equal_weight"]["gaussian_log_score"],
        "integrity": integrity,
    }
    accepted = all(gates.values())

    timing = oos_candidate.gross_returns - oos_trend.gross_returns
    fee_component = (oos_candidate.net_returns - oos_candidate.gross_returns) - (
        oos_trend.net_returns - oos_trend.gross_returns
    )
    decomposition = {
        "candidate_minus_trend_compounded_net_return": candidate_metrics["net_total_return"]
        - trend_metrics["net_total_return"],
        "mean_hourly_gross_timing_difference": float(np.mean(timing)),
        "mean_hourly_fee_difference": float(np.mean(fee_component)),
        "candidate_fee_units": candidate_metrics["one_way_turnover"],
        "trend_fee_units": trend_metrics["one_way_turnover"],
    }

    return {
        "source": data.source,
        "weights": [float(item) for item in weights],
        "weight_fit": {
            "training_anchor_count": int(len(training_anchors)),
            "expert_variances": [float(item) for item in fit["expert_variances"]],
            "expert_scores": [float(item) for item in fit["expert_scores"]],
            "weights": [float(item) for item in weights],
            "weighted_training_variance": fit["weighted_training_variance"],
            "equal_training_variance": fit["equal_training_variance"],
        },
        "forecast_diagnostics": {"train": training_diagnostics, "oos": oos_diagnostics},
        "segments": {name: metric_dict(bundle) for name, bundle in segments.items()},
        "oos_breadth": breadth,
        "bootstrap": bootstrap,
        "delay_stress_oos": delayed.metrics,
        "timing_fee_decomposition": decomposition,
        "integrity": {
            "source": bool(source_integrity),
            "suffix_invariance": bool(suffix_invariant),
            "deterministic_replay": bool(deterministic_replay),
            "daily_only_decisions": bool(daily_only),
            "next_open_execution": bool(next_open_timing),
            "training_label_exclusion": bool(training_excludes_oos),
            "all": integrity,
        },
        "gates": gates,
        "gates_passed": sum(bool(value) for value in gates.values()),
        "gates_total": len(gates),
        "accepted": accepted,
    }


def failure_mechanism(markets: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for symbol, market in markets.items():
        candidate = market["segments"]["oos"]["candidate"]
        trend = market["segments"]["oos"]["trend"]
        equal = market["segments"]["oos"]["equal_weight"]
        failed = [name for name, passed in market["gates"].items() if not passed]
        result[symbol] = {
            "failed_gates": failed,
            "candidate_net_minus_trend": candidate["net_total_return"] - trend["net_total_return"],
            "candidate_net_minus_equal": candidate["net_total_return"] - equal["net_total_return"],
            "candidate_sharpe_minus_trend": candidate["annualised_sharpe"] - trend["annualised_sharpe"],
            "candidate_sharpe_minus_equal": candidate["annualised_sharpe"] - equal["annualised_sharpe"],
            "forecast_score_improvement": market["forecast_diagnostics"]["oos"]["equal_weight"][
                "gaussian_log_score"
            ]
            - market["forecast_diagnostics"]["oos"]["weighted"]["gaussian_log_score"],
            "weight_dispersion": float(max(market["weights"]) - min(market["weights"])),
        }
    return result


def render_report(evidence: dict[str, Any]) -> str:
    lines = [
        "# Multi-horizon local-linear trend ensemble 1H evidence",
        "",
        "```text",
        f"family          {evidence['family_id']}",
        f"candidate count {evidence['candidate_count']}",
        f"parameter grid  {evidence['parameter_grid_count']}",
        f"fee one way     {evidence['fee_one_way']:.4f}",
        f"accepted        {evidence['accepted']}",
        f"verdict         {evidence['verdict']}",
        "```",
        "",
        "## Data and sample",
        "",
        "Immutable public Binance SPOT 1H archives from 2023-04-01 through 2025-12-31; 24,144 exact contiguous rows per market.",
        "",
        "## Strategy metrics",
        "",
        "| Market | Segment | Candidate net | Sharpe | Max DD | Turnover | Trend net | Equal net |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for symbol in SYMBOLS:
        result = evidence["markets"][symbol]
        for segment in ("train", "oos", "full"):
            metrics = result["segments"][segment]
            candidate = metrics["candidate"]
            lines.append(
                f"| {symbol} | {segment} | {candidate['net_total_return']:+.4%} | "
                f"{candidate['annualised_sharpe']:+.4f} | {candidate['maximum_drawdown']:+.4%} | "
                f"{candidate['one_way_turnover']:.0f} | {metrics['trend']['net_total_return']:+.4%} | "
                f"{metrics['equal_weight']['net_total_return']:+.4%} |"
            )
    lines.extend(["", "## Frozen weights and forecast evidence", ""])
    for symbol in SYMBOLS:
        result = evidence["markets"][symbol]
        weights = result["weight_fit"]["weights"]
        oos_diag = result["forecast_diagnostics"]["oos"]
        lines.extend(
            [
                f"### {symbol}",
                "",
                f"- weights 24H/168H/720H: `{weights[0]:.6f}`, `{weights[1]:.6f}`, `{weights[2]:.6f}`",
                f"- weighted OOS RMSE/log score: `{oos_diag['weighted']['rmse']:.6f}` / `{oos_diag['weighted']['gaussian_log_score']:.6f}`",
                f"- equal OOS RMSE/log score: `{oos_diag['equal_weight']['rmse']:.6f}` / `{oos_diag['equal_weight']['gaussian_log_score']:.6f}`",
                f"- candidate-minus-trend mean CI, bps/hour: `{result['bootstrap']['candidate_minus_trend']['mean_ci_bps']}`",
                f"- candidate-minus-trend Sharpe CI: `{result['bootstrap']['candidate_minus_trend']['sharpe_ci']}`",
                f"- delayed OOS net: `{result['delay_stress_oos']['net_total_return']:+.4%}`",
                f"- failed gates: `{', '.join(evidence['failure_mechanism'][symbol]['failed_gates']) or 'none'}`",
                "",
            ]
        )
    lines.extend(
        [
            "## Disposition",
            "",
            f"Verdict: `{evidence['verdict']}`.",
            "",
            "No cross-sectional selection, pairs/spreads, shorting, leverage, synthetic data, private endpoint, account, order, enabled adapter, or 15m input was used.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    markets: dict[str, Any] = {}
    for symbol in SYMBOLS:
        data = load_market(symbol, args.cache_dir)
        markets[symbol] = evaluate_market(data)
    accepted_markets = sum(bool(result["accepted"]) for result in markets.values())
    accepted = accepted_markets == len(SYMBOLS)
    source_manifest = {symbol: markets[symbol]["source"] for symbol in SYMBOLS}
    evidence: dict[str, Any] = {
        "schema_version": 1,
        "family_id": FAMILY_ID,
        "classification": "one-candidate executable temporal-ensemble experiment",
        "provider": PROVIDER,
        "bar": "1h",
        "candidate_count": 1,
        "parameter_grid_count": 0,
        "fee_one_way": FEE,
        "markets_accepted": accepted_markets,
        "accepted": accepted,
        "verdict": (
            "accept_multi_horizon_local_linear_trend_ensemble_architecture_v1"
            if accepted
            else VERDICT_REJECT
        ),
        "boundaries": {
            "warmup": [0, WARMUP_END],
            "training": [TRAIN_START, TRAIN_END],
            "oos": [OOS_START, OOS_END],
            "full": [FULL_START, FULL_END],
            "unscored_suffix": [FULL_END, SOURCE_END],
        },
        "bootstrap": {
            "draws": BOOTSTRAP_DRAWS,
            "block_hours": BOOTSTRAP_BLOCK,
            "seed": BOOTSTRAP_SEED,
        },
        "source_manifest_sha256": sha256_bytes(canonical_json_bytes(source_manifest)),
        "markets": markets,
        "failure_mechanism": failure_mechanism(markets),
        "canonical_strategy_changed": False,
        "paper_live_authority": False,
    }
    evidence_bytes = json.dumps(evidence, indent=2, sort_keys=True, allow_nan=False).encode("utf-8") + b"\n"
    evidence_path = args.output_dir / "evidence.json"
    evidence_path.write_bytes(evidence_bytes)
    evidence_digest = sha256_bytes(evidence_bytes)
    (args.output_dir / "evidence.sha256").write_text(
        f"{evidence_digest}  evidence.json\n", encoding="ascii"
    )
    report = render_report(evidence)
    (args.output_dir / "report.md").write_text(report, encoding="utf-8")
    summary = {
        "family_id": FAMILY_ID,
        "accepted": accepted,
        "markets_accepted": accepted_markets,
        "candidate_count": 1,
        "parameter_grid_count": 0,
        "verdict": evidence["verdict"],
        "evidence_sha256": evidence_digest,
    }
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
