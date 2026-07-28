#!/usr/bin/env python3
"""Execute the frozen causal funding/basis crowding-unwind v2 family.

The run uses only public unauthenticated OKX endpoints, persists every exact
response byte, applies exactly 5 bps one-way fees, and emits a strict JSON
strategy verdict.  The recent REST window is a falsification diagnostic only;
it cannot qualify a strategy that requires the historical archive design.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

BASE = "https://www.okx.com"
FEE = 0.0005
YEAR_HOURS = 8760.0
HOUR_MS = 3_600_000
FUNDING_LIMIT = 400
CANDLE_LIMIT = 100
SPOT_LIMIT = 300
MAX_PAGES = 80
MAX_BYTES = 4_000_000
WARMUP_EVENTS = 30
WARMUP_HOURS = 240
FOLD_HOURS = 14 * 24
BLOCK_HOURS = 168
RESAMPLES = 5000
SEED = 20260728
ARCHIVE_BEGIN = 1782864000000
ARCHIVE_END = 1783036800000
FAMILY = "funding-basis-crowding-unwind-v2"


class ResearchError(RuntimeError):
    """Fail-closed strategy research error."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise ResearchError(f"redirect rejected: {code} {newurl}")


def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ResearchError(f"duplicate JSON field: {key}")
        value[key] = item
    return value


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).isoformat()


def finite(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): finite(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [finite(item) for item in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(float(value)) else None
    return value


@dataclass(frozen=True)
class SourceRecord:
    ordinal: int
    url: str
    status: int
    received_at_utc: str
    byte_length: int
    sha256: str
    relative_path: str


class OKX:
    def __init__(self, raw_dir: Path) -> None:
        self.raw_dir = raw_dir
        raw_dir.mkdir(parents=True, exist_ok=True)
        self.records: list[SourceRecord] = []
        self.opener = urllib.request.build_opener(
            NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context())
        )

    def get(
        self,
        path: str,
        params: dict[str, str | int],
        *,
        optional: bool = False,
    ) -> dict[str, Any]:
        query = urllib.parse.urlencode(sorted((key, str(value)) for key, value in params.items()))
        url = f"{BASE}{path}?{query}"
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != "www.okx.com":
            raise ResearchError(f"untrusted origin: {url}")
        request = urllib.request.Request(
            url,
            method="GET",
            headers={"Accept": "application/json", "User-Agent": "gpt-quant-lab/0.2"},
        )
        error: Exception | None = None
        for attempt in range(5):
            try:
                with self.opener.open(request, timeout=30) as response:
                    status = int(response.status)
                    raw = response.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES:
                    raise ResearchError(f"oversized response: {url}")
                if status != 200:
                    raise ResearchError(f"HTTP {status}: {url}")
                return self._persist(url, status, raw, optional)
            except (urllib.error.URLError, TimeoutError, ResearchError) as exc:
                error = exc
                if "redirect rejected" in str(exc):
                    raise
                if attempt < 4:
                    time.sleep(0.5 * (2**attempt))
        if optional:
            raw = canonical_bytes({"code": "optional_fetch_failed", "msg": str(error), "data": []})
            return self._persist(url, 0, raw, True)
        raise ResearchError(f"request failed: {url}: {error}")

    def _persist(
        self, url: str, status: int, raw: bytes, optional: bool
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
                sha256=sha256(raw),
                relative_path=str(path.relative_to(self.raw_dir.parent)),
            )
        )
        try:
            payload = json.loads(raw.decode(), object_pairs_hook=strict_object)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            if optional:
                return {"code": "optional_parse_failed", "msg": str(exc), "data": []}
            raise ResearchError(f"invalid JSON: {url}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ResearchError(f"top-level response is not an object: {url}")
        if optional and payload.get("code") != "0":
            return payload
        if set(payload) != {"code", "msg", "data"}:
            raise ResearchError(f"unexpected response fields: {url}: {sorted(payload)}")
        if payload["code"] != "0" or payload["msg"] != "":
            raise ResearchError(f"OKX error: {url}: {payload['code']} {payload['msg']}")
        if not isinstance(payload["data"], list):
            raise ResearchError(f"response data is not a list: {url}")
        return payload


def bind_instruments(client: OKX, spot_id: str, swap_id: str) -> dict[str, str]:
    spot = client.get(
        "/api/v5/public/instruments", {"instType": "SPOT", "instId": spot_id}
    )["data"]
    swap = client.get(
        "/api/v5/public/instruments", {"instType": "SWAP", "instId": swap_id}
    )["data"]
    if len(spot) != 1 or len(swap) != 1:
        raise ResearchError(f"ambiguous binding: {spot_id} {swap_id}")
    spot_row, swap_row = spot[0], swap[0]
    if spot_row.get("instId") != spot_id or swap_row.get("instId") != swap_id:
        raise ResearchError("instrument identity mismatch")
    if spot_row.get("state") != "live" or swap_row.get("state") != "live":
        raise ResearchError("instrument is not live")
    index_id = str(swap_row.get("uly", ""))
    family = str(swap_row.get("instFamily", ""))
    if not index_id or not family:
        raise ResearchError("swap response did not bind an index and family")
    return {
        "spot_inst_id": spot_id,
        "swap_inst_id": swap_id,
        "index_id": index_id,
        "inst_family": family,
        "spot_list_time": str(spot_row.get("listTime", "")),
        "swap_list_time": str(swap_row.get("listTime", "")),
    }


def probe_archive(client: OKX, family: str) -> dict[str, Any]:
    response = client.get(
        "/api/v5/public/market-data-history",
        {
            "module": 3,
            "instType": "SWAP",
            "instFamilyList": family,
            "dateAggrType": "daily",
            "begin": ARCHIVE_BEGIN,
            "end": ARCHIVE_END,
        },
        optional=True,
    )
    urls: list[str] = []

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            for child in item.values():
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)
        elif isinstance(item, str) and item.startswith("https://"):
            urls.append(item)

    walk(response.get("data", []))
    data = response.get("data", [])
    return {
        "code": str(response.get("code", "")),
        "message": str(response.get("msg", "")),
        "rows": len(data) if isinstance(data, list) else 0,
        "download_urls_found": sorted(set(urls)),
        "probe_begin_utc": iso(ARCHIVE_BEGIN),
        "probe_end_utc": iso(ARCHIVE_END),
    }


