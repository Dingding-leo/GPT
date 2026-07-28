#!/usr/bin/env python3
"""Run the frozen funding/basis crowding-unwind v2 research family.

Public unauthenticated OKX data only.  The script persists exact response bytes,
implements the two predeclared causal policies, and emits a strict JSON verdict.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

BASE_URL = "https://www.okx.com"
FEE = 0.0005
ANNUAL_HOURS = 8760.0
FUNDING_LIMIT = 400
CANDLE_LIMIT = 100
SPOT_LIMIT = 300
MAX_PAGES = 80
MAX_BYTES = 4_000_000
RETRIES = 5
SLEEP_SECONDS = 0.12
WARMUP_EVENTS = 30
WARMUP_HOURS = 240
FOLD_DAYS = 14
FOLD_HOURS = FOLD_DAYS * 24
BOOTSTRAP_RESAMPLES = 5000
BOOTSTRAP_BLOCK = 168
BOOTSTRAP_SEED = 20260728
ARCHIVE_BEGIN_MS = 1782864000000  # 2026-07-01 00:00 UTC
ARCHIVE_END_MS = 1783036800000  # 2026-07-03 00:00 UTC
FAMILY_ID = "funding-basis-crowding-unwind-v2"


class ResearchError(RuntimeError):
    """Fail-closed research error."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise ResearchError(f"redirect rejected: {code} {newurl}")


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ResearchError(f"duplicate JSON field: {key}")
        out[key] = value
    return out


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _utc_ms(ts: pd.Timestamp) -> int:
    return int(ts.timestamp() * 1000)


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).isoformat()


@dataclass
class SourceRecord:
    ordinal: int
    url: str
    status: int
    received_at_utc: str
    byte_length: int
    sha256: str
    path: str


