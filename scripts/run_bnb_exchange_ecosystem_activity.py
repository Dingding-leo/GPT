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

FAMILY_ID = "causal-lagged-bnb-exchange-ecosystem-activity-opportunity-1h-v1"
REJECT = "reject_causal_lagged_bnb_exchange_ecosystem_activity_information_premise_1h_v1"
SOURCE_REJECT = "reject_causal_lagged_bnb_exchange_ecosystem_activity_source_contract_1h_v1"
SUPPORT = "support_causal_lagged_bnb_exchange_ecosystem_activity_for_separate_candidate_predeclaration_1h_v1"

START = "2023-04-01T00:00:00Z"
END = "2025-12-31T23:00:00Z"
EXPECTED_ROWS = 24_144
TRAIN_START = 2_208
TRAIN_END = 10_800
OOS_START = 10_800
OOS_END = 23_760
SOURCE_END = 24_144
TARGETS = ("BTC-USDT", "ETH-USDT")
EXOG = "BNBUSDT"
ROUND_TRIP_FEE = 0.0010
DRAWS = 5_000
BLOCK = 7
SEEDS = {"BTC-USDT": 202608092301, "ETH-USDT": 202608092302}
BINANCE_ROOT = "https://data.binance.vision/data/spot/monthly/klines"
OUTPUT = Path("reports/research/bnb-exchange-ecosystem-activity-1h-v1")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_frame_bytes(frame: pd.DataFrame) -> bytes:
    return frame.reset_index(names="timestamp").to_csv(
        index=False,
        date_format="%Y-%m-%dT%H:%M:%S.%fZ",
        float_format="%.12g",
        lineterminator="\n",
    ).encode()


