#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

FEE = 0.0005
LOOKBACK = 2160
EPISODE_HOURS = 168
PREFIX_ROWS = 43441
TRAIN = (2880, 17520)
OOS = (17520, 43440)
FULL = (2880, 43440)
FOLD_HOURS = 2160
BOOTSTRAP_BLOCK = 168
BOOTSTRAP_RESAMPLES = 5000
BOOTSTRAP_SEED = 20260731
ANNUALIZATION = 8760.0


@dataclass(frozen=True)
class Episode:
    start_interval: int
    terminal_interval: int
    terminal_reason: str
    posterior_episodes_before: int
    posterior_wins_before: int
    exposure: float
    unit_half_sleeve_carry: float
    unit_half_sleeve_target: float
    win: bool


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_sha(payload: dict[str, Any]) -> str:
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def load_frozen(path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    full_sha = sha256_file(path)
    raw = pd.read_csv(path)
    if len(raw) < PREFIX_ROWS:
        raise ValueError(f"{path}: need at least {PREFIX_ROWS} rows, found {len(raw)}")
    required = {"timestamp", "open", "high", "low", "close", "confirm"}
    missing = required.difference(raw.columns)
    if missing:
        raise ValueError(f"{path}: missing columns {sorted(missing)}")
    raw["timestamp"] = pd.to_datetime(raw["timestamp"], utc=True)
    frozen = raw.iloc[:PREFIX_ROWS].copy()
    if frozen["timestamp"].duplicated().any():
        raise ValueError(f"{path}: duplicate timestamps in frozen prefix")
    delta = frozen["timestamp"].diff().dropna()
    if not (delta == pd.Timedelta(hours=1)).all():
        bad = delta[delta != pd.Timedelta(hours=1)].head()
        raise ValueError(f"{path}: non-contiguous frozen prefix: {bad.to_dict()}")
    if not (frozen["confirm"].astype(int) == 1).all():
        raise ValueError(f"{path}: unconfirmed row in frozen prefix")
    for col in ["open", "high", "low", "close"]:
        vals = frozen[col].to_numpy(dtype=float)
        if not np.isfinite(vals).all() or not (vals > 0).all():
            raise ValueError(f"{path}: invalid {col}")
    prefix_csv = frozen.to_csv(index=False, lineterminator="\n").encode()
    provenance = {
        "file_name": path.name,
        "source_rows": int(len(raw)),
        "frozen_rows": int(len(frozen)),
        "source_start": raw["timestamp"].iloc[0].isoformat(),
        "source_end": raw["timestamp"].iloc[-1].isoformat(),
        "frozen_start": frozen["timestamp"].iloc[0].isoformat(),
        "frozen_end": frozen["timestamp"].iloc[-1].isoformat(),
        "full_file_sha256": full_sha,
        "canonical_frozen_csv_sha256": hashlib.sha256(prefix_csv).hexdigest(),
        "future_suffix_rows_excluded": int(len(raw) - PREFIX_ROWS),
        "confirmed": True,
        "contiguous_1h": True,
    }
    return frozen, provenance


def market_returns(df: pd.DataFrame) -> np.ndarray:
    opens = df["open"].to_numpy(dtype=float)
    return opens[1:] / opens[:-1] - 1.0


def daily_base_decisions(df: pd.DataFrame) -> np.ndarray:
    close = df["close"].to_numpy(dtype=float)
    timestamps = df["timestamp"]
    base = np.zeros(len(df), dtype=float)
    current = 0.0
    for t in range(len(df)):
        if t >= LOOKBACK and timestamps.iloc[t].hour == 0:
            current = float(close[t] > close[t - LOOKBACK])
        base[t] = current
    return base


def hourly_base_decisions(df: pd.DataFrame) -> np.ndarray:
    close = df["close"].to_numpy(dtype=float)
    base = np.zeros(len(df), dtype=float)
    base[LOOKBACK:] = (close[LOOKBACK:] > close[:-LOOKBACK]).astype(float)
    return base


def decision_to_interval_position(target: np.ndarray) -> np.ndarray:
    # Interval i is open[i] -> open[i+1]. A completed bar t can execute only
    # at open[t+1], so interval i uses target decision i-1.
    n_intervals = len(target) - 1
    position = np.zeros(n_intervals, dtype=float)
    if n_intervals > 1:
        position[1:] = target[:-2]
    return position


def build_soft_candidate(
    df: pd.DataFrame,
) -> tuple[np.ndarray, list[Episode], dict[str, Any]]:
    n = len(df)
    rets = market_returns(df)
    base = daily_base_decisions(df)
    target = np.zeros(n, dtype=float)

    wins = 0
    completed = 0
    active: dict[str, Any] | None = None
    episodes: list[Episode] = []
    prior_base = 0.0
    regime_seen_positive = False

    for t in range(n):
        if t < LOOKBACK or df["timestamp"].iloc[t].hour != 0:
            target[t] = target[t - 1] if t else 0.0
            continue

        current_base = base[t]
        execution_interval = t + 1

        if current_base > 0:
            regime_seen_positive = True
            if active is not None:
                terminal = min(execution_interval, len(rets))
                start = active["start_interval"]
                carry = float(np.sum(rets[start:terminal]))
                unit_target = 0.5 * carry + FEE
                win = unit_target > 0.0
                episodes.append(
                    Episode(
                        start_interval=start,
                        terminal_interval=terminal,
                        terminal_reason="base_recross",
                        posterior_episodes_before=active["episodes_before"],
                        posterior_wins_before=active["wins_before"],
                        exposure=active["exposure"],
                        unit_half_sleeve_carry=0.5 * carry,
                        unit_half_sleeve_target=unit_target,
                        win=win,
                    )
                )
                completed += 1
                wins += int(win)
                active = None
            target[t] = 1.0
        else:
            transitioned = prior_base > 0 and regime_seen_positive
            if active is None and transitioned:
                exposure = 0.5 * (wins + 1.0) / (completed + 2.0)
                active = {
                    "start_interval": execution_interval,
                    "episodes_before": completed,
                    "wins_before": wins,
                    "exposure": exposure,
                }
                target[t] = exposure
            elif active is not None:
                elapsed = execution_interval - active["start_interval"]
                if elapsed >= EPISODE_HOURS:
                    terminal = min(execution_interval, len(rets))
                    start = active["start_interval"]
                    carry = float(np.sum(rets[start:terminal]))
                    unit_target = 0.5 * carry
                    win = unit_target > 0.0
                    episodes.append(
                        Episode(
                            start_interval=start,
                            terminal_interval=terminal,
                            terminal_reason="expiry",
                            posterior_episodes_before=active["episodes_before"],
                            posterior_wins_before=active["wins_before"],
                            exposure=active["exposure"],
                            unit_half_sleeve_carry=0.5 * carry,
                            unit_half_sleeve_target=unit_target,
                            win=win,
                        )
                    )
                    completed += 1
                    wins += int(win)
                    active = None
                    target[t] = 0.0
                else:
                    target[t] = active["exposure"]
            else:
                target[t] = 0.0
        prior_base = current_base

    position = decision_to_interval_position(target)
    diag = {
        "completed_episodes": completed,
        "wins": wins,
        "losses": completed - wins,
        "posterior_mean_at_end": (wins + 1.0) / (completed + 2.0),
        "active_uncompleted_episode_at_boundary": active is not None,
        "exposure_min_completed": min((e.exposure for e in episodes), default=None),
        "exposure_max_completed": max((e.exposure for e in episodes), default=None),
    }
    return position, episodes, diag


def build_benchmark(df: pd.DataFrame, daily: bool) -> np.ndarray:
    target = daily_base_decisions(df) if daily else hourly_base_decisions(df)
    return decision_to_interval_position(target)


def policy_returns(
    position: np.ndarray,
    rets: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    previous = np.r_[0.0, position[:-1]]
    turnover = np.abs(position - previous)
    fees = FEE * turnover
    net = position * rets - fees
    return net, turnover, fees


def max_drawdown(net: np.ndarray) -> float:
    if len(net) == 0:
        return float("nan")
    wealth = np.cumprod(1.0 + net)
    peaks = np.maximum.accumulate(np.r_[1.0, wealth])[:-1]
    return float(np.min(wealth / peaks - 1.0))


def sharpe(net: np.ndarray) -> float:
    if len(net) < 2:
        return float("nan")
    sd = float(np.std(net, ddof=1))
    if sd == 0.0:
        return float("nan")
    return float(math.sqrt(ANNUALIZATION) * np.mean(net) / sd)


def metrics(
    net: np.ndarray,
    turnover: np.ndarray,
    fees: np.ndarray,
    position: np.ndarray,
) -> dict[str, Any]:
    wealth = float(np.prod(1.0 + net) - 1.0)
    to = float(np.sum(turnover))
    arithmetic = float(np.sum(net))
    return {
        "net_return": wealth,
        "arithmetic_net_return": arithmetic,
        "sharpe": sharpe(net),
        "max_drawdown": max_drawdown(net),
        "turnover": to,
        "fees": float(np.sum(fees)),
        "edge_per_turnover_bps": (
            float(arithmetic / to * 10000.0) if to > 0 else None
        ),
        "mean_exposure": float(np.mean(position)),
        "long_or_fractional_hours": int(np.sum(position > 0)),
    }


def sample_metrics(
    net: np.ndarray,
    turnover: np.ndarray,
    fees: np.ndarray,
    position: np.ndarray,
    bounds: tuple[int, int],
) -> dict[str, Any]:
    a, b = bounds
    return metrics(net[a:b], turnover[a:b], fees[a:b], position[a:b])


def fold_and_year_breadth(
    df: pd.DataFrame,
    candidate_net: np.ndarray,
    b1_net: np.ndarray,
) -> dict[str, Any]:
    a, b = OOS
    folds = []
    for k, start in enumerate(range(a, b, FOLD_HOURS)):
        end = min(start + FOLD_HOURS, b)
        c = float(np.prod(1.0 + candidate_net[start:end]) - 1.0)
        ref = float(np.prod(1.0 + b1_net[start:end]) - 1.0)
        folds.append(
            {
                "fold": k + 1,
                "start": start,
                "end": end,
                "candidate_net": c,
                "b1_net": ref,
                "improved": c > ref,
            }
        )

    interval_ts = df["timestamp"].iloc[:-1].reset_index(drop=True)
    years = []
    for year in sorted(interval_ts.iloc[a:b].dt.year.unique()):
        mask = interval_ts.dt.year.to_numpy() == year
        idx = np.flatnonzero(
            mask
            & (np.arange(len(interval_ts)) >= a)
            & (np.arange(len(interval_ts)) < b)
        )
        c = float(np.prod(1.0 + candidate_net[idx]) - 1.0)
        ref = float(np.prod(1.0 + b1_net[idx]) - 1.0)
        years.append(
            {
                "year": int(year),
                "candidate_net": c,
                "b1_net": ref,
                "improved": c > ref,
            }
        )

    positive_folds = [x["candidate_net"] for x in folds if x["candidate_net"] > 0]
    concentration = (
        max(positive_folds) / sum(positive_folds)
        if positive_folds and sum(positive_folds) > 0
        else None
    )
    residual = candidate_net[a:b] - b1_net[a:b]
    return {
        "folds": folds,
        "profitable_folds": sum(x["candidate_net"] > 0 for x in folds),
        "improved_folds": sum(x["improved"] for x in folds),
        "years": years,
        "profitable_years": sum(x["candidate_net"] > 0 for x in years),
        "improved_years": sum(x["improved"] for x in years),
        "positive_fold_concentration": concentration,
        "residual_sharpe": sharpe(residual),
    }


def bootstrap(
    candidate: np.ndarray,
    b1: np.ndarray,
    seed: int,
) -> dict[str, Any]:
    n = len(candidate)
    if n != OOS[1] - OOS[0]:
        raise ValueError(f"unexpected OOS length {n}")
    rng = np.random.default_rng(seed)
    starts_max = n - BOOTSTRAP_BLOCK
    mean_delta = np.empty(BOOTSTRAP_RESAMPLES)
    sharpe_delta = np.empty(BOOTSTRAP_RESAMPLES)
    blocks_needed = math.ceil(n / BOOTSTRAP_BLOCK)
    for j in range(BOOTSTRAP_RESAMPLES):
        starts = rng.integers(0, starts_max + 1, size=blocks_needed)
        idx = np.concatenate(
            [np.arange(s, s + BOOTSTRAP_BLOCK) for s in starts]
        )[:n]
        c = candidate[idx]
        r = b1[idx]
        mean_delta[j] = ANNUALIZATION * float(np.mean(c - r))
        sharpe_delta[j] = sharpe(c) - sharpe(r)
    q = [0.025, 0.5, 0.975]
    return {
        "annualized_mean_delta_point": ANNUALIZATION
        * float(np.mean(candidate - b1)),
        "annualized_mean_delta_quantiles": dict(
            zip(
                ["q025", "q500", "q975"],
                map(float, np.quantile(mean_delta, q)),
            )
        ),
        "sharpe_delta_point": sharpe(candidate) - sharpe(b1),
        "sharpe_delta_quantiles": dict(
            zip(
                ["q025", "q500", "q975"],
                map(float, np.quantile(sharpe_delta, q)),
            )
        ),
        "resamples": BOOTSTRAP_RESAMPLES,
        "block_hours": BOOTSTRAP_BLOCK,
        "seed": seed,
    }


def episode_diagnostics(
    episodes: list[Episode],
    bounds: tuple[int, int],
) -> dict[str, Any]:
    a, b = bounds
    overlapping = [
        e for e in episodes if e.start_interval < b and e.terminal_interval > a
    ]
    starts = [e for e in episodes if a <= e.start_interval < b]
    targets = [e.unit_half_sleeve_target for e in starts]
    exposures = [e.exposure for e in starts]
    contributions = [
        (e.exposure / 0.5) * e.unit_half_sleeve_target for e in starts
    ]
    positive = [x for x in contributions if x > 0]
    return {
        "starts": len(starts),
        "overlapping": len(overlapping),
        "wins": sum(e.win for e in starts),
        "expiries": sum(e.terminal_reason == "expiry" for e in starts),
        "recrosses": sum(e.terminal_reason == "base_recross" for e in starts),
        "unit_target_sum": float(sum(targets)),
        "unit_target_mean": float(np.mean(targets)) if targets else None,
        "mean_exposure": float(np.mean(exposures)) if exposures else None,
        "min_exposure": float(np.min(exposures)) if exposures else None,
        "max_exposure": float(np.max(exposures)) if exposures else None,
        "completed_episode_arithmetic_contribution": float(sum(contributions)),
        "largest_positive_episode_share": (
            float(max(positive) / sum(positive)) if positive else None
        ),
        "episodes": [asdict(e) for e in starts],
    }


def residual_decomposition(
    episodes: list[Episode],
    candidate_position: np.ndarray,
    b1_position: np.ndarray,
    candidate_net: np.ndarray,
    b1_net: np.ndarray,
    bounds: tuple[int, int],
) -> dict[str, Any]:
    a, b = bounds
    completed = [
        e
        for e in episodes
        if a <= e.start_interval < b and e.terminal_interval <= b
    ]
    completed_contribution = float(
        sum(
            (e.exposure / 0.5) * e.unit_half_sleeve_target
            for e in completed
        )
    )
    arithmetic_residual = float(np.sum(candidate_net[a:b] - b1_net[a:b]))

    boundary_open = None
    if b > a and abs(candidate_position[b - 1] - b1_position[b - 1]) > 1e-15:
        exposure = float(candidate_position[b - 1])
        start = b - 1
        while (
            start > a
            and abs(candidate_position[start - 1] - exposure) <= 1e-15
            and abs(b1_position[start - 1]) <= 1e-15
        ):
            start -= 1
        partial = float(np.sum(candidate_net[start:b] - b1_net[start:b]))
        boundary_open = {
            "start_interval": start,
            "scored_boundary_interval": b,
            "exposure": exposure,
            "observed_hours": b - start,
            "partial_arithmetic_contribution": partial,
        }
    boundary_contribution = (
        0.0
        if boundary_open is None
        else boundary_open["partial_arithmetic_contribution"]
    )
    identity_error = (
        arithmetic_residual - completed_contribution - boundary_contribution
    )
    if abs(identity_error) > 1e-12:
        raise AssertionError(f"residual decomposition error {identity_error}")
    return {
        "candidate_minus_b1_arithmetic": arithmetic_residual,
        "completed_episode_contribution": completed_contribution,
        "boundary_open_episode": boundary_open,
        "identity_error": float(identity_error),
    }


def evaluate_market(
    name: str,
    path: Path,
) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    df, provenance = load_frozen(path)
    rets = market_returns(df)
    cand_pos, episodes, state_diag = build_soft_candidate(df)
    b1_pos = build_benchmark(df, daily=True)
    b0_pos = build_benchmark(df, daily=False)
    cand_net, cand_to, cand_fee = policy_returns(cand_pos, rets)
    b1_net, b1_to, b1_fee = policy_returns(b1_pos, rets)
    b0_net, b0_to, b0_fee = policy_returns(b0_pos, rets)

    samples: dict[str, Any] = {}
    for label, bounds in [
        ("training", TRAIN),
        ("development_oos", OOS),
        ("full", FULL),
    ]:
        samples[label] = {
            "candidate": sample_metrics(
                cand_net,
                cand_to,
                cand_fee,
                cand_pos,
                bounds,
            ),
            "daily_b1": sample_metrics(
                b1_net,
                b1_to,
                b1_fee,
                b1_pos,
                bounds,
            ),
            "hourly_b0": sample_metrics(
                b0_net,
                b0_to,
                b0_fee,
                b0_pos,
                bounds,
            ),
        }

    breadth = fold_and_year_breadth(df, cand_net, b1_net)
    unc = bootstrap(
        cand_net[OOS[0] : OOS[1]],
        b1_net[OOS[0] : OOS[1]],
        BOOTSTRAP_SEED,
    )
    result = {
        "market": name,
        "provenance": provenance,
        "samples": samples,
        "breadth": breadth,
        "uncertainty": unc,
        "state": state_diag,
        "training_episodes": episode_diagnostics(episodes, TRAIN),
        "oos_episodes": episode_diagnostics(episodes, OOS),
        "full_episodes": episode_diagnostics(episodes, FULL),
        "oos_residual_decomposition": residual_decomposition(
            episodes,
            cand_pos,
            b1_pos,
            cand_net,
            b1_net,
            OOS,
        ),
    }
    arrays = {"candidate": cand_net, "b1": b1_net, "b0": b0_net}
    return result, arrays


def gate_market(result: dict[str, Any]) -> dict[str, bool]:
    c = result["samples"]["development_oos"]["candidate"]
    b = result["samples"]["development_oos"]["daily_b1"]
    breadth = result["breadth"]
    unc = result["uncertainty"]
    full = result["samples"]["full"]["candidate"]
    return {
        "oos_net_ge_b1": c["net_return"] >= b["net_return"],
        "oos_sharpe_ge_b1": c["sharpe"] >= b["sharpe"],
        "oos_drawdown_ge_b1": c["max_drawdown"] >= b["max_drawdown"],
        "oos_turnover_le_b1": c["turnover"] <= b["turnover"],
        "oos_edge_per_turnover_ge_b1": (
            c["edge_per_turnover_bps"] >= b["edge_per_turnover_bps"]
        ),
        "profitable_folds_ge_7": breadth["profitable_folds"] >= 7,
        "profitable_years_ge_3": breadth["profitable_years"] >= 3,
        "residual_sharpe_gt_0": breadth["residual_sharpe"] > 0,
        "mean_delta_l95_gt_0": (
            unc["annualized_mean_delta_quantiles"]["q025"] > 0
        ),
        "sharpe_delta_l95_gt_0": (
            unc["sharpe_delta_quantiles"]["q025"] > 0
        ),
        "full_net_gt_0": full["net_return"] > 0,
    }


def common_bootstrap(
    arrays: dict[str, dict[str, np.ndarray]],
) -> dict[str, Any]:
    names = sorted(arrays)
    pairs = [
        (
            arrays[name]["candidate"][OOS[0] : OOS[1]],
            arrays[name]["b1"][OOS[0] : OOS[1]],
        )
        for name in names
    ]
    n = len(pairs[0][0])
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    starts_max = n - BOOTSTRAP_BLOCK
    blocks_needed = math.ceil(n / BOOTSTRAP_BLOCK)
    mean_stat = np.empty(BOOTSTRAP_RESAMPLES)
    sharpe_stat = np.empty(BOOTSTRAP_RESAMPLES)
    for j in range(BOOTSTRAP_RESAMPLES):
        starts = rng.integers(0, starts_max + 1, size=blocks_needed)
        idx = np.concatenate(
            [np.arange(s, s + BOOTSTRAP_BLOCK) for s in starts]
        )[:n]
        means = [
            ANNUALIZATION * float(np.mean(candidate[idx] - benchmark[idx]))
            for candidate, benchmark in pairs
        ]
        sharpes = [
            sharpe(candidate[idx]) - sharpe(benchmark[idx])
            for candidate, benchmark in pairs
        ]
        mean_stat[j] = float(np.median(means))
        sharpe_stat[j] = float(np.median(sharpes))
    point_means = [
        ANNUALIZATION * float(np.mean(candidate - benchmark))
        for candidate, benchmark in pairs
    ]
    point_sharpes = [
        sharpe(candidate) - sharpe(benchmark)
        for candidate, benchmark in pairs
    ]
    return {
        "markets": names,
        "median_annualized_mean_delta_point": float(np.median(point_means)),
        "median_annualized_mean_delta_ci": list(
            map(float, np.quantile(mean_stat, [0.025, 0.975]))
        ),
        "median_sharpe_delta_point": float(np.median(point_sharpes)),
        "median_sharpe_delta_ci": list(
            map(float, np.quantile(sharpe_stat, [0.025, 0.975]))
        ),
        "resamples": BOOTSTRAP_RESAMPLES,
        "block_hours": BOOTSTRAP_BLOCK,
        "seed": BOOTSTRAP_SEED,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sol", type=Path, required=True)
    parser.add_argument("--xrp", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    protocol_sha = sha256_file(args.protocol)
    markets: dict[str, Any] = {}
    arrays: dict[str, dict[str, np.ndarray]] = {}
    for name, path in [("SOL-USDT", args.sol), ("XRP-USDT", args.xrp)]:
        result, arr = evaluate_market(name, path)
        result["gates"] = gate_market(result)
        result["accepted"] = all(result["gates"].values())
        markets[name] = result
        arrays[name] = arr

    common = common_bootstrap(arrays)
    accepted = all(market["accepted"] for market in markets.values())
    payload: dict[str, Any] = {
        "schema_version": 1,
        "family": "beta-sign-soft-exit-sleeve-1h-v1",
        "issue": 757,
        "candidate_count": 1,
        "parameter_grid_count": 0,
        "fee_one_way": FEE,
        "protocol_sha256": protocol_sha,
        "source_workflow": {
            "run_id": 30599723593,
            "tested_head": "f7c069d5f6a1dfdc9e4ac00d8324f487cb1f69c3",
            "SOL-USDT": {
                "artifact_id": 8781469963,
                "artifact_sha256": (
                    "082b96bdd3bdec5f80b7fd68949ae588"
                    "a77ddd392d733528790400bc725b699a"
                ),
            },
            "XRP-USDT": {
                "artifact_id": 8781477440,
                "artifact_sha256": (
                    "05b884d52cfe7aeaef3bfe116e6875c"
                    "f1cbe70a486600993cece57fa9dc7316c"
                ),
            },
        },
        "diagnostic_repair": (
            "store source basenames rather than environment-specific absolute paths; "
            "explicitly account for any boundary-open sleeve in residual attribution"
        ),
        "markets": markets,
        "common_block_uncertainty": common,
        "accepted": accepted,
        "verdict": (
            "accept_beta_sign_soft_exit_sleeve_family"
            if accepted
            else "reject_beta_sign_soft_exit_sleeve_family"
        ),
    }
    payload["canonical_payload_sha256"] = canonical_sha(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "sha256": sha256_file(args.output),
                "canonical_payload_sha256": payload[
                    "canonical_payload_sha256"
                ],
                "verdict": payload["verdict"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
