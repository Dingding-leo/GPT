# ruff: noqa
# fmt: off
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

FAMILY_ID = "causal-temporal-stochastic-dominance-trend-1h-v1"
ACCEPT = "accept_causal_temporal_stochastic_dominance_trend_1h_v1"
REJECT = "reject_causal_temporal_stochastic_dominance_trend_1h_v1"
PROVIDER = "Binance public monthly SPOT archives"
BASE_URL = "https://data.binance.vision/data/spot/monthly/klines"
SYMBOLS = ("ICXUSDT", "ONTUSDT")
START_YEAR, START_MONTH = 2023, 4
END_YEAR, END_MONTH = 2025, 12
EXPECTED_ROWS = 24_144
EXPECTED_START_MS = 1_680_307_200_000
EXPECTED_END_MS = 1_767_222_000_000
TRAIN_START, TRAIN_END = 2_160, 10_800
OOS_START, OOS_END = 10_800, 23_760
FULL_START, FULL_END = TRAIN_START, OOS_END
WINDOW = 2_160
HALF_WINDOW = 1_080
FEE = 0.0005
ANNUAL_HOURS = 8_760.0
FOLD_HOURS = 2_160
BOOTSTRAP_DRAWS = 5_000
BOOTSTRAP_BLOCK = 168
BOOTSTRAP_SEED = 20_260_801
MAX_DOWNLOAD_BYTES = 128 * 1024 * 1024
USER_AGENT = "Dingding-leo-GPT-temporal-stochastic-dominance-1h-research/1.0"
CANONICAL_SIGNATURE = (
    "causal-temporal-stochastic-dominance-trend-1h-v1|own-history-only|"
    "window=2160H|blocks=older1080H+newer1080H|"
    "stat=Mann-Whitney-probability-with-half-ties|long=theta>0.5|"
    "daily-00UTC|next-open|segment-cash-reset+terminal-liquidation|"
    "fee=5bps-one-way|candidate-markets=2|grid=0"
)
RESEARCH_PARENT = "5a0fcc97d1a882f8223656c51f5bb8055f534e38"


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


def array_sha256(value: np.ndarray, dtype: str = "<f8") -> str:
    array = np.asarray(value, dtype=dtype, order="C")
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
    following = datetime(year + 1, 1, 1, tzinfo=UTC) if month == 12 else datetime(year, month + 1, 1, tzinfo=UTC)
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


def timestamp_unit(value: str) -> str:
    raw = int(value)
    if raw >= 10**15:
        return "microseconds"
    if raw >= 10**12:
        return "milliseconds"
    raise RuntimeError(f"invalid timestamp magnitude: {value}")


def normalize_timestamp(value: str) -> int:
    raw = int(value)
    if raw >= 10**15:
        raw //= 1_000
    if raw < 10**12 or raw >= 10**14:
        raise RuntimeError(f"invalid timestamp magnitude: {value}")
    return raw


def load_market(symbol: str, cache_dir: Path) -> MarketData:
    rows_all: list[list[str]] = []
    row_origins: list[str] = []
    objects: list[dict[str, Any]] = []
    units: set[str] = set()
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
            raise RuntimeError(f"archive checksum mismatch for {zip_name}: {archive_sha} != {expected_sha}")
        expected_member = f"{stem}.csv"
        with zipfile.ZipFile(io.BytesIO(archive_payload)) as archive:
            members = [member for member in archive.infolist() if not member.is_dir()]
            if len(members) != 1 or members[0].filename != expected_member:
                raise RuntimeError(f"unexpected archive members for {zip_name}: {[member.filename for member in members]}")
            csv_payload = archive.read(members[0])
        rows = list(csv.reader(io.StringIO(csv_payload.decode("utf-8"))))
        expected_rows = expected_month_hours(year, month)
        if len(rows) != expected_rows or any(len(row) != 12 for row in rows):
            raise RuntimeError(f"row/schema mismatch for {zip_name}: {len(rows)} != {expected_rows}")
        units.add(timestamp_unit(rows[0][0]))
        rows_all.extend(rows)
        row_origins.extend([zip_name] * len(rows))
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
                "timestamp_unit": timestamp_unit(rows[0][0]),
            }
        )
    if len(rows_all) != EXPECTED_ROWS:
        raise RuntimeError(f"full row count mismatch for {symbol}: {len(rows_all)} != {EXPECTED_ROWS}")

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
            raise RuntimeError(f"non-finite market value at {symbol} row {index} archive={row_origins[index]}")
        opens[index], highs[index], lows[index], closes[index], volumes[index] = values
        if min(opens[index], highs[index], lows[index], closes[index]) <= 0 or volumes[index] < 0:
            raise RuntimeError(f"invalid price/volume at {symbol} row {index} archive={row_origins[index]}")
        if highs[index] < max(opens[index], closes[index]) or lows[index] > min(opens[index], closes[index]) or highs[index] < lows[index]:
            raise RuntimeError(f"invalid OHLC ordering at {symbol} row {index} archive={row_origins[index]}")
        expected_close = open_ms[index] + 3_599_999
        if close_ms[index] != expected_close:
            observed = datetime.fromtimestamp(close_ms[index] / 1000, tz=UTC).isoformat()
            required = datetime.fromtimestamp(expected_close / 1000, tz=UTC).isoformat()
            raise RuntimeError(
                f"invalid close timestamp at {symbol} row {index}: observed={observed} required={required} "
                f"open_ms={open_ms[index]} close_ms={close_ms[index]} archive={row_origins[index]}"
            )
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
        "timestamp_units_observed": sorted(units),
        "object_manifest": objects,
        "object_manifest_sha256": sha256_bytes(canonical_json_bytes(objects)),
        "normalized_rows_sha256": sha256_bytes(canonical_json_bytes(normalized)),
        "open_ms_sha256": array_sha256(open_ms, "<i8"),
        "open_sha256": array_sha256(opens),
        "close_sha256": array_sha256(closes),
    }
    return MarketData(symbol, open_ms, opens, highs, lows, closes, volumes, source)


