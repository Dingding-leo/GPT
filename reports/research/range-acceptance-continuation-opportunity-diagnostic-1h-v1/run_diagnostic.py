from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

BASE_URL = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision/data"
FAMILY_ID = "range-acceptance-continuation-opportunity-diagnostic-1h-v1"
MONTHS = ("2024-12",) + tuple(f"2025-{month:02d}" for month in range(1, 13))
SOURCE_START = pd.Timestamp("2024-12-01T00:00:00Z")
SOURCE_END_EXCLUSIVE = pd.Timestamp("2026-01-01T00:00:00Z")
SCORE_START = pd.Timestamp("2025-02-01T00:00:00Z")
SCORE_END = pd.Timestamp("2025-12-30T00:00:00Z")
FEE_ONE_WAY = 0.0005
RESAMPLES = 5_000
BLOCK = 7
SEED = 20_260_801
USER_AGENT = "gpt-quant-lab/range-acceptance-continuation"
MARKETS = ("BTCUSDT", "ETHUSDT")


@dataclass(frozen=True)
class ObjectSpec:
    market: str
    period: str
    url: str
    checksum_url: str


@dataclass(frozen=True)
class VerifiedMeta:
    market: str
    period: str
    url: str
    checksum_url: str
    sha256: str
    byte_count: int


@dataclass(frozen=True)
class FailedObject:
    market: str
    period: str
    url: str
    checksum_url: str
    error: str


@dataclass(frozen=True)
class Downloaded:
    meta: VerifiedMeta
    payload: bytes


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=12)
    return parser.parse_args()


