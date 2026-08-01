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

FAMILY_ID = "transaction-cost-aware-online-specialist-arbitration-1h-v1"
VERDICT_ACCEPT = "accept_transaction_cost_aware_online_specialist_arbitration_architecture_v1"
VERDICT_REJECT = "reject_transaction_cost_aware_online_specialist_arbitration_architecture_v1"
PROVIDER = "Binance public monthly SPOT archives"
BASE_URL = "https://data.binance.vision/data/spot/monthly/klines"
SYMBOLS = ("RUNEUSDT", "KAVAUSDT")
START_YEAR = 2023
START_MONTH = 4
END_YEAR = 2025
END_MONTH = 12
EXPECTED_ROWS = 24_144
TRAIN_START = 2_160
TRAIN_END = 10_800
OOS_START = 10_800
OOS_END = 23_760
FULL_START = TRAIN_START
FULL_END = OOS_END
SOURCE_END = EXPECTED_ROWS
FOLD_HOURS = 2_160
FEE = 0.0005
ANNUAL_HOURS = 8_760.0
BOOTSTRAP_DRAWS = 5_000
BOOTSTRAP_BLOCK = 168
BOOTSTRAP_SEED = 20_260_801
EXPERTS = (("E2160", 2_160), ("E1440", 1_440), ("E720", 720))
UTILITY_LAMBDA = math.exp(-24.0 / 720.0)
SWITCH_PENALTY = 0.001
MIN_DWELL_DECISIONS = 7
EXPECTED_START_MS = 1_680_307_200_000
EXPECTED_END_MS = 1_767_222_000_000
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


@dataclass(frozen=True)
class ArbitrationResult:
    path: PathResult
    target_map: dict[int, int]
    diagnostics: dict[str, Any]


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
    year, month = START_YEAR, START_MONTH
    while (year, month) <= (END_YEAR, END_MONTH):
        result.append((year, month))
        month += 1
        if month == 13:
            year += 1
            month = 1
    return result


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
    source_objects: list[dict[str, Any]] = []
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
            members = [item for item in archive.infolist() if not item.is_dir()]
            if len(members) != 1 or members[0].filename != expected_member:
                raise RuntimeError(
                    f"unexpected archive members for {zip_name}: {[item.filename for item in members]}"
                )
            csv_payload = archive.read(members[0])
        rows = list(csv.reader(io.StringIO(csv_payload.decode("utf-8"))))
        expected_rows = expected_month_hours(year, month)
        if len(rows) != expected_rows or any(len(row) != 12 for row in rows):
            raise RuntimeError(f"row/schema mismatch for {zip_name}: {len(rows)} rows")
        rows_all.extend(rows)
        source_objects.append(
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
        "objects": len(source_objects),
        "object_manifest": source_objects,
        "object_manifest_sha256": sha256_bytes(canonical_json_bytes(source_objects)),
        "normalized_rows_sha256": sha256_bytes(canonical_json_bytes(normalized)),
    }
    return MarketData(symbol, open_ms, opens, highs, lows, closes, volumes, source)


def daily_anchors(data: MarketData, start: int, end: int) -> np.ndarray:
    hours = (data.open_ms // 3_600_000) % 24
    anchors = np.flatnonzero(
        (hours == 0) & (np.arange(len(hours)) >= max(horizon for _, horizon in EXPERTS))
    )
    eligible = anchors[((anchors + 1) >= start) & ((anchors + 1) < end)]
    if len(eligible) == 0:
        raise RuntimeError(f"no daily anchors in [{start},{end})")
    return eligible.astype(np.int64)


def expert_signals(data: MarketData, anchor: int) -> np.ndarray:
    signals = np.asarray(
        [int(data.closes[anchor] > data.closes[anchor - horizon]) for _, horizon in EXPERTS],
        dtype=np.int8,
    )
    if np.any((signals != 0) & (signals != 1)):
        raise RuntimeError("invalid expert signal")
    return signals


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
    runs: list[tuple[int, int]] = []
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
        "entries": int(positions[0] == 1)
        + int(np.sum((positions[1:] == 1) & (positions[:-1] == 0))),
        "exits": int(np.sum((positions[1:] == 0) & (positions[:-1] == 1)))
        + int(positions[-1] == 1),
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
        "fee_drag": float(gross_total - net_total),
        "edge_per_turnover": float(net_total / turnover) if turnover > 0 else 0.0,
        **episode_statistics(positions),
    }


