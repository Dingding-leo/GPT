from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import os
import tempfile
import time
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import acquire_okx_historical_trades as source
import numpy as np
import pandas as pd

from gpt_quant.okx_1h import fetch_okx_one_hour_candles

ARCHITECTURE = "okx-spot-causal-trade-flow-resilience-v2"
MARKETS = ("BTC-USDT", "ETH-USDT")
FEE = 0.0005
HOUR_MS = 3_600_000
DAY_MS = 24 * HOUR_MS
WARMUP_HOURS = 720
FOLD_HOURS = 90 * 24
FOLDS = 12
EVALUATION_HOURS = FOLD_HOURS * FOLDS
DEVELOPMENT_DAYS = 1290
RESERVED_DAYS = 180
TREND_LOOKBACK = 2160
BLOCK_HOURS = 168
RESAMPLES = 5000
SEED = 20260728


@dataclass
class HourAggregate:
    signed: Decimal = Decimal()
    total: Decimal = Decimal()
    count: int = 0
    first_price: Decimal | None = None
    last_price: Decimal | None = None
    first_trade_id: int | None = None
    last_trade_id: int | None = None


@dataclass
class ParsedFile:
    metadata: dict[str, Any]
    hours: dict[int, HourAggregate]


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_timestamp(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).isoformat().replace("+00:00", "Z")


def floor_day_ms(ms: int) -> int:
    value = datetime.fromtimestamp(ms / 1000, UTC)
    day = value.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(day.timestamp() * 1000)


def persist(path: Path, data: bytes) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def request_manifest(
    base_url: str, inst_id: str, begin_ms: int, end_ms: int, aggregation: str
) -> tuple[dict[str, Any], bytes, str]:
    query = urlencode(
        {
            "module": "1",
            "instType": "SPOT",
            "instIdList": inst_id,
            "dateAggrType": aggregation,
            "begin": str(begin_ms),
            "end": str(end_ms),
        }
    )
    url = f"{base_url.rstrip('/')}/api/v5/public/market-data-history?{query}"
    payload, raw, final_url, _ = source.request_json(url)
    if str(payload.get("code")) != "0":
        raise ValueError(f"archive manifest failed for {inst_id}: {payload.get('msg')}")
    return payload, raw, final_url


def one_daily_record(
    base_url: str, inst_id: str, requested_day_ms: int, root: Path
) -> dict[str, Any] | None:
    payload, raw, final_url = request_manifest(
        base_url,
        inst_id,
        requested_day_ms,
        requested_day_ms + DAY_MS - 1,
        "daily",
    )
    persist(root / f"daily-{requested_day_ms}.json", raw)
    records = source.find_download_records(payload)
    accepted: list[dict[str, Any]] = []
    expected_start = requested_day_ms - 8 * HOUR_MS
    for record in records:
        try:
            declared_start = source.exact_integer(record.get("dateTs"), "dateTs")
        except ValueError:
            continue
        if declared_start != expected_start:
            continue
        if str(record.get("instId", inst_id)) != inst_id:
            continue
        url = str(record["url"])
        if not source.trusted_okx_host(url):
            raise ValueError("manifest returned an untrusted archive URL")
        accepted.append(
            {
                "url": url,
                "declared_start_ms": declared_start,
                "requested_day_ms": requested_day_ms,
                "manifest_final_url": final_url,
                "manifest_record": record,
            }
        )
    if not accepted:
        return None
    if len(accepted) != 1:
        raise ValueError("daily manifest returned multiple matching files")
    return accepted[0]


def determine_common_t_end(base_url: str, now_ms: int, root: Path) -> tuple[int, dict[str, Any]]:
    today = floor_day_ms(now_ms)
    attempts: list[dict[str, Any]] = []
    for days_back in range(4, 15):
        candidate = today - days_back * DAY_MS
        market_records: dict[str, Any] = {}
        passed = True
        for inst_id in MARKETS:
            market_root = root / inst_id
            current = one_daily_record(base_url, inst_id, candidate, market_root)
            previous = one_daily_record(base_url, inst_id, candidate - DAY_MS, market_root)
            market_records[inst_id] = {"current": current, "previous": previous}
            if current is None or previous is None:
                passed = False
        attempts.append(
            {
                "candidate_t_end_ms": candidate,
                "candidate_t_end": utc_timestamp(candidate),
                "markets": market_records,
                "two_adjacent_exchange_days_available": passed,
            }
        )
        if passed:
            return candidate, {"attempts": attempts, "selected": attempts[-1]}
    raise ValueError("no common recent archive boundary with adjacent daily files")


