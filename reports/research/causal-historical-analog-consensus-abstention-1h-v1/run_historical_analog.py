# ruff: noqa: E501
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
import statistics
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

FAMILY_ID = "causal-historical-analog-consensus-abstention-1h-v1"
ACCEPT = "accept_causal_historical_analog_consensus_abstention_1h_v1"
REJECT = "reject_causal_historical_analog_consensus_abstention_1h_v1"
PROVIDER = "Binance public monthly SPOT archives"
BASE_URL = "https://data.binance.vision/data/spot/monthly/klines"
SYMBOLS = ("ALGOUSDT", "ATOMUSDT")
START_YEAR, START_MONTH = 2023, 4
END_YEAR, END_MONTH = 2025, 12
EXPECTED_ROWS = 24_144
TRAIN_START, TRAIN_END = 2_160, 10_800
OOS_START, OOS_END = 10_800, 23_760
FULL_START, FULL_END = TRAIN_START, OOS_END
FEATURE_WINDOW = 168
BLOCK_HOURS = 6
FEATURE_COUNT = 28
NEIGHBOURS = 12
SEPARATION_HOURS = 168
LABEL_HOURS = 24
ENTER_MEDIAN = 0.001
ENTER_COUNT = 9
EXIT_MEDIAN = 0.0
EXIT_COUNT = 5
FEE = 0.0005
ANNUAL_HOURS = 8_760.0
FOLD_HOURS = 2_160
BOOTSTRAP_DRAWS = 5_000
BOOTSTRAP_BLOCK = 168
BOOTSTRAP_SEED = 20_260_801
EXPECTED_START_MS = 1_680_307_200_000
EXPECTED_END_MS = 1_767_222_000_000
MAX_DOWNLOAD_BYTES = 128 * 1024 * 1024
USER_AGENT = "Dingding-leo-GPT-immutable-historical-analog-1h-research/1.0"


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
class Forecast:
    cutoff: int
    action: int
    median_gross: float | None
    fee_clear_count: int | None
    selected_cutoffs: tuple[int, ...]
    selected_distances: tuple[float, ...]
    selected_returns: tuple[float, ...]


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


def array_sha256(value: np.ndarray) -> str:
    array = np.asarray(value, dtype="<f8", order="C")
    return sha256_bytes(array.tobytes(order="C"))


def month_sequence() -> list[tuple[int, int]]:
    months: list[tuple[int, int]] = []
    year, month = START_YEAR, START_MONTH
    while (year, month) <= (END_YEAR, END_MONTH):
        months.append((year, month))
        month += 1
        if month == 13:
            year += 1
            month = 1
    return months


