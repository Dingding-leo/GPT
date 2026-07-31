from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import shutil
import statistics
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

BASE_URL = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision/data"
FAMILY_ID = "coinm-liquidation-exhaustion-opportunity-diagnostic-1h-v1"
START_DAY = date(2024, 1, 1)
END_DAY = date(2024, 9, 30)
SCORE_START = date(2024, 2, 1)
SCORE_END = date(2024, 9, 29)
FEE_ONE_WAY = 0.0005
SEED = 20260801
RESAMPLES = 5000
BLOCK_LENGTH = 7
MIN_BOOTSTRAP_OBS = 180
LIQ_COLUMNS = [
    "time",
    "side",
    "order_type",
    "time_in_force",
    "original_quantity",
    "price",
    "average_price",
    "order_status",
    "last_fill_quantity",
    "accumulated_fill_quantity",
]
KLINE_COLUMNS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "count",
    "taker_buy_volume",
    "taker_buy_quote_volume",
    "ignore",
]
MARKETS = {
    "BTCUSDT": "BTCUSD_PERP",
    "ETHUSDT": "ETHUSD_PERP",
}
USER_AGENT = "gpt-quant-lab/coinm-liquidation-diagnostic"


class DiagnosticError(RuntimeError):
    pass


@dataclass(frozen=True)
class ObjectSpec:
    market: str
    kind: str
    period: str
    url: str
    checksum_url: str


@dataclass
class DownloadRecord:
    market: str
    kind: str
    period: str
    url: str
    checksum_url: str
    expected_sha256: str
    actual_sha256: str
    byte_count: int
    local_path: str
    checksum_text: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=16)
    return parser.parse_args()


def date_range(start: date, end: date) -> list[date]:
    days: list[date] = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return days


def month_range(start: date, end: date) -> list[str]:
    months: list[str] = []
    current = date(start.year, start.month, 1)
    while current <= end:
        months.append(current.strftime("%Y-%m"))
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)
    return months


def build_specs() -> list[ObjectSpec]:
    specs: list[ObjectSpec] = []
    for spot, coinm in MARKETS.items():
        for month in month_range(START_DAY, END_DAY):
            filename = f"{spot}-1h-{month}.zip"
            url = f"{BASE_URL}/spot/monthly/klines/{spot}/1h/{filename}"
            specs.append(
                ObjectSpec(
                    market=spot,
                    kind="spot_1h_kline",
                    period=month,
                    url=url,
                    checksum_url=f"{url}.CHECKSUM",
                )
            )
        for day in date_range(START_DAY, END_DAY):
            period = day.isoformat()
            filename = f"{coinm}-liquidationSnapshot-{period}.zip"
            url = (
                f"{BASE_URL}/futures/cm/daily/liquidationSnapshot/"
                f"{coinm}/{filename}"
            )
            specs.append(
                ObjectSpec(
                    market=spot,
                    kind="coinm_liquidation_snapshot",
                    period=period,
                    url=url,
                    checksum_url=f"{url}.CHECKSUM",
                )
            )
    return specs


