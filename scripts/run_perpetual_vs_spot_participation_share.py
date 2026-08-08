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
ISSUE_NUMBER = 1139
BASE_MAIN = "5a0fcc97d1a882f8223656c51f5bb8055f534e38"
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
BOOTSTRAP_DRAWS = 5_000
BOOTSTRAP_BLOCK = 7
BOOTSTRAP_SEED = 202608091139
SPOT_ROOT = "https://data.binance.vision/data/spot/monthly/klines"
PERP_ROOT = "https://data.binance.vision/data/futures/um/monthly/klines"
OUTPUT = Path("reports/research") / FAMILY_ID
TARGETS = {
    "BTC-USDT": "BTCUSDT",
    "ETH-USDT": "ETHUSDT",
}
REJECT = "reject_causal_same_asset_perpetual_vs_spot_participation_share_information_premise_1h_v1"
SOURCE_REJECT = "reject_causal_same_asset_perpetual_vs_spot_participation_share_source_contract_1h_v1"
SUPPORT = "support_causal_same_asset_perpetual_vs_spot_participation_share_for_separate_candidate_predeclaration_1h_v1"

STRATEGY_METRICS_NULL = {
    "train_strategy_return": None,
    "train_strategy_sharpe": None,
    "oos_strategy_return": None,
    "oos_strategy_sharpe": None,
    "full_strategy_return": None,
    "full_strategy_sharpe": None,
    "benchmark_comparison": None,
    "turnover": None,
    "modeled_fee_drag": None,
    "maximum_drawdown": None,
    "edge_per_turnover": None,
    "fold_year_strategy_breadth": None,
    "strategy_uncertainty": None,
    "position_path": None,
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_frame_bytes(frame: pd.DataFrame) -> bytes:
    return frame.reset_index(names="timestamp").to_csv(
        index=False,
        date_format="%Y-%m-%dT%H:%M:%S.%fZ",
        float_format="%.12g",
        lineterminator="\n",
    ).encode()


def _trusted_get(url: str, timeout: float = 30.0) -> tuple[bytes, str]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "data.binance.vision":
        raise ValueError(f"archive URL outside frozen Binance host: {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "gpt-quant-research/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
        final_url = response.geturl()
    final = urlparse(final_url)
    if final.scheme != "https" or final.hostname != "data.binance.vision":
        raise ValueError(f"archive redirect left frozen Binance host: {final_url}")
    if not raw:
        raise ValueError(f"empty archive response: {url}")
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
    end = period.end_time.floor("h").tz_localize("UTC")
    return pd.date_range(start, end, freq="h")


def _archive_timestamp(raw_value: str, expected_name: str, row_number: int) -> tuple[pd.Timestamp, str]:
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{expected_name}: invalid open time on row {row_number}") from exc
    if value >= 100_000_000_000_000:
        if value % 3_600_000_000 != 0:
            raise ValueError(f"{expected_name}: off-grid microsecond open time")
        return pd.to_datetime(value, unit="us", utc=True), "us"
    if value % 3_600_000 != 0:
        raise ValueError(f"{expected_name}: off-grid millisecond open time")
    return pd.to_datetime(value, unit="ms", utc=True), "ms"


def _parse_binance_zip(
    raw: bytes,
    expected_name: str,
    month: str,
) -> tuple[pd.DataFrame, dict[str, int]]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise ValueError(f"{expected_name}: invalid ZIP") from exc
    names = [name for name in archive.namelist() if not name.endswith("/")]
    expected_csv = expected_name.removesuffix(".zip") + ".csv"
    if names != [expected_csv]:
        raise ValueError(f"{expected_name}: unexpected ZIP members {names}")

    rows: list[tuple[pd.Timestamp, float, float, float, float, float]] = []
    timestamp_units = {"ms": 0, "us": 0}
    with archive.open(expected_csv) as handle:
        reader = csv.reader(io.TextIOWrapper(handle, encoding="utf-8", newline=""))
        for row_number, row in enumerate(reader, start=1):
            if not row:
                continue
            if len(row) != 12:
                raise ValueError(f"{expected_name}: row {row_number} has {len(row)} columns")
            try:
                timestamp, unit = _archive_timestamp(row[0], expected_name, row_number)
            except ValueError:
                if row_number == 1 and "open" in row[0].strip().lower():
                    continue
                raise
            timestamp_units[unit] += 1
            try:
                open_price = float(row[1])
                high = float(row[2])
                low = float(row[3])
                close = float(row[4])
                quote_volume = float(row[7])
            except ValueError as exc:
                raise ValueError(f"{expected_name}: non-numeric kline field on row {row_number}") from exc
            values = np.asarray([open_price, high, low, close, quote_volume], dtype=float)
            if not np.isfinite(values).all():
                raise ValueError(f"{expected_name}: non-finite kline field")
            if min(open_price, high, low, close) <= 0:
                raise ValueError(f"{expected_name}: non-positive OHLC")
            if high < max(open_price, low, close) or low > min(open_price, high, close):
                raise ValueError(f"{expected_name}: invalid OHLC ordering")
            if quote_volume < 0:
                raise ValueError(f"{expected_name}: negative quote asset volume")
            rows.append((timestamp, open_price, high, low, close, quote_volume))

    frame = pd.DataFrame(
        rows,
        columns=["timestamp", "open", "high", "low", "close", "quote_volume"],
    ).set_index("timestamp")
    if frame.index.has_duplicates:
        raise ValueError(f"{expected_name}: duplicate open time")
    frame = frame.sort_index()
    expected_grid = _month_grid(month)
    if len(frame) != len(expected_grid) or not frame.index.equals(expected_grid):
        raise ValueError(
            f"{expected_name}: month grid mismatch; expected {len(expected_grid)}, got {len(frame)}"
        )
    return frame, timestamp_units


def _acquire_archive_arm(
    symbol: str,
    market_type: str,
    source_dir: Path,
) -> tuple[pd.DataFrame, dict[str, object]]:
    if market_type == "spot":
        root = SPOT_ROOT
    elif market_type == "perpetual":
        root = PERP_ROOT
    else:
        raise ValueError(f"unexpected market type {market_type}")

    frames: list[pd.DataFrame] = []
    months: list[dict[str, object]] = []
    unit_totals = {"ms": 0, "us": 0}
    for month in _months():
        filename = f"{symbol}-1h-{month}.zip"
        url = f"{root}/{symbol}/1h/{filename}"
        checksum_url = url + ".CHECKSUM"
        checksum_raw, checksum_final = _trusted_get(checksum_url)
        zip_raw, zip_final = _trusted_get(url)
        declared = _parse_checksum(checksum_raw, filename)
        observed = _sha(zip_raw)
        if declared != observed:
            raise ValueError(f"{market_type}:{filename}: checksum mismatch")
        frame, units = _parse_binance_zip(zip_raw, filename, month)
        for key in unit_totals:
            unit_totals[key] += units[key]
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
                "timestamp_units": units,
            }
        )
        (source_dir / f"{market_type}-{symbol}-{month}.CHECKSUM").write_bytes(checksum_raw)
        time.sleep(0.025)

    combined = pd.concat(frames).sort_index()
    expected = pd.date_range(START, END, freq="h")
    if combined.index.has_duplicates:
        raise ValueError(f"{market_type}:{symbol}: duplicate hours across monthly archives")
    if len(combined) != EXPECTED_ROWS or not combined.index.equals(expected):
        raise ValueError(f"{market_type}:{symbol}: combined 24,144H grid mismatch")
    canonical = _canonical_frame_bytes(combined)
    (source_dir / f"binance-{market_type}-{symbol}-1h.csv").write_bytes(canonical)
    return combined, {
        "provider": "Binance Public Data",
        "market_type": market_type,
        "symbol": symbol,
        "bar": "1h",
        "rows": len(combined),
        "start": str(combined.index[0]),
        "end": str(combined.index[-1]),
        "normalized_sha256": _sha(canonical),
        "training_prefix_sha256": _sha(_canonical_frame_bytes(combined.iloc[:TRAIN_END])),
        "month_count": len(months),
        "month_order": [item["month"] for item in months],
        "timestamp_units": unit_totals,
        "months": months,
        "passed": True,
    }


