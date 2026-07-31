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
FAMILY_ID = "coinm-basis-compression-resilience-opportunity-diagnostic-1h-v1"
MONTHS = tuple(f"2024-{month:02d}" for month in range(1, 10))
SOURCE_START = pd.Timestamp("2024-01-01T00:00:00Z")
SOURCE_END_EXCLUSIVE = pd.Timestamp("2024-10-01T00:00:00Z")
SCORE_START = pd.Timestamp("2024-02-01T00:00:00Z")
SCORE_END = pd.Timestamp("2024-09-29T00:00:00Z")
FEE_ONE_WAY = 0.0005
RESAMPLES = 5_000
BLOCK = 7
SEED = 20_260_801
USER_AGENT = "gpt-quant-lab/coinm-basis-compression"
MARKETS = {"BTCUSDT": "BTCUSD_PERP", "ETHUSDT": "ETHUSD_PERP"}


@dataclass(frozen=True)
class ObjectSpec:
    market: str
    instrument: str
    kind: str
    period: str
    url: str
    checksum_url: str


@dataclass(frozen=True)
class VerifiedMeta:
    market: str
    instrument: str
    kind: str
    period: str
    url: str
    checksum_url: str
    sha256: str
    byte_count: int


@dataclass(frozen=True)
class FailedObject:
    market: str
    instrument: str
    kind: str
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
    for spot, coinm in MARKETS.items():
        for month in MONTHS:
            spot_name = f"{spot}-1h-{month}.zip"
            spot_url = f"{BASE_URL}/spot/monthly/klines/{spot}/1h/{spot_name}"
            specs.append(
                ObjectSpec(
                    market=spot,
                    instrument=spot,
                    kind="spot_1h_kline",
                    period=month,
                    url=spot_url,
                    checksum_url=f"{spot_url}.CHECKSUM",
                )
            )
            coinm_name = f"{coinm}-1h-{month}.zip"
            coinm_url = f"{BASE_URL}/futures/cm/monthly/klines/{coinm}/1h/{coinm_name}"
            specs.append(
                ObjectSpec(
                    market=spot,
                    instrument=coinm,
                    kind="coinm_perpetual_1h_kline",
                    period=month,
                    url=coinm_url,
                    checksum_url=f"{coinm_url}.CHECKSUM",
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
            instrument=spec.instrument,
            kind=spec.kind,
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
                        instrument=spec.instrument,
                        kind=spec.kind,
                        period=spec.period,
                        url=spec.url,
                        checksum_url=spec.checksum_url,
                        error=str(exc),
                    )
                )
    downloaded.sort(key=lambda item: (item.meta.market, item.meta.kind, item.meta.period))
    failed.sort(key=lambda item: (item.market, item.kind, item.period))
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
    rows: list[tuple[int, float, float, float, float]] = []
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
            values = tuple(float(fields[index]) for index in range(1, 5))
        except ValueError as exc:
            raise ValueError(f"non-numeric kline at {downloaded.meta.url}:{line_number}") from exc
        open_price, high, low, close = values
        if not all(math.isfinite(value) and value > 0 for value in values):
            raise ValueError(f"invalid OHLC at {downloaded.meta.url}:{line_number}")
        if high < max(open_price, close) or low > min(open_price, close) or high < low:
            raise ValueError(f"inconsistent OHLC at {downloaded.meta.url}:{line_number}")
        rows.append((open_time, open_price, high, low, close))
    frame = pd.DataFrame(rows, columns=["open_time", "open", "high", "low", "close"])
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


def build_market_frames(downloaded: list[Downloaded]) -> dict[str, dict[str, pd.DataFrame]]:
    grouped: dict[str, dict[str, list[pd.DataFrame]]] = {
        market: {"spot_1h_kline": [], "coinm_perpetual_1h_kline": []} for market in MARKETS
    }
    for item in downloaded:
        grouped[item.meta.market][item.meta.kind].append(parse_kline(item))
    expected = pd.date_range(SOURCE_START, SOURCE_END_EXCLUSIVE, freq="h", inclusive="left")
    output: dict[str, dict[str, pd.DataFrame]] = {}
    for market, kinds in grouped.items():
        output[market] = {}
        for kind, parts in kinds.items():
            if len(parts) != len(MONTHS):
                raise ValueError(f"{market} {kind} did not supply all fixed months")
            frame = pd.concat(parts, ignore_index=True).sort_values("timestamp")
            if bool(frame["timestamp"].duplicated().any()):
                raise ValueError(f"{market} {kind} has duplicate 1H timestamps")
            frame = frame.reset_index(drop=True)
            if len(frame) != len(expected) or not frame["timestamp"].equals(pd.Series(expected)):
                raise ValueError(f"{market} {kind} is not the exact contiguous fixed 1H grid")
            days = frame["timestamp"].dt.floor("D")
            if not bool((days.value_counts().sort_index() == 24).all()):
                raise ValueError(f"{market} {kind} contains an incomplete UTC day")
            output[market][kind] = frame
        if not output[market]["spot_1h_kline"]["timestamp"].equals(
            output[market]["coinm_perpetual_1h_kline"]["timestamp"]
        ):
            raise ValueError(f"{market} spot/perpetual timestamp mismatch")
    return output


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


