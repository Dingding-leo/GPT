from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import pandas as pd

from gpt_quant.okx import _canonical_csv_bytes, _canonical_json_bytes
from gpt_quant.okx_1h import fetch_okx_one_hour_candles

FAMILY_ID = "causal-same-asset-cross-venue-spot-return-coherence-opportunity-1h-v1"
REJECT = "reject_causal_same_asset_cross_venue_spot_return_coherence_information_premise_1h_v1"
SUPPORT = "support_causal_same_asset_cross_venue_spot_return_coherence_for_separate_candidate_preregistration_1h_v1"
START = "2023-04-01T00:00:00Z"
END = "2025-12-31T23:00:00Z"
EXPECTED_ROWS = 24_144
TRAIN_START = 2_208
TRAIN_END = 10_800
OOS_START = 10_800
OOS_END = 23_760
SOURCE_END = 24_144
ROUND_TRIP_FEE = 0.0010
BOOTSTRAP_DRAWS = 5_000
BOOTSTRAP_BLOCK = 7
TARGETS = {
    "ADA-USDT": "ADAUSDT",
    "DOGE-USDT": "DOGEUSDT",
}
BOOTSTRAP_SEEDS = {"ADA-USDT": 2026080921, "DOGE-USDT": 2026080922}
BINANCE_ROOT = "https://data.binance.vision/data/spot/monthly/klines"
OUTPUT = Path("reports/research/cross-venue-spot-coherence-1h-v1")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_frame_bytes(frame: pd.DataFrame) -> bytes:
    return frame.reset_index(names="timestamp").to_csv(
        index=False,
        date_format="%Y-%m-%dT%H:%M:%S.%fZ",
        float_format="%.12g",
        lineterminator="\n",
    ).encode()


def trusted_binance_get(url: str) -> tuple[bytes, str]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "data.binance.vision":
        raise ValueError(f"untrusted Binance URL: {url}")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "gpt-quant-research/1.0"},
    )
    retryable = {408, 429, 500, 502, 503, 504}
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
                final_url = response.geturl()
            final = urlparse(final_url)
            if final.scheme != "https" or final.hostname != "data.binance.vision":
                raise ValueError(f"unexpected Binance redirect: {final_url}")
            if not raw:
                raise ValueError(f"empty Binance response: {final_url}")
            return raw, final_url
        except urllib.error.HTTPError as exc:
            if exc.code not in retryable:
                raise
            last_error = exc
        except urllib.error.URLError as exc:
            last_error = exc
        if attempt < 2:
            time.sleep(float(attempt + 1))
    if last_error is None:
        raise RuntimeError(f"Binance request failed without an error: {url}")
    raise last_error


def month_ids() -> list[str]:
    return [str(value) for value in pd.period_range("2023-04", "2025-12", freq="M")]


def month_grid(month: str) -> pd.DatetimeIndex:
    period = pd.Period(month, freq="M")
    start = period.start_time.tz_localize("UTC")
    end = period.end_time.floor("h").tz_localize("UTC")
    return pd.date_range(start, end, freq="h")


def parse_checksum(raw: bytes, filename: str) -> str:
    try:
        parts = raw.decode("ascii").strip().split()
    except UnicodeDecodeError as exc:
        raise ValueError(f"{filename}: checksum is not ASCII") from exc
    if len(parts) < 2:
        raise ValueError(f"{filename}: malformed checksum response")
    digest = parts[0].lower()
    declared_name = parts[-1].lstrip("*")
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError(f"{filename}: malformed checksum digest")
    if declared_name != filename:
        raise ValueError(f"{filename}: checksum filename mismatch")
    return digest


def parse_binance_timestamp(raw: str, label: str) -> pd.Timestamp:
    integer = int(raw)
    if integer > 10**14:
        unit = "us"
        divisor = 3_600_000_000
    else:
        unit = "ms"
        divisor = 3_600_000
    if integer % divisor != 0:
        raise ValueError(f"{label}: timestamp is not on the 1H grid")
    return pd.to_datetime(integer, unit=unit, utc=True)


