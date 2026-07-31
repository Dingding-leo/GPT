#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

HOUR_MS = 3_600_000
DAY_HOURS = 24
LOOKBACK_HOURS = 2_160
FEE_RATE = 0.0005
MARKETS = ("BTC-USDT", "ETH-USDT")
BAR = "1H"
START_MS = 1_626_998_400_000
END_MS = 1_783_468_800_000
ROWS = 43_441
TRAIN_START = 2_880
OOS_START = 17_520
SCORE_END = 43_440
FOLD_HOURS = 2_160
BOOT_BLOCK = 168
BOOT_RESAMPLES = 5_000
BOOT_SEED = 20_260_731
FAMILY_ID = "daily-margin-acceleration-confirmation-1h-v1"
ISSUE = 753


def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat().replace("+00:00", "Z")


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def request_json(url: str, attempts: int = 6) -> tuple[bytes, dict[str, Any]]:
    error: Exception | None = None
    for attempt in range(attempts):
        req = Request(url, headers={"Accept": "application/json", "User-Agent": "Dingding-leo-GPT-training-candidate/1.0"})
        try:
            with urlopen(req, timeout=30) as response:
                payload = response.read()
                doc = json.loads(payload)
                if doc.get("code") != "0" or not isinstance(doc.get("data"), list):
                    raise ValueError(f"unexpected OKX response: {doc}")
                return payload, doc
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            error = exc
            if attempt + 1 < attempts:
                time.sleep(min(8.0, 0.5 * 2**attempt))
    raise RuntimeError(f"public request failed: {url}") from error


def fetch_market(base_url: str, instrument: str, source_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candles: dict[int, dict[str, Any]] = {}
    pages: list[dict[str, Any]] = []
    cursor = END_MS + HOUR_MS
    page_index = 0
    while True:
        query = urlencode({"instId": instrument, "bar": BAR, "limit": "300", "after": str(cursor)})
        url = f"{base_url}/api/v5/market/history-candles?{query}"
        payload, doc = request_json(url)
        source_dir.mkdir(parents=True, exist_ok=True)
        path = source_dir / f"{instrument}-{page_index:03d}.json"
        path.write_bytes(payload)
        rows = doc["data"]
        if not rows:
            raise ValueError(f"empty history page for {instrument}")
        timestamps: list[int] = []
        for row in rows:
            if not (isinstance(row, list) and len(row) == 9 and all(isinstance(x, str) for x in row)):
                raise ValueError(f"invalid candle schema for {instrument}")
            ts = int(row[0])
            timestamps.append(ts)
            if START_MS <= ts <= END_MS:
                record = {
                    "timestamp_ms": ts,
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume_base": float(row[5]),
                    "volume_quote": float(row[7]),
                    "confirm": row[8],
                }
                old = candles.get(ts)
                if old is not None and old != record:
                    raise ValueError(f"conflicting duplicate {instrument} {iso(ts)}")
                candles[ts] = record
        oldest = min(timestamps)
        newest = max(timestamps)
        pages.append({"request_url": url, "path": str(path), "sha256": sha256(payload), "row_count": len(rows), "oldest": iso(oldest), "newest": iso(newest)})
        if oldest <= START_MS:
            break
        if oldest >= cursor:
            raise ValueError(f"pagination failed to advance for {instrument}")
        cursor = oldest
        page_index += 1
        if page_index > 180:
            raise ValueError(f"pagination budget exhausted for {instrument}")
        time.sleep(0.12)

    ordered: list[dict[str, Any]] = []
    for i in range(ROWS):
        ts = START_MS + i * HOUR_MS
        candle = candles.get(ts)
        if candle is None:
            raise ValueError(f"missing {instrument} candle {iso(ts)}")
        if candle["confirm"] != "1":
            raise ValueError(f"incomplete {instrument} candle {iso(ts)}")
        for field in ("open", "high", "low", "close"):
            value = float(candle[field])
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"invalid {field} {instrument} {iso(ts)}")
        ordered.append(candle)
    return ordered, pages


def annualized_sharpe(returns: list[float]) -> float | None:
    if len(returns) < 2:
        return None
    std = statistics.stdev(returns)
    if std == 0:
        return None
    return statistics.mean(returns) / std * math.sqrt(365.25 * 24)