def http_get(url: str, attempts: int = 5) -> bytes:
    last_error: Exception | None = None
    for attempt in range(attempts):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                if response.status != 200:
                    raise DiagnosticError(f"unexpected HTTP status {response.status}: {url}")
                return response.read()
        except (urllib.error.URLError, TimeoutError, DiagnosticError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(1.0 * (2**attempt))
    raise DiagnosticError(f"download failed after {attempts} attempts: {url}: {last_error}")


def parse_checksum(text: str, url: str) -> str:
    fields = text.strip().split()
    if not fields or len(fields[0]) != 64:
        raise DiagnosticError(f"invalid checksum response: {url}: {text!r}")
    digest = fields[0].lower()
    if any(character not in "0123456789abcdef" for character in digest):
        raise DiagnosticError(f"non-hex checksum: {url}: {digest}")
    return digest


def safe_component(value: str) -> str:
    return value.replace("/", "_").replace(":", "_")


def download_one(spec: ObjectSpec, raw_dir: Path) -> DownloadRecord:
    checksum_bytes = http_get(spec.checksum_url)
    checksum_text = checksum_bytes.decode("utf-8", errors="strict")
    expected = parse_checksum(checksum_text, spec.checksum_url)
    payload = http_get(spec.url)
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected:
        raise DiagnosticError(
            f"checksum mismatch for {spec.url}: expected {expected}, actual {actual}"
        )
    target_dir = raw_dir / spec.market / spec.kind
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{safe_component(spec.period)}-{Path(spec.url).name}"
    target = target_dir / filename
    target.write_bytes(payload)
    target.with_suffix(target.suffix + ".CHECKSUM").write_text(
        checksum_text, encoding="utf-8"
    )
    return DownloadRecord(
        market=spec.market,
        kind=spec.kind,
        period=spec.period,
        url=spec.url,
        checksum_url=spec.checksum_url,
        expected_sha256=expected,
        actual_sha256=actual,
        byte_count=len(payload),
        local_path=str(target),
        checksum_text=checksum_text.strip(),
    )


def download_all(
    specs: list[ObjectSpec], raw_dir: Path, workers: int
) -> list[DownloadRecord]:
    records: list[DownloadRecord] = []
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {executor.submit(download_one, spec, raw_dir): spec for spec in specs}
        for future in as_completed(futures):
            spec = futures[future]
            try:
                records.append(future.result())
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{spec.kind} {spec.market} {spec.period}: {exc}")
    if failures:
        failures.sort()
        preview = "\n".join(failures[:20])
        raise DiagnosticError(
            f"{len(failures)} source objects failed; first failures:\n{preview}"
        )
    records.sort(key=lambda item: (item.market, item.kind, item.period))
    return records


def read_zip_csv(path: Path) -> bytes:
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if not name.endswith("/")]
        if len(names) != 1 or not names[0].lower().endswith(".csv"):
            raise DiagnosticError(f"expected exactly one CSV member in {path}: {names}")
        return archive.read(names[0])


def parse_spot_market(records: list[DownloadRecord], market: str) -> pd.DataFrame:
    chunks: list[pd.DataFrame] = []
    selected = [
        record
        for record in records
        if record.market == market and record.kind == "spot_1h_kline"
    ]
    if len(selected) != 9:
        raise DiagnosticError(f"expected 9 spot monthly files for {market}, got {len(selected)}")
    for record in selected:
        payload = read_zip_csv(Path(record.local_path))
        frame = pd.read_csv(io.BytesIO(payload), header=None, names=KLINE_COLUMNS)
        if frame.shape[1] != len(KLINE_COLUMNS):
            raise DiagnosticError(f"unexpected spot schema for {record.local_path}")
        chunks.append(frame)
    data = pd.concat(chunks, ignore_index=True)
    numeric_columns = [
        "open_time",
        "open",
        "high",
        "low",
        "close",
        "close_time",
    ]
    for column in numeric_columns:
        data[column] = pd.to_numeric(data[column], errors="raise")
    if not np.isfinite(data[numeric_columns].to_numpy(dtype=float)).all():
        raise DiagnosticError(f"non-finite spot values for {market}")
    if (data[["open", "high", "low", "close"]].to_numpy(dtype=float) <= 0).any():
        raise DiagnosticError(f"non-positive spot price for {market}")
    data["open_time"] = data["open_time"].astype("int64")
    if data["open_time"].duplicated().any():
        duplicates = int(data["open_time"].duplicated().sum())
        raise DiagnosticError(f"duplicate spot open times for {market}: {duplicates}")
    data = data.sort_values("open_time", kind="stable").reset_index(drop=True)
    expected_start = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    expected_end = int(datetime(2024, 10, 1, tzinfo=timezone.utc).timestamp() * 1000)
    expected = np.arange(expected_start, expected_end, 3_600_000, dtype=np.int64)
    observed = data["open_time"].to_numpy(dtype=np.int64)
    if not np.array_equal(observed, expected):
        missing = np.setdiff1d(expected, observed)
        extra = np.setdiff1d(observed, expected)
        raise DiagnosticError(
            f"spot grid mismatch for {market}: rows={len(observed)}, expected={len(expected)}, "
            f"missing={len(missing)}, extra={len(extra)}"
        )
    data["timestamp"] = pd.to_datetime(data["open_time"], unit="ms", utc=True)
    return data