def parse_binance_zip(raw: bytes, filename: str, month: str) -> pd.DataFrame:
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise ValueError(f"{filename}: invalid ZIP") from exc
    expected_csv = filename.removesuffix(".zip") + ".csv"
    members = [name for name in archive.namelist() if not name.endswith("/")]
    if members != [expected_csv]:
        raise ValueError(f"{filename}: unexpected archive members {members}")
    rows: list[tuple[pd.Timestamp, float, float, float, float]] = []
    with archive.open(expected_csv) as handle:
        reader = csv.reader(io.TextIOWrapper(handle, encoding="utf-8", newline=""))
        for row_number, row in enumerate(reader, 1):
            if not row:
                continue
            if len(row) != 12:
                raise ValueError(f"{filename}: row {row_number} has {len(row)} columns")
            try:
                timestamp = parse_binance_timestamp(row[0], filename)
            except ValueError:
                if row_number == 1 and "open" in row[0].lower():
                    continue
                raise
            try:
                open_px, high, low, close = map(float, (row[1], row[2], row[3], row[4]))
            except ValueError as exc:
                raise ValueError(f"{filename}: nonnumeric OHLC") from exc
            values = np.asarray([open_px, high, low, close], dtype=float)
            if not np.isfinite(values).all() or np.any(values <= 0):
                raise ValueError(f"{filename}: nonfinite or nonpositive OHLC")
            if high < max(open_px, low, close) or low > min(open_px, high, close):
                raise ValueError(f"{filename}: invalid OHLC ordering")
            rows.append((timestamp, open_px, high, low, close))
    frame = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close"])
    frame = frame.set_index("timestamp").sort_index()
    expected = month_grid(month)
    if frame.index.has_duplicates or len(frame) != len(expected) or not frame.index.equals(expected):
        raise ValueError(f"{filename}: exact monthly UTC 1H grid mismatch")
    return frame


def acquire_binance(symbol: str, source_dir: Path, *, repeat: bool) -> tuple[pd.DataFrame, dict[str, object]]:
    frames: list[pd.DataFrame] = []
    monthly: list[dict[str, object]] = []
    for month in month_ids():
        filename = f"{symbol}-1h-{month}.zip"
        base = f"{BINANCE_ROOT}/{symbol}/1h/{filename}"
        checksum_raw, checksum_url = trusted_binance_get(base + ".CHECKSUM")
        zip_raw, zip_url = trusted_binance_get(base)
        declared = parse_checksum(checksum_raw, filename)
        observed = sha256(zip_raw)
        if declared != observed:
            raise ValueError(f"{filename}: ZIP checksum mismatch")
        frame = parse_binance_zip(zip_raw, filename, month)
        frames.append(frame)
        monthly.append(
            {
                "month": month,
                "zip_url": zip_url,
                "checksum_url": checksum_url,
                "zip_sha256": observed,
                "checksum_response_sha256": sha256(checksum_raw),
                "rows": len(frame),
            }
        )
        time.sleep(0.02)
    combined = pd.concat(frames).sort_index()
    expected = pd.date_range(START, END, freq="h")
    if combined.index.has_duplicates or len(combined) != EXPECTED_ROWS or not combined.index.equals(expected):
        raise ValueError(f"{symbol}: complete Binance 24,144H grid mismatch")
    normalized = canonical_frame_bytes(combined)
    if not repeat:
        (source_dir / f"binance-spot-{symbol}-1h.csv").write_bytes(normalized)
    return combined, {
        "provider": "Binance Public Data",
        "market_type": "SPOT",
        "instrument": symbol,
        "bar": "1H",
        "rows": len(combined),
        "start": str(combined.index[0]),
        "end": str(combined.index[-1]),
        "normalized_sha256": sha256(normalized),
        "training_prefix_sha256": sha256(canonical_frame_bytes(combined.iloc[:TRAIN_END])),
        "month_count": len(monthly),
        "months": monthly,
    }


