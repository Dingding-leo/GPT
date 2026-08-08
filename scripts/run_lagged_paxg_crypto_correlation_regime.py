#!/usr/bin/env python3
"""Training-only test of frozen lagged PAXG/crypto correlation-regime information."""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from gpt_quant.okx import parse_okx_candle_rows

FAMILY_ID = "causal-lagged-paxg-crypto-correlation-regime-opportunity-1h-v1"
ISSUE_NUMBER = 1162
BASE_MAIN = "5a0fcc97d1a882f8223656c51f5bb8055f534e38"
ORIGIN = "https://www.okx.com"
PATH = "/api/v5/market/history-candles"
BAR = "1H"
PAXG = "PAXG-USDT"
TARGETS = ("BTC-USDT", "ETH-USDT")
SOURCE_START = pd.Timestamp("2025-11-01T00:00:00Z")
SOURCE_END = pd.Timestamp("2026-08-07T23:00:00Z")
TRAIN_END = pd.Timestamp("2026-05-19T23:00:00Z")
SOURCE_ROWS = 6_720
TRAIN_ROWS = 4_800
SOURCE_NORMALIZED_SHA256 = "9706000030143e6ab6f7350dca51b7383b8238124be66c1f1995426a60dddc8e"
TARGET_CSV_SHA256 = {
    "BTC-USDT": "ab592ae5e75149a44dc677b3a2c7bd5e7fa6d4da0079e84fcf059401ffbe1752",
    "ETH-USDT": "9f8e4a2d1d3c7753cee84f4851100773e91b643a7e3a7d0587dcaeafb6717a50",
}
FEE_ONE_WAY = 0.0005
ROUND_TRIP_FEE = 0.0010
ANCHORS = tuple(range(912, 4753, 24))
BOOTSTRAP_DRAWS = 5_000
BOOTSTRAP_BLOCK = 7
BOOTSTRAP_SEEDS = {"BTC-USDT": 202608092201, "ETH-USDT": 202608092202}
LIMIT = 100
PAUSE_SECONDS = 0.11
OUT = Path("reports/research") / FAMILY_ID
ACCEPT = "support_causal_lagged_paxg_crypto_correlation_regime_for_separate_candidate_predeclaration_1h_v1"
REJECT = "reject_causal_lagged_paxg_crypto_correlation_regime_information_premise_1h_v1"