def month_starts(start_ms: int, end_ms: int) -> Iterable[tuple[int, int]]:
    start = datetime.fromtimestamp(start_ms / 1000, UTC).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    end = datetime.fromtimestamp(end_ms / 1000, UTC)
    cursor = start
    while cursor < end:
        if cursor.month == 12:
            nxt = cursor.replace(year=cursor.year + 1, month=1)
        else:
            nxt = cursor.replace(month=cursor.month + 1)
        yield int(cursor.timestamp() * 1000), int(nxt.timestamp() * 1000)
        cursor = nxt


def collect_monthly_records(
    base_url: str, inst_id: str, start_ms: int, end_ms: int, root: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records_by_url: dict[str, dict[str, Any]] = {}
    manifests: list[dict[str, Any]] = []
    query_start = start_ms - DAY_MS
    query_end = end_ms + DAY_MS
    for begin_ms, next_month_ms in month_starts(query_start, query_end):
        payload, raw, final_url = request_manifest(
            base_url,
            inst_id,
            begin_ms,
            next_month_ms - 1,
            "monthly",
        )
        response_record = persist(root / "manifests" / f"monthly-{begin_ms}.json", raw)
        discovered = source.find_download_records(payload)
        manifests.append(
            {
                "begin_ms": begin_ms,
                "end_ms": next_month_ms - 1,
                "begin": utc_timestamp(begin_ms),
                "end": utc_timestamp(next_month_ms - 1),
                "final_url": final_url,
                "response": response_record,
                "download_record_count": len(discovered),
            }
        )
        for record in discovered:
            if str(record.get("instId", inst_id)) != inst_id:
                continue
            url = str(record["url"])
            if not source.trusted_okx_host(url):
                raise ValueError("monthly manifest returned an untrusted archive URL")
            records_by_url[url] = {"url": url, "manifest_record": record}
    records = list(records_by_url.values())
    if not records:
        raise ValueError(f"monthly manifest returned no archive files for {inst_id}")
    records.sort(key=lambda item: (str(item["manifest_record"].get("dateTs", "")), item["url"]))
    return records, manifests


def download_to_file(url: str, destination: Path, timeout: float = 300.0) -> dict[str, Any]:
    if not source.trusted_okx_host(url):
        raise ValueError("untrusted archive download host")
    request = Request(
        url,
        headers={"Accept": "application/zip,text/csv,*/*", "User-Agent": "gpt-quant-lab/0.3"},
    )
    digest = hashlib.sha256()
    size = 0
    started = time.monotonic()
    with urlopen(request, timeout=timeout) as response, destination.open("wb") as handle:  # noqa: S310
        final_url = response.geturl()
        if not source.trusted_okx_host(final_url):
            raise ValueError("archive download redirected to an untrusted host")
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    return {
        "url": url,
        "final_url": final_url,
        "bytes": size,
        "sha256": digest.hexdigest(),
        "elapsed_seconds": time.monotonic() - started,
    }


def extract_member(archive_path: Path, csv_path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    size = 0
    if zipfile.is_zipfile(archive_path):
        with zipfile.ZipFile(archive_path) as archive:
            members = [
                member
                for member in archive.infolist()
                if not member.is_dir() and member.filename.lower().endswith(".csv")
            ]
            if len(members) != 1:
                raise ValueError("archive must contain exactly one CSV member")
            member = members[0]
            with archive.open(member) as source_handle, csv_path.open("wb") as output:
                for chunk in iter(lambda: source_handle.read(1024 * 1024), b""):
                    output.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
            return {
                "compression": "zip",
                "member_name": member.filename,
                "member_crc": member.CRC,
                "declared_member_bytes": member.file_size,
                "observed_member_bytes": size,
                "member_sha256": digest.hexdigest(),
            }
    if archive_path.suffix.lower() == ".gz":
        with gzip.open(archive_path, "rb") as source_handle, csv_path.open("wb") as output:
            for chunk in iter(lambda: source_handle.read(1024 * 1024), b""):
                output.write(chunk)
                digest.update(chunk)
                size += len(chunk)
        return {
            "compression": "gzip",
            "observed_member_bytes": size,
            "member_sha256": digest.hexdigest(),
        }
    raw = archive_path.read_bytes()
    csv_path.write_bytes(raw)
    return {
        "compression": "none",
        "observed_member_bytes": len(raw),
        "member_sha256": hashlib.sha256(raw).hexdigest(),
    }


def archive_fields(fieldnames: list[str] | None) -> tuple[str, str, str, str, str, str]:
    if not fieldnames:
        raise ValueError("archive CSV has no header")
    lowered = {field.lower(): field for field in fieldnames}

    def required(*names: str) -> str:
        for name in names:
            if name in lowered:
                return lowered[name]
        raise ValueError(f"archive CSV missing required field {names}")

    return (
        required("instrument_name", "instid", "inst_id", "instrument"),
        required("trade_id", "tradeid", "id"),
        required("side"),
        required("price", "px"),
        required("size", "sz", "amount"),
        required("created_time", "timestamp", "ts", "time"),
    )


def parse_csv_file(csv_path: Path, inst_id: str, start_ms: int, end_ms: int) -> ParsedFile:
    hours: dict[int, HourAggregate] = {}
    rows = 0
    selected_rows = 0
    duplicate_rows = 0
    min_ts: int | None = None
    max_ts: int | None = None
    previous: source.Trade | None = None
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        inst_field, id_field, side_field, price_field, size_field, ts_field = archive_fields(
            reader.fieldnames
        )
        header = list(reader.fieldnames or [])
        for raw in reader:
            observed_inst = str(raw.get(inst_field, "")).strip()
            if observed_inst != inst_id:
                raise ValueError(f"mixed archive instrument: {observed_inst}")
            trade = source.normalize_trade(
                inst_id,
                raw.get(id_field),
                raw.get(side_field),
                raw.get(price_field),
                raw.get(size_field),
                raw.get(ts_field),
            )
            rows += 1
            if previous is not None:
                if trade[1] == previous[1]:
                    if trade != previous:
                        raise ValueError("conflicting duplicate trade identity")
                    duplicate_rows += 1
                    continue
                if trade[1] < previous[1] or trade[5] < previous[5]:
                    raise ValueError("archive provider order is not chronological")
            previous = trade
            min_ts = trade[5] if min_ts is None else min(min_ts, trade[5])
            max_ts = trade[5] if max_ts is None else max(max_ts, trade[5])
            if not start_ms <= trade[5] < end_ms:
                continue
            selected_rows += 1
            hour = trade[5] // HOUR_MS * HOUR_MS
            aggregate = hours.setdefault(hour, HourAggregate())
            quote = trade[3] * trade[4]
            aggregate.total += quote
            aggregate.signed += quote if trade[2] == "buy" else -quote
            aggregate.count += 1
            if aggregate.first_price is None:
                aggregate.first_price = trade[3]
                aggregate.first_trade_id = trade[1]
            aggregate.last_price = trade[3]
            aggregate.last_trade_id = trade[1]
    if rows == 0 or min_ts is None or max_ts is None:
        raise ValueError("archive CSV contains no trades")
    return ParsedFile(
        metadata={
            "header": header,
            "rows": rows,
            "selected_rows": selected_rows,
            "exact_duplicate_rows_removed": duplicate_rows,
            "min_ts_ms": min_ts,
            "max_ts_ms": max_ts,
            "min_ts": utc_timestamp(min_ts),
            "max_ts": utc_timestamp(max_ts),
        },
        hours=hours,
    )


def merge_hours(
    parsed_files: list[ParsedFile], start_ms: int, end_ms: int
) -> dict[int, HourAggregate]:
    ordered = sorted(parsed_files, key=lambda item: item.metadata["min_ts_ms"])
    for left, right in zip(ordered, ordered[1:], strict=False):
        if left.metadata["max_ts_ms"] >= right.metadata["min_ts_ms"]:
            raise ValueError("archive files overlap or reverse in event time")
    merged: dict[int, HourAggregate] = {}
    for parsed in ordered:
        for hour, item in sorted(parsed.hours.items()):
            if hour in merged:
                raise ValueError("archive files overlap inside a UTC feature hour")
            merged[hour] = item
    expected = list(range(start_ms, end_ms, HOUR_MS))
    if sorted(merged) != expected:
        missing = sorted(set(expected) - set(merged))
        extra = sorted(set(merged) - set(expected))
        raise ValueError(
            f"hourly trade coverage mismatch: missing={len(missing)} extra={len(extra)}"
        )
    return merged


def acquire_trade_features(
    base_url: str, inst_id: str, start_ms: int, end_ms: int, output_dir: Path
) -> tuple[pd.DataFrame, dict[str, Any]]:
    records, manifests = collect_monthly_records(base_url, inst_id, start_ms, end_ms, output_dir)
    parsed_files: list[ParsedFile] = []
    file_inventory: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix=f"{inst_id}-archives-") as temporary:
        temp_root = Path(temporary)
        for index, record in enumerate(records):
            archive_path = temp_root / f"archive-{index:03d}.bin"
            csv_path = temp_root / f"archive-{index:03d}.csv"
            download = download_to_file(record["url"], archive_path)
            member = extract_member(archive_path, csv_path)
            parsed = parse_csv_file(csv_path, inst_id, start_ms, end_ms)
            parsed_files.append(parsed)
            file_inventory.append(
                {
                    "manifest_record": record["manifest_record"],
                    "download": download,
                    "member": member,
                    "observed": parsed.metadata,
                    "raw_archive_retained_in_artifact": False,
                    "replay_contract": "trusted URL plus exact compressed and decompressed SHA-256",
                }
            )
    merged = merge_hours(parsed_files, start_ms, end_ms)
    rows: list[dict[str, Any]] = []
    for hour in sorted(merged):
        item = merged[hour]
        if item.total <= 0 or item.first_price is None or item.last_price is None:
            raise ValueError("invalid hourly trade aggregate")
        rows.append(
            {
                "timestamp": pd.Timestamp(hour, unit="ms", tz="UTC"),
                "trade_count": item.count,
                "flow": float(item.signed / item.total),
                "impact_return": math.log(float(item.last_price / item.first_price)),
                "first_trade_id": str(item.first_trade_id),
                "last_trade_id": str(item.last_trade_id),
            }
        )
    frame = pd.DataFrame(rows).set_index("timestamp")
    csv_bytes = frame.to_csv(index=True, lineterminator="\n", float_format="%.18g").encode()
    feature_record = persist(output_dir / "hourly-trade-features.csv", csv_bytes)
    metadata = {
        "instrument": inst_id,
        "manifest_queries": manifests,
        "archive_files": file_inventory,
        "archive_file_count": len(file_inventory),
        "selected_trade_rows": int(frame["trade_count"].sum()),
        "complete_hours": len(frame),
        "missing_hours": 0,
        "feature_record": feature_record,
        "raw_archive_bytes_retained": False,
    }
    persist(output_dir / "archive-inventory.json", canonical_json(metadata))
    return frame, metadata


def persist_candles(
    snapshot: Any, output_dir: Path, inst_id: str
) -> tuple[pd.Series, dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    candles = snapshot.candles.copy()
    csv_bytes = candles.to_csv(index=True, lineterminator="\n", float_format="%.18g").encode()
    raw_bytes = canonical_json(list(snapshot.raw_pages))
    metadata_bytes = canonical_json(snapshot.metadata)
    csv_record = persist(output_dir / "candles.csv", csv_bytes)
    raw_record = persist(output_dir / "candles.raw.json", raw_bytes)
    metadata_record = persist(output_dir / "candles.metadata.json", metadata_bytes)
    if "close" not in candles.columns:
        raise ValueError("canonical candle snapshot has no close column")
    close = candles["close"].astype(float)
    close.index = pd.DatetimeIndex(close.index).tz_convert("UTC")
    return close, {
        "instrument": inst_id,
        "csv": csv_record,
        "raw": raw_record,
        "metadata": metadata_record,
        "observations": len(close),
        "start": close.index[0].isoformat(),
        "end": close.index[-1].isoformat(),
    }


def rolling_mad(values: pd.Series, window: int) -> pd.Series:
    return values.rolling(window, min_periods=window).apply(
        lambda raw: float(np.median(np.abs(raw - np.median(raw)))),
        raw=True,
    )


def build_targets(features: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    flow = features["flow"].astype(float)
    impact = features["impact_return"].astype(float)
    signed_quote_proxy = flow * features["trade_count"].astype(float)
    total_quote_proxy = features["trade_count"].astype(float)
    flow6 = (
        signed_quote_proxy.rolling(6, min_periods=6).sum()
        / total_quote_proxy.rolling(6, min_periods=6).sum()
    )
    prior_flow6 = flow6.shift(1)
    median_flow = prior_flow6.rolling(WARMUP_HOURS, min_periods=WARMUP_HOURS).median()
    mad_flow = rolling_mad(prior_flow6, WARMUP_HOURS)
    z_flow = (flow6 - median_flow) / mad_flow.replace(0.0, np.nan)
    v1 = np.tanh(z_flow).clip(lower=0.0)

    x = flow.to_numpy(dtype=float)
    y = impact.to_numpy(dtype=float)
    z_residual = np.full(len(features), np.nan)
    for index in range(WARMUP_HOURS, len(features)):
        train_x = x[index - WARMUP_HOURS : index]
        train_y = y[index - WARMUP_HOURS : index]
        if not np.isfinite(train_x).all() or not np.isfinite(train_y).all():
            continue
        x_mean = float(train_x.mean())
        y_mean = float(train_y.mean())
        denominator = float(np.square(train_x - x_mean).sum())
        if denominator <= 0:
            continue
        beta = float(((train_x - x_mean) * (train_y - y_mean)).sum() / denominator)
        alpha = y_mean - beta * x_mean
        residuals = train_y - (alpha + beta * train_x)
        scale = float(np.median(np.abs(residuals - np.median(residuals))))
        if not math.isfinite(scale) or scale <= 0:
            continue
        z_residual[index] = (y[index] - (alpha + beta * x[index])) / scale
    z_series = pd.Series(z_residual, index=features.index)
    resilience6 = z_series.rolling(6, min_periods=6).mean()
    v2 = np.tanh(resilience6).clip(lower=0.0)
    targets = pd.DataFrame({"V1": v1, "V2": v2}, index=features.index)
    invalid = {
        "V1": int(targets["V1"].isna().sum()),
        "V2": int(targets["V2"].isna().sum()),
    }
    return targets.fillna(0.0), invalid


def strategy_frame(target: pd.Series, close: pd.Series) -> pd.DataFrame:
    target = target.reindex(close.index).fillna(0.0).clip(0.0, 1.0)
    position = target.shift(1).fillna(0.0)
    asset_return = close.pct_change().fillna(0.0)
    turnover = position.diff().abs().fillna(position.abs())
    fee = turnover * FEE
    gross = position * asset_return
    net = gross - fee
    return pd.DataFrame(
        {
            "close": close,
            "asset_return": asset_return,
            "target": target,
            "position": position,
            "turnover": turnover,
            "fee": fee,
            "gross_return": gross,
            "net_return": net,
        }
    )


def trend_frame(close: pd.Series) -> pd.DataFrame:
    target = (close.pct_change(TREND_LOOKBACK) > 0.0).astype(float)
    return strategy_frame(target, close)


def compounded(values: pd.Series) -> float:
    return float((1.0 + values).prod() - 1.0)


def sharpe(values: pd.Series) -> float | None:
    std = float(values.std(ddof=0))
    if not math.isfinite(std) or std <= 0:
        return None
    return float(values.mean() / std * math.sqrt(8760.0))


def max_drawdown(values: pd.Series) -> float:
    nav = (1.0 + values).cumprod()
    drawdown = nav / nav.cummax() - 1.0
    return float(drawdown.min())


def minimum_rolling_return(values: pd.Series, window: int) -> float | None:
    if len(values) < window:
        return None
    rolling = (1.0 + values).rolling(window).apply(np.prod, raw=True) - 1.0
    return float(rolling.min())


def metrics(frame: pd.DataFrame) -> dict[str, Any]:
    net = frame["net_return"]
    gross = frame["gross_return"]
    total_return = compounded(net)
    annualized = (1.0 + total_return) ** (8760.0 / len(frame)) - 1.0 if total_return > -1 else -1.0
    drawdown = max_drawdown(net)
    turnover = float(frame["turnover"].sum())
    value_sharpe = sharpe(net)
    return {
        "observations": len(frame),
        "gross_return": compounded(gross),
        "net_return": total_return,
        "annualized_return": annualized,
        "sharpe": value_sharpe,
        "calmar": None if drawdown >= 0 else annualized / abs(drawdown),
        "max_drawdown": drawdown,
        "turnover": turnover,
        "annualized_turnover": turnover * 8760.0 / len(frame),
        "fee_drag_arithmetic": float(frame["fee"].sum()),
        "edge_per_turnover_bps": None if turnover <= 0 else float(net.sum() / turnover * 10_000.0),
        "exposure": float(frame["position"].mean()),
        "decisions": int((frame["turnover"] > 0).sum()),
        "worst_24h_return": minimum_rolling_return(net, 24),
        "worst_168h_return": minimum_rolling_return(net, 168),
    }


def evaluate_market(
    inst_id: str,
    features: pd.DataFrame,
    close: pd.Series,
    development_start: pd.Timestamp,
    development_end: pd.Timestamp,
    output_dir: Path,
) -> tuple[dict[str, Any], dict[str, pd.DataFrame]]:
    if not features.index.equals(close.index):
        raise ValueError(f"feature/candle index mismatch for {inst_id}")
    targets, invalid = build_targets(features)
    frames = {variant: strategy_frame(targets[variant], close) for variant in ("V1", "V2")}
    frames["trend"] = trend_frame(close)
    evaluation_start = development_start + pd.Timedelta(hours=WARMUP_HOURS)
    evaluation_end = development_end - pd.Timedelta(hours=1)
    evaluation_frames = {
        name: frame.loc[evaluation_start:evaluation_end].copy() for name, frame in frames.items()
    }
    if any(len(frame) != EVALUATION_HOURS for frame in evaluation_frames.values()):
        raise ValueError("evaluation window is not exactly twelve 90-day folds")
    per_policy: dict[str, Any] = {}
    for name, frame in evaluation_frames.items():
        fold_rows: list[dict[str, Any]] = []
        for fold in range(FOLDS):
            fold_frame = frame.iloc[fold * FOLD_HOURS : (fold + 1) * FOLD_HOURS]
            fold_rows.append({"fold": fold + 1, **metrics(fold_frame)})
        positive = [row["net_return"] for row in fold_rows if row["net_return"] > 0]
        blocks = [metrics(frame.iloc[index * 8640 : (index + 1) * 8640]) for index in range(3)]
        aggregate = metrics(frame)
        aggregate.update(
            {
                "invalid_feature_hours_in_full_development": invalid.get(name, 0),
                "profitable_folds": sum(row["net_return"] > 0 for row in fold_rows),
                "positive_fold_concentration": None
                if not positive
                else max(positive) / sum(positive),
                "folds": fold_rows,
                "blocks_360d": blocks,
            }
        )
        per_policy[name] = aggregate
    for variant in ("V1", "V2"):
        residual = (
            evaluation_frames[variant]["net_return"] - evaluation_frames["trend"]["net_return"]
        )
        per_policy[variant]["residual_return_vs_trend_arithmetic"] = float(residual.sum())
        per_policy[variant]["residual_sharpe_vs_trend"] = sharpe(residual)
        trend_edge = per_policy["trend"]["edge_per_turnover_bps"]
        variant_edge = per_policy[variant]["edge_per_turnover_bps"]
        per_policy[variant]["edge_per_turnover_delta_vs_trend_bps"] = (
            None if variant_edge is None or trend_edge is None else variant_edge - trend_edge
        )
    output = pd.concat(
        {name: frame for name, frame in evaluation_frames.items()},
        axis=1,
    )
    persist(
        output_dir / "evaluation-paths.csv",
        output.to_csv(lineterminator="\n", float_format="%.18g").encode(),
    )
    return {
        "instrument": inst_id,
        "development_start": development_start.isoformat(),
        "development_end_exclusive": development_end.isoformat(),
        "evaluation_start": evaluation_start.isoformat(),
        "evaluation_end_inclusive": evaluation_end.isoformat(),
        "candidate_fold_evaluations": 2 * FOLDS,
        "policies": per_policy,
    }, evaluation_frames


def resample_indices(rng: np.random.Generator) -> np.ndarray:
    pieces: list[np.ndarray] = []
    for fold in range(FOLDS):
        base = fold * FOLD_HOURS
        starts = rng.integers(
            0, FOLD_HOURS - BLOCK_HOURS + 1, size=math.ceil(FOLD_HOURS / BLOCK_HOURS)
        )
        indices = np.concatenate([np.arange(start, start + BLOCK_HOURS) for start in starts])[
            :FOLD_HOURS
        ]
        pieces.append(base + indices)
    return np.concatenate(pieces)


def array_sharpe(values: np.ndarray) -> float:
    std = float(np.std(values))
    return float("nan") if std <= 0 else float(np.mean(values) / std * math.sqrt(8760.0))


def array_edge(net: np.ndarray, turnover: np.ndarray) -> float:
    total = float(np.sum(turnover))
    return float("nan") if total <= 0 else float(np.sum(net) / total * 10_000.0)


def inference(frames: dict[str, dict[str, pd.DataFrame]]) -> dict[str, Any]:
    market_names = list(MARKETS)
    observed: dict[str, float] = {}
    endpoint_samples: dict[str, list[float]] = {
        name: []
        for name in (
            "v2_minus_v1_sharpe",
            "v2_minus_v1_edge",
            "v2_residual_sharpe_vs_trend",
            "v2_minus_trend_edge",
        )
    }

    def endpoint_values(indices: np.ndarray | None = None) -> dict[str, float]:
        per_market: dict[str, dict[str, float]] = {}
        for market in market_names:
            selected: dict[str, tuple[np.ndarray, np.ndarray]] = {}
            for policy in ("V1", "V2", "trend"):
                frame = frames[market][policy]
                net = frame["net_return"].to_numpy(dtype=float)
                turnover = frame["turnover"].to_numpy(dtype=float)
                if indices is not None:
                    net = net[indices]
                    turnover = turnover[indices]
                selected[policy] = net, turnover
            v1_net, v1_turnover = selected["V1"]
            v2_net, v2_turnover = selected["V2"]
            trend_net, trend_turnover = selected["trend"]
            per_market[market] = {
                "v2_minus_v1_sharpe": array_sharpe(v2_net) - array_sharpe(v1_net),
                "v2_minus_v1_edge": array_edge(v2_net, v2_turnover)
                - array_edge(v1_net, v1_turnover),
                "v2_residual_sharpe_vs_trend": array_sharpe(v2_net - trend_net),
                "v2_minus_trend_edge": array_edge(v2_net, v2_turnover)
                - array_edge(trend_net, trend_turnover),
            }
        return {
            endpoint: min(per_market[market][endpoint] for market in market_names)
            for endpoint in endpoint_samples
        }

    observed.update(endpoint_values())
    rng = np.random.default_rng(SEED)
    undefined = {name: 0 for name in endpoint_samples}
    for _ in range(RESAMPLES):
        values = endpoint_values(resample_indices(rng))
        for name, value in values.items():
            if math.isfinite(value):
                endpoint_samples[name].append(value)
            else:
                undefined[name] += 1
    raw_p: dict[str, float] = {}
    results: dict[str, Any] = {}
    for name, samples in endpoint_samples.items():
        array = np.asarray(samples, dtype=float)
        if len(array) == 0:
            lower = None
            p_value = 1.0
        else:
            lower = float(np.quantile(array, 0.05))
            p_value = float((1 + np.count_nonzero(array <= 0.0)) / (len(array) + 1))
        raw_p[name] = p_value
        results[name] = {
            "observed": observed[name],
            "one_sided_95pct_lower_bound": lower,
            "raw_one_sided_p": p_value,
            "defined_resamples": len(samples),
            "undefined_resamples": undefined[name],
        }
    ordered = sorted(raw_p, key=raw_p.get)
    running = 0.0
    for rank, name in enumerate(ordered):
        adjusted = min(1.0, raw_p[name] * (len(ordered) - rank))
        running = max(running, adjusted)
        results[name]["holm_adjusted_p"] = running
    return {
        "block_hours": BLOCK_HOURS,
        "resamples": RESAMPLES,
        "seed": SEED,
        "within_fold_only": True,
        "common_calendar_indices": True,
        "holm_family_size": 4,
        "endpoints": results,
    }


def qualification(
    markets: dict[str, Any], statistical: dict[str, Any], provenance_complete: bool
) -> tuple[str, list[str]]:
    failures: list[str] = []
    for market, result in markets.items():
        v2 = result["policies"]["V2"]
        if v2["net_return"] <= 0 or v2["sharpe"] is None or v2["sharpe"] <= 0:
            failures.append(f"{market}: non-positive aggregate return or Sharpe")
        if v2["profitable_folds"] < 7:
            failures.append(f"{market}: profitable-fold breadth below 7/12")
        if sum(block["net_return"] > 0 for block in v2["blocks_360d"]) < 2:
            failures.append(f"{market}: profitable 360-day block breadth below 2/3")
        concentration = v2["positive_fold_concentration"]
        if concentration is None or concentration > 0.5:
            failures.append(f"{market}: exceptional-fold concentration")
        if v2["edge_per_turnover_bps"] is None or v2["edge_per_turnover_bps"] <= 0:
            failures.append(f"{market}: non-positive edge per turnover")
        if v2["residual_sharpe_vs_trend"] is None or v2["residual_sharpe_vs_trend"] <= 0:
            failures.append(f"{market}: non-positive residual Sharpe versus trend")
        delta = v2["edge_per_turnover_delta_vs_trend_bps"]
        if delta is None or delta <= 0:
            failures.append(f"{market}: edge per turnover not above trend")
    for name, endpoint in statistical["endpoints"].items():
        lower = endpoint["one_sided_95pct_lower_bound"]
        if lower is None or lower <= 0 or endpoint["holm_adjusted_p"] >= 0.05:
            failures.append(f"inference:{name} lacks positive Holm-adjusted evidence")
    if not provenance_complete:
        failures.append(
            "raw archive bytes were streamed and hashed but not retained in the workflow artifact"
        )
    verdict = (
        "trade_flow_resilience_nominated_for_untouched_archive_replication"
        if not failures
        else "trade_flow_resilience_family_rejected"
    )
    return verdict, failures


def run(base_url: str, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    server_ms, server_record = source.fetch_server_time(base_url.rstrip("/"))
    t_end_ms, boundary = determine_common_t_end(base_url, server_ms, output_dir / "boundary")
    development_start_ms = t_end_ms - DEVELOPMENT_DAYS * DAY_MS
    development_end_ms = t_end_ms - RESERVED_DAYS * DAY_MS
    development_start = pd.Timestamp(development_start_ms, unit="ms", tz="UTC")
    development_end = pd.Timestamp(development_end_ms, unit="ms", tz="UTC")
    expected_hours = WARMUP_HOURS + EVALUATION_HOURS
    if (development_end_ms - development_start_ms) // HOUR_MS != expected_hours:
        raise ValueError("frozen development interval length is inconsistent")

    market_results: dict[str, Any] = {}
    evaluation_frames: dict[str, dict[str, pd.DataFrame]] = {}
    acquisition: dict[str, Any] = {}
    for inst_id in MARKETS:
        market_root = output_dir / inst_id
        features, trade_record = acquire_trade_features(
            base_url,
            inst_id,
            development_start_ms,
            development_end_ms,
            market_root / "trades",
        )
        candle_snapshot = fetch_okx_one_hour_candles(
            inst_id=inst_id,
            start=development_start,
            end=development_end - pd.Timedelta(hours=1),
            base_url=base_url,
            pause_seconds=0.12,
            timeout=30.0,
        )
        close, candle_record = persist_candles(candle_snapshot, market_root / "candles", inst_id)
        result, frames = evaluate_market(
            inst_id,
            features,
            close,
            development_start,
            development_end,
            market_root,
        )
        market_results[inst_id] = result
        evaluation_frames[inst_id] = frames
        acquisition[inst_id] = {"trades": trade_record, "candles": candle_record}

    statistical = inference(evaluation_frames)
    raw_archive_bytes_retained = all(
        record["trades"]["raw_archive_bytes_retained"] for record in acquisition.values()
    )
    verdict, failures = qualification(market_results, statistical, raw_archive_bytes_retained)
    result = {
        "schema_version": "trade-flow-development-comparison-v1",
        "architecture_family_id": ARCHITECTURE,
        "candidate_count": 2,
        "new_strategy_architectures": 1,
        "candidate_fold_evaluations": 48,
        "confirmatory_endpoint_family": 4,
        "markets": list(MARKETS),
        "bar": "1H",
        "canonical_fee_bps_one_way": 5.0,
        "execution_delay_complete_bars": 1,
        "performance_previously_seen": False,
        "reserved_oos_consumed": False,
        "global_independent_family_count": None,
        "dsr_status": "prohibited_incomplete_global_independent_family_inventory",
        "pbo_status": "prohibited_no_valid_complete_candidate_by_split_selection_matrix",
        "server_time": {"ms": server_ms, "utc": utc_timestamp(server_ms), **server_record},
        "t_end_ms": t_end_ms,
        "t_end": utc_timestamp(t_end_ms),
        "development_start": development_start.isoformat(),
        "development_end_exclusive": development_end.isoformat(),
        "reserved_interval_start": development_end.isoformat(),
        "reserved_interval_end_exclusive": pd.Timestamp(t_end_ms, unit="ms", tz="UTC").isoformat(),
        "boundary_evidence": boundary,
        "acquisition": acquisition,
        "market_results": market_results,
        "statistical_inference": statistical,
        "provenance_gate": {
            "manifest_bytes_persisted": True,
            "compressed_and_decompressed_hashes_persisted": True,
            "raw_archive_bytes_retained_in_artifact": raw_archive_bytes_retained,
        },
        "qualification_failures": failures,
        "verdict": verdict,
        "next_step": (
            "untouched_archive_replication under the unchanged hash"
            if verdict.endswith("nominated_for_untouched_archive_replication")
            else "cool down the exact V1/V2 family; do not rescue-tune on this development interval"
        ),
    }
    result_bytes = canonical_json(result)
    persist(output_dir / "result.json", result_bytes)
    persist(
        output_dir / "result.sha256", (hashlib.sha256(result_bytes).hexdigest() + "\n").encode()
    )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.environ.get("OKX_BASE_URL", "https://www.okx.com"))
    parser.add_argument(
        "--output-dir", type=Path, default=Path("reports/research/trade-flow-development")
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run(args.base_url, args.output_dir)
    print(
        json.dumps(
            {"verdict": result["verdict"], "failures": result["qualification_failures"]}, indent=2
        )
    )


if __name__ == "__main__":
    main()
