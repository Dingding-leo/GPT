#!/usr/bin/env python3
"""Frozen causal week-phase deseasonalized 2,160H trend experiment.

Public confirmed OKX SPOT 1H candles only. No credentials, accounts, orders,
leverage, adapters, synthetic observations, cross-sectional selection, or OOS refit.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

FAMILY_ID = "causal-week-phase-deseasonalized-endpoint-trend-1h-v1"
REJECT_VERDICT = "reject_causal_week_phase_deseasonalized_endpoint_trend_1h_v1"
ACCEPT_VERDICT = "accept_causal_week_phase_deseasonalized_endpoint_trend_1h_v1"
FROZEN_AT_MAIN = "5a0fcc97d1a882f8223656c51f5bb8055f534e38"
MARKETS = ("SUSHI-USDT", "CRV-USDT")
BAR = "1H"
FEE = 0.0005
START_UTC = dt.datetime(2021, 7, 24, tzinfo=dt.UTC)
FINAL_UTC = dt.datetime(2026, 7, 8, tzinfo=dt.UTC)
EXPECTED_ROWS = 43_441
CALIB_START, CALIB_END = 2_160, 10_080
TRAIN_START, TRAIN_END = 10_080, 17_520
OOS_START, OOS_END = 17_520, 43_440
FULL_START, FULL_END = 10_080, 43_440
BLOCK_HOURS = 168
ECON_DRAWS = 5_000
ECON_SEED = 20_260_802
PROFILE_DRAWS = 5_000
PROFILE_SEED = 20_260_803
API = "https://www.okx.com/api/v5/market/history-candles"
USER_AGENT = "Dingding-leo-GPT-causal-1H-research/1.0"


def canonical_json_bytes(obj: Any) -> bytes:
    return (
        json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def http_get(url: str, retries: int = 10) -> bytes:
    last: Exception | None = None
    for attempt in range(retries):
        req = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                raw = resp.read()
                if resp.status != 200:
                    raise RuntimeError(f"HTTP {resp.status}: {raw[:500]!r}")
                return raw
        except (urllib.error.URLError, TimeoutError, RuntimeError) as exc:
            last = exc
            time.sleep(min(15.0, 0.7 * (2**attempt)))
    raise RuntimeError(f"public OKX request failed after retries: {last}")


@dataclass(frozen=True)
class Candle:
    ts_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    volume_ccy: float
    volume_quote: float
    confirm: int

    def normalized(self) -> dict[str, Any]:
        return {
            "ts_ms": self.ts_ms,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "volume_ccy": self.volume_ccy,
            "volume_quote": self.volume_quote,
            "confirm": self.confirm,
        }


def parse_candle(row: list[str]) -> Candle:
    if len(row) < 9:
        raise ValueError(f"short OKX candle row: {row!r}")
    vals = [float(row[i]) for i in range(1, 8)]
    if not all(math.isfinite(v) for v in vals):
        raise ValueError("non-finite candle field")
    open_px, high_px, low_px, close_px, vol, vol_ccy, vol_quote = vals
    if min(open_px, high_px, low_px, close_px) <= 0 or min(vol, vol_ccy, vol_quote) < 0:
        raise ValueError("invalid non-positive price or negative volume")
    if high_px < max(open_px, low_px, close_px) or low_px > min(open_px, high_px, close_px):
        raise ValueError("invalid OHLC ordering")
    confirm = int(row[8])
    if confirm != 1:
        raise ValueError("unconfirmed candle")
    return Candle(
        int(row[0]),
        open_px,
        high_px,
        low_px,
        close_px,
        vol,
        vol_ccy,
        vol_quote,
        confirm,
    )


def acquire_market(inst_id: str, source_dir: Path) -> tuple[list[Candle], dict[str, Any]]:
    start_ms = int(START_UTC.timestamp() * 1000)
    final_ms = int(FINAL_UTC.timestamp() * 1000)
    cursor = final_ms + 3_600_000
    rows: dict[int, Candle] = {}
    page_records: list[dict[str, Any]] = []
    raw_path = source_dir / f"{inst_id}-raw-pages.jsonl"
    source_dir.mkdir(parents=True, exist_ok=True)
    with raw_path.open("wb") as raw_out:
        for page in range(1, 2_000):
            query = urllib.parse.urlencode(
                {
                    "instId": inst_id,
                    "bar": BAR,
                    "after": str(cursor),
                    "limit": "100",
                }
            )
            url = f"{API}?{query}"
            raw = http_get(url)
            obj = json.loads(raw)
            if obj.get("code") != "0":
                raise RuntimeError(f"OKX error for {inst_id}: {obj}")
            data = obj.get("data")
            if not isinstance(data, list) or not data:
                raise RuntimeError(
                    f"empty OKX page before reaching start for {inst_id}; cursor={cursor}"
                )
            parsed = [parse_candle(row) for row in data]
            timestamps = [c.ts_ms for c in parsed]
            if timestamps != sorted(timestamps, reverse=True):
                raise ValueError(f"provider page not descending for {inst_id} page {page}")
            if len(set(timestamps)) != len(timestamps):
                raise ValueError(f"duplicate timestamp inside provider page for {inst_id}")
            oldest = min(timestamps)
            newest = max(timestamps)
            if oldest >= cursor:
                raise ValueError("pagination did not move backward")
            raw_out.write(raw)
            raw_out.write(b"\n")
            page_records.append(
                {
                    "page": page,
                    "request_url": url,
                    "response_sha256": sha256_bytes(raw),
                    "response_bytes": len(raw),
                    "row_count": len(parsed),
                    "newest_ts_ms": newest,
                    "oldest_ts_ms": oldest,
                }
            )
            for candle in parsed:
                if start_ms <= candle.ts_ms <= final_ms:
                    prior = rows.get(candle.ts_ms)
                    if prior is not None and prior != candle:
                        raise ValueError(f"conflicting duplicate candle {inst_id} {candle.ts_ms}")
                    rows[candle.ts_ms] = candle
            if oldest <= start_ms:
                break
            cursor = oldest
            time.sleep(0.12)
        else:
            raise RuntimeError("pagination safety limit exceeded")

    expected_ts = [start_ms + i * 3_600_000 for i in range(EXPECTED_ROWS)]
    actual_ts = sorted(rows)
    if actual_ts != expected_ts:
        missing = sorted(set(expected_ts) - set(actual_ts))[:10]
        extra = sorted(set(actual_ts) - set(expected_ts))[:10]
        raise ValueError(
            f"exact frozen grid unavailable for {inst_id}: rows={len(actual_ts)} "
            f"missing={missing} extra={extra} first={actual_ts[:1]} "
            f"last={actual_ts[-1:] if actual_ts else []}"
        )
    candles = [rows[t] for t in expected_ts]
    normalized_path = source_dir / f"{inst_id}-normalized.csv"
    with normalized_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(candles[0].normalized()))
        writer.writeheader()
        writer.writerows(c.normalized() for c in candles)
    manifest = {
        "provider": "OKX public REST",
        "endpoint": API,
        "instrument": inst_id,
        "bar": BAR,
        "start_utc": START_UTC.isoformat().replace("+00:00", "Z"),
        "final_utc": FINAL_UTC.isoformat().replace("+00:00", "Z"),
        "expected_rows": EXPECTED_ROWS,
        "actual_rows": len(candles),
        "raw_pages_file": raw_path.name,
        "raw_pages_sha256": sha256_file(raw_path),
        "normalized_file": normalized_path.name,
        "normalized_sha256": sha256_file(normalized_path),
        "pages": page_records,
    }
    return candles, manifest


def phase_for_ms(ts_ms: int) -> int:
    x = dt.datetime.fromtimestamp(ts_ms / 1000, tz=dt.UTC)
    return 4 * x.weekday() + x.hour // 6


def percentile_ci(values: Iterable[float]) -> list[float]:
    arr = np.asarray(list(values), dtype=np.float64)
    return [
        float(np.percentile(arr, 2.5)),
        float(np.percentile(arr, 97.5)),
    ]


def compounded(returns: np.ndarray) -> float:
    if returns.size == 0:
        return 0.0
    if np.any(returns <= -1.0):
        return -1.0
    return float(np.expm1(np.log1p(returns).sum()))


def sharpe(returns: np.ndarray) -> float:
    if returns.size < 2:
        return 0.0
    sd = float(np.std(returns, ddof=1))
    return 0.0 if sd == 0.0 else float(np.mean(returns) / sd * math.sqrt(8_760.0))


def max_drawdown(returns: np.ndarray) -> float:
    if returns.size == 0:
        return 0.0
    wealth = np.cumprod(1.0 + returns)
    peaks = np.maximum.accumulate(np.concatenate(([1.0], wealth)))[1:]
    return float(np.min(wealth / peaks - 1.0))


def episodes(position: np.ndarray) -> dict[str, Any]:
    if position.size == 0:
        return {
            "long_count": 0,
            "cash_count": 0,
            "long_hours": [],
            "cash_hours": [],
        }
    vals: list[int] = []
    lens: list[int] = []
    prev = int(position[0])
    run = 1
    for v in position[1:]:
        iv = int(v)
        if iv == prev:
            run += 1
        else:
            vals.append(prev)
            lens.append(run)
            prev, run = iv, 1
    vals.append(prev)
    lens.append(run)
    longs = [n for v, n in zip(vals, lens, strict=False) if v == 1]
    cash = [n for v, n in zip(vals, lens, strict=False) if v == 0]

    def stats(xs: list[int]) -> dict[str, Any]:
        return {
            "count": len(xs),
            "mean_hours": float(statistics.fmean(xs)) if xs else 0.0,
            "median_hours": float(statistics.median(xs)) if xs else 0.0,
            "max_hours": max(xs) if xs else 0,
        }

    return {"long": stats(longs), "cash": stats(cash)}


@dataclass
class PathResult:
    gross_returns: np.ndarray
    net_returns: np.ndarray
    position: np.ndarray
    fee_events: np.ndarray
    turnover: float
    transitions: int

    def metrics(self) -> dict[str, Any]:
        gross = compounded(self.gross_returns)
        net = compounded(self.net_returns)
        return {
            "gross_return": gross,
            "net_return": net,
            "annualized_arithmetic_mean": float(np.mean(self.net_returns) * 8_760.0),
            "sharpe": sharpe(self.net_returns),
            "max_drawdown": max_drawdown(self.net_returns),
            "exposure_fraction": float(np.mean(self.position)),
            "turnover": self.turnover,
            "transitions": self.transitions,
            "arithmetic_fee_drag": float(np.sum(self.fee_events)),
            "edge_per_turnover": (net / self.turnover if self.turnover > 0 else 0.0),
            "episodes": episodes(self.position),
        }


def simulate(
    opens: np.ndarray,
    target_by_decision: dict[int, int],
    start: int,
    end: int,
    *,
    delay_hours: int = 0,
    always_long: bool = False,
) -> PathResult:
    if not (0 <= start < end < len(opens)):
        raise ValueError("invalid segment boundaries")
    n = end - start
    gross_ret = opens[start + 1 : end + 1] / opens[start:end] - 1.0
    position = np.zeros(n, dtype=np.int8)
    fee_events = np.zeros(n, dtype=np.float64)
    current = 0
    turnover = 0.0
    transitions = 0
    schedule: dict[int, int] = {}
    if always_long:
        schedule[start] = 1
    else:
        for decision, target in target_by_decision.items():
            execution_interval = decision + 1 + delay_hours
            if start <= execution_interval < end:
                schedule[execution_interval] = int(target)
    for interval in range(start, end):
        if interval in schedule:
            target = schedule[interval]
            change = abs(target - current)
            if change:
                turnover += change
                transitions += 1
                fee_events[interval - start] += FEE * change
                current = target
        position[interval - start] = current
    if current:
        turnover += 1.0
        transitions += 1
        fee_events[-1] += FEE
    gross_path = position.astype(np.float64) * gross_ret
    net_path = gross_path - fee_events
    if not math.isclose(
        float(fee_events.sum()),
        turnover * FEE,
        rel_tol=0,
        abs_tol=1e-15,
    ):
        raise AssertionError("fee accounting identity failed")
    return PathResult(
        gross_path,
        net_path,
        position,
        fee_events,
        turnover,
        transitions,
    )


def compute_profile(
    candles: list[Candle],
) -> tuple[np.ndarray, list[int], list[float], float, str]:
    closes = np.array([c.close for c in candles], dtype=np.float64)
    returns = np.full(len(candles), np.nan, dtype=np.float64)
    returns[1:] = np.log(closes[1:] / closes[:-1])
    phases = np.array([phase_for_ms(c.ts_ms) for c in candles], dtype=np.int16)
    idx = np.arange(CALIB_START, CALIB_END)
    mu_all = float(np.mean(returns[idx]))
    counts: list[int] = []
    means: list[float] = []
    profile = np.zeros(28, dtype=np.float64)
    for b in range(28):
        vals = returns[idx[phases[idx] == b]]
        counts.append(int(vals.size))
        means.append(float(np.mean(vals)))
        profile[b] = means[-1] - mu_all
    if min(counts) < 280:
        raise ValueError(f"insufficient calibration phase support: {counts}")
    if abs(float(np.average(profile, weights=counts))) > 1e-15:
        raise AssertionError("weighted profile deviations do not preserve calibration mean")
    payload = {
        "counts": counts,
        "means": means,
        "mu_all": mu_all,
        "deviations": [float(x) for x in profile],
    }
    return (
        profile,
        counts,
        means,
        mu_all,
        sha256_bytes(canonical_json_bytes(payload)),
    )


def targets_for_market(
    candles: list[Candle], profile: np.ndarray
) -> tuple[dict[int, int], dict[int, int], np.ndarray]:
    closes = np.array([c.close for c in candles], dtype=np.float64)
    returns = np.full(len(candles), np.nan, dtype=np.float64)
    returns[1:] = np.log(closes[1:] / closes[:-1])
    phases = np.array([phase_for_ms(c.ts_ms) for c in candles], dtype=np.int16)
    adjusted = returns.copy()
    adjusted[1:] -= profile[phases[1:]]
    csum = np.nancumsum(np.nan_to_num(adjusted, nan=0.0))
    cand: dict[int, int] = {}
    raw: dict[int, int] = {}
    for t in range(FULL_START, FULL_END, 24):
        lo = t - 2_159
        adjusted_margin = float(csum[t] - (csum[lo - 1] if lo > 0 else 0.0))
        raw_margin = float(math.log(closes[t] / closes[t - 2_160]))
        explicit = float(np.sum(adjusted[lo : t + 1]))
        if not math.isclose(adjusted_margin, explicit, rel_tol=0, abs_tol=2e-14):
            raise AssertionError("adjusted margin identity failed")
        cand[t] = int(adjusted_margin > 0.0)
        raw[t] = int(raw_margin > 0.0)

    # Structural future-suffix invariance test only; altered copy is never scored.
    cutoff = TRAIN_END
    altered = adjusted.copy()
    altered[cutoff + 1 :] = altered[cutoff + 1 :][::-1]
    alt_csum = np.nancumsum(np.nan_to_num(altered, nan=0.0))
    for t in range(FULL_START, cutoff, 24):
        lo = t - 2_159
        alt_margin = float(alt_csum[t] - (alt_csum[lo - 1] if lo > 0 else 0.0))
        if int(alt_margin > 0.0) != cand[t]:
            raise AssertionError("future suffix altered an earlier target")
    return cand, raw, returns


def slice_return(arr: np.ndarray, start_offset: int, end_offset: int) -> float:
    return compounded(arr[start_offset:end_offset])


def fold_and_year_breadth(
    candles: list[Candle], candidate: PathResult, benchmark: PathResult
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], float]:
    folds: list[dict[str, Any]] = []
    positive_rel: list[float] = []
    for k in range(12):
        a, b = k * 2_160, (k + 1) * 2_160
        c = slice_return(candidate.net_returns, a, b)
        e = slice_return(benchmark.net_returns, a, b)
        rel = c - e
        folds.append(
            {
                "fold": k + 1,
                "candidate_net": c,
                "e2160_net": e,
                "relative": rel,
            }
        )
        if rel > 0:
            positive_rel.append(rel)
    concentration = max(positive_rel) / sum(positive_rel) if positive_rel else 1.0

    years: list[dict[str, Any]] = []
    by_year: dict[int, list[int]] = defaultdict(list)
    for offset, i in enumerate(range(OOS_START, OOS_END)):
        year = dt.datetime.fromtimestamp(candles[i].ts_ms / 1000, tz=dt.UTC).year
        by_year[year].append(offset)
    for year, offsets in sorted(by_year.items()):
        a, b = min(offsets), max(offsets) + 1
        c = slice_return(candidate.net_returns, a, b)
        e = slice_return(benchmark.net_returns, a, b)
        years.append(
            {
                "year": year,
                "candidate_net": c,
                "e2160_net": e,
                "relative": c - e,
            }
        )
    return folds, years, concentration


def moving_block_uncertainty(candidate: np.ndarray, benchmark: np.ndarray) -> dict[str, Any]:
    if candidate.shape != benchmark.shape:
        raise ValueError("paired paths misaligned")
    n = candidate.size
    rng = np.random.default_rng(ECON_SEED)
    starts_max = n - BLOCK_HOURS
    blocks_needed = math.ceil(n / BLOCK_HOURS)
    mean_delta = np.empty(ECON_DRAWS)
    sharpe_delta = np.empty(ECON_DRAWS)
    mdd_delta = np.empty(ECON_DRAWS)
    for d in range(ECON_DRAWS):
        starts = rng.integers(0, starts_max + 1, size=blocks_needed)
        idx = np.concatenate([np.arange(s, s + BLOCK_HOURS) for s in starts])[:n]
        c = candidate[idx]
        b = benchmark[idx]
        mean_delta[d] = float(np.mean(c - b))
        sharpe_delta[d] = sharpe(c) - sharpe(b)
        mdd_delta[d] = max_drawdown(c) - max_drawdown(b)
    return {
        "draws": ECON_DRAWS,
        "block_hours": BLOCK_HOURS,
        "seed": ECON_SEED,
        "mean_hourly_net_difference_point": float(np.mean(candidate - benchmark)),
        "mean_hourly_net_difference_95": percentile_ci(mean_delta),
        "annualized_sharpe_difference_point": (sharpe(candidate) - sharpe(benchmark)),
        "annualized_sharpe_difference_95": percentile_ci(sharpe_delta),
        "max_drawdown_difference_point": (max_drawdown(candidate) - max_drawdown(benchmark)),
        "max_drawdown_difference_95": percentile_ci(mdd_delta),
    }


def profile_transport(candles: list[Candle], calibration: np.ndarray) -> dict[str, Any]:
    closes = np.array([c.close for c in candles], dtype=np.float64)
    returns = np.full(len(candles), np.nan, dtype=np.float64)
    returns[1:] = np.log(closes[1:] / closes[:-1])
    week_rows: dict[str, list[int]] = defaultdict(list)
    for i in range(OOS_START, OOS_END):
        x = dt.datetime.fromtimestamp(candles[i].ts_ms / 1000, tz=dt.UTC)
        monday = x - dt.timedelta(
            days=x.weekday(),
            hours=x.hour,
            minutes=x.minute,
            seconds=x.second,
            microseconds=x.microsecond,
        )
        week_rows[monday.isoformat()].append(i)
    complete: list[list[int]] = []
    for key in sorted(week_rows):
        idx = week_rows[key]
        contiguous = all(
            candles[i].ts_ms == candles[idx[0]].ts_ms + (i - idx[0]) * 3_600_000 for i in idx
        )
        if len(idx) == 168 and contiguous:
            complete.append(idx)
    if len(complete) < 100:
        raise ValueError(f"insufficient complete OOS weeks: {len(complete)}")
    week_phase_sums = np.zeros((len(complete), 28), dtype=np.float64)
    week_counts = np.zeros((len(complete), 28), dtype=np.int64)
    for w, idx in enumerate(complete):
        for i in idx:
            p = phase_for_ms(candles[i].ts_ms)
            week_phase_sums[w, p] += returns[i]
            week_counts[w, p] += 1
    if not np.all(week_counts == 6):
        raise AssertionError("complete UTC week does not contain six hourly observations per phase")
    total_sums = week_phase_sums.sum(axis=0)
    total_counts = week_counts.sum(axis=0)
    means = total_sums / total_counts
    oos_profile = means - float(total_sums.sum() / total_counts.sum())
    point = float(np.corrcoef(calibration, oos_profile)[0, 1])
    sign_agreement = float(np.mean(np.sign(calibration) == np.sign(oos_profile)))
    rng = np.random.default_rng(PROFILE_SEED)
    corrs = np.empty(PROFILE_DRAWS)
    for d in range(PROFILE_DRAWS):
        sample = rng.integers(0, len(complete), size=len(complete))
        sums = week_phase_sums[sample].sum(axis=0)
        counts = week_counts[sample].sum(axis=0)
        means_d = sums / counts
        profile_d = means_d - float(sums.sum() / counts.sum())
        corrs[d] = float(np.corrcoef(calibration, profile_d)[0, 1])
    return {
        "complete_weeks": len(complete),
        "draws": PROFILE_DRAWS,
        "seed": PROFILE_SEED,
        "oos_profile": [float(x) for x in oos_profile],
        "pearson_correlation": point,
        "pearson_correlation_95": percentile_ci(corrs),
        "sign_agreement": sign_agreement,
    }


def transition_attribution(candidate: dict[int, int], benchmark: dict[int, int]) -> dict[str, Any]:
    decisions = list(range(OOS_START, OOS_END, 24))
    disagreement = [t for t in decisions if candidate[t] != benchmark[t]]
    cand_changes: list[int] = []
    bench_changes: list[int] = []
    prev_c = prev_b = 0
    for t in decisions:
        if candidate[t] != prev_c:
            cand_changes.append(t)
        if benchmark[t] != prev_b:
            bench_changes.append(t)
        prev_c, prev_b = candidate[t], benchmark[t]
    return {
        "decision_count": len(decisions),
        "disagreement_count": len(disagreement),
        "disagreement_fraction": len(disagreement) / len(decisions),
        "candidate_decision_changes": len(cand_changes),
        "e2160_decision_changes": len(bench_changes),
        "candidate_only_change_count": len(set(cand_changes) - set(bench_changes)),
        "e2160_only_change_count": len(set(bench_changes) - set(cand_changes)),
        "simultaneous_change_count": len(set(cand_changes) & set(bench_changes)),
    }


def metric_gate(
    m: dict[str, Any],
    e: dict[str, Any],
    a: dict[str, Any],
    u: dict[str, Any],
    folds: list[dict[str, Any]],
    years: list[dict[str, Any]],
    concentration: float,
    transport: dict[str, Any],
    delay: dict[str, Any],
) -> dict[str, bool]:
    return {
        "oos_positive": m["net_return"] > 0 and m["sharpe"] > 0,
        "beats_e2160": (m["net_return"] > e["net_return"] and m["sharpe"] > e["sharpe"]),
        "beats_always_long": (m["net_return"] > a["net_return"] and m["sharpe"] > a["sharpe"]),
        "paired_lower_bounds_positive": (
            u["mean_hourly_net_difference_95"][0] > 0
            and u["annualized_sharpe_difference_95"][0] > 0
        ),
        "drawdown": (
            m["max_drawdown"] >= e["max_drawdown"] - 0.05 and m["max_drawdown"] > a["max_drawdown"]
        ),
        "turnover": (m["turnover"] <= 1.5 * e["turnover"] and m["turnover"] <= 80),
        "edge_per_turnover": (
            m["edge_per_turnover"] > 0 and m["edge_per_turnover"] > e["edge_per_turnover"]
        ),
        "fold_breadth": (sum(row["relative"] > 0 for row in folds) >= 8),
        "year_breadth": all(row["candidate_net"] > 0 and row["relative"] > 0 for row in years),
        "fold_concentration": concentration <= 0.5,
        "profile_transport": (
            transport["pearson_correlation"] > 0 and transport["pearson_correlation_95"][0] > 0
        ),
        "delay": (
            delay["net_return"] > 0
            and delay["sharpe"] > 0
            and delay["net_return"] > e["net_return"]
        ),
    }


def run_market(inst: str, candles: list[Candle], manifest: dict[str, Any]) -> dict[str, Any]:
    profile, counts, means, mu_all, profile_hash = compute_profile(candles)
    cand_targets, raw_targets, _ = targets_for_market(candles, profile)
    opens = np.array([c.open for c in candles], dtype=np.float64)
    segments = {
        "training": (TRAIN_START, TRAIN_END),
        "oos": (OOS_START, OOS_END),
        "full": (FULL_START, FULL_END),
    }
    perf: dict[str, Any] = {}
    paths: dict[str, dict[str, PathResult]] = {}
    for name, (start, end) in segments.items():
        candidate = simulate(opens, cand_targets, start, end)
        e2160 = simulate(opens, raw_targets, start, end)
        always_long = simulate(opens, {}, start, end, always_long=True)
        cash = simulate(opens, {}, start, end)
        paths[name] = {
            "candidate": candidate,
            "e2160": e2160,
            "always_long": always_long,
            "cash": cash,
        }
        perf[name] = {key: value.metrics() for key, value in paths[name].items()}
    delay_path = simulate(
        opens,
        cand_targets,
        OOS_START,
        OOS_END,
        delay_hours=1,
    )
    delay_metrics = delay_path.metrics()
    folds, years, concentration = fold_and_year_breadth(
        candles,
        paths["oos"]["candidate"],
        paths["oos"]["e2160"],
    )
    uncertainty = moving_block_uncertainty(
        paths["oos"]["candidate"].net_returns,
        paths["oos"]["e2160"].net_returns,
    )
    transport = profile_transport(candles, profile)
    attribution = transition_attribution(cand_targets, raw_targets)
    gross_timing = float(
        np.sum(paths["oos"]["candidate"].gross_returns - paths["oos"]["e2160"].gross_returns)
    )
    relative_fee = float(
        -np.sum(paths["oos"]["candidate"].fee_events - paths["oos"]["e2160"].fee_events)
    )
    gates = metric_gate(
        perf["oos"]["candidate"],
        perf["oos"]["e2160"],
        perf["oos"]["always_long"],
        uncertainty,
        folds,
        years,
        concentration,
        transport,
        delay_metrics,
    )
    gates["source_and_integrity"] = True
    gates["full_positive"] = perf["full"]["candidate"]["net_return"] > 0
    return {
        "instrument": inst,
        "source": manifest,
        "profile": {
            "phase_count": 28,
            "counts": counts,
            "means": means,
            "mu_all": mu_all,
            "deviations": [float(x) for x in profile],
            "dispersion_std": float(np.std(profile, ddof=1)),
            "sha256": profile_hash,
        },
        "performance": perf,
        "oos_fold_results": folds,
        "oos_year_results": years,
        "positive_fold_concentration": concentration,
        "uncertainty": uncertainty,
        "profile_transport": transport,
        "delay_one_extra_hour_oos": delay_metrics,
        "decision_attribution": attribution,
        "oos_decomposition": {
            "arithmetic_gross_timing_difference": gross_timing,
            "arithmetic_relative_fee_contribution": relative_fee,
            "arithmetic_sum": gross_timing + relative_fee,
            "compounded_net_return_difference": (
                perf["oos"]["candidate"]["net_return"] - perf["oos"]["e2160"]["net_return"]
            ),
        },
        "gates": gates,
        "passed_all_market_gates": all(gates.values()),
    }


def fmt_pct(x: float) -> str:
    return f"{100 * x:+.4f}%"


def build_report(evidence: dict[str, Any]) -> str:
    lines = [
        "# Causal week-phase deseasonalized endpoint trend 1H evidence",
        "",
        "```text",
        f"family              {FAMILY_ID}",
        "candidate_count     2 independent markets",
        "parameter_grid      0",
        f"fee                 {FEE:.4f} one way",
        f"accepted            {evidence['accepted']}",
        f"verdict             {evidence['verdict']}",
        "```",
        "",
        "## Immutable sample",
        "",
        f"- Provider: anonymous public confirmed OKX SPOT {BAR} candles.",
        (
            f"- Frozen grid: {START_UTC.isoformat()} through "
            f"{FINAL_UTC.isoformat()}, {EXPECTED_ROWS:,} rows per market."
        ),
        (
            f"- Calibration: [{CALIB_START:,},{CALIB_END:,}); "
            f"training: [{TRAIN_START:,},{TRAIN_END:,}); "
            f"OOS: [{OOS_START:,},{OOS_END:,}); "
            f"full: [{FULL_START:,},{FULL_END:,})."
        ),
        (
            f"- Exactly {FEE * 10_000:.1f} bps per one-way exposure "
            "change, including terminal liquidation."
        ),
        "",
        "## Performance",
        "",
        (
            "| Market | Segment | Candidate net | Sharpe | Max DD | "
            "Turnover | E2160 net | E2160 Sharpe | Always-long net |"
        ),
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for inst in MARKETS:
        market = evidence["markets"][inst]
        for seg in ("training", "oos", "full"):
            p = market["performance"][seg]
            c, e, a = p["candidate"], p["e2160"], p["always_long"]
            lines.append(
                f"| {inst} | {seg} | {fmt_pct(c['net_return'])} | "
                f"{c['sharpe']:+.4f} | {fmt_pct(c['max_drawdown'])} | "
                f"{c['turnover']:.0f} | {fmt_pct(e['net_return'])} | "
                f"{e['sharpe']:+.4f} | {fmt_pct(a['net_return'])} |"
            )
    lines += ["", "## Robustness", ""]
    for inst in MARKETS:
        market = evidence["markets"][inst]
        u = market["uncertainty"]
        folds = sum(x["relative"] > 0 for x in market["oos_fold_results"])
        years = sum(
            x["candidate_net"] > 0 and x["relative"] > 0 for x in market["oos_year_results"]
        )
        lines += [
            f"### {inst}",
            "",
            (
                f"- Positive relative OOS folds: {folds}/12; positive "
                f"candidate-and-relative years: {years}/"
                f"{len(market['oos_year_results'])}."
            ),
            (f"- Positive-fold concentration: {market['positive_fold_concentration']:.4f}."),
            (
                "- Mean hourly net delta 95% CI: "
                f"[{u['mean_hourly_net_difference_95'][0] * 10_000:+.4f}, "
                f"{u['mean_hourly_net_difference_95'][1] * 10_000:+.4f}] "
                "bp/hour."
            ),
            (
                "- Sharpe delta 95% CI: "
                f"[{u['annualized_sharpe_difference_95'][0]:+.4f}, "
                f"{u['annualized_sharpe_difference_95'][1]:+.4f}]."
            ),
            (
                "- Calibration/OOS profile correlation: "
                f"{market['profile_transport']['pearson_correlation']:+.4f}, "
                "95% CI "
                f"[{market['profile_transport']['pearson_correlation_95'][0]:+.4f}, "
                f"{market['profile_transport']['pearson_correlation_95'][1]:+.4f}]."
            ),
            (
                "- One-extra-hour delayed OOS: net "
                f"{fmt_pct(market['delay_one_extra_hour_oos']['net_return'])}, "
                "Sharpe "
                f"{market['delay_one_extra_hour_oos']['sharpe']:+.4f}."
            ),
            (
                f"- Passed gates: {sum(market['gates'].values())}/"
                f"{len(market['gates'])}; market accepted: "
                f"{market['passed_all_market_gates']}."
            ),
            "",
        ]
    lines += [
        "## Disposition",
        "",
        (
            "The architecture is **"
            f"{'accepted' if evidence['accepted'] else 'rejected'}**. "
            "Bilateral promotion requires every frozen gate to pass in both "
            "fixed markets."
        ),
        "",
        (
            "Closed rescue paths: market substitution or subset promotion; "
            "profile bucket/count/lookback/estimator changes; smoothing, "
            "shrinkage or sign reversal; threshold, cadence, fee, sizing, "
            "benchmark, bootstrap, delay or OOS refit changes."
        ),
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    out = args.output_dir
    source_dir = out / "source"
    out.mkdir(parents=True, exist_ok=True)
    manifests: dict[str, Any] = {}
    market_results: dict[str, Any] = {}
    for inst in MARKETS:
        candles, manifest = acquire_market(inst, source_dir)
        manifests[inst] = manifest
        market_results[inst] = run_market(inst, candles, manifest)
    source_manifest = {
        "family_id": FAMILY_ID,
        "frozen_at_main": FROZEN_AT_MAIN,
        "markets": manifests,
    }
    source_manifest_path = out / "source-manifest.json"
    source_manifest_path.write_bytes(canonical_json_bytes(source_manifest))
    bilateral = all(market_results[m]["passed_all_market_gates"] for m in MARKETS)
    evidence = {
        "family_id": FAMILY_ID,
        "classification": "executable base-signal representation experiment",
        "frozen_at_main": FROZEN_AT_MAIN,
        "candidate_count": 2,
        "parameter_grid_count": 0,
        "markets_required": list(MARKETS),
        "bar": BAR,
        "fee_one_way": FEE,
        "exposure_domain": [0, 1],
        "source_start_utc": START_UTC.isoformat().replace("+00:00", "Z"),
        "source_final_utc": FINAL_UTC.isoformat().replace("+00:00", "Z"),
        "rows_per_market": EXPECTED_ROWS,
        "segments": {
            "calibration": [CALIB_START, CALIB_END],
            "training": [TRAIN_START, TRAIN_END],
            "oos": [OOS_START, OOS_END],
            "full": [FULL_START, FULL_END],
        },
        "markets": market_results,
        "bilateral_replication": bilateral,
        "accepted": bilateral,
        "verdict": ACCEPT_VERDICT if bilateral else REJECT_VERDICT,
        "canonical_strategy_changed": False,
        "paper_or_live_authority": False,
        "source_manifest_sha256": sha256_file(source_manifest_path),
        "closed_rescue_paths": [
            "market substitution or subset promotion",
            ("phase count, bucket boundaries, calibration interval, estimator or profile sign"),
            ("trend horizon, cadence, threshold, execution timing, fee or sizing"),
            "benchmark, bootstrap, delay or acceptance-gate changes",
            "OOS refit, profile pooling or favourable-phase selection",
        ],
    }
    evidence_path = out / "evidence.json"
    evidence_path.write_bytes(canonical_json_bytes(evidence))
    report_path = out / "report.md"
    report_path.write_text(build_report(evidence), encoding="utf-8")
    sums: dict[str, str] = {}
    for path in sorted(out.rglob("*")):
        if path.is_file() and path.name != "sha256sums.json":
            sums[str(path.relative_to(out))] = sha256_file(path)
    (out / "sha256sums.json").write_bytes(canonical_json_bytes(sums))
    print(
        json.dumps(
            {
                "accepted": bilateral,
                "verdict": evidence["verdict"],
                "evidence_sha256": sha256_file(evidence_path),
                "source_manifest_sha256": sha256_file(source_manifest_path),
                "markets": {
                    market: {
                        "oos_candidate": market_results[market]["performance"]["oos"]["candidate"],
                        "oos_e2160": market_results[market]["performance"]["oos"]["e2160"],
                        "gates": market_results[market]["gates"],
                    }
                    for market in MARKETS
                },
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
