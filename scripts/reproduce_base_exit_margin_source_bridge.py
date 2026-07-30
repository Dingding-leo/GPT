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
BRIDGE_HOURS = 168
N = 43441
FOLD = 2160
BLOCK = 168
RESAMPLES = 5000
SEED = 20260730
TRAIN = (2880, 17520)
OOS = (17520, 43440)
FULL = (2880, 43440)
HASHES = {
    "BTC-USDT": "92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9",
    "ETH-USDT": "2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path, market: str) -> pd.DataFrame:
    actual = sha256(path)
    if actual != HASHES[market]:
        raise ValueError(f"{market} hash mismatch: {actual}")
    d = pd.read_csv(path, nrows=N)
    t = pd.DatetimeIndex(pd.to_datetime(d.timestamp, utc=True))
    num = d[["open", "high", "low", "close", "volume_quote"]].to_numpy(float)
    valid = (
        len(d) == N
        and t.equals(pd.date_range(t[0], periods=N, freq="1h", tz="UTC"))
        and t.is_unique
        and (d.confirm == 1).all()
        and np.isfinite(num).all()
        and (num[:, :4] > 0).all()
        and (num[:, 4] >= 0).all()
        and (d.high >= d[["open", "close"]].max(axis=1)).all()
        and (d.low <= d[["open", "close"]].min(axis=1)).all()
    )
    if not valid:
        raise ValueError(f"{market} source validation failed")
    d.index = t
    return d


def positions(d: pd.DataFrame) -> tuple[dict[str, np.ndarray], list[dict[str, Any]]]:
    close = d.close.to_numpy(float)
    p = {key: np.zeros(len(d) - 1) for key in ("candidate", "b1", "b0")}
    candidate_state = 0.0
    b1_state = 0.0
    prior_daily_base = 0.0
    bridge_active = False
    bridge_start_t: int | None = None
    bridge_expiry_t: int | None = None
    regime_id = 0
    events: list[dict[str, Any]] = []

    for t in range(TREND, len(d) - 2):
        base = float(close[t] > close[t - TREND])
        p["b0"][t + 1] = base

        if d.index[t].hour == 0:
            if t >= TREND + LEG:
                explicit_previous_base = float(close[t - LEG] > close[t - TREND - LEG])
                if explicit_previous_base != prior_daily_base:
                    raise ValueError("daily base state identity")
                pre_margin = float(math.log(close[t - LEG] / close[t - TREND - LEG]))
                current_leg = float(math.log(close[t] / close[t - LEG]))
                lag_leg = float(math.log(close[t - TREND] / close[t - TREND - LEG]))
            else:
                pre_margin = None
                current_leg = None
                lag_leg = None
            post_margin = float(math.log(close[t] / close[t - TREND]))
            if pre_margin is not None and current_leg is not None and lag_leg is not None:
                if not math.isclose(
                    post_margin - pre_margin, current_leg - lag_leg, abs_tol=1e-14
                ):
                    raise ValueError("endpoint margin decomposition")

            exit_crossing = bool((not base) and prior_daily_base)
            mechanical_exit = bool(
                exit_crossing
                and current_leg is not None
                and lag_leg is not None
                and current_leg >= 0.0
                and lag_leg > 0.0
            )
            event: dict[str, Any] = {
                "decision_t": t,
                "execution_t": t + 1,
                "timestamp": d.index[t].isoformat(),
                "before": candidate_state,
                "after": None,
                "base": base,
                "previous_base": prior_daily_base,
                "onset": False,
                "exit_crossing": exit_crossing,
                "mechanical_exit": mechanical_exit,
                "bridge_start": False,
                "bridge_restore": False,
                "bridge_expiry": False,
                "direct_exit": False,
                "regime_id": regime_id,
                "pre_margin": pre_margin,
                "post_margin": post_margin,
                "current_leg": current_leg,
                "lag_leg": lag_leg,
                "bridge_start_t": bridge_start_t,
                "bridge_expiry_t": bridge_expiry_t,
            }

            b1_state = base
            if bridge_active:
                if bridge_start_t is None or bridge_expiry_t is None:
                    raise ValueError("bridge timestamps missing")
                if base:
                    candidate_state = 1.0
                    bridge_active = False
                    bridge_start_t = None
                    bridge_expiry_t = None
                    regime_id += 1
                    event["bridge_restore"] = True
                    event["onset"] = True
                    event["regime_id"] = regime_id
                elif t >= bridge_expiry_t:
                    if t != bridge_expiry_t:
                        raise ValueError("bridge expiry skipped")
                    candidate_state = 0.0
                    bridge_active = False
                    event["bridge_expiry"] = True
                    bridge_start_t = None
                    bridge_expiry_t = None
                else:
                    candidate_state = 0.5
            elif base:
                candidate_state = 1.0
                if not prior_daily_base:
                    regime_id += 1
                    event["onset"] = True
                    event["regime_id"] = regime_id
            elif exit_crossing:
                if mechanical_exit:
                    candidate_state = 0.5
                    bridge_active = True
                    bridge_start_t = t
                    bridge_expiry_t = t + BRIDGE_HOURS
                    event["bridge_start"] = True
                    event["bridge_start_t"] = bridge_start_t
                    event["bridge_expiry_t"] = bridge_expiry_t
                else:
                    candidate_state = 0.0
                    event["direct_exit"] = True
            else:
                candidate_state = 0.0

            event["after"] = candidate_state
            event["bridge_start_t"] = bridge_start_t
            event["bridge_expiry_t"] = bridge_expiry_t
            events.append(event)
            prior_daily_base = base

        p["candidate"][t + 1] = candidate_state
        p["b1"][t + 1] = b1_state

    if not np.isin(p["candidate"], [0.0, 0.5, 1.0]).all():
        raise ValueError("candidate position domain")
    if np.any(p["candidate"] < p["b1"]):
        raise ValueError("candidate below B1")
    return p, events


def pack(d: pd.DataFrame, position: np.ndarray) -> dict[str, np.ndarray]:
    open_ = d.open.to_numpy(float)
    market = open_[1:] / open_[:-1] - 1.0
    turnover = np.r_[abs(position[0]), abs(np.diff(position))]
    fees = FEE * turnover
    gross = position * market
    net = gross - fees
    return {"market": market, "turnover": turnover, "fees": fees, "gross": gross, "net": net}


def sharpe(x: np.ndarray) -> float | None:
    sd = np.std(x, ddof=1)
    if not np.isfinite(sd) or sd <= 0:
        return None
    return float(math.sqrt(ANN) * np.mean(x) / sd)


def metrics(
    arrays: dict[str, np.ndarray], position: np.ndarray, span: tuple[int, int]
) -> dict[str, Any]:
    i, j = span
    net = arrays["net"][i:j]
    gross = arrays["gross"][i:j]
    wealth = np.cumprod(1.0 + net)
    gross_wealth = np.cumprod(1.0 + gross)
    path = np.r_[1.0, wealth]
    tv = float(arrays["turnover"][i:j].sum())
    return {
        "gross_return": float(gross_wealth[-1] - 1.0),
        "net_return": float(wealth[-1] - 1.0),
        "arithmetic_gross_return": float(gross.sum()),
        "arithmetic_net_return": float(net.sum()),
        "sharpe": sharpe(net),
        "max_drawdown": float(np.min(path / np.maximum.accumulate(path) - 1.0)),
        "turnover": tv,
        "fees": float(arrays["fees"][i:j].sum()),
        "edge_per_turnover_bps": float(net.sum() / tv * 1e4) if tv else None,
        "mean_exposure": float(position[i:j].mean()),
    }


def breadth(net: np.ndarray, index: pd.DatetimeIndex) -> dict[str, Any]:
    folds = [
        float(np.prod(1.0 + net[OOS[0] + k * FOLD : OOS[0] + (k + 1) * FOLD]) - 1.0)
        for k in range(12)
    ]
    positive = [x for x in folds if x > 0]
    years = index[:-1].year[OOS[0] : OOS[1]]
    oos_net = net[OOS[0] : OOS[1]]
    year_returns = {
        str(y): float(np.prod(1.0 + oos_net[years == y]) - 1.0) for y in sorted(set(years))
    }
    return {
        "fold_returns": folds,
        "profitable_folds": int(sum(x > 0 for x in folds)),
        "profitable_years": int(sum(x > 0 for x in year_returns.values())),
        "positive_fold_concentration": float(max(positive) / sum(positive)) if positive else None,
        "year_returns": year_returns,
    }


def bootstrap(candidate: np.ndarray, benchmark: np.ndarray) -> dict[str, Any]:
    c = candidate[OOS[0] : OOS[1]]
    b = benchmark[OOS[0] : OOS[1]]
    rng = np.random.default_rng(SEED)
    n = len(c)
    mean_delta = np.empty(RESAMPLES)
    sharpe_delta = np.empty(RESAMPLES)
    offsets = np.arange(BLOCK)
    n_blocks = math.ceil(n / BLOCK)
    for start in range(0, RESAMPLES, 100):
        q = min(100, RESAMPLES - start)
        block_starts = rng.integers(0, n - BLOCK + 1, (q, n_blocks))
        idx = (block_starts[:, :, None] + offsets).reshape(q, -1)[:, :n]
        cc = c[idx]
        bb = b[idx]
        cm = cc.mean(axis=1)
        bm = bb.mean(axis=1)
        cs = cc.std(axis=1, ddof=1)
        bs = bb.std(axis=1, ddof=1)
        mean_delta[start : start + q] = ANN * (cm - bm)
        csh = np.divide(math.sqrt(ANN) * cm, cs, out=np.zeros(q), where=cs > 0)
        bsh = np.divide(math.sqrt(ANN) * bm, bs, out=np.zeros(q), where=bs > 0)
        sharpe_delta[start : start + q] = csh - bsh
    return {
        "annualized_mean_delta": {
            "point": float(ANN * np.mean(c - b)),
            "lower_95": float(np.quantile(mean_delta, 0.025)),
            "upper_95": float(np.quantile(mean_delta, 0.975)),
        },
        "sharpe_delta": {
            "point": float((sharpe(c) or 0.0) - (sharpe(b) or 0.0)),
            "lower_95": float(np.quantile(sharpe_delta, 0.025)),
            "upper_95": float(np.quantile(sharpe_delta, 0.975)),
        },
    }


def forward_return(market: np.ndarray, start: int, horizon: int) -> dict[str, Any]:
    end = min(start + horizon, len(market))
    arr = market[start:end]
    return {
        "hours": int(len(arr)),
        "compounded": float(np.prod(1.0 + arr) - 1.0) if len(arr) else None,
        "arithmetic": float(arr.sum()) if len(arr) else None,
        "right_censored": bool(len(arr) < horizon),
    }


def diagnose(
    d: pd.DataFrame,
    p: dict[str, np.ndarray],
    arrays: dict[str, dict[str, np.ndarray]],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    i, j = OOS
    candidate = p["candidate"]
    b1 = p["b1"]
    market = arrays["candidate"]["market"]
    candidate_net = arrays["candidate"]["net"]
    b1_net = arrays["b1"]["net"]
    candidate_fees = arrays["candidate"]["fees"]
    b1_fees = arrays["b1"]["fees"]

    bridge_mask = (candidate[i:j] == 0.5) & (b1[i:j] == 0.0)
    fee_delta = float(candidate_fees[i:j].sum() - b1_fees[i:j].sum())
    observed = float((candidate_net[i:j] - b1_net[i:j]).sum())
    timing = float(((candidate[i:j] - b1[i:j]) * market[i:j]).sum())
    if not math.isclose(observed, timing - fee_delta, abs_tol=1e-12):
        raise ValueError("candidate-B1 decomposition")

    oos_events = [e for e in events if i <= e["execution_t"] < j]
    crossings = [e for e in oos_events if e["exit_crossing"]]
    starts = [e for e in oos_events if e["bridge_start"]]
    restores = [e for e in oos_events if e["bridge_restore"]]
    expiries = [e for e in oos_events if e["bridge_expiry"]]
    direct = [e for e in oos_events if e["direct_exit"]]

    crossing_details: list[dict[str, Any]] = []
    for e in crossings:
        start = e["execution_t"]
        crossing_details.append(
            {
                "timestamp": e["timestamp"],
                "mechanical_exit": e["mechanical_exit"],
                "pre_margin": e["pre_margin"],
                "post_margin": e["post_margin"],
                "current_leg": e["current_leg"],
                "lag_leg": e["lag_leg"],
                "next_24h": forward_return(market, start, 24),
                "next_168h": forward_return(market, start, 168),
                "next_720h": forward_return(market, start, 720),
            }
        )

    episodes: list[dict[str, Any]] = []
    for start_event in starts:
        terminal = next(
            (
                e
                for e in events
                if e["decision_t"] > start_event["decision_t"]
                and (e["bridge_restore"] or e["bridge_expiry"])
            ),
            None,
        )
        start = start_event["execution_t"]
        end = terminal["execution_t"] if terminal is not None else min(j, len(candidate))
        end = min(end, j)
        if start >= end:
            continue
        interval_market = market[start:end]
        episodes.append(
            {
                "start_timestamp": start_event["timestamp"],
                "terminal_timestamp": terminal["timestamp"] if terminal else None,
                "terminal_type": (
                    "restore"
                    if terminal and terminal["bridge_restore"]
                    else "expiry"
                    if terminal
                    else "right_censored"
                ),
                "hours": int(end - start),
                "pre_margin": start_event["pre_margin"],
                "post_margin": start_event["post_margin"],
                "current_leg": start_event["current_leg"],
                "lag_leg": start_event["lag_leg"],
                "full_market_return_arithmetic": float(interval_market.sum()),
                "full_market_return_compounded": float(np.prod(1.0 + interval_market) - 1.0),
                "candidate_timing_contribution": float(0.5 * interval_market.sum()),
            }
        )

    bridge_market = market[i:j][bridge_mask]
    mechanical_details = [x for x in crossing_details if x["mechanical_exit"]]
    nonmechanical_details = [x for x in crossing_details if not x["mechanical_exit"]]

    def mean_forward(rows: list[dict[str, Any]], key: str) -> float | None:
        values = [x[key]["compounded"] for x in rows if not x[key]["right_censored"]]
        return float(np.mean(values)) if values else None

    abs_episode_contributions = [abs(x["candidate_timing_contribution"]) for x in episodes]
    return {
        "exit_crossings": len(crossings),
        "mechanical_exit_crossings": len(starts),
        "direct_exits": len(direct),
        "bridge_restores": len(restores),
        "bridge_expiries": len(expiries),
        "bridge_hours": int(bridge_mask.sum()),
        "full_exposure_equivalent_hours_added": float(0.5 * bridge_mask.sum()),
        "bridge_full_market_return_arithmetic": float(bridge_market.sum()),
        "bridge_full_market_return_compounded": (
            float(np.prod(1.0 + bridge_market) - 1.0) if len(bridge_market) else 0.0
        ),
        "candidate_timing_contribution": timing,
        "incremental_fees": fee_delta,
        "arithmetic_candidate_minus_b1": observed,
        "episode_breadth": {
            "positive_episodes": int(
                sum(x["full_market_return_arithmetic"] > 0 for x in episodes)
            ),
            "negative_episodes": int(
                sum(x["full_market_return_arithmetic"] < 0 for x in episodes)
            ),
            "largest_abs_timing_contribution_share": (
                float(max(abs_episode_contributions) / sum(abs_episode_contributions))
                if abs_episode_contributions and sum(abs_episode_contributions) > 0
                else None
            ),
        },
        "mean_post_exit_compounded": {
            "mechanical": {
                "24h": mean_forward(mechanical_details, "next_24h"),
                "168h": mean_forward(mechanical_details, "next_168h"),
                "720h": mean_forward(mechanical_details, "next_720h"),
            },
            "nonmechanical": {
                "24h": mean_forward(nonmechanical_details, "next_24h"),
                "168h": mean_forward(nonmechanical_details, "next_168h"),
                "720h": mean_forward(nonmechanical_details, "next_720h"),
            },
        },
        "crossings": crossing_details,
        "episodes": episodes,
    }


def acceptance(market_result: dict[str, Any]) -> dict[str, bool]:
    c = market_result["metrics"]["development_oos"]["candidate"]
    b = market_result["metrics"]["development_oos"]["b1"]
    br = market_result["breadth"]
    u = market_result["uncertainty"]
    residual = market_result["residual_sharpe"]
    return {
        "positive_net": c["net_return"] > 0,
        "net_at_least_b1": c["net_return"] >= b["net_return"],
        "sharpe_at_least_b1": (
            c["sharpe"] is not None and b["sharpe"] is not None and c["sharpe"] >= b["sharpe"]
        ),
        "drawdown_no_worse": c["max_drawdown"] >= b["max_drawdown"] - 1e-12,
        "turnover_no_more": c["turnover"] <= b["turnover"] + 1e-12,
        "edge_per_turnover_at_least_b1": c["edge_per_turnover_bps"] >= b["edge_per_turnover_bps"],
        "profitable_folds": br["profitable_folds"] >= 7,
        "profitable_years": br["profitable_years"] >= 3,
        "fold_concentration": (
            br["positive_fold_concentration"] is not None
            and br["positive_fold_concentration"] <= 0.5
        ),
        "positive_residual_sharpe": residual is not None and residual > 0,
        "mean_delta_lower_positive": u["annualized_mean_delta"]["lower_95"] > 0,
        "sharpe_delta_lower_positive": u["sharpe_delta"]["lower_95"] > 0,
        "positive_full_return": (
            market_result["metrics"]["full_scored"]["candidate"]["net_return"] > 0
        ),
    }


def market_result(path: Path, market: str) -> dict[str, Any]:
    d = load(path, market)
    p, events = positions(d)
    arrays = {name: pack(d, pos) for name, pos in p.items()}
    out: dict[str, Any] = {
        "source": {
            "path": str(path),
            "sha256": sha256(path),
            "rows_read": len(d),
            "start": d.index[0].isoformat(),
            "end": d.index[-1].isoformat(),
        },
        "metrics": {},
    }
    for label, span in (("training", TRAIN), ("development_oos", OOS), ("full_scored", FULL)):
        out["metrics"][label] = {
            name: metrics(arrays[name], p[name], span) for name in ("candidate", "b1", "b0")
        }
    out["breadth"] = breadth(arrays["candidate"]["net"], d.index)
    out["benchmark_breadth"] = breadth(arrays["b1"]["net"], d.index)
    out["benchmark_relative_breadth"] = {
        "folds_improved_vs_b1": int(
            sum(
                c > b
                for c, b in zip(
                    out["breadth"]["fold_returns"],
                    out["benchmark_breadth"]["fold_returns"],
                    strict=True,
                )
            )
        ),
        "years_improved_vs_b1": int(
            sum(
                out["breadth"]["year_returns"][year]
                > out["benchmark_breadth"]["year_returns"][year]
                for year in out["breadth"]["year_returns"]
            )
        ),
    }
    out["residual_sharpe"] = sharpe(
        arrays["candidate"]["net"][OOS[0] : OOS[1]] - arrays["b1"]["net"][OOS[0] : OOS[1]]
    )
    out["uncertainty"] = bootstrap(arrays["candidate"]["net"], arrays["b1"]["net"])
    out["diagnostic"] = diagnose(d, p, arrays, events)
    out["acceptance_gates"] = acceptance(out)
    out["accepted"] = all(out["acceptance_gates"].values())
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--btc", type=Path, required=True)
    parser.add_argument("--eth", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result = {
        "family_id": "base-exit-margin-source-bridge-1h-v1",
        "issue": 715,
        "candidate_count": 1,
        "parameter_grid_count": 0,
        "fee_one_way": FEE,
        "bar": "1H",
        "execution": "completed daily 00:00 UTC decision -> next hourly open",
        "sample": {"training": TRAIN, "development_oos": OOS, "full_scored": FULL, "rows": N},
        "bootstrap": {"resamples": RESAMPLES, "block_hours": BLOCK, "seed": SEED},
        "markets": {
            "BTC-USDT": market_result(args.btc, "BTC-USDT"),
            "ETH-USDT": market_result(args.eth, "ETH-USDT"),
        },
    }
    result["accepted"] = all(x["accepted"] for x in result["markets"].values())
    result["verdict"] = (
        "accept_exact_base_exit_margin_source_bridge_family"
        if result["accepted"]
        else "reject_exact_base_exit_margin_source_bridge_family"
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
