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

FAMILY_ID = "causal-haar-temporal-basis-fee-clearing-classifier-1h-v1"
ACCEPT = "accept_causal_haar_temporal_basis_fee_clearing_classifier_1h_v1"
REJECT = "reject_causal_haar_temporal_basis_fee_clearing_classifier_1h_v1"
PROVIDER = "Binance public monthly SPOT archives"
BASE_URL = "https://data.binance.vision/data/spot/monthly/klines"
SYMBOLS = ("NEOUSDT", "IOTAUSDT")
START_YEAR, START_MONTH = 2023, 4
END_YEAR, END_MONTH = 2025, 12
EXPECTED_ROWS = 24_144
TRAIN_START, TRAIN_END = 2_160, 10_800
OOS_START, OOS_END = 10_800, 23_760
FULL_START, FULL_END = TRAIN_START, OOS_END
SOURCE_END = EXPECTED_ROWS
FEATURE_WINDOW = 512
HAAR_DEPTHS = tuple(range(5))
FEATURE_COUNT = 32
LABEL_HURDLE = 0.001
RIDGE_LAMBDA = 1.0
THRESHOLD = 0.5
MAX_ITERATIONS = 100
TOLERANCE = 1e-10
FEE = 0.0005
ANNUAL_HOURS = 8_760.0
FOLD_HOURS = 2_160
BOOTSTRAP_DRAWS = 5_000
BOOTSTRAP_BLOCK = 168
BOOTSTRAP_SEED = 20_260_801
EXPECTED_START_MS = 1_680_307_200_000
EXPECTED_END_MS = 1_767_222_000_000
MAX_DOWNLOAD_BYTES = 128 * 1024 * 1024
USER_AGENT = "Dingding-leo-GPT-immutable-haar-1h-research/1.0"


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
class Model:
    feature_mean: np.ndarray
    feature_scale: np.ndarray
    coefficients: np.ndarray
    diagnostics: dict[str, Any]


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


def haar_basis() -> np.ndarray:
    basis = np.zeros((FEATURE_COUNT, FEATURE_WINDOW), dtype=np.float64)
    basis[0] = 1.0 / math.sqrt(FEATURE_WINDOW)
    row = 1
    for depth in HAAR_DEPTHS:
        nodes = 2**depth
        length = FEATURE_WINDOW // nodes
        half = length // 2
        scale = 1.0 / math.sqrt(length)
        for node in range(nodes):
            start = node * length
            basis[row, start : start + half] = scale
            basis[row, start + half : start + length] = -scale
            row += 1
    if row != FEATURE_COUNT:
        raise RuntimeError(f"invalid Haar feature count: {row}")
    gram = basis @ basis.T
    if not np.allclose(gram, np.eye(FEATURE_COUNT), atol=1e-12, rtol=0.0):
        raise RuntimeError("Haar basis is not orthonormal")
    return basis


BASIS = haar_basis()


def feature_at(closes: np.ndarray, decision: int) -> np.ndarray:
    if decision < FEATURE_WINDOW + 1 or decision > len(closes):
        raise RuntimeError(f"invalid feature cutoff {decision}")
    vector = np.diff(np.log(closes[decision - FEATURE_WINDOW - 1 : decision]))
    if len(vector) != FEATURE_WINDOW or not np.all(np.isfinite(vector)):
        raise RuntimeError("invalid return vector")
    rms = max(float(math.sqrt(float(np.mean(vector * vector)))), 1e-12)
    return BASIS @ (vector / rms)


