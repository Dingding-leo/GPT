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

FAMILY_ID = "causal-same-asset-perpetual-to-spot-return-transmission-opportunity-1h-v1"
START = "2023-04-01T00:00:00Z"
END = "2025-12-31T23:00:00Z"
EXPECTED_ROWS = 24_144
TRAIN_START = 2_208
TRAIN_END = 10_800
OOS_START = 10_800
OOS_END = 23_760
SOURCE_END = 24_144
ROUND_TRIP_FEE = 0.0010
TARGETS = ("BTCUSDT", "ETHUSDT")
BOOTSTRAP_DRAWS = 5_000
BOOTSTRAP_BLOCK = 7
BOOTSTRAP_SEEDS = {"BTCUSDT": 202608091145, "ETHUSDT": 202608091146}
SPOT_ROOT = "https://data.binance.vision/data/spot/monthly/klines"
PERP_ROOT = "https://data.binance.vision/data/futures/um/monthly/klines"
OUTPUT = Path("reports/research/perpetual-to-spot-return-transmission-1h-v1")
REJECT = "reject_causal_same_asset_perpetual_to_spot_return_transmission_information_premise_1h_v1"
SOURCE_REJECT = "reject_causal_same_asset_perpetual_to_spot_return_transmission_source_contract_1h_v1"
SUPPORT = "support_causal_same_asset_perpetual_to_spot_return_transmission_for_separate_candidate_predeclaration_1h_v1"
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


def log_returns(close: np.ndarray) -> np.ndarray:
    values = np.asarray(close, dtype=float)
    if len(values) < 2 or not np.isfinite(values).all() or np.any(values <= 0):
        raise ValueError("invalid close series for log returns")
    output = np.full(len(values), np.nan, dtype=float)
    output[1:] = np.log(values[1:] / values[:-1])
    return output


def correlation(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) != len(y) or len(x) < 2 or not np.isfinite(x).all() or not np.isfinite(y).all():
        return float("nan")
    if float(np.std(x)) <= 0 or float(np.std(y)) <= 0:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def lead_asymmetry(spot_ret: np.ndarray, perp_ret: np.ndarray, start: int, end: int) -> float:
    response = np.arange(start, end, dtype=int)
    if len(response) != 720:
        raise ValueError("lead baseline must contain exactly 720 response returns")
    p_to_s = correlation(perp_ret[response - 1], spot_ret[response])
    s_to_p = correlation(spot_ret[response - 1], perp_ret[response])
    if not math.isfinite(p_to_s) or not math.isfinite(s_to_p):
        return float("nan")
    return p_to_s - s_to_p


def anchors() -> list[int]:
    return [t for t in range(TRAIN_START, TRAIN_END, 24) if t + 25 < TRAIN_END]


def structural_checks(spot: pd.DataFrame, perpetual: pd.DataFrame) -> dict[str, object]:
    if not spot.index.equals(perpetual.index):
        raise ValueError("spot/perpetual timestamp identity failed")
    spot_close = spot["close"].to_numpy(float)
    perp_close = perpetual["close"].to_numpy(float)
    spot_ret = log_returns(spot_close)
    perp_ret = log_returns(perp_close)
    scaled_spot_ret = log_returns(spot_close * 7.25)
    scaled_perp_ret = log_returns(perp_close * 3.5)
    scale_error = float(
        max(
            np.nanmax(np.abs(spot_ret - scaled_spot_ret)),
            np.nanmax(np.abs(perp_ret - scaled_perp_ret)),
        )
    )
    swap_errors: list[float] = []
    for t in anchors():
        forward = lead_asymmetry(spot_ret, perp_ret, t - 912, t - 192)
        swapped = lead_asymmetry(perp_ret, spot_ret, t - 912, t - 192)
        if math.isfinite(forward) and math.isfinite(swapped):
            swap_errors.append(abs(forward + swapped))
    max_swap_error = float(max(swap_errors)) if swap_errors else float("inf")
    return {
        "timestamp_identity": True,
        "finite_log_returns": bool(np.isfinite(spot_ret[1:]).all() and np.isfinite(perp_ret[1:]).all()),
        "positive_price_scale_invariance": scale_error <= 1e-12,
        "max_positive_price_scale_error": scale_error,
        "lead_role_swap_antisymmetry": max_swap_error <= 1e-12,
        "max_lead_role_swap_error": max_swap_error,
    }