def max_drawdown(returns: list[float]) -> float:
    equity = 1.0
    peak = 1.0
    worst = 0.0
    for value in returns:
        equity *= 1.0 + value
        peak = max(peak, equity)
        worst = min(worst, equity / peak - 1.0)
    return worst


def compounded(returns: list[float]) -> float:
    equity = 1.0
    for value in returns:
        equity *= 1.0 + value
    return equity - 1.0


def loss_clusters(returns: list[float]) -> dict[str, Any]:
    runs: list[int] = []
    current = 0
    for value in returns:
        if value < 0:
            current += 1
        elif current:
            runs.append(current)
            current = 0
    if current:
        runs.append(current)
    return {"loss_count": sum(value < 0 for value in returns), "cluster_count": len(runs), "maximum_consecutive_losses": max(runs, default=0)}


def build_targets(candles: list[dict[str, Any]], mode: str) -> list[int]:
    targets = [0] * ROWS
    current = 0
    for i in range(LOOKBACK_HOURS, SCORE_END):
        if i % DAY_HOURS == 0:
            margin = candles[i]["close"] / candles[i - LOOKBACK_HOURS]["close"] - 1.0
            if mode in ("hourly", "daily"):
                current = int(margin > 0.0)
            elif mode == "candidate":
                prior_i = i - DAY_HOURS
                prior_margin = candles[prior_i]["close"] / candles[prior_i - LOOKBACK_HOURS]["close"] - 1.0
                current = int(margin > 0.0 and margin - prior_margin > 0.0)
            else:
                raise ValueError(mode)
        elif mode == "hourly":
            margin = candles[i]["close"] / candles[i - LOOKBACK_HOURS]["close"] - 1.0
            current = int(margin > 0.0)
        targets[i] = current
    return targets


def returns_for(candles: list[dict[str, Any]], targets: list[int]) -> tuple[list[float], list[float], list[float]]:
    net = [0.0] * SCORE_END
    gross = [0.0] * SCORE_END
    fees = [0.0] * SCORE_END
    prior_position = 0
    for i in range(SCORE_END):
        position = targets[i]
        turnover = abs(position - prior_position)
        fee = turnover * FEE_RATE
        asset = candles[i + 1]["open"] / candles[i]["open"] - 1.0
        gross[i] = position * asset
        fees[i] = fee
        net[i] = gross[i] - fee
        prior_position = position
    return net, gross, fees


def summarize(returns: list[float], fees: list[float], targets: list[int], start: int, end: int) -> dict[str, Any]:
    subset = returns[start:end]
    turnover = 0.0
    prior = targets[start - 1] if start > 0 else 0
    for i in range(start, end):
        turnover += abs(targets[i] - prior)
        prior = targets[i]
    net = compounded(subset)
    return {
        "compounded_net_return": net,
        "annualized_sharpe": annualized_sharpe(subset),
        "maximum_drawdown": max_drawdown(subset),
        "turnover": turnover,
        "modeled_fees": sum(fees[start:end]),
        "edge_per_turnover_bps": net / turnover * 10_000.0 if turnover > 0 else None,
        "signal_frequency": sum(targets[start:end]) / max(1, end - start),
        "loss_clustering": loss_clusters(subset),
    }


def bootstrap_delta(candidate: list[float], base: list[float], seed: int) -> dict[str, Any]:
    n = len(candidate)
    rng = random.Random(seed)
    mean_deltas: list[float] = []
    sharpe_deltas: list[float] = []
    blocks = math.ceil(n / BOOT_BLOCK)
    for _ in range(BOOT_RESAMPLES):
        idx: list[int] = []
        for _ in range(blocks):
            start = rng.randrange(0, n - BOOT_BLOCK + 1)
            idx.extend(range(start, start + BOOT_BLOCK))
        idx = idx[:n]
        c = [candidate[i] for i in idx]
        b = [base[i] for i in idx]
        mean_deltas.append((statistics.mean(c) - statistics.mean(b)) * 365.25 * 24)
        sharpe_deltas.append((annualized_sharpe(c) or 0.0) - (annualized_sharpe(b) or 0.0))
    mean_deltas.sort()
    sharpe_deltas.sort()
    lo = int(0.025 * BOOT_RESAMPLES)
    hi = int(0.975 * BOOT_RESAMPLES) - 1
    return {"annualized_mean_delta_ci95": [mean_deltas[lo], mean_deltas[hi]], "sharpe_delta_ci95": [sharpe_deltas[lo], sharpe_deltas[hi]]}


