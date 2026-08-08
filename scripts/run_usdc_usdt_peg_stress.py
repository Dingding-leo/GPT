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

FAMILY_ID = "causal-lagged-usdc-usdt-peg-stress-opportunity-1h-v1"
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
EXOGENOUS = "USDCUSDT"
BOOTSTRAP_DRAWS = 5_000
BOOTSTRAP_BLOCK = 7
BOOTSTRAP_SEEDS = {"BTCUSDT": 202608092017, "ETHUSDT": 202608092018}
SPOT_ROOT = "https://data.binance.vision/data/spot/monthly/klines"
OUTPUT = Path("reports/research/usdc-usdt-peg-stress-1h-v1")
REJECT = "reject_causal_lagged_usdc_usdt_peg_stress_opportunity_information_premise_1h_v1"
SUPPORT = (
    "support_causal_lagged_usdc_usdt_peg_stress_information_"
    "for_separate_candidate_predeclaration_1h_v1"
)
EXPECTED_SOURCE_SHA = {
    "BTCUSDT": "c282320ef644ae526eff1eec09b377868fc7ff73395506d65b6bfde6944a876d",
    "ETHUSDT": "ecac9b3431afb8875cc00044aa18c434ebe2f4524caef55ed1afce31f9ab7bba",
}
EXPECTED_TRAIN_SHA = {
    "BTCUSDT": "30d38944190ebaa80e65308c806be34a572e03fea2f1e695887fbd24c2607cc6",
    "ETHUSDT": "55f38818ed50e3cf0e97412aa22b3606ae7f4ec42f3a010cb14ef85b3f2f169f",
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
    transient_codes = {429, 500, 502, 503, 504}
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
                final_url = response.geturl()
            final = urlparse(final_url)
            if final.scheme != "https" or final.hostname != "data.binance.vision" or not raw:
                raise ValueError(f"invalid archive response: {final_url}")
            return raw, final_url
        except urllib.error.HTTPError as exc:
            if exc.code not in transient_codes:
                raise
            last_error = exc
        except urllib.error.URLError as exc:
            last_error = exc
        if attempt < 2:
            time.sleep(1.0 * (attempt + 1))
    if last_error is None:
        raise RuntimeError(f"failed archive request without error: {url}")
    raise last_error


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
            if (
                not np.isfinite(values).all()
                or min(open_px, high, low, close) <= 0
                or quote_volume < 0
            ):
                raise ValueError(f"{expected_name}: invalid finite/positive fields")
            if high < max(open_px, low, close) or low > min(open_px, high, close):
                raise ValueError(f"{expected_name}: invalid OHLC ordering")
            rows.append((timestamp, open_px, high, low, close, quote_volume))
    frame = pd.DataFrame(
        rows,
        columns=["timestamp", "open", "high", "low", "close", "quote_volume"],
    ).set_index("timestamp").sort_index()
    expected = month_grid(month)
    if (
        frame.index.has_duplicates
        or len(frame) != len(expected)
        or not frame.index.equals(expected)
    ):
        raise ValueError(f"{expected_name}: exact monthly 1H grid mismatch")
    return frame


def acquire(
    symbol: str, source_dir: Path, suffix: str = ""
) -> tuple[pd.DataFrame, dict[str, object]]:
    frames: list[pd.DataFrame] = []
    month_hashes: list[dict[str, object]] = []
    for month in months():
        filename = f"{symbol}-1h-{month}.zip"
        url = f"{SPOT_ROOT}/{symbol}/1h/{filename}"
        try:
            checksum_raw, checksum_url = trusted_get(url + ".CHECKSUM")
        except urllib.error.HTTPError as exc:
            raise ValueError(
                f"{symbol}/{filename}: checksum HTTP {exc.code}"
            ) from exc
        except urllib.error.URLError as exc:
            raise ValueError(
                f"{symbol}/{filename}: checksum transport error {exc.reason}"
            ) from exc
        try:
            zip_raw, zip_url = trusted_get(url)
        except urllib.error.HTTPError as exc:
            raise ValueError(f"{symbol}/{filename}: ZIP HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise ValueError(
                f"{symbol}/{filename}: ZIP transport error {exc.reason}"
            ) from exc
        declared = parse_checksum(checksum_raw, filename)
        observed = sha(zip_raw)
        if declared != observed:
            raise ValueError(f"{symbol}/{filename}: checksum mismatch")
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
    if (
        combined.index.has_duplicates
        or len(combined) != EXPECTED_ROWS
        or not combined.index.equals(expected)
    ):
        raise ValueError(f"{symbol}: combined 24,144H grid mismatch")
    normalized_sha = sha(canonical_bytes(combined))
    training_sha = sha(canonical_bytes(combined.iloc[:TRAIN_END]))
    if symbol in EXPECTED_SOURCE_SHA and normalized_sha != EXPECTED_SOURCE_SHA[symbol]:
        raise ValueError(f"{symbol}: normalized source identity mismatch")
    if symbol in EXPECTED_TRAIN_SHA and training_sha != EXPECTED_TRAIN_SHA[symbol]:
        raise ValueError(f"{symbol}: training-prefix identity mismatch")
    filename_suffix = f"-{suffix}" if suffix else ""
    source_path = source_dir / f"binance-spot-{symbol}-1h{filename_suffix}.csv"
    source_path.write_bytes(canonical_bytes(combined))
    return combined, {
        "provider": "Binance Public Data",
        "market_type": "spot",
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


def anchors() -> list[int]:
    return [t for t in range(TRAIN_START, TRAIN_END, 24) if t + 25 < TRAIN_END]


def peg_stress(exogenous_close: np.ndarray, t: int) -> float:
    window = np.asarray(exogenous_close[t - 192 : t - 24], dtype=float)
    if len(window) != 168 or not np.isfinite(window).all() or np.any(window <= 0):
        return float("nan")
    deviations = np.log(window)
    return float(np.sqrt(np.mean(deviations**2)))


def opportunity_frame(
    target: pd.DataFrame, exogenous: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, object]]:
    if not target.index.equals(exogenous.index):
        raise ValueError("target/exogenous common UTC grid mismatch")
    target_close = target["close"].to_numpy(float)
    exog_close = exogenous["close"].to_numpy(float)
    open_px = target["open"].to_numpy(float)
    rows: list[dict[str, object]] = []
    rms_errors: list[float] = []
    for t in anchors():
        margin = float(target_close[t - 25] / target_close[t - 2185] - 1.0)
        if margin <= 0:
            continue
        feature = peg_stress(exog_close, t)
        if not math.isfinite(feature):
            continue
        explicit = float(
            np.linalg.norm(np.log(exog_close[t - 192 : t - 24])) / math.sqrt(168.0)
        )
        rms_errors.append(abs(feature - explicit))
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
                "timestamp": str(target.index[t]),
                "feature": feature,
                "e2160_margin": margin,
                "gross": gross,
                "net": net,
                "adverse": adverse,
                "delay_net": delayed_net,
                "delay_adverse": delayed_adverse,
            }
        )
    structural = {
        "timestamp_identity": True,
        "fixed_parity": 1.0,
        "feature_nonnegative": bool(all(float(row["feature"]) >= 0 for row in rows)),
        "feature_window_hours": 168,
        "latest_exogenous_offset_hours": -25,
        "latest_membership_offset_hours": -25,
        "rms_equivalence_max_abs_error": float(max(rms_errors)) if rms_errors else None,
        "rms_equivalence_pass": bool(rms_errors) and max(rms_errors) <= 1e-15,
    }
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