def parse_liquidation_payload(
    payload: bytes, record: DownloadRecord
) -> tuple[pd.DataFrame, bool]:
    if not payload.strip():
        return pd.DataFrame(columns=LIQ_COLUMNS), False
    rows = list(csv.reader(io.StringIO(payload.decode("utf-8", errors="strict"))))
    if not rows:
        return pd.DataFrame(columns=LIQ_COLUMNS), False
    header_present = rows[0] == LIQ_COLUMNS
    data_rows = rows[1:] if header_present else rows
    for row in data_rows:
        if len(row) != len(LIQ_COLUMNS):
            raise DiagnosticError(
                f"unexpected liquidation schema width for {record.local_path}: {len(row)}"
            )
    return pd.DataFrame(data_rows, columns=LIQ_COLUMNS), header_present


def normalize_timestamp_ms(values: pd.Series, context: str) -> pd.Series:
    numeric = pd.to_numeric(values, errors="raise").astype("int64")
    if numeric.empty:
        return numeric
    maximum = int(numeric.abs().max())
    if maximum >= 10**17:
        raise DiagnosticError(f"unsupported timestamp magnitude for {context}: {maximum}")
    if maximum >= 10**14:
        numeric = numeric // 1000
    if int(numeric.abs().max()) < 10**12:
        raise DiagnosticError(f"timestamp is not milliseconds for {context}")
    return numeric


def parse_liquidations(
    records: list[DownloadRecord], market: str
) -> tuple[pd.DataFrame, dict[str, Any]]:
    selected = [
        record
        for record in records
        if record.market == market and record.kind == "coinm_liquidation_snapshot"
    ]
    expected_days = date_range(START_DAY, END_DAY)
    if len(selected) != len(expected_days):
        raise DiagnosticError(
            f"expected {len(expected_days)} liquidation files for {market}, got {len(selected)}"
        )
    selected_by_day = {record.period: record for record in selected}
    daily_rows: list[dict[str, Any]] = []
    raw_total = 0
    dedup_total = 0
    positive_fill_total = 0
    header_files = 0
    for day in expected_days:
        record = selected_by_day.get(day.isoformat())
        if record is None:
            raise DiagnosticError(f"missing liquidation file for {market} {day}")
        payload = read_zip_csv(Path(record.local_path))
        frame, header_present = parse_liquidation_payload(payload, record)
        header_files += int(header_present)
        raw_count = len(frame)
        raw_total += raw_count
        if raw_count:
            frame = frame.drop_duplicates(ignore_index=True)
            dedup_count = raw_count - len(frame)
            dedup_total += dedup_count
            frame["time"] = normalize_timestamp_ms(frame["time"], record.local_path)
            for column in [
                "original_quantity",
                "price",
                "average_price",
                "last_fill_quantity",
                "accumulated_fill_quantity",
            ]:
                frame[column] = pd.to_numeric(frame[column], errors="raise")
            numeric = frame[
                [
                    "original_quantity",
                    "price",
                    "average_price",
                    "last_fill_quantity",
                    "accumulated_fill_quantity",
                ]
            ].to_numpy(dtype=float)
            if not np.isfinite(numeric).all() or (numeric < 0).any():
                raise DiagnosticError(f"invalid liquidation numeric values: {record.local_path}")
            invalid_sides = sorted(set(frame["side"]) - {"BUY", "SELL"})
            if invalid_sides:
                raise DiagnosticError(
                    f"unexpected liquidation sides for {record.local_path}: {invalid_sides}"
                )
            day_start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
            start_ms = int(day_start.timestamp() * 1000)
            end_ms = start_ms + 86_400_000
            outside = frame[(frame["time"] < start_ms) | (frame["time"] >= end_ms)]
            if not outside.empty:
                raise DiagnosticError(
                    f"out-of-day liquidation timestamp for {record.local_path}: {len(outside)}"
                )
            positive = frame[frame["last_fill_quantity"] > 0].copy()
        else:
            dedup_count = 0
            positive = frame.copy()
        positive_fill_total += len(positive)
        sell = float(
            positive.loc[positive["side"] == "SELL", "last_fill_quantity"].sum()
        )
        buy = float(
            positive.loc[positive["side"] == "BUY", "last_fill_quantity"].sum()
        )
        daily_rows.append(
            {
                "day": day.isoformat(),
                "raw_rows": raw_count,
                "exact_duplicates_removed": dedup_count,
                "positive_fill_rows": len(positive),
                "sell_last_fill_quantity": sell,
                "buy_last_fill_quantity": buy,
                "raw_pressure": math.log1p(sell) - math.log1p(buy),
            }
        )
    daily = pd.DataFrame(daily_rows)
    daily["day"] = pd.to_datetime(daily["day"], utc=True)
    summary = {
        "source_days": len(daily),
        "raw_rows": raw_total,
        "exact_duplicates_removed": dedup_total,
        "positive_fill_rows": positive_fill_total,
        "header_files": header_files,
        "zero_event_days": int((daily["positive_fill_rows"] == 0).sum()),
        "sell_last_fill_quantity_total": float(daily["sell_last_fill_quantity"].sum()),
        "buy_last_fill_quantity_total": float(daily["buy_last_fill_quantity"].sum()),
    }
    return daily, summary


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 2 or np.nanstd(x) == 0 or np.nanstd(y) == 0:
        return math.nan
    x_rank = pd.Series(x).rank(method="average").to_numpy(dtype=float)
    y_rank = pd.Series(y).rank(method="average").to_numpy(dtype=float)
    return float(np.corrcoef(x_rank, y_rank)[0, 1])


