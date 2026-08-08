#!/usr/bin/env python3
"""Exact-fidelity forward repair for the frozen causal E2160 1H policy.

This evaluator exists because the inherited prospective runner used idx-2161
rather than the canonical pct_change(2160) endpoint. It restores the declared
policy, fetches enough public history to cover the entire persisted forward
window plus the exact 2160H warm-up, and quantifies whether the superseded
2161-index calculation changed any long/cash decisions.
"""
from __future__ import annotations

import hashlib
import json
import math
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_URL = "https://www.okx.com"
LOOKBACK = 2160
INTERVAL_MS = 3_600_000
FEE = 0.0005
PRIOR_LAST_SIGNAL_MS = 1785765600000  # 2026-08-03T14:00:00Z
PRIOR_CUMULATIVE_REALIZED_HOURS = 638
INSTRUMENTS = ("BTC-USDT", "ETH-USDT")


def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def get_json(path: str, params: dict[str, str]) -> tuple[bytes, dict[str, Any], str]:
    url = f"{BASE_URL}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "gpt-quant-prospective-fidelity/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read()
        final_url = resp.geturl()
    payload = json.loads(raw.decode("utf-8"))
    if payload.get("code") != "0":
        raise RuntimeError(f"OKX error for {url}: {payload}")
    return raw, payload, final_url