def bootstrap_intervals(
    symbol: str, x: np.ndarray, net: np.ndarray, adverse: np.ndarray
) -> dict[str, list[float]]:
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
    masks = {
        "lower_or_equal": frame["e2160_margin"] <= median,
        "upper": frame["e2160_margin"] > median,
    }
    for name, mask in masks.items():
        sub = frame.loc[mask]
        x = sub["feature"].to_numpy(float)
        output[name] = {
            "rows": len(sub),
            "net_tercile": tercile_effect(x, sub["net"].to_numpy(float)),
            "adverse_tercile": tercile_effect(x, sub["adverse"].to_numpy(float)),
        }
    return output


def summarize(
    symbol: str,
    frame: pd.DataFrame,
    prefix_frame: pd.DataFrame,
    structural: dict[str, object],
    prefix_structural: dict[str, object],
) -> dict[str, object]:
    if len(frame) != len(prefix_frame) or not frame["t"].equals(prefix_frame["t"]):
        raise ValueError(f"{symbol}: opportunity prefix invariance failed")
    numeric = [
        "feature",
        "e2160_margin",
        "gross",
        "net",
        "adverse",
        "delay_net",
        "delay_adverse",
    ]
    if not np.allclose(
        frame[numeric].to_numpy(float),
        prefix_frame[numeric].to_numpy(float),
        rtol=0,
        atol=1e-14,
    ):
        raise ValueError(f"{symbol}: feature/label prefix invariance failed")
    if structural != prefix_structural:
        raise ValueError(f"{symbol}: structural prefix invariance failed")
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
    negative_net_folds = sum(float(fold["net_slope"]) < 0 for fold in folds)
    negative_adverse_folds = sum(float(fold["adverse_slope"]) < 0 for fold in folds)
    negative_net_values = [
        abs(float(fold["net_slope"])) for fold in folds if float(fold["net_slope"]) < 0
    ]
    net_concentration = (
        float(max(negative_net_values) / sum(negative_net_values))
        if negative_net_values
        else None
    )
    negative_adverse_values = [
        abs(float(fold["adverse_slope"])) for fold in folds if float(fold["adverse_slope"]) < 0
    ]
    adverse_concentration = (
        float(max(negative_adverse_values) / sum(negative_adverse_values))
        if negative_adverse_values
        else None
    )
    strata = margin_strata(frame)
    outer_count = len(frame) // 3
    structural_pass = (
        bool(structural["timestamp_identity"])
        and structural["fixed_parity"] == 1.0
        and bool(structural["feature_nonnegative"])
        and structural["feature_window_hours"] == 168
        and structural["latest_exogenous_offset_hours"] == -25
        and structural["latest_membership_offset_hours"] == -25
        and bool(structural["rms_equivalence_pass"])
    )
    gates = {
        "opportunities_ge_180": len(frame) >= 180,
        "feature_support": distinct >= 100 and iqr > 0,
        "outer_terciles_ge_50": outer_count >= 50,
        "net_direction_negative": all(base_net[key] < 0 for key in ("rho", "slope", "tercile")),
        "adverse_direction_negative": all(
            base_adverse[key] < 0 for key in ("rho", "slope", "tercile")
        ),
        "dependence_upper_bounds_negative": all(intervals[key][1] < 0 for key in intervals),
        "temporal_breadth": negative_net_folds >= 3 and negative_adverse_folds >= 3,
        "negative_net_fold_concentration_le_60pct": (
            net_concentration is not None and net_concentration <= 0.60
        ),
        "margin_strata": all(
            float(strata[name][endpoint]) < 0
            for name in ("lower_or_equal", "upper")
            for endpoint in ("net_tercile", "adverse_tercile")
        ),
        "plus_1h_transport": all(value < 0 for value in delayed_net.values())
        and all(value < 0 for value in delayed_adverse.values()),
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
        "negative_net_folds": negative_net_folds,
        "negative_adverse_folds": negative_adverse_folds,
        "negative_net_fold_concentration": net_concentration,
        "negative_adverse_fold_concentration_descriptive": adverse_concentration,
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
        "# Lagged USDC/USDT peg stress — frozen 1H training diagnostic",
        "",
        f"Family: `{FAMILY_ID}`",
        f"Code head: `{payload['code_head']}`",
        f"Source contract passed: `{payload['source_contract_passed']}`",
        f"Candidate/grid: `{payload['candidate_count']} / {payload['parameter_grid_count']}`",
        f"Sealed OOS accessed: `{payload['sealed_oos_accessed']}`",
        "",
    ]
    if payload.get("source_error"):
        report.extend(["## Source rejection", "", f"`{payload['source_error']}`", ""])
    for symbol, result in payload.get("targets", {}).items():
        report.extend(
            [
                f"## {symbol}",
                f"- opportunities: {result['opportunities']}",
                (
                    "- feature distinct/IQR: "
                    f"{result['feature_distribution']['distinct']} / "
                    f"{result['feature_distribution']['iqr']:.10f}"
                ),
                (
                    "- net rho/slope/tercile: "
                    f"{result['net_rho']:+.6f} / {result['net_slope']:+.6f} / "
                    f"{10000 * result['net_tercile_effect']:+.2f} bp"
                ),
                (
                    "- adverse rho/slope/tercile: "
                    f"{result['adverse_rho']:+.6f} / {result['adverse_slope']:+.6f} / "
                    f"{10000 * result['adverse_tercile_effect']:+.2f} bp"
                ),
                (
                    "- negative folds net/adverse: "
                    f"{result['negative_net_folds']}/4 / "
                    f"{result['negative_adverse_folds']}/4"
                ),
                (
                    "- negative-net-fold concentration: "
                    f"{result['negative_net_fold_concentration']}"
                ),
                (
                    "- +1H net rho/slope/tercile: "
                    f"{result['one_hour_delay']['net_rho']:+.6f} / "
                    f"{result['one_hour_delay']['net_slope']:+.6f} / "
                    f"{10000 * result['one_hour_delay']['net_tercile_effect']:+.2f} bp"
                ),
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
    usdc_repeat_identity = False
    common_calendar_passed = False
    panels: dict[str, pd.DataFrame] = {}
    usdc: pd.DataFrame | None = None

    try:
        usdc, usdc_meta = acquire(EXOGENOUS, source_dir, "first")
        usdc_repeat, usdc_repeat_meta = acquire(EXOGENOUS, source_dir, "repeat")
        if not usdc.index.equals(usdc_repeat.index):
            raise ValueError("USDCUSDT: repeat-acquisition timestamp mismatch")
        usdc_repeat_identity = (
            usdc_meta["normalized_sha256"] == usdc_repeat_meta["normalized_sha256"]
            and usdc_meta["training_prefix_sha256"]
            == usdc_repeat_meta["training_prefix_sha256"]
            and canonical_bytes(usdc) == canonical_bytes(usdc_repeat)
        )
        if not usdc_repeat_identity:
            raise ValueError("USDCUSDT: repeat-acquisition identity mismatch")
        sources[EXOGENOUS] = {
            **usdc_meta,
            "repeat_normalized_sha256": usdc_repeat_meta["normalized_sha256"],
            "repeat_training_prefix_sha256": usdc_repeat_meta["training_prefix_sha256"],
            "repeat_identity_passed": True,
        }

        for symbol in TARGETS:
            target, target_meta = acquire(symbol, source_dir)
            if not target.index.equals(usdc.index):
                raise ValueError(f"{symbol}: target/exogenous common UTC grid mismatch")
            panels[symbol] = target
            sources[symbol] = target_meta
        common_calendar_passed = True
        source_passed = True
    except Exception as exc:
        source_error = f"{type(exc).__name__}: {exc}"

    if source_passed:
        if usdc is None:
            raise RuntimeError("source contract marked passed without USDCUSDT panel")
        target_returns_accessed = True
        for symbol, target in panels.items():
            full, structural = opportunity_frame(target, usdc)
            prefix, prefix_structural = opportunity_frame(
                target.iloc[:TRAIN_END].copy(), usdc.iloc[:TRAIN_END].copy()
            )
            targets[symbol] = summarize(
                symbol, full, prefix, structural, prefix_structural
            )

    bilateral = source_passed and len(targets) == 2 and all(
        bool(result["all_training_gates_pass"]) for result in targets.values()
    )
    verdict = SUPPORT if bilateral else REJECT
    payload: dict[str, object] = {
        "schema_version": "usdc-usdt-peg-stress-1h-v1",
        "family_id": FAMILY_ID,
        "code_head": code_head,
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "bar": "1H",
        "provider": "Binance Public Data monthly spot archives",
        "source_window": {"start": START, "end": END, "rows_per_arm": EXPECTED_ROWS},
        "training": {
            "start_index": TRAIN_START,
            "end_index_exclusive": TRAIN_END,
            "step_hours": 24,
        },
        "sealed_oos": {"start_index": OOS_START, "end_index_exclusive": OOS_END},
        "unread_suffix": {"start_index": OOS_END, "end_index_exclusive": SOURCE_END},
        "feature": {
            "exogenous": EXOGENOUS,
            "definition": "sqrt(mean(log(USDCUSDT_close_h)^2)), h=t-192,...,t-25",
            "window_hours": 168,
            "latest_information_offset_hours": -25,
            "parity_usdt_per_usdc": 1.0,
            "fixed_sign": "negative",
        },
        "eligibility": "target_close[t-25] > target_close[t-2185]",
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
        "usdc_repeat_identity_passed": usdc_repeat_identity,
        "common_calendar_passed": common_calendar_passed,
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
    print(
        json.dumps(
            {
                "verdict": verdict,
                "source_passed": source_passed,
                "bilateral": bilateral,
                "source_error": source_error,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
