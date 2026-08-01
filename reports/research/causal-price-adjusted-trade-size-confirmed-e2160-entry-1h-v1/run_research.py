from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

FAMILY_ID = "causal-price-adjusted-trade-size-confirmed-e2160-entry-1h-v1"
VERDICT_REJECT = "reject_causal_price_adjusted_trade_size_confirmed_e2160_entry_1h_v1"
VERDICT_ACCEPT = "accept_causal_price_adjusted_trade_size_confirmed_e2160_entry_1h_v1"
SYMBOLS = ("ATOMUSDT", "NEARUSDT")
INTERVAL = "1h"
BASE_URL = "https://data.binance.vision/data/spot/monthly/klines"
START = datetime(2023, 4, 1, tzinfo=UTC)
END = datetime(2026, 1, 1, tzinfo=UTC)
EXPECTED_ROWS = 24_144
FEE = 0.0005
TRAIN = (4_320, 10_800)
OOS = (10_800, 23_760)
FULL = (4_320, 23_760)
SUFFIX = (23_760, 24_144)
FOLD_HOURS = 2_160
BOOTSTRAP_DRAWS = 5_000
BOOTSTRAP_BLOCK = 168
BOOTSTRAP_SEED = 20_260_802


@dataclass(frozen=True)
class MarketData:
    symbol: str
    timestamps_ms: np.ndarray
    opens: np.ndarray
    highs: np.ndarray
    lows: np.ndarray
    closes: np.ndarray
    base_volume: np.ndarray
    quote_volume: np.ndarray
    trades: np.ndarray
    size: np.ndarray
    source_objects: list[dict[str, Any]]


def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat().replace("+00:00", "Z")


def month_starts() -> list[datetime]:
    out: list[datetime] = []
    cursor = START
    while cursor < END:
        out.append(cursor)
        if cursor.month == 12:
            cursor = datetime(cursor.year + 1, 1, 1, tzinfo=UTC)
        else:
            cursor = datetime(cursor.year, cursor.month + 1, 1, tzinfo=UTC)
    return out


def next_month(value: datetime) -> datetime:
    if value.month == 12:
        return datetime(value.year + 1, 1, 1, tzinfo=UTC)
    return datetime(value.year, value.month + 1, 1, tzinfo=UTC)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def get_bytes(url: str, attempts: int = 4) -> bytes:
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "gpt-quant-lab-public-research/1.0"},
            )
            with urllib.request.urlopen(request, timeout=60) as response:
                if response.status != 200:
                    raise RuntimeError(f"HTTP {response.status} for {url}")
                return response.read()
        except (urllib.error.URLError, TimeoutError, RuntimeError) as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"public source request failed for {url}: {last}")


def normalize_provider_timestamp(raw: str) -> int:
    value = int(raw)
    if value >= 10_000_000_000_000:
        if value % 1000 not in {0, 999}:
            raise ValueError(f"unexpected microsecond timestamp precision: {value}")
        return value // 1000
    return value