def evaluate_market(candles: list[dict[str, Any]], instrument: str, seed_offset: int) -> dict[str, Any]:
    target_map = {"candidate": build_targets(candles, "candidate"), "daily_B1": build_targets(candles, "daily"), "hourly_B0": build_targets(candles, "hourly")}
    data: dict[str, Any] = {}
    return_map: dict[str, list[float]] = {}
    for name, targets in target_map.items():
        net, _gross, fees = returns_for(candles, targets)
        return_map[name] = net
        data[name] = {"training": summarize(net, fees, targets, TRAIN_START, OOS_START), "development_oos": summarize(net, fees, targets, OOS_START, SCORE_END), "full_scored": summarize(net, fees, targets, TRAIN_START, SCORE_END)}

    candidate_oos = return_map["candidate"][OOS_START:SCORE_END]
    base_oos = return_map["daily_B1"][OOS_START:SCORE_END]
    residual = [c - b for c, b in zip(candidate_oos, base_oos)]
    folds: list[dict[str, Any]] = []
    for fold in range(12):
        start = OOS_START + fold * FOLD_HOURS
        end = start + FOLD_HOURS
        c = compounded(return_map["candidate"][start:end])
        b = compounded(return_map["daily_B1"][start:end])
        folds.append({"fold": fold + 1, "start": iso(START_MS + start * HOUR_MS), "end": iso(START_MS + end * HOUR_MS), "candidate_minus_B1": c - b})

    years: list[dict[str, Any]] = []
    for year in (2023, 2024, 2025, 2026):
        indices = [i for i in range(OOS_START, SCORE_END) if datetime.fromtimestamp((START_MS + i * HOUR_MS) / 1000, tz=UTC).year == year]
        if indices:
            start = min(indices)
            end = max(indices) + 1
            years.append({"year": year, "candidate_minus_B1": compounded(return_map["candidate"][start:end]) - compounded(return_map["daily_B1"][start:end])})

    inference = bootstrap_delta(candidate_oos, base_oos, BOOT_SEED + seed_offset)
    cmet = data["candidate"]["development_oos"]
    bmet = data["daily_B1"]["development_oos"]
    gates = {
        "return": cmet["compounded_net_return"] > bmet["compounded_net_return"],
        "sharpe": (cmet["annualized_sharpe"] or -1e9) > (bmet["annualized_sharpe"] or -1e9),
        "drawdown": cmet["maximum_drawdown"] >= bmet["maximum_drawdown"],
        "turnover": cmet["turnover"] <= bmet["turnover"],
        "edge_per_turnover": (cmet["edge_per_turnover_bps"] or -1e9) >= (bmet["edge_per_turnover_bps"] or -1e9),
        "fold_breadth": sum(row["candidate_minus_B1"] > 0 for row in folds) >= 7,
        "year_breadth": sum(row["candidate_minus_B1"] > 0 for row in years) >= 3,
        "residual_sharpe": (annualized_sharpe(residual) or -1e9) > 0,
        "mean_uncertainty": inference["annualized_mean_delta_ci95"][0] > 0,
        "sharpe_uncertainty": inference["sharpe_delta_ci95"][0] > 0,
    }
    return {
        "instrument": instrument,
        "metrics": data,
        "profitable_fold_count": sum(row["candidate_minus_B1"] > 0 for row in folds),
        "profitable_year_count": sum(row["candidate_minus_B1"] > 0 for row in years),
        "folds": folds,
        "years": years,
        "residual_sharpe": annualized_sharpe(residual),
        "inference": inference,
        "gates": gates,
        "all_per_market_gates_passed": all(gates.values()),
        "diagnostic": {
            "candidate_long_hours": sum(target_map["candidate"][OOS_START:SCORE_END]),
            "base_long_hours": sum(target_map["daily_B1"][OOS_START:SCORE_END]),
            "candidate_only_long_hours": sum(c == 1 and b == 0 for c, b in zip(target_map["candidate"][OOS_START:SCORE_END], target_map["daily_B1"][OOS_START:SCORE_END])),
            "base_only_long_hours": sum(c == 0 and b == 1 for c, b in zip(target_map["candidate"][OOS_START:SCORE_END], target_map["daily_B1"][OOS_START:SCORE_END])),
            "base_only_arithmetic_return": sum(b - c for c, b in zip(candidate_oos, base_oos)),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--base-url", default="https://www.okx.com")
    args = parser.parse_args()
    out = args.output_dir
    source = out / "source"
    market_results: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    for offset, instrument in enumerate(MARKETS):
        candles, pages = fetch_market(args.base_url.rstrip("/"), instrument, source / instrument)
        market_results.append(evaluate_market(candles, instrument, offset * 1000))
        source_payload = canonical([c["timestamp_ms"] for c in candles] + [c["open"] for c in candles] + [c["close"] for c in candles])
        sources.append({"instrument": instrument, "row_count": len(candles), "first": iso(candles[0]["timestamp_ms"]), "last": iso(candles[-1]["timestamp_ms"]), "source_sha256": sha256(source_payload), "pages": pages, "contiguous_confirmed_grid_passed": True})

    common = {
        "median_annualized_mean_delta_lower_bound": statistics.median([m["inference"]["annualized_mean_delta_ci95"][0] for m in market_results]),
        "median_sharpe_delta_lower_bound": statistics.median([m["inference"]["sharpe_delta_ci95"][0] for m in market_results]),
    }
    common["passed"] = common["median_annualized_mean_delta_lower_bound"] > 0 and common["median_sharpe_delta_lower_bound"] > 0
    accepted = all(m["all_per_market_gates_passed"] for m in market_results) and common["passed"]
    verdict = "accept_daily_margin_acceleration_confirmation" if accepted else "reject_daily_margin_acceleration_confirmation_family"
    result = {
        "schema_version": 1,
        "family_id": FAMILY_ID,
        "issue": ISSUE,
        "generated_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        "bar": BAR,
        "canonical_fee_bps_one_way": 5.0,
        "candidate_count": 1,
        "parameter_grid_count": 0,
        "strategy_boundary": "own-instrument completed lagged sequence to same-instrument unlevered long/cash",
        "cross_sectional_selection": False,
        "credentials_used": False,
        "private_endpoints_used": False,
        "actual_orders": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "sample": {"warmup": [0, TRAIN_START], "training": [TRAIN_START, OOS_START], "development_oos": [OOS_START, SCORE_END], "full_scored": [TRAIN_START, SCORE_END]},
        "candidate_rule": "at daily 00:00 UTC, long iff 2160H margin > 0 and margin minus its 24H-lagged value > 0; execute next open",
        "markets": market_results,
        "sources": sources,
        "common_index_gate": common,
        "accepted": accepted,
        "verdict": verdict,
        "training_authorized_correction": {"permitted": accepted, "applied": False},
    }
    out.mkdir(parents=True, exist_ok=True)
    payload = canonical(result)
    (out / "result.json").write_bytes(payload)
    (out / "result.sha256").write_text(sha256(payload) + "\n")
    lines = [f"# Daily 2160H margin-acceleration confirmation: {'accepted' if accepted else 'rejected'}", "", f"Verdict: `{verdict}`", "", "| Market | Candidate net | B1 net | Candidate Sharpe | B1 Sharpe | Candidate DD | B1 DD | Turnover | B1 turnover | Folds | Years | Residual Sharpe |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for market in market_results:
        c = market["metrics"]["candidate"]["development_oos"]
        b = market["metrics"]["daily_B1"]["development_oos"]
        lines.append(f"| {market['instrument']} | {c['compounded_net_return']:.2%} | {b['compounded_net_return']:.2%} | {(c['annualized_sharpe'] or 0):.3f} | {(b['annualized_sharpe'] or 0):.3f} | {c['maximum_drawdown']:.2%} | {b['maximum_drawdown']:.2%} | {c['turnover']:.1f} | {b['turnover']:.1f} | {market['profitable_fold_count']}/12 | {market['profitable_year_count']}/4 | {(market['residual_sharpe'] or 0):.3f} |")
    lines += ["", "The result is training/development evidence only. It does not alter the nominated prospective policy or authorize paper/live trading."]
    (out / "report.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