def trusted_get(url: str) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "data.binance.vision":
        raise ValueError(f"untrusted source URL: {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "gpt-quant-research/1.0"})
    retryable = {408, 429, 500, 502, 503, 504}
    last: Exception | None = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                raw = response.read()
                final = urlparse(response.geturl())
            if final.scheme != "https" or final.hostname != "data.binance.vision" or not raw:
                raise ValueError("invalid Binance response")
            return raw
        except urllib.error.HTTPError as exc:
            if exc.code not in retryable:
                raise
            last = exc
        except urllib.error.URLError as exc:
            last = exc
        if attempt < 3:
            time.sleep(float(attempt + 1))
    raise last or RuntimeError("source request failed")


def month_ids() -> list[str]:
    return [str(value) for value in pd.period_range("2023-04", "2025-12", freq="M")]


def month_grid(month: str) -> pd.DatetimeIndex:
    period = pd.Period(month, freq="M")
    return pd.date_range(
        period.start_time.tz_localize("UTC"),
        period.end_time.floor("h").tz_localize("UTC"),
        freq="h",
    )


def parse_checksum(raw: bytes, filename: str) -> str:
    parts = raw.decode("ascii").strip().split()
    if len(parts) < 2:
        raise ValueError(f"{filename}: malformed checksum")
    digest = parts[0].lower()
    declared = parts[-1].lstrip("*")
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError(f"{filename}: malformed checksum digest")
    if declared != filename:
        raise ValueError(f"{filename}: checksum filename mismatch")
    return digest


def parse_timestamp(raw: str, label: str) -> pd.Timestamp:
    value = int(raw)
    if value > 10**14:
        unit = "us"
        divisor = 3_600_000_000
    else:
        unit = "ms"
        divisor = 3_600_000
    if value % divisor:
        raise ValueError(f"{label}: off-grid timestamp")
    return pd.to_datetime(value, unit=unit, utc=True)


def parse_binance_zip(raw: bytes, filename: str, month: str) -> pd.DataFrame:
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise ValueError(f"{filename}: invalid ZIP") from exc
    expected_csv = filename.removesuffix(".zip") + ".csv"
    members = [name for name in archive.namelist() if not name.endswith("/")]
    if members != [expected_csv]:
        raise ValueError(f"{filename}: unexpected archive members {members}")
    rows: list[tuple[pd.Timestamp, float]] = []
    with archive.open(expected_csv) as handle:
        reader = csv.reader(io.TextIOWrapper(handle, encoding="utf-8", newline=""))
        for row_number, row in enumerate(reader, 1):
            if not row:
                continue
            if len(row) != 12:
                raise ValueError(f"{filename}: row {row_number} schema mismatch")
            try:
                timestamp = parse_timestamp(row[0], filename)
            except ValueError:
                if row_number == 1 and "open" in row[0].lower():
                    continue
                raise
            try:
                open_px, high, low, close, quote_volume = map(
                    float, (row[1], row[2], row[3], row[4], row[7])
                )
            except ValueError as exc:
                raise ValueError(f"{filename}: nonnumeric kline") from exc
            values = np.asarray([open_px, high, low, close, quote_volume], dtype=float)
            if not np.isfinite(values).all() or min(open_px, high, low, close) <= 0 or quote_volume < 0:
                raise ValueError(f"{filename}: invalid values")
            if high < max(open_px, low, close) or low > min(open_px, high, close):
                raise ValueError(f"{filename}: invalid OHLC ordering")
            rows.append((timestamp, quote_volume))
    frame = pd.DataFrame(rows, columns=["timestamp", "quote_volume"]).set_index("timestamp").sort_index()
    expected = month_grid(month)
    if frame.index.has_duplicates or not frame.index.equals(expected):
        raise ValueError(f"{filename}: monthly 1H grid mismatch")
    return frame


def acquire_binance_bnb(*, persist: bool) -> tuple[pd.DataFrame, dict[str, object]]:
    frames: list[pd.DataFrame] = []
    records: list[dict[str, object]] = []
    source_dir = OUTPUT / "sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    for month in month_ids():
        filename = f"{EXOG}-1h-{month}.zip"
        base = f"{BINANCE_ROOT}/{EXOG}/1h/{filename}"
        checksum_raw = trusted_get(base + ".CHECKSUM")
        zip_raw = trusted_get(base)
        declared = parse_checksum(checksum_raw, filename)
        observed = sha256(zip_raw)
        if declared != observed:
            raise ValueError(f"{filename}: checksum mismatch")
        frame = parse_binance_zip(zip_raw, filename, month)
        frames.append(frame)
        records.append(
            {
                "month": month,
                "rows": len(frame),
                "zip_sha256": observed,
                "checksum_sha256": sha256(checksum_raw),
            }
        )
        time.sleep(0.01)
    combined = pd.concat(frames).sort_index()
    expected = pd.date_range(START, END, freq="h")
    if len(combined) != EXPECTED_ROWS or combined.index.has_duplicates or not combined.index.equals(expected):
        raise ValueError(f"{EXOG}: exact 24,144H grid mismatch")
    raw = canonical_frame_bytes(combined)
    if persist:
        (source_dir / "binance-spot-BNBUSDT-1h.csv").write_bytes(raw)
    meta = {
        "provider": "Binance Public Data",
        "market_type": "SPOT",
        "instrument": EXOG,
        "bar": "1H",
        "rows": len(combined),
        "start": str(combined.index[0]),
        "end": str(combined.index[-1]),
        "normalized_sha256": sha256(raw),
        "training_prefix_sha256": sha256(canonical_frame_bytes(combined.iloc[:TRAIN_END])),
        "month_count": len(records),
        "months": records,
    }
    return combined, meta


def acquire_okx_target(inst_id: str, *, persist: bool) -> tuple[pd.DataFrame, dict[str, object]]:
    snapshot = fetch_okx_one_hour_candles(
        inst_id=inst_id,
        start=START,
        end=END,
        pause_seconds=0.12,
        timeout=30.0,
        safety_pages=96,
    )
    frame = snapshot.candles.copy()
    expected = pd.date_range(START, END, freq="h")
    if len(frame) != EXPECTED_ROWS or frame.index.has_duplicates or not frame.index.equals(expected):
        raise ValueError(f"{inst_id}: exact 24,144H grid mismatch")
    if "confirm" not in frame.columns or not (frame["confirm"].astype(str) == "1").all():
        raise ValueError(f"{inst_id}: unconfirmed candle in frozen interval")
    normalized = _canonical_csv_bytes(frame)
    raw_pages = _canonical_json_bytes(snapshot.raw_pages)
    metadata = _canonical_json_bytes(snapshot.metadata)
    if persist:
        source_dir = OUTPUT / "sources"
        source_dir.mkdir(parents=True, exist_ok=True)
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


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    rx = pd.Series(x).rank(method="average").to_numpy(float)
    ry = pd.Series(y).rank(method="average").to_numpy(float)
    if np.std(rx) <= 0 or np.std(ry) <= 0:
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


def tercile_effect(x: np.ndarray, y: np.ndarray) -> tuple[float, int]:
    order = np.argsort(x, kind="mergesort")
    k = len(order) // 3
    if k < 1:
        return float("nan"), 0
    return float(np.mean(y[order[-k:]]) - np.mean(y[order[:k]])), k


def triple(x: np.ndarray, y: np.ndarray) -> dict[str, float]:
    effect, _ = tercile_effect(x, y)
    return {"rho": spearman(x, y), "slope": standardized_slope(x, y), "tercile": effect}


def moving_block_intervals(
    inst_id: str, x: np.ndarray, net: np.ndarray, adverse: np.ndarray
) -> dict[str, list[float]]:
    n = len(x)
    starts = np.arange(0, n - BLOCK + 1)
    if len(starts) < 1:
        raise ValueError("insufficient opportunities for bootstrap")
    rng = np.random.default_rng(SEEDS[inst_id])
    blocks_needed = math.ceil(n / BLOCK)
    draws = {key: [] for key in ("net_rho", "net_slope", "adverse_rho", "adverse_slope")}
    for _ in range(DRAWS):
        idx = np.concatenate(
            [
                np.arange(int(start), int(start) + BLOCK)
                for start in rng.choice(starts, size=blocks_needed, replace=True)
            ]
        )[:n]
        xx = x[idx]
        nn = net[idx]
        aa = adverse[idx]
        draws["net_rho"].append(spearman(xx, nn))
        draws["net_slope"].append(standardized_slope(xx, nn))
        draws["adverse_rho"].append(spearman(xx, aa))
        draws["adverse_slope"].append(standardized_slope(xx, aa))
    return {
        key: [float(np.quantile(values, 0.025)), float(np.quantile(values, 0.975))]
        for key, values in draws.items()
    }


def opportunity_frame(target: pd.DataFrame, exog: pd.DataFrame) -> pd.DataFrame:
    if not target.index.equals(exog.index):
        raise ValueError("target/exogenous calendar mismatch")
    close = target["close"].to_numpy(float)
    open_px = target["open"].to_numpy(float)
    volume = exog["quote_volume"].to_numpy(float)
    rows: list[dict[str, object]] = []
    for t in range(TRAIN_START, TRAIN_END, 24):
        if t + 25 >= TRAIN_END:
            continue
        if close[t - 25] <= close[t - 2185]:
            continue
        recent = volume[t - 192 : t - 24]
        baseline = volume[t - 912 : t - 192]
        if len(recent) != 168 or len(baseline) != 720:
            raise ValueError("feature window length mismatch")
        recent_mean = float(np.mean(recent))
        baseline_mean = float(np.mean(baseline))
        if not math.isfinite(recent_mean) or not math.isfinite(baseline_mean) or recent_mean <= 0 or baseline_mean <= 0:
            continue
        feature = float(math.log(recent_mean / baseline_mean))
        entry = float(open_px[t])
        net = float(open_px[t + 24] / entry - 1.0 - ROUND_TRIP_FEE)
        adverse = float(np.min(open_px[t : t + 25] / entry - 1.0))
        delayed_entry = float(open_px[t + 1])
        delayed_net = float(open_px[t + 25] / delayed_entry - 1.0 - ROUND_TRIP_FEE)
        delayed_adverse = float(np.min(open_px[t + 1 : t + 26] / delayed_entry - 1.0))
        rows.append(
            {
                "t": t,
                "timestamp": str(target.index[t]),
                "feature": feature,
                "e2160_margin": float(close[t - 25] / close[t - 2185] - 1.0),
                "net": net,
                "adverse": adverse,
                "delay_net": delayed_net,
                "delay_adverse": delayed_adverse,
            }
        )
    return pd.DataFrame(rows)


def evaluate(inst_id: str, target: pd.DataFrame, exog: pd.DataFrame) -> dict[str, object]:
    frame = opportunity_frame(target, exog)
    x = frame["feature"].to_numpy(float)
    net = frame["net"].to_numpy(float)
    adverse = frame["adverse"].to_numpy(float)
    dnet = frame["delay_net"].to_numpy(float)
    dadverse = frame["delay_adverse"].to_numpy(float)

    point = {"net": triple(x, net), "adverse": triple(x, adverse)}
    delay = {"net": triple(x, dnet), "adverse": triple(x, dadverse)}
    bootstrap = moving_block_intervals(inst_id, x, net, adverse)

    folds: list[dict[str, object]] = []
    for number, idx in enumerate(np.array_split(np.arange(len(frame)), 4), 1):
        sub = frame.iloc[idx]
        sx = sub["feature"].to_numpy(float)
        folds.append(
            {
                "fold": number,
                "rows": len(sub),
                "net_slope": standardized_slope(sx, sub["net"].to_numpy(float)),
                "adverse_slope": standardized_slope(sx, sub["adverse"].to_numpy(float)),
            }
        )
    positive_net = [max(0.0, float(item["net_slope"])) for item in folds]
    positive_sum = sum(positive_net)
    concentration = max(positive_net) / positive_sum if positive_sum > 0 else None
    positive_net_folds = sum(float(item["net_slope"]) > 0 for item in folds)
    positive_adverse_folds = sum(float(item["adverse_slope"]) > 0 for item in folds)

    median_margin = float(frame["e2160_margin"].median())
    strata: dict[str, object] = {"median_margin": median_margin}
    for name, mask in {
        "lower_or_equal": frame["e2160_margin"] <= median_margin,
        "upper": frame["e2160_margin"] > median_margin,
    }.items():
        sub = frame.loc[mask]
        sx = sub["feature"].to_numpy(float)
        strata[name] = {
            "rows": len(sub),
            "net_tercile": tercile_effect(sx, sub["net"].to_numpy(float))[0],
            "adverse_tercile": tercile_effect(sx, sub["adverse"].to_numpy(float))[0],
        }

    midpoint = len(frame) // 2
    halves: dict[str, object] = {}
    for name, sub in {"first": frame.iloc[:midpoint], "second": frame.iloc[midpoint:]}.items():
        sx = sub["feature"].to_numpy(float)
        halves[name] = {
            "rows": len(sub),
            "net_tercile": tercile_effect(sx, sub["net"].to_numpy(float))[0],
            "adverse_tercile": tercile_effect(sx, sub["adverse"].to_numpy(float))[0],
        }

    distinct = int(frame["feature"].nunique())
    iqr = float(frame["feature"].quantile(0.75) - frame["feature"].quantile(0.25))
    outer = len(frame) // 3

    volume = exog["quote_volume"].to_numpy(float)
    first_t = int(frame["t"].iloc[0])
    base_feature = math.log(
        float(np.mean(volume[first_t - 192 : first_t - 24]))
        / float(np.mean(volume[first_t - 912 : first_t - 192]))
    )
    scaled = volume * 7.25
    scaled_feature = math.log(
        float(np.mean(scaled[first_t - 192 : first_t - 24]))
        / float(np.mean(scaled[first_t - 912 : first_t - 192]))
    )
    structural = {
        "recent_hours": 168,
        "baseline_hours": 720,
        "latest_information_offset_hours": -25,
        "volume_scale_invariance_abs_error": abs(base_feature - scaled_feature),
        "volume_scale_invariance_pass": abs(base_feature - scaled_feature) <= 1e-12,
    }

    gates = {
        "opportunities_ge_180": len(frame) >= 180,
        "feature_support": distinct >= 100 and iqr > 0 and outer >= 50,
        "net_direction_positive": all(point["net"][key] > 0 for key in ("rho", "slope", "tercile")),
        "adverse_direction_positive": all(
            point["adverse"][key] > 0 for key in ("rho", "slope", "tercile")
        ),
        "dependence_lower_bounds_positive": all(
            interval[0] > 0 for interval in bootstrap.values()
        ),
        "temporal_fold_breadth": positive_net_folds >= 3 and positive_adverse_folds >= 3,
        "positive_net_fold_concentration_le_60pct": concentration is not None
        and concentration <= 0.60,
        "e2160_margin_strata": all(
            float(strata[name][endpoint]) > 0
            for name in ("lower_or_equal", "upper")
            for endpoint in ("net_tercile", "adverse_tercile")
        ),
        "chronological_halves": all(
            float(halves[name][endpoint]) > 0
            for name in ("first", "second")
            for endpoint in ("net_tercile", "adverse_tercile")
        ),
        "plus_1h_transport": all(delay[endpoint][key] > 0 for endpoint in ("net", "adverse") for key in ("rho", "slope", "tercile")),
        "structural_checks": structural["volume_scale_invariance_pass"]
        and structural["latest_information_offset_hours"] == -25,
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
            "outer_tercile_rows_each": outer,
        },
        "unconditional_net_label": {
            "mean": float(np.mean(net)),
            "median": float(np.median(net)),
            "positive_fraction": float(np.mean(net > 0)),
        },
        "net_rho": point["net"]["rho"],
        "net_slope": point["net"]["slope"],
        "net_tercile_effect": point["net"]["tercile"],
        "adverse_rho": point["adverse"]["rho"],
        "adverse_slope": point["adverse"]["slope"],
        "adverse_tercile_effect": point["adverse"]["tercile"],
        "bootstrap_95": bootstrap,
        "folds": folds,
        "positive_net_folds": positive_net_folds,
        "positive_adverse_folds": positive_adverse_folds,
        "positive_net_fold_concentration": concentration,
        "margin_strata": strata,
        "chronological_halves": halves,
        "one_hour_delay": {
            "net_rho": delay["net"]["rho"],
            "net_slope": delay["net"]["slope"],
            "net_tercile_effect": delay["net"]["tercile"],
            "adverse_rho": delay["adverse"]["rho"],
            "adverse_slope": delay["adverse"]["slope"],
            "adverse_tercile_effect": delay["adverse"]["tercile"],
        },
        "structural": structural,
        "gates": gates,
        "all_training_gates_pass": all(gates.values()),
        "_frame": frame,
    }


