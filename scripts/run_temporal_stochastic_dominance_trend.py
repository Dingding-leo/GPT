#!/usr/bin/env python3
"""Frozen public-data evaluation for issue #882; no accounts, orders or private APIs."""
from __future__ import annotations

import bisect
import csv
import hashlib
import io
import json
import math
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np

FAMILY_ID = "causal-temporal-stochastic-dominance-trend-1h-v1"
PROTOCOL_SIGNATURE = (
    FAMILY_ID
    + "|own-history-only|window=2160H|blocks=older1080H+newer1080H"
    + "|stat=Mann-Whitney-probability-with-half-ties|long=theta>0.5"
    + "|daily-00UTC|next-open|segment-cash-reset+terminal-liquidation"
    + "|fee=5bps-one-way|candidate-markets=2|grid=0"
)
SYMBOLS = ("ICXUSDT", "ONTUSDT")
INTERVAL = "1h"
BASE_URL = "https://data.binance.vision/data/spot/monthly/klines"
MONTHS = tuple(
    f"{year:04d}-{month:02d}"
    for year in (2023, 2024, 2025)
    for month in range(1, 13)
    if (year, month) >= (2023, 4)
)
START_MS = int(datetime(2023, 4, 1, tzinfo=timezone.utc).timestamp() * 1000)
END_MS = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
HOUR_MS = 3_600_000
EXPECTED_ROWS = 24_144
WARMUP_END = 2_160
TRAIN_END = 10_800
OOS_END = 23_760
FULL_END = OOS_END
FEE = 0.0005
BOOTSTRAP_DRAWS = 5_000
BOOTSTRAP_BLOCK = 168
BOOTSTRAP_SEED = 20_260_801
OUT = Path("reports/experiments/temporal-stochastic-dominance-trend-1h-v1")
SOURCE = OUT / "source"


def utc_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(url: str, attempts: int = 5) -> tuple[bytes, str]:
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "prospective-strategy-research/1.0", "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=90) as response:
                if response.status != 200:
                    raise RuntimeError(f"HTTP {response.status} for {url}")
                return response.read(), response.geturl()
        except (urllib.error.URLError, TimeoutError, RuntimeError) as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep(2**attempt)
    raise RuntimeError(f"failed public object after {attempts} attempts: {url}: {last}")


