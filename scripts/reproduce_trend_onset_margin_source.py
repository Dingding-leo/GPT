from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

FEE = 5e-4
ANN = 8760.0
TREND = 2160
LEG = 24
N = 43441
FOLD = 2160
TRAIN = (2880, 17520)
OOS = (17520, 43440)
FULL = (2880, 43440)
BLOCK = 168
RESAMPLES = 5000
SEED = 20260730
HASHES = {
    "BTC-USDT": "92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9",
    "ETH-USDT": "2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726",
}
FAMILY_ID = "trend-onset-margin-source-attribution-selector-1h-v1"
REJECT_VERDICT = "reject_exact_trend_onset_margin_source_attribution_selector_family"
ACCEPT_VERDICT = "nominate_exact_trend_onset_margin_source_attribution_selector_for_replication"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load(path: Path, market: str) -> pd.DataFrame:
    observed = sha256_file(path)
    if observed != HASHES[market]:
        raise ValueError(f"{market} SHA mismatch: {observed}")
    d = pd.read_csv(path, nrows=N)
    if len(d) != N:
        raise ValueError(f"{market} row count {len(d)} != {N}")
    t = pd.DatetimeIndex(pd.to_datetime(d["timestamp"], utc=True))
    expected = pd.date_range(t[0], periods=N, freq="1h", tz="UTC")
    numeric = d[["open", "high", "low", "close", "volume_quote"]].to_numpy(float)
    valid = (
        t.equals(expected)
        and t.is_unique
        and (d["confirm"] == 1).all()
        and np.isfinite(numeric).all()
        and (numeric[:, :4] > 0).all()
        and (numeric[:, 4] >= 0).all()
        and (d["high"] >= d[["open", "close"]].max(axis=1)).all()
        and (d["low"] <= d[["open", "close"]].min(axis=1)).all()
    )
    if not valid:
        raise ValueError(f"{market} source validation failed")
    d.index = t
    return d


def build_positions(d: pd.DataFrame) -> tuple[dict[str, np.ndarray], list[dict[str, Any]]]:
    n = len(d)
    close = d["close"].to_numpy(float)
    p = {"candidate": np.zeros(n - 1), "b1": np.zeros(n - 1), "b0": np.zeros(n - 1)}
    events: list[dict[str, Any]] = []
    candidate_state = 0.0
    b1_state = 0.0
    previous_daily_base = 0.0
    regime_id = 0

    for t in range(TREND + LEG, n - 1):
        hourly_base = float(close[t] > close[t - TREND])
        if t + 1 < n - 1:
            p["b0"][t + 1] = hourly_base

        if d.index[t].hour == 0:
            base = hourly_base
            before = candidate_state
            action = "carry"
            current_margin = float(math.log(close[t] / close[t - TREND]))
            previous_margin = float(math.log(close[t - LEG] / close[t - TREND - LEG]))

            if base <= 0.0:
                candidate_state = 0.0
                b1_state = 0.0
                action = "base_exit" if before > 0.0 else "remain_cash"
            elif previous_daily_base <= 0.0:
                regime_id += 1
                current_leg = float(math.log(close[t] / close[t - LEG]))
                lag_leg = float(math.log(close[t - TREND] / close[t - TREND - LEG]))
                stale_release = float(max(0.0, -lag_leg))
                accepted = bool(current_leg > stale_release)
                candidate_state = 1.0 if accepted else 0.0
                b1_state = 1.0
                action = "fresh_dominant_entry" if accepted else "stale_release_skip"
                events.append(
                    {
                        "decision_index": t,
                        "execution_index": t + 1,
                        "timestamp": d.index[t].isoformat(),
                        "regime_id": regime_id,
                        "current_leg": current_leg,
                        "lag_leg": lag_leg,
                        "stale_release": stale_release,
                        "current_margin": current_margin,
                        "previous_margin": previous_margin,
                        "accepted": accepted,
                        "action": action,
                    }
                )
            else:
                b1_state = 1.0
                action = "remain_long" if candidate_state > 0.0 else "remain_skipped"

            previous_daily_base = base

        if t + 1 < n - 1:
            p["candidate"][t + 1] = candidate_state
            p["b1"][t + 1] = b1_state

    if not np.isin(p["candidate"], [0.0, 1.0]).all():
        raise ValueError("candidate outside long/cash domain")
    if np.any(p["candidate"] > p["b1"] + 1e-15):
        raise ValueError("candidate exceeds B1")
    return p, events


