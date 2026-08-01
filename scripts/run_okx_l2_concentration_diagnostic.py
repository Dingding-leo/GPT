from __future__ import annotations

import argparse
import json
import math
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import run_okx_l2_bid_replenishment_diagnostic as core

FAMILY_ID = "okx-l2-persistent-near-touch-concentration-asymmetry-1h-v1"
MARKETS = ("BTC-USDT", "ETH-USDT")
ANCHOR_DATES = (
    "2024-01-03", "2024-01-17", "2024-02-07", "2024-02-21",
    "2024-03-06", "2024-03-20", "2024-04-03", "2024-04-17",
    "2024-05-01", "2024-05-15", "2024-06-05", "2024-06-19",
    "2024-07-03", "2024-07-17", "2024-08-07", "2024-08-21",
    "2024-09-04", "2024-09-18", "2024-10-02", "2024-10-16",
    "2024-11-06", "2024-11-20", "2024-12-04", "2024-12-18",
)
FEE_ONE_WAY = 0.0005
ROUND_TRIP_LABEL_FEE = 0.001
NEAR_BAND = 0.0005
OUTER_BAND = 0.002
LABEL_HOURS = 6
BOOTSTRAP_DRAWS = 5_000
BOOTSTRAP_SEED = 20_260_802
_ORIGINAL_FETCH = core.fetch_okx_one_hour_candles


def boundary_state(bids: dict[float, float], asks: dict[float, float]) -> dict[str, Any] | None:
    if len(bids) < 10 or len(asks) < 10:
        return None
    best_bid, best_ask = max(bids), min(asks)
    if not best_bid < best_ask:
        raise core.SourceFeasibilityError("crossed or locked reconstructed book")
    mid = (best_bid + best_ask) / 2.0
    bid20 = [(p, s) for p, s in bids.items() if p >= mid * (1.0 - OUTER_BAND)]
    ask20 = [(p, s) for p, s in asks.items() if p <= mid * (1.0 + OUTER_BAND)]
    if len(bid20) < 10 or len(ask20) < 10:
        return None
    bid5 = sum(p * s for p, s in bid20 if p >= mid * (1.0 - NEAR_BAND))
    ask5 = sum(p * s for p, s in ask20 if p <= mid * (1.0 + NEAR_BAND))
    bid20n, ask20n = sum(p * s for p, s in bid20), sum(p * s for p, s in ask20)
    if not all(math.isfinite(x) and x > 0 for x in (mid, bid5, ask5, bid20n, ask20n)):
        return None
    bid_conc, ask_conc = bid5 / bid20n, ask5 / ask20n
    shape = math.log(bid_conc / ask_conc)
    if not math.isfinite(shape):
        return None
    return {
        "mid": mid,
        "bid_depth_5bp": bid5,
        "bid_depth_20bp": bid20n,
        "ask_depth_5bp": ask5,
        "ask_depth_20bp": ask20n,
        "bid_concentration": bid_conc,
        "ask_concentration": ask_conc,
        "shape": shape,
        "bid_levels_20bp": len(bid20),
        "ask_levels_20bp": len(ask20),
    }


def hourly_states(boundaries: list[dict[str, Any] | None], *, market: str, anchor: str, day_start_ms: int) -> list[dict[str, Any]]:
    if len(boundaries) != 289:
        raise core.SourceFeasibilityError(f"expected 289 boundaries, got {len(boundaries)}")
    output: list[dict[str, Any]] = []
    for hour in range(24):
        window = boundaries[hour * 12 : hour * 12 + 13]
        record: dict[str, Any] = {
            "market": market,
            "anchor_date_utc": anchor,
            "hour_start_ms": day_start_ms + hour * core.HOUR_MS,
            "valid": False,
            "invalid_reason": None,
            "state": None,
        }
        if any(item is None for item in window):
            record["invalid_reason"] = "missing_causal_boundary_state"
        else:
            shapes = np.asarray([float(item["shape"]) for item in window if item is not None])
            record.update(
                valid=True,
                state=float(np.median(shapes)),
                shape_minimum=float(np.min(shapes)),
                shape_maximum=float(np.max(shapes)),
                shape_first=float(shapes[0]),
                shape_last=float(shapes[-1]),
                boundary_observations=len(shapes),
            )
        output.append(record)
    return output


def label_rows(states: Iterable[dict[str, Any]], candles: pd.DataFrame, *, delay_hours: int) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for record in states:
        if not record["valid"]:
            continue
        hour = pd.Timestamp(record["hour_start_ms"], unit="ms", tz="UTC")
        entry = hour + pd.Timedelta(hours=1 + delay_hours)
        exit_time = entry + pd.Timedelta(hours=LABEL_HOURS)
        path = candles.loc[entry : entry + pd.Timedelta(hours=LABEL_HOURS - 1)]
        if entry not in candles.index or exit_time not in candles.index or len(path) != LABEL_HOURS:
            raise core.SourceFeasibilityError("candle source does not cover frozen 6H label")
        entry_open, exit_open = float(candles.at[entry, "open"]), float(candles.at[exit_time, "open"])
        gross = math.log(exit_open / entry_open)
        output.append(
            {
                **record,
                "entry_open_utc": entry.isoformat(),
                "exit_open_utc": exit_time.isoformat(),
                "gross_6h": gross,
                "net_6h": gross - ROUND_TRIP_LABEL_FEE,
                "adverse_6h": float(np.min(np.log(path["low"].to_numpy(float) / entry_open))),
            }
        )
    return output