def fetch_funding(client: OKX, swap_id: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    cursor: str | None = None
    seen: set[str] = set()
    for _ in range(MAX_PAGES):
        params: dict[str, str | int] = {"instId": swap_id, "limit": FUNDING_LIMIT}
        if cursor is not None:
            params["after"] = cursor
        page = client.get("/api/v5/public/funding-rate-history", params)["data"]
        if not page:
            break
        if not all(isinstance(row, dict) for row in page):
            raise ResearchError("funding page contains a non-object row")
        rows.extend(page)
        next_cursor = str(min(int(row["fundingTime"]) for row in page))
        if next_cursor == cursor or next_cursor in seen:
            break
        seen.add(next_cursor)
        cursor = next_cursor
        time.sleep(0.12)
    if not rows:
        raise ResearchError(f"empty funding history: {swap_id}")
    unique: dict[int, dict[str, Any]] = {}
    for row in rows:
        if row.get("instId") != swap_id:
            raise ResearchError("mixed funding instrument")
        timestamp = int(row["fundingTime"])
        item = {
            "funding_time_ms": timestamp,
            "realized_rate": float(row["realizedRate"]),
            "formula_type": str(row.get("formulaType", "")),
            "method": str(row.get("method", "")),
        }
        if timestamp in unique and unique[timestamp] != item:
            raise ResearchError(f"conflicting funding duplicate: {timestamp}")
        unique[timestamp] = item
    frame = pd.DataFrame(unique.values()).sort_values("funding_time_ms").reset_index(drop=True)
    if frame["funding_time_ms"].duplicated().any() or not frame[
        "funding_time_ms"
    ].is_monotonic_increasing:
        raise ResearchError("invalid funding chronology")
    return frame


def validate_candles(frame: pd.DataFrame, identity: str) -> None:
    if frame.empty:
        raise ResearchError(f"empty candle frame: {identity}")
    if frame["open_time_ms"].duplicated().any() or not frame[
        "open_time_ms"
    ].is_monotonic_increasing:
        raise ResearchError(f"invalid candle chronology: {identity}")
    differences = np.diff(frame["open_time_ms"].to_numpy(dtype=np.int64))
    if len(differences) and np.any(differences != HOUR_MS):
        raise ResearchError(f"gapped 1H candles: {identity}")


def fetch_candles(
    client: OKX,
    endpoint: str,
    inst_id: str,
    start_ms: int,
    *,
    spot: bool,
) -> pd.DataFrame:
    limit = SPOT_LIMIT if spot else CANDLE_LIMIT
    rows: list[list[str]] = []
    cursor: str | None = None
    seen: set[str] = set()
    for _ in range(MAX_PAGES):
        params: dict[str, str | int] = {"instId": inst_id, "bar": "1H", "limit": limit}
        if cursor is not None:
            params["after"] = cursor
        page = client.get(endpoint, params)["data"]
        if not page:
            break
        if not all(isinstance(row, list) for row in page):
            raise ResearchError("candle page contains a non-array row")
        rows.extend(page)
        oldest = min(int(row[0]) for row in page)
        if oldest <= start_ms:
            break
        next_cursor = str(oldest)
        if next_cursor == cursor or next_cursor in seen:
            break
        seen.add(next_cursor)
        cursor = next_cursor
        time.sleep(0.12)
    expected_width = 9 if spot else 6
    unique: dict[int, tuple[float, float]] = {}
    for row in rows:
        if len(row) != expected_width:
            raise ResearchError(f"unexpected candle width: {endpoint}: {len(row)}")
        timestamp = int(row[0])
        open_price, close_price = float(row[1]), float(row[4])
        if str(row[-1]) != "1":
            continue
        if min(open_price, close_price) <= 0 or not all(
            math.isfinite(value) for value in (open_price, close_price)
        ):
            raise ResearchError("non-positive or non-finite candle price")
        item = (open_price, close_price)
        if timestamp in unique and unique[timestamp] != item:
            raise ResearchError(f"conflicting candle duplicate: {timestamp}")
        unique[timestamp] = item
    frame = pd.DataFrame(
        [
            {"open_time_ms": timestamp, "open": value[0], "close": value[1]}
            for timestamp, value in unique.items()
            if timestamp >= start_ms
        ]
    ).sort_values("open_time_ms", ignore_index=True)
    validate_candles(frame, inst_id)
    return frame


def weighted_median(values: np.ndarray, weights: np.ndarray, times: np.ndarray) -> float:
    order = np.lexsort((times, values))
    values, weights = values[order], weights[order]
    index = int(np.searchsorted(np.cumsum(weights), weights.sum() / 2.0, side="left"))
    return float(values[min(index, len(values) - 1)])


def robust_z(
    history: list[dict[str, float]], field: str, current: float
) -> float | None:
    values = np.array([item[field] for item in history], dtype=float)
    weights = np.array([item["interval"] for item in history], dtype=float)
    times = np.array([item["time"] for item in history], dtype=np.int64)
    median = weighted_median(values, weights, times)
    mad = weighted_median(np.abs(values - median), weights, times)
    if not math.isfinite(mad) or mad <= 0:
        return None
    return float(np.clip((current - median) / mad, -6.0, 6.0))


def build_events(
    funding: pd.DataFrame, mark: pd.DataFrame, index: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, int]]:
    mark_by_close = {
        int(row.open_time_ms) + HOUR_MS: float(row.close) for row in mark.itertuples()
    }
    index_by_close = {
        int(row.open_time_ms) + HOUR_MS: float(row.close) for row in index.itertuples()
    }
    basis = {
        timestamp: math.log(mark_price / index_by_close[timestamp])
        for timestamp, mark_price in mark_by_close.items()
        if timestamp in index_by_close
    }
    counts = {
        "invalid_interval": 0,
        "missing_regime": 0,
        "missing_basis": 0,
        "missing_recovery": 0,
        "incomplete_warmup": 0,
        "zero_mad": 0,
    }
    output: list[dict[str, Any]] = []
    previous_time: int | None = None
    previous_regime: tuple[str, str] | None = None
    episode = -1
    history: list[dict[str, float]] = []
    for row in funding.itertuples(index=False):
        timestamp = int(row.funding_time_ms)
        formula, method = str(row.formula_type), str(row.method)
        regime = (formula, method)
        if regime != previous_regime:
            episode += 1
            history = []
            previous_regime = regime
        interval = None if previous_time is None else (timestamp - previous_time) / HOUR_MS
        previous_time = timestamp
        interval_ok = interval in {1.0, 2.0, 4.0, 6.0, 8.0}
        if not interval_ok:
            counts["invalid_interval"] += 1
        if not formula or not method:
            counts["missing_regime"] += 1
        current_basis = basis.get(timestamp)
        prior_basis = basis.get(timestamp - 24 * HOUR_MS)
        if current_basis is None:
            counts["missing_basis"] += 1
        if prior_basis is None:
            counts["missing_recovery"] += 1
        recovery = (
            None if current_basis is None or prior_basis is None else current_basis - prior_basis
        )
        funding_8h = (
            None
            if not interval_ok
            else float(row.realized_rate) * 8.0 / float(interval)
        )
        components_ok = (
            interval_ok
            and bool(formula)
            and bool(method)
            and funding_8h is not None
            and current_basis is not None
            and recovery is not None
        )
        warm = len(history) >= WARMUP_EVENTS and sum(
            item["interval"] for item in history
        ) >= WARMUP_HOURS
        if components_ok and not warm:
            counts["incomplete_warmup"] += 1
        z_funding = z_basis = z_recovery = None
        if components_ok and warm:
            z_funding = robust_z(history, "funding", float(funding_8h))
            z_basis = robust_z(history, "basis", float(current_basis))
            z_recovery = robust_z(history, "recovery", float(recovery))
            if None in (z_funding, z_basis, z_recovery):
                counts["zero_mad"] += 1
        usable = components_ok and warm and None not in (z_funding, z_basis, z_recovery)
        target_f0 = 0.0
        target_f1 = 0.0
        if usable and float(funding_8h) < 0:
            target_f0 = max(0.0, math.tanh(-float(z_funding)))
        if (
            usable
            and float(funding_8h) < 0
            and float(current_basis) < 0
            and float(recovery) > 0
        ):
            target_f1 = max(
                0.0,
                math.tanh(min(-float(z_funding), -float(z_basis), float(z_recovery))),
            )
        output.append(
            {
                "funding_time_ms": timestamp,
                "interval_hours": interval,
                "episode": episode,
                "funding_8h_equivalent": funding_8h,
                "basis_log_close": current_basis,
                "basis_recovery_24h": recovery,
                "z_funding": z_funding,
                "z_basis": z_basis,
                "z_recovery": z_recovery,
                "usable": bool(usable),
                "target_f0": target_f0,
                "target_f1": target_f1,
            }
        )
        if components_ok:
            history.append(
                {
                    "time": float(timestamp),
                    "interval": float(interval),
                    "funding": float(funding_8h),
                    "basis": float(current_basis),
                    "recovery": float(recovery),
                }
            )
    return pd.DataFrame(output), counts


