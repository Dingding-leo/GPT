#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import subprocess
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

BASE_URL = "https://www.okx.com"
ALLOWED_HOSTS = {"www.okx.com", "app.okx.com"}
FUNDING_START = pd.Timestamp("2026-05-04T00:00:00Z")
FUNDING_END = pd.Timestamp("2026-07-30T23:59:59Z")
SPOT_START = pd.Timestamp("2026-05-03T00:00:00Z")
SPOT_END = pd.Timestamp("2026-08-01T00:00:00Z")
ONE_HOUR_MS = 3_600_000
FEE_ONE_WAY = 0.0005
ROUND_TRIP_FEE = 0.001
BOOTSTRAP_DRAWS = 5_000
BOOTSTRAP_SEED = 20260801
MAX_RESPONSE_BYTES = 2_000_000
TIMEOUT_SECONDS = 25.0
PAUSE_SECONDS = 0.12


class ResearchError(RuntimeError):
    pass


def reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ResearchError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


@dataclass(frozen=True)
class SourcePage:
    kind: str
    market: str
    url: str
    final_url: str
    raw_sha256: str
    raw_bytes: int
    raw_base64: str
    payload: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "market": self.market,
            "url": self.url,
            "final_url": self.final_url,
            "raw_sha256": self.raw_sha256,
            "raw_bytes": self.raw_bytes,
            "raw_base64": self.raw_base64,
            "payload": self.payload,
        }