PERFORMANCE_NULLS = {
    "train_strategy_return": None,
    "train_strategy_sharpe": None,
    "oos_strategy_return": None,
    "oos_strategy_sharpe": None,
    "full_strategy_return": None,
    "full_strategy_sharpe": None,
    "benchmark_strategy_comparison": None,
    "turnover": None,
    "strategy_fee_drag": None,
    "strategy_drawdown": None,
    "edge_per_turnover": None,
    "strategy_fold_year_breadth": None,
    "strategy_uncertainty": None,
    "position_path": None,
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(value: Any) -> bytes:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return (text + "\n").encode()


def _canonical_csv(frame: pd.DataFrame) -> bytes:
    return frame.reset_index(names="timestamp").to_csv(
        index=False,
        date_format="%Y-%m-%dT%H:%M:%S.%fZ",
        float_format="%.12g",
        lineterminator="\n",
    ).encode()


def _source_panel_bytes(frame: pd.DataFrame) -> bytes:
    rows: list[list[str]] = []
    for timestamp, row in frame.iterrows():
        rows.append(
            [
                str(int(timestamp.timestamp() * 1000)),
                format(float(row["open"]), ".17g"),
                format(float(row["high"]), ".17g"),
                format(float(row["low"]), ".17g"),
                format(float(row["close"]), ".17g"),
                format(float(row["volume_base"]), ".17g"),
                format(float(row["volume_quote"]), ".17g"),
                format(float(row["volume_quote_alt"]), ".17g"),
                str(row["confirm"]),
            ]
        )
    return _canonical_json(rows)


def _safe_url(inst: str, after_ms: int, before_ms: int) -> str:
    query = urllib.parse.urlencode(
        [
            ("instId", inst),
            ("bar", BAR),
            ("limit", str(LIMIT)),
            ("after", str(after_ms)),
            ("before", str(before_ms)),
        ]
    )
    url = f"{ORIGIN}{PATH}?{query}"
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "www.okx.com" or parsed.path != PATH:
        raise ValueError("untrusted OKX source URL")
    fields = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    if set(fields) != {"instId", "bar", "limit", "after", "before"}:
        raise ValueError("unexpected source query fields")
    if fields["instId"] != inst or fields["bar"] != BAR or fields["limit"] != str(LIMIT):
        raise ValueError("source query escaped frozen market/cadence")
    return url


def _get(url: str) -> bytes:
    retryable = {408, 429, 500, 502, 503, 504}
    last: Exception | None = None
    for attempt in range(4):
        req = urllib.request.Request(
            url,
            method="GET",
            headers={"Accept": "application/json", "User-Agent": "gpt-quant-research/1.0"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30.0) as response:
                raw = response.read(1_000_001)
                if response.status != 200:
                    raise RuntimeError(f"unexpected OKX status {response.status}")
                if len(raw) > 1_000_000:
                    raise RuntimeError("oversized OKX response")
                return raw
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code not in retryable or attempt == 3:
                raise
        except (urllib.error.URLError, TimeoutError) as exc:
            last = exc
            if attempt == 3:
                raise
        time.sleep(0.6 * (2**attempt))
    raise RuntimeError("OKX retry exhaustion") from last


def _parse_envelope(raw: bytes) -> list[list[Any]]:
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict) or str(payload.get("code")) != "0":
        raise RuntimeError(f"OKX source envelope rejected: {payload!r}")
    data = payload.get("data")
    if not isinstance(data, list):
        raise RuntimeError("OKX source data is not a list")
    return data


def _fetch_exact_interval(
    inst: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    expected_rows: int,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    lower_exclusive = start_ms - 1
    cursor = end_ms + 3_600_000
    raw_rows: list[list[Any]] = []
    requests: list[dict[str, Any]] = []
    seen_cursors: set[int] = set()
    max_pages = math.ceil(expected_rows / LIMIT) + 3

    for page in range(max_pages):
        if cursor in seen_cursors:
            raise RuntimeError(f"{inst}: repeated pagination cursor")
        seen_cursors.add(cursor)
        url = _safe_url(inst, cursor, lower_exclusive)
        raw = _get(url)
        rows = _parse_envelope(raw)
        requests.append(
            {
                "page": page + 1,
                "url": url,
                "response_bytes": len(raw),
                "response_sha256": _sha(raw),
                "rows": len(rows),
            }
        )
        if not rows:
            break
        timestamps: list[int] = []
        for row in rows:
            if not isinstance(row, list) or len(row) != 9:
                raise RuntimeError(f"{inst}: malformed candle row")
            ts = int(str(row[0]))
            if ts < start_ms or ts > end_ms:
                raise RuntimeError(f"{inst}: timestamp outside frozen interval: {ts}")
            timestamps.append(ts)
        if any(a <= b for a, b in zip(timestamps, timestamps[1:])):
            raise RuntimeError(f"{inst}: page is not strictly newest-to-oldest")
        raw_rows.extend(rows)
        oldest = timestamps[-1]
        if oldest == start_ms:
            break
        if oldest >= cursor:
            raise RuntimeError(f"{inst}: pagination failed to move backward")
        cursor = oldest
        if len(rows) < LIMIT:
            break
        if PAUSE_SECONDS:
            time.sleep(PAUSE_SECONDS)

    frame = parse_okx_candle_rows(raw_rows)
    if frame.index.has_duplicates:
        duplicates = frame.index[frame.index.duplicated()].unique()
        for timestamp in duplicates:
            if frame.loc[timestamp].drop_duplicates().shape[0] != 1:
                raise RuntimeError(f"{inst}: conflicting duplicate candle")
        frame = frame[~frame.index.duplicated(keep="last")]
    frame = frame.sort_index()
    expected_grid = pd.date_range(start, end, freq="h")
    if len(frame) != expected_rows or not frame.index.equals(expected_grid):
        raise RuntimeError(
            f"{inst}: exact interval mismatch expected={expected_rows} observed={len(frame)}"
        )
    if set(frame["confirm"].astype(str)) != {"1"}:
        raise RuntimeError(f"{inst}: non-completed candle present")
    prices = frame[["open", "high", "low", "close"]].to_numpy(float)
    if not np.isfinite(prices).all() or not (prices > 0).all():
        raise RuntimeError(f"{inst}: invalid OHLC")
    if not (frame["high"] >= frame[["open", "close", "low"]].max(axis=1)).all():
        raise RuntimeError(f"{inst}: high invariant failed")
    if not (frame["low"] <= frame[["open", "close", "high"]].min(axis=1)).all():
        raise RuntimeError(f"{inst}: low invariant failed")

    canonical = _canonical_csv(frame)
    return frame, {
        "instrument": inst,
        "bar": BAR,
        "requested_start": start.isoformat().replace("+00:00", "Z"),
        "requested_end": end.isoformat().replace("+00:00", "Z"),
        "observed_rows": len(frame),
        "first": frame.index[0].isoformat().replace("+00:00", "Z"),
        "last": frame.index[-1].isoformat().replace("+00:00", "Z"),
        "request_count": len(requests),
        "requests": requests,
        "normalized_csv_sha256": _sha(canonical),
        "raw_response_sequence_sha256": _sha(
            _canonical_json([item["response_sha256"] for item in requests])
        ),
        "future_rows_requested_or_parsed": False,
    }


def _spearman(x: np.ndarray, y: np.ndarray) -> float:
    xr = pd.Series(x).rank(method="average")
    yr = pd.Series(y).rank(method="average")
    return float(xr.corr(yr))


def _slope(x: np.ndarray, y: np.ndarray) -> float:
    sd = float(np.std(x, ddof=0))
    if not math.isfinite(sd) or sd <= 0:
        return float("nan")
    z = (x - float(np.mean(x))) / sd
    return float(np.mean(z * y))


def _tercile(x: np.ndarray, y: np.ndarray) -> tuple[float, int]:
    n = len(x) // 3
    if n < 1:
        return float("nan"), 0
    order = np.argsort(x, kind="mergesort")
    effect = float(np.mean(y[order[-n:]]) - np.mean(y[order[:n]]))
    return effect, n


def _pearson(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) != len(y) or len(x) < 2:
        raise ValueError("invalid Pearson inputs")
    if float(np.std(x, ddof=0)) <= 0 or float(np.std(y, ddof=0)) <= 0:
        raise ValueError("zero-variance Pearson input")
    value = float(np.corrcoef(x, y)[0, 1])
    if not math.isfinite(value) or abs(value) > 1.000000000001:
        raise ValueError("invalid Pearson result")
    return value


def _returns(close: np.ndarray) -> np.ndarray:
    result = np.full(len(close), np.nan, dtype=float)
    result[1:] = np.log(close[1:] / close[:-1])
    return result


def _feature_for_anchor(target_r: np.ndarray, paxg_r: np.ndarray, t: int) -> float | None:
    recent = np.arange(t - 192, t - 24, dtype=int)
    baseline = np.arange(t - 912, t - 192, dtype=int)
    if len(recent) != 168 or len(baseline) != 720:
        raise RuntimeError("frozen correlation windows changed")
    # r_h = log(close[h] / close[h-1]); h=0 is undefined on the frozen 4,800H prefix.
    # The preregistered t=912 anchor is therefore invalid rather than fabricated or backfilled.
    if int(baseline.min()) < 1:
        return None
    arrays = (target_r[recent], paxg_r[recent], target_r[baseline], paxg_r[baseline])
    if not all(np.isfinite(array).all() and float(np.std(array, ddof=0)) > 0 for array in arrays):
        return None
    recent_rho = _pearson(target_r[recent], paxg_r[recent])
    baseline_rho = _pearson(target_r[baseline], paxg_r[baseline])
    return recent_rho - baseline_rho


def _build_opportunities(
    target: pd.DataFrame,
    paxg: pd.DataFrame,
) -> tuple[pd.DataFrame, list[int]]:
    if len(target) != TRAIN_ROWS or len(paxg) < TRAIN_ROWS:
        raise RuntimeError("unexpected target/PAXG dimensions")
    if not target.index.equals(paxg.index[:TRAIN_ROWS]):
        raise RuntimeError("target/PAXG training timestamps do not align")
    target_open = target["open"].to_numpy(float)
    target_r = _returns(target["close"].to_numpy(float))
    paxg_r = _returns(paxg["close"].to_numpy(float)[:TRAIN_ROWS])
    rows: list[dict[str, Any]] = []
    invalid: list[int] = []
    for t in ANCHORS:
        feature = _feature_for_anchor(target_r, paxg_r, t)
        if feature is None:
            invalid.append(t)
            continue
        if t + 25 >= TRAIN_ROWS:
            raise RuntimeError("label escaped training prefix")
        entry = float(target_open[t])
        exit_price = float(target_open[t + 24])
        delay_entry = float(target_open[t + 1])
        delay_exit = float(target_open[t + 25])
        net = exit_price / entry - 1.0 - ROUND_TRIP_FEE
        adverse = float(np.min(target_open[t : t + 25] / entry - 1.0))
        delay_net = delay_exit / delay_entry - 1.0 - ROUND_TRIP_FEE
        delay_adverse = float(np.min(target_open[t + 1 : t + 26] / delay_entry - 1.0))
        rows.append(
            {
                "t": t,
                "anchor_timestamp": target.index[t].isoformat().replace("+00:00", "Z"),
                "feature": feature,
                "recent_start": t - 192,
                "recent_end_exclusive": t - 24,
                "baseline_start": t - 912,
                "baseline_end_exclusive": t - 192,
                "latest_return_index": t - 25,
                "net": net,
                "adverse": adverse,
                "delay_net": delay_net,
                "delay_adverse": delay_adverse,
                "entry_index": t,
                "exit_index": t + 24,
                "delay_entry_index": t + 1,
                "delay_exit_index": t + 25,
            }
        )
    return pd.DataFrame(rows), invalid


def _bootstrap(
    x: np.ndarray,
    net: np.ndarray,
    adverse: np.ndarray,
    seed: int,
) -> dict[str, list[float]]:
    rng = np.random.default_rng(seed)
    n = len(x)
    draws = np.empty((BOOTSTRAP_DRAWS, 4), dtype=float)
    for draw in range(BOOTSTRAP_DRAWS):
        selected: list[int] = []
        while len(selected) < n:
            start = int(rng.integers(0, n - BOOTSTRAP_BLOCK + 1))
            selected.extend(range(start, start + BOOTSTRAP_BLOCK))
        idx = np.asarray(selected[:n], dtype=int)
        draws[draw] = [
            _spearman(x[idx], net[idx]),
            _slope(x[idx], net[idx]),
            _spearman(x[idx], adverse[idx]),
            _slope(x[idx], adverse[idx]),
        ]
    names = ("net_rho", "net_slope", "adverse_rho", "adverse_slope")
    return {
        name: [
            float(np.quantile(draws[:, index], 0.025)),
            float(np.quantile(draws[:, index], 0.975)),
        ]
        for index, name in enumerate(names)
    }


def _folds(frame: pd.DataFrame) -> tuple[list[dict[str, Any]], float]:
    parts = np.array_split(np.arange(len(frame)), 4)
    rows: list[dict[str, Any]] = []
    for fold, indices in enumerate(parts, start=1):
        part = frame.iloc[indices]
        x = part["feature"].to_numpy(float)
        rows.append(
            {
                "fold": fold,
                "n": len(part),
                "first_anchor": part.iloc[0]["anchor_timestamp"],
                "last_anchor": part.iloc[-1]["anchor_timestamp"],
                "net_slope": _slope(x, part["net"].to_numpy(float)),
                "adverse_slope": _slope(x, part["adverse"].to_numpy(float)),
            }
        )
    negatives = [
        abs(float(row["net_slope"])) for row in rows if float(row["net_slope"]) < 0
    ]
    concentration = float(max(negatives) / sum(negatives)) if negatives else float("inf")
    return rows, concentration


def _time_halves(frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for half, indices in enumerate(np.array_split(np.arange(len(frame)), 2), start=1):
        part = frame.iloc[indices]
        x = part["feature"].to_numpy(float)
        net_effect, net_n = _tercile(x, part["net"].to_numpy(float))
        adverse_effect, adverse_n = _tercile(x, part["adverse"].to_numpy(float))
        rows.append(
            {
                "half": half,
                "n": len(part),
                "first_anchor": part.iloc[0]["anchor_timestamp"],
                "last_anchor": part.iloc[-1]["anchor_timestamp"],
                "net_tercile_effect": net_effect,
                "adverse_tercile_effect": adverse_effect,
                "outer_tercile_count_each": min(net_n, adverse_n),
            }
        )
    return rows


def _target_result(
    target_name: str,
    target: pd.DataFrame,
    paxg: pd.DataFrame,
) -> dict[str, Any]:
    opp, invalid = _build_opportunities(target, paxg)
    x = opp["feature"].to_numpy(float)
    net = opp["net"].to_numpy(float)
    adverse = opp["adverse"].to_numpy(float)
    delay_net = opp["delay_net"].to_numpy(float)
    delay_adverse = opp["delay_adverse"].to_numpy(float)

    net_rho = _spearman(x, net)
    net_slope = _slope(x, net)
    net_tercile, tercile_n = _tercile(x, net)
    adverse_rho = _spearman(x, adverse)
    adverse_slope = _slope(x, adverse)
    adverse_tercile, _ = _tercile(x, adverse)
    delay = {
        "net_rho": _spearman(x, delay_net),
        "net_slope": _slope(x, delay_net),
        "net_tercile_effect": _tercile(x, delay_net)[0],
        "adverse_rho": _spearman(x, delay_adverse),
        "adverse_slope": _slope(x, delay_adverse),
        "adverse_tercile_effect": _tercile(x, delay_adverse)[0],
    }
    bootstrap = _bootstrap(x, net, adverse, BOOTSTRAP_SEEDS[target_name])
    folds, concentration = _folds(opp)
    halves = _time_halves(opp)

    target_scaled = target.copy()
    paxg_scaled = paxg.copy()
    target_scaled[["open", "high", "low", "close"]] *= 3.7
    paxg_scaled[["open", "high", "low", "close"]] *= 2.5
    scaled_opp, scaled_invalid = _build_opportunities(target_scaled, paxg_scaled)
    scale_invariant = bool(
        invalid == scaled_invalid
        and np.allclose(opp["feature"], scaled_opp["feature"], rtol=0, atol=1e-12)
    )
    source_prefix_opp, source_prefix_invalid = _build_opportunities(
        target,
        paxg.iloc[:TRAIN_ROWS].copy(),
    )
    source_prefix_invariant = bool(
        invalid == source_prefix_invalid
        and np.allclose(opp["feature"], source_prefix_opp["feature"], rtol=0, atol=0)
    )
    chronology = bool(
        tuple(opp["t"].astype(int))
        == tuple(anchor for anchor in ANCHORS if anchor not in invalid)
        and (opp["recent_end_exclusive"] == opp["t"] - 24).all()
        and (opp["latest_return_index"] == opp["t"] - 25).all()
        and (opp["baseline_end_exclusive"] == opp["t"] - 192).all()
        and (opp["exit_index"] == opp["t"] + 24).all()
        and (opp["delay_exit_index"] == opp["t"] + 25).all()
        and int(opp["delay_exit_index"].max()) < TRAIN_ROWS
    )
    first = opp.iloc[0]
    first_t = int(first["t"])
    fee_check = bool(
        ROUND_TRIP_FEE == 2 * FEE_ONE_WAY
        and math.isclose(
            float(first["net"]),
            float(
                target["open"].iloc[first_t + 24] / target["open"].iloc[first_t] - 1.001
            ),
            rel_tol=0,
            abs_tol=1e-15,
        )
    )

    distinct = int(opp["feature"].nunique())
    feature_iqr = float(opp["feature"].quantile(0.75) - opp["feature"].quantile(0.25))
    negative_net_folds = sum(float(row["net_slope"]) < 0 for row in folds)
    negative_adverse_folds = sum(float(row["adverse_slope"]) < 0 for row in folds)
    time_breadth = all(
        float(row["net_tercile_effect"]) < 0 and float(row["adverse_tercile_effect"]) < 0
        for row in halves
    )
    delay_gate = all(float(value) < 0 for value in delay.values())
    gates = {
        "source_and_target_identity": True,
        "opportunity_and_feature_support": (
            len(opp) >= 150 and distinct >= 100 and feature_iqr > 0 and tercile_n >= 45
        ),
        "negative_net_association": net_rho < 0 and net_slope < 0 and net_tercile < 0,
        "negative_adverse_association": (
            adverse_rho < 0 and adverse_slope < 0 and adverse_tercile < 0
        ),
        "net_dependence_upper_bounds_negative": (
            bootstrap["net_rho"][1] < 0 and bootstrap["net_slope"][1] < 0
        ),
        "adverse_dependence_upper_bounds_negative": (
            bootstrap["adverse_rho"][1] < 0 and bootstrap["adverse_slope"][1] < 0
        ),
        "fold_breadth": negative_net_folds >= 3 and negative_adverse_folds >= 3,
        "net_fold_concentration": concentration <= 0.60,
        "chronological_half_breadth": time_breadth,
        "one_hour_delay_transport": delay_gate,
        "chronology_algebra_scale_prefix_invariance": (
            chronology
            and fee_check
            and scale_invariant
            and source_prefix_invariant
            and invalid == [912]
        ),
    }

    opp_bytes = opp.to_csv(index=False, float_format="%.17g", lineterminator="\n").encode()
    return {
        "target": target_name,
        "opportunities": len(opp),
        "scheduled_anchors": len(ANCHORS),
        "invalid_anchors": invalid,
        "invalid_anchor_reason": "t=912 lacks r_0 because frozen sample has no close[-1]",
        "opportunity_sha256": _sha(opp_bytes),
        "feature_distribution": {
            "distinct": distinct,
            "iqr": feature_iqr,
            "q25": float(opp["feature"].quantile(0.25)),
            "median": float(opp["feature"].median()),
            "q75": float(opp["feature"].quantile(0.75)),
        },
        "net_rho": net_rho,
        "net_slope": net_slope,
        "net_tercile_effect": net_tercile,
        "adverse_rho": adverse_rho,
        "adverse_slope": adverse_slope,
        "adverse_tercile_effect": adverse_tercile,
        "outer_tercile_count_each": tercile_n,
        "bootstrap_95": bootstrap,
        "folds": folds,
        "negative_net_folds": negative_net_folds,
        "negative_adverse_folds": negative_adverse_folds,
        "negative_net_fold_concentration": concentration,
        "chronological_halves": halves,
        "one_hour_delay": delay,
        "chronology": {
            "first_valid_anchor_index": int(opp.iloc[0]["t"]),
            "last_anchor_index": int(opp.iloc[-1]["t"]),
            "latest_feature_return_lag_hours": 25,
            "recent_return_count": 168,
            "baseline_return_count": 720,
            "target_oos_requested_or_parsed": False,
            "source_prefix_invariant": source_prefix_invariant,
            "positive_price_scale_invariant": scale_invariant,
            "fee_accounting_exact": fee_check,
            "structural_checks": chronology,
        },
        "gates": {name: bool(value) for name, value in gates.items()},
        "all_training_gates_pass": bool(all(gates.values())),
    }


def _write(payload: dict[str, Any]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    evidence = _canonical_json(payload)
    evidence_path = OUT / "evidence.json"
    evidence_path.write_bytes(evidence)
    (OUT / "evidence.sha256").write_text(_sha(evidence) + "\n", encoding="utf-8")
    report = OUT / "report.md"
    lines = [
        "# Lagged PAXG/crypto correlation regime — bilateral training-only 1H diagnostic",
        "",
        f"Family: `{FAMILY_ID}`",
        f"Verdict: `{payload['verdict']}`",
        "Candidate/grid: `0/0`",
        "Target OOS accessed: `false`",
        "Executable strategy performance: `null`",
        "Canonical mutation: `false`",
        "Paper/live authorization: `false`",
        "",
        "## Bilateral training evidence",
        "",
    ]
    for target, result in payload.get("targets", {}).items():
        lines.append(
            f"- {target}: n={result['opportunities']}, net rho={result['net_rho']:.6f}, "
            f"net slope={result['net_slope']:.6f}, "
            f"net tercile={result['net_tercile_effect']:.6f}, "
            f"adverse rho={result['adverse_rho']:.6f}, "
            f"adverse slope={result['adverse_slope']:.6f}, "
            f"adverse tercile={result['adverse_tercile_effect']:.6f}, "
            f"pass={result['all_training_gates_pass']}"
        )
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (OUT / "report.sha256").write_text(_sha(report.read_bytes()) + "\n", encoding="utf-8")
    manifest = {
        "family_id": FAMILY_ID,
        "exact_head": payload["exact_head"],
        "verdict": payload["verdict"],
        "evidence_sha256": _sha(evidence),
        "report_sha256": _sha(report.read_bytes()),
    }
    manifest_path = OUT / "manifest.json"
    manifest_path.write_bytes(_canonical_json(manifest))
    (OUT / "manifest.sha256").write_text(
        _sha(manifest_path.read_bytes()) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "exact_head": payload["exact_head"],
                "bilateral_training_pass": payload["bilateral_training_pass"],
                "target_oos_accessed": False,
                "verdict": payload["verdict"],
                "evidence_sha256": _sha(evidence),
            },
            sort_keys=True,
        )
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    source_dir = OUT / "sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    exact_head = os.environ.get("RESEARCH_HEAD_SHA", os.environ.get("GITHUB_SHA", "local-unbound"))

    paxg, paxg_meta = _fetch_exact_interval(PAXG, SOURCE_START, SOURCE_END, SOURCE_ROWS)
    paxg_hash = _sha(_source_panel_bytes(paxg))
    if paxg_hash != SOURCE_NORMALIZED_SHA256:
        raise RuntimeError(
            f"PAXG immutable identity mismatch expected={SOURCE_NORMALIZED_SHA256} observed={paxg_hash}"
        )
    (source_dir / "paxg-source.csv").write_bytes(_canonical_csv(paxg))

    target_frames: dict[str, pd.DataFrame] = {}
    target_sources: dict[str, Any] = {}
    for target_name in TARGETS:
        frame, meta = _fetch_exact_interval(target_name, SOURCE_START, TRAIN_END, TRAIN_ROWS)
        observed_hash = _sha(_canonical_csv(frame))
        if observed_hash != TARGET_CSV_SHA256[target_name]:
            raise RuntimeError(
                f"{target_name} immutable prefix mismatch "
                f"expected={TARGET_CSV_SHA256[target_name]} observed={observed_hash}"
            )
        target_frames[target_name] = frame
        target_sources[target_name] = meta
        (source_dir / f"{target_name.lower()}-training.csv").write_bytes(_canonical_csv(frame))

    results = {
        target_name: _target_result(target_name, target_frames[target_name], paxg)
        for target_name in TARGETS
    }
    bilateral = all(result["all_training_gates_pass"] for result in results.values())
    payload = {
        "family_id": FAMILY_ID,
        "issue_number": ISSUE_NUMBER,
        "base_main": BASE_MAIN,
        "exact_head": exact_head,
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "bar": BAR,
        "source_calendar": [
            SOURCE_START.isoformat().replace("+00:00", "Z"),
            SOURCE_END.isoformat().replace("+00:00", "Z"),
        ],
        "training_calendar": [
            SOURCE_START.isoformat().replace("+00:00", "Z"),
            TRAIN_END.isoformat().replace("+00:00", "Z"),
        ],
        "training_target_rows": TRAIN_ROWS,
        "sealed_target_suffix_accessed": False,
        "fee_bps_one_way": 5.0,
        "round_trip_label_bps": 10.0,
        "feature": "corr(rT,rG)[t-192:t-24] - corr(rT,rG)[t-912:t-192]",
        "frozen_sign": "higher feature predicts lower net return and lower adverse excursion",
        "scheduled_anchors": len(ANCHORS),
        "bootstrap_draws": BOOTSTRAP_DRAWS,
        "bootstrap_block_opportunities": BOOTSTRAP_BLOCK,
        "bootstrap_seeds": BOOTSTRAP_SEEDS,
        "source_identity_reproduced": True,
        "source_expected_sha256": SOURCE_NORMALIZED_SHA256,
        "source_observed_sha256": paxg_hash,
        "source": paxg_meta,
        "target_expected_sha256": TARGET_CSV_SHA256,
        "target_sources": target_sources,
        "target_returns_accessed": True,
        "target_oos_accessed": False,
        "targets": results,
        "bilateral_training_pass": bilateral,
        "performance": PERFORMANCE_NULLS,
        "canonical_mutation": False,
        "correction_authority": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "verdict": ACCEPT if bilateral else REJECT,
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    _write(payload)


if __name__ == "__main__":
    main()