def build_hourly(events: pd.DataFrame, spot: pd.DataFrame) -> pd.DataFrame:
    frame = spot[["open_time_ms", "close"]].copy()
    frame["close_time_ms"] = frame["open_time_ms"] + HOUR_MS
    frame = frame.set_index("close_time_ms")
    event_times = set(events["funding_time_ms"].astype(int))
    actions: dict[int, tuple[float, float, str]] = {}
    for row in events.itertuples(index=False):
        timestamp = int(row.funding_time_ms)
        actions[timestamp + HOUR_MS] = (
            float(row.target_f0),
            float(row.target_f1),
            "event",
        )
        if row.interval_hours in {1.0, 2.0, 4.0, 6.0, 8.0}:
            deadline = timestamp + int(float(row.interval_hours) * HOUR_MS)
            if deadline not in event_times:
                actions[deadline + HOUR_MS] = (0.0, 0.0, "expiry")
    current_f0 = current_f1 = 0.0
    targets_f0: list[float] = []
    targets_f1: list[float] = []
    reasons: list[str] = []
    for timestamp in frame.index.astype(int):
        if timestamp in actions:
            current_f0, current_f1, reason = actions[timestamp]
        else:
            reason = "carry"
        targets_f0.append(current_f0)
        targets_f1.append(current_f1)
        reasons.append(reason)
    frame["target_f0"] = targets_f0
    frame["target_f1"] = targets_f1
    frame["action_reason"] = reasons
    frame["spot_return"] = frame["close"].pct_change().fillna(0.0)
    for policy in ("f0", "f1"):
        frame[f"position_{policy}"] = frame[f"target_{policy}"].shift(1).fillna(0.0)
        turnover = frame[f"position_{policy}"].diff().abs()
        turnover.iloc[0] = abs(float(frame[f"position_{policy}"].iloc[0]))
        frame[f"turnover_{policy}"] = turnover
        frame[f"gross_return_{policy}"] = frame[f"position_{policy}"] * frame["spot_return"]
        frame[f"net_return_{policy}"] = (
            frame[f"gross_return_{policy}"] - FEE * turnover
        )
    trend_target = (frame["close"] / frame["close"].shift(2160) - 1.0 > 0).astype(float)
    frame["position_trend"] = trend_target.shift(1).fillna(0.0)
    trend_turnover = frame["position_trend"].diff().abs()
    trend_turnover.iloc[0] = abs(float(frame["position_trend"].iloc[0]))
    frame["turnover_trend"] = trend_turnover
    frame["net_return_trend"] = (
        frame["position_trend"] * frame["spot_return"] - FEE * trend_turnover
    )
    return frame.reset_index()