def fetch_candles(inst: str, root: Path) -> dict[str, Any]:
    out = root / inst
    out.mkdir(parents=True, exist_ok=True)
    rows: dict[int, list[str]] = {}
    pages: list[dict[str, Any]] = []

    raw, payload, final_url = get_json(
        "/api/v5/market/candles", {"instId": inst, "bar": "1H", "limit": "300"}
    )
    (out / "page-00.json").write_bytes(raw)
    data = payload["data"]
    for row in data:
        rows[int(row[0])] = row
    pages.append(
        {
            "request": final_url,
            "sha256": sha256_bytes(raw),
            "row_count": len(data),
            "newest_ms": max(int(r[0]) for r in data),
            "oldest_ms": min(int(r[0]) for r in data),
        }
    )

    # Earliest new signal is PRIOR_LAST_SIGNAL_MS + 1H and its exact canonical
    # denominator is 2160 indices/hours earlier. Fetch slightly beyond that
    # boundary rather than relying on a fixed latest-row count.
    required_oldest_ms = PRIOR_LAST_SIGNAL_MS - LOOKBACK * INTERVAL_MS
    page_no = 0
    while min(rows) > required_oldest_ms:
        oldest = min(rows)
        page_no += 1
        raw, payload, final_url = get_json(
            "/api/v5/market/history-candles",
            {"instId": inst, "bar": "1H", "limit": "300", "after": str(oldest)},
        )
        data = payload["data"]
        if not data:
            raise RuntimeError(f"No older candles returned for {inst} after {oldest}")
        before = len(rows)
        for row in data:
            rows[int(row[0])] = row
        if len(rows) == before:
            raise RuntimeError(f"Pagination stalled for {inst} at {oldest}")
        page_path = out / f"page-{page_no:02d}.json"
        page_path.write_bytes(raw)
        pages.append(
            {
                "request": final_url,
                "sha256": sha256_bytes(raw),
                "row_count": len(data),
                "newest_ms": max(int(r[0]) for r in data),
                "oldest_ms": min(int(r[0]) for r in data),
            }
        )

    ordered = [rows[k] for k in sorted(rows)]
    completed = [r for r in ordered if len(r) >= 9 and r[8] == "1"]
    incomplete = [r for r in ordered if len(r) >= 9 and r[8] != "1"]
    completed.sort(key=lambda r: int(r[0]))
    ts = [int(r[0]) for r in completed]

    if not completed or ts[0] > required_oldest_ms:
        raise RuntimeError(
            f"Warm-up coverage failure for {inst}: oldest={iso(ts[0]) if ts else None}, "
            f"required<={iso(required_oldest_ms)}"
        )
    for a, b in zip(ts, ts[1:]):
        if b - a != INTERVAL_MS:
            raise RuntimeError(f"Non-contiguous completed 1H grid for {inst}: {iso(a)} -> {iso(b)}")
    if any(float(r[j]) <= 0 or not math.isfinite(float(r[j])) for r in completed for j in (1, 2, 3, 4)):
        raise RuntimeError(f"Non-positive/non-finite OHLC for {inst}")

    current_open = None
    current_ts = None
    if incomplete:
        latest = max(incomplete, key=lambda r: int(r[0]))
        current_ts = int(latest[0])
        current_open = float(latest[1])
        if not math.isfinite(current_open) or current_open <= 0:
            raise RuntimeError(f"Invalid current fixed open for {inst}")

    completed_bytes = (json.dumps(completed, separators=(",", ":")) + "\n").encode()
    (out / "completed.json").write_bytes(completed_bytes)
    manifest = {
        "instrument": inst,
        "bar": "1H",
        "required_oldest_ms": required_oldest_ms,
        "required_oldest": iso(required_oldest_ms),
        "first_completed_ms": ts[0],
        "first_completed": iso(ts[0]),
        "last_completed_ms": ts[-1],
        "last_completed": iso(ts[-1]),
        "completed_count": len(completed),
        "current_open_ms": current_ts,
        "current_open": current_open,
        "completed_sha256": sha256_bytes(completed_bytes),
        "pages": pages,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return {"completed": completed, "current_open": current_open, "current_ts": current_ts, "manifest": manifest}


def canonical_margin(closes: list[float], i: int) -> float:
    return closes[i] / closes[i - LOOKBACK] - 1.0


def superseded_margin(closes: list[float], i: int) -> float:
    return closes[i] / closes[i - LOOKBACK - 1] - 1.0


def evaluate(inst: str, source: dict[str, Any], root: Path) -> dict[str, Any]:
    rows = source["completed"]
    ts = [int(r[0]) for r in rows]
    opens = [float(r[1]) for r in rows]
    closes = [float(r[4]) for r in rows]
    index = {t: i for i, t in enumerate(ts)}
    if PRIOR_LAST_SIGNAL_MS not in index:
        raise RuntimeError(f"Persisted prior signal missing for {inst}")
    prior_i = index[PRIOR_LAST_SIGNAL_MS]
    if prior_i < LOOKBACK + 1:
        raise RuntimeError(f"Insufficient prior-signal warm-up for {inst}")

    prior_target = int(canonical_margin(closes, prior_i) > 0)
    superseded_prior_target = int(superseded_margin(closes, prior_i) > 0)
    if prior_target != superseded_prior_target:
        raise RuntimeError(
            f"Prior checkpoint target changes under fidelity repair for {inst}; epoch state needs separate adjudication"
        )

    intervals: list[dict[str, Any]] = []
    prev_target = prior_target
    target_disagreement_count = 0
    max_margin_abs_difference = 0.0

    for i, t in enumerate(ts):
        if t <= PRIOR_LAST_SIGNAL_MS or i < LOOKBACK + 1:
            continue
        entry_i = i + 1
        payoff_i = i + 2
        if entry_i >= len(opens):
            continue
        entry_open = opens[entry_i]
        if payoff_i < len(opens):
            exit_open = opens[payoff_i]
            endpoint_ms = ts[payoff_i]
        elif (
            source["current_open"] is not None
            and source["current_ts"] is not None
            and source["current_ts"] == ts[entry_i] + INTERVAL_MS
        ):
            exit_open = source["current_open"]
            endpoint_ms = source["current_ts"]
        else:
            continue

        margin = canonical_margin(closes, i)
        old_margin = superseded_margin(closes, i)
        target = int(margin > 0)
        old_target = int(old_margin > 0)
        target_disagreement_count += int(target != old_target)
        max_margin_abs_difference = max(max_margin_abs_difference, abs(margin - old_margin))
        turnover = abs(target - prev_target)
        modeled_fee = FEE * turnover
        asset_return = exit_open / entry_open - 1.0
        net_return = target * asset_return - modeled_fee
        intervals.append(
            {
                "signal_hour_start": iso(t),
                "signal_hour_start_ms": t,
                "execution_open": iso(ts[entry_i]),
                "execution_open_ms": ts[entry_i],
                "payoff_open_end": iso(endpoint_ms),
                "payoff_open_end_ms": endpoint_ms,
                "canonical_margin": margin,
                "superseded_2161_index_margin": old_margin,
                "target": target,
                "superseded_target": old_target,
                "previous_target": prev_target,
                "asset_return": asset_return,
                "turnover": turnover,
                "modeled_fee": modeled_fee,
                "net_strategy_return": net_return,
                "benchmark_residual": net_return - asset_return,
            }
        )
        prev_target = target

    if not intervals:
        raise RuntimeError(f"No fully realised forward intervals for {inst}")

    returns = [x["net_strategy_return"] for x in intervals]
    benchmark = [x["asset_return"] for x in intervals]
    turnover = sum(x["turnover"] for x in intervals)
    fees = sum(x["modeled_fee"] for x in intervals)
    compound = math.prod(1 + r for r in returns) - 1
    bench_compound = math.prod(1 + r for r in benchmark) - 1
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1) if len(returns) > 1 else 0.0
    sharpe = mean / math.sqrt(variance) * math.sqrt(8760) if variance > 0 else None

    equity = peak = 1.0
    max_dd = 0.0
    losses = streak = max_streak = 0
    for r in returns:
        equity *= 1 + r
        peak = max(peak, equity)
        max_dd = min(max_dd, equity / peak - 1)
        if r < 0:
            losses += 1
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0

    margins = [x["canonical_margin"] for x in intervals]
    recent = intervals[-5:]
    result = {
        "instrument": inst,
        "prior_target": prior_target,
        "new_interval_count": len(intervals),
        "first_signal": intervals[0]["signal_hour_start"],
        "last_signal": intervals[-1]["signal_hour_start"],
        "latest_target": intervals[-1]["target"],
        "signal_frequency": sum(x["target"] for x in intervals) / len(intervals),
        "no_trade_frequency": 1 - sum(x["target"] for x in intervals) / len(intervals),
        "net_compound_return": compound,
        "benchmark_compound_return": bench_compound,
        "benchmark_residual": compound - bench_compound,
        "sharpe": sharpe,
        "turnover": turnover,
        "fees": fees,
        "edge_per_turnover_bps": sum(returns) / turnover * 10000 if turnover else None,
        "maximum_drawdown": max_dd,
        "loss_count": losses,
        "max_loss_streak": max_streak,
        "margin_start": margins[0],
        "margin_end": margins[-1],
        "margin_drift": margins[-1] - margins[0],
        "recent_5h_benchmark_return": math.prod(1 + x["asset_return"] for x in recent) - 1,
        "fidelity_audit": {
            "superseded_formula": "close[i] / close[i-2161] - 1",
            "canonical_formula": "close[i] / close[i-2160] - 1",
            "target_disagreement_count": target_disagreement_count,
            "max_margin_abs_difference": max_margin_abs_difference,
            "prior_target_agrees": prior_target == superseded_prior_target,
        },
        "intervals": intervals,
    }
    (root / inst / "forward_intervals.json").write_text(json.dumps(intervals, indent=2, sort_keys=True) + "\n")
    return result