def acquire_okx(inst_id: str, source_dir: Path, *, repeat: bool) -> tuple[pd.DataFrame, dict[str, object]]:
    snapshot = fetch_okx_one_hour_candles(
        inst_id=inst_id,
        start=START,
        end=END,
        pause_seconds=0.12,
        timeout=30.0,
    )
    frame = snapshot.candles.copy()
    expected = pd.date_range(START, END, freq="h")
    if frame.index.has_duplicates or len(frame) != EXPECTED_ROWS or not frame.index.equals(expected):
        raise ValueError(f"{inst_id}: complete OKX 24,144H grid mismatch")
    if not (frame["confirm"].astype(str) == "1").all():
        raise ValueError(f"{inst_id}: unconfirmed OKX candle inside frozen interval")
    normalized = _canonical_csv_bytes(frame)
    raw_pages = _canonical_json_bytes(snapshot.raw_pages)
    metadata = _canonical_json_bytes(snapshot.metadata)
    if not repeat:
        stem = source_dir / f"okx-spot-{inst_id}-1h"
        stem.with_suffix(".csv").write_bytes(normalized)
        Path(str(stem) + ".raw.json").write_bytes(raw_pages)
        Path(str(stem) + ".metadata.json").write_bytes(metadata)
    return frame, {
        "provider": "OKX",
        "market_type": "SPOT",
        "instrument": inst_id,
        "bar": "1H",
        "rows": len(frame),
        "start": str(frame.index[0]),
        "end": str(frame.index[-1]),
        "normalized_sha256": sha256(normalized),
        "training_prefix_sha256": sha256(_canonical_csv_bytes(frame.iloc[:TRAIN_END])),
        "raw_pages_sha256": sha256(raw_pages),
        "metadata_sha256": sha256(metadata),
        "pages": snapshot.metadata.get("pages"),
        "pagination_complete": snapshot.metadata.get("pagination_complete"),
        "missing_intervals": snapshot.metadata.get("missing_intervals"),
    }


def anchors() -> list[int]:
    return [t for t in range(TRAIN_START, TRAIN_END, 24) if t + 25 < TRAIN_END]


def coherence(okx_returns: np.ndarray, binance_returns: np.ndarray) -> float:
    if len(okx_returns) != len(binance_returns) or len(okx_returns) == 0:
        return float("nan")
    if not np.isfinite(okx_returns).all() or not np.isfinite(binance_returns).all():
        return float("nan")
    d = float(np.mean((okx_returns - binance_returns) ** 2))
    e = float(np.mean(okx_returns**2 + binance_returns**2))
    if not math.isfinite(d) or not math.isfinite(e) or d < 0 or e <= 0:
        return float("nan")
    return float(1.0 - d / e)