def null_strategy_metrics() -> dict[str, None]:
    return {
        key: None
        for key in (
            "training_return",
            "training_sharpe",
            "oos_return",
            "oos_sharpe",
            "full_return",
            "full_sharpe",
            "benchmark_comparison",
            "turnover",
            "modeled_fee_drag",
            "maximum_drawdown",
            "edge_per_turnover",
            "fold_year_strategy_breadth",
            "strategy_uncertainty",
        )
    }


def write_outputs(payload: dict[str, object]) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    evidence = OUTPUT / "evidence.json"
    report = OUTPUT / "report.md"
    manifest = OUTPUT / "manifest.json"
    evidence.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
    lines = [
        "# Lagged BNB exchange-ecosystem activity — frozen 1H training diagnostic",
        "",
        f"Family: `{FAMILY_ID}`",
        f"Code head: `{payload['code_head']}`",
        f"Candidate/grid: `0 / 0`",
        f"Source contract passed: `{payload['source_contract_passed']}`",
        f"Sealed OOS accessed: `{payload['sealed_oos_accessed']}`",
        "",
    ]
    if payload.get("source_error"):
        lines += ["## Source failure", "", f"`{payload['source_error']}`", ""]
    for inst_id, result in payload.get("targets", {}).items():
        lines += [
            f"## {inst_id}",
            "",
            f"- opportunities: `{result['opportunities']}`",
            f"- feature distinct / IQR: `{result['feature_distribution']['distinct']}` / `{result['feature_distribution']['iqr']:.10f}`",
            f"- net rho / slope / tercile: `{result['net_rho']:+.6f}` / `{result['net_slope']:+.6f}` / `{10000*result['net_tercile_effect']:+.2f} bp`",
            f"- adverse rho / slope / tercile: `{result['adverse_rho']:+.6f}` / `{result['adverse_slope']:+.6f}` / `{10000*result['adverse_tercile_effect']:+.2f} bp`",
            f"- positive folds net / adverse: `{result['positive_net_folds']}/4` / `{result['positive_adverse_folds']}/4`",
            f"- positive-net fold concentration: `{result['positive_net_fold_concentration']}`",
            f"- all training gates pass: `{result['all_training_gates_pass']}`",
            "",
        ]
    lines += ["## Verdict", "", f"`{payload['verdict']}`", ""]
    report.write_text("\n".join(lines))
    manifest.write_text(
        json.dumps(
            {
                "family_id": FAMILY_ID,
                "code_head": payload["code_head"],
                "evidence_sha256": sha256(evidence.read_bytes()),
                "report_sha256": sha256(report.read_bytes()),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    code_head = os.environ.get("RESEARCH_HEAD_SHA", "unknown")
    sources: dict[str, object] = {}
    source_error: str | None = None
    source_contract_passed = False
    target_returns_accessed = False
    targets: dict[str, object] = {}
    target_frames: dict[str, pd.DataFrame] = {}
    exog: pd.DataFrame | None = None

    try:
        exog, exog_meta = acquire_binance_bnb(persist=True)
        exog_repeat, repeat_meta = acquire_binance_bnb(persist=False)
        repeat_ok = (
            exog.index.equals(exog_repeat.index)
            and canonical_frame_bytes(exog) == canonical_frame_bytes(exog_repeat)
            and exog_meta["normalized_sha256"] == repeat_meta["normalized_sha256"]
        )
        exog_meta["repeat_identity_passed"] = repeat_ok
        if not repeat_ok:
            raise ValueError("BNBUSDT: repeat identity failed")
        sources[f"binance:{EXOG}"] = exog_meta

        for inst_id in TARGETS:
            first, meta = acquire_okx_target(inst_id, persist=True)
            second, repeat = acquire_okx_target(inst_id, persist=False)
            repeat_ok = (
                first.index.equals(second.index)
                and _canonical_csv_bytes(first) == _canonical_csv_bytes(second)
                and meta["normalized_sha256"] == repeat["normalized_sha256"]
            )
            meta["repeat_identity_passed"] = repeat_ok
            if not repeat_ok:
                raise ValueError(f"{inst_id}: repeat identity failed")
            if not first.index.equals(exog.index):
                raise ValueError(f"{inst_id}: common-calendar mismatch")
            target_frames[inst_id] = first
            sources[f"okx:{inst_id}"] = meta
        source_contract_passed = True
    except Exception as exc:
        source_error = f"{type(exc).__name__}: {exc}"

    if source_contract_passed:
        assert exog is not None
        target_returns_accessed = True
        for inst_id in TARGETS:
            full_result = evaluate(inst_id, target_frames[inst_id], exog)
            full_frame = full_result.pop("_frame")
            prefix_result = evaluate(
                inst_id, target_frames[inst_id].iloc[:TRAIN_END], exog.iloc[:TRAIN_END]
            )
            prefix_frame = prefix_result.pop("_frame")
            opportunity_prefix_ok = full_frame.equals(prefix_frame)
            source_prefix_ok = (
                sources[f"okx:{inst_id}"]["training_prefix_sha256"]
                == sha256(_canonical_csv_bytes(target_frames[inst_id].iloc[:TRAIN_END]))
                and sources[f"binance:{EXOG}"]["training_prefix_sha256"]
                == sha256(canonical_frame_bytes(exog.iloc[:TRAIN_END]))
            )
            full_result["opportunity_prefix_invariance_passed"] = opportunity_prefix_ok
            full_result["source_prefix_invariance_passed"] = source_prefix_ok
            full_result["gates"]["prefix_invariance"] = opportunity_prefix_ok and source_prefix_ok
            full_result["all_training_gates_pass"] = all(full_result["gates"].values())
            targets[inst_id] = full_result

    bilateral = source_contract_passed and len(targets) == 2 and all(
        bool(targets[inst_id]["all_training_gates_pass"]) for inst_id in TARGETS
    )
    verdict = SUPPORT if bilateral else (REJECT if source_contract_passed else SOURCE_REJECT)
    payload: dict[str, object] = {
        "schema_version": "bnb-exchange-ecosystem-activity-1h-v1",
        "family_id": FAMILY_ID,
        "code_head": code_head,
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "bar": "1H",
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "fixed_targets": list(TARGETS),
        "fixed_exogenous": EXOG,
        "source_window": {"start": START, "end": END, "rows_per_arm": EXPECTED_ROWS},
        "training": {"start_index": TRAIN_START, "end_index_exclusive": TRAIN_END, "step_hours": 24},
        "sealed_oos": {"start_index": OOS_START, "end_index_exclusive": OOS_END},
        "unread_suffix": {"start_index": OOS_END, "end_index_exclusive": SOURCE_END},
        "feature": {
            "field": "BNBUSDT provider-reported quote-asset volume",
            "definition": "log(mean(v[t-192:t-24])/mean(v[t-912:t-192]))",
            "recent_hours": 168,
            "baseline_hours": 720,
            "latest_information_offset_hours": -25,
            "fixed_sign": "positive",
        },
        "eligibility": "target close[t-25] > close[t-2185]",
        "fee_bps_one_way": 5.0,
        "round_trip_label_bps": 10.0,
        "bootstrap_draws": DRAWS,
        "bootstrap_block_opportunities": BLOCK,
        "bootstrap_seeds": SEEDS,
        "source_contract_passed": source_contract_passed,
        "source_error": source_error,
        "sources": sources,
        "target_returns_accessed": target_returns_accessed,
        "target_oos_accessed": False,
        "sealed_oos_accessed": False,
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
    print(
        "TERMINAL_EVIDENCE_JSON="
        + json.dumps(
            {
                "code_head": code_head,
                "source_contract_passed": source_contract_passed,
                "source_error": source_error,
                "candidate_count": 0,
                "parameter_grid_count": 0,
                "targets": targets,
                "bilateral_training_pass": bilateral,
                "verdict": verdict,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