def decision_indices(
    data: MarketData, start: int, end: int, require_label: bool = False
) -> np.ndarray:
    indices = np.arange(start, end, dtype=np.int64)
    utc_hours = (data.open_ms[indices] // 3_600_000) % 24
    valid = (utc_hours == 0) & (indices >= FEATURE_WINDOW + 1)
    if require_label:
        valid &= indices + 24 <= end
    result = indices[valid]
    expected = (end - start) // 24
    if require_label:
        expected = expected
    if len(result) != expected:
        raise RuntimeError(
            f"daily decision count mismatch [{start},{end}): {len(result)} != {expected}"
        )
    return result


def design(data: MarketData, decisions: np.ndarray) -> np.ndarray:
    matrix = np.vstack([feature_at(data.closes, int(decision)) for decision in decisions])
    if matrix.shape != (len(decisions), FEATURE_COUNT):
        raise RuntimeError("invalid feature design")
    return matrix


def labels(data: MarketData, decisions: np.ndarray) -> np.ndarray:
    targets = np.asarray(
        [math.log(data.opens[int(t) + 24] / data.opens[int(t)]) > LABEL_HURDLE for t in decisions],
        dtype=np.float64,
    )
    if len(np.unique(targets)) != 2:
        raise RuntimeError("training target has only one class")
    return targets


def sigmoid(values: np.ndarray) -> np.ndarray:
    output = np.empty_like(values, dtype=np.float64)
    positive = values >= 0
    output[positive] = 1.0 / (1.0 + np.exp(-values[positive]))
    exponential = np.exp(values[~positive])
    output[~positive] = exponential / (1.0 + exponential)
    return output


def fit_model(x: np.ndarray, y: np.ndarray) -> Model:
    mean = np.mean(x, axis=0)
    scale = np.std(x, axis=0, ddof=0)
    scale = np.where(scale > 0, scale, 1.0)
    z = (x - mean) / scale
    augmented = np.column_stack((np.ones(len(z)), z))
    beta = np.zeros(augmented.shape[1], dtype=np.float64)
    penalty = np.zeros_like(beta)
    penalty[1:] = RIDGE_LAMBDA
    converged = False
    updates: list[float] = []
    for iteration in range(1, MAX_ITERATIONS + 1):
        probabilities = sigmoid(augmented @ beta)
        weights = probabilities * (1.0 - probabilities)
        gradient = augmented.T @ (probabilities - y) + penalty * beta
        hessian = augmented.T @ (weights[:, None] * augmented) + np.diag(penalty)
        update = np.linalg.solve(hessian, gradient)
        beta -= update
        maximum_update = float(np.max(np.abs(update)))
        updates.append(maximum_update)
        if maximum_update <= TOLERANCE:
            converged = True
            break
    probabilities = sigmoid(augmented @ beta)
    weights = probabilities * (1.0 - probabilities)
    gradient = augmented.T @ (probabilities - y) + penalty * beta
    hessian = augmented.T @ (weights[:, None] * augmented) + np.diag(penalty)
    eigenvalues = np.linalg.eigvalsh(hessian)
    if not converged:
        raise RuntimeError(f"IRLS did not converge after {MAX_ITERATIONS} iterations")
    diagnostics = {
        "converged": converged,
        "iterations": iteration,
        "maximum_update": updates[-1],
        "maximum_gradient": float(np.max(np.abs(gradient))),
        "hessian_minimum_eigenvalue": float(np.min(eigenvalues)),
        "hessian_condition_number": float(np.linalg.cond(hessian)),
        "objective": float(
            -np.sum(
                y * np.log(np.clip(probabilities, 1e-15, 1.0))
                + (1.0 - y) * np.log(np.clip(1.0 - probabilities, 1e-15, 1.0))
            )
            + 0.5 * RIDGE_LAMBDA * np.sum(beta[1:] ** 2)
        ),
    }
    return Model(mean, scale, beta, diagnostics)


def probabilities(model: Model, x: np.ndarray) -> np.ndarray:
    z = (x - model.feature_mean) / model.feature_scale
    augmented = np.column_stack((np.ones(len(z)), z))
    return sigmoid(augmented @ model.coefficients)


def model_identity(model: Model) -> dict[str, Any]:
    return {
        "feature_mean": [float(value) for value in model.feature_mean],
        "feature_scale": [float(value) for value in model.feature_scale],
        "coefficients": [float(value) for value in model.coefficients],
        "feature_mean_sha256": array_sha256(model.feature_mean),
        "feature_scale_sha256": array_sha256(model.feature_scale),
        "coefficients_sha256": array_sha256(model.coefficients),
        "diagnostics": model.diagnostics,
    }


def target_map_from_probabilities(decisions: np.ndarray, values: np.ndarray) -> dict[int, int]:
    return {
        int(decision): int(probability >= THRESHOLD)
        for decision, probability in zip(decisions, values, strict=True)
    }


def e2160_target_map(data: MarketData, start: int, end: int) -> dict[int, int]:
    result: dict[int, int] = {}
    for decision in decision_indices(data, start, end):
        t = int(decision)
        if t >= 2_161:
            result[t] = int(data.closes[t - 1] > data.closes[t - 2_161])
    return result


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
        "arithmetic_fee_units": turnover,
        "arithmetic_fee_rate_sum": FEE * turnover,
        "fee_drag": float(gross_total - net_total),
        "edge_per_turnover": float(net_total / turnover) if turnover > 0 else 0.0,
        "entries": entries,
        "exits": exits,
        **episode_statistics(positions),
    }