def _perpetual_share(spot: pd.DataFrame, perpetual: pd.DataFrame) -> np.ndarray:
    if not spot.index.equals(perpetual.index):
        raise ValueError("spot/perpetual source grids differ")
    spot_volume = spot["quote_volume"].to_numpy(float)
    perp_volume = perpetual["quote_volume"].to_numpy(float)
    denominator = spot_volume + perp_volume
    share = np.full(len(spot), np.nan, dtype=float)
    valid = denominator > 0
    share[valid] = perp_volume[valid] / denominator[valid]
    finite = np.isfinite(share)
    if finite.any() and (float(np.nanmin(share)) < -1e-12 or float(np.nanmax(share)) > 1.0 + 1e-12):
        raise ValueError("perpetual share outside [0,1]")

    scale = 7.25
    scaled_denominator = scale * perp_volume + scale * spot_volume
    scaled = np.full(len(spot), np.nan, dtype=float)
    scaled_valid = scaled_denominator > 0
    scaled[scaled_valid] = (scale * perp_volume[scaled_valid]) / scaled_denominator[scaled_valid]
    same_mask = finite & np.isfinite(scaled)
    if not np.array_equal(finite, np.isfinite(scaled)):
        raise ValueError("share validity changed under common positive volume scaling")
    if same_mask.any() and float(np.max(np.abs(share[same_mask] - scaled[same_mask]))) > 1e-12:
        raise ValueError("perpetual share is not common-volume-scale invariant")
    return share


