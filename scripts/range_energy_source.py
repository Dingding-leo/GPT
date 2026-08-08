from __future__ import annotations

import csv
import hashlib
import io
import time
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import pandas as pd

START = "2023-04-01T00:00:00Z"
END = "2025-12-31T23:00:00Z"
EXPECTED_ROWS = 24_144
TRAIN_END = 10_800
SPOT_ROOT = "https://data.binance.vision/data/spot/monthly/klines"
PERP_ROOT = "https://data.binance.vision/data/futures/um/monthly/klines"
EXPECTED_SOURCE_SHA = {
    "BTCUSDT_spot": "c282320ef644ae526eff1eec09b377868fc7ff73395506d65b6bfde6944a876d",
    "BTCUSDT_perpetual": "eabfbd041599c55d320971d7cf78014a38131f3adae9b4231710ae100f90707a",
    "ETHUSDT_spot": "ecac9b3431afb8875cc00044aa18c434ebe2f4524caef55ed1afce31f9ab7bba",
    "ETHUSDT_perpetual": "8944707c9db16673881f97a7c7284abd3666e1fb55a0c1b649d7bc6e4fdf01b9",
}
EXPECTED_TRAIN_SHA = {
    "BTCUSDT_spot": "30d38944190ebaa80e65308c806be34a572e03fea2f1e695887fbd24c2607cc6",
    "BTCUSDT_perpetual": "0d0c34a17944f9700dae97bb884610d7304d780e43969639485af56149cd6460",
    "ETHUSDT_spot": "55f38818ed50e3cf0e97412aa22b3606ae7f4ec42f3a010cb14ef85b3f2f169f",
    "ETHUSDT_perpetual": "d6f004bc17cb562bf47348f83ba521369ade169fa57d7420dc2f6dabc336471d",
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_bytes(frame: pd.DataFrame) -> bytes:
    return frame.reset_index(names="timestamp").to_csv(
        index=False,
        date_format="%Y-%m-%dT%H:%M:%S.%fZ",
        float_format="%.12g",
        lineterminator="\n",
    ).encode()


def trusted_get(url: str) -> tuple[bytes, str]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "data.binance.vision":
        raise ValueError(f"untrusted Binance archive URL: {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "gpt-quant-research/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
        final_url = response.geturl()
    final = urlparse(final_url)
    if final.scheme != "https" or final.hostname != "data.binance.vision" or not raw:
        raise ValueError(f"invalid archive response: {final_url}")
    return raw, final_url


def months() -> list[str]:
    return [str(x) for x in pd.period_range("2023-04", "2025-12", freq="M")]


def parse_checksum(raw: bytes, expected_name: str) -> str:
    parts = raw.decode("ascii").strip().split()
    if len(parts) < 2:
        raise ValueError(f"{expected_name}: malformed checksum")
    digest = parts[0].lower()
    filename = parts[-1].lstrip("*")
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError(f"{expected_name}: invalid checksum digest")
    if filename != expected_name:
        raise ValueError(f"{expected_name}: checksum filename mismatch")
    return digest


def month_grid(month: str) -> pd.DatetimeIndex:
    period = pd.Period(month, freq="M")
    start = period.start_time.tz_localize("UTC")
    end = period.end_time.floor("h").tz_localize("UTC")
    return pd.date_range(start, end, freq="h")


def parse_timestamp(raw: str, label: str) -> pd.Timestamp:
    integer = int(raw)
    unit, divisor = ("us", 3_600_000_000) if integer > 10**14 else ("ms", 3_600_000)
    if integer % divisor != 0:
        raise ValueError(f"{label}: off-grid open timestamp")
    return pd.to_datetime(integer, unit=unit, utc=True)


def parse_zip(raw: bytes, expected_name: str, month: str) -> pd.DataFrame:
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise ValueError(f"{expected_name}: bad ZIP") from exc
    expected_csv = expected_name.removesuffix(".zip") + ".csv"
    names = [name for name in archive.namelist() if not name.endswith("/")]
    if names != [expected_csv]:
        raise ValueError(f"{expected_name}: unexpected members {names}")
    rows: list[tuple[pd.Timestamp, float, float, float, float, float]] = []
    with archive.open(expected_csv) as handle:
        reader = csv.reader(io.TextIOWrapper(handle, encoding="utf-8", newline=""))
        for row_number, row in enumerate(reader, 1):
            if not row:
                continue
            if len(row) != 12:
                raise ValueError(f"{expected_name}: row {row_number} has {len(row)} columns")
            try:
                timestamp = parse_timestamp(row[0], expected_name)
            except ValueError:
                if row_number == 1 and "open" in row[0].lower():
                    continue
                raise
            try:
                open_px, high, low, close, quote_volume = map(
                    float, (row[1], row[2], row[3], row[4], row[7])
                )
            except ValueError as exc:
                raise ValueError(f"{expected_name}: nonnumeric kline field") from exc
            values = np.asarray([open_px, high, low, close, quote_volume], dtype=float)
            if not np.isfinite(values).all() or min(open_px, high, low, close) <= 0 or quote_volume < 0:
                raise ValueError(f"{expected_name}: invalid finite/positive fields")
            if high < max(open_px, low, close) or low > min(open_px, high, close):
                raise ValueError(f"{expected_name}: invalid OHLC ordering")
            rows.append((timestamp, open_px, high, low, close, quote_volume))
    frame = pd.DataFrame(
        rows,
        columns=["timestamp", "open", "high", "low", "close", "quote_volume"],
    ).set_index("timestamp").sort_index()
    expected = month_grid(month)
    if frame.index.has_duplicates or len(frame) != len(expected) or not frame.index.equals(expected):
        raise ValueError(f"{expected_name}: exact monthly 1H grid mismatch")
    return frame


def acquire(symbol: str, market: str, source_dir: Path) -> tuple[pd.DataFrame, dict[str, object]]:
    root = SPOT_ROOT if market == "spot" else PERP_ROOT
    frames: list[pd.DataFrame] = []
    month_hashes: list[dict[str, object]] = []
    for month in months():
        filename = f"{symbol}-1h-{month}.zip"
        url = f"{root}/{symbol}/1h/{filename}"
        checksum_raw, checksum_url = trusted_get(url + ".CHECKSUM")
        zip_raw, zip_url = trusted_get(url)
        declared = parse_checksum(checksum_raw, filename)
        observed = sha(zip_raw)
        if declared != observed:
            raise ValueError(f"{market}/{filename}: checksum mismatch")
        frame = parse_zip(zip_raw, filename, month)
        frames.append(frame)
        month_hashes.append(
            {
                "month": month,
                "zip_url": zip_url,
                "checksum_url": checksum_url,
                "zip_sha256": observed,
                "checksum_response_sha256": sha(checksum_raw),
                "rows": len(frame),
            }
        )
        time.sleep(0.02)
    combined = pd.concat(frames).sort_index()
    expected = pd.date_range(START, END, freq="h")
    if combined.index.has_duplicates or len(combined) != EXPECTED_ROWS or not combined.index.equals(expected):
        raise ValueError(f"{market}/{symbol}: combined 24,144H grid mismatch")
    identity = f"{symbol}_{market}"
    normalized_sha = sha(canonical_bytes(combined))
    training_sha = sha(canonical_bytes(combined.iloc[:TRAIN_END]))
    if normalized_sha != EXPECTED_SOURCE_SHA[identity]:
        raise ValueError(f"{identity}: normalized source identity mismatch")
    if training_sha != EXPECTED_TRAIN_SHA[identity]:
        raise ValueError(f"{identity}: training-prefix identity mismatch")
    (source_dir / f"binance-{market}-{symbol}-1h.csv").write_bytes(canonical_bytes(combined))
    return combined, {
        "provider": "Binance Public Data",
        "market_type": market,
        "symbol": symbol,
        "bar": "1h",
        "rows": len(combined),
        "start": str(combined.index[0]),
        "end": str(combined.index[-1]),
        "normalized_sha256": normalized_sha,
        "training_prefix_sha256": training_sha,
        "month_count": len(month_hashes),
        "months": month_hashes,
        "passed": True,
    }


def range_share(spot: pd.DataFrame, perpetual: pd.DataFrame) -> tuple[pd.Series, dict[str, object]]:
    if not spot.index.equals(perpetual.index):
        raise ValueError("spot/perpetual timestamp identity failed")
    spot_energy = np.square(np.log(spot["high"].to_numpy(float) / spot["low"].to_numpy(float)))
    perp_energy = np.square(
        np.log(perpetual["high"].to_numpy(float) / perpetual["low"].to_numpy(float))
    )
    if np.any(spot_energy < 0) or np.any(perp_energy < 0):
        raise ValueError("negative range energy")
    total = spot_energy + perp_energy
    valid = total > 0
    share = np.full(len(total), np.nan, dtype=float)
    share[valid] = perp_energy[valid] / total[valid]
    finite = share[valid]
    if len(finite) == 0 or not np.isfinite(finite).all() or finite.min() < 0 or finite.max() > 1:
        raise ValueError("perpetual range share outside [0,1]")
    scaled_spot = np.square(
        np.log((spot["high"].to_numpy(float) * 7.25) / (spot["low"].to_numpy(float) * 7.25))
    )
    scaled_perp = np.square(
        np.log(
            (perpetual["high"].to_numpy(float) * 3.5)
            / (perpetual["low"].to_numpy(float) * 3.5)
        )
    )
    scaled_total = scaled_spot + scaled_perp
    scaled_valid = scaled_total > 0
    scaled_share = np.full(len(total), np.nan, dtype=float)
    scaled_share[scaled_valid] = scaled_perp[scaled_valid] / scaled_total[scaled_valid]
    if not np.array_equal(valid, scaled_valid) or np.nanmax(np.abs(scaled_share - share)) > 1e-12:
        raise ValueError("positive-price-scale invariance failed")
    structural_zero_total_invalid = bool(np.all(np.isnan(share[~valid])))
    return pd.Series(share, index=spot.index, name="perp_range_share"), {
        "timestamp_identity": True,
        "nonnegative_energy": True,
        "range_share_bounds": True,
        "positive_price_scale_invariance": True,
        "zero_total_range_invalidation": structural_zero_total_invalid,
        "invalid_zero_total_range_hours": int(np.sum(~valid)),
        "valid_hours": int(np.sum(valid)),
    }
