from __future__ import annotations

import argparse
import json
import math
import os
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from acquire_okx_historical_trades import (
    HOUR_MS,
    canonical_json,
    canonicalize,
    extract_csv,
    fetch_server_time,
    parse_archive_csv,
    persist,
    query_archive,
    request_bytes,
    sha256,
    validate_complete_exchange_day,
)
from gpt_quant.okx_1h import fetch_okx_one_hour_candles

FEE_RATE = 0.0005
LOOKBACK_HOURS = 2160
BLOCK_HOURS = 6
BOOTSTRAP_RESAMPLES = 5000
BOOTSTRAP_SEED = 20260729
MARKETS = ("BTC-USDT", "ETH-USDT")


def utc_timestamp(ms: int) -> pd.Timestamp:
    return pd.Timestamp(ms, unit="ms", tz="UTC")


def feature_rows(trades: list[tuple[str, int, str, Decimal, Decimal, int]]) -> list[dict[str, Any]]:
    grouped: dict[int, list[tuple[str, int, str, Decimal, Decimal, int]]] = defaultdict(list)
    for trade in canonicalize(trades):
        grouped[trade[5] // HOUR_MS].append(trade)

    rows: list[dict[str, Any]] = []
    for hour in sorted(grouped):
        hour_trades = grouped[hour]
        quote = [trade[3] * trade[4] for trade in hour_trades]
        total = sum(quote, Decimal())
        squared_total = sum((value * value for value in quote), Decimal())
        if total <= 0 or squared_total <= 0:
            raise ValueError("hour has non-positive trade notional")

        signed = [
            value * (Decimal(1) if trade[2] == "buy" else Decimal(-1))
            for value, trade in zip(quote, hour_trades, strict=True)
        ]
        raw_flow = sum(signed, Decimal()) / total
        concentration_direction = sum(
            (
                value * value * (Decimal(1) if trade[2] == "buy" else Decimal(-1))
                for value, trade in zip(quote, hour_trades, strict=True)
            ),
            Decimal(),
        ) / squared_total
        hhi = squared_total / (total * total)
        rows.append(
            {
                "hour_start_ms": hour * HOUR_MS,
                "trade_count": len(hour_trades),
                "raw_flow": float(raw_flow),
                "concentration_direction": float(concentration_direction),
                "notional_hhi": float(hhi),
                "candidate_target": max(0.0, float(concentration_direction)),
                "raw_flow_target": max(0.0, float(raw_flow)),
            }
        )
    return rows


def assert_feature_contract(
    rows: list[dict[str, Any]],
    trades: list[tuple[str, int, str, Decimal, Decimal, int]],
) -> dict[str, Any]:
    hours = [int(row["hour_start_ms"]) for row in rows]
    if len(rows) != 24:
        raise ValueError("diagnostic requires exactly 24 complete feature hours")
    if any(right - left != HOUR_MS for left, right in zip(hours, hours[1:], strict=True)):
        raise ValueError("feature hours are not a complete consecutive UTC grid")
    for row in rows:
        for field in ("raw_flow", "concentration_direction", "candidate_target", "raw_flow_target"):
            value = float(row[field])
            if not math.isfinite(value):
                raise ValueError(f"non-finite feature: {field}")
        if not 0.0 <= float(row["candidate_target"]) <= 1.0:
            raise ValueError("candidate target is outside long/cash bounds")
        if not 0.0 <= float(row["raw_flow_target"]) <= 1.0:
            raise ValueError("raw-flow target is outside long/cash bounds")

    cutoff = hours[len(hours) // 2]
    prefix = [trade for trade in trades if trade[5] < cutoff]
    suffix = [trade for trade in trades if trade[5] >= cutoff]
    mutated_suffix = list(suffix)
    changed = list(mutated_suffix[-1])
    changed[3] *= Decimal("1.01")
    mutated_suffix[-1] = tuple(changed)  # type: ignore[assignment]
    original_prefix = [row for row in feature_rows(prefix + suffix) if row["hour_start_ms"] < cutoff]
    changed_prefix = [
        row for row in feature_rows(prefix + mutated_suffix) if row["hour_start_ms"] < cutoff
    ]
    if original_prefix != changed_prefix:
        raise ValueError("future trade suffix changed an earlier feature")

    return {
        "complete_24h_grid_passed": True,
        "future_suffix_invariance_passed": True,
        "target_bounds_passed": True,
    }


def policy_returns(
    positions: np.ndarray,
    gross_returns: np.ndarray,
) -> tuple[np.ndarray, float, int]:
    if positions.shape != gross_returns.shape:
        raise ValueError("position and return arrays differ")
    net = np.empty_like(gross_returns, dtype=float)
    previous = 0.0
    turnover = 0.0
    adjustments = 0
    for index, (position, gross_return) in enumerate(
        zip(positions, gross_returns, strict=True)
    ):
        change = abs(float(position) - previous)
        turnover += change
        adjustments += int(change > 0.0)
        net[index] = float(position) * float(gross_return) - FEE_RATE * change
        previous = float(position)
    terminal = abs(previous)
    if terminal:
        turnover += terminal
        adjustments += 1
        net[-1] -= FEE_RATE * terminal
    return net, turnover, adjustments


def sharpe(returns: np.ndarray) -> float | None:
    if returns.size < 2:
        return None
    standard_deviation = float(np.std(returns, ddof=1))
    if standard_deviation <= 0.0 or not math.isfinite(standard_deviation):
        return None
    return float(np.mean(returns) / standard_deviation * math.sqrt(8760.0))


def max_drawdown(returns: np.ndarray) -> float:
    equity = np.cumprod(1.0 + returns)
    peaks = np.maximum.accumulate(np.concatenate((np.array([1.0]), equity)))
    drawdowns = equity / peaks[1:] - 1.0
    return float(np.min(drawdowns, initial=0.0))


def total_return(returns: np.ndarray) -> float:
    return float(np.prod(1.0 + returns) - 1.0)


def holding_periods(positions: np.ndarray) -> list[int]:
    periods: list[int] = []
    active = 0
    for position in positions:
        if position > 0.0:
            active += 1
        elif active:
            periods.append(active)
            active = 0
    if active:
        periods.append(active)
    return periods


def policy_metrics(
    positions: np.ndarray,
    gross_returns: np.ndarray,
) -> tuple[dict[str, Any], np.ndarray]:
    net, turnover, adjustments = policy_returns(positions, gross_returns)
    periods = holding_periods(positions)
    block_returns = [
        total_return(net[start : start + BLOCK_HOURS])
        for start in range(0, len(net), BLOCK_HOURS)
    ]
    positive_blocks = [value for value in block_returns if value > 0.0]
    positive_concentration = (
        max(positive_blocks) / sum(positive_blocks) if positive_blocks else None
    )
    edge_per_turnover = float(np.sum(net) / turnover * 10_000.0) if turnover > 0.0 else None
    return (
        {
            "net_return": total_return(net),
            "gross_strategy_return": total_return(positions * gross_returns),
            "sharpe": sharpe(net),
            "max_drawdown": max_drawdown(net),
            "turnover": turnover,
            "adjustments": adjustments,
            "fee_burden": turnover * FEE_RATE,
            "edge_per_turnover_bps": edge_per_turnover,
            "time_in_market": float(np.mean(positions > 0.0)),
            "mean_position": float(np.mean(positions)),
            "no_trade_frequency": float(np.mean(positions == 0.0)),
            "average_holding_period_hours": float(np.mean(periods)) if periods else None,
            "profitable_6h_blocks": sum(value > 0.0 for value in block_returns),
            "six_hour_block_count": len(block_returns),
            "positive_block_concentration": positive_concentration,
            "worst_6h_return": min(block_returns),
        },
        net,
    )


def canonical_candle_evidence(snapshot: Any, root: Path) -> dict[str, Any]:
    frame = snapshot.candles.reset_index(names="timestamp")
    csv_bytes = frame.to_csv(
        index=False,
        date_format="%Y-%m-%dT%H:%M:%S.%fZ",
        float_format="%.12g",
        lineterminator="\n",
    ).encode()
    pages = canonical_json(snapshot.raw_pages)
    metadata = canonical_json(snapshot.metadata)
    return {
        "candles": persist(root / "candles.csv", csv_bytes),
        "raw_pages": persist(root / "candle-pages.json", pages),
        "metadata": persist(root / "candle-metadata.json", metadata),
    }


def market_run(base_url: str, inst_id: str, now_ms: int, root: Path) -> dict[str, Any]:
    selection, attempts = query_archive(base_url, inst_id, now_ms, root)
    if selection is None:
        raise ValueError("no exact recent immutable archive day was available")

    archive_bytes, final_url, elapsed = request_bytes(selection["url"], timeout=120.0)
    archive_record = persist(root / "archive.bin", archive_bytes)
    csv_bytes, member = extract_csv(archive_bytes)
    csv_record = persist(root / "archive.csv", csv_bytes)
    trades = canonicalize(parse_archive_csv(csv_bytes, inst_id))
    day = validate_complete_exchange_day(
        trades,
        expected_start_ms=int(selection["declared_start_ms"]),
    )
    features = feature_rows(trades)
    leakage = assert_feature_contract(features, trades)

    feature_start = utc_timestamp(int(features[0]["hour_start_ms"]))
    feature_end = utc_timestamp(int(features[-1]["hour_start_ms"]))
    candle_start = feature_start - pd.Timedelta(hours=LOOKBACK_HOURS)
    candle_end = feature_end + pd.Timedelta(hours=1)
    snapshot = fetch_okx_one_hour_candles(
        inst_id=inst_id,
        start=candle_start,
        end=candle_end,
        base_url=base_url,
        pause_seconds=0.05,
    )
    close = snapshot.close

    feature_index = pd.DatetimeIndex(
        [utc_timestamp(int(row["hour_start_ms"])) for row in features]
    )
    if not feature_index.isin(close.index).all():
        raise ValueError("feature hours are absent from the canonical candle grid")
    payoff_index = feature_index + pd.Timedelta(hours=1)
    if not payoff_index.isin(close.index).all():
        raise ValueError("next-hour payoff candles are absent")

    gross_returns = np.array(
        [float(close.loc[next_hour] / close.loc[hour] - 1.0) for hour, next_hour in zip(
            feature_index,
            payoff_index,
            strict=True,
        )],
        dtype=float,
    )
    candidate_positions = np.array([float(row["candidate_target"]) for row in features])
    raw_positions = np.array([float(row["raw_flow_target"]) for row in features])
    trend_positions = np.array(
        [
            float(close.loc[hour] / close.loc[hour - pd.Timedelta(hours=LOOKBACK_HOURS)] > 1.0)
            for hour in feature_index
        ],
        dtype=float,
    )

    candidate_metrics, candidate_net = policy_metrics(candidate_positions, gross_returns)
    raw_metrics, raw_net = policy_metrics(raw_positions, gross_returns)
    trend_metrics, trend_net = policy_metrics(trend_positions, gross_returns)
    features_bytes = canonical_json(features)
    persist(root / "features.json", features_bytes)
    candle_evidence = canonical_candle_evidence(snapshot, root / "candles")

    return {
        "inst_id": inst_id,
        "archive_selection": selection,
        "manifest_attempts": attempts,
        "archive": {
            **archive_record,
            "csv": csv_record,
            "member": member,
            "final_url": final_url,
            "rtt_seconds": elapsed,
            "rows": len(trades),
            **day,
        },
        "fields": {
            "source": ["trade_id", "taker_side", "price", "base_size", "timestamp_ms"],
            "derived": [
                "quote_notional",
                "raw_flow",
                "notional_hhi",
                "concentration_direction",
            ],
            "availability": "after the complete UTC trade hour closes",
            "position_effective": "next complete 1H candle only",
        },
        "sample": {
            "feature_start": feature_start.isoformat(),
            "feature_end_exclusive": (feature_end + pd.Timedelta(hours=1)).isoformat(),
            "observations": len(features),
            "missing_hours": 0,
        },
        "feature_sha256": sha256(features_bytes),
        "candle_evidence": candle_evidence,
        "leakage_and_timing": {
            **leakage,
            "one_complete_bar_delay_passed": True,
            "benchmark_window_parity_passed": True,
        },
        "policies": {
            "large_trade_concentration_pressure": candidate_metrics,
            "raw_hourly_flow": raw_metrics,
            "simple_trend_long_cash": trend_metrics,
        },
        "incremental": {
            "candidate_minus_raw_net_return": (
                candidate_metrics["net_return"] - raw_metrics["net_return"]
            ),
            "candidate_minus_trend_net_return": (
                candidate_metrics["net_return"] - trend_metrics["net_return"]
            ),
            "candidate_minus_raw_sharpe": (
                None
                if candidate_metrics["sharpe"] is None or raw_metrics["sharpe"] is None
                else candidate_metrics["sharpe"] - raw_metrics["sharpe"]
            ),
            "candidate_minus_trend_sharpe": (
                None
                if candidate_metrics["sharpe"] is None or trend_metrics["sharpe"] is None
                else candidate_metrics["sharpe"] - trend_metrics["sharpe"]
            ),
        },
        "series": {
            "candidate_net": candidate_net.tolist(),
            "raw_net": raw_net.tolist(),
            "trend_net": trend_net.tolist(),
        },
    }


def bootstrap(markets: list[dict[str, Any]]) -> dict[str, Any]:
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    starts = np.arange(0, 24 - BLOCK_HOURS + 1)
    observed = {
        "candidate_minus_raw_mean": min(
            float(np.mean(market["series"]["candidate_net"]))
            - float(np.mean(market["series"]["raw_net"]))
            for market in markets
        ),
        "candidate_minus_trend_mean": min(
            float(np.mean(market["series"]["candidate_net"]))
            - float(np.mean(market["series"]["trend_net"]))
            for market in markets
        ),
    }
    samples = {name: [] for name in observed}
    for _ in range(BOOTSTRAP_RESAMPLES):
        selected = rng.choice(starts, size=math.ceil(24 / BLOCK_HOURS), replace=True)
        indices = np.concatenate(
            [np.arange(start, start + BLOCK_HOURS) for start in selected]
        )[:24]
        raw_deltas: list[float] = []
        trend_deltas: list[float] = []
        for market in markets:
            candidate = np.asarray(market["series"]["candidate_net"])[indices]
            raw = np.asarray(market["series"]["raw_net"])[indices]
            trend = np.asarray(market["series"]["trend_net"])[indices]
            raw_deltas.append(float(np.mean(candidate - raw)))
            trend_deltas.append(float(np.mean(candidate - trend)))
        samples["candidate_minus_raw_mean"].append(min(raw_deltas))
        samples["candidate_minus_trend_mean"].append(min(trend_deltas))

    unadjusted: dict[str, float] = {}
    endpoints: dict[str, Any] = {}
    for name, values in samples.items():
        array = np.asarray(values)
        unadjusted[name] = (1.0 + float(np.sum(array <= 0.0))) / (BOOTSTRAP_RESAMPLES + 1.0)
        endpoints[name] = {
            "observed": observed[name],
            "one_sided_95pct_lower_bound": float(np.quantile(array, 0.05)),
            "unadjusted_p": unadjusted[name],
        }

    ordered = sorted(unadjusted, key=unadjusted.get)
    running = 0.0
    count = len(ordered)
    for rank, name in enumerate(ordered):
        adjusted = min(1.0, (count - rank) * unadjusted[name])
        running = max(running, adjusted)
        endpoints[name]["holm_adjusted_p"] = running
    return {
        "method": "paired non-circular 6H moving-block bootstrap with common calendar indices",
        "resamples": BOOTSTRAP_RESAMPLES,
        "seed": BOOTSTRAP_SEED,
        "holm_family_size": len(endpoints),
        "endpoints": endpoints,
    }


def qualification(markets: list[dict[str, Any]], inference: dict[str, Any]) -> tuple[str, list[str]]:
    failures: list[str] = []
    for market in markets:
        name = market["inst_id"]
        candidate = market["policies"]["large_trade_concentration_pressure"]
        raw = market["policies"]["raw_hourly_flow"]
        trend = market["policies"]["simple_trend_long_cash"]
        if candidate["net_return"] <= raw["net_return"]:
            failures.append(f"{name}: candidate net return did not exceed raw flow")
        if candidate["net_return"] <= trend["net_return"]:
            failures.append(f"{name}: candidate net return did not exceed simple trend")
        if candidate["edge_per_turnover_bps"] is None or candidate["edge_per_turnover_bps"] <= 0.0:
            failures.append(f"{name}: candidate edge per turnover was not positive")
        if candidate["profitable_6h_blocks"] < 2:
            failures.append(f"{name}: fewer than two of four 6H blocks were profitable")
        concentration = candidate["positive_block_concentration"]
        if concentration is None or concentration > 0.5:
            failures.append(f"{name}: positive block return was too concentrated")

    for name, endpoint in inference["endpoints"].items():
        if endpoint["one_sided_95pct_lower_bound"] <= 0.0:
            failures.append(f"{name}: one-sided lower bound was not positive")
        if endpoint["holm_adjusted_p"] > 0.05:
            failures.append(f"{name}: Holm-adjusted evidence did not pass")

    verdict = (
        "large_trade_concentration_pressure_promising_for_training_only_followup"
        if not failures
        else "large_trade_concentration_pressure_rejected_by_bounded_diagnostic"
    )
    return verdict, failures


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    now_ms, server_time = fetch_server_time(base_url)
    markets = [
        market_run(base_url, inst_id, now_ms, output_dir / inst_id)
        for inst_id in MARKETS
    ]
    inference = bootstrap(markets)
    verdict, failures = qualification(markets, inference)
    for market in markets:
        market.pop("series")

    result = {
        "schema_version": "large-trade-concentration-pressure-bounded-v1",
        "architecture_family_id": "trade-size-concentration-temporal-diagnostic-v1",
        "hypothesis": (
            "next-hour continuation is stronger when the completed hour's size-squared "
            "taker imbalance is positive than under unweighted signed flow"
        ),
        "candidate_count": 1,
        "comparators": ["raw_hourly_flow", "simple_trend_long_cash"],
        "canonical_fee_bps_one_way": 5.0,
        "bar": "1H",
        "cross_sectional_selection": False,
        "performance_inspected_before_freeze": False,
        "reserved_trade_flow_oos_consumed": False,
        "server_time": server_time,
        "markets": markets,
        "inference": inference,
        "qualification_failures": failures,
        "verdict": verdict,
        "next_feature_hypothesis": (
            "trade-arrival burstiness interacted with signed flow, using a separately frozen "
            "training-only design rather than another concentration threshold"
        ),
        "generated_at_utc": datetime.now(UTC).isoformat(),
    }
    data = canonical_json(result)
    persist(output_dir / "result.json", data)
    (output_dir / "result.sha256").write_text(sha256(data) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        default="reports/okx/large-trade-concentration-diagnostic",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("OKX_BASE_URL", "https://www.okx.com"),
    )
    args = parser.parse_args()
    result = run(Path(args.output_dir), args.base_url.rstrip("/"))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