def simulate(
    data: MarketData,
    start: int,
    end: int,
    target_map: dict[int, int],
    force_always_long: bool = False,
) -> PathResult:
    positions = np.zeros(end - start, dtype=np.int8)
    fee_units = np.zeros(end - start, dtype=np.float64)
    position = 0
    for execution in range(start, end):
        target = 1 if force_always_long and execution == start else target_map.get(execution)
        if target is not None:
            target = int(target)
            if target not in (0, 1):
                raise RuntimeError("invalid target position")
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


def classification_diagnostics(y: np.ndarray, p: np.ndarray) -> dict[str, Any]:
    prediction = p >= THRESHOLD
    actual = y.astype(bool)
    clipped = np.clip(p, 1e-15, 1.0 - 1e-15)
    return {
        "count": len(y),
        "positive_prevalence": float(np.mean(y)),
        "predicted_positive_fraction": float(np.mean(prediction)),
        "true_positive": int(np.sum(prediction & actual)),
        "false_positive": int(np.sum(prediction & ~actual)),
        "true_negative": int(np.sum(~prediction & ~actual)),
        "false_negative": int(np.sum(~prediction & actual)),
        "brier_score": float(np.mean((p - y) ** 2)),
        "log_loss": float(-np.mean(y * np.log(clipped) + (1.0 - y) * np.log(1.0 - clipped))),
    }


def decomposition(candidate: PathResult, benchmark: PathResult) -> dict[str, float]:
    return {
        "gross_timing_return_difference": float(
            candidate.metrics["gross_total_return"] - benchmark.metrics["gross_total_return"]
        ),
        "relative_fee_drag": float(candidate.metrics["fee_drag"] - benchmark.metrics["fee_drag"]),
        "net_return_difference": float(
            candidate.metrics["net_total_return"] - benchmark.metrics["net_total_return"]
        ),
    }


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
    point_sharpe = annualised_sharpe(candidate) - annualised_sharpe(benchmark)
    point_drawdown = maximum_drawdown(candidate) - maximum_drawdown(benchmark)
    return {
        "mean_hourly_net_difference": point_mean,
        "mean_hourly_net_difference_bp": point_mean * 10_000,
        "mean_hourly_net_difference_ci95": interval(means),
        "mean_hourly_net_difference_bp_ci95": [value * 10_000 for value in interval(means)],
        "annualised_sharpe_difference": point_sharpe,
        "annualised_sharpe_difference_ci95": interval(sharpes),
        "maximum_drawdown_difference": point_drawdown,
        "maximum_drawdown_difference_ci95": interval(drawdowns),
    }


def segment_bundle(data: MarketData, model: Model, start: int, end: int) -> dict[str, Any]:
    decisions = decision_indices(data, start, end)
    x = design(data, decisions)
    p = probabilities(model, x)
    candidate_map = target_map_from_probabilities(decisions, p)
    e2160_map = e2160_target_map(data, start, end)
    candidate = simulate(data, start, end, candidate_map)
    e2160 = simulate(data, start, end, e2160_map)
    always_long = simulate(data, start, end, {}, force_always_long=True)
    cash = simulate(data, start, end, {})
    return {
        "decisions": decisions,
        "features": x,
        "probabilities": p,
        "candidate_map": candidate_map,
        "e2160_map": e2160_map,
        "candidate": candidate,
        "e2160": e2160,
        "always_long": always_long,
        "cash": cash,
    }