def sharpe(returns: np.ndarray) -> float | None:
    if len(returns) < 2:
        return None
    deviation = float(np.std(returns, ddof=1))
    if deviation <= 0 or not math.isfinite(deviation):
        return None
    return float(np.mean(returns) / deviation * math.sqrt(YEAR_HOURS))


def drawdown(returns: np.ndarray) -> float:
    wealth = np.cumprod(1.0 + returns)
    peaks = np.maximum.accumulate(np.r_[1.0, wealth])[1:]
    return float(np.min(wealth / peaks - 1.0)) if len(wealth) else 0.0


def rolling_worst(returns: np.ndarray, hours: int) -> float | None:
    if len(returns) < hours:
        return None
    values = pd.Series(returns).rolling(hours).apply(
        lambda item: np.prod(1.0 + item) - 1.0, raw=True
    )
    return float(values.min())


def metrics(frame: pd.DataFrame, policy: str, fold_ids: np.ndarray) -> dict[str, Any]:
    returns = frame[f"net_return_{policy}"].to_numpy(dtype=float)
    turnover = frame[f"turnover_{policy}"].to_numpy(dtype=float)
    positions = frame[f"position_{policy}"].to_numpy(dtype=float)
    total_return = float(np.prod(1.0 + returns) - 1.0)
    annual_mean = float(np.mean(returns) * YEAR_HOURS)
    annual_turnover = float(np.mean(turnover) * YEAR_HOURS)
    maximum_drawdown = drawdown(returns)
    edge = None if annual_turnover <= 0 else annual_mean / annual_turnover * 10_000.0
    fold_returns = [
        float(np.prod(1.0 + returns[fold_ids == fold]) - 1.0)
        for fold in sorted(set(fold_ids))
    ]
    positive = [value for value in fold_returns if value > 0]
    years = frame["year"].to_numpy(dtype=int)
    changes = np.flatnonzero(turnover > 0)
    holding = np.diff(changes) if len(changes) > 1 else np.array([], dtype=int)
    residual = returns - frame["net_return_trend"].to_numpy(dtype=float)
    gross = (
        frame[f"gross_return_{policy}"].to_numpy(dtype=float)
        if policy in {"f0", "f1"}
        else None
    )
    return {
        "observations": int(len(frame)),
        "net_total_return": total_return,
        "gross_total_return": (
            None if gross is None else float(np.prod(1.0 + gross) - 1.0)
        ),
        "annualized_arithmetic_mean": annual_mean,
        "sharpe": sharpe(returns),
        "calmar": (
            None
            if maximum_drawdown >= 0
            else ((1.0 + total_return) ** (YEAR_HOURS / len(frame)) - 1.0)
            / abs(maximum_drawdown)
        ),
        "max_drawdown": maximum_drawdown,
        "annualized_turnover": annual_turnover,
        "modeled_fee_sum": float(FEE * turnover.sum()),
        "edge_per_turnover_bps": edge,
        "time_in_market": float(np.mean(positions > 0)),
        "adjustment_count": int(np.sum(turnover > 0)),
        "median_holding_hours": None if not len(holding) else float(np.median(holding)),
        "profitable_folds": int(sum(value > 0 for value in fold_returns)),
        "total_folds": int(len(fold_returns)),
        "positive_fold_concentration": (
            None if not positive else max(positive) / sum(positive)
        ),
        "year_returns": {
            str(year): float(np.prod(1.0 + returns[years == year]) - 1.0)
            for year in sorted(set(years))
        },
        "worst_24h": rolling_worst(returns, 24),
        "worst_168h": rolling_worst(returns, 168),
        "residual_sharpe_vs_simple_trend": sharpe(residual),
    }


