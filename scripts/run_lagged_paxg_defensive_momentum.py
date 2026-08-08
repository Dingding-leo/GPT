#!/usr/bin/env python3
"""Training-only test of frozen lagged PAXG defensive momentum information."""
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

FAMILY_ID = "causal-lagged-paxg-defensive-momentum-opportunity-1h-v1"
ISSUE_NUMBER = 1135
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
FEE_ONE_WAY = 0.0005
ROUND_TRIP_FEE = 0.0010
ANCHORS = tuple(range(216, 4753, 24))
BOOTSTRAP_DRAWS = 5_000
BOOTSTRAP_BLOCK = 7
BOOTSTRAP_SEED = 202608091135
LIMIT = 100
PAUSE_SECONDS = 0.11
OUT = Path("reports/research") / FAMILY_ID
ACCEPT = "accept_lagged_paxg_defensive_momentum_information_for_separate_candidate_preregistration"
REJECT = "reject_causal_lagged_paxg_defensive_momentum_opportunity_1h_v1"

PERFORMANCE_NULLS = {
    "train_strategy_return": None,
    "train_strategy_sharpe": None,
    "oos_strategy_return": None,
    "oos_strategy_sharpe": None,
    "full_strategy_return": None,
    "full_strategy_sharpe": None,
    "benchmark_strategy_comparison": None,
    "turnover": None,
    "strategy_drawdown": None,
    "edge_per_turnover": None,
    "position_path": None,
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


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
        rows.append([
            str(int(timestamp.timestamp() * 1000)),
            format(float(row["open"]), ".17g"),
            format(float(row["high"]), ".17g"),
            format(float(row["low"]), ".17g"),
            format(float(row["close"]), ".17g"),
            format(float(row["volume_base"]), ".17g"),
            format(float(row["volume_quote"]), ".17g"),
            format(float(row["volume_quote_alt"]), ".17g"),
            str(row["confirm"]),
        ])
    return _canonical_json(rows)


def _safe_url(inst: str, after_ms: int, before_ms: int) -> str:
    query = urllib.parse.urlencode([
        ("instId", inst),
        ("bar", BAR),
        ("limit", str(LIMIT)),
        ("after", str(after_ms)),
        ("before", str(before_ms)),
    ])
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


def _fetch_exact_interval(inst: str, start: pd.Timestamp, end: pd.Timestamp, expected_rows: int) -> tuple[pd.DataFrame, dict[str, Any]]:
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
        requests.append({
            "page": page + 1,
            "url": url,
            "response_bytes": len(raw),
            "response_sha256": _sha(raw),
            "rows": len(rows),
        })
        if not rows:
            break
        timestamps: list[int] = []
        for row in rows:
            if not isinstance(row, list) or len(row) != 9:
                raise RuntimeError(f"{inst}: malformed candle row")
            ts = int(str(row[0]))
            if ts < start_ms or ts > end_ms:
                raise RuntimeError(
                    f"{inst}: provider returned timestamp outside frozen interval: {ts}"
                )
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
            # One more bounded query is unnecessary: exact-grid validation below is terminal.
            break
        if PAUSE_SECONDS:
            time.sleep(PAUSE_SECONDS)

    frame = parse_okx_candle_rows(raw_rows)
    if frame.index.has_duplicates:
        duplicates = frame.index[frame.index.duplicated()].unique()
        grouped = frame.loc[duplicates]
        for timestamp in duplicates:
            if grouped.loc[timestamp].drop_duplicates().shape[0] != 1:
                raise RuntimeError(f"{inst}: conflicting duplicate candle")
        frame = frame[~frame.index.duplicated(keep="last")]
    frame = frame.sort_index()
    expected_grid = pd.date_range(start, end, freq="h")
    if len(frame) != expected_rows or not frame.index.equals(expected_grid):
        raise RuntimeError(
            f"{inst}: exact interval mismatch expected={expected_rows} observed={len(frame)} "
            f"start={frame.index[0] if len(frame) else None} end={frame.index[-1] if len(frame) else None}"
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
    volume = frame[["volume_base", "volume_quote", "volume_quote_alt"]].to_numpy(float)
    if not np.isfinite(volume).all() or (volume < 0).any():
        raise RuntimeError(f"{inst}: invalid volume")

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
        "raw_response_sequence_sha256": _sha(_canonical_json([x["response_sha256"] for x in requests])),
        "queried_timestamp_min_ms": start_ms,
        "queried_timestamp_max_ms": end_ms,
        "future_rows_requested_or_parsed": False,
    }


def _rho(x: np.ndarray, y: np.ndarray) -> float:
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
    return float(np.mean(y[order[-n:]]) - np.mean(y[order[:n]])), n


def _bootstrap(x: np.ndarray, net: np.ndarray, adverse: np.ndarray, seed: int) -> dict[str, list[float]]:
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
            _rho(x[idx], net[idx]),
            _slope(x[idx], net[idx]),
            _rho(x[idx], adverse[idx]),
            _slope(x[idx], adverse[idx]),
        ]
    names = ("net_rho", "net_slope", "adverse_rho", "adverse_slope")
    return {
        name: [float(np.quantile(draws[:, i], 0.025)), float(np.quantile(draws[:, i], 0.975))]
        for i, name in enumerate(names)
    }