def delayed_target_map(target_map: dict[int, int], end: int, delay: int) -> dict[int, int]:
    return {
        execution + delay: target
        for execution, target in target_map.items()
        if execution + delay < end
    }


def breadth(
    data: MarketData, model: Model, candidate_map: dict[int, int], e2160_map: dict[int, int]
) -> dict[str, Any]:
    folds: list[dict[str, Any]] = []
    for start in range(OOS_START, OOS_END, FOLD_HOURS):
        end = min(start + FOLD_HOURS, OOS_END)
        candidate = simulate(data, start, end, candidate_map)
        benchmark = simulate(data, start, end, e2160_map)
        effect = float(
            candidate.metrics["net_total_return"] - benchmark.metrics["net_total_return"]
        )
        folds.append(
            {
                "start": start,
                "end": end,
                "candidate_net_return": candidate.metrics["net_total_return"],
                "e2160_net_return": benchmark.metrics["net_total_return"],
                "relative_net_effect": effect,
            }
        )
    years: list[dict[str, Any]] = []
    years_by_hour = np.asarray(
        [
            datetime.fromtimestamp(timestamp / 1000, tz=UTC).year
            for timestamp in data.open_ms[OOS_START:OOS_END]
        ]
    )
    for year in sorted(set(int(value) for value in years_by_hour)):
        offsets = np.flatnonzero(years_by_hour == year)
        start = OOS_START + int(offsets[0])
        end = OOS_START + int(offsets[-1]) + 1
        candidate = simulate(data, start, end, candidate_map)
        benchmark = simulate(data, start, end, e2160_map)
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


def feature_integrity(
    data: MarketData, decisions: np.ndarray, features: np.ndarray
) -> dict[str, Any]:
    replay = design(data, decisions)
    truncated = data.closes[: int(decisions[-1]) + 1]
    suffix_replay = np.vstack([feature_at(truncated, int(decision)) for decision in decisions])
    stale = np.vstack([feature_at(data.closes, int(decision) - 1) for decision in decisions])
    stale_different = np.any(features != stale, axis=1)
    return {
        "basis_shape": list(BASIS.shape),
        "basis_orthonormality_max_error": float(
            np.max(np.abs(BASIS @ BASIS.T - np.eye(FEATURE_COUNT)))
        ),
        "basis_orthonormality_pass": bool(
            np.allclose(BASIS @ BASIS.T, np.eye(FEATURE_COUNT), atol=1e-12, rtol=0.0)
        ),
        "exact_feature_replay": bool(np.array_equal(features, replay)),
        "future_suffix_invariance": bool(np.array_equal(features, suffix_replay)),
        "one_hour_stale_feature_different_count": int(np.sum(stale_different)),
        "one_hour_stale_feature_test": bool(np.all(stale_different)),
        "feature_replay_sha256": array_sha256(features),
    }