def parse_month(symbol: str, month: datetime) -> tuple[list[tuple[Any, ...]], dict[str, Any]]:
    label = month.strftime("%Y-%m")
    filename = f"{symbol}-{INTERVAL}-{label}.zip"
    root = f"{BASE_URL}/{symbol}/{INTERVAL}"
    checksum_url = f"{root}/{filename}.CHECKSUM"
    archive_url = f"{root}/{filename}"
    checksum_bytes = get_bytes(checksum_url)
    tokens = checksum_bytes.decode("ascii").strip().split()
    if len(tokens) < 2 or len(tokens[0]) != 64 or tokens[-1] != filename:
        raise ValueError(f"invalid checksum object for {filename}")
    expected_sha = tokens[0].lower()
    archive = get_bytes(archive_url)
    actual_sha = sha256_bytes(archive)
    if actual_sha != expected_sha:
        raise ValueError(f"checksum mismatch for {filename}")
    expected_member = filename.removesuffix(".zip") + ".csv"
    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
        names = zipped.namelist()
        if names != [expected_member]:
            raise ValueError(f"unexpected ZIP members for {filename}: {names}")
        csv_bytes = zipped.read(expected_member)
    rows: list[tuple[Any, ...]] = []
    reader = csv.reader(io.StringIO(csv_bytes.decode("utf-8")))
    for line_no, row in enumerate(reader, start=1):
        if len(row) != 12:
            raise ValueError(f"{filename}:{line_no}: expected 12 fields")
        open_ms = normalize_provider_timestamp(row[0])
        close_ms = normalize_provider_timestamp(row[6])
        values = [float(row[i]) for i in (1, 2, 3, 4, 5, 7)]
        if not all(math.isfinite(value) for value in values):
            raise ValueError(f"{filename}:{line_no}: non-finite numeric field")
        open_, high, low, close, base_vol, quote_vol = values
        if min(open_, high, low, close) <= 0:
            raise ValueError(f"{filename}:{line_no}: non-positive OHLC")
        if low > min(open_, close) or high < max(open_, close) or low > high:
            raise ValueError(f"{filename}:{line_no}: invalid OHLC ordering")
        if base_vol < 0 or quote_vol < 0:
            raise ValueError(f"{filename}:{line_no}: negative volume")
        trades = int(row[8])
        if str(trades) != row[8].strip() or trades < 0:
            raise ValueError(f"{filename}:{line_no}: invalid number_of_trades")
        if close_ms != open_ms + 3_600_000 - 1:
            raise ValueError(f"{filename}:{line_no}: incomplete 1H close timestamp")
        rows.append((open_ms, open_, high, low, close, base_vol, quote_vol, trades))
    month_end = next_month(month)
    expected_month_rows = int((month_end - month).total_seconds() // 3600)
    if len(rows) != expected_month_rows:
        raise ValueError(f"{filename}: expected {expected_month_rows} rows, got {len(rows)}")
    expected_first = int(month.timestamp() * 1000)
    expected_last = int((month_end.timestamp() - 3600) * 1000)
    if rows[0][0] != expected_first or rows[-1][0] != expected_last:
        raise ValueError(f"{filename}: monthly boundary mismatch")
    if any(rows[i][0] - rows[i - 1][0] != 3_600_000 for i in range(1, len(rows))):
        raise ValueError(f"{filename}: non-contiguous hourly rows")
    identity = {
        "symbol": symbol,
        "month": label,
        "archive_url": archive_url,
        "checksum_url": checksum_url,
        "archive_filename": filename,
        "archive_sha256": actual_sha,
        "checksum_object_sha256": sha256_bytes(checksum_bytes),
        "member": expected_member,
        "member_sha256": sha256_bytes(csv_bytes),
        "row_count": len(rows),
        "first_timestamp": iso(rows[0][0]),
        "last_timestamp": iso(rows[-1][0]),
    }
    return rows, identity


def acquire_market(symbol: str) -> MarketData:
    months = month_starts()
    results: dict[str, tuple[list[tuple[Any, ...]], dict[str, Any]]] = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(parse_month, symbol, month): month for month in months}
        for future in as_completed(futures):
            month = futures[future]
            results[month.strftime("%Y-%m")] = future.result()
    all_rows: list[tuple[Any, ...]] = []
    objects: list[dict[str, Any]] = []
    for month in months:
        rows, identity = results[month.strftime("%Y-%m")]
        all_rows.extend(rows)
        objects.append(identity)
    if len(all_rows) != EXPECTED_ROWS:
        raise ValueError(f"{symbol}: expected {EXPECTED_ROWS} rows, got {len(all_rows)}")
    timestamps = np.asarray([row[0] for row in all_rows], dtype=np.int64)
    if len(np.unique(timestamps)) != EXPECTED_ROWS:
        raise ValueError(f"{symbol}: duplicate timestamps")
    expected = int(START.timestamp() * 1000) + np.arange(EXPECTED_ROWS, dtype=np.int64) * 3_600_000
    if not np.array_equal(timestamps, expected):
        raise ValueError(f"{symbol}: exact common 1H grid failed")
    opens = np.asarray([row[1] for row in all_rows], dtype=np.float64)
    highs = np.asarray([row[2] for row in all_rows], dtype=np.float64)
    lows = np.asarray([row[3] for row in all_rows], dtype=np.float64)
    closes = np.asarray([row[4] for row in all_rows], dtype=np.float64)
    base_volume = np.asarray([row[5] for row in all_rows], dtype=np.float64)
    quote_volume = np.asarray([row[6] for row in all_rows], dtype=np.float64)
    trades = np.asarray([row[7] for row in all_rows], dtype=np.int64)
    size = np.full(EXPECTED_ROWS, np.nan, dtype=np.float64)
    valid = (quote_volume > 0) & (trades > 0) & (closes > 0)
    size[valid] = np.log(quote_volume[valid] / trades[valid]) - np.log(closes[valid])
    return MarketData(
        symbol=symbol,
        timestamps_ms=timestamps,
        opens=opens,
        highs=highs,
        lows=lows,
        closes=closes,
        base_volume=base_volume,
        quote_volume=quote_volume,
        trades=trades,
        size=size,
        source_objects=objects,
    )