def build_specs() -> list[ObjectSpec]:
    specs: list[ObjectSpec] = []
    for market in MARKETS:
        for month in MONTHS:
            name = f"{market}-1h-{month}.zip"
            url = f"{BASE_URL}/spot/monthly/klines/{market}/1h/{name}"
            specs.append(
                ObjectSpec(
                    market=market,
                    period=month,
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
                    raise RuntimeError(f"unexpected HTTP status {response.status}")
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise RuntimeError(f"HTTP 404 Not Found: {url}") from exc
            last_error = exc
        except (urllib.error.URLError, TimeoutError, OSError, RuntimeError) as exc:
            last_error = exc
        if attempt + 1 < attempts:
            time.sleep(float(2**attempt))
    raise RuntimeError(f"download failed after {attempts} attempts: {url}: {last_error}")


def parse_checksum(payload: bytes, url: str) -> str:
    fields = payload.decode("utf-8", errors="strict").strip().split()
    if not fields or len(fields[0]) != 64:
        raise RuntimeError(f"invalid checksum response: {url}")
    digest = fields[0].lower()
    if any(character not in "0123456789abcdef" for character in digest):
        raise RuntimeError(f"non-hex checksum response: {url}")
    return digest


def download(spec: ObjectSpec) -> Downloaded:
    expected = parse_checksum(http_get(spec.checksum_url), spec.checksum_url)
    payload = http_get(spec.url)
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected:
        raise RuntimeError(f"checksum mismatch: expected {expected}, observed {actual}")
    return Downloaded(
        meta=VerifiedMeta(
            market=spec.market,
            period=spec.period,
            url=spec.url,
            checksum_url=spec.checksum_url,
            sha256=actual,
            byte_count=len(payload),
        ),
        payload=payload,
    )


def download_all(
    specs: list[ObjectSpec], workers: int
) -> tuple[list[Downloaded], list[FailedObject]]:
    downloaded: list[Downloaded] = []
    failed: list[FailedObject] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {executor.submit(download, spec): spec for spec in specs}
        for future in as_completed(futures):
            spec = futures[future]
            try:
                downloaded.append(future.result())
            except Exception as exc:  # noqa: BLE001
                failed.append(
                    FailedObject(
                        market=spec.market,
                        period=spec.period,
                        url=spec.url,
                        checksum_url=spec.checksum_url,
                        error=str(exc),
                    )
                )
    downloaded.sort(key=lambda item: (item.meta.market, item.meta.period))
    failed.sort(key=lambda item: (item.market, item.period))
    return downloaded, failed


def month_bounds(period: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    start = pd.Timestamp(f"{period}-01T00:00:00Z")
    return start, start + pd.offsets.MonthBegin(1)


def parse_kline(downloaded: Downloaded) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(downloaded.payload)) as archive:
        members = [name for name in archive.namelist() if not name.endswith("/")]
        if len(members) != 1 or not members[0].lower().endswith(".csv"):
            raise ValueError(f"unexpected archive members for {downloaded.meta.url}: {members}")
        text = archive.read(members[0]).decode("utf-8", errors="strict")
    rows: list[tuple[int, float, float, float, float, float]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        fields = line.split(",")
        if line_number == 1 and fields[0].strip().lower() in {"open_time", "open time"}:
            continue
        if len(fields) != 12:
            raise ValueError(
                f"unexpected kline width {len(fields)} at {downloaded.meta.url}:{line_number}"
            )
        try:
            open_time = int(fields[0])
            open_price, high, low, close, volume = (float(fields[index]) for index in range(1, 6))
        except ValueError as exc:
            raise ValueError(f"non-numeric kline at {downloaded.meta.url}:{line_number}") from exc
        prices = (open_price, high, low, close)
        if not all(math.isfinite(value) and value > 0 for value in prices):
            raise ValueError(f"invalid OHLC at {downloaded.meta.url}:{line_number}")
        if not math.isfinite(volume) or volume < 0:
            raise ValueError(f"invalid volume at {downloaded.meta.url}:{line_number}")
        if high < max(open_price, close) or low > min(open_price, close) or high < low:
            raise ValueError(f"inconsistent OHLC at {downloaded.meta.url}:{line_number}")
        rows.append((open_time, open_price, high, low, close, volume))
    frame = pd.DataFrame(rows, columns=["open_time", "open", "high", "low", "close", "volume"])
    if frame.empty:
        raise ValueError(f"empty kline archive: {downloaded.meta.url}")
    if frame["open_time"].max() >= 10**15:
        timestamps = pd.to_datetime(frame["open_time"], unit="us", utc=True)
    else:
        timestamps = pd.to_datetime(frame["open_time"], unit="ms", utc=True)
    frame.insert(0, "timestamp", timestamps)
    start, end = month_bounds(downloaded.meta.period)
    if bool(((frame["timestamp"] < start) | (frame["timestamp"] >= end)).any()):
        raise ValueError(f"row outside declared month: {downloaded.meta.url}")
    return frame.drop(columns="open_time")


def build_market_frames(downloaded: list[Downloaded]) -> dict[str, pd.DataFrame]:
    grouped: dict[str, list[pd.DataFrame]] = {market: [] for market in MARKETS}
    for item in downloaded:
        grouped[item.meta.market].append(parse_kline(item))
    expected = pd.date_range(SOURCE_START, SOURCE_END_EXCLUSIVE, freq="h", inclusive="left")
    output: dict[str, pd.DataFrame] = {}
    for market, parts in grouped.items():
        if len(parts) != len(MONTHS):
            raise ValueError(f"{market} did not supply all fixed months")
        frame = pd.concat(parts, ignore_index=True).sort_values("timestamp")
        if bool(frame["timestamp"].duplicated().any()):
            raise ValueError(f"{market} has duplicate 1H timestamps")
        frame = frame.reset_index(drop=True)
        if len(frame) != len(expected) or not frame["timestamp"].equals(pd.Series(expected)):
            raise ValueError(f"{market} is not the exact contiguous fixed 1H grid")
        days = frame["timestamp"].dt.floor("D")
        if not bool((days.value_counts().sort_index() == 24).all()):
            raise ValueError(f"{market} contains an incomplete UTC day")
        output[market] = frame
    return output


def build_daily(frame: pd.DataFrame) -> pd.DataFrame:
    table = frame.copy()
    table["day"] = table["timestamp"].dt.floor("D")
    daily = (
        table.groupby("day", sort=True)
        .agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
            hourly_rows=("open", "size"),
        )
        .reset_index()
    )
    if not bool((daily["hourly_rows"] == 24).all()):
        raise ValueError("daily aggregation contains incomplete UTC days")
    daily["previous_close"] = daily["close"].shift(1)
    daily["true_high"] = np.maximum(daily["high"], daily["previous_close"])
    daily["true_low"] = np.minimum(daily["low"], daily["previous_close"])
    daily["true_range"] = daily["true_high"] - daily["true_low"]
    daily["acceptance"] = 2.0 * (daily["close"] - daily["true_low"]) / daily["true_range"] - 1.0
    daily["raw_expansion"] = np.nan
    for index in range(30, len(daily)):
        prior = daily.iloc[index - 30 : index]
        median_range = float(prior["true_range"].median())
        median_volume = float(prior["volume"].median())
        current_range = float(daily.at[index, "true_range"])
        current_volume = float(daily.at[index, "volume"])
        previous_close = float(daily.at[index, "previous_close"])
        close = float(daily.at[index, "close"])
        valid = bool(
            math.isfinite(median_range)
            and median_range > 0
            and math.isfinite(median_volume)
            and median_volume > 0
            and math.isfinite(current_range)
            and current_range > 0
            and math.isfinite(current_volume)
            and current_volume > 0
            and math.isfinite(previous_close)
            and previous_close > 0
            and math.isfinite(close)
            and close > 0
        )
        if not valid:
            continue
        direction = float(np.sign(math.log(close / previous_close)))
        range_ratio = current_range / median_range
        volume_ratio = current_volume / median_volume
        daily.at[index, "raw_expansion"] = direction * math.log(
            range_ratio / math.sqrt(volume_ratio)
        )
    daily["expansion_z"] = np.nan
    daily["state"] = np.nan
    for index in range(60, len(daily)):
        prior_raw = daily.iloc[index - 30 : index]["raw_expansion"].to_numpy(float)
        current_raw = float(daily.at[index, "raw_expansion"])
        acceptance = float(daily.at[index, "acceptance"])
        if not bool(np.isfinite(prior_raw).all()) or not math.isfinite(current_raw):
            continue
        center = float(np.median(prior_raw))
        scale = float(1.4826 * np.median(np.abs(prior_raw - center)))
        if not math.isfinite(scale) or scale <= 0 or not math.isfinite(acceptance):
            continue
        expansion_z = (current_raw - center) / scale
        daily.at[index, "expansion_z"] = expansion_z
        daily.at[index, "state"] = acceptance + expansion_z
    return daily


def build_labels(frame: pd.DataFrame) -> pd.DataFrame:
    daily = build_daily(frame)
    daily_by_day = daily.set_index("day")
    locations = {timestamp: index for index, timestamp in enumerate(frame["timestamp"])}
    opens = frame["open"].to_numpy(float)
    score_days = pd.date_range(SCORE_START, SCORE_END, freq="D")
    rows: list[dict[str, Any]] = []
    for target_day in score_days:
        feature_day = target_day - pd.Timedelta(days=1)
        terminal_day = target_day + pd.Timedelta(days=1)
        if feature_day not in daily_by_day.index:
            raise ValueError(f"missing feature day {feature_day}")
        if target_day not in locations or terminal_day not in locations:
            raise ValueError(f"missing target opens for {target_day}")
        entry = locations[target_day]
        terminal = locations[terminal_day]
        if terminal != entry + 24:
            raise ValueError(f"broken 24H target adjacency at {target_day}")
        feature = daily_by_day.loc[feature_day]
        state = float(feature["state"])
        acceptance = float(feature["acceptance"])
        expansion_z = float(feature["expansion_z"])
        raw_expansion = float(feature["raw_expansion"])
        valid = bool(
            math.isfinite(state)
            and math.isfinite(acceptance)
            and math.isfinite(expansion_z)
            and math.isfinite(raw_expansion)
        )
        path = opens[entry : terminal + 1] / opens[entry] - 1.0
        if len(path) != 25 or not bool(np.isfinite(path).all()):
            raise ValueError(f"invalid target path at {target_day}")
        gross = float(path[-1])
        rows.append(
            {
                "decision_day": target_day,
                "feature_day": feature_day,
                "state": state,
                "acceptance": acceptance,
                "expansion_z": expansion_z,
                "raw_expansion": raw_expansion,
                "gross": gross,
                "net": gross - 2 * FEE_ONE_WAY,
                "adverse": float(path.min()),
                "valid": valid,
            }
        )
    table = pd.DataFrame(rows)
    if len(table) != 333:
        raise ValueError(f"expected 333 decisions, observed {len(table)}")
    return table


def average_ranks(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    sorted_values = values[order]
    ranks = np.empty(len(values), dtype=float)
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and sorted_values[end] == sorted_values[start]:
            end += 1
        ranks[order[start:end]] = (start + 1 + end) / 2.0
        start = end
    return ranks


def correlation(left: np.ndarray, right: np.ndarray) -> float | None:
    if len(left) < 3 or np.std(left) == 0 or np.std(right) == 0:
        return None
    return float(np.corrcoef(left, right)[0, 1])


def spearman(left: np.ndarray, right: np.ndarray) -> float | None:
    return correlation(average_ranks(left), average_ranks(right))


def standardized_slope(state: np.ndarray, target: np.ndarray) -> float | None:
    if len(state) < 3:
        return None
    standard_deviation = float(np.std(state, ddof=1))
    if not math.isfinite(standard_deviation) or standard_deviation <= 0:
        return None
    standardized = (state - float(np.mean(state))) / standard_deviation
    denominator = float(np.dot(standardized, standardized))
    if denominator <= 0:
        return None
    centered_target = target - float(np.mean(target))
    return float(np.dot(standardized, centered_target) / denominator)


def segment_slope(part: pd.DataFrame, target: str) -> float | None:
    valid = part[part["valid"]]
    if len(valid) < 10:
        return None
    return standardized_slope(valid["state"].to_numpy(float), valid[target].to_numpy(float))


def temporal_breadth(table: pd.DataFrame) -> dict[str, Any]:
    folds: list[dict[str, Any]] = []
    for number in range(11):
        part = table.iloc[number * 30 : (number + 1) * 30]
        folds.append(
            {
                "fold": number + 1,
                "start": part["decision_day"].iloc[0].isoformat(),
                "end": part["decision_day"].iloc[-1].isoformat(),
                "gross_slope": segment_slope(part, "gross"),
                "adverse_slope": segment_slope(part, "adverse"),
            }
        )
    remainder = table.iloc[330:]
    month_key = table["decision_day"].dt.to_period("M")
    months: list[dict[str, Any]] = []
    for period in sorted(month_key.unique()):
        part = table[month_key == period]
        months.append(
            {
                "month": str(period),
                "observations": len(part),
                "gross_slope": segment_slope(part, "gross"),
                "adverse_slope": segment_slope(part, "adverse"),
            }
        )
    return {
        "folds": folds,
        "positive_gross_folds": sum(
            row["gross_slope"] is not None and row["gross_slope"] > 0 for row in folds
        ),
        "positive_adverse_folds": sum(
            row["adverse_slope"] is not None and row["adverse_slope"] > 0 for row in folds
        ),
        "remainder": {
            "observations": len(remainder),
            "start": remainder["decision_day"].iloc[0].isoformat(),
            "end": remainder["decision_day"].iloc[-1].isoformat(),
        },
        "months": months,
        "positive_gross_months": sum(
            row["gross_slope"] is not None and row["gross_slope"] > 0 for row in months
        ),
        "positive_adverse_months": sum(
            row["adverse_slope"] is not None and row["adverse_slope"] > 0 for row in months
        ),
    }


def quintile_statistics(valid: pd.DataFrame) -> dict[str, Any]:
    ordered = valid.sort_values(["state", "decision_day"], kind="mergesort").reset_index(drop=True)
    groups = np.minimum((np.arange(len(ordered)) * 5) // len(ordered), 4)
    ordered["bucket"] = groups + 1
    buckets: list[dict[str, Any]] = []
    for number in range(1, 6):
        part = ordered[ordered["bucket"] == number]
        buckets.append(
            {
                "bucket": number,
                "observations": len(part),
                "state_min": float(part["state"].min()),
                "state_max": float(part["state"].max()),
                "mean_gross": float(part["gross"].mean()),
                "mean_net": float(part["net"].mean()),
                "mean_adverse": float(part["adverse"].mean()),
            }
        )
    gross_means = np.array([row["mean_gross"] for row in buckets], dtype=float)
    adverse_means = np.array([row["mean_adverse"] for row in buckets], dtype=float)
    index = np.arange(1, 6, dtype=float)
    return {
        "buckets": buckets,
        "positive_adjacent_gross": int(np.sum(np.diff(gross_means) > 0)),
        "positive_adjacent_adverse": int(np.sum(np.diff(adverse_means) > 0)),
        "gross_index_rho": spearman(index, gross_means),
        "adverse_index_rho": spearman(index, adverse_means),
    }


def point_statistics(table: pd.DataFrame) -> dict[str, Any]:
    valid = table[table["valid"]].copy()
    state = valid["state"].to_numpy(float)
    gross = valid["gross"].to_numpy(float)
    adverse = valid["adverse"].to_numpy(float)
    median = float(np.median(state))
    low = valid[valid["state"] <= median]
    high = valid[valid["state"] > median]
    quantiles = np.quantile(state, [0.0, 0.25, 0.5, 0.75, 1.0])
    absolute = np.abs(gross)
    return {
        "intended_decisions": len(table),
        "valid_decisions": len(valid),
        "state_quantiles": {
            "minimum": float(quantiles[0]),
            "q25": float(quantiles[1]),
            "median": float(quantiles[2]),
            "q75": float(quantiles[3]),
            "maximum": float(quantiles[4]),
            "iqr": float(quantiles[3] - quantiles[1]),
        },
        "median_partitions": {"low": len(low), "high": len(high)},
        "gross_rho": spearman(state, gross),
        "adverse_rho": spearman(state, adverse),
        "gross_slope_per_state_sd": standardized_slope(state, gross),
        "adverse_slope_per_state_sd": standardized_slope(state, adverse),
        "high_minus_low": {
            "gross": float(high["gross"].mean() - low["gross"].mean()),
            "net": float(high["net"].mean() - low["net"].mean()),
            "adverse": float(high["adverse"].mean() - low["adverse"].mean()),
        },
        "quintiles": quintile_statistics(valid),
        "component_correlations": {
            "acceptance_gross": spearman(valid["acceptance"].to_numpy(float), gross),
            "acceptance_adverse": spearman(valid["acceptance"].to_numpy(float), adverse),
            "expansion_z_gross": spearman(valid["expansion_z"].to_numpy(float), gross),
            "expansion_z_adverse": spearman(valid["expansion_z"].to_numpy(float), adverse),
            "acceptance_expansion_z": spearman(
                valid["acceptance"].to_numpy(float), valid["expansion_z"].to_numpy(float)
            ),
        },
        "target_economics": {
            "mean_gross": float(valid["gross"].mean()),
            "median_gross": float(valid["gross"].median()),
            "mean_net": float(valid["net"].mean()),
            "median_net": float(valid["net"].median()),
            "mean_adverse": float(valid["adverse"].mean()),
            "gross_positive_days": int((valid["gross"] > 0).sum()),
            "net_positive_days": int((valid["net"] > 0).sum()),
            "turnover": int(2 * len(valid)),
            "embedded_fees": float(2 * FEE_ONE_WAY * len(valid)),
            "max_absolute_gross_share": float(absolute.max() / absolute.sum()),
        },
        "temporal": temporal_breadth(table),
    }


def bootstrap_indices(length: int) -> np.ndarray:
    rng = np.random.default_rng(SEED)
    starts = np.arange(length - BLOCK + 1)
    blocks_needed = math.ceil(length / BLOCK)
    chosen = rng.choice(starts, size=(RESAMPLES, blocks_needed), replace=True)
    offsets = np.arange(BLOCK)
    return (chosen[:, :, None] + offsets[None, None, :]).reshape(RESAMPLES, -1)[:, :length]


def bootstrap(table: pd.DataFrame, indices: np.ndarray) -> dict[str, Any]:
    state = table["state"].to_numpy(float)
    gross = table["gross"].to_numpy(float)
    adverse = table["adverse"].to_numpy(float)
    valid_source = table["valid"].to_numpy(bool)
    draws = np.full((RESAMPLES, 4), np.nan)
    for number, sampled in enumerate(indices):
        mask = valid_source[sampled]
        sampled_state = state[sampled][mask]
        if len(sampled_state) < 250 or np.std(sampled_state) == 0:
            continue
        sampled_gross = gross[sampled][mask]
        sampled_adverse = adverse[sampled][mask]
        if np.std(sampled_gross) == 0 or np.std(sampled_adverse) == 0:
            continue
        values = (
            spearman(sampled_state, sampled_gross),
            spearman(sampled_state, sampled_adverse),
            standardized_slope(sampled_state, sampled_gross),
            standardized_slope(sampled_state, sampled_adverse),
        )
        if all(value is not None and math.isfinite(value) for value in values):
            draws[number] = values
    valid = np.isfinite(draws).all(axis=1)
    valid_draws = draws[valid]
    if len(valid_draws) == 0:
        raise ValueError("no valid moving-block bootstrap draws")

    def interval(column: int) -> list[float]:
        return np.quantile(valid_draws[:, column], [0.025, 0.975]).tolist()

    return {
        "resamples": RESAMPLES,
        "block_days": BLOCK,
        "seed": SEED,
        "valid_draws": int(valid.sum()),
        "valid_fraction": float(valid.mean()),
        "gross_rho_ci95": interval(0),
        "adverse_rho_ci95": interval(1),
        "gross_slope_ci95": interval(2),
        "adverse_slope_ci95": interval(3),
        "draws": draws,
        "valid_mask": valid,
    }


def common_inference(bootstraps: dict[str, dict[str, Any]]) -> dict[str, Any]:
    market_names = sorted(bootstraps)
    common = np.logical_and.reduce([bootstraps[name]["valid_mask"] for name in market_names])
    if not bool(common.any()):
        raise ValueError("no common valid bootstrap draws")
    stacked = np.stack([bootstraps[name]["draws"][common] for name in market_names], axis=0)
    medians = np.median(stacked, axis=0)
    return {
        "valid_draws": int(common.sum()),
        "valid_fraction": float(common.mean()),
        "gross_rho_ci95": np.quantile(medians[:, 0], [0.025, 0.975]).tolist(),
        "adverse_rho_ci95": np.quantile(medians[:, 1], [0.025, 0.975]).tolist(),
        "gross_slope_ci95": np.quantile(medians[:, 2], [0.025, 0.975]).tolist(),
        "adverse_slope_ci95": np.quantile(medians[:, 3], [0.025, 0.975]).tolist(),
    }


def strip_bootstrap_arrays(result: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in result.items() if key not in {"draws", "valid_mask"}}


def evaluate_gates(result: dict[str, Any], common: dict[str, Any]) -> dict[str, bool]:
    temporal = result["temporal"]
    uncertainty = result["uncertainty"]
    partitions = result["median_partitions"]
    delta = result["high_minus_low"]
    quintiles = result["quintiles"]
    return {
        "gross_information": bool(
            result["gross_rho"] is not None
            and result["gross_rho"] > 0
            and uncertainty["gross_rho_ci95"][0] > 0
        ),
        "adverse_information": bool(
            result["adverse_rho"] is not None
            and result["adverse_rho"] > 0
            and uncertainty["adverse_rho_ci95"][0] > 0
        ),
        "positive_slope_information": bool(
            result["gross_slope_per_state_sd"] is not None
            and result["gross_slope_per_state_sd"] > 0
            and uncertainty["gross_slope_ci95"][0] > 0
            and result["adverse_slope_per_state_sd"] is not None
            and result["adverse_slope_per_state_sd"] > 0
            and uncertainty["adverse_slope_ci95"][0] > 0
        ),
        "fold_breadth": temporal["positive_gross_folds"] >= 7
        and temporal["positive_adverse_folds"] >= 7,
        "month_breadth": temporal["positive_gross_months"] >= 7
        and temporal["positive_adverse_months"] >= 7,
        "state_support": result["state_quantiles"]["iqr"] >= 1.0,
        "partition_support": partitions["low"] >= 150 and partitions["high"] >= 150,
        "economic_ordering": delta["gross"] > 0 and delta["adverse"] > 0,
        "quintile_monotonicity": bool(
            quintiles["positive_adjacent_gross"] >= 3
            and quintiles["positive_adjacent_adverse"] >= 3
            and quintiles["gross_index_rho"] is not None
            and quintiles["gross_index_rho"] >= 0.8
            and quintiles["adverse_index_rho"] is not None
            and quintiles["adverse_index_rho"] >= 0.8
        ),
        "valid_bootstrap": uncertainty["valid_fraction"] >= 0.95,
        "common_lower_bounds": common["gross_rho_ci95"][0] > 0
        and common["adverse_rho_ci95"][0] > 0
        and common["gross_slope_ci95"][0] > 0
        and common["adverse_slope_ci95"][0] > 0,
    }


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(json_safe(payload), indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def render_report(evidence: dict[str, Any]) -> str:
    lines = [
        "# Range-acceptance continuation diagnostic",
        "",
        "```text",
        f"family          {FAMILY_ID}",
        "candidate count 0",
        "diagnostic      1",
        "parameter grid  0",
        f"performance     {str(evidence['performance_seen']).lower()}",
        f"markets passing {evidence['markets_passing']}/2",
        f"verdict         {evidence['verdict']}",
        "```",
        "",
        "## Source contract",
        "",
        f"Requested archive/checksum pairs: {evidence['source']['requested_object_count']}.",
        f"Verified pairs: {evidence['source']['successful_object_count']}.",
        f"Failed pairs: {evidence['source']['failed_object_count']}.",
        "",
    ]
    if evidence["source"]["failures"]:
        lines.extend(["## Source failures", ""])
        for failure in evidence["source"]["failures"]:
            lines.append(f"- `{failure['market']} {failure['period']}`: {failure['error']}")
        lines.extend(
            [
                "",
                "The fixed source contract failed before feature construction or performance "
                "inspection. No metric or alpha claim exists.",
            ]
        )
        return "\n".join(lines) + "\n"
    lines.extend(
        [
            "## Information results",
            "",
            "| Market | Valid | Gross rho (95% CI) | Adverse rho (95% CI) | "
            "Gross/adverse folds | Gross/adverse months | IQR | High-low gross | "
            "High-low adverse |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for market, result in evidence["markets"].items():
        lines.append(
            f"| {market} | {result['valid_decisions']} | "
            f"{result['gross_rho']:+.4f} "
            f"[{result['uncertainty']['gross_rho_ci95'][0]:+.4f},"
            f"{result['uncertainty']['gross_rho_ci95'][1]:+.4f}] | "
            f"{result['adverse_rho']:+.4f} "
            f"[{result['uncertainty']['adverse_rho_ci95'][0]:+.4f},"
            f"{result['uncertainty']['adverse_rho_ci95'][1]:+.4f}] | "
            f"{result['temporal']['positive_gross_folds']}/11 / "
            f"{result['temporal']['positive_adverse_folds']}/11 | "
            f"{result['temporal']['positive_gross_months']}/11 / "
            f"{result['temporal']['positive_adverse_months']}/11 | "
            f"{result['state_quantiles']['iqr']:.4f} | "
            f"{result['high_minus_low']['gross']:+.4%} | "
            f"{result['high_minus_low']['adverse']:+.4%} |"
        )
    lines.extend(
        [
            "",
            "## Quintile monotonicity",
            "",
            "| Market | Gross adjacent | Adverse adjacent | Gross bucket rho | "
            "Adverse bucket rho |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for market, result in evidence["markets"].items():
        quintiles = result["quintiles"]
        lines.append(
            f"| {market} | {quintiles['positive_adjacent_gross']}/4 | "
            f"{quintiles['positive_adjacent_adverse']}/4 | "
            f"{quintiles['gross_index_rho']:+.4f} | "
            f"{quintiles['adverse_index_rho']:+.4f} |"
        )
        gross_sequence = ", ".join(f"{row['mean_gross']:+.4%}" for row in quintiles["buckets"])
        adverse_sequence = ", ".join(f"{row['mean_adverse']:+.4%}" for row in quintiles["buckets"])
        lines.append(f"\n{market} gross bucket means: `{gross_sequence}`.")
        lines.append(f"{market} adverse bucket means: `{adverse_sequence}`.")
    lines.extend(
        [
            "",
            "## Target-label economics",
            "",
            "These are independent next-day labels, not an executable strategy path.",
            "",
            "| Market | Mean gross | Mean net | Mean adverse | Positive gross | Turnover | Fees |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for market, result in evidence["markets"].items():
        economics = result["target_economics"]
        lines.append(
            f"| {market} | {economics['mean_gross']:+.4%} | "
            f"{economics['mean_net']:+.4%} | {economics['mean_adverse']:+.4%} | "
            f"{economics['gross_positive_days']}/{result['valid_decisions']} | "
            f"{economics['turnover']} | {economics['embedded_fees']:.2%} |"
        )
    common = evidence["common_inference"]
    lines.extend(
        [
            "",
            "## Common-index uncertainty",
            "",
            "```text",
            f"gross rho 95% CI       [{common['gross_rho_ci95'][0]:+.4f}, "
            f"{common['gross_rho_ci95'][1]:+.4f}]",
            f"adverse rho 95% CI     [{common['adverse_rho_ci95'][0]:+.4f}, "
            f"{common['adverse_rho_ci95'][1]:+.4f}]",
            f"gross slope 95% CI     [{common['gross_slope_ci95'][0]:+.4%}, "
            f"{common['gross_slope_ci95'][1]:+.4%}]",
            f"adverse slope 95% CI   [{common['adverse_slope_ci95'][0]:+.4%}, "
            f"{common['adverse_slope_ci95'][1]:+.4%}]",
            f"valid draws              {common['valid_draws']}/{RESAMPLES}",
            "```",
            "",
            "Candidate count is zero, so executable train/OOS/full return, Sharpe, maximum "
            "drawdown, benchmark comparison, strategy turnover and edge per turnover are not "
            "computed. Exactly 5 bps one way is embedded only in each independent target label.",
        ]
    )
    return "\n".join(lines) + "\n"


def abort_evidence(
    specs: list[ObjectSpec], downloaded: list[Downloaded], failed: list[FailedObject]
) -> dict[str, Any]:
    return {
        "family_id": FAMILY_ID,
        "classification": "training-only own-OHLCV information eligibility diagnostic",
        "candidate_count": 0,
        "diagnostic_count": 1,
        "parameter_grid_count": 0,
        "fee_one_way": FEE_ONE_WAY,
        "accepted": False,
        "performance_seen": False,
        "later_data_accessed": False,
        "markets_passing": 0,
        "verdict": "abort_fixed_source_contract_missing_or_invalid_public_objects",
        "source": {
            "base_url": BASE_URL,
            "source_start": SOURCE_START.isoformat(),
            "source_end_exclusive": SOURCE_END_EXCLUSIVE.isoformat(),
            "requested_object_count": len(specs),
            "successful_object_count": len(downloaded),
            "checksum_matches": len(downloaded),
            "failed_object_count": len(failed),
            "failures": [asdict(item) for item in failed],
        },
        "sample": {"intended_decisions_per_market": 333, "completed_decisions": 0},
        "markets": {},
    }


def main() -> None:
    args = parse_args()
    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    specs = build_specs()
    downloaded, failed = download_all(specs, args.workers)
    manifest = [asdict(item.meta) for item in downloaded]
    if not failed:
        try:
            frames = build_market_frames(downloaded)
        except Exception as exc:  # noqa: BLE001
            failed = [
                FailedObject(
                    market="ALL",
                    period="2024-12..2025-12",
                    url="verified archives",
                    checksum_url="verified companion checksums",
                    error=str(exc),
                )
            ]
    if failed:
        evidence = abort_evidence(specs, downloaded, failed)
    else:
        tables = {market: build_labels(frame) for market, frame in frames.items()}
        indices = bootstrap_indices(333)
        bootstrap_results = {market: bootstrap(table, indices) for market, table in tables.items()}
        common = common_inference(bootstrap_results)
        markets: dict[str, Any] = {}
        for market, table in tables.items():
            result = point_statistics(table)
            result["uncertainty"] = strip_bootstrap_arrays(bootstrap_results[market])
            result["gates"] = evaluate_gates(result, common)
            result["passed"] = all(result["gates"].values())
            markets[market] = result
        markets_passing = sum(result["passed"] for result in markets.values())
        accepted = markets_passing == len(MARKETS)
        verdict = (
            "support_range_acceptance_continuation_information_premise"
            if accepted
            else "reject_range_acceptance_continuation_information_premise"
        )
        evidence = {
            "family_id": FAMILY_ID,
            "classification": "training-only own-OHLCV information eligibility diagnostic",
            "candidate_count": 0,
            "diagnostic_count": 1,
            "parameter_grid_count": 0,
            "fee_one_way": FEE_ONE_WAY,
            "accepted": accepted,
            "performance_seen": True,
            "later_data_accessed": False,
            "markets_passing": markets_passing,
            "verdict": verdict,
            "source": {
                "base_url": BASE_URL,
                "source_start": SOURCE_START.isoformat(),
                "source_end_exclusive": SOURCE_END_EXCLUSIVE.isoformat(),
                "requested_object_count": len(specs),
                "successful_object_count": len(downloaded),
                "checksum_matches": len(downloaded),
                "failed_object_count": 0,
                "failures": [],
            },
            "sample": {
                "score_start": SCORE_START.isoformat(),
                "score_end": SCORE_END.isoformat(),
                "intended_decisions_per_market": 333,
                "completed_decisions": int(
                    sum(item["valid_decisions"] for item in markets.values())
                ),
            },
            "markets": markets,
            "common_inference": common,
        }
        for market, table in tables.items():
            table_to_write = table.copy()
            table_to_write["decision_day"] = table_to_write["decision_day"].map(
                pd.Timestamp.isoformat
            )
            table_to_write["feature_day"] = table_to_write["feature_day"].map(
                pd.Timestamp.isoformat
            )
            table_to_write.to_csv(output_dir / f"{market}-labels.csv", index=False)
    write_json(output_dir / "source-manifest.json", manifest)
    write_json(output_dir / "evidence.json", evidence)
    (output_dir / "report.md").write_text(render_report(evidence), encoding="utf-8")
    digest = hashlib.sha256((output_dir / "evidence.json").read_bytes()).hexdigest()
    (output_dir / "evidence.sha256").write_text(f"{digest}  evidence.json\n", encoding="utf-8")
    print(json.dumps({"verdict": evidence["verdict"], "evidence_sha256": digest}, sort_keys=True))


if __name__ == "__main__":
    main()