def build_price_only_shadow(d: pd.DataFrame) -> np.ndarray:
    """Non-selectable diagnostic: accept an onset iff the latest 24H close leg is positive."""
    n = len(d)
    close = d["close"].to_numpy(float)
    position = np.zeros(n - 1)
    state = 0.0
    previous_daily_base = 0.0
    for t in range(TREND + LEG, n - 1):
        base = float(close[t] > close[t - TREND])
        if d.index[t].hour == 0:
            if base <= 0.0:
                state = 0.0
            elif previous_daily_base <= 0.0:
                current_leg = float(math.log(close[t] / close[t - LEG]))
                state = float(current_leg > 0.0)
            previous_daily_base = base
        if t + 1 < n - 1:
            position[t + 1] = state
    return position


def pack(d: pd.DataFrame, position: np.ndarray) -> dict[str, np.ndarray]:
    opens = d["open"].to_numpy(float)
    market = opens[1:] / opens[:-1] - 1.0
    turnover = np.r_[abs(position[0]), np.abs(np.diff(position))]
    fees = FEE * turnover
    gross = position * market
    net = gross - fees
    if not np.array_equal(net, position * market - FEE * turnover):
        raise ValueError("fee identity failed")
    return {"market": market, "turnover": turnover, "fees": fees, "gross": gross, "net": net}


def sharpe(x: np.ndarray) -> float | None:
    std = float(np.std(x, ddof=1))
    if std <= 0.0 or not np.isfinite(std):
        return None
    return float(math.sqrt(ANN) * np.mean(x) / std)


def metric(a: dict[str, np.ndarray], position: np.ndarray, span: tuple[int, int]) -> dict[str, float | None]:
    start, end = span
    net = a["net"][start:end]
    gross = a["gross"][start:end]
    wealth = np.cumprod(1.0 + net)
    gross_wealth = np.cumprod(1.0 + gross)
    path = np.r_[1.0, wealth]
    turnover = float(a["turnover"][start:end].sum())
    return {
        "gross_return": float(gross_wealth[-1] - 1.0),
        "net_return": float(wealth[-1] - 1.0),
        "sharpe": sharpe(net),
        "max_drawdown": float(np.min(path / np.maximum.accumulate(path) - 1.0)),
        "turnover": turnover,
        "fees": float(a["fees"][start:end].sum()),
        "edge_per_turnover_bps": float(net.sum() / turnover * 1e4) if turnover > 0 else None,
        "mean_exposure": float(np.mean(position[start:end])),
        "exposed_hours": int(np.sum(position[start:end] > 0.0)),
    }


def breadth(net: np.ndarray, timestamps: pd.DatetimeIndex) -> dict[str, Any]:
    fold_returns = [
        float(np.prod(1.0 + net[OOS[0] + k * FOLD : OOS[0] + (k + 1) * FOLD]) - 1.0)
        for k in range(12)
    ]
    positive = [value for value in fold_returns if value > 0.0]
    concentration = float(max(positive) / sum(positive)) if positive else None
    years = timestamps[:-1].year
    oos_years = years[OOS[0] : OOS[1]]
    oos_net = net[OOS[0] : OOS[1]]
    year_returns: dict[str, float] = {}
    for year in sorted(set(oos_years)):
        mask = oos_years == year
        year_returns[str(int(year))] = float(np.prod(1.0 + oos_net[mask]) - 1.0)
    return {
        "fold_returns": fold_returns,
        "profitable_folds": int(sum(value > 0.0 for value in fold_returns)),
        "positive_fold_concentration": concentration,
        "year_returns": year_returns,
        "profitable_years": int(sum(value > 0.0 for value in year_returns.values())),
    }


def bootstrap(candidate: np.ndarray, benchmark: np.ndarray) -> dict[str, Any]:
    candidate = candidate[OOS[0] : OOS[1]]
    benchmark = benchmark[OOS[0] : OOS[1]]
    n = len(candidate)
    rng = np.random.default_rng(SEED)
    mean_delta = np.empty(RESAMPLES)
    sharpe_delta = np.empty(RESAMPLES)
    offsets = np.arange(BLOCK)
    n_blocks = math.ceil(n / BLOCK)
    chunk = 100
    for start in range(0, RESAMPLES, chunk):
        size = min(chunk, RESAMPLES - start)
        idx = (
            rng.integers(0, n - BLOCK + 1, size=(size, n_blocks))[:, :, None] + offsets
        ).reshape(size, -1)[:, :n]
        c = candidate[idx]
        b = benchmark[idx]
        cmean = c.mean(axis=1)
        bmean = b.mean(axis=1)
        cstd = c.std(axis=1, ddof=1)
        bstd = b.std(axis=1, ddof=1)
        mean_delta[start : start + size] = ANN * (cmean - bmean)
        sharpe_delta[start : start + size] = np.divide(
            math.sqrt(ANN) * cmean, cstd, out=np.zeros(size), where=cstd > 0
        ) - np.divide(math.sqrt(ANN) * bmean, bstd, out=np.zeros(size), where=bstd > 0)
    return {
        "annualized_mean_delta": {
            "point": float(ANN * np.mean(candidate - benchmark)),
            "lower_95": float(np.quantile(mean_delta, 0.025)),
            "upper_95": float(np.quantile(mean_delta, 0.975)),
        },
        "sharpe_delta": {
            "point": float((sharpe(candidate) or 0.0) - (sharpe(benchmark) or 0.0)),
            "lower_95": float(np.quantile(sharpe_delta, 0.025)),
            "upper_95": float(np.quantile(sharpe_delta, 0.975)),
        },
    }