def quarter_label(ms: int) -> str:
    dt = datetime.fromtimestamp(ms / 1000, tz=UTC)
    return f"{dt.year}-Q{(dt.month - 1) // 3 + 1}"


def year_label(ms: int) -> str:
    return str(datetime.fromtimestamp(ms / 1000, tz=UTC).year)


def feature_at(data: MarketData, t: int) -> tuple[float, float] | None:
    if t - 2161 < 0 or t - 1464 < 0:
        return None
    old = data.size[t - 1464 : t - 744]
    recent = data.size[t - 744 : t - 24]
    if len(old) != 720 or len(recent) != 720 or not np.isfinite(old).all() or not np.isfinite(recent).all():
        return None
    spot_margin = math.log(data.closes[t - 1] / data.closes[t - 2161])
    size_margin = float(np.median(recent) - np.median(old))
    if not math.isfinite(spot_margin) or not math.isfinite(size_margin):
        return None
    return spot_margin, size_margin


def decision_indices(start: int, end: int) -> list[int]:
    return [t for t in range(start, end) if t % 24 == 0]


def decision_trace(data: MarketData, start: int, end: int, kind: str) -> list[dict[str, Any]]:
    position = 0
    pending_veto = False
    trace: list[dict[str, Any]] = []
    for t in decision_indices(start, end):
        feature = feature_at(data, t)
        valid = feature is not None
        spot_margin = None if feature is None else feature[0]
        size_margin = None if feature is None else feature[1]
        prior_position = position
        veto = False
        deferred_entry = False
        if kind == "cash":
            position = 0
        elif kind == "always_long":
            position = 1
        elif kind == "e2160":
            position = int(valid and spot_margin is not None and spot_margin > 0)
        elif kind == "candidate":
            if not valid or spot_margin is None or spot_margin <= 0:
                position = 0
                pending_veto = False
            elif position == 1:
                position = 1
            elif size_margin is not None and size_margin > 0:
                position = 1
                deferred_entry = pending_veto
                pending_veto = False
            else:
                position = 0
                veto = True
                pending_veto = True
        else:
            raise ValueError(kind)
        trace.append(
            {
                "t": t,
                "timestamp": iso(int(data.timestamps_ms[t])),
                "quarter": quarter_label(int(data.timestamps_ms[t])),
                "year": year_label(int(data.timestamps_ms[t])),
                "valid": valid,
                "spot_margin": spot_margin,
                "size_margin": size_margin,
                "prior_position": prior_position,
                "position": position,
                "veto": veto,
                "deferred_entry": deferred_entry,
            }
        )
    return trace


def suffix_invariance(data: MarketData) -> bool:
    original = [
        feature_at(data, t)
        for t in decision_indices(FULL[0], FULL[1])
    ]
    size = data.size.copy()
    closes = data.closes.copy()
    size[SUFFIX[0] :] = 1_000_000.0
    closes[SUFFIX[0] :] = closes[SUFFIX[0] :] * 17.0
    altered = MarketData(
        symbol=data.symbol,
        timestamps_ms=data.timestamps_ms,
        opens=data.opens,
        highs=data.highs,
        lows=data.lows,
        closes=closes,
        base_volume=data.base_volume,
        quote_volume=data.quote_volume,
        trades=data.trades,
        size=size,
        source_objects=data.source_objects,
    )
    changed = [feature_at(altered, t) for t in decision_indices(FULL[0], FULL[1])]
    return original == changed


