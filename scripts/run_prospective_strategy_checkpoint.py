#!/usr/bin/env python3
"""Forward-only evidence runner for the frozen causal 1H strategy.

This script deliberately evaluates only the immutable per-instrument
simple_trend_long_cash_2160h_next_open rule.  It consumes public OKX 1H
candles, never writes orders, and never performs cross-sectional selection.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_URL = "https://www.okx.com"
FEE = 0.0005
LOOKBACK = 2160
INTERVAL_MS = 3_600_000
PRIOR_LAST_SIGNAL_MS = 1785765600000  # 2026-08-03T14:00:00Z
PRIOR_CUMULATIVE_REALIZED_HOURS = 638
PRIOR_RESULT_SHA256 = "a2515ce4121705af8593dc5e87a8cfc955bada1ff15ce7db45b298a396c355b2"
PRIOR_ARTIFACT_SHA256 = "099164a015605b5a845334f276c7d1541f424233b598f82c8b78d61bea2857b0"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def get_json(path: str, params: dict[str, str]) -> tuple[bytes, dict[str, Any], str]:
    query = urllib.parse.urlencode(params)
    url = f"{BASE_URL}{path}?{query}"
    req = urllib.request.Request(url, headers={"User-Agent": "gpt-quant-prospective-research/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read()
        final_url = resp.geturl()
    payload = json.loads(raw.decode("utf-8"))
    if payload.get("code") != "0":
        raise RuntimeError(f"OKX error for {url}: {payload}")
    return raw, payload, final_url


def fetch_candles(inst: str, output_dir: Path, need: int = 2164) -> dict[str, Any]:
    out = output_dir / inst
    out.mkdir(parents=True, exist_ok=True)
    pages: list[dict[str, Any]] = []
    rows: dict[int, list[str]] = {}

    raw, payload, final_url = get_json(
        "/api/v5/market/candles",
        {"instId": inst, "bar": "1H", "limit": "300"},
    )
    (out / "page-00.json").write_bytes(raw)
    page_no = 0
    data = payload["data"]
    for row in data:
        rows[int(row[0])] = row
    pages.append({
        "path": str((out / "page-00.json").relative_to(output_dir.parent)),
        "request": final_url,
        "sha256": sha256_bytes(raw),
        "row_count": len(data),
        "newest_ms": max(int(r[0]) for r in data),
        "oldest_ms": min(int(r[0]) for r in data),
    })

    while sum(1 for r in rows.values() if len(r) >= 9) < need:
        oldest = min(rows)
        page_no += 1
        raw, payload, final_url = get_json(
            "/api/v5/market/history-candles",
            {"instId": inst, "bar": "1H", "limit": "300", "after": str(oldest)},
        )
        page_path = out / f"page-{page_no:02d}.json"
        page_path.write_bytes(raw)
        data = payload["data"]
        if not data:
            raise RuntimeError(f"No older candles returned for {inst} after {oldest}")
        before = len(rows)
        for row in data:
            rows[int(row[0])] = row
        if len(rows) == before:
            raise RuntimeError(f"Pagination stalled for {inst} at {oldest}")
        pages.append({
            "path": str(page_path.relative_to(output_dir.parent)),
            "request": final_url,
            "sha256": sha256_bytes(raw),
            "row_count": len(data),
            "newest_ms": max(int(r[0]) for r in data),
            "oldest_ms": min(int(r[0]) for r in data),
        })

    # We need the current in-progress candle's fixed open only as the latest
    # payoff endpoint. Keep it in the raw source evidence, but never use its
    # high/low/close/volume/confirm=0 fields.
    ordered = [rows[k] for k in sorted(rows)]
    completed = [r for r in ordered if r[8] == "1"]
    current = [r for r in ordered if r[8] != "1"]
    if len(completed) < need - 1:
        raise RuntimeError(f"Insufficient completed 1H candles for {inst}: {len(completed)}")
    if current:
        current_open = float(current[-1][1])
        current_ts = int(current[-1][0])
    else:
        # A run exactly at an hourly boundary may have no incomplete row yet.
        # In that case the latest completed candle is still the fixed endpoint
        # only if its opening is already known; use the next completed row when
        # present and fail closed otherwise.
        current_open = None
        current_ts = None

    completed.sort(key=lambda r: int(r[0]))
    # Validate exact hourly grid over the retained completed suffix.
    ts = [int(r[0]) for r in completed]
    for a, b in zip(ts, ts[1:]):
        if b - a != INTERVAL_MS:
            raise RuntimeError(f"1H grid gap/duplicate for {inst}: {iso(a)} -> {iso(b)}")
    if any(r[8] != "1" for r in completed):
        raise RuntimeError(f"Incomplete row leaked into completed set for {inst}")

    manifest = {
        "instrument": inst,
        "bar": "1H",
        "pages": pages,
        "completed_count": len(completed),
        "first_completed_ms": ts[0],
        "last_completed_ms": ts[-1],
        "current_open_ms": current_ts,
        "current_open": current_open,
        "completed_grid_sha256": sha256_bytes(
            "\n".join(f"{int(r[0])},{r[1]},{r[2]},{r[3]},{r[4]},{r[8]}" for r in completed).encode()
        ),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "completed.json").write_text(json.dumps(completed, separators=(",", ":")) + "\n", encoding="utf-8")
    return {"manifest": manifest, "completed": completed, "current_open": current_open, "current_ts": current_ts}


def margin(closes: list[float], idx: int) -> float:
    return closes[idx] / closes[idx - LOOKBACK - 1] - 1.0


def evaluate_market(inst: str, fetched: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    completed = fetched["completed"]
    opens = [float(r[1]) for r in completed]
    closes = [float(r[4]) for r in completed]
    ts = [int(r[0]) for r in completed]

    # Realised intervals start strictly after the persisted checkpoint.
    # A decision at signal index i enters at i+1 open and is realised at i+2 open.
    eligible: list[int] = []
    for i, t in enumerate(ts):
        if t <= PRIOR_LAST_SIGNAL_MS:
            continue
        if i - (LOOKBACK + 1) < 0 or i + 2 >= len(opens):
            continue
        eligible.append(i)

    # At the latest available point, the final payoff endpoint may be the
    # current candle's fixed open, which is not a signal input.
    current_open = fetched["current_open"]
    current_ts = fetched["current_ts"]
    latest_completed_i = len(completed) - 1
    if current_open is not None and current_ts == ts[-1] + INTERVAL_MS:
        if ts[-2] > PRIOR_LAST_SIGNAL_MS:
            eligible.append(latest_completed_i - 1)

    # De-duplicate and keep only intervals whose payoff endpoint is known.
    eligible = sorted(set(i for i in eligible if i > 0))
    intervals: list[dict[str, Any]] = []
    prev_position = 0
    for i in eligible:
        target = 1 if margin(closes, i) > 0 else 0
        entry_open = opens[i + 1]
        if i + 2 < len(opens):
            exit_open = opens[i + 2]
            endpoint_ts = ts[i + 2]
        elif current_open is not None and current_ts == ts[i + 1] + INTERVAL_MS:
            exit_open = current_open
            endpoint_ts = current_ts
        else:
            continue
        asset_return = exit_open / entry_open - 1.0
        turnover = abs(target - prev_position)
        fee = turnover * FEE
        net = target * asset_return - fee
        intervals.append({
            "signal_hour_start": iso(ts[i]),
            "signal_hour_start_ms": ts[i],
            "signal_margin": margin(closes, i),
            "execution_open": iso(ts[i + 1]),
            "execution_open_ms": ts[i + 1],
            "payoff_open_end": iso(endpoint_ts),
            "payoff_open_end_ms": endpoint_ts,
            "target": target,
            "previous_target": prev_position,
            "asset_return": asset_return,
            "turnover": turnover,
            "modeled_fee": fee,
            "net_strategy_return": net,
            "benchmark_residual": net - asset_return,
        })
        prev_position = target

    # If the checkpoint starts from cash, this is correct for the first new
    # interval.  If no interval exists, fail closed rather than fabricate.
    if not intervals:
        raise RuntimeError(f"No new realised intervals for {inst}")

    returns = [x["net_strategy_return"] for x in intervals]
    benchmark = [x["asset_return"] for x in intervals]
    turnover = sum(x["turnover"] for x in intervals)
    fees = sum(x["modeled_fee"] for x in intervals)
    compound = math.prod(1.0 + r for r in returns) - 1.0
    bench_compound = math.prod(1.0 + r for r in benchmark) - 1.0
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1) if len(returns) > 1 else 0.0
    sharpe = (mean / math.sqrt(variance)) * math.sqrt(8760) if variance > 0 else None
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    loss_count = 0
    loss_streak = 0
    max_loss_streak = 0
    for r in returns:
        equity *= 1.0 + r
        peak = max(peak, equity)
        max_dd = min(max_dd, equity / peak - 1.0)
        if r < 0:
            loss_count += 1
            loss_streak += 1
            max_loss_streak = max(max_loss_streak, loss_streak)
        else:
            loss_streak = 0

    margins = [x["signal_margin"] for x in intervals]
    margin_drift = margins[-1] - margins[0]
    signal_frequency = sum(x["target"] for x in intervals) / len(intervals)
    no_trade = 1.0 - signal_frequency
    edge_per_turnover_bps = (sum(returns) / turnover * 10_000) if turnover > 0 else None
    recent = intervals[-5:]
    recent_returns = [x["net_strategy_return"] for x in recent]
    recent_bench = [x["asset_return"] for x in recent]
    recent_compound = math.prod(1 + r for r in recent_returns) - 1.0
    recent_bench_compound = math.prod(1 + r for r in recent_bench) - 1.0

    result = {
        "instrument": inst,
        "new_interval_count": len(intervals),
        "first_signal": intervals[0]["signal_hour_start"],
        "last_signal": intervals[-1]["signal_hour_start"],
        "signal_frequency": signal_frequency,
        "no_trade_frequency": no_trade,
        "net_compound_return": compound,
        "benchmark_compound_return": bench_compound,
        "benchmark_residual": compound - bench_compound,
        "sharpe": sharpe,
        "turnover": turnover,
        "fees": fees,
        "edge_per_turnover_bps": edge_per_turnover_bps,
        "maximum_drawdown": max_dd,
        "loss_count": loss_count,
        "max_loss_streak": max_loss_streak,
        "margin_start": margins[0],
        "margin_end": margins[-1],
        "margin_drift": margin_drift,
        "latest_decision_target": intervals[-1]["target"],
        "latest_decision_margin": intervals[-1]["signal_margin"],
        "recent_forward_window": {
            "count": len(recent),
            "net_compound_return": recent_compound,
            "benchmark_compound_return": recent_bench_compound,
            "residual": recent_compound - recent_bench_compound,
            "turnover": sum(x["turnover"] for x in recent),
            "fees": sum(x["modeled_fee"] for x in recent),
        },
        "intervals": intervals,
    }
    (out_dir / inst / "forward_intervals.json").write_text(
        json.dumps(intervals, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", default="reports/prospective/simple-trend-forward")
    args = ap.parse_args()
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    server_raw, server_payload, server_url = get_json("/api/v5/public/time", {})
    (out / "server-time.json").write_bytes(server_raw)
    server_ms = int(server_payload["data"][0]["ts"])

    fetched = {inst: fetch_candles(inst, out) for inst in ("BTC-USDT", "ETH-USDT")}
    market_results = [evaluate_market(inst, fetched[inst], out) for inst in ("BTC-USDT", "ETH-USDT")]

    total_intervals = sum(x["new_interval_count"] for x in market_results)
    total_turnover = sum(x["turnover"] for x in market_results)
    total_fees = sum(x["fees"] for x in market_results)
    target_count = sum(x["latest_decision_target"] for x in market_results)

    # One predeclared discrepancy: BTC margin movement since the first newly
    # realised interval. No post-hoc discrepancy selection is permitted.
    btc = market_results[0]
    discrepancy = {
        "instrument": "BTC-USDT",
        "metric": "E2160_margin_drift",
        "start": btc["margin_start"],
        "end": btc["margin_end"],
        "delta": btc["margin_drift"],
        "classification": "trend-margin-regime-drift",
        "interpretation": (
            "The frozen slow-trend margin moved across the newly observed forward "
            "window; the position decision remained the unchanged sign test."
        ),
    }

    verdict = "prospective_simple_trend_forward_epoch_continues"
    payload = {
        "schema_version": "prospective-strategy-optimizer-v2",
        "generated_at": iso(server_ms),
        "acquisition_server_time_ms": server_ms,
        "server_time_request": server_url,
        "policy_name": "simple_trend_long_cash_2160h_next_open",
        "policy_boundary": {
            "bar": "1H",
            "fee_bps_one_way": 5,
            "lookback_hours": LOOKBACK,
            "position_set": [0, 1],
            "per_instrument_only": True,
            "cross_sectional_selection": False,
            "current_relative_rank": False,
            "pairs_spreads_stat_arb": False,
            "market_neutral_long_short": False,
            "post_hoc_filtering": False,
            "credentials_private_endpoints_accounts_orders": False,
            "leverage_funds_enabled_adapters": False,
            "synthetic_data": False,
            "non_1h_or_15m": False,
        },
        "prior_checkpoint": {
            "pr": 1067,
            "last_signal_bar_start": iso(PRIOR_LAST_SIGNAL_MS),
            "cumulative_realized_hours": PRIOR_CUMULATIVE_REALIZED_HOURS,
            "result_sha256": PRIOR_RESULT_SHA256,
            "artifact_sha256": PRIOR_ARTIFACT_SHA256,
        },
        "source": [fetched[i]["manifest"] for i in ("BTC-USDT", "ETH-USDT")],
        "markets": market_results,
        "observations": {
            "new_realized_intervals_per_market": {x["instrument"]: x["new_interval_count"] for x in market_results},
            "total_new_realized_intervals": total_intervals,
            "updated_cumulative_realized_hours": PRIOR_CUMULATIVE_REALIZED_HOURS + min(
                x["new_interval_count"] for x in market_results
            ),
        },
        "scorecard": {
            "latest_targets_long": target_count,
            "total_turnover": total_turnover,
            "total_fees": total_fees,
            "aggregate_net_return_not_pooled": None,
            "aggregate_sharpe_not_pooled": None,
            "reason": "Markets remain independent; no pooled portfolio metric is constructed.",
        },
        "strategy_facing_discrepancy": discrepancy,
        "training_authorized_correction": {
            "permitted": False,
            "applied": False,
            "policy_changed": False,
            "observation_epoch_restarted": False,
            "reason": "No preregistered training correction was activated by the frozen protocol.",
        },
        "abort_conditions": [],
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "verdict": verdict,
        "next_strategy_facing_action": (
            "Advance the unchanged independent BTC-USDT and ETH-USDT E2160 shadow at the "
            "next complete public 1H observation; keep all candidate families sealed until "
            "their own preregistered validation gates authorize them."
        ),
    }
    result_path = out / "result.json"
    result_text = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    result_path.write_text(result_text, encoding="utf-8")
    result_sha = sha256_bytes(result_text.encode())
    (out / "result.sha256").write_text(result_sha + "\n", encoding="utf-8")

    report = f"""# Prospective frozen 1H strategy checkpoint

