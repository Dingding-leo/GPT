#!/usr/bin/env python3
"""Training-only forward-minus-realized volatility-premium information diagnostic."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

FAMILY = "causal-forward-realized-volatility-premium-opportunity-diagnostic-1h-v1"
REJECT = "reject_causal_forward_realized_volatility_premium_opportunity_diagnostic_1h_v1"
ACCEPT = "accept_forward_realized_volatility_premium_information_for_separate_candidate"
START_MS = int(datetime(2021, 4, 1, tzinfo=timezone.utc).timestamp() * 1000)
END_MS = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
TRAIN_START_MS = int(datetime(2021, 7, 1, tzinfo=timezone.utc).timestamp() * 1000)
TRAIN_END_MS = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
EXPECTED_ROWS = (END_MS - START_MS) // 3_600_000
FEE_ONE_WAY = 0.0005
SEED = 20260802
N_BOOT = 5000
OUT = Path("evidence_vrp")
RAW = OUT / "raw_deribit"
NORMALIZED = OUT / "normalized"
USER_AGENT = "Dingding-leo-GPT-research/vrp-diagnostic-v1"


@dataclass(frozen=True)
class SpotBar:
    ts: int
    open: float
    high: float
    low: float
    close: float


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_bytes(url: str, attempts: int = 4) -> bytes:
    last: Exception | None = None
    for attempt in range(attempts):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                return response.read()
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt + 1 < attempts:
                time.sleep(2**attempt)
    assert last is not None
    raise last


def iter_months() -> list[str]:
    months: list[str] = []
    year, month = 2021, 4
    while (year, month) <= (2025, 12):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            month = 1
            year += 1
    return months


def normalize_binance_timestamp(raw: str) -> int:
    value = int(raw)
    if value > 10**15:
        value //= 1000
    return value


def acquire_binance(symbol: str) -> tuple[list[SpotBar], dict[str, Any]]:
    base = "https://data.binance.vision/data/spot/monthly/klines"
    bars: list[SpotBar] = []
    objects: list[dict[str, Any]] = []
    for month in iter_months():
        name = f"{symbol}-1h-{month}.zip"
        url = f"{base}/{symbol}/1h/{name}"
        checksum_url = url + ".CHECKSUM"
        checksum_bytes = fetch_bytes(checksum_url)
        expected = checksum_bytes.decode("utf-8").strip().split()[0].lower()
        payload = fetch_bytes(url)
        observed = sha256_bytes(payload)
        if observed != expected:
            raise ValueError(f"{symbol} {month} checksum mismatch {observed} != {expected}")
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            members = archive.namelist()
            if len(members) != 1:
                raise ValueError(f"{symbol} {month} unexpected archive members {members}")
            member = members[0]
            rows = archive.read(member).decode("utf-8").splitlines()
        month_count = 0
        for row_text in rows:
            row = next(csv.reader([row_text]))
            if not row or not row[0].lstrip("-").isdigit():
                continue
            if len(row) < 12:
                raise ValueError(f"{symbol} {month} unexpected row width {len(row)}")
            ts = normalize_binance_timestamp(row[0])
            values = [float(row[index]) for index in range(1, 5)]
            if not all(math.isfinite(value) and value > 0 for value in values):
                raise ValueError(f"{symbol} {month} invalid OHLC")
            opn, high, low, close = values
            if high < max(opn, close) or low > min(opn, close) or high < low:
                raise ValueError(f"{symbol} {month} invalid OHLC ordering")
            bars.append(SpotBar(ts, opn, high, low, close))
            month_count += 1
        objects.append(
            {
                "month": month,
                "url": url,
                "checksum_url": checksum_url,
                "zip_sha256": observed,
                "checksum_sha256": sha256_bytes(checksum_bytes),
                "bytes": len(payload),
                "member": member,
                "rows": month_count,
            }
        )
    bars.sort(key=lambda item: item.ts)
    timestamps = [bar.ts for bar in bars]
    if len(timestamps) != len(set(timestamps)):
        raise ValueError(f"{symbol} duplicate timestamps")
    expected_grid = list(range(START_MS, END_MS, 3_600_000))
    if timestamps != expected_grid:
        missing = sorted(set(expected_grid) - set(timestamps))
        extra = sorted(set(timestamps) - set(expected_grid))
        raise ValueError(
            f"{symbol} grid mismatch rows={len(timestamps)} "
            f"missing={len(missing)} extra={len(extra)} "
            f"first_missing={missing[:3]} first_extra={extra[:3]}"
        )
    return bars, {"provider": "Binance", "symbol": symbol, "objects": objects}


def acquire_dvol(currency: str) -> tuple[list[tuple[int, float]], dict[str, Any]]:
    endpoint = "https://www.deribit.com/api/v2/public/get_volatility_index_data"
    start = START_MS
    rows_by_ts: dict[int, float] = {}
    pages: list[dict[str, Any]] = []
    page_index = 0
    while start < END_MS:
        params = {
            "currency": currency,
            "start_timestamp": start,
            "end_timestamp": END_MS - 1,
            "resolution": "3600",
        }
        url = endpoint + "?" + urllib.parse.urlencode(params)
        payload = fetch_bytes(url)
        RAW.mkdir(parents=True, exist_ok=True)
        raw_path = RAW / f"{currency.lower()}-{page_index:03d}.json"
        raw_path.write_bytes(payload)
        parsed = json.loads(payload)
        if "error" in parsed:
            raise ValueError(f"Deribit {currency} error: {parsed['error']}")
        result = parsed.get("result")
        if not isinstance(result, dict):
            raise ValueError(f"Deribit {currency} invalid result")
        data = result.get("data", [])
        if not isinstance(data, list) or not data:
            raise ValueError(f"Deribit {currency} empty page at {start}")
        page_first: int | None = None
        page_last: int | None = None
        for item in data:
            if not isinstance(item, list) or len(item) < 5:
                raise ValueError(f"Deribit {currency} invalid candle")
            ts = int(item[0])
            close = float(item[4])
            if not math.isfinite(close) or close <= 0:
                raise ValueError(f"Deribit {currency} invalid close")
            if ts % 3_600_000 != 0:
                raise ValueError(f"Deribit {currency} non-hour timestamp {ts}")
            old = rows_by_ts.get(ts)
            if old is not None and not math.isclose(old, close, rel_tol=0, abs_tol=0):
                raise ValueError(f"Deribit {currency} conflicting duplicate {ts}")
            rows_by_ts[ts] = close
            page_first = ts if page_first is None else min(page_first, ts)
            page_last = ts if page_last is None else max(page_last, ts)
        continuation = result.get("continuation")
        pages.append(
            {
                "page": page_index,
                "url": url,
                "request_start_ms": start,
                "response_sha256": sha256_bytes(payload),
                "bytes": len(payload),
                "rows": len(data),
                "first_ts": page_first,
                "last_ts": page_last,
                "continuation": continuation,
            }
        )
        page_index += 1
        if continuation is None:
            break
        next_start = int(continuation)
        if next_start <= start:
            if page_last is None:
                raise ValueError(f"Deribit {currency} stalled pagination")
            next_start = page_last + 3_600_000
        start = next_start
        if page_index > 200:
            raise ValueError(f"Deribit {currency} excessive pages")
    rows = sorted((ts, value) for ts, value in rows_by_ts.items() if START_MS <= ts < END_MS)
    expected_grid = list(range(START_MS, END_MS, 3_600_000))
    timestamps = [row[0] for row in rows]
    if timestamps != expected_grid:
        missing = sorted(set(expected_grid) - set(timestamps))
        extra = sorted(set(timestamps) - set(expected_grid))
        raise ValueError(
            f"Deribit {currency} grid mismatch rows={len(rows)} "
            f"missing={len(missing)} extra={len(extra)} "
            f"first_missing={missing[:3]} first_extra={extra[:3]}"
        )
    return rows, {
        "provider": "Deribit",
        "currency": currency,
        "endpoint": endpoint,
        "resolution": 3600,
        "pages": pages,
    }


def write_normalized_spot(symbol: str, bars: list[SpotBar]) -> dict[str, Any]:
    NORMALIZED.mkdir(parents=True, exist_ok=True)
    path = NORMALIZED / f"{symbol.lower()}-1h.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["timestamp_ms", "open", "high", "low", "close"])
        for bar in bars:
            writer.writerow(
                [
                    bar.ts,
                    format(bar.open, ".15g"),
                    format(bar.high, ".15g"),
                    format(bar.low, ".15g"),
                    format(bar.close, ".15g"),
                ]
            )
    return {"path": str(path), "sha256": sha256_file(path), "rows": len(bars)}


def write_normalized_dvol(currency: str, rows: list[tuple[int, float]]) -> dict[str, Any]:
    NORMALIZED.mkdir(parents=True, exist_ok=True)
    path = NORMALIZED / f"{currency.lower()}-dvol-1h.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["timestamp_ms", "close"])
        for ts, close in rows:
            writer.writerow([ts, format(close, ".15g")])
    return {"path": str(path), "sha256": sha256_file(path), "rows": len(rows)}


def average_ranks(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=float)
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and values[order[end]] == values[order[start]]:
            end += 1
        rank = 0.5 * (start + end - 1) + 1.0
        ranks[order[start:end]] = rank
        start = end
    return ranks


def corr(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 3:
        return float("nan")
    sx = float(np.std(x, ddof=1))
    sy = float(np.std(y, ddof=1))
    if sx <= 0 or sy <= 0:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    return corr(average_ranks(x), average_ranks(y))


def standardized_slope(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 3:
        return float("nan")
    sx = float(np.std(x, ddof=1))
    if sx <= 0:
        return float("nan")
    centered_x = x - float(np.mean(x))
    centered_y = y - float(np.mean(y))
    denominator = float(np.dot(centered_x, centered_x))
    if denominator <= 0:
        return float("nan")
    raw = float(np.dot(centered_x, centered_y) / denominator)
    return raw * sx


def percentile_interval(values: list[float]) -> list[float]:
    array = np.asarray([value for value in values if math.isfinite(value)], dtype=float)
    if len(array) == 0:
        return [float("nan"), float("nan")]
    return [float(np.percentile(array, 2.5)), float(np.percentile(array, 97.5))]


def non_circular_blocks(n: int, block: int, rng: np.random.Generator) -> np.ndarray:
    chunks: list[np.ndarray] = []
    needed = math.ceil(n / block)
    max_start = n - block
    starts = rng.integers(0, max_start + 1, size=needed)
    for start in starts:
        chunks.append(np.arange(int(start), int(start) + block))
    return np.concatenate(chunks)[:n]


def bootstrap_calendar(
    state: np.ndarray,
    gross: np.ndarray,
    adverse: np.ndarray,
    eligible: np.ndarray,
) -> dict[str, Any]:
    rng = np.random.default_rng(SEED)
    gross_rhos: list[float] = []
    adverse_rhos: list[float] = []
    gross_slopes: list[float] = []
    adverse_slopes: list[float] = []
    valid = 0
    n = len(state)
    for _ in range(N_BOOT):
        indices = non_circular_blocks(n, 7, rng)
        mask = eligible[indices]
        if int(np.sum(mask)) < 200:
            continue
        selected_state = state[indices][mask]
        selected_gross = gross[indices][mask]
        selected_adverse = adverse[indices][mask]
        if float(np.std(selected_state, ddof=1)) <= 0:
            continue
        values = (
            spearman(selected_state, selected_gross),
            spearman(selected_state, selected_adverse),
            standardized_slope(selected_state, selected_gross),
            standardized_slope(selected_state, selected_adverse),
        )
        if not all(math.isfinite(value) for value in values):
            continue
        gross_rhos.append(values[0])
        adverse_rhos.append(values[1])
        gross_slopes.append(values[2])
        adverse_slopes.append(values[3])
        valid += 1
    return {
        "valid_draws": valid,
        "valid_fraction": valid / N_BOOT,
        "gross_rho_ci": percentile_interval(gross_rhos),
        "adverse_rho_ci": percentile_interval(adverse_rhos),
        "gross_slope_ci": percentile_interval(gross_slopes),
        "adverse_slope_ci": percentile_interval(adverse_slopes),
    }


def segment_slopes(
    state: np.ndarray,
    target: np.ndarray,
    eligible: np.ndarray,
    groups: np.ndarray,
) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    for group in sorted(set(groups.tolist())):
        mask = eligible & (groups == group)
        key = str(group)
        if int(np.sum(mask)) < 10:
            result[key] = None
        else:
            value = standardized_slope(state[mask], target[mask])
            result[key] = value if math.isfinite(value) else None
    return result


def median_split_effect(state: np.ndarray, target: np.ndarray) -> tuple[float, int, int]:
    median = float(np.median(state))
    low = state <= median
    high = state > median
    return float(np.mean(target[high]) - np.mean(target[low])), int(np.sum(low)), int(np.sum(high))


def analyze_arm(
    symbol: str,
    bars: list[SpotBar],
    dvol_rows: list[tuple[int, float]],
) -> dict[str, Any]:
    timestamps = np.asarray([bar.ts for bar in bars], dtype=np.int64)
    opens = np.asarray([bar.open for bar in bars], dtype=float)
    lows = np.asarray([bar.low for bar in bars], dtype=float)
    closes = np.asarray([bar.close for bar in bars], dtype=float)
    dvol = np.asarray([value for _, value in dvol_rows], dtype=float)
    returns = np.full(len(closes), np.nan)
    returns[1:] = np.log(closes[1:] / closes[:-1])

    daily_indices = np.where(
        (timestamps >= TRAIN_START_MS)
        & (timestamps < TRAIN_END_MS)
        & (((timestamps // 3_600_000) % 24) == 0)
    )[0]
    n_daily = len(daily_indices)
    state = np.full(n_daily, np.nan)
    gross = np.full(n_daily, np.nan)
    adverse = np.full(n_daily, np.nan)
    gross_delay = np.full(n_daily, np.nan)
    adverse_delay = np.full(n_daily, np.nan)
    eligible = np.zeros(n_daily, dtype=bool)
    dates: list[datetime] = []

    for daily_index, t in enumerate(daily_indices):
        dates.append(datetime.fromtimestamp(int(timestamps[t]) / 1000, tz=timezone.utc))
        if t < 2161 or t < 744 or t < 192 or t + 25 >= len(bars):
            continue
        if not closes[t - 1] > closes[t - 2161]:
            continue
        rv_window = returns[t - 744 : t - 24]
        iv_window = dvol[t - 192 : t - 24] / 100.0
        if len(rv_window) != 720 or len(iv_window) != 168:
            continue
        if not np.all(np.isfinite(rv_window)) or not np.all(np.isfinite(iv_window)):
            continue
        realized = math.sqrt(8760.0 * float(np.mean(rv_window**2)))
        implied = float(np.median(iv_window))
        if not (
            math.isfinite(realized)
            and realized > 0
            and math.isfinite(implied)
            and implied > 0
        ):
            continue
        state[daily_index] = -math.log(implied / realized)
        gross[daily_index] = math.log(opens[t + 24] / opens[t])
        path = np.log(lows[t : t + 24] / opens[t])
        adverse[daily_index] = min(0.0, float(np.min(path)))
        gross_delay[daily_index] = math.log(opens[t + 25] / opens[t + 1])
        delayed_path = np.log(lows[t + 1 : t + 25] / opens[t + 1])
        adverse_delay[daily_index] = min(0.0, float(np.min(delayed_path)))
        eligible[daily_index] = True

    selected_state = state[eligible]
    selected_gross = gross[eligible]
    selected_adverse = adverse[eligible]
    selected_gross_delay = gross_delay[eligible]
    selected_adverse_delay = adverse_delay[eligible]
    if len(selected_state) == 0:
        raise ValueError(f"{symbol} no eligible anchors")

    fold_ids = np.floor(np.arange(n_daily) * 6 / n_daily).astype(int)
    quarter_ids = np.asarray(
        [f"{date.year}-Q{(date.month - 1) // 3 + 1}" for date in dates], dtype=object
    )
    gross_fold = segment_slopes(state, gross, eligible, fold_ids)
    adverse_fold = segment_slopes(state, adverse, eligible, fold_ids)
    gross_quarter = segment_slopes(state, gross, eligible, quarter_ids)
    adverse_quarter = segment_slopes(state, adverse, eligible, quarter_ids)

    gross_effect, low_count, high_count = median_split_effect(selected_state, selected_gross)
    adverse_effect, _, _ = median_split_effect(selected_state, selected_adverse)
    uncertainty = bootstrap_calendar(state, gross, adverse, eligible)
    delay_uncertainty = bootstrap_calendar(state, gross_delay, adverse_delay, eligible)

    positive_gross_fold_effects: list[float] = []
    for fold in range(6):
        mask = eligible & (fold_ids == fold)
        if int(np.sum(mask)) < 10:
            continue
        effect, _, _ = median_split_effect(state[mask], gross[mask])
        if effect > 0:
            positive_gross_fold_effects.append(effect)
    concentration = (
        max(positive_gross_fold_effects) / sum(positive_gross_fold_effects)
        if positive_gross_fold_effects
        else float("nan")
    )

    point = {
        "gross_rho": spearman(selected_state, selected_gross),
        "adverse_rho": spearman(selected_state, selected_adverse),
        "gross_standardized_slope": standardized_slope(selected_state, selected_gross),
        "adverse_standardized_slope": standardized_slope(selected_state, selected_adverse),
        "gross_high_minus_low": gross_effect,
        "adverse_high_minus_low": adverse_effect,
    }
    delay = {
        "gross_rho": spearman(selected_state, selected_gross_delay),
        "adverse_rho": spearman(selected_state, selected_adverse_delay),
        "gross_standardized_slope": standardized_slope(
            selected_state, selected_gross_delay
        ),
        "adverse_standardized_slope": standardized_slope(
            selected_state, selected_adverse_delay
        ),
        "gross_high_minus_low": median_split_effect(
            selected_state, selected_gross_delay
        )[0],
        "adverse_high_minus_low": median_split_effect(
            selected_state, selected_adverse_delay
        )[0],
    }

    quantiles = np.percentile(selected_state, [0, 25, 50, 75, 100])
    gross_positive_folds = sum(
        value is not None and value > 0 for value in gross_fold.values()
    )
    adverse_positive_folds = sum(
        value is not None and value > 0 for value in adverse_fold.values()
    )
    gross_positive_quarters = sum(
        value is not None and value > 0 for value in gross_quarter.values()
    )
    adverse_positive_quarters = sum(
        value is not None and value > 0 for value in adverse_quarter.values()
    )

    gates = {
        "support_at_least_250": len(selected_state) >= 250,
        "state_iqr_at_least_0_10": float(quantiles[3] - quantiles[1]) >= 0.10,
        "median_groups_at_least_100": low_count >= 100 and high_count >= 100,
        "positive_point_rhos": point["gross_rho"] > 0 and point["adverse_rho"] > 0,
        "positive_point_slopes": (
            point["gross_standardized_slope"] > 0
            and point["adverse_standardized_slope"] > 0
        ),
        "positive_uncertainty_lower_bounds": (
            uncertainty["gross_rho_ci"][0] > 0
            and uncertainty["adverse_rho_ci"][0] > 0
            and uncertainty["gross_slope_ci"][0] > 0
            and uncertainty["adverse_slope_ci"][0] > 0
        ),
        "positive_median_split_effects": gross_effect > 0 and adverse_effect > 0,
        "fold_breadth_4_of_6": gross_positive_folds >= 4
        and adverse_positive_folds >= 4,
        "quarter_breadth_6": gross_positive_quarters >= 6
        and adverse_positive_quarters >= 6,
        "positive_effect_concentration_at_most_0_50": math.isfinite(concentration)
        and concentration <= 0.50,
        "delay_positive_points_and_lower_bounds": (
            delay["gross_rho"] > 0
            and delay["adverse_rho"] > 0
            and delay["gross_standardized_slope"] > 0
            and delay["adverse_standardized_slope"] > 0
            and delay_uncertainty["gross_rho_ci"][0] > 0
            and delay_uncertainty["adverse_rho_ci"][0] > 0
            and delay_uncertainty["gross_slope_ci"][0] > 0
            and delay_uncertainty["adverse_slope_ci"][0] > 0
        ),
    }
    return {
        "symbol": symbol,
        "daily_training_decisions": n_daily,
        "eligible_e2160_long_anchors": int(len(selected_state)),
        "state_quantiles": {
            "min": float(quantiles[0]),
            "q25": float(quantiles[1]),
            "median": float(quantiles[2]),
            "q75": float(quantiles[3]),
            "max": float(quantiles[4]),
            "iqr": float(quantiles[3] - quantiles[1]),
        },
        "median_group_counts": {"low": low_count, "high": high_count},
        "independent_label_economics": {
            "mean_gross_24h": float(np.mean(selected_gross)),
            "mean_net_24h_after_10bps": float(np.mean(selected_gross) - 0.001),
            "mean_adverse_24h": float(np.mean(selected_adverse)),
            "positive_gross_fraction": float(np.mean(selected_gross > 0)),
            "turnover_per_label": 2,
            "fee_per_label": 0.001,
        },
        "point_estimates": point,
        "uncertainty": uncertainty,
        "one_hour_delay": {
            "point_estimates": delay,
            "uncertainty": delay_uncertainty,
        },
        "folds": {
            "gross_standardized_slopes": gross_fold,
            "adverse_standardized_slopes": adverse_fold,
            "positive_gross": gross_positive_folds,
            "positive_adverse": adverse_positive_folds,
        },
        "quarters": {
            "gross_standardized_slopes": gross_quarter,
            "adverse_standardized_slopes": adverse_quarter,
            "positive_gross": gross_positive_quarters,
            "positive_adverse": adverse_positive_quarters,
        },
        "positive_gross_effect_concentration": concentration,
        "gates": gates,
        "passed": all(gates.values()),
    }


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        value = float(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def render_report(evidence: dict[str, Any]) -> str:
    lines = [
        "# Forward-minus-realized volatility-premium diagnostic",
        "",
        "```text",
        f"family                  {FAMILY}",
        "candidate count         0",
        "parameter grid          0",
        f"source rows             {EXPECTED_ROWS} per series",
        "training                2021-07-01 through 2023-12-31 UTC",
        "sealed OOS              2024-01-01 through 2025-12-31 UTC",
        f"verdict                 {evidence['verdict']}",
        "```",
        "",
    ]
    if evidence.get("source_error"):
        lines += ["## Source failure", "", f"`{evidence['source_error']}`", ""]
        return "\n".join(lines)
    lines += [
        "## Training-only information results",
        "",
        "| Market | Eligible | Safety IQR | Gross rho | Adverse rho | Gross slope | Adverse slope | Gates |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for arm in evidence["arms"]:
        point = arm["point_estimates"]
        lines.append(
            f"| {arm['symbol']} | {arm['eligible_e2160_long_anchors']} | "
            f"{arm['state_quantiles']['iqr']:.6f} | {point['gross_rho']:.6f} | "
            f"{point['adverse_rho']:.6f} | "
            f"{point['gross_standardized_slope']:.8f} | "
            f"{point['adverse_standardized_slope']:.8f} | "
            f"{sum(arm['gates'].values())}/{len(arm['gates'])} |"
        )
    lines += [
        "",
        "## Candidate economics",
        "",
        "No executable candidate was authorised. Candidate train/OOS/full return, Sharpe, "
        "benchmark comparison, maximum drawdown, continuous turnover and edge per turnover "
        "are null rather than zero. Each diagnostic label charged exactly 5 bps on entry "
        "and 5 bps on exit.",
        "",
        "## Machine-readable identities",
        "",
        "- Source manifest: `source_manifest.json`",
        "- Normalized source directory: `normalized/`",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    evidence: dict[str, Any] = {
        "family_id": FAMILY,
        "issue": 936,
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "bar": "1H",
        "fee_one_way": FEE_ONE_WAY,
        "expected_rows_per_series": EXPECTED_ROWS,
        "training_interval": ["2021-07-01T00:00:00Z", "2024-01-01T00:00:00Z"],
        "sealed_oos_interval": ["2024-01-01T00:00:00Z", "2026-01-01T00:00:00Z"],
        "oos_accessed": False,
        "candidate_metrics": {
            "train": None,
            "oos": None,
            "full": None,
            "sharpe": None,
            "benchmark_comparison": None,
            "turnover": None,
            "drawdown": None,
            "edge_per_turnover": None,
        },
    }
    manifest: dict[str, Any] = {"family_id": FAMILY, "sources": []}
    try:
        datasets: dict[str, tuple[list[SpotBar], list[tuple[int, float]]]] = {}
        normalized: list[dict[str, Any]] = []
        for symbol, currency in (("BTCUSDT", "BTC"), ("ETHUSDT", "ETH")):
            spot, spot_manifest = acquire_binance(symbol)
            dvol, dvol_manifest = acquire_dvol(currency)
            if [bar.ts for bar in spot] != [row[0] for row in dvol]:
                raise ValueError(f"{symbol}/{currency} common-grid mismatch")
            datasets[symbol] = (spot, dvol)
            manifest["sources"].extend([spot_manifest, dvol_manifest])
            normalized.extend(
                [write_normalized_spot(symbol, spot), write_normalized_dvol(currency, dvol)]
            )
        manifest["normalized"] = normalized
        manifest_path = OUT / "source_manifest.json"
        manifest_path.write_text(
            json.dumps(json_safe(manifest), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        evidence["source_manifest_sha256"] = sha256_file(manifest_path)
        evidence["normalized"] = normalized
        arms = [
            analyze_arm(symbol, datasets[symbol][0], datasets[symbol][1])
            for symbol in ("BTCUSDT", "ETHUSDT")
        ]
        evidence["arms"] = arms
        evidence["source_contract_passed"] = True
        evidence["markets_passing"] = sum(arm["passed"] for arm in arms)
        evidence["verdict"] = ACCEPT if all(arm["passed"] for arm in arms) else REJECT
    except Exception as exc:  # noqa: BLE001
        evidence["source_contract_passed"] = False
        evidence["source_error"] = f"{type(exc).__name__}: {exc}"
        evidence["markets_passing"] = 0
        evidence["verdict"] = REJECT

    evidence_path = OUT / "evidence.json"
    safe = json_safe(evidence)
    evidence_path.write_text(
        json.dumps(safe, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report = render_report(safe)
    (OUT / "report.md").write_text(report + "\n", encoding="utf-8")
    print(report)
    print(f"evidence sha256: {sha256_file(evidence_path)}")
    print(f"report sha256: {sha256_file(OUT / 'report.md')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