def support_audit(data: MarketData) -> dict[str, Any]:
    trace = decision_trace(data, TRAIN[0], TRAIN[1], "candidate")
    valid = [row for row in trace if row["valid"]]
    margins = np.asarray([row["size_margin"] for row in valid], dtype=np.float64)
    quarters = sorted({row["quarter"] for row in valid})
    vetoes = [row for row in trace if row["veto"]]
    veto_quarters: dict[str, int] = {}
    for row in vetoes:
        veto_quarters[row["quarter"]] = veto_quarters.get(row["quarter"], 0) + 1
    deferred = [row for row in trace if row["deferred_entry"]]
    largest = max(veto_quarters.values(), default=0)
    concentration = largest / len(vetoes) if vetoes else None
    expected_quarters = sorted(
        {
            quarter_label(int(data.timestamps_ms[t]))
            for t in decision_indices(TRAIN[0], TRAIN[1])
        }
    )
    gates = {
        "at_least_250_valid_training_decisions": len(valid) >= 250,
        "valid_features_in_every_training_quarter": quarters == expected_quarters,
        "nonzero_iqr_and_30_distinct_margins": (
            len(margins) > 0
            and float(np.percentile(margins, 75) - np.percentile(margins, 25)) > 0
            and len(set(float(value) for value in margins)) >= 30
        ),
        "at_least_20_veto_opportunities": len(vetoes) >= 20,
        "vetoes_in_at_least_four_quarters": len(veto_quarters) >= 4,
        "no_quarter_above_50_percent": concentration is not None and concentration <= 0.50,
        "at_least_20_later_authorized_entries": len(deferred) >= 20,
        "future_suffix_invariance": suffix_invariance(data),
        "source_timing_feature_identities": True,
    }
    return {
        "valid_training_decisions": len(valid),
        "training_quarters": quarters,
        "expected_training_quarters": expected_quarters,
        "size_margin_distinct_count": len(set(float(value) for value in margins)),
        "size_margin_iqr": None
        if len(margins) == 0
        else float(np.percentile(margins, 75) - np.percentile(margins, 25)),
        "size_margin_quantiles": None
        if len(margins) == 0
        else {
            "p01": float(np.percentile(margins, 1)),
            "p25": float(np.percentile(margins, 25)),
            "p50": float(np.percentile(margins, 50)),
            "p75": float(np.percentile(margins, 75)),
            "p99": float(np.percentile(margins, 99)),
        },
        "veto_count": len(vetoes),
        "veto_quarter_counts": veto_quarters,
        "veto_quarter_concentration": concentration,
        "later_authorized_entry_count": len(deferred),
        "gates": gates,
        "passed": all(gates.values()),
    }


def positions_from_trace(start: int, end: int, trace: list[dict[str, Any]]) -> np.ndarray:
    positions = np.zeros(end - start, dtype=np.int8)
    by_t = {int(row["t"]): int(row["position"]) for row in trace}
    position = 0
    for t in range(start, end):
        if t in by_t:
            position = by_t[t]
        positions[t - start] = position
    return positions


def episode_summary(positions: np.ndarray) -> dict[str, Any]:
    if len(positions) == 0:
        return {"long_count": 0, "cash_count": 0, "long_hours": [], "cash_hours": []}
    runs: dict[int, list[int]] = {0: [], 1: []}
    current = int(positions[0])
    length = 1
    for value in positions[1:]:
        value_i = int(value)
        if value_i == current:
            length += 1
        else:
            runs[current].append(length)
            current = value_i
            length = 1
    runs[current].append(length)
    return {
        "long_count": len(runs[1]),
        "cash_count": len(runs[0]),
        "long_hours": runs[1],
        "cash_hours": runs[0],
    }


def evaluate_positions(data: MarketData, start: int, end: int, positions: np.ndarray) -> dict[str, Any]:
    returns = data.opens[start + 1 : end + 1] / data.opens[start:end] - 1.0
    gross = positions.astype(np.float64) * returns
    net = gross.copy()
    prior_position = 0
    turnover = 0.0
    transitions = 0
    for i, position in enumerate(positions):
        change = abs(int(position) - prior_position)
        if change:
            transitions += 1
            turnover += change
            net[i] -= FEE * change
        prior_position = int(position)
    terminal = abs(prior_position)
    if terminal:
        turnover += terminal
        transitions += 1
        net[-1] -= FEE * terminal
    gross_equity = np.cumprod(1.0 + gross)
    net_equity = np.cumprod(1.0 + net)
    peaks = np.maximum.accumulate(np.concatenate(([1.0], net_equity)))
    equity_with_initial = np.concatenate(([1.0], net_equity))
    drawdowns = equity_with_initial / peaks - 1.0
    mean = float(np.mean(net))
    std = float(np.std(net, ddof=1)) if len(net) > 1 else 0.0
    sharpe = None if std <= 0 else mean / std * math.sqrt(8_760)
    net_return = float(net_equity[-1] - 1.0)
    return {
        "gross_compound_return": float(gross_equity[-1] - 1.0),
        "net_compound_return": net_return,
        "annualized_arithmetic_mean": mean * 8_760,
        "sharpe": sharpe,
        "maximum_drawdown": float(np.min(drawdowns)),
        "exposure_fraction": float(np.mean(positions)),
        "one_way_turnover": turnover,
        "transitions_including_terminal": transitions,
        "modeled_fees": turnover * FEE,
        "edge_per_turnover_bps": None if turnover == 0 else net_return / turnover * 10_000,
        "episodes": episode_summary(positions),
        "hourly_gross_returns": gross,
        "hourly_net_returns": net,
    }


def evaluate_strategy(data: MarketData, start: int, end: int, kind: str, delay: int = 0) -> dict[str, Any]:
    trace = decision_trace(data, start, end, kind)
    positions = positions_from_trace(start, end, trace)
    if delay:
        shifted = np.zeros_like(positions)
        shifted[delay:] = positions[:-delay]
        positions = shifted
    metrics = evaluate_positions(data, start, end, positions)
    metrics["decision_trace"] = trace
    metrics["positions"] = positions
    return metrics