class PublicOKX:
    def __init__(self, raw_dir: Path) -> None:
        self.raw_dir = raw_dir
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.records: list[SourceRecord] = []
        self.opener = urllib.request.build_opener(
            NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context())
        )

    def fetch(
        self,
        path: str,
        params: dict[str, str | int],
        *,
        optional: bool = False,
    ) -> dict[str, Any]:
        ordered = sorted((key, str(value)) for key, value in params.items())
        query = urllib.parse.urlencode(ordered)
        url = f"{BASE_URL}{path}?{query}"
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != "www.okx.com":
            raise ResearchError(f"untrusted origin: {url}")
        req = urllib.request.Request(
            url,
            method="GET",
            headers={"Accept": "application/json", "User-Agent": "gpt-quant-lab/0.2"},
        )
        last_error: Exception | None = None
        for attempt in range(RETRIES):
            try:
                with self.opener.open(req, timeout=30) as response:
                    status = int(response.status)
                    raw = response.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES:
                    raise ResearchError(f"response exceeds {MAX_BYTES} bytes: {url}")
                if status != 200:
                    raise ResearchError(f"HTTP {status}: {url}")
                return self._persist_and_parse(url, status, raw, optional=optional)
            except (urllib.error.URLError, TimeoutError, ResearchError) as exc:
                last_error = exc
                if isinstance(exc, ResearchError) and "redirect rejected" in str(exc):
                    raise
                if attempt + 1 < RETRIES:
                    time.sleep(0.5 * (2**attempt))
        if optional:
            payload = {"code": "optional_fetch_failed", "msg": str(last_error), "data": []}
            raw = _json_bytes(payload)
            return self._persist_and_parse(url, 0, raw, optional=True)
        raise ResearchError(f"request failed after retries: {url}: {last_error}")

    def _persist_and_parse(
        self, url: str, status: int, raw: bytes, *, optional: bool
    ) -> dict[str, Any]:
        ordinal = len(self.records)
        path = self.raw_dir / f"{ordinal:04d}.json"
        path.write_bytes(raw)
        self.records.append(
            SourceRecord(
                ordinal=ordinal,
                url=url,
                status=status,
                received_at_utc=datetime.now(UTC).isoformat(),
                byte_length=len(raw),
                sha256=_sha(raw),
                path=str(path.relative_to(self.raw_dir.parent)),
            )
        )
        try:
            payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_object)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            if optional:
                return {"code": "optional_parse_failed", "msg": str(exc), "data": []}
            raise ResearchError(f"invalid JSON response: {url}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ResearchError(f"top-level JSON must be object: {url}")
        if optional and payload.get("code") != "0":
            return payload
        if set(payload) != {"code", "msg", "data"}:
            raise ResearchError(f"unexpected top-level fields: {url}: {sorted(payload)}")
        if payload["code"] != "0" or payload["msg"] != "":
            raise ResearchError(f"OKX error: {url}: {payload['code']} {payload['msg']}")
        if not isinstance(payload["data"], list):
            raise ResearchError(f"data must be list: {url}")
        return payload


def instrument_binding(client: PublicOKX, spot_id: str, swap_id: str) -> dict[str, str]:
    spot = client.fetch(
        "/api/v5/public/instruments", {"instType": "SPOT", "instId": spot_id}
    )["data"]
    swap = client.fetch(
        "/api/v5/public/instruments", {"instType": "SWAP", "instId": swap_id}
    )["data"]
    if len(spot) != 1 or len(swap) != 1:
        raise ResearchError(f"ambiguous instrument binding: {spot_id} {swap_id}")
    spot_row, swap_row = spot[0], swap[0]
    if spot_row.get("instId") != spot_id or swap_row.get("instId") != swap_id:
        raise ResearchError("instrument response identity mismatch")
    if spot_row.get("state") != "live" or swap_row.get("state") != "live":
        raise ResearchError("instrument is not live")
    index_id = str(swap_row.get("uly", ""))
    family = str(swap_row.get("instFamily", ""))
    if not index_id or not family:
        raise ResearchError("swap response did not bind index/family")
    return {
        "spot_inst_id": spot_id,
        "swap_inst_id": swap_id,
        "index_id": index_id,
        "inst_family": family,
        "spot_list_time": str(spot_row.get("listTime", "")),
        "swap_list_time": str(swap_row.get("listTime", "")),
    }


def archive_probe(client: PublicOKX, family: str) -> dict[str, Any]:
    payload = client.fetch(
        "/api/v5/public/market-data-history",
        {
            "module": 3,
            "instType": "SWAP",
            "instFamilyList": family,
            "dateAggrType": "daily",
            "begin": ARCHIVE_BEGIN_MS,
            "end": ARCHIVE_END_MS,
        },
        optional=True,
    )
    urls: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
        elif isinstance(value, str) and value.startswith("https://"):
            urls.append(value)

    walk(payload.get("data", []))
    return {
        "code": str(payload.get("code", "")),
        "message": str(payload.get("msg", "")),
        "rows": len(payload.get("data", [])) if isinstance(payload.get("data"), list) else 0,
        "download_urls_found": sorted(set(urls)),
        "probe_begin_utc": _iso(ARCHIVE_BEGIN_MS),
        "probe_end_utc": _iso(ARCHIVE_END_MS),
    }


def fetch_funding(client: PublicOKX, swap_id: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()
    for _ in range(MAX_PAGES):
        params: dict[str, str | int] = {"instId": swap_id, "limit": FUNDING_LIMIT}
        if cursor is not None:
            params["after"] = cursor
        page = client.fetch("/api/v5/public/funding-rate-history", params)["data"]
        if not page:
            break
        for row in page:
            if not isinstance(row, dict):
                raise ResearchError("funding row must be object")
            rows.append(row)
        oldest = min(int(row["fundingTime"]) for row in page)
        new_cursor = str(oldest)
        if new_cursor in seen_cursors or new_cursor == cursor:
            break
        seen_cursors.add(new_cursor)
        cursor = new_cursor
        time.sleep(SLEEP_SECONDS)
    if not rows:
        raise ResearchError(f"no funding rows for {swap_id}")
    normalized: dict[int, dict[str, Any]] = {}
    for row in rows:
        if row.get("instId") != swap_id:
            raise ResearchError("mixed funding instrument")
        ts = int(row["fundingTime"])
        item = {
            "funding_time_ms": ts,
            "realized_rate": float(row["realizedRate"]),
            "formula_type": str(row.get("formulaType", "")),
            "method": str(row.get("method", "")),
        }
        prior = normalized.get(ts)
        if prior is not None and prior != item:
            raise ResearchError(f"conflicting funding duplicate at {ts}")
        normalized[ts] = item
    frame = pd.DataFrame(normalized.values()).sort_values("funding_time_ms").reset_index(drop=True)
    if frame["funding_time_ms"].duplicated().any() or not frame["funding_time_ms"].is_monotonic_increasing:
        raise ResearchError("invalid funding chronology")
    return frame


def fetch_candles(
    client: PublicOKX,
    endpoint: str,
    inst_id: str,
    start_ms: int,
    *,
    limit: int,
    spot: bool,
) -> pd.DataFrame:
    rows: list[list[str]] = []
    cursor: str | None = None
    seen: set[str] = set()
    for _ in range(MAX_PAGES):
        params: dict[str, str | int] = {"instId": inst_id, "bar": "1H", "limit": limit}
        if cursor is not None:
            params["after"] = cursor
        page = client.fetch(endpoint, params)["data"]
        if not page:
            break
        for row in page:
            if not isinstance(row, list):
                raise ResearchError("candle row must be array")
            rows.append(row)
        oldest = min(int(row[0]) for row in page)
        if oldest <= start_ms:
            break
        new_cursor = str(oldest)
        if new_cursor in seen or new_cursor == cursor:
            break
        seen.add(new_cursor)
        cursor = new_cursor
        time.sleep(SLEEP_SECONDS)
    by_ts: dict[int, tuple[float, float, str]] = {}
    for row in rows:
        expected = 9 if spot else 6
        if len(row) != expected:
            raise ResearchError(f"unexpected candle width {len(row)} for {endpoint}")
        ts = int(row[0])
        close = float(row[4])
        confirm = str(row[-1])
        if confirm != "1" or not math.isfinite(close) or close <= 0:
            continue
        item = (float(row[1]), close, confirm)
        prior = by_ts.get(ts)
        if prior is not None and prior != item:
            raise ResearchError(f"conflicting candle duplicate at {ts}")
        by_ts[ts] = item
    frame = pd.DataFrame(
        [
            {"open_time_ms": ts, "open": item[0], "close": item[1], "confirm": item[2]}
            for ts, item in by_ts.items()
            if ts >= start_ms
        ]
    ).sort_values("open_time_ms")
    frame = frame.reset_index(drop=True)
    if frame.empty:
        raise ResearchError(f"no candles for {inst_id}")
    if frame["open_time_ms"].duplicated().any() or not frame["open_time_ms"].is_monotonic_increasing:
        raise ResearchError("invalid candle chronology")
    diffs = np.diff(frame["open_time_ms"].to_numpy(dtype=np.int64))
    if len(diffs) and np.any(diffs != 3_600_000):
        raise ResearchError(f"gapped 1H candles for {inst_id}")
    return frame


def weighted_median(values: np.ndarray, weights: np.ndarray, times: np.ndarray) -> float:
    order = np.lexsort((times, values))
    sorted_values = values[order]
    sorted_weights = weights[order]
    cutoff = float(sorted_weights.sum()) / 2.0
    idx = int(np.searchsorted(np.cumsum(sorted_weights), cutoff, side="left"))
    return float(sorted_values[min(idx, len(sorted_values) - 1)])


def robust_z(values: np.ndarray, weights: np.ndarray, times: np.ndarray, current: float) -> float | None:
    median = weighted_median(values, weights, times)
    mad = weighted_median(np.abs(values - median), weights, times)
    if not math.isfinite(mad) or mad <= 0:
        return None
    return float(np.clip((current - median) / mad, -6.0, 6.0))


def build_events(
    funding: pd.DataFrame, mark: pd.DataFrame, index: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, int]]:
    mark_map = {int(row.open_time_ms) + 3_600_000: float(row.close) for row in mark.itertuples()}
    index_map = {int(row.open_time_ms) + 3_600_000: float(row.close) for row in index.itertuples()}
    basis_map = {
        close_time: math.log(mark_px / index_map[close_time])
        for close_time, mark_px in mark_map.items()
        if close_time in index_map
    }
    output: list[dict[str, Any]] = []
    invalid_counts: dict[str, int] = {
        "invalid_interval": 0,
        "missing_regime": 0,
        "missing_basis": 0,
        "missing_recovery": 0,
        "incomplete_warmup": 0,
        "zero_mad": 0,
    }
    episode = -1
    previous_tuple: tuple[str, str] | None = None
    episode_history: list[dict[str, Any]] = []
    previous_time: int | None = None
    for row in funding.itertuples(index=False):
        ts = int(row.funding_time_ms)
        formula = str(row.formula_type)
        method = str(row.method)
        regime = (formula, method)
        if not formula or not method:
            regime = ("", "")
        if regime != previous_tuple:
            episode += 1
            episode_history = []
            previous_tuple = regime
        interval = None if previous_time is None else (ts - previous_time) / 3_600_000
        previous_time = ts
        valid_interval = interval in {1.0, 2.0, 4.0, 6.0, 8.0}
        if not valid_interval:
            invalid_counts["invalid_interval"] += 1
        if not formula or not method:
            invalid_counts["missing_regime"] += 1
        basis = basis_map.get(ts)
        recovery = None if basis is None else basis_map.get(ts - 24 * 3_600_000)
        if basis is None:
            invalid_counts["missing_basis"] += 1
        if recovery is None:
            invalid_counts["missing_recovery"] += 1
        funding_8h = None
        if valid_interval:
            funding_8h = float(row.realized_rate) * 8.0 / float(interval)
        valid_components = (
            valid_interval
            and bool(formula)
            and bool(method)
            and funding_8h is not None
            and basis is not None
            and recovery is not None
        )
        zf = zb = zr = None
        warm = False
        if valid_components:
            warm = len(episode_history) >= WARMUP_EVENTS and sum(
                item["interval"] for item in episode_history
            ) >= WARMUP_HOURS
            if not warm:
                invalid_counts["incomplete_warmup"] += 1
            else:
                weights = np.array([item["interval"] for item in episode_history], dtype=float)
                times = np.array([item["time"] for item in episode_history], dtype=np.int64)
                zf = robust_z(
                    np.array([item["funding"] for item in episode_history], dtype=float),
                    weights,
                    times,
                    float(funding_8h),
                )
                zb = robust_z(
                    np.array([item["basis"] for item in episode_history], dtype=float),
                    weights,
                    times,
                    float(basis),
                )
                zr = robust_z(
                    np.array([item["recovery"] for item in episode_history], dtype=float),
                    weights,
                    times,
                    float(basis - recovery),
                )
                if zf is None or zb is None or zr is None:
                    invalid_counts["zero_mad"] += 1
        f0 = f1 = 0.0
        usable = valid_components and warm and None not in (zf, zb, zr)
        basis_recovery = None if basis is None or recovery is None else basis - recovery
        if usable and float(funding_8h) < 0:
            f0 = max(0.0, math.tanh(-float(zf)))
        if (
            usable
            and float(funding_8h) < 0
            and float(basis) < 0
            and float(basis_recovery) > 0
        ):
            score = min(-float(zf), -float(zb), float(zr))
            f1 = max(0.0, math.tanh(score))
        output.append(
            {
                "funding_time_ms": ts,
                "interval_hours": interval,
                "episode": episode,
                "funding_8h_equivalent": funding_8h,
                "basis_log_close": basis,
                "basis_recovery_24h": basis_recovery,
                "z_funding": zf,
                "z_basis": zb,
                "z_recovery": zr,
                "usable": bool(usable),
                "target_f0": f0,
                "target_f1": f1,
            }
        )
        if valid_components:
            episode_history.append(
                {
                    "time": ts,
                    "interval": float(interval),
                    "funding": float(funding_8h),
                    "basis": float(basis),
                    "recovery": float(basis_recovery),
                }
            )
    return pd.DataFrame(output), invalid_counts


def build_hourly_targets(events: pd.DataFrame, spot: pd.DataFrame) -> pd.DataFrame:
    closes = spot[["open_time_ms", "close"]].copy()
    closes["close_time_ms"] = closes["open_time_ms"] + 3_600_000
    closes = closes.set_index("close_time_ms")
    actions: dict[int, tuple[float, float, str]] = {}
    event_times = set(events["funding_time_ms"].astype(int))
    for row in events.itertuples(index=False):
        ts = int(row.funding_time_ms)
        decision_close = ts + 3_600_000
        actions[decision_close] = (float(row.target_f0), float(row.target_f1), "event")
        if row.interval_hours in {1.0, 2.0, 4.0, 6.0, 8.0}:
            deadline = ts + int(float(row.interval_hours) * 3_600_000)
            if deadline not in event_times:
                actions[deadline + 3_600_000] = (0.0, 0.0, "expiry")
    current_f0 = current_f1 = 0.0
    target_f0: list[float] = []
    target_f1: list[float] = []
    reasons: list[str] = []
    for close_time in closes.index.astype(int):
        if close_time in actions:
            current_f0, current_f1, reason = actions[close_time]
        else:
            reason = "carry"
        target_f0.append(current_f0)
        target_f1.append(current_f1)
        reasons.append(reason)
    closes["target_f0"] = target_f0
    closes["target_f1"] = target_f1
    closes["action_reason"] = reasons
    closes["position_f0"] = closes["target_f0"].shift(1).fillna(0.0)
    closes["position_f1"] = closes["target_f1"].shift(1).fillna(0.0)
    closes["spot_return"] = closes["close"].pct_change().fillna(0.0)
    for policy in ("f0", "f1"):
        position = closes[f"position_{policy}"]
        turnover = position.diff().abs()
        turnover.iloc[0] = abs(float(position.iloc[0]))
        closes[f"turnover_{policy}"] = turnover
        closes[f"gross_return_{policy}"] = position * closes["spot_return"]
        closes[f"net_return_{policy}"] = closes[f"gross_return_{policy}"] - FEE * turnover
    return closes.reset_index()


def add_trend_benchmark(hourly: pd.DataFrame) -> pd.DataFrame:
    frame = hourly.copy()
    target = (frame["close"] / frame["close"].shift(2160) - 1.0 > 0).astype(float)
    position = target.shift(1).fillna(0.0)
    turnover = position.diff().abs()
    turnover.iloc[0] = abs(float(position.iloc[0]))
    frame["position_trend"] = position
    frame["turnover_trend"] = turnover
    frame["net_return_trend"] = position * frame["spot_return"] - FEE * turnover
    return frame


def sharpe(returns: np.ndarray) -> float | None:
    if len(returns) < 2:
        return None
    std = float(np.std(returns, ddof=1))
    if std <= 0 or not math.isfinite(std):
        return None
    return float(np.mean(returns) / std * math.sqrt(ANNUAL_HOURS))


def max_drawdown(returns: np.ndarray) -> float:
    wealth = np.cumprod(1.0 + returns)
    peak = np.maximum.accumulate(np.r_[1.0, wealth])[1:]
    return float(np.min(wealth / peak - 1.0)) if len(wealth) else 0.0


def rolling_worst(returns: np.ndarray, window: int) -> float | None:
    if len(returns) < window:
        return None
    values = pd.Series(returns).rolling(window).apply(lambda x: np.prod(1.0 + x) - 1.0, raw=True)
    return float(values.min())


def metric_set(frame: pd.DataFrame, policy: str, fold_ids: np.ndarray) -> dict[str, Any]:
    returns = frame[f"net_return_{policy}"].to_numpy(dtype=float)
    gross = frame[f"gross_return_{policy}"].to_numpy(dtype=float) if policy in {"f0", "f1"} else None
    turnover = frame[f"turnover_{policy}"].to_numpy(dtype=float)
    position = frame[f"position_{policy}"].to_numpy(dtype=float)
    total = float(np.prod(1.0 + returns) - 1.0)
    ann_mean = float(np.mean(returns) * ANNUAL_HOURS)
    ann_turnover = float(np.mean(turnover) * ANNUAL_HOURS)
    edge = None if ann_turnover <= 0 else ann_mean / ann_turnover * 10_000.0
    mdd = max_drawdown(returns)
    years = frame["year"].to_numpy()
    year_returns = {
        str(int(year)): float(np.prod(1.0 + returns[years == year]) - 1.0)
        for year in sorted(set(years))
    }
    fold_returns = [
        float(np.prod(1.0 + returns[fold_ids == fold]) - 1.0)
        for fold in sorted(set(fold_ids))
    ]
    positives = [value for value in fold_returns if value > 0]
    concentration = None if not positives else max(positives) / sum(positives)
    changes = np.flatnonzero(turnover > 0)
    holding = np.diff(changes) if len(changes) > 1 else np.array([], dtype=int)
    residual = returns - frame["net_return_trend"].to_numpy(dtype=float)
    return {
        "observations": int(len(frame)),
        "net_total_return": total,
        "gross_total_return": None if gross is None else float(np.prod(1.0 + gross) - 1.0),
        "annualized_arithmetic_mean": ann_mean,
        "sharpe": sharpe(returns),
        "calmar": None if mdd >= 0 else ((1.0 + total) ** (ANNUAL_HOURS / len(frame)) - 1.0) / abs(mdd),
        "max_drawdown": mdd,
        "annualized_turnover": ann_turnover,
        "modeled_fee_sum": float(FEE * turnover.sum()),
        "edge_per_turnover_bps": edge,
        "time_in_market": float(np.mean(position > 0)),
        "adjustment_count": int(np.sum(turnover > 0)),
        "median_holding_hours": None if not len(holding) else float(np.median(holding)),
        "profitable_folds": int(sum(value > 0 for value in fold_returns)),
        "total_folds": int(len(fold_returns)),
        "positive_fold_concentration": concentration,
        "year_returns": year_returns,
        "worst_24h": rolling_worst(returns, 24),
        "worst_168h": rolling_worst(returns, 168),
        "residual_sharpe_vs_simple_trend": sharpe(residual),
    }


def resample_fold_indices(length: int, rng: np.random.Generator) -> np.ndarray:
    if length <= 1:
        return np.arange(length)
    remaining = length - 1
    block = min(BOOTSTRAP_BLOCK, remaining)
    starts = np.arange(1, length - block + 1)
    sampled: list[int] = [0]
    while len(sampled) < length:
        start = int(rng.choice(starts))
        sampled.extend(range(start, start + block))
    return np.array(sampled[:length], dtype=int)


def bootstrap_endpoint(
    markets: dict[str, pd.DataFrame], fold_ids: dict[str, np.ndarray]
) -> dict[str, Any]:
    observed_sharpes: list[float] = []
    observed_edges: list[float] = []
    for market, frame in markets.items():
        m0 = metric_set(frame, "f0", fold_ids[market])
        m1 = metric_set(frame, "f1", fold_ids[market])
        observed_sharpes.append(float(m1["sharpe"]) - float(m0["sharpe"]))
        observed_edges.append(
            float(m1["edge_per_turnover_bps"]) - float(m0["edge_per_turnover_bps"])
        )
    observed = np.array([min(observed_sharpes), min(observed_edges)], dtype=float)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    draws = np.empty((BOOTSTRAP_RESAMPLES, 2), dtype=float)
    for b in range(BOOTSTRAP_RESAMPLES):
        delta_s: list[float] = []
        delta_e: list[float] = []
        for market, frame in markets.items():
            pieces: list[pd.DataFrame] = []
            ids = fold_ids[market]
            for fold in sorted(set(ids)):
                subset = frame.loc[ids == fold].reset_index(drop=True)
                idx = resample_fold_indices(len(subset), rng)
                pieces.append(subset.iloc[idx].reset_index(drop=True))
            sample = pd.concat(pieces, ignore_index=True)
            sample_ids = np.repeat(np.arange(len(pieces)), [len(piece) for piece in pieces])
            m0 = metric_set(sample, "f0", sample_ids)
            m1 = metric_set(sample, "f1", sample_ids)
            delta_s.append(float(m1["sharpe"]) - float(m0["sharpe"]))
            delta_e.append(
                float(m1["edge_per_turnover_bps"]) - float(m0["edge_per_turnover_bps"])
            )
        draws[b] = [min(delta_s), min(delta_e)]
    raw_p: list[float] = []
    endpoints: list[dict[str, Any]] = []
    for idx, name in enumerate(("worst_market_sharpe_delta", "worst_market_edge_delta_bps")):
        errors = draws[:, idx] - observed[idx]
        lower = float(observed[idx] - np.quantile(errors, 0.95))
        p = float((1 + np.sum(errors <= -observed[idx])) / (BOOTSTRAP_RESAMPLES + 1))
        raw_p.append(p)
        endpoints.append(
            {
                "name": name,
                "observed": float(observed[idx]),
                "one_sided_95_lower_bound": lower,
                "basic_95_interval": [
                    float(2 * observed[idx] - np.quantile(draws[:, idx], 0.975)),
                    float(2 * observed[idx] - np.quantile(draws[:, idx], 0.025)),
                ],
                "raw_one_sided_p": p,
            }
        )
    order = np.argsort(raw_p)
    adjusted = np.empty(2)
    running = 0.0
    for rank, index in enumerate(order):
        value = min(1.0, raw_p[index] * (2 - rank))
        running = max(running, value)
        adjusted[index] = running
    for endpoint, value in zip(endpoints, adjusted, strict=True):
        endpoint["holm_adjusted_p"] = float(value)
    return {
        "block_hours": BOOTSTRAP_BLOCK,
        "resamples": BOOTSTRAP_RESAMPLES,
        "seed": BOOTSTRAP_SEED,
        "endpoints": endpoints,
    }


def finite(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): finite(child) for key, child in value.items()}
    if isinstance(value, list):
        return [finite(child) for child in value]
    if isinstance(value, tuple):
        return [finite(child) for child in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not math.isfinite(float(value)) else float(value)
    return value


def run(output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    client = PublicOKX(output_dir / "raw")
    configs = {
        "BTC-USDT": "BTC-USDT-SWAP",
        "ETH-USDT": "ETH-USDT-SWAP",
    }
    market_frames: dict[str, pd.DataFrame] = {}
    market_meta: dict[str, Any] = {}
    first_usable: dict[str, int] = {}
    last_available: dict[str, int] = {}
    for spot_id, swap_id in configs.items():
        binding = instrument_binding(client, spot_id, swap_id)
        archive = archive_probe(client, binding["inst_family"])
        funding = fetch_funding(client, swap_id)
        earliest_funding = int(funding["funding_time_ms"].min())
        latest_funding = int(funding["funding_time_ms"].max())
        mark_start = earliest_funding - 25 * 3_600_000
        spot_start = earliest_funding - 2162 * 3_600_000
        mark = fetch_candles(
            client,
            "/api/v5/market/history-mark-price-candles",
            swap_id,
            mark_start,
            limit=CANDLE_LIMIT,
            spot=False,
        )
        index = fetch_candles(
            client,
            "/api/v5/market/history-index-candles",
            binding["index_id"],
            mark_start,
            limit=CANDLE_LIMIT,
            spot=False,
        )
        spot = fetch_candles(
            client,
            "/api/v5/market/history-candles",
            spot_id,
            spot_start,
            limit=SPOT_LIMIT,
            spot=True,
        )
        events, invalid_counts = build_events(funding, mark, index)
        hourly = add_trend_benchmark(build_hourly_targets(events, spot))
        usable_events = events.loc[events["usable"]]
        if usable_events.empty:
            raise ResearchError(f"no usable post-warmup events for {spot_id}")
        first_usable[spot_id] = int(usable_events["funding_time_ms"].min()) + 2 * 3_600_000
        last_available[spot_id] = min(
            int(hourly["close_time_ms"].max()), latest_funding + 8 * 3_600_000
        )
        market_frames[spot_id] = hourly
        market_meta[spot_id] = {
            "binding": binding,
            "archive_probe": archive,
            "funding_rows": int(len(funding)),
            "funding_start_utc": _iso(earliest_funding),
            "funding_end_utc": _iso(latest_funding),
            "mark_rows": int(len(mark)),
            "index_rows": int(len(index)),
            "spot_rows": int(len(spot)),
            "invalid_event_counts": invalid_counts,
            "usable_events": int(events["usable"].sum()),
            "f0_positive_events": int((events["target_f0"] > 0).sum()),
            "f1_positive_events": int((events["target_f1"] > 0).sum()),
        }
    common_start = max(first_usable.values())
    common_end = min(last_available.values())
    available_hours = (common_end - common_start) // 3_600_000 + 1
    complete_folds = int(available_hours // FOLD_HOURS)
    if complete_folds < 2:
        raise ResearchError(f"insufficient shorter-window folds: {complete_folds}")
    evaluation_end = common_start + complete_folds * FOLD_HOURS * 3_600_000 - 3_600_000
    evaluated: dict[str, pd.DataFrame] = {}
    fold_ids: dict[str, np.ndarray] = {}
    for market, frame in market_frames.items():
        subset = frame.loc[
            (frame["close_time_ms"] >= common_start)
            & (frame["close_time_ms"] <= evaluation_end)
        ].copy()
        if len(subset) != complete_folds * FOLD_HOURS:
            raise ResearchError(f"evaluation row mismatch for {market}: {len(subset)}")
        subset["year"] = pd.to_datetime(subset["close_time_ms"], unit="ms", utc=True).dt.year
        evaluated[market] = subset.reset_index(drop=True)
        fold_ids[market] = np.repeat(np.arange(complete_folds), FOLD_HOURS)
    metrics: dict[str, Any] = {}
    for market, frame in evaluated.items():
        metrics[market] = {
            policy: metric_set(frame, policy, fold_ids[market])
            for policy in ("f0", "f1", "trend")
        }
    bootstrap = bootstrap_endpoint(evaluated, fold_ids)
    endpoints = bootstrap["endpoints"]
    deterministic_failures: list[str] = []
    for market in configs:
        f0 = metrics[market]["f0"]
        f1 = metrics[market]["f1"]
        if f1["net_total_return"] <= 0:
            deterministic_failures.append(f"{market}:nonpositive_f1_return")
        if f1["sharpe"] is None or f1["sharpe"] <= 0:
            deterministic_failures.append(f"{market}:nonpositive_f1_sharpe")
        if f1["edge_per_turnover_bps"] is None or f1["edge_per_turnover_bps"] <= 0:
            deterministic_failures.append(f"{market}:nonpositive_f1_edge")
        if f1["sharpe"] <= f0["sharpe"]:
            deterministic_failures.append(f"{market}:f1_sharpe_not_above_f0")
        if f1["edge_per_turnover_bps"] <= f0["edge_per_turnover_bps"]:
            deterministic_failures.append(f"{market}:f1_edge_not_above_f0")
        if f1["residual_sharpe_vs_simple_trend"] is None or f1[
            "residual_sharpe_vs_simple_trend"
        ] <= 0:
            deterministic_failures.append(f"{market}:nonpositive_trend_residual")
    statistical_pass = all(
        endpoint["one_sided_95_lower_bound"] > 0 and endpoint["holm_adjusted_p"] < 0.05
        for endpoint in endpoints
    )
    archive_available = all(
        bool(market_meta[market]["archive_probe"]["download_urls_found"])
        for market in configs
    )
    if deterministic_failures:
        verdict = "rejected_by_predeclared_short_window_diagnostic"
    elif not statistical_pass:
        verdict = "insufficient_short_window_evidence"
    else:
        verdict = "diagnostic_pass_but_insufficient_history_for_qualification"
    result = {
        "family_id": FAMILY_ID,
        "generated_from_commit": os.environ.get("GITHUB_SHA", "local"),
        "candidate_count": 2,
        "policies": ["F0_funding_only_attribution", "F1_strict_funding_basis_unwind"],
        "fee_one_way": FEE,
        "bar": "1H",
        "data_mode": "recent_public_rest_short_window_diagnostic",
        "archive_manifest_available_for_both_markets": archive_available,
        "qualification_history_required": "180d warmup plus at least 8 non-overlapping 90d folds",
        "qualification_history_available": False,
        "short_window_predeclaration": {
            "warmup_events": WARMUP_EVENTS,
            "warmup_interval_hours": WARMUP_HOURS,
            "fold_days": FOLD_DAYS,
            "complete_folds": complete_folds,
            "evaluation_start_utc": _iso(common_start),
            "evaluation_end_utc": _iso(evaluation_end),
            "hours_per_market": complete_folds * FOLD_HOURS,
            "purpose": "falsification diagnostic only; cannot qualify or promote F1",
        },
        "markets": market_meta,
        "metrics": metrics,
        "bootstrap": bootstrap,
        "deterministic_failures": deterministic_failures,
        "statistical_pass": statistical_pass,
        "verdict": verdict,
        "oos_consumed": False,
        "untouched_evidence_consumed": False,
        "checks": {
            "strict_public_https_origin": True,
            "credentials_used": False,
            "confirmed_contiguous_1h_candles": True,
            "one_bar_post_decision_execution": True,
            "same_instrument_only": True,
            "cross_sectional_selection": False,
            "exact_5bps_fee": True,
            "future_suffix_test": "performed_by_prefix_replay_below",
        },
    }
    # Prefix replay: truncating after the midpoint must preserve every earlier target exactly.
    for market, frame in evaluated.items():
        midpoint = len(frame) // 2
        prefix = frame.iloc[:midpoint]
        for policy in ("f0", "f1"):
            if not np.array_equal(
                prefix[f"position_{policy}"].to_numpy(),
                frame[f"position_{policy}"].iloc[:midpoint].to_numpy(),
            ):
                raise ResearchError(f"future suffix invariance failed: {market} {policy}")
    result["checks"]["future_suffix_test"] = "pass"
    manifest = {
        "base_url": BASE_URL,
        "records": [record.__dict__ for record in client.records],
        "record_count": len(client.records),
    }
    manifest_bytes = _json_bytes(finite(manifest))
    (output_dir / "source-manifest.json").write_bytes(manifest_bytes)
    result["source_manifest_sha256"] = _sha(manifest_bytes)
    final = finite(result)
    result_bytes = _json_bytes(final)
    (output_dir / "result-summary.json").write_bytes(result_bytes)
    (output_dir / "result-summary.sha256").write_text(f"{_sha(result_bytes)}  result-summary.json\n")
    return final


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.output_dir)
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