def future_compound(market: np.ndarray, start: int, hours: int) -> float:
    end = min(start + hours, len(market))
    return float(np.prod(1.0 + market[start:end]) - 1.0)


def diagnostics(
    d: pd.DataFrame,
    positions: dict[str, np.ndarray],
    arrays: dict[str, dict[str, np.ndarray]],
    events: list[dict[str, Any]],
    span: tuple[int, int],
) -> dict[str, Any]:
    start, end = span
    candidate = positions["candidate"]
    benchmark = positions["b1"]
    market = arrays["candidate"]["market"]
    selected = [event for event in events if start <= event["execution_index"] < end]
    rows: list[dict[str, Any]] = []
    for event in selected:
        execution = int(event["execution_index"])
        regime_end = execution
        while regime_end < end and benchmark[regime_end] > 0.0:
            regime_end += 1
        row = dict(event)
        row.update(
            {
                "regime_hours_within_span": int(regime_end - execution),
                "regime_market_return_arithmetic": float(market[execution:regime_end].sum()),
                "regime_market_return_compounded": float(np.prod(1.0 + market[execution:regime_end]) - 1.0),
                "next_24h_return": future_compound(market, execution, 24),
                "next_168h_return": future_compound(market, execution, 168),
                "next_720h_return": future_compound(market, execution, 720),
            }
        )
        rows.append(row)

    position_delta = candidate[start:end] - benchmark[start:end]
    exposure_timing = float(np.sum(position_delta * market[start:end]))
    fee_delta = float(arrays["candidate"]["fees"][start:end].sum() - arrays["b1"]["fees"][start:end].sum())
    observed = float(np.sum(arrays["candidate"]["net"][start:end] - arrays["b1"]["net"][start:end]))
    if not math.isclose(observed, exposure_timing - fee_delta, abs_tol=1e-12):
        raise ValueError("return decomposition failed")

    skipped = [row for row in rows if not row["accepted"]]
    accepted = [row for row in rows if row["accepted"]]
    omitted_mask = benchmark[start:end] > candidate[start:end]
    omitted_hours = int(np.sum(omitted_mask))
    omitted_carry = float(np.sum((benchmark[start:end] - candidate[start:end]) * market[start:end]))

    def averages(rows_in: list[dict[str, Any]]) -> dict[str, float | None]:
        if not rows_in:
            return {"next_24h": None, "next_168h": None, "next_720h": None}
        return {
            "next_24h": float(np.mean([row["next_24h_return"] for row in rows_in])),
            "next_168h": float(np.mean([row["next_168h_return"] for row in rows_in])),
            "next_720h": float(np.mean([row["next_720h_return"] for row in rows_in])),
        }

    attributed_skipped_hours = int(sum(row["regime_hours_within_span"] for row in skipped))
    inherited_b1_only_hours = omitted_hours - attributed_skipped_hours
    if inherited_b1_only_hours < 0:
        raise ValueError("event attribution exceeds B1-only exposure")

    return {
        "onsets": len(rows),
        "accepted_onsets": len(accepted),
        "skipped_onsets": len(skipped),
        "event_rows": rows,
        "accepted_future_mean": averages(accepted),
        "skipped_future_mean": averages(skipped),
        "b1_only_hours": omitted_hours,
        "event_attributed_skipped_hours": attributed_skipped_hours,
        "inherited_b1_only_hours": inherited_b1_only_hours,
        "inherited_b1_only_at_span_start": bool(benchmark[start] > candidate[start]),
        "omitted_market_carry": omitted_carry,
        "incremental_fees": fee_delta,
        "exposure_timing_contribution": exposure_timing,
        "arithmetic_net_delta": observed,
    }