def metrics_from_positions(
    opens: np.ndarray,
    start: int,
    end: int,
    positions: np.ndarray,
    fee_units: np.ndarray,
    terminal_liquidation: bool = True,
) -> PathResult:
    if len(positions) != end - start or len(fee_units) != end - start or end >= len(opens):
        raise RuntimeError("invalid path boundaries")
    if np.any((positions != 0) & (positions != 1)):
        raise RuntimeError("invalid position domain")
    fees = fee_units.astype(np.float64, copy=True)
    if terminal_liquidation and positions[-1] == 1:
        fees[-1] += 1.0
    open_returns = opens[start + 1 : end + 1] / opens[start:end] - 1.0
    gross_factors = 1.0 + positions * open_returns
    fee_factors = 1.0 - FEE * fees
    if np.any(gross_factors <= 0) or np.any(fee_factors <= 0):
        raise RuntimeError("non-positive return factor")
    gross_returns = gross_factors - 1.0
    net_returns = gross_factors * fee_factors - 1.0
    return PathResult(
        path_metrics(gross_returns, net_returns, positions, fees),
        positions,
        gross_returns,
        net_returns,
        fees,
    )


def simulate_target_map(
    opens: np.ndarray, start: int, end: int, target_map: dict[int, int]
) -> PathResult:
    positions = np.zeros(end - start, dtype=np.int8)
    fee_units = np.zeros(end - start, dtype=np.float64)
    position = 0
    for execution in range(start, end):
        if execution in target_map:
            target = int(target_map[execution])
            if target not in (0, 1):
                raise RuntimeError("invalid target")
            if target != position:
                fee_units[execution - start] = abs(target - position)
                position = target
        positions[execution - start] = position
    return metrics_from_positions(opens, start, end, positions, fee_units)


def simulate_cash(opens: np.ndarray, start: int, end: int) -> PathResult:
    positions = np.zeros(end - start, dtype=np.int8)
    return metrics_from_positions(
        opens, start, end, positions, np.zeros(end - start), terminal_liquidation=False
    )


def simulate_buy_hold(opens: np.ndarray, start: int, end: int) -> PathResult:
    positions = np.ones(end - start, dtype=np.int8)
    fees = np.zeros(end - start, dtype=np.float64)
    fees[0] = 1.0
    return metrics_from_positions(opens, start, end, positions, fees)


def expert_target_maps(data: MarketData, start: int, end: int) -> dict[str, dict[int, int]]:
    maps = {name: {} for name, _ in EXPERTS}
    for anchor in daily_anchors(data, start, end):
        execution = int(anchor + 1)
        signals = expert_signals(data, int(anchor))
        for expert_index, (name, _) in enumerate(EXPERTS):
            maps[name][execution] = int(signals[expert_index])
    return maps