def sample_indices(length: int, rng: np.random.Generator) -> np.ndarray:
    if length <= 1:
        return np.arange(length)
    block = min(BLOCK_HOURS, length - 1)
    starts = np.arange(1, length - block + 1)
    selected: list[int] = [0]
    while len(selected) < length:
        start = int(rng.choice(starts))
        selected.extend(range(start, start + block))
    return np.array(selected[:length], dtype=int)


def fast_sharpe(frame: pd.DataFrame, policy: str) -> float | None:
    return sharpe(frame[f"net_return_{policy}"].to_numpy(dtype=float))


def fast_edge(frame: pd.DataFrame, policy: str) -> float | None:
    annual_mean = float(frame[f"net_return_{policy}"].mean() * YEAR_HOURS)
    annual_turnover = float(frame[f"turnover_{policy}"].mean() * YEAR_HOURS)
    return None if annual_turnover <= 0 else annual_mean / annual_turnover * 10_000.0


def bootstrap(
    frames: dict[str, pd.DataFrame], fold_ids: dict[str, np.ndarray]
) -> dict[str, Any]:
    observed_sharpe: list[float] = []
    observed_edge: list[float] = []
    edge_available = True
    for market, frame in frames.items():
        delta_sharpe = float(fast_sharpe(frame, "f1")) - float(fast_sharpe(frame, "f0"))
        observed_sharpe.append(delta_sharpe)
        edge_f0, edge_f1 = fast_edge(frame, "f0"), fast_edge(frame, "f1")
        if edge_f0 is None or edge_f1 is None:
            edge_available = False
        else:
            observed_edge.append(edge_f1 - edge_f0)
    observed = [min(observed_sharpe), min(observed_edge) if edge_available else None]
    rng = np.random.default_rng(SEED)
    draws_sharpe: list[float] = []
    draws_edge: list[float] = []
    for _ in range(RESAMPLES):
        market_sharpe: list[float] = []
        market_edge: list[float] = []
        draw_edge_available = edge_available
        for market, frame in frames.items():
            pieces: list[pd.DataFrame] = []
            ids = fold_ids[market]
            for fold in sorted(set(ids)):
                subset = frame.loc[ids == fold].reset_index(drop=True)
                pieces.append(subset.iloc[sample_indices(len(subset), rng)])
            sample = pd.concat(pieces, ignore_index=True)
            market_sharpe.append(
                float(fast_sharpe(sample, "f1")) - float(fast_sharpe(sample, "f0"))
            )
            edge_f0, edge_f1 = fast_edge(sample, "f0"), fast_edge(sample, "f1")
            if edge_f0 is None or edge_f1 is None:
                draw_edge_available = False
            else:
                market_edge.append(edge_f1 - edge_f0)
        draws_sharpe.append(min(market_sharpe))
        if draw_edge_available:
            draws_edge.append(min(market_edge))
    endpoints: list[dict[str, Any]] = []
    raw_p: list[float | None] = []
    for name, point, values in (
        ("worst_market_sharpe_delta", observed[0], np.array(draws_sharpe)),
        ("worst_market_edge_delta_bps", observed[1], np.array(draws_edge)),
    ):
        if point is None or len(values) != RESAMPLES:
            endpoints.append(
                {
                    "name": name,
                    "available": False,
                    "reason": "zero-turnover edge is undefined",
                }
            )
            raw_p.append(None)
            continue
        errors = values - float(point)
        p_value = float((1 + np.sum(errors <= -float(point))) / (RESAMPLES + 1))
        endpoints.append(
            {
                "name": name,
                "available": True,
                "observed": float(point),
                "one_sided_95_lower_bound": float(point - np.quantile(errors, 0.95)),
                "basic_95_interval": [
                    float(2 * point - np.quantile(values, 0.975)),
                    float(2 * point - np.quantile(values, 0.025)),
                ],
                "raw_one_sided_p": p_value,
            }
        )
        raw_p.append(p_value)
    available = [index for index, value in enumerate(raw_p) if value is not None]
    ordered = sorted(available, key=lambda index: float(raw_p[index]))
    running = 0.0
    for rank, index in enumerate(ordered):
        adjusted = min(1.0, float(raw_p[index]) * (len(ordered) - rank))
        running = max(running, adjusted)
        endpoints[index]["holm_adjusted_p"] = running
    return {
        "block_hours": BLOCK_HOURS,
        "resamples": RESAMPLES,
        "seed": SEED,
        "endpoints": endpoints,
    }


