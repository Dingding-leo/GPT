from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import time
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import pandas as pd

from gpt_quant.okx_1h import fetch_okx_one_hour_candles

FAMILY_ID = "causal-same-asset-perpetual-taker-flow-absorption-opportunity-1h-v1"
START = "2023-04-01T00:00:00Z"
END = "2025-12-31T23:00:00Z"
EXPECTED_ROWS = 24_144
TRAIN_START = 2_208
TRAIN_END = 10_800
OOS_END = 23_760
SOURCE_END = 24_144
FEE_ONE_WAY = 0.0005
ROUND_TRIP_FEE = 0.0010
E2160_HOURS = 2_160
BASELINE_HOURS = 720
RECENT_HOURS = 168
SAFETY_LAG = 24
BOOTSTRAP_DRAWS = 5_000
BOOTSTRAP_BLOCK = 7
BOOTSTRAP_SEED = 2026080818
BINANCE_ROOT = "https://data.binance.vision/data/futures/um/monthly/klines"
OUTPUT = Path("reports/research/perpetual-taker-flow-absorption-1h-v1")
TARGETS = {
    "SOL-USDT": "SOLUSDT",
    "XRP-USDT": "XRPUSDT",
}
REJECT = "reject_causal_same_asset_perpetual_taker_flow_absorption_information_premise_1h_v1"
SOURCE_REJECT = "reject_causal_same_asset_perpetual_taker_flow_absorption_source_contract_1h_v1"
SUPPORT = "support_causal_same_asset_perpetual_taker_flow_absorption_for_separate_candidate_predeclaration_1h_v1"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_frame_bytes(frame: pd.DataFrame) -> bytes:
    return frame.reset_index(names="timestamp").to_csv(
        index=False,
        date_format="%Y-%m-%dT%H:%M:%SZ",
        float_format="%.17g",
        lineterminator="\n",
    ).encode()