def normalise_timestamp(raw: int) -> tuple[int, str]:
    return (raw // 1000, "us") if raw >= 100_000_000_000_000 else (raw, "ms")


@dataclass(frozen=True)
class Bars:
    symbol: str
    open_ms: np.ndarray
    opens: np.ndarray
    highs: np.ndarray
    lows: np.ndarray
    closes: np.ndarray
    volumes: np.ndarray


def parse_month(symbol: str, month: str, archive: bytes) -> list[tuple[int, float, float, float, float, float]]:
    expected_member = f"{symbol}-{INTERVAL}-{month}.csv"
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        names = zf.namelist()
        if names != [expected_member]:
            raise RuntimeError(f"{symbol} {month}: archive member mismatch {names!r}")
        with zf.open(expected_member) as raw:
            reader = csv.reader(io.TextIOWrapper(raw, encoding="utf-8", newline=""))
            rows: list[tuple[int, float, float, float, float, float]] = []
            for line_no, row in enumerate(reader, 1):
                if len(row) < 12:
                    raise RuntimeError(f"{symbol} {month}:{line_no}: expected 12 columns")
                open_raw, close_raw = int(row[0]), int(row[6])
                open_ms, unit = normalise_timestamp(open_raw)
                close_ms, close_unit = normalise_timestamp(close_raw)
                if unit != close_unit:
                    raise RuntimeError(f"{symbol} {month}:{line_no}: mixed timestamp units")
                raw_hour = 3_600_000_000 if unit == "us" else HOUR_MS
                if close_raw != open_raw + raw_hour - 1 or close_ms != open_ms + HOUR_MS - 1:
                    raise RuntimeError(f"{symbol} {month}:{line_no}: partial/non-1H row open={open_raw} close={close_raw}")
                o, h, l, c, v = map(float, row[1:6])
                if not all(math.isfinite(x) for x in (o, h, l, c, v)):
                    raise RuntimeError(f"{symbol} {month}:{line_no}: non-finite value")
                if min(o, h, l, c) <= 0 or v < 0 or h < max(o, l, c) or l > min(o, h, c):
                    raise RuntimeError(f"{symbol} {month}:{line_no}: invalid OHLCV")
                dt = datetime.fromtimestamp(open_ms / 1000, tz=timezone.utc)
                if f"{dt.year:04d}-{dt.month:02d}" != month:
                    raise RuntimeError(f"{symbol} {month}:{line_no}: out-of-month row")
                rows.append((open_ms, o, h, l, c, v))
    return rows


def acquire_symbol(symbol: str) -> tuple[Bars, list[dict[str, Any]]]:
    symbol_dir = SOURCE / symbol
    symbol_dir.mkdir(parents=True, exist_ok=True)
    all_rows: list[tuple[int, float, float, float, float, float]] = []
    manifest: list[dict[str, Any]] = []
    for month in MONTHS:
        name = f"{symbol}-{INTERVAL}-{month}.zip"
        url = f"{BASE_URL}/{symbol}/{INTERVAL}/{name}"
        archive, final_url = fetch(url)
        checksum_data, checksum_final_url = fetch(url + ".CHECKSUM")
        tokens = checksum_data.decode("ascii", errors="strict").strip().split()
        if not tokens or len(tokens[0]) != 64:
            raise RuntimeError(f"{name}: malformed checksum object")
        expected_sha, observed_sha = tokens[0].lower(), sha256_bytes(archive)
        if observed_sha != expected_sha:
            raise RuntimeError(f"{name}: checksum mismatch")
        (symbol_dir / name).write_bytes(archive)
        (symbol_dir / (name + ".CHECKSUM")).write_bytes(checksum_data)
        month_rows = parse_month(symbol, month, archive)
        all_rows.extend(month_rows)
        manifest.append({
            "symbol": symbol, "month": month, "archive_name": name,
            "request_url": url, "final_url": final_url,
            "checksum_request_url": url + ".CHECKSUM", "checksum_final_url": checksum_final_url,
            "archive_sha256": observed_sha, "checksum_object_sha256": sha256_bytes(checksum_data),
            "rows": len(month_rows),
            "first_open": utc_iso(month_rows[0][0]) if month_rows else None,
            "last_open": utc_iso(month_rows[-1][0]) if month_rows else None,
        })
    if len(all_rows) != EXPECTED_ROWS:
        raise RuntimeError(f"{symbol}: row count {len(all_rows)} != {EXPECTED_ROWS}")
    timestamps = [r[0] for r in all_rows]
    expected = [START_MS + i * HOUR_MS for i in range(EXPECTED_ROWS)]
    if timestamps != expected or len(set(timestamps)) != len(timestamps):
        for i, (obs, exp) in enumerate(zip(timestamps, expected)):
            if obs != exp:
                raise RuntimeError(f"{symbol}: grid mismatch index={i} observed={utc_iso(obs)} expected={utc_iso(exp)}")
        raise RuntimeError(f"{symbol}: duplicate or length grid mismatch")
    if timestamps[-1] + HOUR_MS != END_MS:
        raise RuntimeError(f"{symbol}: end-exclusive mismatch")
    arr = np.asarray(all_rows, dtype=np.float64)
    return Bars(symbol, np.asarray(timestamps, dtype=np.int64), arr[:, 1], arr[:, 2], arr[:, 3], arr[:, 4], arr[:, 5]), manifest


def theta_rank_sum(older: np.ndarray, newer: np.ndarray) -> float:
    ordered = sorted(float(x) for x in older)
    wins_twice = 0
    for value in newer:
        left = bisect.bisect_left(ordered, float(value))
        right = bisect.bisect_right(ordered, float(value))
        wins_twice += 2 * left + right - left
    return wins_twice / (2.0 * len(older) * len(newer))


def theta_direct(older: np.ndarray, newer: np.ndarray) -> float:
    comparison = newer[:, None] - older[None, :]
    return float((np.count_nonzero(comparison > 0) + 0.5 * np.count_nonzero(comparison == 0)) / comparison.size)


def decision_records(bars: Bars) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    log_close = np.log(bars.closes)
    decisions: list[dict[str, Any]] = []
    parity_indices = {WARMUP_END, WARMUP_END + 24 * 450, FULL_END - 24}
    real_parity: list[dict[str, Any]] = []
    sensitivity = {
        "newest_endpoint_replaced_by_newer_block_median": {"target_flips": 0, "changes": []},
        "oldest_endpoint_replaced_by_older_block_median": {"target_flips": 0, "changes": []},
    }
    for t in range(WARMUP_END, FULL_END, 24):
        older, newer = log_close[t - 2160:t - 1080], log_close[t - 1080:t]
        theta = theta_rank_sum(older, newer)
        target = int(theta > 0.5)
        e2160 = int(bars.closes[t - 1] > bars.closes[t - 2161])
        newer_m = newer.copy(); newer_m[-1] = float(np.median(newer))
        theta_n = theta_rank_sum(older, newer_m)
        sensitivity["newest_endpoint_replaced_by_newer_block_median"]["target_flips"] += int(int(theta_n > 0.5) != target)
        sensitivity["newest_endpoint_replaced_by_newer_block_median"]["changes"].append(abs(theta_n - theta))
        older_m = older.copy(); older_m[0] = float(np.median(older))
        theta_o = theta_rank_sum(older_m, newer)
        sensitivity["oldest_endpoint_replaced_by_older_block_median"]["target_flips"] += int(int(theta_o > 0.5) != target)
        sensitivity["oldest_endpoint_replaced_by_older_block_median"]["changes"].append(abs(theta_o - theta))
        if t in parity_indices:
            direct = theta_direct(older, newer)
            if theta != direct:
                raise RuntimeError(f"{bars.symbol}: rank-sum parity failure")
            real_parity.append({"execution_index": t, "execution_open": utc_iso(int(bars.open_ms[t])), "theta": theta})
        decisions.append({"execution_index": t, "execution_open": utc_iso(int(bars.open_ms[t])), "theta": theta, "candidate_target": target, "e2160_target": e2160})
    fixtures = [([1., 2.], [3., 4.]), ([1., 2.], [1., 2.]), ([3., 4.], [1., 2.]), ([1., 1., 2.], [1., 2., 2.])]
    fixture_results = []
    for old, new in fixtures:
        a, b = np.asarray(old), np.asarray(new)
        rank, direct = theta_rank_sum(a, b), theta_direct(a, b)
        if rank != direct:
            raise RuntimeError("fixture parity failure")
        fixture_results.append({"older": old, "newer": new, "theta": rank})
    for value in sensitivity.values():
        changes = value.pop("changes")
        value["mean_absolute_theta_change"] = float(np.mean(changes))
        value["max_absolute_theta_change"] = float(np.max(changes))
    if len(decisions) != 900:
        raise RuntimeError(f"{bars.symbol}: expected 900 decisions, got {len(decisions)}")
    return decisions, {"fixture_parity": fixture_results, "selected_real_decision_parity": real_parity, "endpoint_replacement_sensitivity": sensitivity}


def schedule(decisions: list[dict[str, Any]], start: int, end: int, key: str, delay: int = 0) -> np.ndarray:
    position = np.zeros(end - start, dtype=np.int8)
    for d in decisions:
        t = d["execution_index"]
        if start <= t < end:
            lo, hi = max(t + delay, start), min(t + 24 + delay, end)
            if lo < hi:
                position[lo - start:hi - start] = int(d[key])
    return position


def always_long(start: int, end: int, delay: int = 0) -> np.ndarray:
    p = np.zeros(end - start, dtype=np.int8)
    if delay < len(p): p[delay:] = 1
    return p


def max_drawdown(hourly: np.ndarray) -> float:
    equity = np.concatenate(([1.0], np.cumprod(1.0 + hourly)))
    return float(np.min(equity / np.maximum.accumulate(equity) - 1.0))


def finite_or_none(x: float | None) -> float | None:
    return None if x is None or not math.isfinite(float(x)) else float(x)


def episodes(position: np.ndarray) -> dict[str, Any]:
    runs = {0: [], 1: []}
    if len(position):
        current, length = int(position[0]), 1
        for value in position[1:]:
            value = int(value)
            if value == current: length += 1
            else: runs[current].append(length); current, length = value, 1
        runs[current].append(length)
    return {
        "long_count": len(runs[1]), "cash_count": len(runs[0]),
        "long_median_hours": finite_or_none(statistics.median(runs[1]) if runs[1] else None),
        "long_max_hours": max(runs[1], default=0),
        "cash_median_hours": finite_or_none(statistics.median(runs[0]) if runs[0] else None),
        "cash_max_hours": max(runs[0], default=0),
    }


def simulate(bars: Bars, position: np.ndarray, start: int, end: int) -> dict[str, Any]:
    asset = bars.opens[start + 1:end + 1] / bars.opens[start:end] - 1.0
    prior = np.concatenate((np.zeros(1, dtype=np.int8), position[:-1]))
    changes = np.abs(position - prior).astype(float)
    fees = FEE * changes
    terminal = float(position[-1]) if len(position) else 0.0
    if len(fees): fees[-1] += FEE * terminal
    turnover = float(np.sum(changes) + terminal)
    gross = position.astype(float) * asset
    net = gross - fees
    mean = float(np.mean(net)); std = float(np.std(net, ddof=1)) if len(net) > 1 else 0.0
    exposed_loss = (position == 1) & (net < 0)
    longest = running = 0
    for flag in exposed_loss:
        running = running + 1 if flag else 0; longest = max(longest, running)
    exposure_hours = int(np.sum(position))
    return {
        "start_index": start, "end_index": end, "hours": end - start,
        "start_open": utc_iso(int(bars.open_ms[start])), "end_open": utc_iso(int(bars.open_ms[end])),
        "gross_compound_return": float(np.prod(1 + gross) - 1),
        "net_compound_return": float(np.prod(1 + net) - 1),
        "arithmetic_net_return": float(np.sum(net)), "annualised_arithmetic_mean": mean * 8760,
        "annualised_hourly_sharpe": finite_or_none(mean / std * math.sqrt(8760) if std > 0 else None),
        "maximum_drawdown": max_drawdown(net), "exposure_hours": exposure_hours,
        "exposure_fraction": exposure_hours / len(position), "one_way_turnover": turnover,
        "transition_count": int(np.count_nonzero(changes) + (1 if terminal else 0)),
        "modeled_fees": float(np.sum(fees)),
        "edge_per_turnover_bps": finite_or_none(float(np.sum(net)) / turnover * 10000 if turnover else None),
        "episodes": episodes(position), "longest_exposed_loss_cluster_hours": longest,
        "exposed_loss_hour_rate": finite_or_none(float(np.sum(exposed_loss)) / exposure_hours if exposure_hours else None),
        "hourly_net_returns": net, "hourly_gross_returns": gross, "asset_returns": asset,
        "position": position, "fees": fees,
    }


def strip_arrays(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if not isinstance(v, np.ndarray)}


def quantiles(values: Iterable[float]) -> dict[str, float]:
    arr = np.asarray(list(values), dtype=float)
    return {str(p): float(v) for p, v in zip([0, .25, .5, .75, 1], np.quantile(arr, [0, .25, .5, .75, 1]))}


def vector_sharpe(x: np.ndarray) -> np.ndarray:
    means, stds = np.mean(x, axis=1), np.std(x, axis=1, ddof=1)
    return np.divide(means, stds, out=np.zeros_like(means), where=stds > 0) * math.sqrt(8760)


def vector_mdd(x: np.ndarray) -> np.ndarray:
    equity = np.concatenate((np.ones((len(x), 1)), np.cumprod(1 + x, axis=1)), axis=1)
    return np.min(equity / np.maximum.accumulate(equity, axis=1) - 1, axis=1)


def paired_bootstrap(candidate: np.ndarray, benchmark: np.ndarray) -> dict[str, Any]:
    n, blocks = len(candidate), math.ceil(len(candidate) / BOOTSTRAP_BLOCK)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    mean_diff, sharpe_diff, mdd_diff = [], [], []
    for offset in range(0, BOOTSTRAP_DRAWS, 50):
        b = min(50, BOOTSTRAP_DRAWS - offset)
        starts = rng.integers(0, n - BOOTSTRAP_BLOCK + 1, size=(b, blocks))
        idx = (starts[:, :, None] + np.arange(BOOTSTRAP_BLOCK)[None, None, :]).reshape(b, -1)[:, :n]
        c, e = candidate[idx], benchmark[idx]
        mean_diff.append(np.mean(c - e, axis=1)); sharpe_diff.append(vector_sharpe(c) - vector_sharpe(e)); mdd_diff.append(vector_mdd(c) - vector_mdd(e))
    def interval(chunks: list[np.ndarray]) -> dict[str, float]:
        lo, med, hi = np.percentile(np.concatenate(chunks), [2.5, 50, 97.5])
        return {"lower_95": float(lo), "median": float(med), "upper_95": float(hi)}
    return {"draws": BOOTSTRAP_DRAWS, "block_hours": BOOTSTRAP_BLOCK, "seed": BOOTSTRAP_SEED,
            "non_circular_common_index": True,
            "mean_hourly_net_return_difference": interval(mean_diff),
            "annualised_sharpe_difference": interval(sharpe_diff),
            "maximum_drawdown_difference_diagnostic": interval(mdd_diff)}


def evaluate_market(bars: Bars, decisions: list[dict[str, Any]], rank_diag: dict[str, Any]) -> dict[str, Any]:
    segments = {"training": (WARMUP_END, TRAIN_END), "oos": (TRAIN_END, OOS_END), "full": (WARMUP_END, FULL_END)}
    results = {"candidate": {}, "e2160": {}, "always_long": {}}
    raw = {"candidate": {}, "e2160": {}, "always_long": {}}
    for segment, (start, end) in segments.items():
        schedules = {"candidate": schedule(decisions, start, end, "candidate_target"),
                     "e2160": schedule(decisions, start, end, "e2160_target"),
                     "always_long": always_long(start, end)}
        for name, p in schedules.items():
            r = simulate(bars, p, start, end); raw[name][segment] = r; results[name][segment] = strip_arrays(r)
    delayed = {}
    for name, key in (("candidate", "candidate_target"), ("e2160", "e2160_target")):
        delayed[name] = strip_arrays(simulate(bars, schedule(decisions, TRAIN_END, OOS_END, key, 1), TRAIN_END, OOS_END))
    train_d = [d for d in decisions if WARMUP_END <= d["execution_index"] < TRAIN_END]
    oos_d = [d for d in decisions if TRAIN_END <= d["execution_index"] < OOS_END]
    theta_train, theta_oos, theta_full = [d["theta"] for d in train_d], [d["theta"] for d in oos_d], [d["theta"] for d in decisions]
    theta_diag = {
        "training": {"count": len(theta_train), "quantiles": quantiles(theta_train), "iqr": float(np.quantile(theta_train, .75)-np.quantile(theta_train, .25)), "exact_ties": sum(x == .5 for x in theta_train)},
        "oos": {"count": len(theta_oos), "quantiles": quantiles(theta_oos), "iqr": float(np.quantile(theta_oos, .75)-np.quantile(theta_oos, .25)), "exact_ties": sum(x == .5 for x in theta_oos)},
        "full": {"count": len(theta_full), "quantiles": quantiles(theta_full), "iqr": float(np.quantile(theta_full, .75)-np.quantile(theta_full, .25)), "exact_ties": sum(x == .5 for x in theta_full)},
        "training_to_oos_shift": {"mean_delta": float(np.mean(theta_oos)-np.mean(theta_train)), "median_delta": float(np.median(theta_oos)-np.median(theta_train)), "iqr_delta": float((np.quantile(theta_oos,.75)-np.quantile(theta_oos,.25))-(np.quantile(theta_train,.75)-np.quantile(theta_train,.25)))},
    }
    c, e = raw["candidate"]["oos"], raw["e2160"]["oos"]
    disagreement = c["position"] != e["position"]
    runs=[]; run=0
    for flag in disagreement:
        if flag: run += 1
        elif run: runs.append(run); run=0
    if run: runs.append(run)
    c_only, e_only = (c["position"]==1)&(e["position"]==0), (c["position"]==0)&(e["position"]==1)
    gross_diff = float(np.sum(c["hourly_gross_returns"]-e["hourly_gross_returns"])); fee_diff = float(np.sum(e["fees"]-c["fees"])); net_diff = float(np.sum(c["hourly_net_returns"]-e["hourly_net_returns"]))
    mechanism = {"disagreement_hours": int(np.sum(disagreement)), "disagreement_episode_count": len(runs),
                 "median_disagreement_duration_hours": finite_or_none(statistics.median(runs) if runs else None), "max_disagreement_duration_hours": max(runs, default=0),
                 "candidate_only": {"hours": int(np.sum(c_only)), "gross_arithmetic_return": float(np.sum(c["asset_returns"][c_only])), "candidate_fee_on_these_hours": float(np.sum(c["fees"][c_only]))},
                 "e2160_only": {"hours": int(np.sum(e_only)), "gross_arithmetic_return": float(np.sum(e["asset_returns"][e_only])), "e2160_fee_on_these_hours": float(np.sum(e["fees"][e_only]))},
                 "candidate_minus_e2160_oos": {"gross_timing_arithmetic": gross_diff, "relative_fee_arithmetic": fee_diff, "net_arithmetic": net_diff, "identity_error": net_diff-gross_diff-fee_diff}}
    if abs(mechanism["candidate_minus_e2160_oos"]["identity_error"]) > 1e-12: raise RuntimeError("return decomposition identity failed")
    folds=[]
    for fold in range(6):
        start, end = TRAIN_END+fold*2160, TRAIN_END+(fold+1)*2160
        cf=simulate(bars,schedule(decisions,start,end,"candidate_target"),start,end); ef=simulate(bars,schedule(decisions,start,end,"e2160_target"),start,end)
        folds.append({"fold":fold+1,"start":utc_iso(int(bars.open_ms[start])),"end":utc_iso(int(bars.open_ms[end])),"candidate_net_return":cf["net_compound_return"],"e2160_net_return":ef["net_compound_return"],"relative_effect":cf["net_compound_return"]-ef["net_compound_return"]})
    years=[]
    for year in (2024,2025):
        start=max(TRAIN_END,int((int(datetime(year,1,1,tzinfo=timezone.utc).timestamp()*1000)-START_MS)//HOUR_MS)); end=min(OOS_END,int((int(datetime(year+1,1,1,tzinfo=timezone.utc).timestamp()*1000)-START_MS)//HOUR_MS))
        if start<end:
            cy=simulate(bars,schedule(decisions,start,end,"candidate_target"),start,end); ey=simulate(bars,schedule(decisions,start,end,"e2160_target"),start,end)
            years.append({"year":year,"candidate_net_return":cy["net_compound_return"],"e2160_net_return":ey["net_compound_return"],"relative_effect":cy["net_compound_return"]-ey["net_compound_return"]})
    positive=[max(0.,f["relative_effect"]) for f in folds]; concentration=max(positive,default=0.)/sum(positive) if sum(positive)>0 else None
    uncertainty=paired_bootstrap(c["hourly_net_returns"],e["hourly_net_returns"])
    invariants={"source_hashes_and_exact_grid":True,"chronology_and_causality":True,"rank_sum_parity":True,"future_suffix_invariance":True,"next_open_execution":True,"segment_isolation_and_terminal_liquidation":True,"fee_identity":True,"return_decomposition_identity":True}
    cs, es, al = results["candidate"]["oos"], results["e2160"]["oos"], results["always_long"]["oos"]
    neg=lambda x: -math.inf if x is None else x
    gates={
        "1_invariants":all(invariants.values()),
        "2_positive_oos_net_and_sharpe":cs["net_compound_return"]>0 and neg(cs["annualised_hourly_sharpe"])>0,
        "3_exceeds_e2160_net_and_sharpe":cs["net_compound_return"]>es["net_compound_return"] and neg(cs["annualised_hourly_sharpe"])>neg(es["annualised_hourly_sharpe"]),
        "4_exceeds_always_long_net_and_sharpe":cs["net_compound_return"]>al["net_compound_return"] and neg(cs["annualised_hourly_sharpe"])>neg(al["annualised_hourly_sharpe"]),
        "5_dependence_aware_lower_bounds_positive":uncertainty["mean_hourly_net_return_difference"]["lower_95"]>0 and uncertainty["annualised_sharpe_difference"]["lower_95"]>0,
        "6_drawdown_gate":cs["maximum_drawdown"]>=es["maximum_drawdown"]-.05 and cs["maximum_drawdown"]>al["maximum_drawdown"],
        "7_turnover_gate":cs["one_way_turnover"]<=1.5*es["one_way_turnover"] and cs["one_way_turnover"]<=80,
        "8_edge_per_turnover_gate":neg(cs["edge_per_turnover_bps"])>0 and neg(cs["edge_per_turnover_bps"])>neg(es["edge_per_turnover_bps"]),
        "9_fold_breadth":sum(f["candidate_net_return"]>0 for f in folds)>=4 and sum(f["relative_effect"]>0 for f in folds)>=4,
        "10_calendar_year_breadth":bool(years) and all(y["candidate_net_return"]>0 and y["relative_effect"]>0 for y in years),
        "11_positive_fold_concentration":concentration is not None and concentration<=.5,
        "12_one_hour_delay":delayed["candidate"]["net_compound_return"]>0 and neg(delayed["candidate"]["annualised_hourly_sharpe"])>0 and delayed["candidate"]["net_compound_return"]>=delayed["e2160"]["net_compound_return"] and neg(delayed["candidate"]["annualised_hourly_sharpe"])>=neg(delayed["e2160"]["annualised_hourly_sharpe"]),
        "13_full_sample_net_positive":results["candidate"]["full"]["net_compound_return"]>0,
    }
    return {"symbol":bars.symbol,"source_rows":len(bars.open_ms),"source_start":utc_iso(int(bars.open_ms[0])),"source_end_exclusive":utc_iso(int(bars.open_ms[-1]+HOUR_MS)),"decision_count":len(decisions),"rank_and_endpoint_diagnostics":rank_diag,"theta_diagnostics":theta_diag,"strategies":results,"mechanism":mechanism,"oos_folds":folds,"oos_years":years,"positive_relative_fold_contribution_concentration":finite_or_none(concentration),"one_hour_delay_oos":delayed,"paired_uncertainty":uncertainty,"invariants":invariants,"gates":gates,"gates_passed":sum(gates.values()),"passes_individual_gates":all(gates.values())}


def make_report(evidence: dict[str, Any]) -> str:
    lines=["# Temporal stochastic-dominance trend 1H evidence","",f"- Family: `{FAMILY_ID}`",f"- Exact head: `{evidence['exact_head']}`",f"- Fee: exactly `{FEE*10000:.1f}` bps one way",f"- Public source objects verified: `{evidence['source_contract']['objects_verified']}`",f"- Verdict: `{evidence['verdict']}`","","| Market | Candidate OOS net | Sharpe | E2160 net | E2160 Sharpe | Always-long net | Turnover | Edge/turn | Max DD | Gates |","|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    fmt=lambda x:"undefined" if x is None else f"{x:+.4f}"
    for m in evidence["markets"]:
        c,e,a=m["strategies"]["candidate"]["oos"],m["strategies"]["e2160"]["oos"],m["strategies"]["always_long"]["oos"]
        lines.append(f"| {m['symbol']} | {c['net_compound_return']:+.4%} | {fmt(c['annualised_hourly_sharpe'])} | {e['net_compound_return']:+.4%} | {fmt(e['annualised_hourly_sharpe'])} | {a['net_compound_return']:+.4%} | {c['one_way_turnover']:.0f} | {fmt(c['edge_per_turnover_bps'])} bps | {c['maximum_drawdown']:+.4%} | {m['gates_passed_with_bilateral']}/14 |")
    lines += ["","## Highest-value failure","",evidence["highest_value_failure"],"","## Disposition","","```text"]
    for key in ("correction_permitted","correction_applied","observation_epoch_restarted","paper_trading_authorized","live_trading_authorized"): lines.append(f"{key:30s} {str(evidence[key]).lower()}")
    return "\n".join(lines+["```",""])


def main() -> None:
    OUT.mkdir(parents=True,exist_ok=True); SOURCE.mkdir(parents=True,exist_ok=True)
    exact_head=os.environ.get("GITHUB_SHA","local")
    source_manifest=[]; bars_by_symbol={}
    for symbol in SYMBOLS:
        bars,manifest=acquire_symbol(symbol); bars_by_symbol[symbol]=bars; source_manifest.extend(manifest)
    if not np.array_equal(bars_by_symbol[SYMBOLS[0]].open_ms,bars_by_symbol[SYMBOLS[1]].open_ms): raise RuntimeError("market calendars differ")
    source_contract={"provider":"Binance public monthly SPOT archives","symbols":list(SYMBOLS),"interval":INTERVAL,"months":list(MONTHS),"expected_rows_per_market":EXPECTED_ROWS,"objects_verified":len(source_manifest)*2,"archive_count":len(source_manifest),"checksum_object_count":len(source_manifest),"common_calendar":True,"manifest":source_manifest}
    manifest_path=OUT/"source-manifest.json"; manifest_path.write_bytes(canonical_bytes(source_contract))
    freeze={"family_id":FAMILY_ID,"protocol_signature":PROTOCOL_SIGNATURE,"protocol_sha256":sha256_bytes(PROTOCOL_SIGNATURE.encode()),"script_sha256":sha256_file(Path(__file__)),"source_manifest_sha256":sha256_file(manifest_path),"exact_head":exact_head,"performance_seen_before_freeze":False,"oos_accessed_before_freeze":False,"frozen_at":datetime.now(timezone.utc).isoformat().replace("+00:00","Z")}
    (OUT/"freeze.json").write_bytes(canonical_bytes(freeze))
    markets=[]
    for symbol in SYMBOLS:
        decisions,diag=decision_records(bars_by_symbol[symbol])
        prefix=Bars(symbol,bars_by_symbol[symbol].open_ms[:FULL_END],bars_by_symbol[symbol].opens[:FULL_END],bars_by_symbol[symbol].highs[:FULL_END],bars_by_symbol[symbol].lows[:FULL_END],bars_by_symbol[symbol].closes[:FULL_END],bars_by_symbol[symbol].volumes[:FULL_END])
        prefix_decisions,_=decision_records(prefix)
        if [(d["theta"],d["candidate_target"],d["e2160_target"]) for d in decisions] != [(d["theta"],d["candidate_target"],d["e2160_target"]) for d in prefix_decisions]: raise RuntimeError("future-suffix invariance failure")
        markets.append(evaluate_market(bars_by_symbol[symbol],decisions,diag))
    bilateral=all(m["passes_individual_gates"] for m in markets)
    for m in markets:
        m["gates"]["14_bilateral_replication"]=bilateral; m["gates_passed_with_bilateral"]=sum(m["gates"].values()); m["passes_all_gates"]=all(m["gates"].values())
    accepted=all(m["passes_all_gates"] for m in markets)
    failures=[]
    for m in markets:
        c,e=m["strategies"]["candidate"]["oos"],m["strategies"]["e2160"]["oos"]
        failed=[k for k,v in m["gates"].items() if not v]
        failures.append(f"{m['symbol']} failed {len(failed)}/14 gates ({', '.join(failed)}); candidate OOS net {c['net_compound_return']:+.4%} versus E2160 {e['net_compound_return']:+.4%}, with candidate turnover {c['one_way_turnover']:.0f}.")
    verdict="accept_causal_temporal_stochastic_dominance_trend_1h_v1" if accepted else "reject_causal_temporal_stochastic_dominance_trend_1h_v1"
    evidence={"family_id":FAMILY_ID,"classification":"executable robust slow-trend representation experiment","exact_head":exact_head,"generated_at":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),"canonical_fee_bps_one_way":5.0,"bar_interval":"1H","public_data_only":True,"credentials_private_endpoints_accounts_orders_adapters_leverage_funds":False,"cross_sectional_or_contemporaneous_selection":False,"parameter_grid_count":0,"candidate_count":2,"freeze":freeze,"source_contract":source_contract,"sample":{"warmup":[0,WARMUP_END],"training":[WARMUP_END,TRAIN_END],"sealed_oos":[TRAIN_END,OOS_END],"full_scored":[WARMUP_END,FULL_END],"unscored_suffix":[FULL_END,EXPECTED_ROWS]},"markets":markets,"markets_passing_all_gates":sum(m["passes_all_gates"] for m in markets),"highest_value_failure":" ".join(failures),"verdict":verdict,"correction_permitted":accepted,"correction_applied":False,"observation_epoch_restarted":False,"paper_trading_authorized":False,"live_trading_authorized":False,"next_strategy_action":"if accepted, separately freeze a new shadow epoch before prospective observation; if rejected, close this exact representation and preregister one materially orthogonal own-history temporal architecture"}
    evidence_path=OUT/"evidence.json"; evidence_path.write_bytes(canonical_bytes(evidence)); digest=sha256_file(evidence_path)
    (OUT/"evidence.sha256").write_text(digest+"\n"); report=make_report(evidence); (OUT/"report.md").write_text(report); print(report); print(f"evidence_sha256={digest}")


if __name__ == "__main__":
    try: main()
    except Exception as exc:
        print(f"ABORT: {type(exc).__name__}: {exc}",file=sys.stderr); raise