def _anchors() -> list[int]:
    return [t for t in range(TRAIN_START, TRAIN_END, 24) if t + 25 < TRAIN_END]


def _opportunities(spot: pd.DataFrame, perpetual: pd.DataFrame) -> pd.DataFrame:
    share = _perpetual_share(spot, perpetual)
    close = spot["close"].to_numpy(float)
    open_price = spot["open"].to_numpy(float)
    low = spot["low"].to_numpy(float)
    rows: list[dict[str, float | int | bool]] = []

    for t in _anchors():
        latest = t - 25
        old = t - 2185
        if latest < 0 or old < 0 or latest - old != E2160_HOURS:
            raise ValueError("delayed E2160 index arithmetic failed")
        margin = math.log(float(close[latest]) / float(close[old]))
        if margin <= 0:
            continue

        baseline_start = t - 912
        baseline_end = t - 192
        recent_start = t - 192
        recent_end = t - 24
        if baseline_end - baseline_start != BASELINE_HOURS:
            raise ValueError("baseline window width mismatch")
        if recent_end - recent_start != RECENT_HOURS:
            raise ValueError("recent window width mismatch")
        if baseline_end != recent_start or recent_end - 1 != latest:
            raise ValueError("feature windows overlap or violate t-25 lag")

        baseline_values = share[baseline_start:baseline_end]
        recent_values = share[recent_start:recent_end]
        feature_valid = bool(np.isfinite(baseline_values).all() and np.isfinite(recent_values).all())
        if not feature_valid:
            feature = float("nan")
        else:
            feature = float(np.mean(recent_values) - np.mean(baseline_values))

        entry = float(open_price[t])
        delay_entry = float(open_price[t + 1])
        rows.append(
            {
                "t": t,
                "feature": feature,
                "feature_valid": feature_valid,
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
                "latest_feature_input": recent_end - 1,
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
    lower = order[:count]
    upper = order[-count:]
    return float(yv[upper].mean() - yv[lower].mean()), len(lower), len(upper)


def _bootstrap(
    x: np.ndarray,
    net: np.ndarray,
    adverse: np.ndarray,
) -> dict[str, list[float]]:
    n = len(x)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    draws = np.full((BOOTSTRAP_DRAWS, 4), np.nan, dtype=float)
    for draw in range(BOOTSTRAP_DRAWS):
        selected: list[int] = []
        while len(selected) < n:
            start = int(rng.integers(0, n - BOOTSTRAP_BLOCK + 1))
            selected.extend(range(start, start + BOOTSTRAP_BLOCK))
        idx = np.asarray(selected[:n], dtype=int)
        draws[draw] = (
            _rho(x[idx], net[idx]),
            _slope(x[idx], net[idx]),
            _rho(x[idx], adverse[idx]),
            _slope(x[idx], adverse[idx]),
        )
    names = ("net_rho", "net_slope", "adverse_rho", "adverse_slope")
    return {
        name: [
            float(np.nanquantile(draws[:, i], 0.025)),
            float(np.nanquantile(draws[:, i], 0.975)),
        ]
        for i, name in enumerate(names)
    }


def _folds(opportunities: pd.DataFrame) -> tuple[list[dict[str, float | int]], float]:
    ordered = opportunities.sort_values("t").reset_index(drop=True)
    output: list[dict[str, float | int]] = []
    for fold_number, indices in enumerate(np.array_split(np.arange(len(ordered)), 4), start=1):
        fold = ordered.iloc[indices]
        x = fold["feature"].to_numpy(float)
        output.append(
            {
                "fold": fold_number,
                "n": len(fold),
                "net_slope": _slope(x, fold["net"]),
                "adverse_slope": _slope(x, fold["adverse"]),
            }
        )
    negative = [
        abs(float(item["net_slope"]))
        for item in output
        if math.isfinite(float(item["net_slope"])) and float(item["net_slope"]) < 0
    ]
    concentration = float("inf") if not negative else max(negative) / sum(negative)
    return output, float(concentration)


def _margin_strata(opportunities: pd.DataFrame) -> dict[str, object]:
    median = float(opportunities["margin"].median())
    output: dict[str, object] = {"median_margin": median}
    for name, subset in (
        ("lower", opportunities[opportunities["margin"] <= median]),
        ("upper", opportunities[opportunities["margin"] > median]),
    ):
        net_effect, net_low, net_high = _tercile(subset["feature"], subset["net"])
        adverse_effect, adverse_low, adverse_high = _tercile(
            subset["feature"], subset["adverse"]
        )
        output[name] = {
            "n": len(subset),
            "net_tercile_effect": net_effect,
            "adverse_tercile_effect": adverse_effect,
            "net_tercile_counts": [net_low, net_high],
            "adverse_tercile_counts": [adverse_low, adverse_high],
        }
    return output


def _target_result(
    spot: pd.DataFrame,
    perpetual: pd.DataFrame,
    target_name: str,
) -> dict[str, object]:
    full = _opportunities(spot, perpetual)
    prefix = _opportunities(spot.iloc[:TRAIN_END].copy(), perpetual.iloc[:TRAIN_END].copy())
    compare_columns = [
        "t",
        "feature",
        "feature_valid",
        "margin",
        "net",
        "adverse",
        "delay_net",
        "delay_adverse",
        "baseline_start",
        "baseline_end",
        "recent_start",
        "recent_end",
        "latest_feature_input",
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
        raise ValueError(f"{target_name}: no positive delayed-E2160 training opportunities")

    valid = full[full["feature_valid"] & np.isfinite(full["feature"])].copy()
    if valid.empty:
        raise ValueError(f"{target_name}: no valid participation-share features")
    x = valid["feature"].to_numpy(float)
    net = valid["net"].to_numpy(float)
    adverse = valid["adverse"].to_numpy(float)

    net_rho = _rho(x, net)
    net_slope = _slope(x, net)
    adverse_rho = _rho(x, adverse)
    adverse_slope = _slope(x, adverse)
    net_tercile, net_low_count, net_high_count = _tercile(x, net)
    adverse_tercile, adverse_low_count, adverse_high_count = _tercile(x, adverse)
    bootstrap = _bootstrap(x, net, adverse)
    folds, concentration = _folds(valid)
    negative_net_folds = sum(float(item["net_slope"]) < 0 for item in folds)
    negative_adverse_folds = sum(float(item["adverse_slope"]) < 0 for item in folds)
    strata = _margin_strata(valid)

    delay_net_rho = _rho(x, valid["delay_net"])
    delay_net_slope = _slope(x, valid["delay_net"])
    delay_net_tercile, _, _ = _tercile(x, valid["delay_net"])
    delay_adverse_rho = _rho(x, valid["delay_adverse"])
    delay_adverse_slope = _slope(x, valid["delay_adverse"])
    delay_adverse_tercile, _, _ = _tercile(x, valid["delay_adverse"])

    distribution = {
        "distinct": int(valid["feature"].nunique()),
        "iqr": float(valid["feature"].quantile(0.75) - valid["feature"].quantile(0.25)),
        "q25": float(valid["feature"].quantile(0.25)),
        "median": float(valid["feature"].median()),
        "q75": float(valid["feature"].quantile(0.75)),
    }
    strata_negative = all(
        float(strata[stratum][metric]) < 0
        for stratum in ("lower", "upper")
        for metric in ("net_tercile_effect", "adverse_tercile_effect")
    )
    structural = bool(
        (valid["baseline_end"] == valid["recent_start"]).all()
        and (valid["baseline_end"] - valid["baseline_start"] == BASELINE_HOURS).all()
        and (valid["recent_end"] - valid["recent_start"] == RECENT_HOURS).all()
        and (valid["latest_feature_input"] <= valid["t"] - 25).all()
        and (valid["e2160_latest"] == valid["t"] - 25).all()
        and (valid["e2160_latest"] - valid["e2160_old"] == E2160_HOURS).all()
        and prefix_invariant
    )

    gates = {
        "source_and_common_grid": spot.index.equals(perpetual.index),
        "minimum_opportunities": len(valid) >= 180,
        "feature_support": distribution["distinct"] >= 100 and distribution["iqr"] > 0,
        "tercile_sample_size": min(
            net_low_count, net_high_count, adverse_low_count, adverse_high_count
        ) >= 50,
        "negative_net_association": net_rho < 0 and net_slope < 0,
        "negative_adverse_association": adverse_rho < 0 and adverse_slope < 0,
        "negative_tercile_effects": net_tercile < 0 and adverse_tercile < 0,
        "negative_dependence_upper_bounds": all(interval[1] < 0 for interval in bootstrap.values()),
        "fold_breadth": negative_net_folds >= 3 and negative_adverse_folds >= 3,
        "fold_concentration": math.isfinite(concentration) and concentration <= 0.60,
        "endpoint_margin_stratification": strata_negative,
        "one_hour_delay_transport": (
            delay_net_rho < 0
            and delay_net_slope < 0
            and delay_net_tercile < 0
            and delay_adverse_rho < 0
            and delay_adverse_slope < 0
            and delay_adverse_tercile < 0
        ),
        "prefix_invariance": prefix_invariant,
        "structural_identities": structural,
    }

    stable = valid.to_csv(index=False, float_format="%.17g", lineterminator="\n").encode()
    return {
        "positive_e2160_opportunities_before_feature_validity": len(full),
        "opportunities": len(valid),
        "invalid_share_window_opportunities": len(full) - len(valid),
        "opportunity_sha256": _sha(stable),
        "feature_distribution": distribution,
        "net_rho": net_rho,
        "net_slope": net_slope,
        "net_tercile_effect": net_tercile,
        "adverse_rho": adverse_rho,
        "adverse_slope": adverse_slope,
        "adverse_tercile_effect": adverse_tercile,
        "tercile_counts": {
            "net": [net_low_count, net_high_count],
            "adverse": [adverse_low_count, adverse_high_count],
        },
        "bootstrap_95": bootstrap,
        "folds": folds,
        "negative_net_folds": negative_net_folds,
        "negative_adverse_folds": negative_adverse_folds,
        "negative_net_fold_concentration": concentration,
        "margin_strata": strata,
        "one_hour_delay": {
            "net_rho": delay_net_rho,
            "net_slope": delay_net_slope,
            "net_tercile_effect": delay_net_tercile,
            "adverse_rho": delay_adverse_rho,
            "adverse_slope": delay_adverse_slope,
            "adverse_tercile_effect": delay_adverse_tercile,
        },
        "chronology": {
            "target_oos_labels_accessed": False,
            "latest_feature_input_rule": "<=t-25",
            "prefix_invariant": prefix_invariant,
            "structural_checks": structural,
            "fee_accounting_exact": True,
        },
        "gates": {key: bool(value) for key, value in gates.items()},
        "all_training_gates_pass": bool(all(gates.values())),
    }


def _write(payload: dict[str, object]) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    evidence = (json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    (OUTPUT / "evidence.json").write_bytes(evidence)
    evidence_sha = _sha(evidence)

    report_lines = [
        "# Same-asset perpetual-vs-spot participation share — training-only 1H diagnostic",
        "",
        f"Family: `{FAMILY_ID}`",
        f"Issue: `#{ISSUE_NUMBER}`",
        f"Exact head: `{payload['exact_head']}`",
        f"Verdict: `{payload['verdict']}`",
        f"Source contract passed: `{payload['source_contract_passed']}`",
        "Candidate/grid: `0/0`",
        "Fee: exactly `5 bps` one way inside each 24H label",
        "Target OOS labels accessed: `false`",
        "Executable strategy performance: `null`",
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
                    report_lines.extend(
                        [
                            f"### {name}",
                            "",
                            f"- opportunities: `{result.get('opportunities')}`",
                            f"- net rho / slope / tercile: `{result.get('net_rho')}` / `{result.get('net_slope')}` / `{result.get('net_tercile_effect')}`",
                            f"- adverse rho / slope / tercile: `{result.get('adverse_rho')}` / `{result.get('adverse_slope')}` / `{result.get('adverse_tercile_effect')}`",
                            f"- negative folds net/adverse: `{result.get('negative_net_folds')}/4` / `{result.get('negative_adverse_folds')}/4`",
                            f"- all training gates pass: `{result.get('all_training_gates_pass')}`",
                            "",
                        ]
                    )
    report = "\n".join(report_lines) + "\n"
    (OUTPUT / "report.md").write_text(report, encoding="utf-8")
    report_sha = _sha(report.encode())

    manifest = {
        "family_id": FAMILY_ID,
        "issue_number": ISSUE_NUMBER,
        "exact_head": payload["exact_head"],
        "verdict": payload["verdict"],
        "evidence_sha256": evidence_sha,
        "report_sha256": report_sha,
    }
    manifest_raw = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
    (OUTPUT / "manifest.json").write_bytes(manifest_raw)
    (OUTPUT / "evidence.sha256").write_text(evidence_sha + "\n", encoding="utf-8")
    (OUTPUT / "report.sha256").write_text(report_sha + "\n", encoding="utf-8")
    (OUTPUT / "manifest.sha256").write_text(_sha(manifest_raw) + "\n", encoding="utf-8")

    print(json.dumps(payload, sort_keys=True, indent=2, allow_nan=False))
    print("EVIDENCE_SHA256", evidence_sha)
    print("REPORT_SHA256", report_sha)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    source_dir = OUTPUT / "sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    exact_head = os.environ.get("RESEARCH_HEAD_SHA", os.environ.get("GITHUB_SHA", "local"))

    base_payload: dict[str, object] = {
        "family_id": FAMILY_ID,
        "issue_number": ISSUE_NUMBER,
        "exact_head": exact_head,
        "base_main": BASE_MAIN,
        "targets_fixed_preperformance": list(TARGETS),
        "source_arms_fixed_preperformance": [
            f"spot:{symbol}" for symbol in TARGETS.values()
        ] + [f"perpetual:{symbol}" for symbol in TARGETS.values()],
        "provider": "Binance Public Data monthly archives + companion CHECKSUM",
        "bar": "1H",
        "calendar": [START, END],
        "rows_per_source_arm": EXPECTED_ROWS,
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
        "target_oos_accessed": False,
        "unread_suffix_accessed": False,
        "strategy_performance_accessed": False,
        "canonical_mutation": False,
        "correction_authority": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "strategy_metrics": STRATEGY_METRICS_NULL,
    }

    sources: dict[str, object] = {}
    spot_frames: dict[str, pd.DataFrame] = {}
    perp_frames: dict[str, pd.DataFrame] = {}
    try:
        for target_name, symbol in TARGETS.items():
            spot, spot_meta = _acquire_archive_arm(symbol, "spot", source_dir)
            spot_frames[target_name] = spot
            sources[f"spot:{symbol}"] = spot_meta
        for target_name, symbol in TARGETS.items():
            perp, perp_meta = _acquire_archive_arm(symbol, "perpetual", source_dir)
            perp_frames[target_name] = perp
            sources[f"perpetual:{symbol}"] = perp_meta

        common_grid = pd.date_range(START, END, freq="h")
        for target_name in TARGETS:
            if not spot_frames[target_name].index.equals(common_grid):
                raise ValueError(f"{target_name}: spot common grid mismatch")
            if not perp_frames[target_name].index.equals(common_grid):
                raise ValueError(f"{target_name}: perpetual common grid mismatch")
            if not spot_frames[target_name].index.equals(perp_frames[target_name].index):
                raise ValueError(f"{target_name}: spot/perpetual calendar mismatch")
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
    try:
        for target_name in TARGETS:
            results[target_name] = _target_result(
                spot_frames[target_name], perp_frames[target_name], target_name
            )
    except Exception as exc:
        payload = {
            **base_payload,
            "sources": sources,
            "source_contract_passed": True,
            "source_failure": None,
            "target_returns_accessed": True,
            "targets": results,
            "bilateral_training_pass": False,
            "diagnostic_failure": f"{type(exc).__name__}: {exc}",
            "verdict": REJECT,
        }
        _write(payload)
        return

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