def arbitration_schedule(
    data: MarketData, start: int, end: int
) -> tuple[dict[int, int], dict[str, Any]]:
    anchors = daily_anchors(data, start, end)
    scores = np.zeros(len(EXPERTS), dtype=np.float64)
    incumbent = 0
    dwell = 0
    previous_signals = np.zeros(len(EXPERTS), dtype=np.int8)
    previous_previous_signals = np.zeros(len(EXPERTS), dtype=np.int8)
    previous_execution: int | None = None
    target_map: dict[int, int] = {}
    identity_counts = np.zeros(len(EXPERTS), dtype=np.int64)
    switch_events: list[dict[str, Any]] = []
    score_min = np.full(len(EXPERTS), np.inf)
    score_max = np.full(len(EXPERTS), -np.inf)
    utility_observations: list[list[float]] = []
    selected_utilities: list[float] = []
    best_utilities: list[float] = []
    identity_history: list[int] = []
    signal_history: list[list[int]] = []
    execution_history: list[int] = []
    dwell_history: list[int] = []

    for anchor_value in anchors:
        anchor = int(anchor_value)
        execution = anchor + 1
        if previous_execution is not None:
            day_return = float(data.opens[execution] / data.opens[previous_execution] - 1.0)
            utilities = np.empty(len(EXPERTS), dtype=np.float64)
            for expert_index in range(len(EXPERTS)):
                gross_factor = 1.0 + int(previous_signals[expert_index]) * day_return
                fee_factor = 1.0 - FEE * abs(
                    int(previous_signals[expert_index])
                    - int(previous_previous_signals[expert_index])
                )
                if gross_factor <= 0 or fee_factor <= 0:
                    raise RuntimeError("non-positive specialist utility factor")
                utilities[expert_index] = math.log(gross_factor * fee_factor)
            scores = UTILITY_LAMBDA * scores + utilities
            utility_observations.append([float(value) for value in utilities])
            selected_utilities.append(float(utilities[identity_history[-1]]))
            best_utilities.append(float(np.max(utilities)))
        if not np.all(np.isfinite(scores)):
            raise RuntimeError("non-finite specialist score")
        score_min = np.minimum(score_min, scores)
        score_max = np.maximum(score_max, scores)

        best = int(np.argmax(scores))
        old_incumbent = incumbent
        if (
            dwell >= MIN_DWELL_DECISIONS
            and best != incumbent
            and float(scores[best] - scores[incumbent]) > SWITCH_PENALTY
        ):
            switch_events.append(
                {
                    "execution_index": execution,
                    "execution_time": datetime.fromtimestamp(
                        data.open_ms[execution] / 1000, tz=UTC
                    ).isoformat(),
                    "from": EXPERTS[incumbent][0],
                    "to": EXPERTS[best][0],
                    "prior_dwell_decisions": dwell,
                    "score_gap": float(scores[best] - scores[incumbent]),
                }
            )
            incumbent = best
            dwell = 0
        signals = expert_signals(data, anchor)
        target_map[execution] = int(signals[incumbent])
        identity_counts[incumbent] += 1
        dwell += 1
        identity_history.append(incumbent)
        signal_history.append([int(value) for value in signals])
        execution_history.append(execution)
        dwell_history.append(dwell)
        previous_previous_signals = previous_signals.copy()
        previous_signals = signals.copy()
        previous_execution = execution
        if (
            old_incumbent != incumbent
            and switch_events[-1]["prior_dwell_decisions"] < MIN_DWELL_DECISIONS
        ):
            raise RuntimeError("minimum dwell violation")

    decisions = int(np.sum(identity_counts))
    residence = {
        EXPERTS[index][0]: float(identity_counts[index] / decisions)
        for index in range(len(EXPERTS))
    }
    diagnostics = {
        "decision_count": decisions,
        "identity_switches": len(switch_events),
        "switch_events": switch_events,
        "identity_decision_counts": {
            EXPERTS[index][0]: int(identity_counts[index]) for index in range(len(EXPERTS))
        },
        "identity_residence_fraction": residence,
        "identities_with_positive_residence": int(np.sum(identity_counts > 0)),
        "terminal_scores": {
            EXPERTS[index][0]: float(scores[index]) for index in range(len(EXPERTS))
        },
        "score_minimum": {
            EXPERTS[index][0]: float(score_min[index]) for index in range(len(EXPERTS))
        },
        "score_maximum": {
            EXPERTS[index][0]: float(score_max[index]) for index in range(len(EXPERTS))
        },
        "minimum_observed_switch_dwell": min(
            (int(event["prior_dwell_decisions"]) for event in switch_events), default=None
        ),
        "minimum_recorded_current_dwell": min(dwell_history, default=0),
        "maximum_recorded_current_dwell": max(dwell_history, default=0),
        "utility_updates": len(utility_observations),
        "ex_post_best_specialist_log_utility": float(sum(best_utilities)),
        "selected_specialist_log_utility": float(sum(selected_utilities)),
        "cumulative_specialist_regret": float(sum(best_utilities) - sum(selected_utilities)),
        "identity_history": identity_history,
        "signal_history": signal_history,
        "execution_history": execution_history,
    }
    return target_map, diagnostics