def standardized_slope(x: np.ndarray, y: np.ndarray) -> float:
    scale = float(np.std(x, ddof=0))
    if len(x) < 2 or not math.isfinite(scale) or scale == 0:
        return math.nan
    z = (x - float(np.mean(x))) / scale
    denominator = float(np.dot(z, z))
    if denominator == 0:
        return math.nan
    centered_y = y - float(np.mean(y))
    return float(np.dot(z, centered_y) / denominator)


def percentile_interval(values: Iterable[float]) -> list[float]:
    array = np.asarray([value for value in values if math.isfinite(value)], dtype=float)
    if array.size == 0:
        return [math.nan, math.nan]
    return [float(np.quantile(array, 0.025)), float(np.quantile(array, 0.975))]


def construct_market_labels(
    spot: pd.DataFrame, liquidations: pd.DataFrame, market: str
) -> pd.DataFrame:
    spot = spot.copy()
    spot["open"] = spot["open"].astype(float)
    spot["close"] = spot["close"].astype(float)
    open_by_time = pd.Series(spot["open"].to_numpy(), index=spot["timestamp"])
    close_by_time = pd.Series(spot["close"].to_numpy(), index=spot["timestamp"])
    log_close = np.log(close_by_time)
    hourly_log_returns = log_close.diff()
    liquidation_by_day = liquidations.set_index("day")
    rows: list[dict[str, Any]] = []
    for decision_day in date_range(SCORE_START, SCORE_END):
        decision_ts = pd.Timestamp(decision_day, tz="UTC")
        feature_ts = decision_ts - pd.Timedelta(days=1)
        prior_start = feature_ts - pd.Timedelta(days=30)
        prior_days = pd.date_range(
            prior_start, feature_ts - pd.Timedelta(days=1), freq="D"
        )
        prior_raw = liquidation_by_day.reindex(prior_days)["raw_pressure"]
        current_raw = liquidation_by_day.loc[feature_ts, "raw_pressure"]
        center = float(prior_raw.median())
        mad = float(np.median(np.abs(prior_raw.to_numpy(dtype=float) - center)))
        scale = 1.4826 * mad
        liq_z = (float(current_raw) - center) / scale if scale > 0 else math.nan

        first_open = float(open_by_time.loc[feature_ts])
        last_hour = decision_ts - pd.Timedelta(hours=1)
        last_close = float(close_by_time.loc[last_hour])
        r24 = math.log(last_close / first_open)
        return_window = hourly_log_returns.loc[
            last_hour - pd.Timedelta(hours=167) : last_hour
        ].to_numpy(dtype=float)
        if len(return_window) != 168 or not np.isfinite(return_window).all():
            raise DiagnosticError(
                f"invalid 168H volatility window for {market} {decision_day}: "
                f"{len(return_window)}"
            )
        sigma_h = float(np.sqrt(np.mean(return_window**2)))
        price_z = r24 / (math.sqrt(24.0) * sigma_h) if sigma_h > 0 else math.nan
        state = liq_z + price_z if math.isfinite(liq_z) and math.isfinite(price_z) else math.nan

        target_times = pd.date_range(decision_ts, periods=25, freq="h")
        target_opens = open_by_time.reindex(target_times).to_numpy(dtype=float)
        if len(target_opens) != 25 or not np.isfinite(target_opens).all():
            raise DiagnosticError(f"incomplete target day for {market} {decision_day}")
        hourly_returns = target_opens[1:] / target_opens[:-1] - 1.0
        gross = float(hourly_returns.sum())
        cumulative = np.concatenate(([0.0], np.cumsum(hourly_returns)))
        adverse = float(np.min(cumulative))
        net = gross - 2.0 * FEE_ONE_WAY
        rows.append(
            {
                "market": market,
                "decision_day": decision_ts,
                "feature_day": feature_ts,
                "current_raw_pressure": float(current_raw),
                "prior_raw_median": center,
                "prior_raw_mad_scale": scale,
                "liq_z": liq_z,
                "r24": r24,
                "sigma_h": sigma_h,
                "price_z": price_z,
                "state": state,
                "gross": gross,
                "net": net,
                "adverse": adverse,
                "turnover": 2.0,
                "fee": 2.0 * FEE_ONE_WAY,
            }
        )
    frame = pd.DataFrame(rows)
    if len(frame) != 242:
        raise DiagnosticError(f"expected 242 intended decisions for {market}, got {len(frame)}")
    frame["calendar_index"] = np.arange(len(frame), dtype=int)
    frame["fold"] = frame["calendar_index"] // 30 + 1
    frame.loc[frame["fold"] > 8, "fold"] = 9
    frame["month"] = frame["decision_day"].dt.strftime("%Y-%m")
    return frame