def evaluate_market(data: MarketData, model: Model, training: dict[str, Any]) -> dict[str, Any]:
    bundles = {
        "training": segment_bundle(data, model, TRAIN_START, TRAIN_END),
        "oos": segment_bundle(data, model, OOS_START, OOS_END),
        "full": segment_bundle(data, model, FULL_START, FULL_END),
    }
    oos = bundles["oos"]
    delayed = simulate(
        data, OOS_START, OOS_END, delayed_target_map(oos["candidate_map"], OOS_END, 24)
    )
    oos_labels = labels(data, oos["decisions"])
    breadth_result = breadth(data, model, oos["candidate_map"], oos["e2160_map"])
    uncertainty = bootstrap(oos["candidate"].net_returns, oos["e2160"].net_returns)
    replay_model = fit_model(training["features"], training["labels"])
    replay_equal = bool(
        np.array_equal(model.coefficients, replay_model.coefficients)
        and np.array_equal(model.feature_mean, replay_model.feature_mean)
        and np.array_equal(model.feature_scale, replay_model.feature_scale)
    )
    integrity = {
        "source_grid": bool(
            len(data.open_ms) == EXPECTED_ROWS and np.all(np.diff(data.open_ms) == 3_600_000)
        ),
        "feature": feature_integrity(data, oos["decisions"], oos["features"]),
        "solver_replay": replay_equal,
        "candidate_fee_identity": fee_identity(oos["candidate"]),
        "e2160_fee_identity": fee_identity(oos["e2160"]),
        "always_long_fee_identity": fee_identity(oos["always_long"]),
        "segment_isolation": bool(
            oos["candidate"].fee_units[0] == oos["candidate"].positions[0]
            and oos["e2160"].fee_units[0] == oos["e2160"].positions[0]
        ),
        "daily_decisions_at_00utc": bool(
            np.all(((data.open_ms[oos["decisions"]] // 3_600_000) % 24) == 0)
        ),
        "suffix_excluded": bool(int(oos["decisions"][-1]) < OOS_END and OOS_END <= SOURCE_END),
    }
    integrity["all"] = bool(
        all(
            value
            if isinstance(value, bool)
            else all(
                subvalue
                for key, subvalue in value.items()
                if key.endswith("pass")
                or key
                in {
                    "exact_feature_replay",
                    "future_suffix_invariance",
                    "one_hour_stale_feature_test",
                }
            )
            for value in integrity.values()
        )
    )

    candidate_metrics = oos["candidate"].metrics
    e2160_metrics = oos["e2160"].metrics
    always_metrics = oos["always_long"].metrics
    gates = {
        "positive_oos_return_and_sharpe": candidate_metrics["net_total_return"] > 0
        and candidate_metrics["annualised_sharpe"] > 0,
        "beats_e2160_and_always_long": candidate_metrics["net_total_return"]
        > e2160_metrics["net_total_return"]
        and candidate_metrics["annualised_sharpe"] > e2160_metrics["annualised_sharpe"]
        and candidate_metrics["net_total_return"] > always_metrics["net_total_return"]
        and candidate_metrics["annualised_sharpe"] > always_metrics["annualised_sharpe"],
        "paired_lower_bounds_positive": uncertainty["mean_hourly_net_difference_ci95"][0] > 0
        and uncertainty["annualised_sharpe_difference_ci95"][0] > 0,
        "drawdown": candidate_metrics["maximum_drawdown"]
        >= e2160_metrics["maximum_drawdown"] - 0.05
        and candidate_metrics["maximum_drawdown"] > always_metrics["maximum_drawdown"],
        "edge_per_turnover": candidate_metrics["edge_per_turnover"] > 0
        and candidate_metrics["edge_per_turnover"] >= e2160_metrics["edge_per_turnover"],
        "turnover": candidate_metrics["one_way_turnover"] <= 3.0 * e2160_metrics["one_way_turnover"]
        and candidate_metrics["one_way_turnover"] <= 120,
        "fold_breadth": breadth_result["positive_relative_folds"] >= 4,
        "year_breadth": breadth_result["positive_candidate_years"] == len(breadth_result["years"])
        and breadth_result["positive_relative_years"] == len(breadth_result["years"]),
        "fold_concentration": breadth_result["positive_fold_concentration"] <= 0.5,
        "delay_stress": delayed.metrics["net_total_return"] > 0
        and delayed.metrics["annualised_sharpe"] > 0,
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
            "decision_count": len(bundle["decisions"]),
            "probability_sha256": array_sha256(bundle["probabilities"]),
            "feature_sha256": array_sha256(bundle["features"]),
        }
    return {
        "source": data.source,
        "model": model_identity(model),
        "training_classification": classification_diagnostics(
            training["labels"], training["probabilities"]
        ),
        "oos_classification": classification_diagnostics(oos_labels, oos["probabilities"]),
        "segments": output_segments,
        "oos_breadth": breadth_result,
        "oos_uncertainty": uncertainty,
        "oos_delay_24h": delayed.metrics,
        "integrity": integrity,
        "acceptance_gates": gates,
        "gates_passed": int(sum(gates.values())),
        "gates_total": len(gates),
        "market_pass": all(gates.values()),
    }


def pct(value: float) -> str:
    return f"{100 * value:+.4f}%"


def number(value: float) -> str:
    return f"{value:+.6f}"


def render_report(evidence: dict[str, Any]) -> str:
    lines = [
        "# Direct causal Haar temporal-basis fee-clearing classifier",
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
        "## Strategy change",
        "",
        "The candidate maps each market's latest 512 completed close-to-close returns to 32 fixed coarse Haar coefficients, standardises them on training only, and applies one training-frozen ridge-logistic boundary to a next-24H 10 bp hurdle. Daily 00:00 UTC decisions execute at the same timestamped open and remain long or cash for 24 hours.",
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
        "| Market/segment | Candidate net | Sharpe | Max DD | Turnover | Edge/turn | E2160 net/Sharpe | Always-long net/Sharpe |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for symbol in SYMBOLS:
        market = evidence["markets"][symbol]
        for segment in ("training", "oos", "full"):
            bundle = market["segments"][segment]
            candidate = bundle["candidate"]
            e2160 = bundle["benchmarks"]["E2160"]
            always = bundle["benchmarks"]["always_long"]
            lines.append(
                f"| {symbol} {segment} | {pct(candidate['net_total_return'])} | {number(candidate['annualised_sharpe'])} | {pct(candidate['maximum_drawdown'])} | {candidate['one_way_turnover']:.0f} | {pct(candidate['edge_per_turnover'])} | {pct(e2160['net_total_return'])} / {number(e2160['annualised_sharpe'])} | {pct(always['net_total_return'])} / {number(always['annualised_sharpe'])} |"
            )
    lines.extend(["", "## OOS robustness", ""])
    for symbol in SYMBOLS:
        market = evidence["markets"][symbol]
        breadth_result = market["oos_breadth"]
        uncertainty = market["oos_uncertainty"]
        delay = market["oos_delay_24h"]
        lines.extend(
            [
                f"### {symbol}",
                "",
                "```text",
                f"relative positive folds       {breadth_result['positive_relative_folds']}/6",
                f"candidate/relative years      {breadth_result['positive_candidate_years']}/{len(breadth_result['years'])}, {breadth_result['positive_relative_years']}/{len(breadth_result['years'])}",
                f"positive-fold concentration   {breadth_result['positive_fold_concentration']:.4f}",
                f"24H delay net / Sharpe         {pct(delay['net_total_return'])} / {number(delay['annualised_sharpe'])}",
                f"mean delta CI bp/hour          [{uncertainty['mean_hourly_net_difference_bp_ci95'][0]:+.4f},{uncertainty['mean_hourly_net_difference_bp_ci95'][1]:+.4f}]",
                f"Sharpe delta CI                [{uncertainty['annualised_sharpe_difference_ci95'][0]:+.4f},{uncertainty['annualised_sharpe_difference_ci95'][1]:+.4f}]",
                f"drawdown delta CI              [{uncertainty['maximum_drawdown_difference_ci95'][0]:+.4f},{uncertainty['maximum_drawdown_difference_ci95'][1]:+.4f}]",
                f"gates                           {market['gates_passed']}/{market['gates_total']}",
                "```",
                "",
                "Failed gates: "
                + ", ".join(
                    name for name, passed in market["acceptance_gates"].items() if not passed
                ),
                "",
            ]
        )
    lines.extend(
        [
            "## Verdict",
            "",
            f"`{evidence['verdict']}`",
            "",
            f"Markets passing: {evidence['markets_passing']}/{len(SYMBOLS)}.",
            "",
            "No canonical mutation, paper/live authority, market subset, or same-cohort change to the basis, window, hurdle, ridge, threshold, cadence, market, benchmark, delay, or sizing is authorised unless every frozen bilateral gate passes.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    data = {symbol: load_market(symbol, args.cache_dir) for symbol in SYMBOLS}
    source_manifest = {symbol: market.source for symbol, market in data.items()}
    source_bytes = canonical_json_bytes(source_manifest) + b"\n"
    (args.output_dir / "source-manifest.json").write_bytes(source_bytes)
    (args.output_dir / "source-manifest.sha256").write_text(
        f"{sha256_bytes(source_bytes)}  source-manifest.json\n", encoding="utf-8"
    )

    models: dict[str, Model] = {}
    training_data: dict[str, dict[str, Any]] = {}
    freeze_markets: dict[str, Any] = {}
    for symbol in SYMBOLS:
        market = data[symbol]
        decisions = decision_indices(market, TRAIN_START, TRAIN_END, require_label=True)
        x = design(market, decisions)
        y = labels(market, decisions)
        model = fit_model(x, y)
        p = probabilities(model, x)
        models[symbol] = model
        training_data[symbol] = {
            "decisions": decisions,
            "features": x,
            "labels": y,
            "probabilities": p,
        }
        freeze_markets[symbol] = {
            "source_normalized_rows_sha256": market.source["normalized_rows_sha256"],
            "training_decisions_sha256": sha256_bytes(np.asarray(decisions, dtype="<i8").tobytes()),
            "training_design_sha256": array_sha256(x),
            "training_labels_sha256": array_sha256(y),
            "model": model_identity(model),
        }
    freeze = {
        "family_id": FAMILY_ID,
        "oos_opened": False,
        "source_manifest_sha256": sha256_bytes(source_bytes),
        "protocol": {
            "feature_window": FEATURE_WINDOW,
            "feature_count": FEATURE_COUNT,
            "haar_depths": list(HAAR_DEPTHS),
            "label_hurdle": LABEL_HURDLE,
            "ridge_lambda": RIDGE_LAMBDA,
            "threshold": THRESHOLD,
            "fee_one_way": FEE,
            "boundaries": {
                "training": [TRAIN_START, TRAIN_END],
                "oos": [OOS_START, OOS_END],
                "full": [FULL_START, FULL_END],
                "suffix": [OOS_END, SOURCE_END],
            },
        },
        "markets": freeze_markets,
    }
    freeze_bytes = canonical_json_bytes(freeze) + b"\n"
    (args.output_dir / "training-freeze.json").write_bytes(freeze_bytes)
    (args.output_dir / "training-freeze.sha256").write_text(
        f"{sha256_bytes(freeze_bytes)}  training-freeze.json\n", encoding="utf-8"
    )

    markets = {
        symbol: evaluate_market(data[symbol], models[symbol], training_data[symbol])
        for symbol in SYMBOLS
    }
    markets_passing = int(sum(bool(markets[symbol]["market_pass"]) for symbol in SYMBOLS))
    verdict = ACCEPT if markets_passing == len(SYMBOLS) else REJECT
    evidence = {
        "schema_version": 1,
        "family_id": FAMILY_ID,
        "classification": "two independent direct causal temporal-representation candidates",
        "candidate_count": 2,
        "parameter_grid_count": 0,
        "provider": PROVIDER,
        "bar": "1h",
        "fee_one_way": FEE,
        "symbols": list(SYMBOLS),
        "feature_window": FEATURE_WINDOW,
        "feature_count": FEATURE_COUNT,
        "haar_depths": list(HAAR_DEPTHS),
        "target_hurdle": LABEL_HURDLE,
        "ridge_lambda": RIDGE_LAMBDA,
        "threshold": THRESHOLD,
        "boundaries": {
            "training": [TRAIN_START, TRAIN_END],
            "oos": [OOS_START, OOS_END],
            "full": [FULL_START, FULL_END],
            "suffix": [OOS_END, SOURCE_END],
        },
        "bootstrap": {
            "draws": BOOTSTRAP_DRAWS,
            "block_hours": BOOTSTRAP_BLOCK,
            "seed": BOOTSTRAP_SEED,
        },
        "source_manifest_sha256": sha256_bytes(source_bytes),
        "training_freeze_sha256": sha256_bytes(freeze_bytes),
        "oos_opened_after_training_freeze": True,
        "markets": markets,
        "markets_passing": markets_passing,
        "verdict": verdict,
    }
    evidence_bytes = canonical_json_bytes(evidence) + b"\n"
    evidence_sha = sha256_bytes(evidence_bytes)
    report = render_report(evidence)
    (args.output_dir / "evidence.json").write_bytes(evidence_bytes)
    (args.output_dir / "evidence.sha256").write_text(
        f"{evidence_sha}  evidence.json\n", encoding="utf-8"
    )
    (args.output_dir / "report.md").write_text(report, encoding="utf-8")
    print(
        json.dumps(
            {
                "family_id": FAMILY_ID,
                "markets_passing": markets_passing,
                "verdict": verdict,
                "evidence_sha256": evidence_sha,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