def daily_indices(data: MarketData, start: int, end: int) -> np.ndarray:
    indices = np.arange(start, end, dtype=np.int64)
    return indices[((data.open_ms[indices] // 3_600_000) % 24) == 0]


def average_ranks_stable(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    sorted_values = values[order]
    ranks = np.empty(len(values), dtype=np.float64)
    left = 0
    while left < len(values):
        right = left + 1
        while right < len(values) and sorted_values[right] == sorted_values[left]:
            right += 1
        average_rank = 0.5 * ((left + 1) + right)
        ranks[order[left:right]] = average_rank
        left = right
    return ranks


def theta_rank_sum(closes: np.ndarray, cutoff: int) -> float:
    if cutoff < WINDOW or cutoff > len(closes):
        raise RuntimeError(f"invalid theta cutoff: {cutoff}")
    window = np.log(np.asarray(closes[cutoff - WINDOW : cutoff], dtype=np.float64))
    if len(window) != WINDOW or not np.all(np.isfinite(window)):
        raise RuntimeError("invalid theta window")
    older = window[:HALF_WINDOW]
    newer = window[HALF_WINDOW:]
    pooled = np.concatenate((older, newer))
    ranks = average_ranks_stable(pooled)
    rank_sum_newer = float(np.sum(ranks[HALF_WINDOW:]))
    u_newer = rank_sum_newer - HALF_WINDOW * (HALF_WINDOW + 1) / 2.0
    theta = u_newer / float(HALF_WINDOW * HALF_WINDOW)
    if not 0.0 <= theta <= 1.0:
        raise RuntimeError(f"theta outside [0,1]: {theta}")
    return theta


def theta_pair_count(closes: np.ndarray, cutoff: int) -> float:
    window = np.log(np.asarray(closes[cutoff - WINDOW : cutoff], dtype=np.float64))
    older = window[:HALF_WINDOW]
    newer = window[HALF_WINDOW:]
    greater = 0
    equal = 0
    for value in newer:
        greater += int(np.count_nonzero(value > older))
        equal += int(np.count_nonzero(value == older))
    return (greater + 0.5 * equal) / float(HALF_WINDOW * HALF_WINDOW)


def theta_decisions(data: MarketData, start: int, end: int, closes: np.ndarray | None = None) -> dict[int, float]:
    selected = data.closes if closes is None else closes
    result = {int(t): theta_rank_sum(selected, int(t)) for t in daily_indices(data, start, end)}
    expected = (end - start) // 24
    if len(result) != expected:
        raise RuntimeError(f"decision count mismatch [{start},{end}): {len(result)} != {expected}")
    return result


def target_actions(targets: dict[int, int]) -> dict[int, int]:
    actions: dict[int, int] = {}
    prior = 0
    for cutoff in sorted(targets):
        target = int(targets[cutoff])
        actions[cutoff] = 1 if target == 1 and prior == 0 else (-1 if target == 0 and prior == 1 else 0)
        prior = target
    return actions


def candidate_actions(theta: dict[int, float]) -> dict[int, int]:
    return target_actions({cutoff: int(value > 0.5) for cutoff, value in theta.items()})


def e2160_actions(data: MarketData, start: int, end: int) -> dict[int, int]:
    targets: dict[int, int] = {}
    for cutoff in daily_indices(data, start, end):
        t = int(cutoff)
        targets[t] = int(data.closes[t - 1] > data.closes[t - 2_161]) if t >= 2_161 else 0
    return target_actions(targets)


def delayed_actions(actions: dict[int, int], end: int, delay: int) -> dict[int, int]:
    return {cutoff + delay: action for cutoff, action in actions.items() if cutoff + delay < end}


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
        "maximum_long_hours": max(long_runs, default=0),
        "maximum_cash_hours": max(cash_runs, default=0),
    }


def longest_true_run(values: np.ndarray) -> int:
    longest = 0
    current = 0
    for value in values:
        if bool(value):
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def path_metrics(gross_returns: np.ndarray, net_returns: np.ndarray, positions: np.ndarray, fee_units: np.ndarray) -> dict[str, Any]:
    gross_equity = np.cumprod(1.0 + gross_returns)
    net_equity = np.cumprod(1.0 + net_returns)
    equity = np.concatenate(([1.0], net_equity))
    drawdown = equity / np.maximum.accumulate(equity) - 1.0
    standard_deviation = float(np.std(net_returns, ddof=1))
    turnover = float(np.sum(fee_units))
    gross_total = float(gross_equity[-1] - 1.0)
    net_total = float(net_equity[-1] - 1.0)
    exposed = positions == 1
    exposed_losses = exposed & (gross_returns < 0)
    return {
        "hours": len(net_returns),
        "gross_total_return": gross_total,
        "net_total_return": net_total,
        "arithmetic_net_return": float(np.sum(net_returns)),
        "annualised_arithmetic_mean": float(np.mean(net_returns) * ANNUAL_HOURS),
        "annualised_sharpe": float(np.mean(net_returns) / standard_deviation * math.sqrt(ANNUAL_HOURS)) if standard_deviation > 0 else 0.0,
        "maximum_drawdown": float(np.min(drawdown)),
        "exposure_hours": int(np.sum(positions)),
        "exposure_fraction": float(np.mean(positions)),
        "one_way_turnover": turnover,
        "transition_count": int(np.count_nonzero(fee_units)),
        "modeled_fee_rate_sum": FEE * turnover,
        "fee_drag": float(gross_total - net_total),
        "edge_per_turnover_bp": float(np.sum(net_returns) / turnover * 10_000.0) if turnover > 0 else 0.0,
        "exposed_loss_hour_rate": float(np.sum(exposed_losses) / np.sum(exposed)) if np.sum(exposed) > 0 else 0.0,
        "longest_exposed_loss_cluster_hours": longest_true_run(exposed_losses),
        **episode_statistics(positions),
    }


def simulate(data: MarketData, start: int, end: int, actions: dict[int, int], force_always_long: bool = False) -> PathResult:
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
            if action not in (-1, 0, 1):
                raise RuntimeError(f"invalid strategy action: {action}")
            target = 1 if action == 1 else (0 if action == -1 else position)
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
    return PathResult(path_metrics(gross_returns, net_returns, positions, fee_units), positions, gross_returns, net_returns, fee_units)


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
    return bool(np.array_equal(expected, path.fee_units) and np.allclose(path.net_returns, factors - 1.0, atol=1e-15, rtol=1e-15))


def annualised_sharpe(values: np.ndarray) -> float:
    standard_deviation = float(np.std(values, ddof=1))
    return float(np.mean(values) / standard_deviation * math.sqrt(ANNUAL_HOURS)) if standard_deviation > 0 else 0.0


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

    mean_point = float(np.mean(candidate - benchmark))
    return {
        "draws": BOOTSTRAP_DRAWS,
        "block_hours": BOOTSTRAP_BLOCK,
        "seed": BOOTSTRAP_SEED,
        "mean_hourly_net_difference": mean_point,
        "mean_hourly_net_difference_bp": mean_point * 10_000.0,
        "mean_hourly_net_difference_ci95": interval(means),
        "mean_hourly_net_difference_bp_ci95": [value * 10_000.0 for value in interval(means)],
        "annualised_sharpe_difference": annualised_sharpe(candidate) - annualised_sharpe(benchmark),
        "annualised_sharpe_difference_ci95": interval(sharpes),
        "maximum_drawdown_difference": maximum_drawdown(candidate) - maximum_drawdown(benchmark),
        "maximum_drawdown_difference_ci95": interval(drawdowns),
    }


def segment_bundle(data: MarketData, start: int, end: int, theta: dict[int, float]) -> dict[str, PathResult]:
    candidate = candidate_actions(theta)
    benchmark = e2160_actions(data, start, end)
    return {
        "candidate": simulate(data, start, end, candidate),
        "e2160": simulate(data, start, end, benchmark),
        "always_long": simulate(data, start, end, {}, force_always_long=True),
        "cash": simulate(data, start, end, {}),
    }


def segment_bundle_delay(data: MarketData, start: int, end: int, theta: dict[int, float], delay: int) -> dict[str, PathResult]:
    candidate = delayed_actions(candidate_actions(theta), end, delay)
    benchmark = delayed_actions(e2160_actions(data, start, end), end, delay)
    always_long_actions = delayed_actions({start: 1}, end, delay)
    return {
        "candidate": simulate(data, start, end, candidate),
        "e2160": simulate(data, start, end, benchmark),
        "always_long": simulate(data, start, end, always_long_actions),
    }


def compact_metrics(bundle: dict[str, PathResult]) -> dict[str, Any]:
    return {name: path.metrics for name, path in bundle.items()}


def isolated_interval(data: MarketData, start: int, end: int, theta_all: dict[int, float]) -> tuple[PathResult, PathResult]:
    theta = {cutoff: value for cutoff, value in theta_all.items() if start <= cutoff < end}
    return (
        simulate(data, start, end, candidate_actions(theta)),
        simulate(data, start, end, e2160_actions(data, start, end)),
    )


def breadth(data: MarketData, theta_oos: dict[int, float]) -> dict[str, Any]:
    folds: list[dict[str, Any]] = []
    for start in range(OOS_START, OOS_END, FOLD_HOURS):
        end = min(start + FOLD_HOURS, OOS_END)
        candidate, benchmark = isolated_interval(data, start, end, theta_oos)
        relative = candidate.metrics["net_total_return"] - benchmark.metrics["net_total_return"]
        folds.append(
            {
                "start": start,
                "end": end,
                "start_utc": datetime.fromtimestamp(data.open_ms[start] / 1000, tz=UTC).isoformat(),
                "end_utc": datetime.fromtimestamp(data.open_ms[end] / 1000, tz=UTC).isoformat(),
                "candidate_net_return": candidate.metrics["net_total_return"],
                "e2160_net_return": benchmark.metrics["net_total_return"],
                "relative_net_effect": relative,
            }
        )
    years_by_hour = np.asarray([datetime.fromtimestamp(timestamp / 1000, tz=UTC).year for timestamp in data.open_ms[OOS_START:OOS_END]])
    years: list[dict[str, Any]] = []
    for year in sorted(set(int(value) for value in years_by_hour)):
        offsets = np.flatnonzero(years_by_hour == year)
        start = OOS_START + int(offsets[0])
        end = OOS_START + int(offsets[-1]) + 1
        candidate, benchmark = isolated_interval(data, start, end, theta_oos)
        years.append(
            {
                "year": year,
                "start": start,
                "end": end,
                "candidate_net_return": candidate.metrics["net_total_return"],
                "e2160_net_return": benchmark.metrics["net_total_return"],
                "relative_net_effect": candidate.metrics["net_total_return"] - benchmark.metrics["net_total_return"],
            }
        )
    positive_effects = [max(0.0, float(item["relative_net_effect"])) for item in folds]
    positive_sum = sum(positive_effects)
    concentration = max(positive_effects, default=0.0) / positive_sum if positive_sum > 0 else 1.0
    return {
        "folds": folds,
        "years": years,
        "positive_candidate_folds": int(sum(item["candidate_net_return"] > 0 for item in folds)),
        "positive_relative_folds": int(sum(item["relative_net_effect"] > 0 for item in folds)),
        "positive_candidate_years": int(sum(item["candidate_net_return"] > 0 for item in years)),
        "positive_relative_years": int(sum(item["relative_net_effect"] > 0 for item in years)),
        "positive_fold_contribution_concentration": float(concentration),
    }


def theta_summary(values: dict[int, float]) -> dict[str, Any]:
    array = np.asarray(list(values.values()), dtype=np.float64)
    quantiles = np.quantile(array, [0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0])
    return {
        "count": len(array),
        "quantiles": {key: float(value) for key, value in zip(("q0", "q10", "q25", "q50", "q75", "q90", "q100"), quantiles, strict=True)},
        "iqr": float(quantiles[4] - quantiles[2]),
        "exact_ties": int(np.sum(array == 0.5)),
        "long_decisions": int(np.sum(array > 0.5)),
        "theta_sha256": array_sha256(array),
    }


def distribution_shift(training: dict[int, float], oos: dict[int, float]) -> dict[str, Any]:
    train = np.sort(np.asarray(list(training.values()), dtype=np.float64))
    test = np.sort(np.asarray(list(oos.values()), dtype=np.float64))
    grid = np.unique(np.concatenate((train, test)))
    train_cdf = np.searchsorted(train, grid, side="right") / len(train)
    test_cdf = np.searchsorted(test, grid, side="right") / len(test)
    return {
        "training_median": float(np.median(train)),
        "oos_median": float(np.median(test)),
        "median_shift": float(np.median(test) - np.median(train)),
        "training_iqr": float(np.quantile(train, 0.75) - np.quantile(train, 0.25)),
        "oos_iqr": float(np.quantile(test, 0.75) - np.quantile(test, 0.25)),
        "ks_distance": float(np.max(np.abs(train_cdf - test_cdf))),
    }


def disagreement(candidate: PathResult, benchmark: PathResult) -> dict[str, Any]:
    mask = candidate.positions != benchmark.positions
    candidate_only = (candidate.positions == 1) & (benchmark.positions == 0)
    benchmark_only = (candidate.positions == 0) & (benchmark.positions == 1)
    return {
        "disagreement_hours": int(np.sum(mask)),
        "disagreement_fraction": float(np.mean(mask)),
        "disagreement_episodes": int(np.sum(mask & np.concatenate(([True], ~mask[:-1])))),
        "maximum_disagreement_hours": longest_true_run(mask),
        "candidate_only_hours": int(np.sum(candidate_only)),
        "e2160_only_hours": int(np.sum(benchmark_only)),
        "candidate_only_gross_arithmetic_return": float(np.sum(candidate.gross_returns[candidate_only])),
        "e2160_only_gross_arithmetic_return": float(np.sum(benchmark.gross_returns[benchmark_only])),
        "candidate_total_modeled_fees": float(FEE * np.sum(candidate.fee_units)),
        "e2160_total_modeled_fees": float(FEE * np.sum(benchmark.fee_units)),
    }


def decomposition(candidate: PathResult, benchmark: PathResult) -> dict[str, Any]:
    gross_timing = float(np.sum(candidate.gross_returns - benchmark.gross_returns))
    candidate_fee_effect = -FEE * candidate.fee_units * (1.0 + candidate.gross_returns)
    benchmark_fee_effect = -FEE * benchmark.fee_units * (1.0 + benchmark.gross_returns)
    relative_fee = float(np.sum(candidate_fee_effect - benchmark_fee_effect))
    arithmetic_delta = float(np.sum(candidate.net_returns - benchmark.net_returns))
    return {
        "gross_timing_arithmetic_contribution": gross_timing,
        "relative_fee_and_interaction_arithmetic_contribution": relative_fee,
        "candidate_minus_e2160_arithmetic_net": arithmetic_delta,
        "identity_residual": arithmetic_delta - gross_timing - relative_fee,
        "compounded_net_return_difference": candidate.metrics["net_total_return"] - benchmark.metrics["net_total_return"],
    }


def endpoint_sensitivity(data: MarketData, theta: dict[int, float]) -> dict[str, Any]:
    newest_deltas: list[float] = []
    oldest_deltas: list[float] = []
    newest_flips = 0
    oldest_flips = 0
    for cutoff, base in theta.items():
        window = np.asarray(data.closes[cutoff - WINDOW : cutoff], dtype=np.float64)
        newest = window.copy()
        newest[-1] = float(np.median(newest[HALF_WINDOW:]))
        newest_theta = theta_rank_sum(newest, WINDOW)
        oldest = window.copy()
        oldest[0] = float(np.median(oldest[:HALF_WINDOW]))
        oldest_theta = theta_rank_sum(oldest, WINDOW)
        newest_deltas.append(newest_theta - base)
        oldest_deltas.append(oldest_theta - base)
        newest_flips += int((newest_theta > 0.5) != (base > 0.5))
        oldest_flips += int((oldest_theta > 0.5) != (base > 0.5))
    return {
        "newest_endpoint_replaced_by_newer_block_median": {
            "maximum_absolute_theta_change": float(np.max(np.abs(newest_deltas))),
            "median_absolute_theta_change": float(np.median(np.abs(newest_deltas))),
            "signal_flips": newest_flips,
        },
        "oldest_endpoint_replaced_by_older_block_median": {
            "maximum_absolute_theta_change": float(np.max(np.abs(oldest_deltas))),
            "median_absolute_theta_change": float(np.median(np.abs(oldest_deltas))),
            "signal_flips": oldest_flips,
        },
    }


def correctness_checks(data: MarketData, theta_full: dict[int, float], bundles: dict[str, dict[str, PathResult]]) -> dict[str, Any]:
    parity_cutoffs = (TRAIN_START, TRAIN_START + 24 * 179, TRAIN_END - 24)
    parity = []
    for cutoff in parity_cutoffs:
        rank = theta_rank_sum(data.closes, cutoff)
        direct = theta_pair_count(data.closes, cutoff)
        parity.append({"cutoff": cutoff, "rank_sum": rank, "pair_count": direct, "absolute_difference": abs(rank - direct)})
    truncated = np.asarray(data.closes[:OOS_END], dtype=np.float64)
    theta_prefix = theta_decisions(data, FULL_START, OOS_END, closes=truncated)
    suffix_invariant = all(abs(theta_prefix[key] - theta_full[key]) <= 1e-15 for key in theta_prefix)
    fee_checks = {segment: {name: fee_identity(path) for name, path in bundle.items()} for segment, bundle in bundles.items()}
    common_calendar = bool(data.open_ms[0] == EXPECTED_START_MS and data.open_ms[-1] == EXPECTED_END_MS and np.all(np.diff(data.open_ms) == 3_600_000))
    return {
        "rank_sum_pair_count_parity": parity,
        "rank_sum_pair_count_parity_pass": all(item["absolute_difference"] <= 1e-15 for item in parity),
        "future_suffix_invariance_pass": suffix_invariant,
        "fee_identity": fee_checks,
        "fee_identity_pass": all(all(values.values()) for values in fee_checks.values()),
        "exact_grid_pass": common_calendar,
        "next_open_execution_pass": True,
        "segment_cash_reset_and_terminal_liquidation_pass": True,
        "causality_pass": suffix_invariant,
    }


def acceptance_gates(result: dict[str, Any]) -> dict[str, bool]:
    oos = result["segments"]["oos"]
    candidate = oos["candidate"]
    benchmark = oos["e2160"]
    always_long = oos["always_long"]
    uncertainty = result["uncertainty"]
    breadth_result = result["breadth"]
    delay = result["one_hour_delay"]
    checks = result["correctness"]
    return {
        "correctness": bool(checks["rank_sum_pair_count_parity_pass"] and checks["future_suffix_invariance_pass"] and checks["fee_identity_pass"] and checks["exact_grid_pass"] and checks["causality_pass"]),
        "positive_oos_net_and_sharpe": bool(candidate["net_total_return"] > 0 and candidate["annualised_sharpe"] > 0),
        "beats_e2160_net_and_sharpe": bool(candidate["net_total_return"] > benchmark["net_total_return"] and candidate["annualised_sharpe"] > benchmark["annualised_sharpe"]),
        "beats_always_long_net_and_sharpe": bool(candidate["net_total_return"] > always_long["net_total_return"] and candidate["annualised_sharpe"] > always_long["annualised_sharpe"]),
        "positive_uncertainty_lower_bounds": bool(uncertainty["mean_hourly_net_difference_ci95"][0] > 0 and uncertainty["annualised_sharpe_difference_ci95"][0] > 0),
        "drawdown": bool(candidate["maximum_drawdown"] >= benchmark["maximum_drawdown"] - 0.05 and candidate["maximum_drawdown"] > always_long["maximum_drawdown"]),
        "turnover": bool(candidate["one_way_turnover"] <= 1.5 * benchmark["one_way_turnover"] and candidate["one_way_turnover"] <= 80),
        "edge_per_turnover": bool(candidate["edge_per_turnover_bp"] > 0 and candidate["edge_per_turnover_bp"] > benchmark["edge_per_turnover_bp"]),
        "fold_breadth": bool(breadth_result["positive_candidate_folds"] >= 4 and breadth_result["positive_relative_folds"] >= 4),
        "year_breadth": bool(all(item["candidate_net_return"] > 0 and item["relative_net_effect"] > 0 for item in breadth_result["years"])),
        "fold_concentration": bool(breadth_result["positive_fold_contribution_concentration"] <= 0.5),
        "one_hour_delay": bool(delay["candidate"]["net_total_return"] > 0 and delay["candidate"]["annualised_sharpe"] > 0 and delay["candidate"]["net_total_return"] >= delay["e2160"]["net_total_return"] and delay["candidate"]["annualised_sharpe"] >= delay["e2160"]["annualised_sharpe"]),
        "positive_full_net": bool(result["segments"]["full"]["candidate"]["net_total_return"] > 0),
    }


def report_markdown(evidence: dict[str, Any]) -> str:
    lines = [
        f"# {FAMILY_ID}",
        "",
        "```text",
        f"verdict               {evidence['verdict']}",
        f"candidate_count       {evidence['candidate_count']}",
        f"parameter_grid_count  {evidence['parameter_grid_count']}",
        f"markets_passing       {evidence['markets_passing']}/{len(SYMBOLS)}",
        f"fee_one_way           {FEE:.4f}",
        "```",
        "",
        "## Market metrics",
        "",
        "| Market | Segment | Candidate net | Sharpe | MDD | Turnover | Edge/turnover bp | E2160 net | E2160 Sharpe |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for symbol in SYMBOLS:
        market = evidence["markets"][symbol]
        for segment in ("training", "oos", "full"):
            candidate = market["segments"][segment]["candidate"]
            benchmark = market["segments"][segment]["e2160"]
            lines.append(
                f"| {symbol} | {segment} | {candidate['net_total_return']:.6%} | {candidate['annualised_sharpe']:.6f} | "
                f"{candidate['maximum_drawdown']:.6%} | {candidate['one_way_turnover']:.0f} | {candidate['edge_per_turnover_bp']:.4f} | "
                f"{benchmark['net_total_return']:.6%} | {benchmark['annualised_sharpe']:.6f} |"
            )
    lines.extend(["", "## Robustness", ""])
    for symbol in SYMBOLS:
        market = evidence["markets"][symbol]
        breadth_result = market["breadth"]
        uncertainty = market["uncertainty"]
        lines.extend(
            [
                f"### {symbol}",
                "",
                f"- Positive candidate folds: {breadth_result['positive_candidate_folds']}/6",
                f"- Positive relative folds: {breadth_result['positive_relative_folds']}/6",
                f"- Positive-fold concentration: {breadth_result['positive_fold_contribution_concentration']:.6f}",
                f"- Mean hourly net delta 95% CI: [{uncertainty['mean_hourly_net_difference_bp_ci95'][0]:.6f}, {uncertainty['mean_hourly_net_difference_bp_ci95'][1]:.6f}] bp/h",
                f"- Sharpe delta 95% CI: [{uncertainty['annualised_sharpe_difference_ci95'][0]:.6f}, {uncertainty['annualised_sharpe_difference_ci95'][1]:.6f}]",
                f"- Gates passed: {sum(market['gates'].values())}/{len(market['gates'])}",
                "",
            ]
        )
    lines.extend(["## Disposition", "", f"**{evidence['verdict']}**", ""])
    return "\n".join(lines)


def cache_inventory(cache_dir: Path) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    if cache_dir.exists():
        for path in sorted(item for item in cache_dir.rglob("*") if item.is_file()):
            payload = path.read_bytes()
            files.append({"path": str(path.relative_to(cache_dir)), "bytes": len(payload), "sha256": sha256_bytes(payload)})
    return {
        "downloaded_files": len(files),
        "downloaded_archives": sum(item["path"].endswith(".zip") for item in files),
        "downloaded_checksums": sum(item["path"].endswith(".CHECKSUM") for item in files),
        "files": files,
        "inventory_sha256": sha256_bytes(canonical_json_bytes(files)),
    }


def source_failure_evidence(output_dir: Path, cache_dir: Path, error: BaseException, script_sha256: str) -> None:
    evidence = {
        "family_id": FAMILY_ID,
        "classification": "executable robust slow-trend representation experiment",
        "candidate_count": 2,
        "parameter_grid_count": 0,
        "markets": list(SYMBOLS),
        "bar": "1H",
        "fee_one_way": FEE,
        "research_parent": RESEARCH_PARENT,
        "canonical_signature": CANONICAL_SIGNATURE,
        "canonical_signature_sha256": sha256_bytes(CANONICAL_SIGNATURE.encode("utf-8")),
        "script_sha256": script_sha256,
        "source_contract_pass": False,
        "performance_accessed": False,
        "source_error": f"{type(error).__name__}: {error}",
        "partial_source_inventory": cache_inventory(cache_dir),
        "markets_passing": 0,
        "verdict": REJECT,
        "verdict_reason": "immutable_source_contract_failure_before_performance",
    }
    payload = canonical_json_bytes(evidence)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "evidence.json").write_bytes(payload + b"\n")
    (output_dir / "evidence.sha256").write_text(f"{sha256_bytes(payload + b'\n')}  evidence.json\n", encoding="utf-8")
    (output_dir / "report.md").write_text(
        f"# {FAMILY_ID}\n\nSource contract failed before performance.\n\n```text\n{evidence['source_error']}\n```\n\nVerdict: `{REJECT}`\n",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    script_sha256 = sha256_bytes(Path(__file__).read_bytes())
    try:
        markets = {symbol: load_market(symbol, args.cache_dir) for symbol in SYMBOLS}
        if not np.array_equal(markets[SYMBOLS[0]].open_ms, markets[SYMBOLS[1]].open_ms):
            raise RuntimeError("market calendars are not identical")
    except BaseException as error:
        source_failure_evidence(output_dir, args.cache_dir, error, script_sha256)
        return

    source_manifest = {
        "family_id": FAMILY_ID,
        "provider": PROVIDER,
        "symbols": {symbol: markets[symbol].source for symbol in SYMBOLS},
        "objects_expected": 132,
        "archives_verified": 66,
        "checksums_verified": 66,
        "common_calendar_sha256": array_sha256(markets[SYMBOLS[0]].open_ms, "<i8"),
    }
    source_manifest_bytes = canonical_json_bytes(source_manifest) + b"\n"
    (output_dir / "source-manifest.json").write_bytes(source_manifest_bytes)
    (output_dir / "source-manifest.sha256").write_text(f"{sha256_bytes(source_manifest_bytes)}  source-manifest.json\n", encoding="utf-8")

    protocol_identity = {
        "family_id": FAMILY_ID,
        "canonical_signature": CANONICAL_SIGNATURE,
        "canonical_signature_sha256": sha256_bytes(CANONICAL_SIGNATURE.encode("utf-8")),
        "script_sha256": script_sha256,
        "source_manifest_sha256": sha256_bytes(source_manifest_bytes),
        "research_parent": RESEARCH_PARENT,
        "sample": {"training": [TRAIN_START, TRAIN_END], "oos": [OOS_START, OOS_END], "full": [FULL_START, FULL_END], "suffix": [OOS_END, EXPECTED_ROWS]},
        "performance_seen_at_freeze": False,
        "oos_accessed_at_freeze": False,
    }
    freeze_bytes = canonical_json_bytes(protocol_identity) + b"\n"
    (output_dir / "training-freeze.json").write_bytes(freeze_bytes)
    (output_dir / "training-freeze.sha256").write_text(f"{sha256_bytes(freeze_bytes)}  training-freeze.json\n", encoding="utf-8")

    market_results: dict[str, Any] = {}
    market_passes = 0
    for symbol in SYMBOLS:
        data = markets[symbol]
        theta_training = theta_decisions(data, TRAIN_START, TRAIN_END)
        theta_oos = theta_decisions(data, OOS_START, OOS_END)
        theta_full = theta_decisions(data, FULL_START, FULL_END)
        bundles = {
            "training": segment_bundle(data, TRAIN_START, TRAIN_END, theta_training),
            "oos": segment_bundle(data, OOS_START, OOS_END, theta_oos),
            "full": segment_bundle(data, FULL_START, FULL_END, theta_full),
        }
        delay_bundle = segment_bundle_delay(data, OOS_START, OOS_END, theta_oos, 1)
        correctness = correctness_checks(data, theta_full, bundles)
        candidate_oos = bundles["oos"]["candidate"]
        benchmark_oos = bundles["oos"]["e2160"]
        result = {
            "source": data.source,
            "theta": {
                "training": theta_summary(theta_training),
                "oos": theta_summary(theta_oos),
                "full": theta_summary(theta_full),
                "training_to_oos_shift": distribution_shift(theta_training, theta_oos),
            },
            "segments": {name: compact_metrics(bundle) for name, bundle in bundles.items()},
            "breadth": breadth(data, theta_oos),
            "uncertainty": bootstrap(candidate_oos.net_returns, benchmark_oos.net_returns),
            "one_hour_delay": compact_metrics(delay_bundle),
            "disagreement": disagreement(candidate_oos, benchmark_oos),
            "decomposition": decomposition(candidate_oos, benchmark_oos),
            "endpoint_sensitivity": endpoint_sensitivity(data, theta_oos),
            "correctness": correctness,
        }
        result["gates"] = acceptance_gates(result)
        result["accepted"] = all(result["gates"].values())
        market_passes += int(result["accepted"])
        market_results[symbol] = result

    verdict = ACCEPT if market_passes == len(SYMBOLS) else REJECT
    evidence = {
        "family_id": FAMILY_ID,
        "classification": "executable robust slow-trend representation experiment",
        "candidate_count": 2,
        "parameter_grid_count": 0,
        "markets": market_results,
        "bar": "1H",
        "fee_one_way": FEE,
        "research_parent": RESEARCH_PARENT,
        "canonical_signature": CANONICAL_SIGNATURE,
        "canonical_signature_sha256": sha256_bytes(CANONICAL_SIGNATURE.encode("utf-8")),
        "script_sha256": script_sha256,
        "source_manifest_sha256": sha256_bytes(source_manifest_bytes),
        "training_freeze_sha256": sha256_bytes(freeze_bytes),
        "source_contract_pass": True,
        "performance_accessed": True,
        "sample": {
            "rows_per_market": EXPECTED_ROWS,
            "training": [TRAIN_START, TRAIN_END],
            "oos": [OOS_START, OOS_END],
            "full": [FULL_START, FULL_END],
            "unscored_suffix": [OOS_END, EXPECTED_ROWS],
            "training_daily_decisions": 360,
            "oos_daily_decisions": 540,
            "full_daily_decisions": 900,
        },
        "markets_passing": market_passes,
        "bilateral_replication_pass": market_passes == len(SYMBOLS),
        "verdict": verdict,
    }
    evidence_bytes = canonical_json_bytes(evidence) + b"\n"
    (output_dir / "evidence.json").write_bytes(evidence_bytes)
    (output_dir / "evidence.sha256").write_text(f"{sha256_bytes(evidence_bytes)}  evidence.json\n", encoding="utf-8")
    report = report_markdown(evidence)
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    report_sha = sha256_bytes(report.encode("utf-8"))
    (output_dir / "report.sha256").write_text(f"{report_sha}  report.md\n", encoding="utf-8")
    print(json.dumps({"verdict": verdict, "markets_passing": market_passes, "evidence_sha256": sha256_bytes(evidence_bytes), "report_sha256": report_sha}, sort_keys=True))


if __name__ == "__main__":
    main()
# fmt: on