def segment_slopes(
    frame: pd.DataFrame, column: str
) -> tuple[list[dict[str, Any]], int]:
    records: list[dict[str, Any]] = []
    positives = 0
    for fold in range(1, 9):
        subset = frame[(frame["fold"] == fold) & frame["state"].notna()]
        slope = standardized_slope(
            subset["state"].to_numpy(dtype=float), subset[column].to_numpy(dtype=float)
        )
        if math.isfinite(slope) and slope > 0:
            positives += 1
        records.append(
            {
                "fold": fold,
                "observations": len(subset),
                "slope": slope if math.isfinite(slope) else None,
                "positive": bool(math.isfinite(slope) and slope > 0),
            }
        )
    remainder = frame[(frame["fold"] == 9) & frame["state"].notna()]
    records.append(
        {
            "fold": "remainder",
            "observations": len(remainder),
            "slope": None,
            "positive": False,
        }
    )
    return records, positives


def monthly_slopes(
    frame: pd.DataFrame, column: str
) -> tuple[list[dict[str, Any]], int]:
    records: list[dict[str, Any]] = []
    positives = 0
    for month in [f"2024-{number:02d}" for number in range(2, 10)]:
        subset = frame[(frame["month"] == month) & frame["state"].notna()]
        slope = standardized_slope(
            subset["state"].to_numpy(dtype=float), subset[column].to_numpy(dtype=float)
        )
        if math.isfinite(slope) and slope > 0:
            positives += 1
        records.append(
            {
                "month": month,
                "observations": len(subset),
                "slope": slope if math.isfinite(slope) else None,
                "positive": bool(math.isfinite(slope) and slope > 0),
            }
        )
    return records, positives