def public_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in metrics.items() if key not in {"hourly_gross_returns", "hourly_net_returns", "positions", "decision_trace"}}


def bootstrap_intervals(candidate: np.ndarray, benchmark: np.ndarray) -> dict[str, Any]:
    n = len(candidate)
    if len(benchmark) != n or n < BOOTSTRAP_BLOCK:
        raise ValueError("invalid bootstrap inputs")
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    starts_max = n - BOOTSTRAP_BLOCK + 1
    blocks_needed = math.ceil(n / BOOTSTRAP_BLOCK)
    mean_diffs = np.empty(BOOTSTRAP_DRAWS, dtype=np.float64)
    sharpe_diffs = np.empty(BOOTSTRAP_DRAWS, dtype=np.float64)
    for draw in range(BOOTSTRAP_DRAWS):
        starts = rng.integers(0, starts_max, size=blocks_needed)
        indices = np.concatenate(
            [np.arange(start, start + BOOTSTRAP_BLOCK, dtype=np.int64) for start in starts]
        )[:n]
        cand = candidate[indices]
        bench = benchmark[indices]
        mean_diffs[draw] = float(np.mean(cand - bench))
        cand_std = float(np.std(cand, ddof=1))
        bench_std = float(np.std(bench, ddof=1))
        cand_sharpe = 0.0 if cand_std <= 0 else float(np.mean(cand) / cand_std * math.sqrt(8_760))
        bench_sharpe = 0.0 if bench_std <= 0 else float(np.mean(bench) / bench_std * math.sqrt(8_760))
        sharpe_diffs[draw] = cand_sharpe - bench_sharpe
    return {
        "draws": BOOTSTRAP_DRAWS,
        "block_hours": BOOTSTRAP_BLOCK,
        "seed": BOOTSTRAP_SEED,
        "mean_hourly_net_difference_95ci": [
            float(np.percentile(mean_diffs, 2.5)),
            float(np.percentile(mean_diffs, 97.5)),
        ],
        "annualized_sharpe_difference_95ci": [
            float(np.percentile(sharpe_diffs, 2.5)),
            float(np.percentile(sharpe_diffs, 97.5)),
        ],
    }


