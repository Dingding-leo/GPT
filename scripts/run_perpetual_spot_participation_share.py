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

FAMILY_ID = "causal-same-asset-perpetual-vs-spot-participation-share-opportunity-1h-v1"
START = "2023-04-01T00:00:00Z"
END = "2025-12-31T23:00:00Z"
EXPECTED_ROWS = 24_144
TRAIN_START = 2_208
TRAIN_END = 10_800
OOS_START = 10_800
OOS_END = 23_760
SOURCE_END = 24_144
FEE_ONE_WAY = 0.0005
ROUND_TRIP_FEE = 0.0010
E2160 = 2_160
BASELINE = 720
RECENT = 168
SAFETY_LAG = 24
BOOTSTRAP_DRAWS = 5_000
BOOTSTRAP_BLOCK = 7
BOOTSTRAP_SEED = 202608091139
TARGETS = ("BTCUSDT", "ETHUSDT")
SPOT_ROOT = "https://data.binance.vision/data/spot/monthly/klines"
PERP_ROOT = "https://data.binance.vision/data/futures/um/monthly/klines"
OUTPUT = Path("reports/research/perpetual-vs-spot-participation-share-1h-v1")
REJECT = "reject_causal_same_asset_perpetual_vs_spot_participation_share_information_premise_1h_v1"
SOURCE_REJECT = "reject_causal_same_asset_perpetual_vs_spot_participation_share_source_contract_1h_v1"
SUPPORT = "support_causal_same_asset_perpetual_vs_spot_participation_share_for_separate_candidate_predeclaration_1h_v1"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_bytes(frame: pd.DataFrame) -> bytes:
    return frame.reset_index(names="timestamp").to_csv(
        index=False,
        date_format="%Y-%m-%dT%H:%M:%S.%fZ",
        float_format="%.12g",
        lineterminator="\n",
    ).encode()