def validate_structural_attacks(spot: pd.DataFrame) -> dict[str, bool]:
    attacks: dict[str, bool] = {}
    shuffled = spot.sample(frac=1.0, random_state=SEED).reset_index(drop=True)
    try:
        validate_candles(shuffled, "shuffled-attack")
        attacks["shuffled_rejected"] = False
    except ResearchError:
        attacks["shuffled_rejected"] = True
    gapped = spot.drop(index=len(spot) // 2).reset_index(drop=True)
    try:
        validate_candles(gapped, "gapped-attack")
        attacks["gapped_rejected"] = False
    except ResearchError:
        attacks["gapped_rejected"] = True
    duplicated = pd.concat([spot, spot.iloc[[len(spot) // 2]]], ignore_index=True).sort_values(
        "open_time_ms", ignore_index=True
    )
    try:
        validate_candles(duplicated, "duplicate-attack")
        attacks["duplicate_rejected"] = False
    except ResearchError:
        attacks["duplicate_rejected"] = True
    return attacks


def run(output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    client = OKX(output_dir / "raw")
    instruments = {
        "BTC-USDT": "BTC-USDT-SWAP",
        "ETH-USDT": "ETH-USDT-SWAP",
    }
    full_frames: dict[str, pd.DataFrame] = {}
    metadata: dict[str, Any] = {}
    first_usable: dict[str, int] = {}
    last_available: dict[str, int] = {}
    causal_checks: dict[str, Any] = {}
    for spot_id, swap_id in instruments.items():
        binding = bind_instruments(client, spot_id, swap_id)
        funding = fetch_funding(client, swap_id)
        earliest = int(funding["funding_time_ms"].min())
        latest = int(funding["funding_time_ms"].max())
        mark = fetch_candles(
            client,
            "/api/v5/market/history-mark-price-candles",
            swap_id,
            earliest - 25 * HOUR_MS,
            spot=False,
        )
        index = fetch_candles(
            client,
            "/api/v5/market/history-index-candles",
            binding["index_id"],
            earliest - 25 * HOUR_MS,
            spot=False,
        )
        spot = fetch_candles(
            client,
            "/api/v5/market/history-candles",
            spot_id,
            earliest - 2162 * HOUR_MS,
            spot=True,
        )
        events, invalid_counts = build_events(funding, mark, index)
        hourly = build_hourly(events, spot)
        usable = events.loc[events["usable"]]
        if usable.empty:
            raise ResearchError(f"no usable post-warmup event: {spot_id}")
        first_usable[spot_id] = int(usable["funding_time_ms"].min()) + 2 * HOUR_MS
        last_available[spot_id] = min(
            int(hourly["close_time_ms"].max()), latest + 8 * HOUR_MS
        )
        # Rebuild from a strict prefix, then mutate every future source value.  Earlier
        # targets and positions must remain byte-identical.
        cutoff_row = len(funding) // 2
        cutoff = int(funding.iloc[cutoff_row]["funding_time_ms"])
        funding_prefix = funding.loc[funding["funding_time_ms"] <= cutoff].copy()
        prefix_spot = spot.loc[spot["open_time_ms"] <= cutoff + 2 * HOUR_MS].copy()
        prefix_events, _ = build_events(funding_prefix, mark, index)
        prefix_hourly = build_hourly(prefix_events, prefix_spot)
        compare_end = int(prefix_hourly["close_time_ms"].max())
        full_prefix = hourly.loc[hourly["close_time_ms"] <= compare_end]
        prefix_equal = len(full_prefix) == len(prefix_hourly) and all(
            np.array_equal(
                full_prefix[column].to_numpy(), prefix_hourly[column].to_numpy()
            )
            for column in ("target_f0", "target_f1", "position_f0", "position_f1")
        )
        if not prefix_equal:
            raise ResearchError(f"future suffix invariance failed: {spot_id}")
        causal_checks[spot_id] = {
            "future_suffix_invariance": True,
            **validate_structural_attacks(spot),
        }
        full_frames[spot_id] = hourly
        metadata[spot_id] = {
            "binding": binding,
            "archive_probe": probe_archive(client, binding["inst_family"]),
            "funding_rows": int(len(funding)),
            "funding_start_utc": iso(earliest),
            "funding_end_utc": iso(latest),
            "mark_rows": int(len(mark)),
            "index_rows": int(len(index)),
            "spot_rows": int(len(spot)),
            "usable_events": int(events["usable"].sum()),
            "f0_positive_events": int((events["target_f0"] > 0).sum()),
            "f1_positive_events": int((events["target_f1"] > 0).sum()),
            "invalid_event_counts": invalid_counts,
        }
    common_start = max(first_usable.values())
    common_end = min(last_available.values())
    complete_folds = int(((common_end - common_start) // HOUR_MS + 1) // FOLD_HOURS)
    if complete_folds < 2:
        raise ResearchError(f"fewer than two complete short-window folds: {complete_folds}")
    evaluation_end = common_start + complete_folds * FOLD_HOURS * HOUR_MS - HOUR_MS
    frames: dict[str, pd.DataFrame] = {}
    fold_ids: dict[str, np.ndarray] = {}
    for market, frame in full_frames.items():
        subset = frame.loc[
            (frame["close_time_ms"] >= common_start)
            & (frame["close_time_ms"] <= evaluation_end)
        ].copy()
        expected = complete_folds * FOLD_HOURS
        if len(subset) != expected:
            raise ResearchError(f"evaluation row mismatch: {market}: {len(subset)} != {expected}")
        subset["year"] = pd.to_datetime(subset["close_time_ms"], unit="ms", utc=True).dt.year
        frames[market] = subset.reset_index(drop=True)
        fold_ids[market] = np.repeat(np.arange(complete_folds), FOLD_HOURS)
    all_metrics = {
        market: {
            policy: metrics(frame, policy, fold_ids[market])
            for policy in ("f0", "f1", "trend")
        }
        for market, frame in frames.items()
    }
    inference = bootstrap(frames, fold_ids)
    failures: list[str] = []
    for market in instruments:
        f0, f1 = all_metrics[market]["f0"], all_metrics[market]["f1"]
        screens = {
            "positive_return": f1["net_total_return"] > 0,
            "positive_sharpe": f1["sharpe"] is not None and f1["sharpe"] > 0,
            "positive_edge": (
                f1["edge_per_turnover_bps"] is not None
                and f1["edge_per_turnover_bps"] > 0
            ),
            "sharpe_above_f0": (
                f1["sharpe"] is not None
                and f0["sharpe"] is not None
                and f1["sharpe"] > f0["sharpe"]
            ),
            "edge_above_f0": (
                f1["edge_per_turnover_bps"] is not None
                and f0["edge_per_turnover_bps"] is not None
                and f1["edge_per_turnover_bps"] > f0["edge_per_turnover_bps"]
            ),
            "positive_trend_residual": (
                f1["residual_sharpe_vs_simple_trend"] is not None
                and f1["residual_sharpe_vs_simple_trend"] > 0
            ),
        }
        metadata[market]["deterministic_screens"] = screens
        failures.extend(f"{market}:{name}" for name, passed in screens.items() if not passed)
    statistical_pass = all(
        endpoint.get("available")
        and endpoint.get("one_sided_95_lower_bound", -math.inf) > 0
        and endpoint.get("holm_adjusted_p", 1.0) < 0.05
        for endpoint in inference["endpoints"]
    )
    archive_manifest_available = all(
        bool(metadata[market]["archive_probe"]["download_urls_found"])
        for market in instruments
    )
    if failures:
        verdict = "rejected_by_predeclared_short_window_diagnostic"
    elif not statistical_pass:
        verdict = "insufficient_short_window_evidence"
    else:
        verdict = "diagnostic_pass_but_insufficient_history_for_qualification"
    manifest = {
        "base_url": BASE,
        "record_count": len(client.records),
        "records": [asdict(record) for record in client.records],
    }
    manifest_bytes = canonical_bytes(finite(manifest))
    (output_dir / "source-manifest.json").write_bytes(manifest_bytes)
    result = finite(
        {
            "family_id": FAMILY,
            "generated_from_commit": os.environ.get("GITHUB_SHA", "local"),
            "candidate_count": 2,
            "policies": ["F0_funding_only_attribution", "F1_strict_funding_basis_unwind"],
            "bar": "1H",
            "fee_one_way": FEE,
            "exact_fields": [
                "realizedRate",
                "fundingTime",
                "formulaType",
                "method",
                "inferred interval hours",
                "completed mark close",
                "completed index close",
                "confirmed spot close",
            ],
            "availability": (
                "funding event T uses the completed mark/index candle closing at or before T; "
                "the target is formed at the first completed spot bar strictly after T and "
                "the position is applied one further bar later"
            ),
            "data_mode": "recent_public_rest_short_window_falsification_diagnostic",
            "archive_manifest_available_for_both_markets": archive_manifest_available,
            "historical_archive_materialized": False,
            "qualification_history_required": (
                "180 calendar-day warmup and at least eight non-overlapping 90-day folds"
            ),
            "qualification_history_available": False,
            "short_window_predeclaration": {
                "warmup_events": WARMUP_EVENTS,
                "warmup_interval_hours": WARMUP_HOURS,
                "fold_hours": FOLD_HOURS,
                "complete_folds": complete_folds,
                "evaluation_start_utc": iso(common_start),
                "evaluation_end_utc": iso(evaluation_end),
                "hours_per_market": complete_folds * FOLD_HOURS,
                "purpose": "falsification only; cannot qualify or promote F1",
            },
            "markets": metadata,
            "metrics": all_metrics,
            "bootstrap": inference,
            "deterministic_failures": failures,
            "statistical_pass": statistical_pass,
            "causal_and_structure_checks": causal_checks,
            "source_manifest_sha256": sha256(manifest_bytes),
            "source_response_count": len(client.records),
            "oos_consumed": False,
            "untouched_evidence_consumed": False,
            "verdict": verdict,
        }
    )
    result_bytes = canonical_bytes(result)
    (output_dir / "result-summary.json").write_bytes(result_bytes)
    (output_dir / "result-summary.sha256").write_text(
        f"{sha256(result_bytes)}  result-summary.json\n"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    result = run(args.output_dir)
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