def opportunity_frame(spot: pd.DataFrame, perpetual: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    if not spot.index.equals(perpetual.index):
        raise ValueError("spot/perpetual common UTC grid mismatch")
    structural = structural_checks(spot, perpetual)
    spot_close = spot["close"].to_numpy(float)
    perp_close = perpetual["close"].to_numpy(float)
    spot_ret = log_returns(spot_close)
    perp_ret = log_returns(perp_close)
    open_px = spot["open"].to_numpy(float)
    rows: list[dict[str, object]] = []
    for t in anchors():
        if t + 25 >= len(spot):
            continue
        margin = float(spot_close[t - 25] / spot_close[t - 2185] - 1.0)
        if margin <= 0:
            continue
        lead = lead_asymmetry(spot_ret, perp_ret, t - 912, t - 192)
        recent = perp_ret[t - 192 : t - 24]
        if len(recent) != 168 or not np.isfinite(recent).all() or not math.isfinite(lead):
            continue
        impulse = float(np.sum(recent))
        feature = float(lead * impulse)
        if not math.isfinite(feature):
            continue
        entry = float(open_px[t])
        gross = float(open_px[t + 24] / entry - 1.0)
        net = gross - ROUND_TRIP_FEE
        adverse = float(np.min(open_px[t : t + 25] / entry - 1.0))
        delayed_entry = float(open_px[t + 1])
        delayed_gross = float(open_px[t + 25] / delayed_entry - 1.0)
        delayed_net = delayed_gross - ROUND_TRIP_FEE
        delayed_adverse = float(np.min(open_px[t + 1 : t + 26] / delayed_entry - 1.0))
        rows.append(
            {
                "t": t,
                "timestamp": str(spot.index[t]),
                "feature": feature,
                "lead_asymmetry": lead,
                "perp_impulse_168": impulse,
                "e2160_margin": margin,
                "gross": gross,
                "net": net,
                "adverse": adverse,
                "delay_net": delayed_net,
                "delay_adverse": delayed_adverse,
            }
        )
    return pd.DataFrame(rows), structural


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    rx = pd.Series(x).rank(method="average").to_numpy(float)
    ry = pd.Series(y).rank(method="average").to_numpy(float)
    if np.std(rx) == 0 or np.std(ry) == 0:
        return float("nan")
    return float(np.corrcoef(rx, ry)[0, 1])


def std_slope(x: np.ndarray, y: np.ndarray) -> float:
    sd = float(np.std(x, ddof=0))
    if not math.isfinite(sd) or sd <= 0:
        return float("nan")
    z = (x - float(np.mean(x))) / sd
    centered = z - np.mean(z)
    denominator = float(np.dot(centered, centered))
    if denominator <= 0:
        return float("nan")
    return float(np.dot(centered, y - np.mean(y)) / denominator)


def tercile_effect(x: np.ndarray, y: np.ndarray) -> float:
    order = np.argsort(x, kind="mergesort")
    k = len(order) // 3
    if k < 1:
        return float("nan")
    return float(np.mean(y[order[-k:]]) - np.mean(y[order[:k]]))


def triple(x: np.ndarray, y: np.ndarray) -> dict[str, float]:
    return {"rho": spearman(x, y), "slope": std_slope(x, y), "tercile": tercile_effect(x, y)}


def bootstrap_intervals(symbol: str, x: np.ndarray, net: np.ndarray, adverse: np.ndarray) -> dict[str, list[float]]:
    n = len(x)
    starts = np.arange(0, n - BOOTSTRAP_BLOCK + 1)
    if len(starts) < 1:
        raise ValueError("not enough opportunities for bootstrap")
    rng = np.random.default_rng(BOOTSTRAP_SEEDS[symbol])
    draws = {"net_rho": [], "net_slope": [], "adverse_rho": [], "adverse_slope": []}
    blocks_needed = math.ceil(n / BOOTSTRAP_BLOCK)
    for _ in range(BOOTSTRAP_DRAWS):
        picked: list[int] = []
        for start in rng.choice(starts, size=blocks_needed, replace=True):
            picked.extend(range(int(start), int(start) + BOOTSTRAP_BLOCK))
        index = np.asarray(picked[:n], dtype=int)
        draws["net_rho"].append(spearman(x[index], net[index]))
        draws["net_slope"].append(std_slope(x[index], net[index]))
        draws["adverse_rho"].append(spearman(x[index], adverse[index]))
        draws["adverse_slope"].append(std_slope(x[index], adverse[index]))
    return {
        key: [float(np.quantile(values, 0.025)), float(np.quantile(values, 0.975))]
        for key, values in draws.items()
    }


def fold_stats(frame: pd.DataFrame) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for fold, index in enumerate(np.array_split(np.arange(len(frame)), 4), 1):
        sub = frame.iloc[index]
        x = sub["feature"].to_numpy(float)
        output.append(
            {
                "fold": fold,
                "rows": len(sub),
                "start": sub["timestamp"].iloc[0],
                "end": sub["timestamp"].iloc[-1],
                "net_slope": std_slope(x, sub["net"].to_numpy(float)),
                "adverse_slope": std_slope(x, sub["adverse"].to_numpy(float)),
            }
        )
    return output


def margin_strata(frame: pd.DataFrame) -> dict[str, object]:
    median = float(frame["e2160_margin"].median())
    output: dict[str, object] = {"median_margin": median}
    masks = {"lower_or_equal": frame["e2160_margin"] <= median, "upper": frame["e2160_margin"] > median}
    for name, mask in masks.items():
        sub = frame.loc[mask]
        x = sub["feature"].to_numpy(float)
        output[name] = {
            "rows": len(sub),
            "net_tercile": tercile_effect(x, sub["net"].to_numpy(float)),
            "adverse_tercile": tercile_effect(x, sub["adverse"].to_numpy(float)),
        }
    return output


def summarize(symbol: str, frame: pd.DataFrame, prefix_frame: pd.DataFrame, structural: dict[str, object]) -> dict[str, object]:
    if len(frame) != len(prefix_frame) or not frame["t"].equals(prefix_frame["t"]):
        raise ValueError(f"{symbol}: opportunity prefix invariance failed")
    numeric = [
        "feature",
        "lead_asymmetry",
        "perp_impulse_168",
        "e2160_margin",
        "gross",
        "net",
        "adverse",
        "delay_net",
        "delay_adverse",
    ]
    if not np.allclose(frame[numeric].to_numpy(float), prefix_frame[numeric].to_numpy(float), rtol=0, atol=1e-14):
        raise ValueError(f"{symbol}: feature/label prefix invariance failed")
    x = frame["feature"].to_numpy(float)
    net = frame["net"].to_numpy(float)
    adverse = frame["adverse"].to_numpy(float)
    delay_net = frame["delay_net"].to_numpy(float)
    delay_adverse = frame["delay_adverse"].to_numpy(float)
    distinct = int(pd.Series(x).nunique())
    iqr = float(np.quantile(x, 0.75) - np.quantile(x, 0.25))
    base_net = triple(x, net)
    base_adverse = triple(x, adverse)
    delayed_net = triple(x, delay_net)
    delayed_adverse = triple(x, delay_adverse)
    intervals = bootstrap_intervals(symbol, x, net, adverse)
    folds = fold_stats(frame)
    positive_net_folds = sum(float(fold["net_slope"]) > 0 for fold in folds)
    positive_adverse_folds = sum(float(fold["adverse_slope"]) > 0 for fold in folds)
    positive_values = [float(fold["net_slope"]) for fold in folds if float(fold["net_slope"]) > 0]
    concentration = float(max(positive_values) / sum(positive_values)) if positive_values else None
    strata = margin_strata(frame)
    outer_count = len(frame) // 3
    structural_pass = (
        bool(structural["timestamp_identity"])
        and bool(structural["finite_log_returns"])
        and bool(structural["positive_price_scale_invariance"])
        and bool(structural["lead_role_swap_antisymmetry"])
    )
    gates = {
        "opportunities_ge_180": len(frame) >= 180,
        "feature_support": distinct >= 100 and iqr > 0,
        "outer_terciles_ge_50": outer_count >= 50,
        "net_direction": all(base_net[key] > 0 for key in ("rho", "slope", "tercile")),
        "adverse_direction": all(base_adverse[key] > 0 for key in ("rho", "slope", "tercile")),
        "dependence_lower_bounds_positive": all(intervals[key][0] > 0 for key in intervals),
        "temporal_breadth": positive_net_folds >= 3 and positive_adverse_folds >= 3,
        "positive_net_fold_concentration_le_60pct": concentration is not None and concentration <= 0.60,
        "margin_strata": all(
            float(strata[name][endpoint]) > 0
            for name in ("lower_or_equal", "upper")
            for endpoint in ("net_tercile", "adverse_tercile")
        ),
        "plus_1h_transport": all(value > 0 for value in delayed_net.values())
        and all(value > 0 for value in delayed_adverse.values()),
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
        },
        "lead_asymmetry_distribution": {
            "min": float(frame["lead_asymmetry"].min()),
            "max": float(frame["lead_asymmetry"].max()),
            "mean": float(frame["lead_asymmetry"].mean()),
            "median": float(frame["lead_asymmetry"].median()),
        },
        "perp_impulse_168_distribution": {
            "min": float(frame["perp_impulse_168"].min()),
            "max": float(frame["perp_impulse_168"].max()),
            "mean": float(frame["perp_impulse_168"].mean()),
            "median": float(frame["perp_impulse_168"].median()),
        },
        "unconditional_net_return": {
            "mean": float(np.mean(net)),
            "median": float(np.median(net)),
            "positive_fraction": float(np.mean(net > 0)),
        },
        "net_rho": base_net["rho"],
        "net_slope": base_net["slope"],
        "net_tercile_effect": base_net["tercile"],
        "adverse_rho": base_adverse["rho"],
        "adverse_slope": base_adverse["slope"],
        "adverse_tercile_effect": base_adverse["tercile"],
        "bootstrap_95": intervals,
        "folds": folds,
        "positive_net_folds": positive_net_folds,
        "positive_adverse_folds": positive_adverse_folds,
        "positive_net_fold_concentration": concentration,
        "margin_strata": strata,
        "one_hour_delay": {
            "net_rho": delayed_net["rho"],
            "net_slope": delayed_net["slope"],
            "net_tercile_effect": delayed_net["tercile"],
            "adverse_rho": delayed_adverse["rho"],
            "adverse_slope": delayed_adverse["slope"],
            "adverse_tercile_effect": delayed_adverse["tercile"],
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
        "calendar_year_strategy_breadth": None,
    }


def write_outputs(payload: dict[str, object]) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    evidence_path = OUTPUT / "evidence.json"
    report_path = OUTPUT / "report.md"
    evidence_path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
    report = [
        "# Same-asset perpetual-to-spot return transmission — frozen 1H training diagnostic",
        "",
        f"Family: `{FAMILY_ID}`",
        f"Code head: `{payload['code_head']}`",
        f"Source contract passed: `{payload['source_contract_passed']}`",
        f"Candidate/grid: `{payload['candidate_count']} / {payload['parameter_grid_count']}`",
        f"Sealed OOS accessed: `{payload['sealed_oos_accessed']}`",
        "",
    ]
    for symbol, result in payload.get("targets", {}).items():
        report.extend(
            [
                f"## {symbol}",
                f"- opportunities: {result['opportunities']}",
                f"- feature distinct/IQR: {result['feature_distribution']['distinct']} / {result['feature_distribution']['iqr']:.8f}",
                f"- lead-asymmetry mean/median: {result['lead_asymmetry_distribution']['mean']:+.6f} / {result['lead_asymmetry_distribution']['median']:+.6f}",
                f"- net rho/slope/tercile: {result['net_rho']:+.6f} / {result['net_slope']:+.6f} / {10000 * result['net_tercile_effect']:+.2f} bp",
                f"- adverse rho/slope/tercile: {result['adverse_rho']:+.6f} / {result['adverse_slope']:+.6f} / {10000 * result['adverse_tercile_effect']:+.2f} bp",
                f"- positive folds net/adverse: {result['positive_net_folds']}/4 / {result['positive_adverse_folds']}/4",
                f"- positive-net-fold concentration: {result['positive_net_fold_concentration']}",
                f"- +1H net rho/slope/tercile: {result['one_hour_delay']['net_rho']:+.6f} / {result['one_hour_delay']['net_slope']:+.6f} / {10000 * result['one_hour_delay']['net_tercile_effect']:+.2f} bp",
                f"- all gates pass: {result['all_training_gates_pass']}",
                "",
            ]
        )
    report.extend(["## Verdict", "", f"`{payload['verdict']}`", ""])
    report_path.write_text("\n".join(report))
    manifest = {
        "family_id": FAMILY_ID,
        "evidence_sha256": sha(evidence_path.read_bytes()),
        "report_sha256": sha(report_path.read_bytes()),
    }
    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    source_dir = OUTPUT / "sources"
    source_dir.mkdir(exist_ok=True)
    code_head = os.environ.get("RESEARCH_HEAD_SHA", "unknown")
    sources: dict[str, object] = {}
    targets: dict[str, object] = {}
    source_passed = False
    target_returns_accessed = False
    source_error: str | None = None
    try:
        panels: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}
        for symbol in TARGETS:
            spot, spot_meta = acquire(symbol, "spot", source_dir)
            perpetual, perpetual_meta = acquire(symbol, "perpetual", source_dir)
            if not spot.index.equals(perpetual.index):
                raise ValueError(f"{symbol}: spot/perpetual common UTC grid mismatch")
            panels[symbol] = (spot, perpetual)
            sources[f"{symbol}_spot"] = spot_meta
            sources[f"{symbol}_perpetual"] = perpetual_meta
        source_passed = True
        target_returns_accessed = True
        for symbol, (spot, perpetual) in panels.items():
            full, structural = opportunity_frame(spot, perpetual)
            prefix, prefix_structural = opportunity_frame(spot.iloc[:TRAIN_END].copy(), perpetual.iloc[:TRAIN_END].copy())
            structural_bool_keys = (
                "timestamp_identity",
                "finite_log_returns",
                "positive_price_scale_invariance",
                "lead_role_swap_antisymmetry",
            )
            if any(bool(structural[key]) != bool(prefix_structural[key]) for key in structural_bool_keys):
                raise ValueError(f"{symbol}: structural prefix invariance failed")
            targets[symbol] = summarize(symbol, full, prefix, structural)
    except Exception as exc:
        source_error = f"{type(exc).__name__}: {exc}"

    bilateral = source_passed and len(targets) == 2 and all(
        bool(result["all_training_gates_pass"]) for result in targets.values()
    )
    verdict = SUPPORT if bilateral else (REJECT if source_passed else SOURCE_REJECT)
    payload: dict[str, object] = {
        "schema_version": "perpetual-to-spot-return-transmission-1h-v1",
        "family_id": FAMILY_ID,
        "code_head": code_head,
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "bar": "1H",
        "provider": "Binance Public Data monthly archives",
        "source_window": {"start": START, "end": END, "rows_per_arm": EXPECTED_ROWS},
        "training": {"start_index": TRAIN_START, "end_index_exclusive": TRAIN_END, "step_hours": 24},
        "sealed_oos": {"start_index": OOS_START, "end_index_exclusive": OOS_END},
        "unread_suffix": {"start_index": OOS_END, "end_index_exclusive": SOURCE_END},
        "feature": {
            "spot_return": "log(spot_close_i/spot_close_(i-1))",
            "perpetual_return": "log(perp_close_i/perp_close_(i-1))",
            "lead_baseline": "corr(perp_r_(i-1),spot_r_i)-corr(spot_r_(i-1),perp_r_i), i in [t-912,t-192)",
            "perpetual_impulse": "sum(perp_r_i), i in [t-192,t-24) = 168 returns through t-25",
            "feature": "lead_asymmetry * perpetual_impulse_168",
            "fixed_sign": "positive",
        },
        "fee_bps_one_way": 5.0,
        "round_trip_label_bps": 10.0,
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "bootstrap_draws": BOOTSTRAP_DRAWS,
        "bootstrap_block_opportunities": BOOTSTRAP_BLOCK,
        "bootstrap_seeds": BOOTSTRAP_SEEDS,
        "targets_fixed_preperformance": list(TARGETS),
        "source_contract_passed": source_passed,
        "source_error": source_error,
        "sources": sources,
        "target_returns_accessed": target_returns_accessed,
        "target_oos_accessed": False,
        "sealed_oos_accessed": False,
        "unread_suffix_accessed": False,
        "strategy_performance_accessed": False,
        "strategy_metrics": null_strategy_metrics(),
        "targets": targets,
        "bilateral_training_pass": bilateral,
        "canonical_mutation": False,
        "correction_authority": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "verdict": verdict,
    }
    write_outputs(payload)
    print(json.dumps({"verdict": verdict, "source_passed": source_passed, "bilateral": bilateral}, sort_keys=True))


if __name__ == "__main__":
    main()