def trusted_get(url: str, timeout: float = 30.0) -> tuple[bytes, str]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "data.binance.vision":
        raise ValueError(f"untrusted Binance archive URL: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "gpt-quant-research/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read()
        final_url = response.geturl()
    final = urlparse(final_url)
    if final.scheme != "https" or final.hostname != "data.binance.vision":
        raise ValueError(f"archive redirect escaped frozen host: {final_url}")
    if not raw:
        raise ValueError(f"empty archive response: {url}")
    return raw, final_url


def months() -> list[str]:
    return [str(x) for x in pd.period_range("2023-04", "2025-12", freq="M")]


def parse_checksum(raw: bytes, expected_name: str) -> str:
    text = raw.decode("ascii").strip()
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


def month_grid(month: str) -> pd.DatetimeIndex:
    period = pd.Period(month, freq="M")
    start = period.start_time.tz_localize("UTC")
    end = period.end_time.floor("h").tz_localize("UTC")
    return pd.date_range(start, end, freq="h")


def parse_timestamp(raw: str, label: str) -> pd.Timestamp:
    integer = int(raw)
    if integer > 10**14:
        unit = "us"
        divisor = 3_600_000_000
    else:
        unit = "ms"
        divisor = 3_600_000
    if integer % divisor != 0:
        raise ValueError(f"{label}: off-grid open timestamp")
    return pd.to_datetime(integer, unit=unit, utc=True)


def parse_zip(raw: bytes, expected_name: str, month: str) -> pd.DataFrame:
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise ValueError(f"{expected_name}: bad ZIP") from exc
    names = [x for x in archive.namelist() if not x.endswith("/")]
    expected_csv = expected_name.removesuffix(".zip") + ".csv"
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
                ts = parse_timestamp(row[0], expected_name)
            except ValueError:
                if row_number == 1 and "open" in row[0].lower():
                    continue
                raise
            try:
                o, h, l, c, qv = map(float, (row[1], row[2], row[3], row[4], row[7]))
            except ValueError as exc:
                raise ValueError(f"{expected_name}: nonnumeric kline field") from exc
            vals = np.asarray([o, h, l, c, qv], float)
            if not np.isfinite(vals).all() or min(o, h, l, c) <= 0 or qv < 0:
                raise ValueError(f"{expected_name}: invalid finite/positive fields")
            if h < max(o, l, c) or l > min(o, h, c):
                raise ValueError(f"{expected_name}: invalid OHLC ordering")
            rows.append((ts, o, h, l, c, qv))
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
    month_records: list[dict[str, object]] = []
    for month in months():
        filename = f"{symbol}-1h-{month}.zip"
        url = f"{root}/{symbol}/1h/{filename}"
        checksum_url = url + ".CHECKSUM"
        checksum_raw, checksum_final = trusted_get(checksum_url)
        zip_raw, zip_final = trusted_get(url)
        declared = parse_checksum(checksum_raw, filename)
        observed = sha(zip_raw)
        if declared != observed:
            raise ValueError(f"{market}/{filename}: checksum mismatch")
        frame = parse_zip(zip_raw, filename, month)
        frames.append(frame)
        month_records.append(
            {
                "month": month,
                "zip_url": zip_final,
                "checksum_url": checksum_final,
                "declared_zip_sha256": declared,
                "compressed_zip_sha256": observed,
                "checksum_response_sha256": sha(checksum_raw),
                "rows": len(frame),
            }
        )
        time.sleep(0.02)
    combined = pd.concat(frames).sort_index()
    expected = pd.date_range(START, END, freq="h")
    if combined.index.has_duplicates or len(combined) != EXPECTED_ROWS or not combined.index.equals(expected):
        raise ValueError(f"{market}/{symbol}: combined 24,144H grid mismatch")
    raw = canonical_bytes(combined)
    path = source_dir / f"binance-{market}-{symbol}-1h.csv"
    path.write_bytes(raw)
    return combined, {
        "provider": "Binance Public Data",
        "market_type": market,
        "symbol": symbol,
        "bar": "1h",
        "rows": len(combined),
        "start": str(combined.index[0]),
        "end": str(combined.index[-1]),
        "normalized_sha256": sha(raw),
        "training_prefix_sha256": sha(canonical_bytes(combined.iloc[:TRAIN_END])),
        "months": month_records,
        "month_count": len(month_records),
        "passed": True,
    }


def share_frame(spot: pd.DataFrame, perp: pd.DataFrame) -> pd.Series:
    if not spot.index.equals(perp.index):
        raise ValueError("spot/perpetual common grid mismatch")
    s = spot["quote_volume"].to_numpy(float)
    p = perp["quote_volume"].to_numpy(float)
    denominator = s + p
    if np.any(denominator <= 0):
        raise ValueError("zero total quote volume hour")
    share = p / denominator
    if not np.isfinite(share).all() or np.min(share) < 0 or np.max(share) > 1:
        raise ValueError("perpetual share outside [0,1]")
    scaled = (p * 7.25) / ((p * 7.25) + (s * 7.25))
    if np.max(np.abs(scaled - share)) > 1e-12:
        raise ValueError("quote-volume common-scale invariance failed")
    return pd.Series(share, index=spot.index, name="perp_share")


def anchor_candidates() -> list[int]:
    return [t for t in range(TRAIN_START, TRAIN_END, 24) if t + 25 < TRAIN_END]


def opportunity_frame(spot: pd.DataFrame, perp: pd.DataFrame) -> pd.DataFrame:
    share = share_frame(spot, perp).to_numpy(float)
    close = spot["close"].to_numpy(float)
    open_px = spot["open"].to_numpy(float)
    low = spot["low"].to_numpy(float)
    rows: list[dict[str, object]] = []
    for t in anchor_candidates():
        latest = t - 25
        old = t - 2185
        margin = close[latest] / close[old] - 1.0
        if margin <= 0:
            continue
        baseline = share[t - 912 : t - 192]
        recent = share[t - 192 : t - 24]
        if len(baseline) != BASELINE or len(recent) != RECENT:
            raise ValueError("feature window length mismatch")
        feature = float(np.mean(recent) - np.mean(baseline))
        entry = open_px[t]
        exit_px = open_px[t + 24]
        net = float(math.log(exit_px / entry) - ROUND_TRIP_FEE)
        adverse = float(np.min(np.log(low[t : t + 25] / entry) - ROUND_TRIP_FEE))
        dentry = open_px[t + 1]
        dexit = open_px[t + 25]
        dnet = float(math.log(dexit / dentry) - ROUND_TRIP_FEE)
        dadverse = float(np.min(np.log(low[t + 1 : t + 26] / dentry) - ROUND_TRIP_FEE))
        rows.append(
            {
                "t": t,
                "timestamp": str(spot.index[t]),
                "feature": feature,
                "e2160_margin": float(margin),
                "net": net,
                "adverse": adverse,
                "delay_net": dnet,
                "delay_adverse": dadverse,
            }
        )
    return pd.DataFrame(rows)


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
    return float(np.dot(z - np.mean(z), y - np.mean(y)) / np.dot(z - np.mean(z), z - np.mean(z)))


def tercile_effect(x: np.ndarray, y: np.ndarray) -> float:
    order = np.argsort(x, kind="mergesort")
    n = len(order)
    k = n // 3
    if k < 1:
        return float("nan")
    return float(np.mean(y[order[-k:]]) - np.mean(y[order[:k]]))


def triple(x: np.ndarray, y: np.ndarray) -> dict[str, float]:
    return {
        "rho": spearman(x, y),
        "slope": std_slope(x, y),
        "tercile": tercile_effect(x, y),
    }


def bootstrap_intervals(x: np.ndarray, net: np.ndarray, adverse: np.ndarray) -> dict[str, list[float]]:
    n = len(x)
    starts = np.arange(0, n - BOOTSTRAP_BLOCK + 1)
    if len(starts) < 1:
        raise ValueError("not enough opportunities for bootstrap")
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    draws = {"net_rho": [], "net_slope": [], "adverse_rho": [], "adverse_slope": []}
    blocks_needed = math.ceil(n / BOOTSTRAP_BLOCK)
    for _ in range(BOOTSTRAP_DRAWS):
        picked: list[int] = []
        for start in rng.choice(starts, size=blocks_needed, replace=True):
            picked.extend(range(int(start), int(start) + BOOTSTRAP_BLOCK))
        idx = np.asarray(picked[:n], int)
        nx, nn, na = x[idx], net[idx], adverse[idx]
        draws["net_rho"].append(spearman(nx, nn))
        draws["net_slope"].append(std_slope(nx, nn))
        draws["adverse_rho"].append(spearman(nx, na))
        draws["adverse_slope"].append(std_slope(nx, na))
    return {k: [float(np.quantile(v, 0.025)), float(np.quantile(v, 0.975))] for k, v in draws.items()}


def fold_stats(frame: pd.DataFrame) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for i, idx in enumerate(np.array_split(np.arange(len(frame)), 4), 1):
        sub = frame.iloc[idx]
        x = sub["feature"].to_numpy(float)
        net = sub["net"].to_numpy(float)
        adverse = sub["adverse"].to_numpy(float)
        out.append(
            {
                "fold": i,
                "rows": len(sub),
                "net_slope": std_slope(x, net),
                "adverse_slope": std_slope(x, adverse),
            }
        )
    return out


def margin_strata(frame: pd.DataFrame) -> dict[str, dict[str, object]]:
    median = float(frame["e2160_margin"].median())
    out: dict[str, dict[str, object]] = {}
    masks = {
        "lower_or_equal": frame["e2160_margin"] <= median,
        "upper": frame["e2160_margin"] > median,
    }
    for name, mask in masks.items():
        sub = frame.loc[mask]
        x = sub["feature"].to_numpy(float)
        out[name] = {
            "rows": len(sub),
            "net_tercile": tercile_effect(x, sub["net"].to_numpy(float)),
            "adverse_tercile": tercile_effect(x, sub["adverse"].to_numpy(float)),
        }
    return {"median_margin": median, **out}


def summarize(symbol: str, frame: pd.DataFrame, prefix_frame: pd.DataFrame) -> dict[str, object]:
    if len(frame) != len(prefix_frame):
        raise ValueError(f"{symbol}: prefix opportunity count changed")
    compare_cols = ["t", "feature", "e2160_margin", "net", "adverse", "delay_net", "delay_adverse"]
    if not np.allclose(
        frame[compare_cols[1:]].to_numpy(float),
        prefix_frame[compare_cols[1:]].to_numpy(float),
        rtol=0,
        atol=1e-14,
    ) or not frame["t"].equals(prefix_frame["t"]):
        raise ValueError(f"{symbol}: source/feature/label prefix invariance failed")
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
    intervals = bootstrap_intervals(x, net, adverse)
    folds = fold_stats(frame)
    negative_net_folds = sum(float(f["net_slope"]) < 0 for f in folds)
    negative_adverse_folds = sum(float(f["adverse_slope"]) < 0 for f in folds)
    neg_abs = [abs(float(f["net_slope"])) for f in folds if float(f["net_slope"]) < 0]
    concentration = float(max(neg_abs) / sum(neg_abs)) if neg_abs else None
    strata = margin_strata(frame)
    k = len(frame) // 3
    gates = {
        "opportunities_ge_180": len(frame) >= 180,
        "feature_support": distinct >= 100 and iqr > 0,
        "outer_terciles_ge_50": k >= 50,
        "net_direction": base_net["rho"] < 0 and base_net["slope"] < 0 and base_net["tercile"] < 0,
        "adverse_direction": base_adverse["rho"] < 0 and base_adverse["slope"] < 0 and base_adverse["tercile"] < 0,
        "dependence_upper_bounds_negative": all(intervals[key][1] < 0 for key in intervals),
        "temporal_breadth": negative_net_folds >= 3 and negative_adverse_folds >= 3,
        "negative_net_fold_concentration_le_60pct": concentration is not None and concentration <= 0.60,
        "margin_strata": all(
            float(strata[name][endpoint]) < 0
            for name in ("lower_or_equal", "upper")
            for endpoint in ("net_tercile", "adverse_tercile")
        ),
        "plus_1h_transport": all(value < 0 for value in delayed_net.values()) and all(value < 0 for value in delayed_adverse.values()),
        "prefix_invariance": True,
        "structural_identities": True,
    }
    return {
        "opportunities": len(frame),
        "feature_distribution": {
            "distinct": distinct,
            "iqr": iqr,
            "min": float(np.min(x)),
            "max": float(np.max(x)),
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
        "negative_net_folds": negative_net_folds,
        "negative_adverse_folds": negative_adverse_folds,
        "negative_net_fold_concentration": concentration,
        "margin_strata": strata,
        "one_hour_delay": {
            "net_rho": delayed_net["rho"],
            "net_slope": delayed_net["slope"],
            "net_tercile_effect": delayed_net["tercile"],
            "adverse_rho": delayed_adverse["rho"],
            "adverse_slope": delayed_adverse["slope"],
            "adverse_tercile_effect": delayed_adverse["tercile"],
        },
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
    }


def write_outputs(payload: dict[str, object]) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    evidence = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    evidence_path = OUTPUT / "evidence.json"
    evidence_path.write_text(evidence)
    report_lines = [
        "# Same-asset perpetual-vs-spot participation share — frozen 1H training diagnostic",
        "",
        f"Family: `{FAMILY_ID}`",
        f"Code head: `{payload['code_head']}`",
        f"Source contract passed: `{payload['source_contract_passed']}`",
        f"Candidate/grid: `{payload['candidate_count']} / {payload['parameter_grid_count']}`",
        f"Sealed OOS accessed: `{payload['sealed_oos_accessed']}`",
        "",
    ]
    for symbol, result in payload.get("targets", {}).items():
        report_lines.extend(
            [
                f"## {symbol}",
                f"- opportunities: {result['opportunities']}",
                f"- feature distinct/IQR: {result['feature_distribution']['distinct']} / {result['feature_distribution']['iqr']:.8f}",
                f"- net rho/slope/tercile: {result['net_rho']:+.6f} / {result['net_slope']:+.6f} / {10000*result['net_tercile_effect']:+.2f} bp",
                f"- adverse rho/slope/tercile: {result['adverse_rho']:+.6f} / {result['adverse_slope']:+.6f} / {10000*result['adverse_tercile_effect']:+.2f} bp",
                f"- negative folds net/adverse: {result['negative_net_folds']}/4 / {result['negative_adverse_folds']}/4",
                f"- all gates pass: {result['all_training_gates_pass']}",
                "",
            ]
        )
    report_lines.extend(["## Verdict", "", f"`{payload['verdict']}`", ""])
    report_path = OUTPUT / "report.md"
    report_path.write_text("\n".join(report_lines))
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
            perp, perp_meta = acquire(symbol, "perpetual", source_dir)
            if not spot.index.equals(perp.index):
                raise ValueError(f"{symbol}: spot/perpetual calendar mismatch")
            panels[symbol] = (spot, perp)
            sources[f"{symbol}_spot"] = spot_meta
            sources[f"{symbol}_perpetual"] = perp_meta
        source_passed = True
        target_returns_accessed = True
        for symbol, (spot, perp) in panels.items():
            full = opportunity_frame(spot, perp)
            prefix = opportunity_frame(spot.iloc[:TRAIN_END].copy(), perp.iloc[:TRAIN_END].copy())
            targets[symbol] = summarize(symbol, full, prefix)
    except Exception as exc:
        source_error = f"{type(exc).__name__}: {exc}"

    bilateral = source_passed and len(targets) == 2 and all(
        bool(result["all_training_gates_pass"]) for result in targets.values()
    )
    verdict = SUPPORT if bilateral else (REJECT if source_passed else SOURCE_REJECT)
    payload: dict[str, object] = {
        "schema_version": "perpetual-vs-spot-participation-share-1h-v1",
        "family_id": FAMILY_ID,
        "code_head": code_head,
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "bar": "1H",
        "provider": "Binance Public Data monthly archives",
        "source_window": {"start": START, "end": END, "rows_per_arm": EXPECTED_ROWS},
        "training": {"start_index": TRAIN_START, "end_index_exclusive": TRAIN_END, "step_hours": 24},
        "sealed_oos": {"start_index": OOS_START, "end_index_exclusive": OOS_END},
        "unread_suffix": {"start_index": OOS_END, "end_index_exclusive": SOURCE_END},
        "fee_bps_one_way": 5.0,
        "round_trip_label_bps": 10.0,
        "candidate_count": 0,
        "parameter_grid_count": 0,
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