def daily_compressions(spot: pd.DataFrame, coinm: pd.DataFrame) -> pd.Series:
    basis = np.log(coinm["close"].to_numpy(float) / spot["close"].to_numpy(float))
    table = pd.DataFrame({"day": spot["timestamp"].dt.floor("D"), "basis": basis})
    return table.groupby("day", sort=True)["basis"].agg(
        lambda values: -(values.iloc[-1] - values.iloc[0])
    )


def build_labels(spot: pd.DataFrame, coinm: pd.DataFrame) -> pd.DataFrame:
    opens = spot["open"].to_numpy(float)
    closes = spot["close"].to_numpy(float)
    timestamps = spot["timestamp"]
    day_index = timestamps.dt.floor("D")
    compression = daily_compressions(spot, coinm)
    close_returns = np.r_[np.nan, np.diff(np.log(closes))]
    locations = {timestamp: index for index, timestamp in enumerate(timestamps)}
    score_days = pd.date_range(SCORE_START, SCORE_END, freq="D")
    rows: list[dict[str, Any]] = []
    for decision_day in score_days:
        feature_day = decision_day - pd.Timedelta(days=1)
        prior_days = pd.date_range(feature_day - pd.Timedelta(days=30), periods=30, freq="D")
        prior = compression.reindex(prior_days).to_numpy(float)
        current_compression = float(compression.loc[feature_day])
        center = float(np.median(prior))
        scale = float(1.4826 * np.median(np.abs(prior - center)))
        feature_positions = np.flatnonzero(day_index.to_numpy() == feature_day)
        target_positions = np.flatnonzero(day_index.to_numpy() == decision_day)
        if len(feature_positions) != 24 or len(target_positions) != 24:
            raise ValueError(f"incomplete feature or target day {decision_day}")
        feature_start = int(feature_positions[0])
        feature_end = int(feature_positions[-1])
        target_start = int(target_positions[0])
        target_end = int(target_positions[-1])
        next_open_timestamp = decision_day + pd.Timedelta(days=1)
        if next_open_timestamp not in locations:
            raise ValueError(f"missing terminal target open {next_open_timestamp}")
        terminal = locations[next_open_timestamp]
        if terminal != target_end + 1 or target_start != feature_end + 1:
            raise ValueError(f"broken day adjacency at {decision_day}")
        rv_window = close_returns[feature_end - 167 : feature_end + 1]
        sigma = float(np.sqrt(np.mean(np.square(rv_window))))
        r24 = float(np.log(closes[feature_end] / opens[feature_start]))
        valid = bool(
            np.isfinite(prior).all()
            and math.isfinite(scale)
            and scale > 0
            and math.isfinite(sigma)
            and sigma > 0
        )
        basis_z = (current_compression - center) / scale if valid else math.nan
        price_z = r24 / (math.sqrt(24.0) * sigma) if valid else math.nan
        state = basis_z + price_z if valid else math.nan
        hourly = opens[target_start + 1 : terminal + 1] / opens[target_start:terminal] - 1
        if len(hourly) != 24 or not bool(np.isfinite(hourly).all()):
            raise ValueError(f"invalid target return path {decision_day}")
        gross = float(hourly.sum())
        rows.append(
            {
                "decision_day": decision_day,
                "state": state,
                "basis_z": basis_z,
                "price_z": price_z,
                "compression": current_compression,
                "gross": gross,
                "net": gross - 2 * FEE_ONE_WAY,
                "adverse": float(np.r_[0.0, np.cumsum(hourly)].min()),
                "valid": valid,
            }
        )
    table = pd.DataFrame(rows)
    if len(table) != 242:
        raise ValueError(f"expected 242 decisions, observed {len(table)}")
    return table


def segment_slope(part: pd.DataFrame, target: str) -> float | None:
    valid = part[part["valid"]]
    if len(valid) < 10:
        return None
    return standardized_slope(valid["state"].to_numpy(float), valid[target].to_numpy(float))