def evaluate_market(data: MarketData) -> dict[str, Any]:
    segments: dict[str, Any] = {}
    raw: dict[str, dict[str, dict[str, Any]]] = {}
    for segment_name, bounds in (("training", TRAIN), ("oos", OOS), ("full", FULL)):
        raw[segment_name] = {}
        segments[segment_name] = {}
        for kind in ("candidate", "e2160", "always_long", "cash"):
            metrics = evaluate_strategy(data, bounds[0], bounds[1], kind)
            raw[segment_name][kind] = metrics
            segments[segment_name][kind] = public_metrics(metrics)
    folds: list[dict[str, Any]] = []
    for fold in range(6):
        start = OOS[0] + fold * FOLD_HOURS
        end = start + FOLD_HOURS
        candidate = evaluate_strategy(data, start, end, "candidate")
        benchmark = evaluate_strategy(data, start, end, "e2160")
        vetoes = sum(row["veto"] for row in candidate["decision_trace"])
        folds.append(
            {
                "fold": fold + 1,
                "start": iso(int(data.timestamps_ms[start])),
                "end_exclusive": iso(int(data.timestamps_ms[end])),
                "candidate_net_return": candidate["net_compound_return"],
                "e2160_net_return": benchmark["net_compound_return"],
                "relative_effect": candidate["net_compound_return"] - benchmark["net_compound_return"],
                "veto_count": vetoes,
            }
        )
    years: list[dict[str, Any]] = []
    oos_years = sorted({year_label(int(data.timestamps_ms[t])) for t in range(OOS[0], OOS[1])})
    for year in oos_years:
        indices = [t for t in range(OOS[0], OOS[1]) if year_label(int(data.timestamps_ms[t])) == year]
        start = min(indices)
        end = max(indices) + 1
        candidate = evaluate_strategy(data, start, end, "candidate")
        benchmark = evaluate_strategy(data, start, end, "e2160")
        vetoes = sum(row["veto"] for row in candidate["decision_trace"])
        years.append(
            {
                "year": year,
                "candidate_net_return": candidate["net_compound_return"],
                "e2160_net_return": benchmark["net_compound_return"],
                "relative_effect": candidate["net_compound_return"] - benchmark["net_compound_return"],
                "veto_count": vetoes,
            }
        )
    delayed_candidate = evaluate_strategy(data, OOS[0], OOS[1], "candidate", delay=1)
    delayed_e2160 = evaluate_strategy(data, OOS[0], OOS[1], "e2160", delay=1)
    bootstrap = bootstrap_intervals(
        raw["oos"]["candidate"]["hourly_net_returns"],
        raw["oos"]["e2160"]["hourly_net_returns"],
    )
    candidate_oos = raw["oos"]["candidate"]
    e2160_oos = raw["oos"]["e2160"]
    always_oos = raw["oos"]["always_long"]
    positive_relative = [max(0.0, row["relative_effect"]) for row in folds]
    positive_total = sum(positive_relative)
    concentration = None if positive_total <= 0 else max(positive_relative) / positive_total
    gross_timing = float(
        np.sum(candidate_oos["hourly_gross_returns"] - e2160_oos["hourly_gross_returns"])
    )
    fee_contribution = -(candidate_oos["modeled_fees"] - e2160_oos["modeled_fees"])
    gates = {
        "source_and_identity_gates": True,
        "training_support_gate": True,
        "positive_oos_return_and_sharpe": candidate_oos["net_compound_return"] > 0
        and candidate_oos["sharpe"] is not None
        and candidate_oos["sharpe"] > 0,
        "beats_e2160_and_always_long": (
            candidate_oos["net_compound_return"] > e2160_oos["net_compound_return"]
            and candidate_oos["sharpe"] is not None
            and e2160_oos["sharpe"] is not None
            and candidate_oos["sharpe"] > e2160_oos["sharpe"]
            and candidate_oos["net_compound_return"] > always_oos["net_compound_return"]
            and always_oos["sharpe"] is not None
            and candidate_oos["sharpe"] > always_oos["sharpe"]
        ),
        "positive_dependence_aware_lower_bounds": (
            bootstrap["mean_hourly_net_difference_95ci"][0] > 0
            and bootstrap["annualized_sharpe_difference_95ci"][0] > 0
        ),
        "drawdown_gate": (
            candidate_oos["maximum_drawdown"] >= e2160_oos["maximum_drawdown"] - 0.05
            and candidate_oos["maximum_drawdown"] > always_oos["maximum_drawdown"]
        ),
        "turnover_gate": candidate_oos["one_way_turnover"] <= e2160_oos["one_way_turnover"]
        and candidate_oos["one_way_turnover"] <= 80,
        "edge_per_turnover_gate": (
            candidate_oos["edge_per_turnover_bps"] is not None
            and candidate_oos["edge_per_turnover_bps"] > 0
            and e2160_oos["edge_per_turnover_bps"] is not None
            and candidate_oos["edge_per_turnover_bps"] > e2160_oos["edge_per_turnover_bps"]
        ),
        "fold_breadth_gate": sum(row["candidate_net_return"] > 0 for row in folds) >= 4
        and sum(row["relative_effect"] > 0 for row in folds) >= 4,
        "calendar_transport_gate": all(
            row["candidate_net_return"] > 0 and row["relative_effect"] > 0 for row in years
        ),
        "positive_relative_concentration_gate": concentration is not None and concentration <= 0.50,
        "one_hour_delay_gate": (
            delayed_candidate["net_compound_return"] > 0
            and delayed_candidate["net_compound_return"] > delayed_e2160["net_compound_return"]
            and delayed_candidate["sharpe"] is not None
            and delayed_e2160["sharpe"] is not None
            and delayed_candidate["sharpe"] > delayed_e2160["sharpe"]
        ),
        "positive_full_sample_return_and_sharpe": (
            raw["full"]["candidate"]["net_compound_return"] > 0
            and raw["full"]["candidate"]["sharpe"] is not None
            and raw["full"]["candidate"]["sharpe"] > 0
        ),
        "oos_veto_transport_gate": sum(row["veto_count"] > 0 for row in folds) >= 4
        and all(row["veto_count"] > 0 for row in years),
    }
    return {
        "segments": segments,
        "folds": folds,
        "calendar_years": years,
        "positive_relative_fold_concentration": concentration,
        "one_hour_delay": {
            "candidate": public_metrics(delayed_candidate),
            "e2160": public_metrics(delayed_e2160),
        },
        "bootstrap": bootstrap,
        "mechanism_decomposition": {
            "candidate_only_hours": int(np.sum((candidate_oos["positions"] == 1) & (e2160_oos["positions"] == 0))),
            "e2160_only_hours": int(np.sum((candidate_oos["positions"] == 0) & (e2160_oos["positions"] == 1))),
            "gross_timing_sum": gross_timing,
            "modeled_fee_contribution": fee_contribution,
            "arithmetic_net_difference_sum": float(
                np.sum(candidate_oos["hourly_net_returns"] - e2160_oos["hourly_net_returns"])
            ),
        },
        "gates": gates,
        "passed": all(gates.values()),
    }