def opportunity_frame(okx_frame: pd.DataFrame, binance_frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    if not okx_frame.index.equals(binance_frame.index):
        raise ValueError("OKX/Binance source calendars differ")
    okx_close = okx_frame["close"].to_numpy(float)
    binance_close = binance_frame["close"].to_numpy(float)
    okx_open = okx_frame["open"].to_numpy(float)
    r_okx = np.full(len(okx_close), np.nan, dtype=float)
    r_binance = np.full(len(binance_close), np.nan, dtype=float)
    r_okx[1:] = np.diff(np.log(okx_close))
    r_binance[1:] = np.diff(np.log(binance_close))
    rows: list[dict[str, object]] = []
    algebra_errors: list[float] = []
    scale_errors: list[float] = []
    identical_errors: list[float] = []
    for t in anchors():
        margin = float(okx_close[t - 25] / okx_close[t - 2185] - 1.0)
        if margin <= 0:
            continue
        recent_o = r_okx[t - 192 : t - 24]
        recent_b = r_binance[t - 192 : t - 24]
        baseline_o = r_okx[t - 912 : t - 192]
        baseline_b = r_binance[t - 912 : t - 192]
        if len(recent_o) != 168 or len(baseline_o) != 720:
            raise ValueError("coherence window length mismatch")
        c_recent = coherence(recent_o, recent_b)
        c_baseline = coherence(baseline_o, baseline_b)
        feature = c_recent - c_baseline
        if not all(math.isfinite(value) for value in (c_recent, c_baseline, feature)):
            continue
        d_recent = float(np.mean((recent_o - recent_b) ** 2))
        e_recent = float(np.mean(recent_o**2 + recent_b**2))
        replay = float(1.0 - d_recent / e_recent)
        algebra_errors.append(abs(c_recent - replay))
        identical_errors.append(abs(coherence(recent_o, recent_o) - 1.0))
        # Multiplicative price-scale invariance is exact in log-return space. Replay it
        # from independently scaled positive close arrays rather than asserting it.
        scaled_o = np.log((okx_close * 7.0)[1:] / (okx_close * 7.0)[:-1])
        scaled_b = np.log((binance_close * 11.0)[1:] / (binance_close * 11.0)[:-1])
        scaled_recent_o = scaled_o[t - 193 : t - 25]
        scaled_recent_b = scaled_b[t - 193 : t - 25]
        scale_errors.append(abs(c_recent - coherence(scaled_recent_o, scaled_recent_b)))
        entry = float(okx_open[t])
        gross = float(okx_open[t + 24] / entry - 1.0)
        net = gross - ROUND_TRIP_FEE
        adverse = float(np.min(okx_open[t : t + 25] / entry - 1.0))
        delayed_entry = float(okx_open[t + 1])
        delayed_gross = float(okx_open[t + 25] / delayed_entry - 1.0)
        delayed_net = delayed_gross - ROUND_TRIP_FEE
        delayed_adverse = float(np.min(okx_open[t + 1 : t + 26] / delayed_entry - 1.0))
        rows.append(
            {
                "t": t,
                "timestamp": str(okx_frame.index[t]),
                "feature": feature,
                "coherence_recent": c_recent,
                "coherence_baseline": c_baseline,
                "e2160_margin": margin,
                "gross": gross,
                "net": net,
                "adverse": adverse,
                "delay_net": delayed_net,
                "delay_adverse": delayed_adverse,
            }
        )
    structural = {
        "common_timestamp_identity": True,
        "recent_return_count": 168,
        "baseline_return_count": 720,
        "latest_information_offset_hours": -25,
        "coherence_algebra_max_abs_error": max(algebra_errors) if algebra_errors else None,
        "identical_return_coherence_max_abs_error": max(identical_errors) if identical_errors else None,
        "price_scale_invariance_max_abs_error": max(scale_errors) if scale_errors else None,
        "coherence_algebra_pass": bool(algebra_errors) and max(algebra_errors) <= 1e-15,
        "identical_return_coherence_pass": bool(identical_errors) and max(identical_errors) <= 1e-15,
        "price_scale_invariance_pass": bool(scale_errors) and max(scale_errors) <= 1e-12,
    }
    return pd.DataFrame(rows), structural


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    rx = pd.Series(x).rank(method="average").to_numpy(float)
    ry = pd.Series(y).rank(method="average").to_numpy(float)
    if np.std(rx) == 0 or np.std(ry) == 0:
        return float("nan")
    return float(np.corrcoef(rx, ry)[0, 1])


def standardized_slope(x: np.ndarray, y: np.ndarray) -> float:
    sd = float(np.std(x, ddof=0))
    if not math.isfinite(sd) or sd <= 0:
        return float("nan")
    z = (x - float(np.mean(x))) / sd
    denominator = float(np.dot(z - np.mean(z), z - np.mean(z)))
    if denominator <= 0:
        return float("nan")
    return float(np.dot(z - np.mean(z), y - np.mean(y)) / denominator)


def tercile_effect(x: np.ndarray, y: np.ndarray) -> float:
    order = np.argsort(x, kind="mergesort")
    k = len(order) // 3
    if k < 1:
        return float("nan")
    return float(np.mean(y[order[-k:]]) - np.mean(y[order[:k]]))


def triple(x: np.ndarray, y: np.ndarray) -> dict[str, float]:
    return {
        "rho": spearman(x, y),
        "slope": standardized_slope(x, y),
        "tercile": tercile_effect(x, y),
    }


def bootstrap_intervals(inst_id: str, x: np.ndarray, net: np.ndarray, adverse: np.ndarray) -> dict[str, list[float]]:
    n = len(x)
    starts = np.arange(0, n - BOOTSTRAP_BLOCK + 1)
    if len(starts) < 1:
        raise ValueError("insufficient opportunities for moving-block bootstrap")
    rng = np.random.default_rng(BOOTSTRAP_SEEDS[inst_id])
    blocks_needed = math.ceil(n / BOOTSTRAP_BLOCK)
    draws: dict[str, list[float]] = {
        "net_rho": [],
        "net_slope": [],
        "adverse_rho": [],
        "adverse_slope": [],
    }
    for _ in range(BOOTSTRAP_DRAWS):
        indices: list[int] = []
        for start in rng.choice(starts, size=blocks_needed, replace=True):
            indices.extend(range(int(start), int(start) + BOOTSTRAP_BLOCK))
        index = np.asarray(indices[:n], dtype=int)
        draws["net_rho"].append(spearman(x[index], net[index]))
        draws["net_slope"].append(standardized_slope(x[index], net[index]))
        draws["adverse_rho"].append(spearman(x[index], adverse[index]))
        draws["adverse_slope"].append(standardized_slope(x[index], adverse[index]))
    return {
        key: [float(np.quantile(values, 0.025)), float(np.quantile(values, 0.975))]
        for key, values in draws.items()
    }


def fold_stats(frame: pd.DataFrame) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for fold_number, index in enumerate(np.array_split(np.arange(len(frame)), 4), 1):
        sub = frame.iloc[index]
        x = sub["feature"].to_numpy(float)
        output.append(
            {
                "fold": fold_number,
                "rows": len(sub),
                "start": sub["timestamp"].iloc[0],
                "end": sub["timestamp"].iloc[-1],
                "net_slope": standardized_slope(x, sub["net"].to_numpy(float)),
                "adverse_slope": standardized_slope(x, sub["adverse"].to_numpy(float)),
            }
        )
    return output


def margin_strata(frame: pd.DataFrame) -> dict[str, object]:
    median = float(frame["e2160_margin"].median())
    output: dict[str, object] = {"median_margin": median}
    for name, mask in {
        "lower_or_equal": frame["e2160_margin"] <= median,
        "upper": frame["e2160_margin"] > median,
    }.items():
        sub = frame.loc[mask]
        x = sub["feature"].to_numpy(float)
        output[name] = {
            "rows": len(sub),
            "net_tercile": tercile_effect(x, sub["net"].to_numpy(float)),
            "adverse_tercile": tercile_effect(x, sub["adverse"].to_numpy(float)),
        }
    return output


def summarize(inst_id: str, frame: pd.DataFrame, prefix: pd.DataFrame, structural: dict[str, object], prefix_structural: dict[str, object]) -> dict[str, object]:
    if len(frame) != len(prefix) or not frame["t"].equals(prefix["t"]):
        raise ValueError(f"{inst_id}: opportunity membership prefix mismatch")
    numeric = [
        "feature",
        "coherence_recent",
        "coherence_baseline",
        "e2160_margin",
        "gross",
        "net",
        "adverse",
        "delay_net",
        "delay_adverse",
    ]
    if not np.allclose(frame[numeric].to_numpy(float), prefix[numeric].to_numpy(float), rtol=0, atol=1e-14):
        raise ValueError(f"{inst_id}: feature/label prefix mismatch")
    if structural != prefix_structural:
        raise ValueError(f"{inst_id}: structural prefix mismatch")
    x = frame["feature"].to_numpy(float)
    net = frame["net"].to_numpy(float)
    adverse = frame["adverse"].to_numpy(float)
    delay_net = frame["delay_net"].to_numpy(float)
    delay_adverse = frame["delay_adverse"].to_numpy(float)
    distinct = int(pd.Series(x).nunique())
    iqr = float(np.quantile(x, 0.75) - np.quantile(x, 0.25))
    net_stats = triple(x, net)
    adverse_stats = triple(x, adverse)
    delay_net_stats = triple(x, delay_net)
    delay_adverse_stats = triple(x, delay_adverse)
    intervals = bootstrap_intervals(inst_id, x, net, adverse)
    folds = fold_stats(frame)
    positive_net = [max(0.0, float(item["net_slope"])) for item in folds]
    positive_net_sum = sum(positive_net)
    concentration = max(positive_net) / positive_net_sum if positive_net_sum > 0 else None
    positive_net_folds = sum(float(item["net_slope"]) > 0 for item in folds)
    positive_adverse_folds = sum(float(item["adverse_slope"]) > 0 for item in folds)
    strata = margin_strata(frame)
    outer_count = len(frame) // 3
    structural_pass = all(
        bool(structural[key])
        for key in (
            "coherence_algebra_pass",
            "identical_return_coherence_pass",
            "price_scale_invariance_pass",
        )
    ) and structural["latest_information_offset_hours"] == -25
    gates = {
        "opportunities_ge_180": len(frame) >= 180,
        "feature_support": distinct >= 100 and iqr > 0 and outer_count >= 50,
        "net_direction_positive": all(net_stats[key] > 0 for key in ("rho", "slope", "tercile")),
        "adverse_direction_positive": all(adverse_stats[key] > 0 for key in ("rho", "slope", "tercile")),
        "dependence_lower_bounds_positive": all(intervals[key][0] > 0 for key in intervals),
        "temporal_breadth": positive_net_folds >= 3 and positive_adverse_folds >= 3,
        "positive_net_fold_concentration_le_60pct": concentration is not None and concentration <= 0.60,
        "margin_strata": all(
            float(strata[name][endpoint]) > 0
            for name in ("lower_or_equal", "upper")
            for endpoint in ("net_tercile", "adverse_tercile")
        ),
        "plus_1h_transport": all(value > 0 for value in delay_net_stats.values())
        and all(value > 0 for value in delay_adverse_stats.values()),
        "structural_checks": structural_pass,
        "prefix_invariance": True,
    }
    return {
        "opportunities": len(frame),
        "feature_distribution": {
            "distinct": distinct,
            "iqr": iqr,
            "min": float(np.min(x)),
            "max": float(np.max(x)),
            "mean": float(np.mean(x)),
            "median": float(np.median(x)),
        },
        "outer_tercile_rows_each": outer_count,
        "unconditional_net_label": {
            "mean": float(np.mean(net)),
            "median": float(np.median(net)),
            "positive_fraction": float(np.mean(net > 0)),
        },
        "net_rho": net_stats["rho"],
        "net_slope": net_stats["slope"],
        "net_tercile_effect": net_stats["tercile"],
        "adverse_rho": adverse_stats["rho"],
        "adverse_slope": adverse_stats["slope"],
        "adverse_tercile_effect": adverse_stats["tercile"],
        "bootstrap_95": intervals,
        "folds": folds,
        "positive_net_folds": positive_net_folds,
        "positive_adverse_folds": positive_adverse_folds,
        "positive_net_fold_concentration": concentration,
        "margin_strata": strata,
        "one_hour_delay": {
            "net_rho": delay_net_stats["rho"],
            "net_slope": delay_net_stats["slope"],
            "net_tercile_effect": delay_net_stats["tercile"],
            "adverse_rho": delay_adverse_stats["rho"],
            "adverse_slope": delay_adverse_stats["slope"],
            "adverse_tercile_effect": delay_adverse_stats["tercile"],
        },
        "structural": structural,
        "gates": gates,
        "all_training_gates_pass": all(gates.values()),
    }


def null_strategy_metrics() -> dict[str, None]:
    return {
        "training_return": None,
        "training_sharpe": None,
        "oos_return": None,
        "oos_sharpe": None,
        "full_return": None,
        "full_sharpe": None,
        "benchmark_comparison": None,
        "turnover": None,
        "modeled_fee_drag": None,
        "maximum_drawdown": None,
        "edge_per_turnover": None,
        "fold_year_strategy_breadth": None,
    }


def write_outputs(payload: dict[str, object]) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    evidence = OUTPUT / "evidence.json"
    report = OUTPUT / "report.md"
    evidence.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
    lines = [
        "# Cross-venue spot return coherence — frozen 1H training diagnostic",
        "",
        f"Family: `{FAMILY_ID}`",
        f"Code head: `{payload['code_head']}`",
        f"Candidate/grid: `{payload['candidate_count']} / {payload['parameter_grid_count']}`",
        f"Source contract passed: `{payload['source_contract_passed']}`",
        f"Sealed OOS accessed: `{payload['sealed_oos_accessed']}`",
        "",
    ]
    if payload.get("source_error"):
        lines.extend(["## Source failure", "", f"`{payload['source_error']}`", ""])
    for inst_id, result in payload.get("targets", {}).items():
        lines.extend(
            [
                f"## {inst_id}",
                "",
                f"- opportunities: {result['opportunities']}",
                f"- feature distinct / IQR: {result['feature_distribution']['distinct']} / {result['feature_distribution']['iqr']:.10f}",
                f"- net rho / slope / tercile: {result['net_rho']:+.6f} / {result['net_slope']:+.6f} / {10000 * result['net_tercile_effect']:+.2f} bp",
                f"- adverse rho / slope / tercile: {result['adverse_rho']:+.6f} / {result['adverse_slope']:+.6f} / {10000 * result['adverse_tercile_effect']:+.2f} bp",
                f"- positive folds net / adverse: {result['positive_net_folds']}/4 / {result['positive_adverse_folds']}/4",
                f"- positive-net fold concentration: {result['positive_net_fold_concentration']}",
                f"- all training gates pass: {result['all_training_gates_pass']}",
                "",
            ]
        )
    lines.extend(["## Verdict", "", f"`{payload['verdict']}`", ""])
    report.write_text("\n".join(lines))
    manifest = {
        "family_id": FAMILY_ID,
        "evidence_sha256": sha256(evidence.read_bytes()),
        "report_sha256": sha256(report.read_bytes()),
    }
    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    source_dir = OUTPUT / "sources"
    source_dir.mkdir(exist_ok=True)
    code_head = os.environ.get("RESEARCH_HEAD_SHA", "unknown")
    sources: dict[str, object] = {}
    source_error: str | None = None
    source_contract_passed = False
    target_returns_accessed = False
    targets: dict[str, object] = {}
    okx_panels: dict[str, pd.DataFrame] = {}
    binance_panels: dict[str, pd.DataFrame] = {}

    try:
        for okx_id, binance_id in TARGETS.items():
            first, meta = acquire_binance(binance_id, source_dir, repeat=False)
            second, repeat_meta = acquire_binance(binance_id, source_dir, repeat=True)
            if canonical_frame_bytes(first) != canonical_frame_bytes(second):
                raise ValueError(f"{binance_id}: repeated Binance normalized acquisition mismatch")
            meta["repeat_normalized_sha256"] = repeat_meta["normalized_sha256"]
            meta["repeat_identity_passed"] = meta["normalized_sha256"] == repeat_meta["normalized_sha256"]
            if not meta["repeat_identity_passed"]:
                raise ValueError(f"{binance_id}: repeated Binance hash mismatch")
            binance_panels[okx_id] = first
            sources[f"binance:{binance_id}"] = meta

        for okx_id in TARGETS:
            first, meta = acquire_okx(okx_id, source_dir, repeat=False)
            second, repeat_meta = acquire_okx(okx_id, source_dir, repeat=True)
            if _canonical_csv_bytes(first) != _canonical_csv_bytes(second):
                raise ValueError(f"{okx_id}: repeated OKX normalized acquisition mismatch")
            meta["repeat_normalized_sha256"] = repeat_meta["normalized_sha256"]
            meta["repeat_identity_passed"] = meta["normalized_sha256"] == repeat_meta["normalized_sha256"]
            if not meta["repeat_identity_passed"]:
                raise ValueError(f"{okx_id}: repeated OKX hash mismatch")
            if not first.index.equals(binance_panels[okx_id].index):
                raise ValueError(f"{okx_id}: OKX/Binance common calendar mismatch")
            okx_panels[okx_id] = first
            sources[f"okx:{okx_id}"] = meta
        source_contract_passed = True
    except Exception as exc:
        source_error = f"{type(exc).__name__}: {exc}"

    if source_contract_passed:
        target_returns_accessed = True
        for okx_id in TARGETS:
            full, structural = opportunity_frame(okx_panels[okx_id], binance_panels[okx_id])
            prefix_okx = okx_panels[okx_id].iloc[:TRAIN_END].copy()
            prefix_binance = binance_panels[okx_id].iloc[:TRAIN_END].copy()
            prefix, prefix_structural = opportunity_frame(prefix_okx, prefix_binance)
            targets[okx_id] = summarize(okx_id, full, prefix, structural, prefix_structural)

    bilateral = source_contract_passed and len(targets) == 2 and all(
        bool(result["all_training_gates_pass"]) for result in targets.values()
    )
    verdict = SUPPORT if bilateral else REJECT
    payload: dict[str, object] = {
        "schema_version": "cross-venue-spot-coherence-1h-v1",
        "family_id": FAMILY_ID,
        "code_head": code_head,
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "bar": "1H",
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "fixed_targets": list(TARGETS),
        "fixed_exogenous_map": TARGETS,
        "source_window": {"start": START, "end": END, "rows_per_arm": EXPECTED_ROWS},
        "training": {"start_index": TRAIN_START, "end_index_exclusive": TRAIN_END, "step_hours": 24},
        "sealed_oos": {"start_index": OOS_START, "end_index_exclusive": OOS_END},
        "unread_suffix": {"start_index": OOS_END, "end_index_exclusive": SOURCE_END},
        "feature": {
            "definition": "C(recent168)-C(baseline720), C=1-mean((rOKX-rBinance)^2)/mean(rOKX^2+rBinance^2)",
            "recent_return_count": 168,
            "baseline_return_count": 720,
            "latest_information_offset_hours": -25,
            "fixed_sign": "positive",
        },
        "eligibility": "OKX close[t-25] > OKX close[t-2185]",
        "fee_bps_one_way": 5.0,
        "round_trip_label_bps": 10.0,
        "bootstrap_draws": BOOTSTRAP_DRAWS,
        "bootstrap_block_opportunities": BOOTSTRAP_BLOCK,
        "bootstrap_seeds": BOOTSTRAP_SEEDS,
        "source_contract_passed": source_contract_passed,
        "source_error": source_error,
        "sources": sources,
        "target_returns_accessed": target_returns_accessed,
        "sealed_oos_accessed": False,
        "target_oos_accessed": False,
        "unread_suffix_used_in_feature_or_label": False,
        "strategy_performance_accessed": False,
        "strategy_metrics": null_strategy_metrics(),
        "targets": targets,
        "bilateral_training_pass": bilateral,
        "canonical_mutation": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "verdict": verdict,
    }
    write_outputs(payload)
    print(json.dumps({"source_contract_passed": source_contract_passed, "bilateral_training_pass": bilateral, "verdict": verdict, "source_error": source_error}, sort_keys=True))


if __name__ == "__main__":
    main()