def hypothetical_identity_window(
    data: MarketData,
    start_execution: int,
    end_execution: int,
    initial_position: int,
    expert_index: int,
) -> float:
    positions = np.empty(end_execution - start_execution, dtype=np.int8)
    fees = np.zeros(end_execution - start_execution, dtype=np.float64)
    position = initial_position
    target_map: dict[int, int] = {}
    for anchor in daily_anchors(data, start_execution, min(end_execution, len(data.opens) - 1)):
        execution = int(anchor + 1)
        if start_execution <= execution < end_execution:
            target_map[execution] = int(expert_signals(data, int(anchor))[expert_index])
    for execution in range(start_execution, end_execution):
        if execution in target_map:
            target = target_map[execution]
            if target != position:
                fees[execution - start_execution] = abs(target - position)
                position = target
        positions[execution - start_execution] = position
    result = metrics_from_positions(
        data.opens, start_execution, end_execution, positions, fees, terminal_liquidation=False
    )
    return float(result.metrics["net_total_return"])


def switch_effectiveness(
    data: MarketData, start: int, end: int, arbitration: ArbitrationResult
) -> dict[str, Any]:
    events = arbitration.diagnostics["switch_events"]
    improvements: list[float] = []
    expert_index = {name: index for index, (name, _) in enumerate(EXPERTS)}
    for event in events:
        execution = int(event["execution_index"])
        window_end = min(execution + 168, end)
        if window_end <= execution:
            continue
        offset = execution - start
        initial_position = int(arbitration.path.positions[offset - 1]) if offset > 0 else 0
        selected = hypothetical_identity_window(
            data, execution, window_end, initial_position, expert_index[str(event["to"])]
        )
        retained = hypothetical_identity_window(
            data, execution, window_end, initial_position, expert_index[str(event["from"])]
        )
        improvements.append(selected - retained)
    return {
        "eligible_switches": len(improvements),
        "improved_switches": int(sum(value > 0 for value in improvements)),
        "mean_168h_net_improvement": float(np.mean(improvements)) if improvements else None,
        "median_168h_net_improvement": float(np.median(improvements)) if improvements else None,
    }


def simulate_arbitration(data: MarketData, start: int, end: int) -> ArbitrationResult:
    target_map, diagnostics = arbitration_schedule(data, start, end)
    path = simulate_target_map(data.opens, start, end, target_map)
    exposure_changes = int(np.count_nonzero(path.fee_units) - int(path.positions[-1] == 1))
    diagnostics = dict(diagnostics)
    diagnostics["actual_exposure_changes_ex_terminal"] = exposure_changes
    diagnostics["identity_only_switches"] = int(
        sum(
            1
            for event in diagnostics["switch_events"]
            if target_map[int(event["execution_index"])]
            == (
                int(path.positions[int(event["execution_index"]) - start - 1])
                if int(event["execution_index"]) > start
                else 0
            )
        )
    )
    result = ArbitrationResult(path, target_map, diagnostics)
    diagnostics["switch_effectiveness"] = switch_effectiveness(data, start, end, result)
    return ArbitrationResult(path, target_map, diagnostics)


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
    return simulate_target_map(opens, start, end, schedule)


def annualised_sharpe(values: np.ndarray) -> float:
    standard_deviation = float(np.std(values, ddof=1))
    return (
        float(np.mean(values) / standard_deviation * math.sqrt(ANNUAL_HOURS))
        if standard_deviation > 0
        else 0.0
    )