def metric_vector(frame: pd.DataFrame) -> dict[str, float]:
    state, net, adverse = (frame[name].to_numpy(float) for name in ("state", "net_6h", "adverse_6h"))
    return {
        "net_rho": core.spearman(state, net),
        "adverse_rho": core.spearman(state, adverse),
        "net_slope": core.standardized_slope(state, net),
        "adverse_slope": core.standardized_slope(state, adverse),
    }


def bucket_analysis(state: np.ndarray, target: np.ndarray) -> dict[str, Any]:
    order, bucket = np.argsort(state, kind="mergesort"), np.empty(len(state), dtype=int)
    for rank, position in enumerate(order):
        bucket[position] = min(4, rank * 5 // len(state))
    means = [float(np.mean(target[bucket == i])) for i in range(5)]
    return {
        "means": means,
        "favourable_adjacent_changes": sum(b > a for a, b in zip(means, means[1:], strict=False)),
        "bucket_index_correlation": core.correlation(np.arange(5, dtype=float), np.asarray(means)),
        "counts": [int((bucket == i).sum()) for i in range(5)],
    }


def analyze_market(frame: pd.DataFrame) -> dict[str, Any]:
    state, net, adverse = (frame[name].to_numpy(float) for name in ("state", "net_6h", "adverse_6h"))
    net_effect, high_count, low_count, median = core.high_minus_low(state, net)
    adverse_effect, _, _, _ = core.high_minus_low(state, adverse)
    metrics = metric_vector(frame)
    intervals = core.bootstrap_intervals(frame, list(ANCHOR_DATES))
    net_days, adverse_days = core.day_effects(frame, "net_6h"), core.day_effects(frame, "adverse_6h")
    return {
        "observations": len(frame),
        "complete_anchor_days": int(frame["anchor_date_utc"].nunique()),
        "state": {
            "minimum": float(np.min(state)), "maximum": float(np.max(state)),
            "median": median, "iqr": float(np.quantile(state, 0.75) - np.quantile(state, 0.25)),
            "p01": float(np.quantile(state, 0.01)), "p99": float(np.quantile(state, 0.99)),
            "high_count": high_count, "low_count": low_count,
        },
        "metrics": metrics,
        "confidence_intervals": intervals,
        "median_split": {"net_high_minus_low": net_effect, "adverse_high_minus_low": adverse_effect},
        "buckets": {"net": bucket_analysis(state, net), "adverse": bucket_analysis(state, adverse)},
        "anchor_day_effects": {"net": net_days, "adverse": adverse_days},
        "positive_anchor_days": {
            "net": sum(item["favourable"] for item in net_days),
            "adverse": sum(item["favourable"] for item in adverse_days),
        },
    }


def acceptance(result: dict[str, Any]) -> dict[str, bool]:
    state, metrics, intervals = result["state"], result["metrics"], result["confidence_intervals"]
    split, buckets, days = result["median_split"], result["buckets"], result["positive_anchor_days"]
    return {
        "support": result["observations"] >= 528 and result["complete_anchor_days"] >= 22,
        "state_support": state["iqr"] > 0 and state["high_count"] >= 240 and state["low_count"] >= 240,
        "positive_point_metrics": all(value > 0 for value in metrics.values()),
        "positive_lower_bounds": all(intervals[key][0] > 0 for key in metrics),
        "positive_median_split": split["net_high_minus_low"] > 0 and split["adverse_high_minus_low"] > 0,
        "anchor_day_breadth": days["net"] >= 15 and days["adverse"] >= 15,
        "ordered_buckets": all(
            buckets[target]["favourable_adjacent_changes"] >= 3
            and buckets[target]["bucket_index_correlation"] >= 0.80
            for target in ("net", "adverse")
        ),
    }


def common_index_frame(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    columns = ["anchor_date_utc", "hour_start_ms", "state", "net_6h", "adverse_6h"]
    left = frames[MARKETS[0]][columns].rename(columns={name: f"{name}_l" for name in columns[2:]})
    right = frames[MARKETS[1]][columns].rename(columns={name: f"{name}_r" for name in columns[2:]})
    merged = left.merge(right, on=columns[:2], validate="one_to_one")
    for side in ("l", "r"):
        values = merged[f"state_{side}"].to_numpy(float)
        merged[f"state_z_{side}"] = (values - np.mean(values)) / np.std(values)
    return pd.DataFrame(
        {
            "anchor_date_utc": merged["anchor_date_utc"],
            "hour_start_ms": merged["hour_start_ms"],
            "state": (merged["state_z_l"] + merged["state_z_r"]) / 2,
            "net_6h": (merged["net_6h_l"] + merged["net_6h_r"]) / 2,
            "adverse_6h": (merged["adverse_6h_l"] + merged["adverse_6h_r"]) / 2,
        }
    )


def fetch_2024_candles(**kwargs: Any):
    kwargs.update(start="2024-01-03T00:00:00Z", end="2024-12-20T00:00:00Z", safety_pages=512)
    return _ORIGINAL_FETCH(**kwargs)


def configure_core() -> None:
    core.FAMILY_ID, core.MARKETS, core.ANCHOR_DATES = FAMILY_ID, MARKETS, ANCHOR_DATES
    core.FEE_ONE_WAY, core.ROUND_TRIP_LABEL_FEE = FEE_ONE_WAY, ROUND_TRIP_LABEL_FEE
    core.BOOTSTRAP_DRAWS, core.BOOTSTRAP_SEED = BOOTSTRAP_DRAWS, BOOTSTRAP_SEED
    core.boundary_state, core.hourly_states = boundary_state, hourly_states
    core.label_rows, core.metric_vector = label_rows, metric_vector
    core.bucket_analysis, core.analyze_market = bucket_analysis, analyze_market
    core.acceptance, core.common_index_frame = acceptance, common_index_frame
    core.fetch_okx_one_hour_candles = fetch_2024_candles


def aggregate(manifest_path: Path, days_root: Path, output_dir: Path) -> dict[str, Any]:
    configure_core()
    result = core.aggregate(manifest_path, days_root, output_dir)
    accepted = all(result["gates"][market]["passed_all"] for market in MARKETS)
    result.update(
        label_horizon_hours=LABEL_HOURS,
        state_contract={
            "near_band_bps": 5, "outer_band_bps": 20, "boundaries_per_hour": 13,
            "aggregation": "median", "minimum_levels_per_side_in_outer_band": 10,
        },
        verdict=(
            "accept_okx_l2_persistent_near_touch_concentration_information_premise"
            if accepted else "reject_okx_l2_persistent_near_touch_concentration_information_premise"
        ),
    )
    result["bootstrap"]["seed"] = BOOTSTRAP_SEED
    result["bootstrap"]["unit"] = "paired complete 24H anchor-day blocks"
    result["performance"]["reason"] = "candidate count is zero; overlapping independent 6H labels are not an equity curve"
    (output_dir / "evidence.json").write_bytes(core.canonical_json(result))
    lines = [
        "# OKX L2 persistent near-touch concentration-asymmetry diagnostic", "", "```text",
        f"family              {FAMILY_ID}", "candidate count     0", "diagnostic count    1",
        "markets             BTC-USDT and ETH-USDT independently", "bar                 causal completed UTC 1H",
        "fee                 exactly 5 bps one way; 10 bps per independent 6H label",
        f"verdict             {result['verdict']}", "```", "",
    ]
    for market in MARKETS:
        primary, delayed = result["primary"][market], result["one_hour_delay"][market]
        lines += [
            f"## {market}",
            f"- Support: {primary['observations']}/576 observations; {primary['complete_anchor_days']}/24 days",
            f"- Net rho / CI: {primary['metrics']['net_rho']:.6f} / {primary['confidence_intervals']['net_rho']}",
            f"- Adverse rho / CI: {primary['metrics']['adverse_rho']:.6f} / {primary['confidence_intervals']['adverse_rho']}",
            f"- Net slope / CI: {primary['metrics']['net_slope']:.8f} / {primary['confidence_intervals']['net_slope']}",
            f"- Adverse slope / CI: {primary['metrics']['adverse_slope']:.8f} / {primary['confidence_intervals']['adverse_slope']}",
            f"- Median split net/adverse: {primary['median_split']['net_high_minus_low']:.8f} / {primary['median_split']['adverse_high_minus_low']:.8f}",
            f"- Positive days net/adverse: {primary['positive_anchor_days']['net']}/24 / {primary['positive_anchor_days']['adverse']}/24",
            f"- Delayed net/adverse rho: {delayed['metrics']['net_rho']:.6f} / {delayed['metrics']['adverse_rho']:.6f}",
            f"- Gates: {result['gates'][market]}", "",
        ]
    lines += [
        "## Executable performance", "",
        "Training/OOS/full return, Sharpe, benchmark comparison, maximum drawdown, executable turnover and edge per turnover were not computed because candidate count is zero.", "",
    ]
    (output_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return result


def main() -> None:
    configure_core()
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    metadata = sub.add_parser("metadata")
    metadata.add_argument("--base-url", default="https://www.okx.com")
    metadata.add_argument("--output-dir", type=Path, required=True)
    aggregate_parser = sub.add_parser("aggregate")
    aggregate_parser.add_argument("--manifest-path", type=Path, required=True)
    aggregate_parser.add_argument("--days-root", type=Path, required=True)
    aggregate_parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = (
        core.acquire_metadata(args.base_url, args.output_dir)
        if args.command == "metadata"
        else aggregate(args.manifest_path, args.days_root, args.output_dir)
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