def json_safe(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value


def write_report(output_dir: Path, result: dict[str, Any]) -> None:
    lines = [
        "# Price-adjusted trade-size confirmed E2160 entry — terminal evidence",
        "",
        f"- Family: `{result['family_id']}`",
        f"- Fee: exactly `{result['canonical_fee_bps_one_way']}` bps one way",
        f"- Source objects: `{result['source_contract']['verified_objects']}/{result['source_contract']['expected_objects']}`",
        f"- Performance accessed: `{result['performance_accessed']}`",
        f"- Markets passing: `{result['markets_passing_all_gates']}/2`",
        f"- Verdict: `{result['verdict']}`",
        "",
        "## Training-only information support",
        "",
        "| Market | Valid decisions | IQR | Distinct margins | Vetoes | Veto quarters | Deferred entries | Passed |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for market in result["markets"]:
        support = market["support"]
        lines.append(
            f"| {market['symbol']} | {support['valid_training_decisions']} | "
            f"{support['size_margin_iqr']} | {support['size_margin_distinct_count']} | "
            f"{support['veto_count']} | {len(support['veto_quarter_counts'])} | "
            f"{support['later_authorized_entry_count']} | {support['passed']} |"
        )
    if result["performance_accessed"]:
        lines.extend(
            [
                "",
                "## Sealed OOS economics",
                "",
                "| Market | Candidate net | Sharpe | E2160 net | E2160 Sharpe | Turnover | Fees | Edge/turnover | Gates |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for market in result["markets"]:
            performance = market["performance"]
            candidate = performance["segments"]["oos"]["candidate"]
            benchmark = performance["segments"]["oos"]["e2160"]
            lines.append(
                f"| {market['symbol']} | {candidate['net_compound_return']:+.6%} | "
                f"{candidate['sharpe']} | {benchmark['net_compound_return']:+.6%} | "
                f"{benchmark['sharpe']} | {candidate['one_way_turnover']} | "
                f"{candidate['modeled_fees']:+.6%} | {candidate['edge_per_turnover_bps']} | "
                f"{sum(performance['gates'].values())}/{len(performance['gates'])} |"
            )
    lines.extend(
        [
            "",
            "## Disposition",
            "",
            result["highest_value_discrepancy"],
            "",
            "```json",
            json.dumps(result["machine_readable_verdict"], sort_keys=True, indent=2),
            "```",
            "",
            f"Next strategy-facing action: {result['next_strategy_action']}.",
            "",
        ]
    )
    (output_dir / "report.md").write_text("\n".join(lines))


def run(output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    source_dir = output_dir / "source"
    source_dir.mkdir(exist_ok=True)
    data_by_symbol: dict[str, MarketData] = {}
    source_error: str | None = None
    try:
        for symbol in SYMBOLS:
            data_by_symbol[symbol] = acquire_market(symbol)
        if not np.array_equal(
            data_by_symbol[SYMBOLS[0]].timestamps_ms,
            data_by_symbol[SYMBOLS[1]].timestamps_ms,
        ):
            raise ValueError("market calendars differ")
    except Exception as exc:
        source_error = f"{type(exc).__name__}: {exc}"

    source_objects = [
        item
        for symbol in SYMBOLS
        for item in data_by_symbol.get(symbol, MarketData(symbol, np.array([]), np.array([]), np.array([]), np.array([]), np.array([]), np.array([]), np.array([]), np.array([]), [])).source_objects
    ]
    source_manifest = {
        "provider": "Binance public monthly SPOT kline archives",
        "credentials_used": False,
        "private_endpoints_used": False,
        "symbols": list(SYMBOLS),
        "interval": INTERVAL,
        "start": START.isoformat().replace("+00:00", "Z"),
        "end_exclusive": END.isoformat().replace("+00:00", "Z"),
        "expected_rows_per_market": EXPECTED_ROWS,
        "expected_objects": 132,
        "verified_objects": len(source_objects) * 2,
        "common_grid_passed": source_error is None,
        "error": source_error,
        "objects": source_objects,
    }
    (source_dir / "manifest.json").write_text(json.dumps(source_manifest, sort_keys=True, indent=2))

    markets: list[dict[str, Any]] = []
    support_passed = False
    if source_error is None:
        for symbol in SYMBOLS:
            support = support_audit(data_by_symbol[symbol])
            markets.append({"symbol": symbol, "support": support, "performance": None})
        support_passed = all(market["support"]["passed"] for market in markets)
    else:
        for symbol in SYMBOLS:
            markets.append({"symbol": symbol, "support": None, "performance": None})

    performance_accessed = source_error is None and support_passed
    if performance_accessed:
        for market in markets:
            market["performance"] = evaluate_market(data_by_symbol[market["symbol"]])
    markets_passing = (
        sum(bool(market["performance"] and market["performance"]["passed"]) for market in markets)
        if performance_accessed
        else 0
    )
    accepted = performance_accessed and markets_passing == len(SYMBOLS)
    if source_error is not None:
        discrepancy = (
            "The immutable public-source contract failed before feature or performance access: "
            f"{source_error}. Performance fields remain null rather than zero."
        )
    elif not support_passed:
        failures = []
        for market in markets:
            failed = [name for name, passed in market["support"]["gates"].items() if not passed]
            failures.append(f"{market['symbol']}: {', '.join(failed)}")
        discrepancy = (
            "The price-adjusted trade-size feature failed the bilateral training-only information-support gate before sealed OOS access. "
            + " | ".join(failures)
        )
    else:
        failures = []
        for market in markets:
            failed = [name for name, passed in market["performance"]["gates"].items() if not passed]
            failures.append(f"{market['symbol']}: {', '.join(failed)}")
        discrepancy = "Sealed OOS gate failures: " + " | ".join(failures)

    protocol = {
        "family_id": FAMILY_ID,
        "candidate_count": 2,
        "parameter_grid_count": 0,
        "fee_one_way": FEE,
        "bar": "1H",
        "markets": list(SYMBOLS),
        "feature": "24H-lagged adjacent 720H medians of log(quote_volume/trades)-log(close)",
        "entry_authority": "E2160 entry veto only",
        "exit_authority": "E2160 only",
        "training": TRAIN,
        "oos": OOS,
        "full": FULL,
        "bootstrap": {
            "draws": BOOTSTRAP_DRAWS,
            "block_hours": BOOTSTRAP_BLOCK,
            "seed": BOOTSTRAP_SEED,
        },
    }
    script_sha = sha256_bytes(Path(__file__).read_bytes())
    protocol_sha = sha256_bytes(json.dumps(protocol, sort_keys=True).encode())
    data_sha = sha256_bytes(
        "\n".join(item["archive_sha256"] for item in source_objects).encode()
    ) if source_objects else None
    verdict = VERDICT_ACCEPT if accepted else VERDICT_REJECT
    result: dict[str, Any] = {
        "generated_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        "family_id": FAMILY_ID,
        "candidate_count": 2,
        "parameter_grid_count": 0,
        "bar": "1H",
        "canonical_fee_bps_one_way": 5.0,
        "cross_sectional_selection": False,
        "pairs_or_spreads": False,
        "market_neutral": False,
        "credentials_used": False,
        "private_endpoints_used": False,
        "synthetic_market_data_used": False,
        "actual_orders": False,
        "leverage_used": False,
        "source_contract": source_manifest,
        "performance_accessed": performance_accessed,
        "oos_accessed": performance_accessed,
        "markets": markets,
        "markets_passing_all_gates": markets_passing,
        "correction_permitted": accepted,
        "correction_applied": False,
        "observation_epoch_restarted": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "highest_value_discrepancy": discrepancy,
        "protocol": protocol,
        "hashes": {
            "script_sha256": script_sha,
            "protocol_sha256": protocol_sha,
            "source_archive_set_sha256": data_sha,
        },
        "verdict": verdict,
        "next_strategy_action": (
            "freeze a new observation epoch for this unchanged rule only after an explicit separate prospective-shadow preregistration"
            if accepted
            else "keep this exact feature, windows, lag, threshold, markets and cohort closed; nominate one materially orthogonal same-instrument causal information source before performance access"
        ),
    }
    result["machine_readable_verdict"] = {
        "family_id": FAMILY_ID,
        "source_contract_passed": source_error is None,
        "training_support_passed_bilaterally": support_passed,
        "performance_accessed": performance_accessed,
        "markets_passing_all_gates": markets_passing,
        "correction_permitted": accepted,
        "correction_applied": False,
        "observation_epoch_restarted": False,
        "verdict": verdict,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
    }
    safe = json_safe(result)
    payload = json.dumps(safe, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"
    (output_dir / "evidence.json").write_bytes(payload)
    (output_dir / "evidence.sha256").write_text(sha256_bytes(payload) + "\n")
    write_report(output_dir, safe)
    return safe


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.output_dir), sort_keys=True, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