def bootstrap(candidate: np.ndarray, experts: dict[str, np.ndarray]) -> dict[str, Any]:
    n = len(candidate)
    if n < BOOTSTRAP_BLOCK or any(len(values) != n for values in experts.values()):
        raise RuntimeError("invalid bootstrap arrays")
    blocks = math.ceil(n / BOOTSTRAP_BLOCK)
    offsets = np.arange(BOOTSTRAP_BLOCK, dtype=np.int64)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    values = {
        name: {"mean": np.empty(BOOTSTRAP_DRAWS), "sharpe": np.empty(BOOTSTRAP_DRAWS)}
        for name in experts
    }
    for draw in range(BOOTSTRAP_DRAWS):
        starts = rng.integers(0, n - BOOTSTRAP_BLOCK + 1, size=blocks)
        indices = (starts[:, None] + offsets[None, :]).reshape(-1)[:n]
        candidate_draw = candidate[indices]
        candidate_sharpe = annualised_sharpe(candidate_draw)
        for name, expert_returns in experts.items():
            expert_draw = expert_returns[indices]
            values[name]["mean"][draw] = float(np.mean(candidate_draw - expert_draw))
            values[name]["sharpe"][draw] = candidate_sharpe - annualised_sharpe(expert_draw)
    result: dict[str, Any] = {}
    for name, metrics in values.items():
        result[name] = {
            "mean_hourly_net_difference_ci95": [
                float(value) for value in np.quantile(metrics["mean"], [0.025, 0.975])
            ],
            "mean_hourly_net_difference_bp_ci95": [
                float(value * 10_000) for value in np.quantile(metrics["mean"], [0.025, 0.975])
            ],
            "annualised_sharpe_difference_ci95": [
                float(value) for value in np.quantile(metrics["sharpe"], [0.025, 0.975])
            ],
        }
    return result


def fold_and_year_breadth(
    data: MarketData, start: int, end: int, returns: np.ndarray
) -> dict[str, Any]:
    if end - start != len(returns):
        raise RuntimeError("breadth path mismatch")
    folds: list[dict[str, Any]] = []
    for fold_start in range(start, end, FOLD_HOURS):
        fold_end = min(fold_start + FOLD_HOURS, end)
        values = returns[fold_start - start : fold_end - start]
        folds.append(
            {
                "start": fold_start,
                "end": fold_end,
                "net_total_return": float(np.prod(1.0 + values) - 1.0),
            }
        )
    years: list[dict[str, Any]] = []
    year_values = np.asarray(
        [
            datetime.fromtimestamp(timestamp / 1000, tz=UTC).year
            for timestamp in data.open_ms[start:end]
        ]
    )
    for year in sorted(set(int(value) for value in year_values)):
        values = returns[year_values == year]
        years.append(
            {
                "year": year,
                "hours": len(values),
                "net_total_return": float(np.prod(1.0 + values) - 1.0),
            }
        )
    positive_returns = [max(0.0, float(item["net_total_return"])) for item in folds]
    positive_sum = sum(positive_returns)
    concentration = max(positive_returns, default=0.0) / positive_sum if positive_sum > 0 else 1.0
    return {
        "folds": folds,
        "years": years,
        "positive_folds": int(sum(item["net_total_return"] > 0 for item in folds)),
        "positive_years": int(sum(item["net_total_return"] > 0 for item in years)),
        "positive_fold_concentration": float(concentration),
    }


def fee_identity(path: PathResult) -> bool:
    expected = np.zeros(len(path.positions), dtype=np.float64)
    previous = 0
    for index, value in enumerate(path.positions):
        current = int(value)
        expected[index] = abs(current - previous)
        previous = current
    if path.positions[-1] == 1:
        expected[-1] += 1.0
    return bool(np.array_equal(expected, path.fee_units))


def slice_market(data: MarketData, length: int) -> MarketData:
    return MarketData(
        data.symbol,
        data.open_ms[:length].copy(),
        data.opens[:length].copy(),
        data.highs[:length].copy(),
        data.lows[:length].copy(),
        data.closes[:length].copy(),
        data.volumes[:length].copy(),
        data.source,
    )