def _fold_summaries(frame: pd.DataFrame) -> tuple[list[dict[str, Any]], dict[str, float]]:
    sizes = (48, 47, 47, 48)
    cursor = 0
    rows: list[dict[str, Any]] = []
    for fold, size in enumerate(sizes, start=1):
        part = frame.iloc[cursor : cursor + size]
        cursor += size
        x = part["feature"].to_numpy(float)
        rows.append({
            "fold": fold,
            "n": len(part),
            "first_anchor": part.iloc[0]["anchor_timestamp"],
            "last_anchor": part.iloc[-1]["anchor_timestamp"],
            "net_slope": _slope(x, part["net"].to_numpy(float)),
            "adverse_slope": _slope(x, part["adverse"].to_numpy(float)),
        })
    if cursor != len(frame):
        raise RuntimeError("fold partition does not cover exactly 190 opportunities")

    concentrations: dict[str, float] = {}
    for endpoint in ("net", "adverse"):
        negatives = [abs(float(row[f"{endpoint}_slope"])) for row in rows if float(row[f"{endpoint}_slope"]) < 0]
        concentrations[endpoint] = float(max(negatives) / sum(negatives)) if negatives else float("inf")
    return rows, concentrations


def _year_summaries(frame: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for year in (2025, 2026):
        part = frame[frame["anchor_year"] == year]
        x = part["feature"].to_numpy(float)
        net_effect, net_n = _tercile(x, part["net"].to_numpy(float))
        adverse_effect, adverse_n = _tercile(x, part["adverse"].to_numpy(float))
        out[str(year)] = {
            "n": len(part),
            "net_tercile_effect": net_effect,
            "adverse_tercile_effect": adverse_effect,
            "outer_tercile_count_each": min(net_n, adverse_n),
        }
    return out


def _build_opportunities(target: pd.DataFrame, paxg: pd.DataFrame) -> pd.DataFrame:
    if len(target) != TRAIN_ROWS or len(paxg) < TRAIN_ROWS:
        raise RuntimeError("unexpected target/PAXG training dimensions")
    if not target.index.equals(paxg.index[:TRAIN_ROWS]):
        raise RuntimeError("target/PAXG training timestamps do not align exactly")
    p_close = paxg["close"].to_numpy(float)
    t_open = target["open"].to_numpy(float)
    t_low = target["low"].to_numpy(float)
    rows: list[dict[str, Any]] = []
    for t in ANCHORS:
        feature_latest = t - 25
        feature_old = t - 193
        if feature_latest - feature_old != 168 or feature_latest >= t:
            raise RuntimeError("frozen PAXG feature chronology failed")
        entry = float(t_open[t])
        exit_price = float(t_open[t + 24])
        delay_entry = float(t_open[t + 1])
        delay_exit = float(t_open[t + 25])
        feature = math.log(float(p_close[feature_latest]) / float(p_close[feature_old]))
        net = math.log(exit_price / entry) - ROUND_TRIP_FEE
        adverse = float(np.min(np.log(t_low[t : t + 24] / entry) - ROUND_TRIP_FEE))
        delay_net = math.log(delay_exit / delay_entry) - ROUND_TRIP_FEE
        delay_adverse = float(np.min(np.log(t_low[t + 1 : t + 25] / delay_entry) - ROUND_TRIP_FEE))
        rows.append({
            "t": t,
            "anchor_timestamp": target.index[t].isoformat().replace("+00:00", "Z"),
            "anchor_year": int(target.index[t].year),
            "feature": feature,
            "feature_old_index": feature_old,
            "feature_latest_index": feature_latest,
            "feature_latest_timestamp": paxg.index[feature_latest].isoformat().replace("+00:00", "Z"),
            "net": net,
            "adverse": adverse,
            "delay_net": delay_net,
            "delay_adverse": delay_adverse,
            "entry_index": t,
            "exit_index": t + 24,
            "delay_entry_index": t + 1,
            "delay_exit_index": t + 25,
        })
    result = pd.DataFrame(rows)
    if len(result) != 190:
        raise RuntimeError(f"expected 190 opportunities, got {len(result)}")
    return result


def _target_result(target_name: str, target: pd.DataFrame, paxg: pd.DataFrame, seed: int) -> dict[str, Any]:
    opp = _build_opportunities(target, paxg)
    x = opp["feature"].to_numpy(float)
    net = opp["net"].to_numpy(float)
    adverse = opp["adverse"].to_numpy(float)
    delay_net = opp["delay_net"].to_numpy(float)
    delay_adverse = opp["delay_adverse"].to_numpy(float)

    net_rho = _rho(x, net)
    net_slope = _slope(x, net)
    net_tercile, tercile_n = _tercile(x, net)
    adverse_rho = _rho(x, adverse)
    adverse_slope = _slope(x, adverse)
    adverse_tercile, _ = _tercile(x, adverse)
    delay_net_rho = _rho(x, delay_net)
    delay_net_slope = _slope(x, delay_net)
    delay_net_tercile, _ = _tercile(x, delay_net)
    delay_adverse_rho = _rho(x, delay_adverse)
    delay_adverse_slope = _slope(x, delay_adverse)
    delay_adverse_tercile, _ = _tercile(x, delay_adverse)
    bootstrap = _bootstrap(x, net, adverse, seed)
    folds, concentration = _fold_summaries(opp)
    years = _year_summaries(opp)

    # Future-suffix invariance without requesting any target OOS: PAXG's already-frozen
    # post-training source suffix must not alter any training feature, and a target-only
    # training prefix must reproduce every opportunity whose 24H label is contained in it.
    opp_source_prefix = _build_opportunities(target, paxg.iloc[:TRAIN_ROWS].copy())
    source_suffix_invariant = opp.equals(opp_source_prefix)
    prefix_anchor_count = 150
    prefix_last_exit = int(opp.iloc[prefix_anchor_count - 1]["exit_index"])
    target_prefix = target.iloc[: prefix_last_exit + 1].copy()
    prefix_rows: list[dict[str, Any]] = []
    for _, row in opp.iloc[:prefix_anchor_count].iterrows():
        t = int(row["t"])
        entry = float(target_prefix["open"].iloc[t])
        net_replay = math.log(float(target_prefix["open"].iloc[t + 24]) / entry) - ROUND_TRIP_FEE
        adverse_replay = float(np.min(np.log(target_prefix["low"].iloc[t : t + 24].to_numpy(float) / entry) - ROUND_TRIP_FEE))
        prefix_rows.append({"net": net_replay, "adverse": adverse_replay})
    target_prefix_invariant = bool(
        np.allclose([x["net"] for x in prefix_rows], opp.iloc[:prefix_anchor_count]["net"].to_numpy(float), rtol=0, atol=1e-15)
        and np.allclose([x["adverse"] for x in prefix_rows], opp.iloc[:prefix_anchor_count]["adverse"].to_numpy(float), rtol=0, atol=1e-15)
    )

    distinct = int(opp["feature"].nunique())
    feature_iqr = float(opp["feature"].quantile(0.75) - opp["feature"].quantile(0.25))
    negative_net_folds = sum(float(row["net_slope"]) < 0 for row in folds)
    negative_adverse_folds = sum(float(row["adverse_slope"]) < 0 for row in folds)
    chronology = bool(
        tuple(opp["t"].astype(int)) == ANCHORS
        and (opp["feature_latest_index"] == opp["t"] - 25).all()
        and (opp["feature_old_index"] == opp["t"] - 193).all()
        and (opp["exit_index"] == opp["t"] + 24).all()
        and (opp["delay_exit_index"] == opp["t"] + 25).all()
        and int(opp["delay_exit_index"].max()) < TRAIN_ROWS
    )
    fee_check = bool(
        math.isclose(ROUND_TRIP_FEE, 2 * FEE_ONE_WAY, rel_tol=0, abs_tol=0)
        and math.isclose(float(opp.iloc[0]["net"]), math.log(float(target["open"].iloc[240]) / float(target["open"].iloc[216])) - 0.0010, rel_tol=0, abs_tol=1e-15)
    )
    year_gate = all(
        float(years[str(year)]["net_tercile_effect"]) < 0
        and float(years[str(year)]["adverse_tercile_effect"]) < 0
        for year in (2025, 2026)
    )
    gates = {
        "opportunity_and_feature_support": len(opp) == 190 and distinct >= 150 and feature_iqr > 0,
        "negative_net_association": net_rho < 0 and net_slope < 0 and net_tercile < 0,
        "negative_adverse_association": adverse_rho < 0 and adverse_slope < 0 and adverse_tercile < 0,
        "net_dependence_upper_bounds_negative": bootstrap["net_rho"][1] < 0 and bootstrap["net_slope"][1] < 0,
        "adverse_dependence_upper_bounds_negative": bootstrap["adverse_rho"][1] < 0 and bootstrap["adverse_slope"][1] < 0,
        "fold_breadth": negative_net_folds >= 3 and negative_adverse_folds >= 3,
        "fold_concentration": concentration["net"] <= 0.60 and concentration["adverse"] <= 0.60,
        "calendar_year_breadth": year_gate,
        "one_hour_delay_transport": (
            delay_net_rho < 0 and delay_net_slope < 0 and delay_net_tercile < 0
            and delay_adverse_rho < 0 and delay_adverse_slope < 0 and delay_adverse_tercile < 0
        ),
        "chronology_fee_and_suffix_invariance": chronology and fee_check and source_suffix_invariant and target_prefix_invariant,
    }

    opp_bytes = opp.to_csv(index=False, float_format="%.17g", lineterminator="\n").encode()
    return {
        "target": target_name,
        "opportunities": len(opp),
        "opportunity_sha256": _sha(opp_bytes),
        "feature_distribution": {
            "distinct": distinct,
            "iqr": feature_iqr,
            "q25": float(opp["feature"].quantile(0.25)),
            "median": float(opp["feature"].median()),
            "q75": float(opp["feature"].quantile(0.75)),
        },
        "unconditional_net_return": {
            "mean": float(np.mean(net)),
            "median": float(np.median(net)),
            "q25": float(np.quantile(net, 0.25)),
            "q75": float(np.quantile(net, 0.75)),
            "minimum": float(np.min(net)),
            "maximum": float(np.max(net)),
            "positive_fraction": float(np.mean(net > 0)),
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
        "negative_fold_concentration": concentration,
        "calendar_years": years,
        "one_hour_delay": {
            "net_rho": delay_net_rho,
            "net_slope": delay_net_slope,
            "net_tercile_effect": delay_net_tercile,
            "adverse_rho": delay_adverse_rho,
            "adverse_slope": delay_adverse_slope,
            "adverse_tercile_effect": delay_adverse_tercile,
        },
        "chronology": {
            "anchor_count": len(ANCHORS),
            "first_anchor_index": ANCHORS[0],
            "last_anchor_index": ANCHORS[-1],
            "latest_feature_lag_hours": 25,
            "feature_horizon_hours": 168,
            "target_oos_requested_or_parsed": False,
            "source_suffix_invariant": source_suffix_invariant,
            "target_training_prefix_invariant": target_prefix_invariant,
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
        "# Lagged PAXG defensive momentum — bilateral training-only 1H diagnostic",
        "",
        f"Family: `{FAMILY_ID}`",
        f"Verdict: `{payload['verdict']}`",
        "Candidate/grid: `0/0`",
        f"Source identity reproduced: `{payload['source_identity_reproduced']}`",
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
            f"net slope={result['net_slope']:.6f}, net tercile={result['net_tercile_effect']:.6f}, "
            f"adverse rho={result['adverse_rho']:.6f}, adverse slope={result['adverse_slope']:.6f}, "
            f"adverse tercile={result['adverse_tercile_effect']:.6f}, pass={result['all_training_gates_pass']}"
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
    (OUT / "manifest.sha256").write_text(_sha(manifest_path.read_bytes()) + "\n", encoding="utf-8")
    print(json.dumps({
        "exact_head": payload["exact_head"],
        "bilateral_training_pass": payload["bilateral_training_pass"],
        "target_oos_accessed": False,
        "verdict": payload["verdict"],
        "evidence_sha256": _sha(evidence),
    }, sort_keys=True))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    source_dir = OUT / "sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    exact_head = os.environ.get("RESEARCH_HEAD_SHA", os.environ.get("GITHUB_SHA", "local-unbound"))

    paxg, paxg_meta = _fetch_exact_interval(PAXG, SOURCE_START, SOURCE_END, SOURCE_ROWS)
    paxg_source_hash = _sha(_source_panel_bytes(paxg))
    source_identity_reproduced = paxg_source_hash == SOURCE_NORMALIZED_SHA256
    if not source_identity_reproduced:
        payload = {
            "family_id": FAMILY_ID,
            "issue_number": ISSUE_NUMBER,
            "base_main": BASE_MAIN,
            "exact_head": exact_head,
            "candidate_count": 0,
            "parameter_grid_count": 0,
            "bar": BAR,
            "fee_bps_one_way": 5.0,
            "source_identity_reproduced": False,
            "source_expected_sha256": SOURCE_NORMALIZED_SHA256,
            "source_observed_sha256": paxg_source_hash,
            "source": paxg_meta,
            "target_returns_accessed": False,
            "target_oos_accessed": False,
            "targets": {},
            "bilateral_training_pass": False,
            "performance": PERFORMANCE_NULLS,
            "canonical_mutation": False,
            "paper_trading_authorized": False,
            "live_trading_authorized": False,
            "verdict": REJECT,
        }
        _write(payload)
        return

    (source_dir / "paxg-source.csv").write_bytes(_canonical_csv(paxg))
    target_frames: dict[str, pd.DataFrame] = {}
    target_sources: dict[str, Any] = {}
    for target in TARGETS:
        frame, meta = _fetch_exact_interval(target, SOURCE_START, TRAIN_END, TRAIN_ROWS)
        target_frames[target] = frame
        target_sources[target] = meta
        (source_dir / f"{target.lower()}-training.csv").write_bytes(_canonical_csv(frame))

    results = {
        target: _target_result(target, target_frames[target], paxg, BOOTSTRAP_SEED + i)
        for i, target in enumerate(TARGETS)
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
        "source_calendar": [SOURCE_START.isoformat().replace("+00:00", "Z"), SOURCE_END.isoformat().replace("+00:00", "Z")],
        "training_calendar": [SOURCE_START.isoformat().replace("+00:00", "Z"), TRAIN_END.isoformat().replace("+00:00", "Z")],
        "training_target_rows": TRAIN_ROWS,
        "sealed_oos_calendar": ["2026-05-20T00:00:00Z", "2026-08-03T23:00:00Z"],
        "unread_suffix_calendar": ["2026-08-04T00:00:00Z", "2026-08-07T23:00:00Z"],
        "fee_bps_one_way": 5.0,
        "round_trip_label_bps": 10.0,
        "feature": "log(PAXG_close[t-25] / PAXG_close[t-193])",
        "frozen_sign": "higher feature predicts lower net return and more-negative adverse excursion",
        "bootstrap_draws": BOOTSTRAP_DRAWS,
        "bootstrap_block_opportunities": BOOTSTRAP_BLOCK,
        "bootstrap_seed_base": BOOTSTRAP_SEED,
        "source_identity_reproduced": True,
        "source_expected_sha256": SOURCE_NORMALIZED_SHA256,
        "source_observed_sha256": paxg_source_hash,
        "source": paxg_meta,
        "target_sources": target_sources,
        "target_returns_accessed": True,
        "target_oos_accessed": False,
        "unread_suffix_accessed": False,
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