def expected_month_hours(year: int, month: int) -> int:
    current = datetime(year, month, 1, tzinfo=UTC)
    following = (
        datetime(year + 1, 1, 1, tzinfo=UTC)
        if month == 12
        else datetime(year, month + 1, 1, tzinfo=UTC)
    )
    return int((following - current).total_seconds() // 3_600)


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
            if not payload or len(payload) > MAX_DOWNLOAD_BYTES:
                raise RuntimeError(f"invalid download size for {url}: {len(payload)}")
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
    if match is None or match.group(2).strip() != expected_filename:
        raise RuntimeError(f"invalid checksum payload for {expected_filename}: {text!r}")
    return match.group(1).lower()


def normalize_timestamp(value: str) -> int:
    raw = int(value)
    if raw >= 10**15:
        raw //= 1_000
    if raw < 10**12 or raw >= 10**14:
        raise RuntimeError(f"invalid timestamp magnitude: {value}")
    return raw


def load_market(symbol: str, cache_dir: Path) -> MarketData:
    rows_all: list[list[str]] = []
    objects: list[dict[str, Any]] = []
    timestamp_units: set[str] = set()
    for year, month in month_sequence():
        stem = f"{symbol}-1h-{year:04d}-{month:02d}"
        zip_name = f"{stem}.zip"
        zip_url = f"{BASE_URL}/{symbol}/1h/{zip_name}"
        checksum_url = f"{zip_url}.CHECKSUM"
        checksum_payload = fetch_bytes(checksum_url, cache_dir / symbol / f"{zip_name}.CHECKSUM")
        archive_payload = fetch_bytes(zip_url, cache_dir / symbol / zip_name)
        expected_sha = parse_checksum(checksum_payload, zip_name)
        archive_sha = sha256_bytes(archive_payload)
        if archive_sha != expected_sha:
            raise RuntimeError(
                f"archive checksum mismatch for {zip_name}: {archive_sha} != {expected_sha}"
            )
        expected_member = f"{stem}.csv"
        with zipfile.ZipFile(io.BytesIO(archive_payload)) as archive:
            members = [member for member in archive.infolist() if not member.is_dir()]
            if len(members) != 1 or members[0].filename != expected_member:
                raise RuntimeError(
                    f"unexpected archive members for {zip_name}: {[member.filename for member in members]}"
                )
            csv_payload = archive.read(members[0])
        rows = list(csv.reader(io.StringIO(csv_payload.decode("utf-8"))))
        if len(rows) != expected_month_hours(year, month) or any(len(row) != 12 for row in rows):
            raise RuntimeError(f"row/schema mismatch for {zip_name}: {len(rows)} rows")
        timestamp_units.add("microseconds" if int(rows[0][0]) >= 10**15 else "milliseconds")
        rows_all.extend(rows)
        objects.append(
            {
                "month": f"{year:04d}-{month:02d}",
                "archive_url": zip_url,
                "checksum_url": checksum_url,
                "archive_bytes": len(archive_payload),
                "archive_sha256": archive_sha,
                "checksum_sha256": sha256_bytes(checksum_payload),
                "csv_sha256": sha256_bytes(csv_payload),
                "rows": len(rows),
            }
        )
    if len(rows_all) != EXPECTED_ROWS:
        raise RuntimeError(
            f"full row count mismatch for {symbol}: {len(rows_all)} != {EXPECTED_ROWS}"
        )

    open_ms = np.empty(EXPECTED_ROWS, dtype=np.int64)
    close_ms = np.empty(EXPECTED_ROWS, dtype=np.int64)
    opens = np.empty(EXPECTED_ROWS, dtype=np.float64)
    highs = np.empty(EXPECTED_ROWS, dtype=np.float64)
    lows = np.empty(EXPECTED_ROWS, dtype=np.float64)
    closes = np.empty(EXPECTED_ROWS, dtype=np.float64)
    volumes = np.empty(EXPECTED_ROWS, dtype=np.float64)
    normalized: list[list[Any]] = []
    for index, row in enumerate(rows_all):
        open_ms[index] = normalize_timestamp(row[0])
        close_ms[index] = normalize_timestamp(row[6])
        values = [float(row[column]) for column in range(1, 6)]
        if not all(math.isfinite(value) for value in values):
            raise RuntimeError(f"non-finite market value at {symbol} row {index}")
        opens[index], highs[index], lows[index], closes[index], volumes[index] = values
        if min(opens[index], highs[index], lows[index], closes[index]) <= 0 or volumes[index] < 0:
            raise RuntimeError(f"invalid price/volume at {symbol} row {index}")
        if (
            highs[index] < max(opens[index], closes[index])
            or lows[index] > min(opens[index], closes[index])
            or highs[index] < lows[index]
        ):
            raise RuntimeError(f"invalid OHLC ordering at {symbol} row {index}")
        if close_ms[index] < open_ms[index] or close_ms[index] >= open_ms[index] + 3_600_000:
            raise RuntimeError(f"invalid close timestamp at {symbol} row {index}")
        normalized.append([int(open_ms[index]), *[float(value) for value in values]])
    if open_ms[0] != EXPECTED_START_MS or open_ms[-1] != EXPECTED_END_MS:
        raise RuntimeError(f"source boundary mismatch for {symbol}: {open_ms[0]}..{open_ms[-1]}")
    if not np.all(np.diff(open_ms) == 3_600_000) or len(np.unique(open_ms)) != EXPECTED_ROWS:
        raise RuntimeError(f"non-contiguous or duplicate 1H source for {symbol}")
    source = {
        "provider": PROVIDER,
        "symbol": symbol,
        "bar": "1h",
        "start": datetime.fromtimestamp(open_ms[0] / 1000, tz=UTC).isoformat(),
        "end": datetime.fromtimestamp(open_ms[-1] / 1000, tz=UTC).isoformat(),
        "rows": EXPECTED_ROWS,
        "objects": len(objects),
        "timestamp_units_observed": sorted(timestamp_units),
        "object_manifest": objects,
        "object_manifest_sha256": sha256_bytes(canonical_json_bytes(objects)),
        "normalized_rows_sha256": sha256_bytes(canonical_json_bytes(normalized)),
    }
    return MarketData(symbol, open_ms, opens, highs, lows, closes, volumes, source)


def daily_indices(data: MarketData, start: int, end: int) -> np.ndarray:
    indices = np.arange(start, end, dtype=np.int64)
    return indices[((data.open_ms[indices] // 3_600_000) % 24) == 0]


def feature_at(closes: np.ndarray, cutoff: int) -> np.ndarray:
    if cutoff < FEATURE_WINDOW + 1 or cutoff > len(closes):
        raise RuntimeError(f"invalid feature cutoff {cutoff}")
    hourly = np.diff(np.log(closes[cutoff - FEATURE_WINDOW - 1 : cutoff]))
    if len(hourly) != FEATURE_WINDOW or not np.all(np.isfinite(hourly)):
        raise RuntimeError("invalid 168H return vector")
    blocks = hourly.reshape(FEATURE_COUNT, BLOCK_HOURS).sum(axis=1)
    rms = max(float(math.sqrt(float(np.mean(blocks * blocks)))), 1e-12)
    result = blocks / rms
    if result.shape != (FEATURE_COUNT,) or not np.all(np.isfinite(result)):
        raise RuntimeError("invalid 28-block normalized feature")
    return result


def all_feature_cutoffs(data: MarketData, label_end: int) -> np.ndarray:
    cutoffs = daily_indices(data, 0, label_end)
    return cutoffs[(cutoffs >= FEATURE_WINDOW + 1) & (cutoffs + LABEL_HOURS <= label_end)]


def build_feature_library(
    data: MarketData, label_end: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    cutoffs = all_feature_cutoffs(data, label_end)
    features = np.vstack([feature_at(data.closes, int(cutoff)) for cutoff in cutoffs])
    forward = np.log(data.opens[cutoffs + LABEL_HOURS] / data.opens[cutoffs])
    if features.shape != (len(cutoffs), FEATURE_COUNT) or not np.all(np.isfinite(forward)):
        raise RuntimeError("invalid feature library")
    return cutoffs, features, forward


def select_analogs(
    query_cutoff: int,
    query_feature: np.ndarray,
    library_cutoffs: np.ndarray,
    library_features: np.ndarray,
    library_returns: np.ndarray,
) -> Forecast:
    eligible = np.flatnonzero(
        (library_cutoffs < query_cutoff) & (library_cutoffs + LABEL_HOURS <= query_cutoff)
    )
    if len(eligible) == 0:
        return Forecast(query_cutoff, -2, None, None, (), (), ())
    delta = library_features[eligible] - query_feature
    distances = np.sum(delta * delta, axis=1)
    order = np.lexsort((library_cutoffs[eligible], distances))
    selected: list[int] = []
    for position in order:
        candidate = int(eligible[int(position)])
        cutoff = int(library_cutoffs[candidate])
        if all(abs(cutoff - int(library_cutoffs[prior])) >= SEPARATION_HOURS for prior in selected):
            selected.append(candidate)
            if len(selected) == NEIGHBOURS:
                break
    if len(selected) < NEIGHBOURS:
        return Forecast(
            query_cutoff,
            -2,
            None,
            None,
            tuple(int(library_cutoffs[i]) for i in selected),
            tuple(float(np.sum((library_features[i] - query_feature) ** 2)) for i in selected),
            tuple(float(library_returns[i]) for i in selected),
        )
    returns = np.asarray([library_returns[i] for i in selected], dtype=np.float64)
    selected_distances = tuple(
        float(np.sum((library_features[i] - query_feature) ** 2)) for i in selected
    )
    median_gross = float(np.median(returns))
    fee_clear_count = int(np.sum(returns > ENTER_MEDIAN))
    if median_gross > ENTER_MEDIAN and fee_clear_count >= ENTER_COUNT:
        action = 1
    elif median_gross <= EXIT_MEDIAN or fee_clear_count <= EXIT_COUNT:
        action = -1
    else:
        action = 0
    return Forecast(
        query_cutoff,
        action,
        median_gross,
        fee_clear_count,
        tuple(int(library_cutoffs[i]) for i in selected),
        selected_distances,
        tuple(float(value) for value in returns),
    )


def forecast_range(
    data: MarketData,
    start: int,
    end: int,
    library_cutoffs: np.ndarray,
    library_features: np.ndarray,
    library_returns: np.ndarray,
) -> dict[int, Forecast]:
    result: dict[int, Forecast] = {}
    for cutoff in daily_indices(data, start, end):
        t = int(cutoff)
        result[t] = select_analogs(
            t, feature_at(data.closes, t), library_cutoffs, library_features, library_returns
        )
    expected = (end - start) // 24
    if len(result) != expected:
        raise RuntimeError(f"decision count mismatch [{start},{end}): {len(result)} != {expected}")
    return result


def e2160_actions(data: MarketData, start: int, end: int) -> dict[int, int]:
    actions: dict[int, int] = {}
    prior_target = 0
    for cutoff in daily_indices(data, start, end):
        t = int(cutoff)
        target = prior_target
        if t >= 2_161:
            target = int(data.closes[t - 1] > data.closes[t - 2_161])
        actions[t] = (
            1
            if target == 1 and prior_target == 0
            else (-1 if target == 0 and prior_target == 1 else 0)
        )
        prior_target = target
    return actions


def episode_statistics(positions: np.ndarray) -> dict[str, Any]:
    runs: list[tuple[int, int]] = []
    if len(positions):
        state, length = int(positions[0]), 1
        for value in positions[1:]:
            current = int(value)
            if current == state:
                length += 1
            else:
                runs.append((state, length))
                state, length = current, 1
        runs.append((state, length))
    long_runs = [length for state, length in runs if state == 1]
    cash_runs = [length for state, length in runs if state == 0]
    return {
        "long_episodes": len(long_runs),
        "cash_episodes": len(cash_runs),
        "median_long_hours": float(statistics.median(long_runs)) if long_runs else 0.0,
        "median_cash_hours": float(statistics.median(cash_runs)) if cash_runs else 0.0,
        "longest_long_hours": max(long_runs, default=0),
        "longest_cash_hours": max(cash_runs, default=0),
    }


def path_metrics(
    gross_returns: np.ndarray, net_returns: np.ndarray, positions: np.ndarray, fee_units: np.ndarray
) -> dict[str, Any]:
    gross_equity = np.cumprod(1.0 + gross_returns)
    net_equity = np.cumprod(1.0 + net_returns)
    equity = np.concatenate(([1.0], net_equity))
    drawdown = equity / np.maximum.accumulate(equity) - 1.0
    standard_deviation = float(np.std(net_returns, ddof=1))
    turnover = float(np.sum(fee_units))
    gross_total = float(gross_equity[-1] - 1.0)
    net_total = float(net_equity[-1] - 1.0)
    entries = int(positions[0] == 1) + int(np.sum((positions[1:] == 1) & (positions[:-1] == 0)))
    exits = int(np.sum((positions[1:] == 0) & (positions[:-1] == 1))) + int(positions[-1] == 1)
    return {
        "hours": len(net_returns),
        "gross_total_return": gross_total,
        "net_total_return": net_total,
        "annualised_arithmetic_mean": float(np.mean(net_returns) * ANNUAL_HOURS),
        "annualised_sharpe": float(
            np.mean(net_returns) / standard_deviation * math.sqrt(ANNUAL_HOURS)
        )
        if standard_deviation > 0
        else 0.0,
        "maximum_drawdown": float(np.min(drawdown)),
        "exposure_fraction": float(np.mean(positions)),
        "one_way_turnover": turnover,
        "transition_count": int(np.count_nonzero(fee_units)),
        "arithmetic_fee_rate_sum": FEE * turnover,
        "fee_drag": float(gross_total - net_total),
        "edge_per_turnover": float(net_total / turnover) if turnover > 0 else 0.0,
        "entries": entries,
        "exits": exits,
        **episode_statistics(positions),
    }


def simulate(
    data: MarketData, start: int, end: int, actions: dict[int, int], force_always_long: bool = False
) -> PathResult:
    positions = np.zeros(end - start, dtype=np.int8)
    fee_units = np.zeros(end - start, dtype=np.float64)
    position = 0
    for execution in range(start, end):
        action: int | None = None
        if force_always_long and execution == start:
            action = 1
        elif execution in actions:
            action = int(actions[execution])
        if action is not None:
            if action not in (-2, -1, 0, 1):
                raise RuntimeError("invalid strategy action")
            target = (
                0 if action == -2 else (1 if action == 1 else (0 if action == -1 else position))
            )
            if target != position:
                fee_units[execution - start] = abs(target - position)
                position = target
        positions[execution - start] = position
    if positions[-1] == 1:
        fee_units[-1] += 1.0
    open_returns = data.opens[start + 1 : end + 1] / data.opens[start:end] - 1.0
    gross_factors = 1.0 + positions * open_returns
    fee_factors = 1.0 - FEE * fee_units
    if np.any(gross_factors <= 0) or np.any(fee_factors <= 0):
        raise RuntimeError("non-positive return factor")
    gross_returns = gross_factors - 1.0
    net_returns = gross_factors * fee_factors - 1.0
    return PathResult(
        path_metrics(gross_returns, net_returns, positions, fee_units),
        positions,
        gross_returns,
        net_returns,
        fee_units,
    )


def fee_identity(path: PathResult) -> bool:
    expected = np.zeros(len(path.positions), dtype=np.float64)
    previous = 0
    for index, position in enumerate(path.positions):
        current = int(position)
        expected[index] = abs(current - previous)
        previous = current
    if path.positions[-1] == 1:
        expected[-1] += 1.0
    factors = (1.0 + path.gross_returns) * (1.0 - FEE * expected)
    return bool(
        np.array_equal(expected, path.fee_units)
        and np.allclose(path.net_returns, factors - 1.0, atol=1e-15, rtol=1e-15)
    )


def annualised_sharpe(values: np.ndarray) -> float:
    standard_deviation = float(np.std(values, ddof=1))
    return (
        float(np.mean(values) / standard_deviation * math.sqrt(ANNUAL_HOURS))
        if standard_deviation > 0
        else 0.0
    )


def maximum_drawdown(values: np.ndarray) -> float:
    equity = np.concatenate(([1.0], np.cumprod(1.0 + values)))
    return float(np.min(equity / np.maximum.accumulate(equity) - 1.0))


def bootstrap(candidate: np.ndarray, benchmark: np.ndarray) -> dict[str, Any]:
    n = len(candidate)
    blocks = math.ceil(n / BOOTSTRAP_BLOCK)
    offsets = np.arange(BOOTSTRAP_BLOCK, dtype=np.int64)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    means = np.empty(BOOTSTRAP_DRAWS)
    sharpes = np.empty(BOOTSTRAP_DRAWS)
    drawdowns = np.empty(BOOTSTRAP_DRAWS)
    for draw in range(BOOTSTRAP_DRAWS):
        starts = rng.integers(0, n - BOOTSTRAP_BLOCK + 1, size=blocks)
        indices = (starts[:, None] + offsets[None, :]).reshape(-1)[:n]
        candidate_draw = candidate[indices]
        benchmark_draw = benchmark[indices]
        means[draw] = float(np.mean(candidate_draw - benchmark_draw))
        sharpes[draw] = annualised_sharpe(candidate_draw) - annualised_sharpe(benchmark_draw)
        drawdowns[draw] = maximum_drawdown(candidate_draw) - maximum_drawdown(benchmark_draw)

    def interval(values: np.ndarray) -> list[float]:
        return [float(value) for value in np.quantile(values, [0.025, 0.975])]

    point_mean = float(np.mean(candidate - benchmark))
    return {
        "mean_hourly_net_difference": point_mean,
        "mean_hourly_net_difference_bp": point_mean * 10_000,
        "mean_hourly_net_difference_ci95": interval(means),
        "mean_hourly_net_difference_bp_ci95": [value * 10_000 for value in interval(means)],
        "annualised_sharpe_difference": annualised_sharpe(candidate) - annualised_sharpe(benchmark),
        "annualised_sharpe_difference_ci95": interval(sharpes),
        "maximum_drawdown_difference": maximum_drawdown(candidate) - maximum_drawdown(benchmark),
        "maximum_drawdown_difference_ci95": interval(drawdowns),
    }


def action_map(forecasts: dict[int, Forecast]) -> dict[int, int]:
    return {cutoff: forecast.action for cutoff, forecast in forecasts.items()}


def delayed_actions(actions: dict[int, int], end: int, delay: int) -> dict[int, int]:
    return {cutoff + delay: action for cutoff, action in actions.items() if cutoff + delay < end}


def decomposition(candidate: PathResult, benchmark: PathResult) -> dict[str, float]:
    gross_difference = float(
        candidate.metrics["gross_total_return"] - benchmark.metrics["gross_total_return"]
    )
    relative_fee = float(candidate.metrics["fee_drag"] - benchmark.metrics["fee_drag"])
    net_difference = float(
        candidate.metrics["net_total_return"] - benchmark.metrics["net_total_return"]
    )
    return {
        "gross_timing_return_difference": gross_difference,
        "relative_fee_drag": relative_fee,
        "net_return_difference": net_difference,
        "interaction_residual": net_difference - (gross_difference - relative_fee),
    }


def segment_bundle(
    data: MarketData, start: int, end: int, forecasts: dict[int, Forecast]
) -> dict[str, Any]:
    candidate_actions = action_map(forecasts)
    benchmark_actions = e2160_actions(data, start, end)
    return {
        "candidate_actions": candidate_actions,
        "e2160_actions": benchmark_actions,
        "candidate": simulate(data, start, end, candidate_actions),
        "e2160": simulate(data, start, end, benchmark_actions),
        "always_long": simulate(data, start, end, {}, force_always_long=True),
        "cash": simulate(data, start, end, {}),
    }


def breadth(data: MarketData, forecasts: dict[int, Forecast]) -> dict[str, Any]:
    actions = action_map(forecasts)
    folds: list[dict[str, Any]] = []
    for start in range(OOS_START, OOS_END, FOLD_HOURS):
        end = min(start + FOLD_HOURS, OOS_END)
        candidate = simulate(data, start, end, actions)
        benchmark = simulate(data, start, end, e2160_actions(data, start, end))
        folds.append(
            {
                "start": start,
                "end": end,
                "candidate_net_return": candidate.metrics["net_total_return"],
                "e2160_net_return": benchmark.metrics["net_total_return"],
                "relative_net_effect": float(
                    candidate.metrics["net_total_return"] - benchmark.metrics["net_total_return"]
                ),
            }
        )
    years_by_hour = np.asarray(
        [
            datetime.fromtimestamp(timestamp / 1000, tz=UTC).year
            for timestamp in data.open_ms[OOS_START:OOS_END]
        ]
    )
    years: list[dict[str, Any]] = []
    for year in sorted(set(int(value) for value in years_by_hour)):
        offsets = np.flatnonzero(years_by_hour == year)
        start = OOS_START + int(offsets[0])
        end = OOS_START + int(offsets[-1]) + 1
        candidate = simulate(data, start, end, actions)
        benchmark = simulate(data, start, end, e2160_actions(data, start, end))
        years.append(
            {
                "year": year,
                "start": start,
                "end": end,
                "candidate_net_return": candidate.metrics["net_total_return"],
                "e2160_net_return": benchmark.metrics["net_total_return"],
                "relative_net_effect": float(
                    candidate.metrics["net_total_return"] - benchmark.metrics["net_total_return"]
                ),
            }
        )
    positive_effects = [max(0.0, float(item["relative_net_effect"])) for item in folds]
    positive_sum = sum(positive_effects)
    concentration = max(positive_effects, default=0.0) / positive_sum if positive_sum > 0 else 1.0
    return {
        "folds": folds,
        "years": years,
        "positive_relative_folds": int(sum(item["relative_net_effect"] > 0 for item in folds)),
        "positive_candidate_years": int(sum(item["candidate_net_return"] > 0 for item in years)),
        "positive_relative_years": int(sum(item["relative_net_effect"] > 0 for item in years)),
        "positive_fold_concentration": float(concentration),
    }


def forecast_diagnostics(forecasts: dict[int, Forecast]) -> dict[str, Any]:
    values = list(forecasts.values())
    complete = [forecast for forecast in values if len(forecast.selected_cutoffs) == NEIGHBOURS]
    nearest = [forecast.selected_distances[0] for forecast in complete]
    selected = [distance for forecast in complete for distance in forecast.selected_distances]
    ages = [
        (forecast.cutoff - cutoff) / 24.0
        for forecast in complete
        for cutoff in forecast.selected_cutoffs
    ]
    dispersions = [float(np.std(forecast.selected_returns, ddof=1)) for forecast in complete]
    return {
        "decision_count": len(values),
        "complete_analog_decisions": len(complete),
        "complete_analog_fraction": len(complete) / len(values),
        "median_nearest_distance": float(np.median(nearest)) if nearest else None,
        "upper_quartile_nearest_distance": float(np.quantile(nearest, 0.75)) if nearest else None,
        "median_selected_distance": float(np.median(selected)) if selected else None,
        "upper_quartile_selected_distance": float(np.quantile(selected, 0.75))
        if selected
        else None,
        "median_analog_age_days": float(np.median(ages)) if ages else None,
        "median_neighbour_outcome_dispersion": float(np.median(dispersions))
        if dispersions
        else None,
        "enter_actions": int(sum(forecast.action == 1 for forecast in values)),
        "exit_actions": int(sum(forecast.action == -1 for forecast in values)),
        "hold_actions": int(sum(forecast.action == 0 for forecast in values)),
        "insufficient_actions": int(sum(forecast.action == -2 for forecast in values)),
    }


def forecasts_identity(forecasts: dict[int, Forecast]) -> str:
    payload = [
        {
            "cutoff": cutoff,
            "action": forecast.action,
            "median_gross": forecast.median_gross,
            "fee_clear_count": forecast.fee_clear_count,
            "selected_cutoffs": list(forecast.selected_cutoffs),
            "selected_distances": list(forecast.selected_distances),
            "selected_returns": list(forecast.selected_returns),
        }
        for cutoff, forecast in sorted(forecasts.items())
    ]
    return sha256_bytes(canonical_json_bytes(payload))


def integrity_tests(
    data: MarketData,
    library_cutoffs: np.ndarray,
    library_features: np.ndarray,
    library_returns: np.ndarray,
    oos_forecasts: dict[int, Forecast],
    oos_path: PathResult,
    e2160_path: PathResult,
    always_path: PathResult,
) -> dict[str, Any]:
    decisions = np.asarray(sorted(oos_forecasts), dtype=np.int64)
    replay_features = np.vstack([feature_at(data.closes, int(cutoff)) for cutoff in decisions])
    suffix = np.concatenate(
        (data.closes, np.asarray([data.closes[-1] * 17.0, data.closes[-1] / 13.0]))
    )
    suffix_features = np.vstack([feature_at(suffix, int(cutoff)) for cutoff in decisions])
    stale_features = np.vstack([feature_at(data.closes, int(cutoff) - 1) for cutoff in decisions])
    replay_forecasts = forecast_range(
        data, OOS_START, OOS_END, library_cutoffs, library_features, library_returns
    )
    analog_ok = True
    for forecast in oos_forecasts.values():
        analog_ok &= all(
            cutoff + LABEL_HOURS <= forecast.cutoff and cutoff < forecast.cutoff
            for cutoff in forecast.selected_cutoffs
        )
        analog_ok &= all(
            abs(a - b) >= SEPARATION_HOURS
            for index, a in enumerate(forecast.selected_cutoffs)
            for b in forecast.selected_cutoffs[index + 1 :]
        )
    return {
        "source_grid": bool(
            len(data.open_ms) == EXPECTED_ROWS and np.all(np.diff(data.open_ms) == 3_600_000)
        ),
        "exact_168h_28block_chronology": bool(
            replay_features.shape == (len(decisions), FEATURE_COUNT)
        ),
        "exact_feature_replay": bool(
            np.array_equal(
                replay_features,
                np.vstack([feature_at(data.closes, int(cutoff)) for cutoff in decisions]),
            )
        ),
        "future_suffix_invariance": bool(np.array_equal(replay_features, suffix_features)),
        "one_hour_delay_sensitivity": bool(
            np.all(np.any(replay_features != stale_features, axis=1))
        ),
        "forecast_distance_tie_replay": forecasts_identity(oos_forecasts)
        == forecasts_identity(replay_forecasts),
        "analog_label_and_separation": bool(analog_ok),
        "candidate_fee_identity": fee_identity(oos_path),
        "e2160_fee_identity": fee_identity(e2160_path),
        "always_long_fee_identity": fee_identity(always_path),
        "terminal_liquidation": bool(
            oos_path.fee_units[-1] >= int(oos_path.positions[-1])
            and e2160_path.fee_units[-1] >= int(e2160_path.positions[-1])
        ),
        "daily_decisions_at_00utc": bool(
            np.all(((data.open_ms[decisions] // 3_600_000) % 24) == 0)
        ),
        "segment_isolation": bool(
            oos_path.fee_units[0] == oos_path.positions[0]
            and e2160_path.fee_units[0] == e2160_path.positions[0]
        ),
    }


def evaluate_market(
    data: MarketData,
    library_cutoffs: np.ndarray,
    library_features: np.ndarray,
    library_returns: np.ndarray,
) -> dict[str, Any]:
    forecasts = {
        "training": forecast_range(
            data, TRAIN_START, TRAIN_END, library_cutoffs, library_features, library_returns
        ),
        "oos": forecast_range(
            data, OOS_START, OOS_END, library_cutoffs, library_features, library_returns
        ),
        "full": forecast_range(
            data, FULL_START, FULL_END, library_cutoffs, library_features, library_returns
        ),
    }
    bundles = {
        "training": segment_bundle(data, TRAIN_START, TRAIN_END, forecasts["training"]),
        "oos": segment_bundle(data, OOS_START, OOS_END, forecasts["oos"]),
        "full": segment_bundle(data, FULL_START, FULL_END, forecasts["full"]),
    }
    oos = bundles["oos"]
    delayed = simulate(
        data, OOS_START, OOS_END, delayed_actions(oos["candidate_actions"], OOS_END, 24)
    )
    breadth_result = breadth(data, forecasts["oos"])
    uncertainty = bootstrap(oos["candidate"].net_returns, oos["e2160"].net_returns)
    integrity = integrity_tests(
        data,
        library_cutoffs,
        library_features,
        library_returns,
        forecasts["oos"],
        oos["candidate"],
        oos["e2160"],
        oos["always_long"],
    )
    integrity["all"] = bool(all(integrity.values()))

    candidate = oos["candidate"].metrics
    benchmark = oos["e2160"].metrics
    always = oos["always_long"].metrics
    diagnostics = forecast_diagnostics(forecasts["oos"])
    gates = {
        "positive_oos_return_and_sharpe": candidate["net_total_return"] > 0
        and candidate["annualised_sharpe"] > 0,
        "beats_e2160_and_always_long": candidate["net_total_return"] > benchmark["net_total_return"]
        and candidate["annualised_sharpe"] > benchmark["annualised_sharpe"]
        and candidate["net_total_return"] > always["net_total_return"]
        and candidate["annualised_sharpe"] > always["annualised_sharpe"],
        "paired_lower_bounds_positive": uncertainty["mean_hourly_net_difference_ci95"][0] > 0
        and uncertainty["annualised_sharpe_difference_ci95"][0] > 0,
        "drawdown": candidate["maximum_drawdown"] >= benchmark["maximum_drawdown"] - 0.05
        and candidate["maximum_drawdown"] > always["maximum_drawdown"],
        "edge_per_turnover": candidate["edge_per_turnover"] > 0
        and candidate["edge_per_turnover"] >= benchmark["edge_per_turnover"],
        "turnover": candidate["one_way_turnover"] <= 3.0 * benchmark["one_way_turnover"]
        and candidate["one_way_turnover"] <= 80,
        "fold_breadth": breadth_result["positive_relative_folds"] >= 4,
        "year_breadth": breadth_result["positive_candidate_years"] == len(breadth_result["years"])
        and breadth_result["positive_relative_years"] == len(breadth_result["years"]),
        "fold_concentration": breadth_result["positive_fold_concentration"] <= 0.5,
        "delay_stress": delayed.metrics["net_total_return"] > 0
        and delayed.metrics["annualised_sharpe"] > 0,
        "analog_availability": diagnostics["complete_analog_fraction"] >= 0.95,
        "integrity": integrity["all"],
    }
    output_segments: dict[str, Any] = {}
    for name, bundle in bundles.items():
        output_segments[name] = {
            "candidate": bundle["candidate"].metrics,
            "benchmarks": {
                "E2160": bundle["e2160"].metrics,
                "always_long": bundle["always_long"].metrics,
                "cash": bundle["cash"].metrics,
            },
            "decomposition_vs_e2160": decomposition(bundle["candidate"], bundle["e2160"]),
            "decision_count": len(forecasts[name]),
            "forecast_sha256": forecasts_identity(forecasts[name]),
            "forecast_diagnostics": forecast_diagnostics(forecasts[name]),
        }
    return {
        "source": data.source,
        "library": {
            "cutoff_count": len(library_cutoffs),
            "cutoffs_sha256": sha256_bytes(np.asarray(library_cutoffs, dtype="<i8").tobytes()),
            "features_sha256": array_sha256(library_features),
            "returns_sha256": array_sha256(library_returns),
        },
        "segments": output_segments,
        "oos_breadth": breadth_result,
        "oos_uncertainty": uncertainty,
        "oos_delay_24h": delayed.metrics,
        "oos_analog_diagnostics": diagnostics,
        "integrity": integrity,
        "acceptance_gates": gates,
        "gates_passed": int(sum(gates.values())),
        "gates_total": len(gates),
        "market_pass": all(gates.values()),
    }


def pct(value: float) -> str:
    return f"{100 * value:+.4f}%"


def render_report(evidence: dict[str, Any]) -> str:
    lines = [
        "# Causal historical-analog consensus with abstention",
        "",
        "```text",
        f"family          {FAMILY_ID}",
        "candidate count 2 independent market candidates",
        "parameter grid  0",
        f"markets         {', '.join(SYMBOLS)} independently",
        "bar/provider    immutable public Binance SPOT 1H",
        "fee             exactly 5 bps one way",
        f"verdict         {evidence['verdict']}",
        "```",
        "",
        "## Frozen architecture",
        "",
        "Each daily query maps the latest 168 completed 1H returns into 28 chronological six-hour sums, RMS-normalises the path, selects 12 nearest fully realised own-history analogs separated by at least 168H, and applies the preregistered median/count hysteresis rule. Exposure is unlevered long or cash; no market pooling, fitting, weighting or parameter search is used.",
        "",
        "## Immutable sample",
        "",
        "```text",
        "source months   2023-04 through 2025-12",
        "rows            24,144 per market",
        "training        [2,160,10,800)",
        "OOS             [10,800,23,760)",
        "full scored     [2,160,23,760)",
        "unscored suffix [23,760,24,144)",
        "```",
        "",
        "## Performance",
        "",
        "| Market | Segment | Candidate net | Sharpe | Max DD | Turnover | Edge/turn | E2160 net | E2160 Sharpe | Always-long net |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for symbol in SYMBOLS:
        market = evidence["markets"][symbol]
        for segment in ("training", "oos", "full"):
            item = market["segments"][segment]
            candidate = item["candidate"]
            e2160 = item["benchmarks"]["E2160"]
            always = item["benchmarks"]["always_long"]
            lines.append(
                f"| {symbol} | {segment} | {pct(candidate['net_total_return'])} | {candidate['annualised_sharpe']:+.4f} | {pct(candidate['maximum_drawdown'])} | {candidate['one_way_turnover']:.0f} | {pct(candidate['edge_per_turnover'])} | {pct(e2160['net_total_return'])} | {e2160['annualised_sharpe']:+.4f} | {pct(always['net_total_return'])} |"
            )
    lines.extend(
        [
            "",
            "## OOS robustness",
            "",
            "| Market | Positive folds | Positive years | Relative years | Concentration | Complete analogs | Delay net / Sharpe | Mean delta CI bp/h | Sharpe delta CI | Gates |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for symbol in SYMBOLS:
        market = evidence["markets"][symbol]
        breadth_result = market["oos_breadth"]
        diagnostics = market["oos_analog_diagnostics"]
        delay = market["oos_delay_24h"]
        uncertainty = market["oos_uncertainty"]
        lines.append(
            f"| {symbol} | {breadth_result['positive_relative_folds']}/6 | {breadth_result['positive_candidate_years']}/{len(breadth_result['years'])} | {breadth_result['positive_relative_years']}/{len(breadth_result['years'])} | {100 * breadth_result['positive_fold_concentration']:.2f}% | {100 * diagnostics['complete_analog_fraction']:.2f}% | {pct(delay['net_total_return'])} / {delay['annualised_sharpe']:+.4f} | [{uncertainty['mean_hourly_net_difference_bp_ci95'][0]:+.4f},{uncertainty['mean_hourly_net_difference_bp_ci95'][1]:+.4f}] | [{uncertainty['annualised_sharpe_difference_ci95'][0]:+.4f},{uncertainty['annualised_sharpe_difference_ci95'][1]:+.4f}] | {market['gates_passed']}/{market['gates_total']} |"
        )
    lines.extend(
        [
            "",
            "## Verdict",
            "",
            f"`{evidence['verdict']}`",
            "",
            "Promotion requires every frozen gate to pass independently in both markets. No market-subset promotion or same-cohort rescue is authorised.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.cache_dir.mkdir(parents=True, exist_ok=True)

    markets = {symbol: load_market(symbol, args.cache_dir) for symbol in SYMBOLS}
    training_libraries = {
        symbol: build_feature_library(data, TRAIN_END) for symbol, data in markets.items()
    }

    protocol = {
        "family_id": FAMILY_ID,
        "symbols": list(SYMBOLS),
        "bar": "1h",
        "fee_one_way": FEE,
        "feature_window": FEATURE_WINDOW,
        "block_hours": BLOCK_HOURS,
        "feature_count": FEATURE_COUNT,
        "neighbours": NEIGHBOURS,
        "separation_hours": SEPARATION_HOURS,
        "label_hours": LABEL_HOURS,
        "entry": {"median_gross_gt": ENTER_MEDIAN, "fee_clear_count_gte": ENTER_COUNT},
        "exit": {"median_gross_lte": EXIT_MEDIAN, "fee_clear_count_lte": EXIT_COUNT},
        "chronology": {
            "training": [TRAIN_START, TRAIN_END],
            "oos": [OOS_START, OOS_END],
            "full": [FULL_START, FULL_END],
            "source_rows": EXPECTED_ROWS,
        },
        "bootstrap": {
            "draws": BOOTSTRAP_DRAWS,
            "block_hours": BOOTSTRAP_BLOCK,
            "seed": BOOTSTRAP_SEED,
        },
        "parameter_grid_count": 0,
    }
    source_manifest = {
        "protocol_sha256": sha256_bytes(canonical_json_bytes(protocol)),
        "sources": {symbol: data.source for symbol, data in markets.items()},
    }
    source_bytes = canonical_json_bytes(source_manifest) + b"\n"
    (args.output_dir / "source-manifest.json").write_bytes(source_bytes)
    (args.output_dir / "source-manifest.sha256").write_text(
        f"{sha256_bytes(source_bytes)}  source-manifest.json\n"
    )

    training_freeze = {
        "protocol": protocol,
        "source_manifest_sha256": sha256_bytes(source_bytes),
        "libraries": {
            symbol: {
                "cutoff_count": len(training_libraries[symbol][0]),
                "cutoffs_sha256": sha256_bytes(
                    np.asarray(training_libraries[symbol][0], dtype="<i8").tobytes()
                ),
                "features_sha256": array_sha256(training_libraries[symbol][1]),
                "returns_sha256": array_sha256(training_libraries[symbol][2]),
                "training_forecast_sha256": forecasts_identity(
                    forecast_range(
                        markets[symbol], TRAIN_START, TRAIN_END, *training_libraries[symbol]
                    )
                ),
            }
            for symbol in SYMBOLS
        },
        "oos_opened": False,
    }
    freeze_bytes = canonical_json_bytes(training_freeze) + b"\n"
    (args.output_dir / "training-freeze.json").write_bytes(freeze_bytes)
    (args.output_dir / "training-freeze.sha256").write_text(
        f"{sha256_bytes(freeze_bytes)}  training-freeze.json\n"
    )

    libraries = {symbol: build_feature_library(data, FULL_END) for symbol, data in markets.items()}
    results = {symbol: evaluate_market(markets[symbol], *libraries[symbol]) for symbol in SYMBOLS}
    accepted = all(result["market_pass"] for result in results.values())
    evidence = {
        **protocol,
        "candidate_count": len(SYMBOLS),
        "provider": PROVIDER,
        "oos_opened_after_training_freeze": True,
        "source_manifest_sha256": sha256_bytes(source_bytes),
        "training_freeze_sha256": sha256_bytes(freeze_bytes),
        "markets": results,
        "markets_passing": int(sum(result["market_pass"] for result in results.values())),
        "accepted": accepted,
        "verdict": ACCEPT if accepted else REJECT,
    }
    evidence_bytes = canonical_json_bytes(evidence) + b"\n"
    (args.output_dir / "evidence.json").write_bytes(evidence_bytes)
    (args.output_dir / "evidence.sha256").write_text(
        f"{sha256_bytes(evidence_bytes)}  evidence.json\n"
    )
    (args.output_dir / "report.md").write_text(render_report(evidence))
    print(
        json.dumps(
            {
                "family_id": FAMILY_ID,
                "verdict": evidence["verdict"],
                "markets_passing": evidence["markets_passing"],
                "evidence_sha256": sha256_bytes(evidence_bytes),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