class ExactSourceCollector:
    def __init__(self) -> None:
        self.pages: list[SourcePage] = []

    def fetch(self, *, kind: str, market: str, path: str, params: dict[str, str]) -> dict[str, Any]:
        query = urllib.parse.urlencode(sorted(params.items()))
        url = f"{BASE_URL}{path}?{query}"
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "gpt-quant-lab-funding-reset/1.0",
            },
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            final_url = response.geturl()
            parsed_final = urllib.parse.urlparse(final_url)
            if parsed_final.scheme != "https" or parsed_final.hostname not in ALLOWED_HOSTS:
                raise ResearchError(f"unapproved OKX redirect target: {final_url}")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if not raw or len(raw) > MAX_RESPONSE_BYTES:
            raise ResearchError(f"{kind} response is empty or exceeds bound")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ResearchError(f"{kind} response is not UTF-8") from exc
        try:
            payload = json.loads(text, object_pairs_hook=reject_duplicate_pairs)
        except json.JSONDecodeError as exc:
            raise ResearchError(f"{kind} response is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise ResearchError(f"{kind} response is not an object")
        if set(payload) != {"code", "msg", "data"}:
            raise ResearchError(f"{kind} top-level schema mismatch: {sorted(payload)}")
        if payload["code"] != "0" or not isinstance(payload["msg"], str):
            raise ResearchError(f"{kind} provider error code={payload.get('code')} msg={payload.get('msg')}")
        if not isinstance(payload["data"], list):
            raise ResearchError(f"{kind} data must be a list")
        page = SourcePage(
            kind=kind,
            market=market,
            url=url,
            final_url=final_url,
            raw_sha256=hashlib.sha256(raw).hexdigest(),
            raw_bytes=len(raw),
            raw_base64=base64.b64encode(raw).decode("ascii"),
            payload=payload,
        )
        self.pages.append(page)
        time.sleep(PAUSE_SECONDS)
        return payload


def require_one_instrument(
    collector: ExactSourceCollector,
    *,
    market: str,
    inst_type: str,
    inst_id: str,
) -> dict[str, Any]:
    payload = collector.fetch(
        kind=f"instruments_{inst_type.lower()}",
        market=market,
        path="/api/v5/public/instruments",
        params={"instType": inst_type, "instId": inst_id},
    )
    rows = payload["data"]
    if len(rows) != 1 or not isinstance(rows[0], dict):
        raise ResearchError(f"{market} {inst_type} binding returned {len(rows)} rows")
    row = rows[0]
    if row.get("instId") != inst_id or row.get("instType") != inst_type:
        raise ResearchError(f"{market} {inst_type} instrument identity mismatch")
    if row.get("state") != "live":
        raise ResearchError(f"{market} {inst_type} instrument is not live")
    if inst_type == "SPOT":
        base, quote = market.split("-")
        if row.get("baseCcy") != base or row.get("quoteCcy") != quote:
            raise ResearchError(f"{market} SPOT base/quote binding mismatch")
    else:
        if row.get("ctType") != "linear" or row.get("settleCcy") != "USDT":
            raise ResearchError(f"{market} SWAP is not linear USDT-settled")
        if row.get("uly") != market:
            raise ResearchError(f"{market} SWAP underlying binding mismatch")
    return row


def parse_finite_float(value: Any, *, field: str) -> float:
    if isinstance(value, bool):
        raise ResearchError(f"{field} must be numeric text")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ResearchError(f"{field} is not numeric") from exc
    if not math.isfinite(result):
        raise ResearchError(f"{field} is not finite")
    return result


def fetch_funding(
    collector: ExactSourceCollector,
    *,
    market: str,
    swap_id: str,
) -> pd.DataFrame:
    records: dict[int, dict[str, Any]] = {}
    after: str | None = None
    previous_oldest: int | None = None
    for page_index in range(4):
        params = {"instId": swap_id, "limit": "400"}
        if after is not None:
            params["after"] = after
        payload = collector.fetch(
            kind="funding_rate_history",
            market=market,
            path="/api/v5/public/funding-rate-history",
            params=params,
        )
        rows = payload["data"]
        if not rows:
            break
        page_times: list[int] = []
        for raw in rows:
            if not isinstance(raw, dict):
                raise ResearchError(f"{market} funding row is not an object")
            if raw.get("instId") != swap_id or raw.get("instType") != "SWAP":
                raise ResearchError(f"{market} funding instrument identity mismatch")
            if "realizedRate" not in raw:
                raise ResearchError(f"{market} funding row lacks realizedRate")
            try:
                timestamp = int(raw["fundingTime"])
            except (TypeError, ValueError, OverflowError) as exc:
                raise ResearchError(f"{market} invalid fundingTime") from exc
            rate = parse_finite_float(raw["realizedRate"], field=f"{market} realizedRate")
            normalized = {
                "funding_time_ms": timestamp,
                "realized_rate": rate,
                "formula_type": raw.get("formulaType"),
                "method": raw.get("method"),
            }
            prior = records.get(timestamp)
            if prior is not None and prior != normalized:
                raise ResearchError(f"{market} conflicting duplicate funding timestamp {timestamp}")
            records[timestamp] = normalized
            page_times.append(timestamp)
        oldest = min(page_times)
        if previous_oldest is not None and oldest >= previous_oldest:
            raise ResearchError(f"{market} funding pagination failed to move backward")
        previous_oldest = oldest
        if oldest <= int(FUNDING_START.timestamp() * 1000):
            break
        after = str(oldest)
    if not records:
        raise ResearchError(f"{market} funding source returned no rows")
    frame = pd.DataFrame(sorted(records.values(), key=lambda item: item["funding_time_ms"]))
    frame["timestamp"] = pd.to_datetime(frame["funding_time_ms"], unit="ms", utc=True)
    frame = frame[(frame["timestamp"] >= FUNDING_START) & (frame["timestamp"] <= FUNDING_END)]
    frame = frame.reset_index(drop=True)
    if frame.empty:
        raise ResearchError(f"{market} funding source did not cover the frozen window")
    if frame["funding_time_ms"].duplicated().any() or not frame["funding_time_ms"].is_monotonic_increasing:
        raise ResearchError(f"{market} funding chronology is not unique and increasing")
    gaps = frame["timestamp"].diff().dropna().dt.total_seconds().div(3600.0)
    if not gaps.empty and float(gaps.max()) > 24.0:
        raise ResearchError(f"{market} funding coverage has a gap above 24 hours")
    if frame["timestamp"].iloc[0] > FUNDING_START + pd.Timedelta(hours=24):
        raise ResearchError(f"{market} funding start coverage is incomplete")
    if frame["timestamp"].iloc[-1] < FUNDING_END - pd.Timedelta(hours=24):
        raise ResearchError(f"{market} funding end coverage is incomplete")
    return frame


def fetch_spot_candles(
    collector: ExactSourceCollector,
    *,
    market: str,
) -> pd.DataFrame:
    records: dict[int, tuple[int, float, float, float, float]] = {}
    after: str | None = None
    previous_oldest: int | None = None
    for page_index in range(30):
        params = {"instId": market, "bar": "1H", "limit": "100"}
        if after is not None:
            params["after"] = after
        payload = collector.fetch(
            kind="spot_history_candles",
            market=market,
            path="/api/v5/market/history-candles",
            params=params,
        )
        rows = payload["data"]
        if not rows:
            break
        page_times: list[int] = []
        for raw in rows:
            if not isinstance(raw, list) or len(raw) != 9:
                raise ResearchError(f"{market} candle row schema mismatch")
            try:
                timestamp = int(raw[0])
            except (TypeError, ValueError, OverflowError) as exc:
                raise ResearchError(f"{market} invalid candle timestamp") from exc
            if timestamp % ONE_HOUR_MS != 0:
                raise ResearchError(f"{market} candle is not aligned to 1H")
            open_px = parse_finite_float(raw[1], field=f"{market} open")
            high_px = parse_finite_float(raw[2], field=f"{market} high")
            low_px = parse_finite_float(raw[3], field=f"{market} low")
            close_px = parse_finite_float(raw[4], field=f"{market} close")
            if raw[8] != "1":
                continue
            if min(open_px, high_px, low_px, close_px) <= 0:
                raise ResearchError(f"{market} candle contains non-positive price")
            if high_px < max(open_px, close_px, low_px) or low_px > min(open_px, close_px, high_px):
                raise ResearchError(f"{market} candle OHLC ordering is invalid")
            normalized = (timestamp, open_px, high_px, low_px, close_px)
            prior = records.get(timestamp)
            if prior is not None and prior != normalized:
                raise ResearchError(f"{market} conflicting duplicate candle {timestamp}")
            records[timestamp] = normalized
            page_times.append(timestamp)
        if not page_times:
            raise ResearchError(f"{market} candle page had no completed rows")
        oldest = min(page_times)
        if previous_oldest is not None and oldest >= previous_oldest:
            raise ResearchError(f"{market} candle pagination failed to move backward")
        previous_oldest = oldest
        if oldest <= int(SPOT_START.timestamp() * 1000):
            break
        after = str(oldest)
    rows = [value for timestamp, value in records.items()]
    frame = pd.DataFrame(rows, columns=["timestamp_ms", "open", "high", "low", "close"])
    frame["timestamp"] = pd.to_datetime(frame["timestamp_ms"], unit="ms", utc=True)
    frame = frame[(frame["timestamp"] >= SPOT_START) & (frame["timestamp"] <= SPOT_END)]
    frame = frame.sort_values("timestamp").reset_index(drop=True)
    expected = int((SPOT_END - SPOT_START) / pd.Timedelta(hours=1)) + 1
    if len(frame) != expected:
        raise ResearchError(f"{market} expected {expected} frozen candles, received {len(frame)}")
    expected_index = pd.date_range(SPOT_START, SPOT_END, freq="h", tz="UTC")
    if not frame["timestamp"].equals(pd.Series(expected_index, name="timestamp")):
        raise ResearchError(f"{market} frozen candle grid is not exactly contiguous")
    return frame


def ceil_hour(timestamp: pd.Timestamp) -> pd.Timestamp:
    if timestamp != timestamp.floor("h"):
        return timestamp.ceil("h")
    return timestamp


def build_labels(
    *,
    funding: pd.DataFrame,
    candles: pd.DataFrame,
    delay_hours: int,
) -> pd.DataFrame:
    candle_index = candles.set_index("timestamp", drop=False)
    rows: list[dict[str, Any]] = []
    rates = funding["realized_rate"].to_numpy(dtype=float)
    for index, funding_row in funding.iterrows():
        funding_time = pd.Timestamp(funding_row["timestamp"])
        event = bool(index >= 2 and rates[index - 2] > 0 and rates[index - 1] > 0 and rates[index] <= 0)
        entry = ceil_hour(funding_time + pd.Timedelta(hours=delay_hours))
        exit_time = entry + pd.Timedelta(hours=24)
        if entry not in candle_index.index or exit_time not in candle_index.index:
            continue
        adverse_times = pd.date_range(entry, periods=24, freq="h", tz="UTC")
        if not adverse_times.isin(candle_index.index).all():
            continue
        entry_open = float(candle_index.loc[entry, "open"])
        exit_open = float(candle_index.loc[exit_time, "open"])
        lows = candle_index.loc[adverse_times, "low"].to_numpy(dtype=float)
        gross = math.log(exit_open / entry_open)
        rows.append(
            {
                "funding_time": funding_time,
                "decision_day": funding_time.floor("D"),
                "month": funding_time.strftime("%Y-%m"),
                "realized_rate": float(funding_row["realized_rate"]),
                "event": event,
                "entry": entry,
                "exit": exit_time,
                "gross_24h": gross,
                "net_24h": gross - ROUND_TRIP_FEE,
                "adverse_24h": float(np.min(np.log(lows / entry_open))),
            }
        )
    return pd.DataFrame(rows)


def percentile_interval(values: list[float]) -> list[float] | None:
    finite = np.asarray([value for value in values if math.isfinite(value)], dtype=float)
    if len(finite) < int(BOOTSTRAP_DRAWS * 0.95):
        return None
    return [float(np.percentile(finite, 2.5)), float(np.percentile(finite, 97.5))]


def bootstrap_day_effects(labels: pd.DataFrame, *, seed: int) -> dict[str, Any]:
    groups = {
        day: group.reset_index(drop=True)
        for day, group in labels.groupby("decision_day", sort=True)
    }
    days = list(groups)
    rng = np.random.default_rng(seed)
    net_diffs: list[float] = []
    adverse_diffs: list[float] = []
    for _ in range(BOOTSTRAP_DRAWS):
        sampled_days = rng.choice(days, size=len(days), replace=True)
        sampled = pd.concat([groups[day] for day in sampled_days], ignore_index=True)
        events = sampled[sampled["event"]]
        controls = sampled[~sampled["event"]]
        if events.empty or controls.empty:
            continue
        net_diffs.append(float(events["net_24h"].mean() - controls["net_24h"].mean()))
        adverse_diffs.append(
            float(events["adverse_24h"].mean() - controls["adverse_24h"].mean())
        )
    return {
        "draws_requested": BOOTSTRAP_DRAWS,
        "valid_net_draws": len(net_diffs),
        "valid_adverse_draws": len(adverse_diffs),
        "net_difference_ci95": percentile_interval(net_diffs),
        "adverse_difference_ci95": percentile_interval(adverse_diffs),
    }


def summarize_labels(labels: pd.DataFrame, *, seed: int) -> dict[str, Any]:
    events = labels[labels["event"]].copy()
    controls = labels[~labels["event"]].copy()
    month_effects: list[dict[str, Any]] = []
    for month, month_rows in labels.groupby("month", sort=True):
        month_events = month_rows[month_rows["event"]]
        month_controls = month_rows[~month_rows["event"]]
        if len(month_events) < 2 or month_controls.empty:
            continue
        month_effects.append(
            {
                "month": month,
                "events": int(len(month_events)),
                "controls": int(len(month_controls)),
                "net_difference": float(
                    month_events["net_24h"].mean() - month_controls["net_24h"].mean()
                ),
                "adverse_difference": float(
                    month_events["adverse_24h"].mean()
                    - month_controls["adverse_24h"].mean()
                ),
            }
        )
    absolute_event_net = float(events["net_24h"].abs().sum()) if not events.empty else 0.0
    concentration = (
        float(events["net_24h"].abs().max() / absolute_event_net)
        if absolute_event_net > 0
        else None
    )
    bootstrap = bootstrap_day_effects(labels, seed=seed) if not events.empty and not controls.empty else {
        "draws_requested": BOOTSTRAP_DRAWS,
        "valid_net_draws": 0,
        "valid_adverse_draws": 0,
        "net_difference_ci95": None,
        "adverse_difference_ci95": None,
    }
    return {
        "eligible_labels": int(len(labels)),
        "event_count": int(len(events)),
        "control_count": int(len(controls)),
        "event_timestamps": [value.isoformat() for value in events["funding_time"]],
        "event_mean_gross": float(events["gross_24h"].mean()) if not events.empty else None,
        "event_mean_net": float(events["net_24h"].mean()) if not events.empty else None,
        "event_median_net": float(events["net_24h"].median()) if not events.empty else None,
        "event_positive_net_count": int((events["net_24h"] > 0).sum()),
        "event_positive_net_fraction": (
            float((events["net_24h"] > 0).mean()) if not events.empty else None
        ),
        "event_mean_adverse": (
            float(events["adverse_24h"].mean()) if not events.empty else None
        ),
        "control_mean_net": (
            float(controls["net_24h"].mean()) if not controls.empty else None
        ),
        "control_mean_adverse": (
            float(controls["adverse_24h"].mean()) if not controls.empty else None
        ),
        "event_minus_control_net": (
            float(events["net_24h"].mean() - controls["net_24h"].mean())
            if not events.empty and not controls.empty
            else None
        ),
        "event_minus_control_adverse": (
            float(events["adverse_24h"].mean() - controls["adverse_24h"].mean())
            if not events.empty and not controls.empty
            else None
        ),
        "month_effects": month_effects,
        "positive_net_months": int(sum(item["net_difference"] > 0 for item in month_effects)),
        "represented_months": int(len(month_effects)),
        "largest_absolute_event_contribution_share": concentration,
        "bootstrap": bootstrap,
    }


def normalized_candle_hash(frame: pd.DataFrame) -> str:
    lines = ["timestamp_ms,open,high,low,close"]
    for row in frame.itertuples(index=False):
        lines.append(
            f"{int(row.timestamp_ms)},{float(row.open):.17g},{float(row.high):.17g},"
            f"{float(row.low):.17g},{float(row.close):.17g}"
        )
    payload = ("\n".join(lines) + "\n").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def funding_hash(frame: pd.DataFrame) -> str:
    lines = ["funding_time_ms,realized_rate"]
    for row in frame.itertuples(index=False):
        lines.append(f"{int(row.funding_time_ms)},{float(row.realized_rate):.17g}")
    payload = ("\n".join(lines) + "\n").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def gate_audit(primary: dict[str, Any], delayed: dict[str, Any]) -> dict[str, bool]:
    primary_ci_net = primary["bootstrap"]["net_difference_ci95"]
    primary_ci_adverse = primary["bootstrap"]["adverse_difference_ci95"]
    delayed_ci_net = delayed["bootstrap"]["net_difference_ci95"]
    delayed_ci_adverse = delayed["bootstrap"]["adverse_difference_ci95"]
    represented = primary["represented_months"]
    positive_month_requirement = math.ceil(2 * represented / 3) if represented else 1
    return {
        "sample_support": (
            primary["eligible_labels"] >= 250
            and primary["event_count"] >= 12
            and primary["control_count"] >= 200
        ),
        "positive_event_economics": (
            primary["event_mean_net"] is not None
            and primary["event_median_net"] is not None
            and primary["event_mean_net"] > 0
            and primary["event_median_net"] > 0
        ),
        "positive_relative_effects": (
            primary["event_minus_control_net"] is not None
            and primary["event_minus_control_adverse"] is not None
            and primary["event_minus_control_net"] > 0
            and primary["event_minus_control_adverse"] > 0
        ),
        "positive_primary_lower_bounds": (
            primary_ci_net is not None
            and primary_ci_adverse is not None
            and primary_ci_net[0] > 0
            and primary_ci_adverse[0] > 0
        ),
        "month_breadth": (
            represented > 0 and primary["positive_net_months"] >= positive_month_requirement
        ),
        "event_concentration": (
            primary["largest_absolute_event_contribution_share"] is not None
            and primary["largest_absolute_event_contribution_share"] <= 0.35
        ),
        "delay_survival": (
            delayed["event_mean_net"] is not None
            and delayed["event_minus_control_net"] is not None
            and delayed["event_minus_control_adverse"] is not None
            and delayed["event_mean_net"] > 0
            and delayed["event_minus_control_net"] > 0
            and delayed["event_minus_control_adverse"] > 0
            and delayed_ci_net is not None
            and delayed_ci_adverse is not None
            and delayed_ci_net[0] > 0
            and delayed_ci_adverse[0] > 0
        ),
    }


def clean_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): clean_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [clean_json(item) for item in value]
    if isinstance(value, tuple):
        return [clean_json(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(clean_json(value), sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("utf-8")


def current_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


def evaluate_market(
    collector: ExactSourceCollector,
    *,
    market: str,
) -> dict[str, Any]:
    swap_id = f"{market}-SWAP"
    spot_binding = require_one_instrument(
        collector,
        market=market,
        inst_type="SPOT",
        inst_id=market,
    )
    swap_binding = require_one_instrument(
        collector,
        market=market,
        inst_type="SWAP",
        inst_id=swap_id,
    )
    funding = fetch_funding(collector, market=market, swap_id=swap_id)
    candles = fetch_spot_candles(collector, market=market)
    primary_labels = build_labels(funding=funding, candles=candles, delay_hours=1)
    delayed_labels = build_labels(funding=funding, candles=candles, delay_hours=2)
    if len(primary_labels) != len(delayed_labels):
        raise ResearchError(f"{market} primary and delayed label support differ")
    primary = summarize_labels(primary_labels, seed=BOOTSTRAP_SEED)
    delayed = summarize_labels(delayed_labels, seed=BOOTSTRAP_SEED + 1)
    gaps = funding["timestamp"].diff().dropna().dt.total_seconds().div(3600.0)
    gates = gate_audit(primary, delayed)
    return {
        "market": market,
        "spot_instrument": {
            "instId": spot_binding.get("instId"),
            "instType": spot_binding.get("instType"),
            "state": spot_binding.get("state"),
            "baseCcy": spot_binding.get("baseCcy"),
            "quoteCcy": spot_binding.get("quoteCcy"),
        },
        "swap_instrument": {
            "instId": swap_binding.get("instId"),
            "instType": swap_binding.get("instType"),
            "state": swap_binding.get("state"),
            "ctType": swap_binding.get("ctType"),
            "settleCcy": swap_binding.get("settleCcy"),
            "uly": swap_binding.get("uly"),
        },
        "source": {
            "funding_observations": int(len(funding)),
            "funding_start": funding["timestamp"].iloc[0].isoformat(),
            "funding_end": funding["timestamp"].iloc[-1].isoformat(),
            "funding_interval_hours_min": float(gaps.min()) if not gaps.empty else None,
            "funding_interval_hours_median": float(gaps.median()) if not gaps.empty else None,
            "funding_interval_hours_max": float(gaps.max()) if not gaps.empty else None,
            "funding_normalized_sha256": funding_hash(funding),
            "spot_observations": int(len(candles)),
            "spot_start": candles["timestamp"].iloc[0].isoformat(),
            "spot_end": candles["timestamp"].iloc[-1].isoformat(),
            "spot_normalized_sha256": normalized_candle_hash(candles),
        },
        "primary": primary,
        "one_hour_additional_delay": delayed,
        "gates": gates,
        "all_gates_pass": all(gates.values()),
    }


def make_report(evidence: dict[str, Any]) -> str:
    lines = [
        "# OKX settled-funding positive-run reset diagnostic",
        "",
        "```text",
        f"family_id          {evidence['family_id']}",
        f"candidate_count    {evidence['candidate_count']}",
        f"diagnostic_count   {evidence['diagnostic_count']}",
        f"fee_one_way        {evidence['fee_one_way']:.4f}",
        f"exact_head         {evidence['exact_head']}",
        f"verdict            {evidence['verdict']}",
        "```",
        "",
    ]
    if evidence.get("source_feasible") is not True:
        failure = evidence.get("source_failure", {})
        lines.extend(
            [
                "## Source feasibility",
                "",
                f"Rejected before a complete bilateral economic diagnostic: "
                f"`{failure.get('type')}: {failure.get('message')}`.",
                "",
                f"Exact response pages captured before termination: "
                f"{evidence.get('source_pages_captured', 0)}.",
                "",
            ]
        )
    for market, result in evidence.get("markets", {}).items():
        primary = result["primary"]
        delayed = result["one_hour_additional_delay"]
        lines.extend(
            [
                f"## {market}",
                "",
                "| Metric | Primary | +1H delay |",
                "|---|---:|---:|",
                f"| Eligible labels | {primary['eligible_labels']} | {delayed['eligible_labels']} |",
                f"| Events | {primary['event_count']} | {delayed['event_count']} |",
                f"| Controls | {primary['control_count']} | {delayed['control_count']} |",
                f"| Event mean net | {primary['event_mean_net']} | {delayed['event_mean_net']} |",
                f"| Event median net | {primary['event_median_net']} | {delayed['event_median_net']} |",
                f"| Event-control net | {primary['event_minus_control_net']} | "
                f"{delayed['event_minus_control_net']} |",
                f"| Event-control adverse | {primary['event_minus_control_adverse']} | "
                f"{delayed['event_minus_control_adverse']} |",
                f"| Net CI95 | {primary['bootstrap']['net_difference_ci95']} | "
                f"{delayed['bootstrap']['net_difference_ci95']} |",
                f"| Adverse CI95 | {primary['bootstrap']['adverse_difference_ci95']} | "
                f"{delayed['bootstrap']['adverse_difference_ci95']} |",
                f"| Positive months | {primary['positive_net_months']}/"
                f"{primary['represented_months']} | {delayed['positive_net_months']}/"
                f"{delayed['represented_months']} |",
                "",
                "Gate audit:",
                "",
            ]
        )
        for gate, passed in result["gates"].items():
            lines.append(f"- `{gate}`: {'PASS' if passed else 'FAIL'}")
        lines.append("")
    lines.extend(
        [
            "## Executable performance fields",
            "",
            "Candidate count is zero. Training/OOS/full compounded return, Sharpe, benchmark "
            "equity comparison, maximum drawdown, executable turnover and edge per turnover "
            "are not computed from overlapping opportunity labels.",
            "",
            "## Disposition",
            "",
            "No canonical mutation, paper authority, live authority, account, order, leverage "
            "or enabled adapter is produced by this diagnostic.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    head = current_head()
    expected_head = os.environ.get("EXPECTED_SHA")
    if expected_head and head != expected_head:
        raise ResearchError(f"exact-head mismatch: checkout={head} expected={expected_head}")

    collector = ExactSourceCollector()
    evidence: dict[str, Any] = {
        "family_id": "okx-settled-funding-positive-run-reset-opportunity-1h-v1",
        "classification": "training-only temporal-event information diagnostic",
        "candidate_count": 0,
        "diagnostic_count": 1,
        "parameter_grid_count": 0,
        "markets_required": ["BTC-USDT", "ETH-USDT"],
        "fee_one_way": FEE_ONE_WAY,
        "round_trip_label_fee": ROUND_TRIP_FEE,
        "bar": "1H",
        "funding_window": [FUNDING_START.isoformat(), FUNDING_END.isoformat()],
        "spot_window": [SPOT_START.isoformat(), SPOT_END.isoformat()],
        "bootstrap_draws": BOOTSTRAP_DRAWS,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "exact_head": head,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "markets": {},
        "source_feasible": False,
    }

    try:
        for market in evidence["markets_required"]:
            evidence["markets"][market] = evaluate_market(collector, market=market)
        evidence["source_feasible"] = True
        all_pass = all(
            result["all_gates_pass"] for result in evidence["markets"].values()
        )
        evidence["verdict"] = (
            "accept_okx_settled_funding_positive_run_reset_opportunity_premise"
            if all_pass
            else "reject_okx_settled_funding_positive_run_reset_opportunity_premise"
        )
    except Exception as exc:
        evidence["source_failure"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
        evidence["source_pages_captured"] = len(collector.pages)
        evidence["verdict"] = "reject_public_okx_funding_reset_source_feasibility"

    source_manifest = {
        "base_url": BASE_URL,
        "allowed_hosts": sorted(ALLOWED_HOSTS),
        "pages": [page.as_dict() for page in collector.pages],
    }
    source_bytes = canonical_json_bytes(source_manifest)
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    evidence["source_manifest_sha256"] = source_hash
    evidence["source_page_count"] = len(collector.pages)
    evidence["source_total_bytes"] = sum(page.raw_bytes for page in collector.pages)

    source_path = args.output_dir / "source-manifest.json"
    source_path.write_bytes(source_bytes)
    evidence_path = args.output_dir / "evidence.json"
    evidence_bytes = canonical_json_bytes(evidence)
    evidence_path.write_bytes(evidence_bytes)
    evidence_hash = hashlib.sha256(evidence_bytes).hexdigest()
    (args.output_dir / "evidence.sha256").write_text(
        f"{evidence_hash}  evidence.json\n", encoding="utf-8"
    )
    report = make_report(clean_json(evidence))
    report_path = args.output_dir / "report.md"
    report_path.write_text(report, encoding="utf-8")
    identities = {
        "evidence_sha256": evidence_hash,
        "source_manifest_sha256": source_hash,
        "report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
        "exact_head": head,
        "verdict": evidence["verdict"],
    }
    (args.output_dir / "identities.json").write_bytes(canonical_json_bytes(identities))
    print(json.dumps(identities, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