def market_point_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    valid = frame[frame["state"].notna()].copy()
    x = valid["state"].to_numpy(dtype=float)
    gross = valid["gross"].to_numpy(dtype=float)
    adverse = valid["adverse"].to_numpy(dtype=float)
    median_state = float(np.median(x)) if len(x) else math.nan
    low = valid[valid["state"] <= median_state]
    high = valid[valid["state"] > median_state]
    gross_folds, positive_gross_folds = segment_slopes(frame, "gross")
    adverse_folds, positive_adverse_folds = segment_slopes(frame, "adverse")
    gross_months, positive_gross_months = monthly_slopes(frame, "gross")
    adverse_months, positive_adverse_months = monthly_slopes(frame, "adverse")
    return {
        "intended_decisions": len(frame),
        "valid_state_decisions": len(valid),
        "invalid_state_decisions": len(frame) - len(valid),
        "state": {
            "min": float(np.min(x)) if len(x) else None,
            "q25": float(np.quantile(x, 0.25)) if len(x) else None,
            "median": median_state if len(x) else None,
            "q75": float(np.quantile(x, 0.75)) if len(x) else None,
            "max": float(np.max(x)) if len(x) else None,
            "iqr": float(np.quantile(x, 0.75) - np.quantile(x, 0.25))
            if len(x)
            else None,
        },
        "point": {
            "gross_spearman": spearman(x, gross),
            "adverse_spearman": spearman(x, adverse),
            "gross_slope_per_state_sd": standardized_slope(x, gross),
            "adverse_slope_per_state_sd": standardized_slope(x, adverse),
        },
        "median_split": {
            "low_observations": len(low),
            "high_observations": len(high),
            "high_minus_low_gross": float(high["gross"].mean() - low["gross"].mean())
            if len(low) and len(high)
            else None,
            "high_minus_low_net": float(high["net"].mean() - low["net"].mean())
            if len(low) and len(high)
            else None,
            "high_minus_low_adverse": float(
                high["adverse"].mean() - low["adverse"].mean()
            )
            if len(low) and len(high)
            else None,
        },
        "target_economics": {
            "gross_mean": float(valid["gross"].mean()) if len(valid) else None,
            "gross_median": float(valid["gross"].median()) if len(valid) else None,
            "net_mean": float(valid["net"].mean()) if len(valid) else None,
            "net_median": float(valid["net"].median()) if len(valid) else None,
            "adverse_mean": float(valid["adverse"].mean()) if len(valid) else None,
            "positive_gross_days": int((valid["gross"] > 0).sum()),
            "positive_net_days": int((valid["net"] > 0).sum()),
            "turnover_total": float(valid["turnover"].sum()),
            "fees_total": float(valid["fee"].sum()),
            "max_absolute_gross_share": float(
                valid["gross"].abs().max() / valid["gross"].abs().sum()
            )
            if len(valid) and valid["gross"].abs().sum() > 0
            else None,
        },
        "breadth": {
            "gross_folds": gross_folds,
            "adverse_folds": adverse_folds,
            "positive_gross_folds": positive_gross_folds,
            "positive_adverse_folds": positive_adverse_folds,
            "gross_months": gross_months,
            "adverse_months": adverse_months,
            "positive_gross_months": positive_gross_months,
            "positive_adverse_months": positive_adverse_months,
        },
    }