def temporal_breadth(table: pd.DataFrame) -> dict[str, Any]:
    folds: list[dict[str, Any]] = []
    for number in range(8):
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
    remainder = table.iloc[240:]
    months: list[dict[str, Any]] = []
    month_key = table["decision_day"].dt.to_period("M")
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
        if len(sampled_state) < 180 or np.std(sampled_state) == 0:
            continue
        sampled_gross = gross[sampled][mask]
        sampled_adverse = adverse[sampled][mask]
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
        "positive_slopes": bool(
            result["gross_slope_per_state_sd"] is not None
            and result["gross_slope_per_state_sd"] > 0
            and result["adverse_slope_per_state_sd"] is not None
            and result["adverse_slope_per_state_sd"] > 0
        ),
        "fold_breadth": temporal["positive_gross_folds"] >= 5
        and temporal["positive_adverse_folds"] >= 5,
        "month_breadth": temporal["positive_gross_months"] >= 5
        and temporal["positive_adverse_months"] >= 5,
        "state_support": result["state_quantiles"]["iqr"] >= 1.0,
        "partition_support": partitions["low"] >= 100 and partitions["high"] >= 100,
        "economic_ordering": delta["gross"] > 0 and delta["adverse"] > 0,
        "valid_bootstrap": uncertainty["valid_fraction"] >= 0.95,
        "common_lower_bounds": common["gross_rho_ci95"][0] > 0
        and common["adverse_rho_ci95"][0] > 0,
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
        "# COIN-M 1H basis-compression resilience diagnostic",
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
        f"Requested payload/checksum pairs: {evidence['source']['requested_object_count']}.",
        f"Verified pairs: {evidence['source']['successful_object_count']}.",
        f"Failed pairs: {evidence['source']['failed_object_count']}.",
        "",
    ]
    if evidence["source"]["failures"]:
        lines.extend(["## Source failures", ""])
        for failure in evidence["source"]["failures"]:
            lines.append(
                f"- `{failure['market']} {failure['kind']} {failure['period']}`: {failure['error']}"
            )
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
            "Folds G/A | Months G/A | IQR | High-low gross | High-low adverse |",
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
            f"{result['temporal']['positive_gross_folds']}/8 / "
            f"{result['temporal']['positive_adverse_folds']}/8 | "
            f"{result['temporal']['positive_gross_months']}/8 / "
            f"{result['temporal']['positive_adverse_months']}/8 | "
            f"{result['state_quantiles']['iqr']:.4f} | "
            f"{result['high_minus_low']['gross']:+.4%} | "
            f"{result['high_minus_low']['adverse']:+.4%} |"
        )
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
            f"gross rho 95% CI   [{common['gross_rho_ci95'][0]:+.4f}, "
            f"{common['gross_rho_ci95'][1]:+.4f}]",
            f"adverse rho 95% CI [{common['adverse_rho_ci95'][0]:+.4f}, "
            f"{common['adverse_rho_ci95'][1]:+.4f}]",
            f"valid draws          {common['valid_draws']}/{RESAMPLES}",
            "```",
            "",
            "Candidate count is zero, so train/OOS/full executable return, Sharpe, maximum "
            "drawdown, benchmark residual, edge per turnover and strategy turnover are not "
            "computed. The exactly 5 bps one-way fee is embedded only in each independent "
            "target label.",
        ]
    )
    return "\n".join(lines) + "\n"


def abort_evidence(
    specs: list[ObjectSpec], downloaded: list[Downloaded], failed: list[FailedObject]
) -> dict[str, Any]:
    return {
        "family_id": FAMILY_ID,
        "classification": "training-only exogenous-information eligibility diagnostic",
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
        "sample": {"intended_decisions_per_market": 242, "completed_decisions": 0},
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
                    instrument="ALL",
                    kind="parsed_1h_grid",
                    period="2024-01..2024-09",
                    url="verified archives",
                    checksum_url="verified companion checksums",
                    error=str(exc),
                )
            ]
    if failed:
        evidence = abort_evidence(specs, downloaded, failed)
    else:
        tables = {
            market: build_labels(kinds["spot_1h_kline"], kinds["coinm_perpetual_1h_kline"])
            for market, kinds in frames.items()
        }
        indices = bootstrap_indices(242)
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
            "support_coinm_basis_compression_resilience_information_premise"
            if accepted
            else "reject_coinm_basis_compression_resilience_information_premise"
        )
        evidence = {
            "family_id": FAMILY_ID,
            "classification": "training-only exogenous-information eligibility diagnostic",
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
                "intended_decisions_per_market": 242,
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
            table_to_write.to_csv(output_dir / f"{market}-labels.csv", index=False)
    write_json(output_dir / "source-manifest.json", manifest)
    write_json(output_dir / "evidence.json", evidence)
    (output_dir / "report.md").write_text(render_report(evidence), encoding="utf-8")
    digest = hashlib.sha256((output_dir / "evidence.json").read_bytes()).hexdigest()
    (output_dir / "evidence.sha256").write_text(f"{digest}  evidence.json\n", encoding="utf-8")
    print(json.dumps({"verdict": evidence["verdict"], "evidence_sha256": digest}, sort_keys=True))


if __name__ == "__main__":
    main()