def main() -> None:
    root = Path("reports/prospective/e2160-fidelity-repair")
    root.mkdir(parents=True, exist_ok=True)
    time_raw, time_payload, time_url = get_json("/api/v5/public/time", {})
    (root / "server-time.json").write_bytes(time_raw)
    server_ms = int(time_payload["data"][0]["ts"])

    sources = {inst: fetch_candles(inst, root) for inst in INSTRUMENTS}
    markets = [evaluate(inst, sources[inst], root) for inst in INSTRUMENTS]
    counts = {m["instrument"]: m["new_interval_count"] for m in markets}
    if len(set(counts.values())) != 1:
        raise RuntimeError(f"Forward interval count mismatch: {counts}")

    any_target_change = any(m["fidelity_audit"]["target_disagreement_count"] > 0 for m in markets)
    if any_target_change:
        verdict = "abort_and_restart_forward_epoch_due_policy_fidelity_target_change"
        abort_conditions = ["canonical_2160_vs_superseded_2161_target_disagreement"]
    else:
        verdict = "prospective_simple_trend_forward_epoch_revalidated_after_e2160_fidelity_repair"
        abort_conditions = []

    payload = {
        "schema_version": "prospective-strategy-optimizer-e2160-fidelity-repair-v1",
        "generated_at": iso(server_ms),
        "server_time_request": time_url,
        "policy_name": "simple_trend_long_cash_2160h_next_open",
        "policy_definition": {
            "signal": "close[t] / close[t-2160] - 1 > 0",
            "execution": "next observed hourly open",
            "position_set": [0, 1],
            "fee_bps_one_way": 5,
            "bar": "1H",
            "per_instrument_only": True,
        },
        "repair": {
            "classification": "policy-fidelity correctness repair, not strategy mutation",
            "defects": [
                "superseded runner used idx-2161 denominator instead of canonical idx-2160",
                "superseded runner fetched a fixed latest-row count rather than guaranteeing full checkpoint-plus-lookback coverage",
            ],
            "strategy_parameter_changed": False,
            "correct_policy_restored": True,
        },
        "prior_checkpoint": {
            "last_signal_bar_start": iso(PRIOR_LAST_SIGNAL_MS),
            "cumulative_realized_hours": PRIOR_CUMULATIVE_REALIZED_HOURS,
        },
        "sources": [sources[i]["manifest"] for i in INSTRUMENTS],
        "markets": markets,
        "observations": {
            "new_realized_intervals_per_market": counts,
            "updated_cumulative_realized_hours": PRIOR_CUMULATIVE_REALIZED_HOURS + min(counts.values()),
        },
        "abort_conditions": abort_conditions,
        "training_authorized_correction": {
            "permitted": False,
            "applied": False,
            "policy_changed": False,
            "observation_epoch_restarted": any_target_change,
            "reason": "This run restores exact implementation fidelity; it does not use forward data to alter the strategy rule.",
        },
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "verdict": verdict,
        "next_strategy_facing_action": (
            "Continue only the canonical idx-2160 forward evaluator at the next fully completed 1H payoff endpoint. "
            "Treat superseded idx-2161 margin values as invalid policy evidence."
        ),
    }
    text = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    (root / "result.json").write_text(text)
    result_sha = sha256_bytes(text.encode())
    (root / "result.sha256").write_text(result_sha + "\n")

    lines = [
        "# Prospective E2160 policy-fidelity repair",
        "",
        f"Generated at `{payload['generated_at']}`.",
        "",
        "Canonical signal restored to `close[t] / close[t-2160] - 1 > 0`; exactly 5 bps one way; public OKX SPOT 1H only.",
        "",
        "| Instrument | Intervals | Latest target | Net | Benchmark | Turnover | Fees | Margin end | Target disagreements vs superseded |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for m in markets:
        lines.append(
            f"| {m['instrument']} | {m['new_interval_count']} | {m['latest_target']} | "
            f"{m['net_compound_return']:.6%} | {m['benchmark_compound_return']:+.6%} | "
            f"{m['turnover']:.0f} | {m['fees']:.6%} | {m['margin_end']:.6%} | "
            f"{m['fidelity_audit']['target_disagreement_count']} |"
        )
    lines.extend(
        [
            "",
            f"Verdict: `{verdict}`",
            "",
            f"Result SHA-256: `{result_sha}`",
        ]
    )
    (root / "report.md").write_text("\n".join(lines) + "\n")
    print(text)


if __name__ == "__main__":
    main()