def _trusted_get(url: str, timeout: float = 30.0) -> tuple[bytes, str]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "data.binance.vision":
        raise ValueError(f"Binance archive URL outside frozen host: {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "gpt-quant-research/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
        final_url = response.geturl()
    final = urlparse(final_url)
    if final.scheme != "https" or final.hostname != "data.binance.vision":
        raise ValueError(f"Binance archive redirect left frozen host: {final_url}")
    if not raw:
        raise ValueError(f"empty Binance archive response: {url}")
    return raw, final_url


def _months() -> list[str]:
    return [str(period) for period in pd.period_range("2023-04", "2025-12", freq="M")]


def _parse_checksum(raw: bytes, expected_name: str) -> str:
    try:
        text = raw.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise ValueError(f"{expected_name}: checksum is not ASCII") from exc
    parts = text.split()
    if len(parts) < 2:
        raise ValueError(f"{expected_name}: malformed checksum")
    digest = parts[0].lower()
    filename = parts[-1].lstrip("*")
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError(f"{expected_name}: invalid checksum digest")
    if filename != expected_name:
        raise ValueError(f"{expected_name}: checksum filename mismatch: {filename}")
    return digest


def _month_grid(month: str) -> pd.DatetimeIndex:
    period = pd.Period(month, freq="M")
    start = period.start_time.tz_localize("UTC")
    end = (period.end_time.floor("h")).tz_localize("UTC")
    return pd.date_range(start, end, freq="h")


def _parse_binance_zip(raw: bytes, expected_name: str, month: str) -> pd.DataFrame:
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise ValueError(f"{expected_name}: invalid ZIP") from exc
    names = [name for name in archive.namelist() if not name.endswith("/")]
    expected_csv = expected_name.removesuffix(".zip") + ".csv"
    if names != [expected_csv]:
        raise ValueError(f"{expected_name}: unexpected ZIP members {names}")
    rows: list[tuple[pd.Timestamp, float, float, float, float, float, float]] = []
    with archive.open(expected_csv) as handle:
        reader = csv.reader(io.TextIOWrapper(handle, encoding="utf-8", newline=""))
        for row_number, row in enumerate(reader, start=1):
            if not row:
                continue
            if len(row) != 12:
                raise ValueError(f"{expected_name}: row {row_number} has {len(row)} columns")
            try:
                open_time = int(row[0])
            except ValueError:
                if row_number == 1 and "open" in row[0].strip().lower():
                    continue
                raise ValueError(f"{expected_name}: invalid open time on row {row_number}")
            if open_time % 3_600_000 != 0:
                raise ValueError(f"{expected_name}: off-grid millisecond open time")
            timestamp = pd.to_datetime(open_time, unit="ms", utc=True)
            try:
                open_price = float(row[1])
                high = float(row[2])
                low = float(row[3])
                close = float(row[4])
                quote_volume = float(row[7])
                taker_buy_quote = float(row[10])
            except ValueError as exc:
                raise ValueError(f"{expected_name}: non-numeric kline field") from exc
            values = np.asarray(
                [open_price, high, low, close, quote_volume, taker_buy_quote], dtype=float
            )
            if not np.isfinite(values).all():
                raise ValueError(f"{expected_name}: non-finite kline field")
            if min(open_price, high, low, close) <= 0:
                raise ValueError(f"{expected_name}: non-positive OHLC")
            if high < max(open_price, low, close) or low > min(open_price, high, close):
                raise ValueError(f"{expected_name}: invalid OHLC ordering")
            if quote_volume < 0 or taker_buy_quote < -1e-12:
                raise ValueError(f"{expected_name}: negative quote volume")
            tolerance = max(1e-9, abs(quote_volume) * 1e-10)
            if taker_buy_quote - quote_volume > tolerance:
                raise ValueError(f"{expected_name}: taker-buy quote exceeds quote volume")
            rows.append(
                (
                    timestamp,
                    open_price,
                    high,
                    low,
                    close,
                    quote_volume,
                    max(0.0, min(taker_buy_quote, quote_volume)),
                )
            )
    frame = pd.DataFrame(
        rows,
        columns=[
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "quote_volume",
            "taker_buy_quote_volume",
        ],
    ).set_index("timestamp")
    if frame.index.has_duplicates:
        raise ValueError(f"{expected_name}: duplicate open time")
    frame = frame.sort_index()
    expected_grid = _month_grid(month)
    if len(frame) != len(expected_grid) or not frame.index.equals(expected_grid):
        raise ValueError(
            f"{expected_name}: month grid mismatch; expected {len(expected_grid)}, got {len(frame)}"
        )
    return frame


def _acquire_binance(symbol: str, source_dir: Path) -> tuple[pd.DataFrame, dict[str, object]]:
    frames: list[pd.DataFrame] = []
    months: list[dict[str, object]] = []
    for month in _months():
        filename = f"{symbol}-1h-{month}.zip"
        url = f"{BINANCE_ROOT}/{symbol}/1h/{filename}"
        checksum_url = url + ".CHECKSUM"
        checksum_raw, checksum_final = _trusted_get(checksum_url)
        zip_raw, zip_final = _trusted_get(url)
        declared = _parse_checksum(checksum_raw, filename)
        observed = _sha(zip_raw)
        if declared != observed:
            raise ValueError(f"{filename}: checksum mismatch")
        frame = _parse_binance_zip(zip_raw, filename, month)
        checksum_path = source_dir / f"{filename}.CHECKSUM"
        checksum_path.write_bytes(checksum_raw)
        frames.append(frame)
        months.append(
            {
                "month": month,
                "zip_url": zip_final,
                "checksum_url": checksum_final,
                "zip_sha256": observed,
                "checksum_sha256": _sha(checksum_raw),
                "rows": len(frame),
                "start": str(frame.index[0]),
                "end": str(frame.index[-1]),
            }
        )
        time.sleep(0.03)
    combined = pd.concat(frames).sort_index()
    expected = pd.date_range(START, END, freq="h")
    if combined.index.has_duplicates:
        raise ValueError(f"{symbol}: duplicate hours across monthly archives")
    if len(combined) != EXPECTED_ROWS or not combined.index.equals(expected):
        raise ValueError(f"{symbol}: combined Binance grid mismatch")
    canonical = _canonical_frame_bytes(combined)
    (source_dir / f"binance-{symbol}-1h.csv").write_bytes(canonical)
    return combined, {
        "provider": "Binance Public Data",
        "market": "USD-M futures perpetual",
        "symbol": symbol,
        "bar": "1h",
        "rows": len(combined),
        "start": str(combined.index[0]),
        "end": str(combined.index[-1]),
        "normalized_sha256": _sha(canonical),
        "training_prefix_sha256": _sha(_canonical_frame_bytes(combined.iloc[:TRAIN_END])),
        "month_count": len(months),
        "months": months,
        "passed": True,
    }


def _acquire_okx(inst: str, source_dir: Path) -> tuple[pd.DataFrame, dict[str, object]]:
    def fetch() -> object:
        return fetch_okx_one_hour_candles(
            inst_id=inst,
            start=START,
            end=END,
            limit=100,
            pause_seconds=0.08,
            timeout=20.0,
            safety_pages=64,
        )

    first = fetch()
    second = fetch()
    frame = first.candles.copy()
    repeat = second.candles.copy()
    frame.columns = [str(column).lower() for column in frame.columns]
    repeat.columns = [str(column).lower() for column in repeat.columns]
    expected = pd.date_range(START, END, freq="h")
    if len(frame) != EXPECTED_ROWS or not frame.index.equals(expected):
        raise ValueError(f"{inst}: OKX source does not match exact frozen grid")
    if not frame.equals(repeat):
        raise ValueError(f"{inst}: repeated OKX acquisition differs")
    prices = frame[["open", "high", "low", "close"]].to_numpy(float)
    if not np.isfinite(prices).all() or not (prices > 0).all():
        raise ValueError(f"{inst}: invalid OKX OHLC")
    if not (frame["high"] >= frame[["open", "close", "low"]].max(axis=1)).all():
        raise ValueError(f"{inst}: invalid OKX high")
    if not (frame["low"] <= frame[["open", "close", "high"]].min(axis=1)).all():
        raise ValueError(f"{inst}: invalid OKX low")
    if first.metadata.get("instrument_id") != inst or first.metadata.get("bar") != "1H":
        raise ValueError(f"{inst}: OKX source identity mismatch")
    if first.metadata.get("missing_intervals") not in (0, None):
        raise ValueError(f"{inst}: OKX missing intervals")
    canonical = _canonical_frame_bytes(frame)
    repeat_canonical = _canonical_frame_bytes(repeat)
    if _sha(canonical) != _sha(repeat_canonical):
        raise ValueError(f"{inst}: repeated OKX normalized hash differs")
    metadata_hash = str(first.metadata.get("normalized_csv_sha256"))
    if metadata_hash and metadata_hash != "None" and metadata_hash != _sha(canonical):
        raise ValueError(f"{inst}: OKX metadata normalized hash mismatch")
    (source_dir / f"okx-{inst}-1h.csv").write_bytes(canonical)
    return frame, {
        "provider": "anonymous public OKX SPOT history-candles",
        "instrument": inst,
        "bar": "1H",
        "rows": len(frame),
        "start": str(frame.index[0]),
        "end": str(frame.index[-1]),
        "normalized_sha256": _sha(canonical),
        "training_prefix_sha256": _sha(_canonical_frame_bytes(frame.iloc[:TRAIN_END])),
        "repeat_identity": True,
        "passed": True,
    }


def _absorption_frame(frame: pd.DataFrame) -> pd.DataFrame:
    quote = frame["quote_volume"].to_numpy(float)
    taker = frame["taker_buy_quote_volume"].to_numpy(float)
    pressure = np.zeros(len(frame), dtype=float)
    positive = quote > 0
    pressure[positive] = 2.0 * taker[positive] / quote[positive] - 1.0
    width = (frame["high"] - frame["low"]).to_numpy(float)
    efficiency = np.zeros(len(frame), dtype=float)
    nonzero = width > 0
    efficiency[nonzero] = (
        frame["close"].to_numpy(float)[nonzero]
        - frame["open"].to_numpy(float)[nonzero]
    ) / width[nonzero]
    absorption = efficiency - pressure
    out = pd.DataFrame(
        {
            "taker_pressure": pressure,
            "price_efficiency": efficiency,
            "absorption": absorption,
        },
        index=frame.index,
    )
    tolerance = 1e-10
    if np.max(np.abs(pressure)) > 1.0 + tolerance:
        raise ValueError("taker pressure outside [-1,1]")
    if np.max(np.abs(efficiency)) > 1.0 + tolerance:
        raise ValueError("candle efficiency outside [-1,1]")
    if np.max(np.abs(absorption)) > 2.0 + tolerance:
        raise ValueError("absorption outside [-2,2]")
    scaled = frame[["open", "high", "low", "close"]].to_numpy(float) * 7.25
    scaled_width = scaled[:, 1] - scaled[:, 2]
    scaled_efficiency = np.zeros(len(frame), dtype=float)
    scaled_nonzero = scaled_width > 0
    scaled_efficiency[scaled_nonzero] = (
        scaled[:, 3][scaled_nonzero] - scaled[:, 0][scaled_nonzero]
    ) / scaled_width[scaled_nonzero]
    if np.max(np.abs(scaled_efficiency - efficiency)) > 1e-12:
        raise ValueError("candle efficiency is not price-scale invariant")
    return out


def _anchors() -> list[int]:
    return [t for t in range(TRAIN_START, TRAIN_END, 24) if t + 25 < TRAIN_END]


def _opportunities(target: pd.DataFrame, exogenous: pd.DataFrame) -> pd.DataFrame:
    close = target["close"].to_numpy(float)
    open_price = target["open"].to_numpy(float)
    low = target["low"].to_numpy(float)
    absorption = _absorption_frame(exogenous)["absorption"].to_numpy(float)
    rows: list[dict[str, float | int]] = []
    for t in _anchors():
        latest = t - 25
        old = t - 2185
        if latest < 0 or old < 0 or latest - old != E2160_HOURS:
            raise ValueError("delayed E2160 index arithmetic")
        margin = math.log(float(close[latest]) / float(close[old]))
        if margin <= 0:
            continue
        baseline_start = t - 912
        baseline_end = t - 192
        recent_start = t - 192
        recent_end = t - 24
        if baseline_end - baseline_start != BASELINE_HOURS:
            raise ValueError("baseline window width")
        if recent_end - recent_start != RECENT_HOURS:
            raise ValueError("recent window width")
        if baseline_end != recent_start or recent_end - 1 != latest:
            raise ValueError("feature window overlap or causal-lag arithmetic")
        baseline = float(np.mean(absorption[baseline_start:baseline_end]))
        recent = float(np.mean(absorption[recent_start:recent_end]))
        feature = recent - baseline
        entry = float(open_price[t])
        delay_entry = float(open_price[t + 1])
        rows.append(
            {
                "t": t,
                "feature": feature,
                "margin": margin,
                "net": math.log(float(open_price[t + 24]) / entry) - ROUND_TRIP_FEE,
                "adverse": float(np.min(np.log(low[t : t + 25] / entry) - ROUND_TRIP_FEE)),
                "delay_net": math.log(float(open_price[t + 25]) / delay_entry) - ROUND_TRIP_FEE,
                "delay_adverse": float(
                    np.min(np.log(low[t + 1 : t + 26] / delay_entry) - ROUND_TRIP_FEE)
                ),
                "baseline_start": baseline_start,
                "baseline_end": baseline_end,
                "recent_start": recent_start,
                "recent_end": recent_end,
                "latest_signal_input": recent_end - 1,
                "e2160_latest": latest,
                "e2160_old": old,
            }
        )
    return pd.DataFrame(rows)


def _rho(x: object, y: object) -> float:
    xs = pd.Series(np.asarray(x, dtype=float)).rank(method="average")
    ys = pd.Series(np.asarray(y, dtype=float)).rank(method="average")
    return float(xs.corr(ys))


def _slope(x: object, y: object) -> float:
    xv = np.asarray(x, dtype=float)
    yv = np.asarray(y, dtype=float)
    std = float(xv.std(ddof=0))
    if not math.isfinite(std) or std <= 0:
        return float("nan")
    z = (xv - float(xv.mean())) / std
    return float(np.mean(z * yv))


def _tercile(x: object, y: object) -> tuple[float, int, int]:
    xv = np.asarray(x, dtype=float)
    yv = np.asarray(y, dtype=float)
    count = len(xv) // 3
    if count <= 0:
        return float("nan"), 0, 0
    order = np.argsort(xv, kind="mergesort")
    return float(yv[order[-count:]].mean() - yv[order[:count]].mean()), count, count


def _bootstrap(x: np.ndarray, net: np.ndarray, adverse: np.ndarray) -> dict[str, list[float]]:
    size = len(x)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    draws = np.empty((BOOTSTRAP_DRAWS, 4), dtype=float)
    for draw in range(BOOTSTRAP_DRAWS):
        indices: list[int] = []
        while len(indices) < size:
            start = int(rng.integers(0, size - BOOTSTRAP_BLOCK + 1))
            indices.extend(range(start, start + BOOTSTRAP_BLOCK))
        selected = np.asarray(indices[:size], dtype=int)
        draws[draw] = (
            _rho(x[selected], net[selected]),
            _slope(x[selected], net[selected]),
            _rho(x[selected], adverse[selected]),
            _slope(x[selected], adverse[selected]),
        )
    names = ("net_rho", "net_slope", "adverse_rho", "adverse_slope")
    return {
        name: [float(np.quantile(draws[:, i], 0.025)), float(np.quantile(draws[:, i], 0.975))]
        for i, name in enumerate(names)
    }


def _folds(opportunities: pd.DataFrame) -> tuple[list[dict[str, float | int]], float]:
    ordered = opportunities.sort_values("t").reset_index(drop=True)
    results: list[dict[str, float | int]] = []
    for fold_number, indices in enumerate(np.array_split(np.arange(len(ordered)), 4), start=1):
        fold = ordered.iloc[indices]
        x = fold["feature"].to_numpy(float)
        results.append(
            {
                "fold": fold_number,
                "n": len(fold),
                "net_slope": _slope(x, fold["net"]),
                "adverse_slope": _slope(x, fold["adverse"]),
            }
        )
    positive = [
        float(item["net_slope"])
        for item in results
        if math.isfinite(float(item["net_slope"])) and float(item["net_slope"]) > 0
    ]
    concentration = float("inf") if not positive else max(positive) / sum(positive)
    return results, float(concentration)


def _margin_strata(opportunities: pd.DataFrame) -> dict[str, object]:
    median = float(opportunities["margin"].median())
    output: dict[str, object] = {"median_margin": median}
    for name, subset in (
        ("lower", opportunities[opportunities["margin"] <= median]),
        ("upper", opportunities[opportunities["margin"] > median]),
    ):
        net_effect, net_low_n, net_high_n = _tercile(subset["feature"], subset["net"])
        adverse_effect, adverse_low_n, adverse_high_n = _tercile(
            subset["feature"], subset["adverse"]
        )
        output[name] = {
            "n": len(subset),
            "net_tercile_effect": net_effect,
            "adverse_tercile_effect": adverse_effect,
            "net_tercile_counts": [net_low_n, net_high_n],
            "adverse_tercile_counts": [adverse_low_n, adverse_high_n],
        }
    return output


def _target_result(
    target: pd.DataFrame,
    exogenous: pd.DataFrame,
    target_name: str,
) -> dict[str, object]:
    full = _opportunities(target, exogenous)
    prefix = _opportunities(target.iloc[:TRAIN_END].copy(), exogenous.iloc[:TRAIN_END].copy())
    compare_columns = [
        "t",
        "feature",
        "margin",
        "net",
        "adverse",
        "delay_net",
        "delay_adverse",
        "baseline_start",
        "baseline_end",
        "recent_start",
        "recent_end",
        "latest_signal_input",
        "e2160_latest",
        "e2160_old",
    ]
    prefix_invariant = (
        len(full) == len(prefix)
        and full[compare_columns].reset_index(drop=True).equals(
            prefix[compare_columns].reset_index(drop=True)
        )
    )
    if full.empty:
        raise ValueError(f"{target_name}: no eligible training opportunities")
    x = full["feature"].to_numpy(float)
    net = full["net"].to_numpy(float)
    adverse = full["adverse"].to_numpy(float)
    net_rho = _rho(x, net)
    net_slope = _slope(x, net)
    adverse_rho = _rho(x, adverse)
    adverse_slope = _slope(x, adverse)
    net_tercile, low_count, high_count = _tercile(x, net)
    adverse_tercile, adverse_low_count, adverse_high_count = _tercile(x, adverse)
    delay_net_rho = _rho(x, full["delay_net"])
    delay_net_slope = _slope(x, full["delay_net"])
    delay_net_tercile, _, _ = _tercile(x, full["delay_net"])
    delay_adverse_rho = _rho(x, full["delay_adverse"])
    delay_adverse_slope = _slope(x, full["delay_adverse"])
    delay_adverse_tercile, _, _ = _tercile(x, full["delay_adverse"])
    bootstrap = _bootstrap(x, net, adverse)
    folds, concentration = _folds(full)
    positive_net_folds = sum(float(item["net_slope"]) > 0 for item in folds)
    positive_adverse_folds = sum(float(item["adverse_slope"]) > 0 for item in folds)
    strata = _margin_strata(full)
    distribution = {
        "distinct": int(full["feature"].nunique()),
        "iqr": float(full["feature"].quantile(0.75) - full["feature"].quantile(0.25)),
        "q25": float(full["feature"].quantile(0.25)),
        "median": float(full["feature"].median()),
        "q75": float(full["feature"].quantile(0.75)),
    }
    strata_positive = all(
        float(strata[stratum][metric]) > 0
        for stratum in ("lower", "upper")
        for metric in ("net_tercile_effect", "adverse_tercile_effect")
    )
    structural = bool(
        (full["baseline_end"] == full["recent_start"]).all()
        and (full["baseline_end"] - full["baseline_start"] == BASELINE_HOURS).all()
        and (full["recent_end"] - full["recent_start"] == RECENT_HOURS).all()
        and (full["latest_signal_input"] <= full["t"] - 25).all()
        and (full["e2160_latest"] == full["t"] - 25).all()
        and (full["e2160_latest"] - full["e2160_old"] == E2160_HOURS).all()
    )
    gates = {
        "minimum_opportunities": len(full) >= 180,
        "feature_support": distribution["distinct"] >= 100 and distribution["iqr"] > 0,
        "tercile_sample_size": min(low_count, high_count, adverse_low_count, adverse_high_count) >= 50,
        "positive_net_association": net_rho > 0 and net_slope > 0,
        "positive_adverse_association": adverse_rho > 0 and adverse_slope > 0,
        "positive_tercile_effects": net_tercile > 0 and adverse_tercile > 0,
        "positive_bootstrap_lower_bounds": all(interval[0] > 0 for interval in bootstrap.values()),
        "fold_breadth": positive_net_folds >= 3 and positive_adverse_folds >= 3,
        "fold_concentration": math.isfinite(concentration) and concentration <= 0.60,
        "endpoint_margin_stratification": strata_positive,
        "delay_transport": (
            delay_net_rho > 0
            and delay_net_slope > 0
            and delay_net_tercile > 0
            and delay_adverse_rho > 0
            and delay_adverse_slope > 0
            and delay_adverse_tercile > 0
        ),
        "future_suffix_invariance": prefix_invariant,
        "structural_identities": structural,
    }
    stable = full.to_csv(index=False, float_format="%.17g", lineterminator="\n").encode()
    return {
        "opportunities": len(full),
        "opportunity_sha256": _sha(stable),
        "feature_distribution": distribution,
        "net_rho": net_rho,
        "net_slope": net_slope,
        "net_tercile_effect": net_tercile,
        "adverse_rho": adverse_rho,
        "adverse_slope": adverse_slope,
        "adverse_tercile_effect": adverse_tercile,
        "tercile_counts": {
            "net": [low_count, high_count],
            "adverse": [adverse_low_count, adverse_high_count],
        },
        "bootstrap_95": bootstrap,
        "folds": folds,
        "positive_net_folds": positive_net_folds,
        "positive_adverse_folds": positive_adverse_folds,
        "positive_net_fold_concentration": concentration,
        "margin_strata": strata,
        "delay_net_rho": delay_net_rho,
        "delay_net_slope": delay_net_slope,
        "delay_net_tercile_effect": delay_net_tercile,
        "delay_adverse_rho": delay_adverse_rho,
        "delay_adverse_slope": delay_adverse_slope,
        "delay_adverse_tercile_effect": delay_adverse_tercile,
        "gates": {key: bool(value) for key, value in gates.items()},
        "all_training_gates_pass": bool(all(gates.values())),
    }


def _write(payload: dict[str, object]) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    evidence = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    (OUTPUT / "evidence.json").write_bytes(evidence)
    manifest = {
        "code_head": payload["code_head"],
        "family_id": FAMILY_ID,
        "verdict": payload["verdict"],
        "evidence_sha256": _sha(evidence),
    }
    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    report_lines = [
        "# Same-asset perpetual taker-flow absorption — training-only 1H diagnostic",
        "",
        f"Family: `{FAMILY_ID}`",
        f"Verdict: `{payload['verdict']}`",
        f"Source contract passed: `{payload['source_contract_passed']}`",
        "Candidate/grid: `0/0`",
        "Sealed OOS accessed: `false`",
        "Canonical mutation: `false`",
        "Paper/live authorization: `false`",
    ]
    if payload.get("source_failure"):
        report_lines.extend(["", "## Source rejection", "", f"`{payload['source_failure']}`"])
    else:
        report_lines.extend(["", "## Bilateral training evidence", ""])
        targets = payload.get("targets", {})
        if isinstance(targets, dict):
            for name, result in targets.items():
                if isinstance(result, dict):
                    report_lines.append(
                        f"- {name}: n={result.get('opportunities')}, "
                        f"net rho={result.get('net_rho')}, net slope={result.get('net_slope')}, "
                        f"adverse rho={result.get('adverse_rho')}, adverse slope={result.get('adverse_slope')}, "
                        f"pass={result.get('all_training_gates_pass')}"
                    )
    (OUTPUT / "report.md").write_text("\n".join(report_lines) + "\n")
    print(json.dumps(payload, sort_keys=True, indent=2))
    print("EVIDENCE_SHA256", manifest["evidence_sha256"])


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    source_dir = OUTPUT / "sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    base_payload: dict[str, object] = {
        "family_id": FAMILY_ID,
        "code_head": os.environ.get("RESEARCH_HEAD_SHA", os.environ.get("GITHUB_SHA", "local")),
        "base_main": "5a0fcc97d1a882f8223656c51f5bb8055f534e38",
        "targets_fixed_preperformance": list(TARGETS),
        "exogenous_fixed_preperformance": list(TARGETS.values()),
        "providers": {
            "target": "anonymous public OKX SPOT history-candles",
            "exogenous": "Binance Public Data USD-M futures monthly klines",
        },
        "bar": "1H",
        "calendar": [START, END],
        "rows_per_arm": EXPECTED_ROWS,
        "training": [TRAIN_START, TRAIN_END],
        "sealed_oos": [TRAIN_END, OOS_END],
        "unread_suffix": [OOS_END, SOURCE_END],
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "fee_bps_one_way": 5.0,
        "round_trip_label_bps": 10.0,
        "bootstrap_draws": BOOTSTRAP_DRAWS,
        "bootstrap_block_opportunities": BOOTSTRAP_BLOCK,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "target_returns_accessed": False,
        "strategy_performance_accessed": False,
        "sealed_oos_accessed": False,
        "canonical_mutation": False,
        "correction_authority": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "strategy_metrics": {
            "train_return": None,
            "train_sharpe": None,
            "oos_return": None,
            "oos_sharpe": None,
            "full_return": None,
            "full_sharpe": None,
            "benchmark_comparison": None,
            "turnover": None,
            "fee_drag": None,
            "max_drawdown": None,
            "calendar_year_breadth": None,
            "edge_per_turnover": None,
        },
    }

    sources: dict[str, object] = {}
    exogenous_frames: dict[str, pd.DataFrame] = {}
    target_frames: dict[str, pd.DataFrame] = {}
    try:
        for target_name, symbol in TARGETS.items():
            frame, metadata = _acquire_binance(symbol, source_dir)
            exogenous_frames[target_name] = frame
            sources[f"binance:{symbol}"] = metadata
        for target_name in TARGETS:
            frame, metadata = _acquire_okx(target_name, source_dir)
            target_frames[target_name] = frame
            sources[f"okx:{target_name}"] = metadata
    except Exception as exc:
        payload = {
            **base_payload,
            "sources": sources,
            "source_contract_passed": False,
            "source_failure": f"{type(exc).__name__}: {exc}",
            "targets": {},
            "bilateral_training_pass": False,
            "verdict": SOURCE_REJECT,
        }
        _write(payload)
        return

    results: dict[str, object] = {}
    for target_name in TARGETS:
        results[target_name] = _target_result(
            target_frames[target_name], exogenous_frames[target_name], target_name
        )
    bilateral = all(
        isinstance(results[target_name], dict)
        and bool(results[target_name]["all_training_gates_pass"])
        for target_name in TARGETS
    )
    payload = {
        **base_payload,
        "sources": sources,
        "source_contract_passed": True,
        "source_failure": None,
        "target_returns_accessed": True,
        "targets": results,
        "bilateral_training_pass": bilateral,
        "verdict": SUPPORT if bilateral else REJECT,
    }
    _write(payload)


if __name__ == "__main__":
    main()