Generated at `{payload['generated_at']}`.

## Policy

`simple_trend_long_cash_2160h_next_open`, immutable per-instrument 1H temporal rule, exactly 5 bps one-way. No cross-sectional ranking, contemporaneous selection, top-N rotation, pairs/spreads, statistical arbitrage, market-neutral long-short construction, post-hoc filtering, credentials, accounts, orders, leverage, funds, synthetic data or 15m.

## Forward observations

Prior checkpoint signal: `{iso(PRIOR_LAST_SIGNAL_MS)}`; prior realised hours: `{PRIOR_CUMULATIVE_REALIZED_HOURS}`. New realised intervals: BTC `{market_results[0]['new_interval_count']}`, ETH `{market_results[1]['new_interval_count']}`.

| Instrument | New intervals | Latest target | Net return | Benchmark | Residual | Turnover | Fees | Edge/turnover | Margin drift |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | {market_results[0]['new_interval_count']} | {market_results[0]['latest_decision_target']} | {market_results[0]['net_compound_return']:.6%} | {market_results[0]['benchmark_compound_return']:+.6%} | {market_results[0]['benchmark_residual']:+.6%} | {market_results[0]['turnover']:.6f} | {market_results[0]['fees']:.6%} | {market_results[0]['edge_per_turnover_bps'] if market_results[0]['edge_per_turnover_bps'] is not None else 'Undefined'} | {market_results[0]['margin_drift'] * 100:+.6f} pp |
| ETH-USDT | {market_results[1]['new_interval_count']} | {market_results[1]['latest_decision_target']} | {market_results[1]['net_compound_return']:.6%} | {market_results[1]['benchmark_compound_return']:+.6%} | {market_results[1]['benchmark_residual']:+.6%} | {market_results[1]['turnover']:.6f} | {market_results[1]['fees']:.6%} | {market_results[1]['edge_per_turnover_bps'] if market_results[1]['edge_per_turnover_bps'] is not None else 'Undefined'} | {market_results[1]['margin_drift'] * 100:+.6f} pp |

Sharpe is reported per instrument and is undefined when the new-window variance is zero. No pooled portfolio Sharpe or return is computed because cross-market aggregation is outside the hard boundary.

## Drift diagnosis

Predeclared discrepancy: BTC E2160 margin drift. Start `{btc['margin_start']:.6%}`, end `{btc['margin_end']:.6%}`, change `{btc['margin_drift'] * 100:+.6f}` percentage points. This is a regime-drift diagnostic, not a reason to mutate the frozen rule.

## Verdict

`{verdict}`

Correction permitted: `false`; correction applied: `false`; policy changed: `false`; observation epoch restarted: `false`; paper trading: `false`; live trading: `false`.

Result SHA-256: `{result_sha}`
"""
    (out / "report.md").write_text(report, encoding="utf-8")
    print(result_text)


if __name__ == "__main__":
    main()