def run_market(d: pd.DataFrame) -> dict[str, Any]:
    positions, events = build_positions(d)
    shadow_position = build_price_only_shadow(d)
    positions["price_only_shadow"] = shadow_position
    arrays = {name: pack(d, position) for name, position in positions.items()}
    metrics = {
        name: {
            "training": metric(arrays[name], positions[name], TRAIN),
            "development_oos": metric(arrays[name], positions[name], OOS),
            "full_scored": metric(arrays[name], positions[name], FULL),
        }
        for name in positions
    }
    candidate_breadth = breadth(arrays["candidate"]["net"], d.index)
    benchmark_breadth = breadth(arrays["b1"]["net"], d.index)
    candidate_folds = candidate_breadth["fold_returns"]
    benchmark_folds = benchmark_breadth["fold_returns"]
    improved_folds = int(sum(c > b + 1e-15 for c, b in zip(candidate_folds, benchmark_folds)))
    residual = arrays["candidate"]["net"][OOS[0] : OOS[1]] - arrays["b1"]["net"][OOS[0] : OOS[1]]
    residual_sharpe = sharpe(residual)
    uncertainty = bootstrap(arrays["candidate"]["net"], arrays["b1"]["net"])
    diag = {
        "training": diagnostics(d, positions, arrays, events, TRAIN),
        "development_oos": diagnostics(d, positions, arrays, events, OOS),
        "full_scored": diagnostics(d, positions, arrays, events, FULL),
    }

    shadow_delta_hours = int(np.sum(positions["candidate"][OOS[0]:OOS[1]] != shadow_position[OOS[0]:OOS[1]]))
    shadow_arithmetic_delta = float(np.sum(arrays["candidate"]["net"][OOS[0]:OOS[1]] - arrays["price_only_shadow"]["net"][OOS[0]:OOS[1]]))
    shadow_diagnostic = {
        "description": "non-selectable current_leg_gt_0 onset shadow",
        "metrics": metrics["price_only_shadow"],
        "oos_position_difference_hours_vs_candidate": shadow_delta_hours,
        "candidate_minus_shadow_arithmetic_net": shadow_arithmetic_delta,
        "position_identical_oos": bool(shadow_delta_hours == 0),
    }

    c = metrics["candidate"]["development_oos"]
    b = metrics["b1"]["development_oos"]
    gates = {
        "candidate_oos_positive": bool(c["net_return"] is not None and c["net_return"] > 0.0),
        "oos_net_not_below_b1": bool(c["net_return"] >= b["net_return"]),
        "oos_sharpe_not_below_b1": bool(c["sharpe"] is not None and b["sharpe"] is not None and c["sharpe"] >= b["sharpe"]),
        "oos_drawdown_not_worse_b1": bool(c["max_drawdown"] >= b["max_drawdown"]),
        "oos_turnover_not_above_b1": bool(c["turnover"] <= b["turnover"]),
        "oos_edge_per_turn_not_below_b1": bool(c["edge_per_turnover_bps"] >= b["edge_per_turnover_bps"]),
        "profitable_folds_at_least_7": candidate_breadth["profitable_folds"] >= 7,
        "profitable_years_at_least_3": candidate_breadth["profitable_years"] >= 3,
        "positive_fold_concentration_not_above_50pct": bool(candidate_breadth["positive_fold_concentration"] is not None and candidate_breadth["positive_fold_concentration"] <= 0.5),
        "residual_sharpe_positive": bool(residual_sharpe is not None and residual_sharpe > 0.0),
        "mean_delta_lower_95_positive": uncertainty["annualized_mean_delta"]["lower_95"] > 0.0,
        "sharpe_delta_lower_95_positive": uncertainty["sharpe_delta"]["lower_95"] > 0.0,
        "identity_checks": True,
    }
    return {
        "metrics": metrics,
        "breadth": {"candidate": candidate_breadth, "b1": benchmark_breadth, "improved_folds_vs_b1": improved_folds, "residual_sharpe_vs_b1": residual_sharpe},
        "bootstrap": uncertainty,
        "diagnostics": diag,
        "nonselectable_price_only_shadow": shadow_diagnostic,
        "acceptance_gates": gates,
        "accepted": all(gates.values()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--btc", type=Path, required=True)
    parser.add_argument("--eth", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result: dict[str, Any] = {
        "family_id": FAMILY_ID,
        "issue": 702,
        "research_parent": "5a0fcc97d1a882f8223656c51f5bb8055f534e38",
        "candidate_count": 1,
        "parameter_grid_count": 0,
        "fee_one_way": FEE,
        "execution": "completed daily 00:00 UTC decision to next hourly open",
        "source": {"provider": "OKX SPOT public confirmed 1H", "rows_in_source": 43941, "scored_prefix_rows": N, "hashes": HASHES},
        "sample": {"training": TRAIN, "development_oos": OOS, "full_scored": FULL},
        "markets": {},
    }
    for market, path in (("BTC-USDT", args.btc), ("ETH-USDT", args.eth)):
        result["markets"][market] = run_market(load(path, market))
    result["accepted"] = all(market["accepted"] for market in result["markets"].values())
    result["verdict"] = ACCEPT_VERDICT if result["accepted"] else REJECT_VERDICT
    text = json.dumps(result, sort_keys=True, indent=2) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text)
    print(result["verdict"])


if __name__ == "__main__":
    main()