def bootstrap(
    markets: dict[str, pd.DataFrame],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    market_names = list(MARKETS)
    calendar_length = 242
    starts_max = calendar_length - BLOCK_LENGTH
    blocks_needed = math.ceil(calendar_length / BLOCK_LENGTH)
    rng = np.random.default_rng(SEED)
    values: dict[str, dict[str, list[float]]] = {
        market: {
            "gross_spearman": [],
            "adverse_spearman": [],
            "gross_slope": [],
            "adverse_slope": [],
        }
        for market in market_names
    }
    common_values = {
        "gross_spearman": [],
        "adverse_spearman": [],
        "gross_slope": [],
        "adverse_slope": [],
    }
    valid_draws = {market: 0 for market in market_names}
    common_valid = 0
    for _ in range(RESAMPLES):
        starts = rng.integers(0, starts_max + 1, size=blocks_needed)
        indices = np.concatenate(
            [np.arange(start, start + BLOCK_LENGTH, dtype=int) for start in starts]
        )[:calendar_length]
        draw_stats: dict[str, dict[str, float]] = {}
        for market in market_names:
            sampled = markets[market].iloc[indices]
            sampled = sampled[sampled["state"].notna()]
            if len(sampled) < MIN_BOOTSTRAP_OBS or sampled["state"].nunique() < 2:
                continue
            x = sampled["state"].to_numpy(dtype=float)
            gross = sampled["gross"].to_numpy(dtype=float)
            adverse = sampled["adverse"].to_numpy(dtype=float)
            stats = {
                "gross_spearman": spearman(x, gross),
                "adverse_spearman": spearman(x, adverse),
                "gross_slope": standardized_slope(x, gross),
                "adverse_slope": standardized_slope(x, adverse),
            }
            if not all(math.isfinite(value) for value in stats.values()):
                continue
            valid_draws[market] += 1
            draw_stats[market] = stats
            for key, value in stats.items():
                values[market][key].append(value)
        if len(draw_stats) == len(market_names):
            common_valid += 1
            for key in common_values:
                common_values[key].append(
                    float(
                        statistics.median(
                            draw_stats[market][key] for market in market_names
                        )
                    )
                )
    market_results: dict[str, dict[str, Any]] = {}
    for market in market_names:
        market_results[market] = {
            "valid_draws": valid_draws[market],
            "valid_fraction": valid_draws[market] / RESAMPLES,
            "ci95": {
                key: percentile_interval(series) for key, series in values[market].items()
            },
        }
    common = {
        "valid_draws": common_valid,
        "valid_fraction": common_valid / RESAMPLES,
        "ci95": {
            key: percentile_interval(series) for key, series in common_values.items()
        },
    }
    return common, market_results


def finite_positive(value: Any) -> bool:
    return value is not None and math.isfinite(float(value)) and float(value) > 0


def apply_gates(
    metrics: dict[str, Any], uncertainty: dict[str, Any], common: dict[str, Any]
) -> dict[str, bool]:
    point = metrics["point"]
    state = metrics["state"]
    split = metrics["median_split"]
    breadth = metrics["breadth"]
    ci = uncertainty["ci95"]
    gates = {
        "gross_positive_lower_bound": finite_positive(point["gross_spearman"])
        and finite_positive(ci["gross_spearman"][0]),
        "adverse_positive_lower_bound": finite_positive(point["adverse_spearman"])
        and finite_positive(ci["adverse_spearman"][0]),
        "positive_slopes": finite_positive(point["gross_slope_per_state_sd"])
        and finite_positive(point["adverse_slope_per_state_sd"]),
        "fold_breadth": breadth["positive_gross_folds"] >= 5
        and breadth["positive_adverse_folds"] >= 5,
        "month_breadth": breadth["positive_gross_months"] >= 5
        and breadth["positive_adverse_months"] >= 5,
        "state_dispersion": state["iqr"] is not None and state["iqr"] >= 1.0,
        "median_support": split["low_observations"] >= 100
        and split["high_observations"] >= 100,
        "median_economics": finite_positive(split["high_minus_low_gross"])
        and finite_positive(split["high_minus_low_adverse"]),
        "bootstrap_validity": uncertainty["valid_fraction"] >= 0.95,
        "common_positive_lower_bounds": finite_positive(
            common["ci95"]["gross_spearman"][0]
        )
        and finite_positive(common["ci95"]["adverse_spearman"][0]),
    }
    gates["all"] = all(gates.values())
    return gates


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
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    return value


def render_report(result: dict[str, Any]) -> str:
    lines = [
        "# COIN-M liquidation-exhaustion information diagnostic",
        "",
        "```text",
        f"family          {FAMILY_ID}",
        "candidate count 0",
        "diagnostic      1",
        "parameter grid  0",
        "markets         BTCUSDT and ETHUSDT independently",
        "bar             Binance public SPOT 1H + lagged COIN-M liquidation snapshots",
        "fee             exactly 5 bps one way inside target sleeves",
        f"markets passing {result['markets_passing']}/2",
        f"verdict         {result['verdict']}",
        "```",
        "",
        "## Data and sample",
        "",
        f"Source objects: {result['source']['object_count']} with checksum matches "
        f"{result['source']['checksum_matches']}/{result['source']['object_count']}.",
        "Scored calendar: 2024-02-01 through 2024-09-29 UTC, 242 intended daily labels.",
        "",
        "## Results",
        "",
        "| Market | Valid | Gross rho (95% CI) | Adverse rho (95% CI) | "
        "Gross slope | Adverse slope | Folds G/A | Months G/A | IQR |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for market in MARKETS:
        item = result["markets"][market]
        point = item["metrics"]["point"]
        ci = item["uncertainty"]["ci95"]
        breadth = item["metrics"]["breadth"]
        lines.append(
            f"| {market} | {item['metrics']['valid_state_decisions']} | "
            f"{point['gross_spearman']:+.4f} [{ci['gross_spearman'][0]:+.4f},"
            f"{ci['gross_spearman'][1]:+.4f}] | "
            f"{point['adverse_spearman']:+.4f} [{ci['adverse_spearman'][0]:+.4f},"
            f"{ci['adverse_spearman'][1]:+.4f}] | "
            f"{point['gross_slope_per_state_sd']:+.4%} | "
            f"{point['adverse_slope_per_state_sd']:+.4%} | "
            f"{breadth['positive_gross_folds']}/8 / "
            f"{breadth['positive_adverse_folds']}/8 | "
            f"{breadth['positive_gross_months']}/8 / "
            f"{breadth['positive_adverse_months']}/8 | "
            f"{item['metrics']['state']['iqr']:.4f} |"
        )
    common = result["common_index"]
    lines.extend(
        [
            "",
            "## Common-index uncertainty",
            "",
            "```text",
            f"valid draws          {common['valid_draws']}/{RESAMPLES} "
            f"({common['valid_fraction']:.2%})",
            "gross rho CI        "
            f"[{common['ci95']['gross_spearman'][0]:+.4f},"
            f"{common['ci95']['gross_spearman'][1]:+.4f}]",
            "adverse rho CI      "
            f"[{common['ci95']['adverse_spearman'][0]:+.4f},"
            f"{common['ci95']['adverse_spearman'][1]:+.4f}]",
            "```",
            "",
            "## Verdict",
            "",
            f"`{result['verdict']}`",
            "",
            "Candidate count is zero. These are information-label economics, not an executable "
            "strategy backtest; therefore full/train/OOS strategy return, Sharpe, drawdown, "
            "benchmark residual and edge-per-turnover metrics are not applicable.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    output_dir: Path = args.output_dir
    if output_dir.exists():
        shutil.rmtree(output_dir)
    raw_dir = output_dir / "raw"
    output_dir.mkdir(parents=True)
    raw_dir.mkdir(parents=True)

    specs = build_specs()
    records = download_all(specs, raw_dir, args.workers)
    manifest = [record.__dict__ for record in records]
    (output_dir / "source-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    market_frames: dict[str, pd.DataFrame] = {}
    market_payload: dict[str, dict[str, Any]] = {}
    for market in MARKETS:
        spot = parse_spot_market(records, market)
        liquidations, source_summary = parse_liquidations(records, market)
        labels = construct_market_labels(spot, liquidations, market)
        market_frames[market] = labels
        liquidations.to_csv(output_dir / f"{market}-daily-liquidations.csv", index=False)
        labels.to_csv(output_dir / f"{market}-labels.csv", index=False)
        metrics = market_point_metrics(labels)
        market_payload[market] = {
            "source": source_summary,
            "spot_rows": len(spot),
            "spot_first": spot["timestamp"].iloc[0].isoformat(),
            "spot_last": spot["timestamp"].iloc[-1].isoformat(),
            "metrics": metrics,
        }

    common, uncertainty = bootstrap(market_frames)
    markets_passing = 0
    for market in MARKETS:
        market_payload[market]["uncertainty"] = uncertainty[market]
        market_payload[market]["gates"] = apply_gates(
            market_payload[market]["metrics"], uncertainty[market], common
        )
        markets_passing += int(market_payload[market]["gates"]["all"])

    accepted = markets_passing == len(MARKETS)
    verdict = (
        "coinm_liquidation_exhaustion_information_premise_passed"
        if accepted
        else "reject_coinm_liquidation_exhaustion_information_premise"
    )
    result = {
        "family_id": FAMILY_ID,
        "classification": "training-only exogenous-information eligibility diagnostic",
        "candidate_count": 0,
        "diagnostic_count": 1,
        "parameter_grid_count": 0,
        "fee_one_way": FEE_ONE_WAY,
        "seed": SEED,
        "resamples": RESAMPLES,
        "block_length_days": BLOCK_LENGTH,
        "accepted": accepted,
        "markets_passing": markets_passing,
        "verdict": verdict,
        "source": {
            "base_url": BASE_URL,
            "object_count": len(records),
            "checksum_matches": sum(
                record.expected_sha256 == record.actual_sha256 for record in records
            ),
            "source_start": START_DAY.isoformat(),
            "source_end": END_DAY.isoformat(),
        },
        "sample": {
            "score_start": SCORE_START.isoformat(),
            "score_end": SCORE_END.isoformat(),
            "intended_decisions": 242,
        },
        "markets": market_payload,
        "common_index": common,
    }
    safe_result = json_safe(result)
    (output_dir / "evidence.json").write_text(
        json.dumps(safe_result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    (output_dir / "report.md").write_text(render_report(safe_result), encoding="utf-8")
    print(
        json.dumps(
            {"verdict": verdict, "markets_passing": markets_passing}, sort_keys=True
        )
    )


if __name__ == "__main__":
    main()