def segment_bundle(data: MarketData, start: int, end: int) -> dict[str, Any]:
    candidate = simulate_arbitration(data, start, end)
    expert_maps = expert_target_maps(data, start, end)
    paths = {
        name: simulate_target_map(data.opens, start, end, expert_maps[name]) for name, _ in EXPERTS
    }
    paths["cash"] = simulate_cash(data.opens, start, end)
    paths["buy_hold"] = simulate_buy_hold(data.opens, start, end)
    return {"candidate": candidate, "paths": paths}


def decomposition(candidate: PathResult, benchmark: PathResult) -> dict[str, float]:
    return {
        "gross_timing_return_difference": float(
            candidate.metrics["gross_total_return"] - benchmark.metrics["gross_total_return"]
        ),
        "fee_drag_difference": float(candidate.metrics["fee_drag"] - benchmark.metrics["fee_drag"]),
        "net_return_difference": float(
            candidate.metrics["net_total_return"] - benchmark.metrics["net_total_return"]
        ),
    }


def evaluate_market(data: MarketData) -> dict[str, Any]:
    segments = {
        "training": (TRAIN_START, TRAIN_END),
        "oos": (OOS_START, OOS_END),
        "full": (FULL_START, FULL_END),
    }
    bundles = {name: segment_bundle(data, start, end) for name, (start, end) in segments.items()}
    oos_candidate: ArbitrationResult = bundles["oos"]["candidate"]
    oos_paths: dict[str, PathResult] = bundles["oos"]["paths"]
    delayed = simulate_delayed(data.opens, OOS_START, OOS_END, oos_candidate.path)
    breadth = fold_and_year_breadth(data, OOS_START, OOS_END, oos_candidate.path.net_returns)
    uncertainty = bootstrap(
        oos_candidate.path.net_returns, {name: oos_paths[name].net_returns for name, _ in EXPERTS}
    )

    replay = simulate_arbitration(data, OOS_START, OOS_END)
    truncated = slice_market(data, OOS_END + 1)
    truncated_replay = simulate_arbitration(truncated, OOS_START, OOS_END)
    integrity = {
        "deterministic_replay": bool(
            np.array_equal(oos_candidate.path.positions, replay.path.positions)
            and np.array_equal(oos_candidate.path.net_returns, replay.path.net_returns)
            and oos_candidate.target_map == replay.target_map
            and oos_candidate.diagnostics["terminal_scores"]
            == replay.diagnostics["terminal_scores"]
        ),
        "suffix_exclusion": bool(
            np.array_equal(oos_candidate.path.positions, truncated_replay.path.positions)
            and np.array_equal(oos_candidate.path.net_returns, truncated_replay.path.net_returns)
            and oos_candidate.target_map == truncated_replay.target_map
        ),
        "candidate_fee_identity": fee_identity(oos_candidate.path),
        "static_fee_identities": all(fee_identity(oos_paths[name]) for name, _ in EXPERTS),
        "daily_execution_only": all(
            ((data.open_ms[execution - 1] // 3_600_000) % 24) == 0
            for execution in oos_candidate.target_map
        ),
        "strict_switch_rules": all(
            int(event["prior_dwell_decisions"]) >= MIN_DWELL_DECISIONS
            and float(event["score_gap"]) > SWITCH_PENALTY
            for event in oos_candidate.diagnostics["switch_events"]
        ),
        "segment_reset": bool(
            oos_candidate.diagnostics["execution_history"]
            and oos_candidate.diagnostics["identity_history"][0] == 0
        ),
    }
    integrity["all"] = all(integrity.values())

    candidate_metrics = oos_candidate.path.metrics
    expert_metrics = {name: oos_paths[name].metrics for name, _ in EXPERTS}
    max_static_turnover = max(
        float(metrics["one_way_turnover"]) for metrics in expert_metrics.values()
    )
    gates = {
        "positive_oos_net": candidate_metrics["net_total_return"] > 0,
        "beats_all_static_net": all(
            candidate_metrics["net_total_return"] > metrics["net_total_return"]
            for metrics in expert_metrics.values()
        ),
        "beats_all_static_sharpe": all(
            candidate_metrics["annualised_sharpe"] > metrics["annualised_sharpe"]
            for metrics in expert_metrics.values()
        ),
        "beats_all_static_drawdown": all(
            candidate_metrics["maximum_drawdown"] > metrics["maximum_drawdown"]
            for metrics in expert_metrics.values()
        ),
        "beats_all_static_edge_per_turnover": candidate_metrics["edge_per_turnover"] > 0
        and all(
            candidate_metrics["edge_per_turnover"] > metrics["edge_per_turnover"]
            for metrics in expert_metrics.values()
        ),
        "temporal_breadth": breadth["positive_folds"] >= 4
        and breadth["positive_years"] == len(breadth["years"]),
        "fold_concentration": breadth["positive_fold_concentration"] <= 0.5,
        "paired_uncertainty": all(
            uncertainty[name]["mean_hourly_net_difference_ci95"][0] > 0
            and uncertainty[name]["annualised_sharpe_difference_ci95"][0] > 0
            for name, _ in EXPERTS
        ),
        "bounded_turnover": candidate_metrics["one_way_turnover"] <= 2.0 * max_static_turnover
        and candidate_metrics["one_way_turnover"] <= (OOS_END - OOS_START) / 96.0,
        "positive_delayed_oos": delayed.metrics["net_total_return"] > 0,
        "positive_full": bundles["full"]["candidate"].path.metrics["net_total_return"] > 0,
        "specialist_usage_and_switch_integrity": oos_candidate.diagnostics[
            "identities_with_positive_residence"
        ]
        >= 2
        and integrity["strict_switch_rules"],
        "integrity": integrity["all"],
    }

    output_segments: dict[str, Any] = {}
    for segment_name, bundle in bundles.items():
        candidate_result: ArbitrationResult = bundle["candidate"]
        output_segments[segment_name] = {
            "candidate": candidate_result.path.metrics,
            "candidate_diagnostics": {
                key: value
                for key, value in candidate_result.diagnostics.items()
                if key not in {"identity_history", "signal_history", "execution_history"}
            },
            "benchmarks": {name: path.metrics for name, path in bundle["paths"].items()},
            "decomposition_vs_static": {
                name: decomposition(candidate_result.path, bundle["paths"][name])
                for name, _ in EXPERTS
            },
        }
    return {
        "source": data.source,
        "segments": output_segments,
        "oos_breadth": breadth,
        "oos_uncertainty": uncertainty,
        "oos_delayed_candidate": delayed.metrics,
        "integrity": integrity,
        "acceptance_gates": gates,
        "gates_passed": int(sum(gates.values())),
        "gates_total": len(gates),
        "market_pass": all(gates.values()),
    }


def pct(value: float | None) -> str:
    return "n/a" if value is None else f"{100.0 * value:+.4f}%"


def number(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.6f}"


def render_report(evidence: dict[str, Any]) -> str:
    lines = [
        "# Transaction-cost-aware online specialist arbitration",
        "",
        "```text",
        f"family          {FAMILY_ID}",
        "candidate count 1",
        "parameter grid  0",
        f"markets         {', '.join(SYMBOLS)} independently",
        "bar/provider    immutable public Binance SPOT 1H",
        "fee             exactly 5 bps one way",
        f"verdict         {evidence['verdict']}",
        "```",
        "",
        "## Strategy",
        "",
        "Three static daily endpoint-trend specialists (720H, 1,440H, 2,160H) are arbitrated using only exponentially discounted strictly prior standalone net log utility. The incumbent changes only after seven daily decisions and only when the challenger's score lead exceeds the frozen 10 bp switching penalty.",
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
        "| Market/segment | Candidate net | Sharpe | Max DD | Turnover | E720 net/Sharpe | E1440 net/Sharpe | E2160 net/Sharpe |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for symbol in SYMBOLS:
        market = evidence["markets"][symbol]
        for segment in ("training", "oos", "full"):
            item = market["segments"][segment]
            candidate = item["candidate"]
            benchmarks = item["benchmarks"]
            lines.append(
                f"| {symbol} {segment} | {pct(candidate['net_total_return'])} | {number(candidate['annualised_sharpe'])} | {pct(candidate['maximum_drawdown'])} | {candidate['one_way_turnover']:.1f} | "
                f"{pct(benchmarks['E720']['net_total_return'])} / {number(benchmarks['E720']['annualised_sharpe'])} | "
                f"{pct(benchmarks['E1440']['net_total_return'])} / {number(benchmarks['E1440']['annualised_sharpe'])} | "
                f"{pct(benchmarks['E2160']['net_total_return'])} / {number(benchmarks['E2160']['annualised_sharpe'])} |"
            )
    lines.extend(["", "## OOS robustness", ""])
    for symbol in SYMBOLS:
        market = evidence["markets"][symbol]
        breadth = market["oos_breadth"]
        diagnostics = market["segments"]["oos"]["candidate_diagnostics"]
        lines.extend(
            [
                f"### {symbol}",
                "",
                "```text",
                f"positive folds/years    {breadth['positive_folds']}/{len(breadth['folds'])}, {breadth['positive_years']}/{len(breadth['years'])}",
                f"positive concentration  {breadth['positive_fold_concentration']:.4f}",
                f"identity switches       {diagnostics['identity_switches']}",
                f"identity residence      {json.dumps(diagnostics['identity_residence_fraction'], sort_keys=True)}",
                f"delayed OOS net         {pct(market['oos_delayed_candidate']['net_total_return'])}",
                f"gates                   {market['gates_passed']}/{market['gates_total']}",
                "```",
                "",
                "| Static expert | Mean-difference 95% CI (bp/hour) | Sharpe-difference 95% CI |",
                "|---|---:|---:|",
            ]
        )
        for name, _ in EXPERTS:
            uncertainty = market["oos_uncertainty"][name]
            mean_ci = uncertainty["mean_hourly_net_difference_bp_ci95"]
            sharpe_ci = uncertainty["annualised_sharpe_difference_ci95"]
            lines.append(
                f"| {name} | [{mean_ci[0]:+.4f}, {mean_ci[1]:+.4f}] | [{sharpe_ci[0]:+.4f}, {sharpe_ci[1]:+.4f}] |"
            )
        lines.extend(
            [
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
            "No canonical mutation, paper authority, live authority, market subset, or same-cohort parameter rescue is permitted unless every frozen bilateral gate passes.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    markets: dict[str, Any] = {}
    for symbol in SYMBOLS:
        markets[symbol] = evaluate_market(load_market(symbol, args.cache_dir))
    markets_passing = int(sum(bool(markets[symbol]["market_pass"]) for symbol in SYMBOLS))
    verdict = VERDICT_ACCEPT if markets_passing == len(SYMBOLS) else VERDICT_REJECT
    evidence = {
        "schema_version": 1,
        "family_id": FAMILY_ID,
        "classification": "one-candidate executable temporal-arbitration experiment",
        "candidate_count": 1,
        "parameter_grid_count": 0,
        "provider": PROVIDER,
        "bar": "1h",
        "fee_one_way": FEE,
        "symbols": list(SYMBOLS),
        "experts": [{"name": name, "lookback_hours": horizon} for name, horizon in EXPERTS],
        "utility_lambda": UTILITY_LAMBDA,
        "switching_penalty": SWITCH_PENALTY,
        "minimum_dwell_decisions": MIN_DWELL_DECISIONS,
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
        "markets": markets,
        "markets_passing": markets_passing,
        "verdict": verdict,
    }
    evidence_bytes = canonical_json_bytes(evidence)
    evidence_sha = sha256_bytes(evidence_bytes)
    report = render_report(evidence)
    (args.output_dir / "evidence.json").write_bytes(evidence_bytes + b"\n")
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
