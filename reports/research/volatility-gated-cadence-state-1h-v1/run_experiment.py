#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

FEE = 0.0005
ANNUAL_HOURS = 24 * 365
PREFIX_ROWS = 43_441
TRAIN = (2_880, 17_520)
OOS = (17_520, 43_440)
FULL = (2_880, 43_440)
FOLD_HOURS = 2_160
BLOCK_HOURS = 168
DEFAULT_SEED = 20_260_731


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def find_csv(data_root: Path, instrument: str) -> Path:
    candidates = [
        data_root / instrument / "snapshot" / f"okx-{instrument}-1H.normalized.csv",
        data_root / instrument / "candles.csv",
        data_root / instrument / "full" / "candles.csv",
    ]
    for path in candidates:
        if path.is_file():
            return path
    matches = list(data_root.glob(f"**/{instrument}/**/candles.csv")) + list(
        data_root.glob(f"**/okx-{instrument}-1H.normalized.csv")
    )
    if len(matches) != 1:
        raise FileNotFoundError(f"expected exactly one candle CSV for {instrument}, got {matches}")
    return matches[0]


def load_market(path: Path, instrument: str) -> dict[str, Any]:
    frame = pd.read_csv(path)
    required = {"timestamp", "open", "close", "confirm"}
    if not required.issubset(frame.columns):
        raise ValueError(f"{instrument}: missing columns {sorted(required - set(frame.columns))}")
    if len(frame) < PREFIX_ROWS:
        raise ValueError(f"{instrument}: need at least {PREFIX_ROWS} rows, got {len(frame)}")
    frame = frame.iloc[:PREFIX_ROWS].copy()
    timestamps = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
    expected = pd.date_range(timestamps.iloc[0], periods=PREFIX_ROWS, freq="h", tz="UTC")
    if not np.array_equal(timestamps.array, expected.array):
        raise ValueError(f"{instrument}: first {PREFIX_ROWS} timestamps are not contiguous 1H")
    if timestamps.iloc[0] != pd.Timestamp("2021-07-24T00:00:00Z"):
        raise ValueError(f"{instrument}: unexpected first timestamp {timestamps.iloc[0]}")
    if timestamps.iloc[-1] != pd.Timestamp("2026-07-08T00:00:00Z"):
        raise ValueError(f"{instrument}: unexpected frozen-prefix end {timestamps.iloc[-1]}")
    confirm = pd.to_numeric(frame["confirm"], errors="raise").to_numpy()
    if not np.all(confirm == 1):
        raise ValueError(f"{instrument}: frozen prefix contains incomplete bars")
    opens = pd.to_numeric(frame["open"], errors="raise").to_numpy(float)
    closes = pd.to_numeric(frame["close"], errors="raise").to_numpy(float)
    if not np.all(np.isfinite(opens)) or not np.all(opens > 0):
        raise ValueError(f"{instrument}: invalid opens")
    if not np.all(np.isfinite(closes)) or not np.all(closes > 0):
        raise ValueError(f"{instrument}: invalid closes")
    return {
        "timestamps": timestamps,
        "opens": opens,
        "closes": closes,
        "csv_path": str(path),
        "csv_sha256": sha256_file(path),
        "source_rows": int(len(pd.read_csv(path, usecols=["timestamp"]))),
    }


def rolling_rms_squared_returns(log_returns: np.ndarray, window: int) -> np.ndarray:
    sq = np.square(log_returns)
    csum = np.r_[0.0, np.cumsum(sq)]
    out = np.full(log_returns.size, np.nan)
    idx = np.arange(window - 1, log_returns.size)
    sums = csum[idx + 1] - csum[idx + 1 - window]
    out[idx] = np.sqrt(sums / window)
    return out


def build_paths(market: dict[str, Any]) -> dict[str, dict[str, np.ndarray]]:
    ts = market["timestamps"]
    o = market["opens"]
    c = market["closes"]
    n = len(c)
    logret = np.full(n, np.nan)
    logret[1:] = np.log(c[1:] / c[:-1])
    rv168 = rolling_rms_squared_returns(logret[1:], 168)
    rv2160 = rolling_rms_squared_returns(logret[1:], 2160)
    ratio = np.full(n, np.nan)
    ratio[1:] = rv168 / rv2160
    if not np.all(np.isfinite(ratio[2160:])) or np.any(rv2160[2159:] <= 0):
        raise ValueError("non-finite or non-positive slow volatility")
    base = np.zeros(n, dtype=np.int8)
    base[2160:] = (c[2160:] > c[:-2160]).astype(np.int8)

    signals: dict[str, np.ndarray] = {}
    signals["B0"] = base.copy()
    b1 = np.zeros(n, dtype=np.int8)
    candidate = np.zeros(n, dtype=np.int8)
    current_b1 = 0
    current_candidate = 0
    update_daily = np.zeros(n, dtype=bool)
    update_high_vol = np.zeros(n, dtype=bool)
    for t in range(2160, n):
        midnight = ts.iloc[t].hour == 0
        high_vol = ratio[t] > 1.0
        if midnight:
            current_b1 = int(base[t])
            update_daily[t] = True
        b1[t] = current_b1
        if midnight or high_vol:
            current_candidate = int(base[t])
            if high_vol and not midnight:
                update_high_vol[t] = True
        candidate[t] = current_candidate
    signals["B1"] = b1
    signals["candidate"] = candidate

    market_return = o[1:] / o[:-1] - 1.0
    result: dict[str, dict[str, np.ndarray]] = {}
    for name, signal in signals.items():
        position = np.zeros(n - 1, dtype=float)
        position[1:] = signal[:-2]
        changes = np.abs(position - np.r_[0.0, position[:-1]])
        gross = position * market_return
        fee = FEE * changes
        net = gross - fee
        result[name] = {
            "position": position,
            "changes": changes,
            "gross": gross,
            "fee": fee,
            "net": net,
        }
    result["features"] = {
        "ratio": ratio,
        "base": base,
        "daily_update": update_daily,
        "high_vol_update": update_high_vol,
    }
    return result


def metrics(path: dict[str, np.ndarray], start: int, end: int) -> dict[str, float | int]:
    r = path["net"][start:end]
    gross = path["gross"][start:end]
    fees = path["fee"][start:end]
    changes = path["changes"][start:end]
    position = path["position"][start:end]
    wealth = np.cumprod(1.0 + r)
    curve = np.r_[1.0, wealth]
    drawdown = curve / np.maximum.accumulate(curve) - 1.0
    sd = float(np.std(r, ddof=1))
    sharpe = float(np.mean(r) / sd * math.sqrt(ANNUAL_HOURS)) if sd > 0 else math.nan
    turnover = float(np.sum(changes))
    return {
        "net_return": float(wealth[-1] - 1.0),
        "gross_arithmetic_return": float(np.sum(gross)),
        "net_arithmetic_return": float(np.sum(r)),
        "annualized_mean_return": float(np.mean(r) * ANNUAL_HOURS),
        "sharpe": sharpe,
        "max_drawdown": float(np.min(drawdown)),
        "turnover": turnover,
        "fees": float(np.sum(fees)),
        "edge_per_turn_bps": float(np.sum(r) / turnover * 10_000) if turnover > 0 else math.nan,
        "exposure": float(np.mean(position)),
        "position_changes": int(np.count_nonzero(changes)),
    }


def fold_year_diagnostics(path: dict[str, np.ndarray], timestamps: pd.Series) -> dict[str, Any]:
    start, end = OOS
    fold_returns: list[float] = []
    for left in range(start, end, FOLD_HOURS):
        right = left + FOLD_HOURS
        fold_returns.append(float(np.prod(1.0 + path["net"][left:right]) - 1.0))
    positive = [x for x in fold_returns if x > 0]
    concentration = max(positive) / sum(positive) if positive else math.inf
    years: dict[str, float] = {}
    interval_year = timestamps.iloc[:-1].dt.year.to_numpy()
    for year in sorted(set(interval_year[start:end])):
        mask = interval_year[start:end] == year
        years[str(int(year))] = float(np.prod(1.0 + path["net"][start:end][mask]) - 1.0)
    return {
        "fold_returns": fold_returns,
        "profitable_folds": int(sum(x > 0 for x in fold_returns)),
        "positive_fold_concentration": float(concentration),
        "year_returns": years,
        "profitable_years": int(sum(x > 0 for x in years.values())),
    }


def residual_sharpe(candidate: np.ndarray, benchmark: np.ndarray) -> float:
    residual = candidate - benchmark
    sd = float(np.std(residual, ddof=1))
    return float(np.mean(residual) / sd * math.sqrt(ANNUAL_HOURS)) if sd > 0 else math.nan


def paired_bootstrap(candidate: np.ndarray, benchmark: np.ndarray, *, resamples: int, seed: int) -> dict[str, Any]:
    n = len(candidate)
    if n != len(benchmark) or n < BLOCK_HOURS:
        raise ValueError("invalid bootstrap arrays")
    rng = np.random.default_rng(seed)
    blocks = math.ceil(n / BLOCK_HOURS)
    mean_delta = np.empty(resamples)
    sharpe_delta = np.empty(resamples)
    for k in range(resamples):
        starts = rng.integers(0, n - BLOCK_HOURS + 1, size=blocks)
        idx = np.concatenate([np.arange(s, s + BLOCK_HOURS) for s in starts])[:n]
        a = candidate[idx]
        b = benchmark[idx]
        mean_delta[k] = float(np.mean(a - b) * ANNUAL_HOURS)
        sa = float(np.std(a, ddof=1))
        sb = float(np.std(b, ddof=1))
        sharpe_delta[k] = (
            float(np.mean(a) / sa * math.sqrt(ANNUAL_HOURS))
            - float(np.mean(b) / sb * math.sqrt(ANNUAL_HOURS))
        )
    return {
        "method": "paired_non_circular_moving_block",
        "block_hours": BLOCK_HOURS,
        "resamples": resamples,
        "seed": seed,
        "annualized_mean_delta_point": float(np.mean(candidate - benchmark) * ANNUAL_HOURS),
        "annualized_mean_delta_ci95": [float(x) for x in np.quantile(mean_delta, [0.025, 0.975])],
        "sharpe_delta_point": float(
            np.mean(candidate) / np.std(candidate, ddof=1) * math.sqrt(ANNUAL_HOURS)
            - np.mean(benchmark) / np.std(benchmark, ddof=1) * math.sqrt(ANNUAL_HOURS)
        ),
        "sharpe_delta_ci95": [float(x) for x in np.quantile(sharpe_delta, [0.025, 0.975])],
    }


def evaluate_market(instrument: str, market: dict[str, Any], paths: dict[str, dict[str, np.ndarray]], resamples: int, seed: int) -> dict[str, Any]:
    samples = {"train": TRAIN, "oos": OOS, "full": FULL}
    performance = {
        sample: {name: metrics(paths[name], *bounds) for name in ("candidate", "B0", "B1")}
        for sample, bounds in samples.items()
    }
    breadth = fold_year_diagnostics(paths["candidate"], market["timestamps"])
    candidate_oos = paths["candidate"]["net"][OOS[0] : OOS[1]]
    b1_oos = paths["B1"]["net"][OOS[0] : OOS[1]]
    bootstrap = paired_bootstrap(candidate_oos, b1_oos, resamples=resamples, seed=seed)
    residual = residual_sharpe(candidate_oos, b1_oos)
    c = performance["oos"]["candidate"]
    b0 = performance["oos"]["B0"]
    b1 = performance["oos"]["B1"]
    gates = {
        "positive_oos_return": c["net_return"] > 0,
        "positive_oos_sharpe": c["sharpe"] > 0,
        "return_at_least_B1": c["net_return"] >= b1["net_return"],
        "sharpe_at_least_B1": c["sharpe"] >= b1["sharpe"],
        "drawdown_no_worse_B1": c["max_drawdown"] >= b1["max_drawdown"],
        "turnover_below_B0": c["turnover"] < b0["turnover"],
        "edge_per_turn_at_least_B1": c["edge_per_turn_bps"] >= b1["edge_per_turn_bps"],
        "profitable_folds_at_least_7": breadth["profitable_folds"] >= 7,
        "profitable_years_at_least_3": breadth["profitable_years"] >= 3,
        "positive_fold_concentration_at_most_0_5": breadth["positive_fold_concentration"] <= 0.5,
        "positive_residual_sharpe": residual > 0,
        "mean_delta_ci_lower_positive": bootstrap["annualized_mean_delta_ci95"][0] > 0,
        "sharpe_delta_ci_lower_positive": bootstrap["sharpe_delta_ci95"][0] > 0,
        "positive_full_return": performance["full"]["candidate"]["net_return"] > 0,
    }
    ratio = paths["features"]["ratio"]
    base = paths["features"]["base"]
    high_update = paths["features"]["high_vol_update"]
    daily_update = paths["features"]["daily_update"]
    os, oe = OOS
    candidate_pos = paths["candidate"]["position"]
    b1_pos = paths["B1"]["position"]
    b0_pos = paths["B0"]["position"]
    return {
        "instrument": instrument,
        "source": {
            "csv_path": market["csv_path"],
            "csv_sha256": market["csv_sha256"],
            "source_rows": market["source_rows"],
            "frozen_prefix_rows": PREFIX_ROWS,
            "frozen_start": market["timestamps"].iloc[0].isoformat(),
            "frozen_end": market["timestamps"].iloc[-1].isoformat(),
        },
        "performance": performance,
        "breadth": breadth,
        "residual_sharpe_vs_B1": residual,
        "bootstrap_vs_B1": bootstrap,
        "diagnostics": {
            "oos_high_vol_ratio_occupancy": float(np.mean(ratio[os:oe] > 1.0)),
            "oos_daily_refresh_decisions": int(np.sum(daily_update[os:oe])),
            "oos_non_midnight_high_vol_refresh_decisions": int(np.sum(high_update[os:oe])),
            "oos_base_sign_changes": int(np.count_nonzero(np.diff(base[os:oe]))),
            "oos_candidate_vs_B1_position_hours": int(np.count_nonzero(candidate_pos[os:oe] != b1_pos[os:oe])),
            "oos_candidate_vs_B0_position_hours": int(np.count_nonzero(candidate_pos[os:oe] != b0_pos[os:oe])),
            "oos_candidate_minus_B1_arithmetic": float(np.sum(candidate_oos - b1_oos)),
            "oos_candidate_minus_B1_fee": float(
                np.sum(paths["candidate"]["fee"][os:oe] - paths["B1"]["fee"][os:oe])
            ),
            "oos_candidate_minus_B1_gross": float(
                np.sum(paths["candidate"]["gross"][os:oe] - paths["B1"]["gross"][os:oe])
            ),
        },
        "gates": gates,
        "accepted": bool(all(gates.values())),
    }


def render_report(result: dict[str, Any]) -> str:
    lines = [
        "# Volatility-gated cadence state — terminal result",
        "",
        "```text",
        f"family          {result['family_id']}",
        f"issue           #{result['issue']}",
        f"candidate count {result['candidate_count']}",
        f"parameter grid  {result['parameter_grid']}",
        "fee             exactly 5 bps one way",
        f"verdict         {result['verdict']}",
        "```",
        "",
        "## Performance",
        "",
    ]
    for instrument, item in result["markets"].items():
        lines += [f"### {instrument}", "", "| Sample | Policy | Net | Sharpe | Max DD | Turnover | Edge/turn |", "|---|---|---:|---:|---:|---:|---:|"]
        for sample in ("train", "oos", "full"):
            for policy in ("candidate", "B1", "B0"):
                m = item["performance"][sample][policy]
                lines.append(
                    f"| {sample} | {policy} | {m['net_return']:.2%} | {m['sharpe']:.3f} | {m['max_drawdown']:.2%} | {m['turnover']:.3f} | {m['edge_per_turn_bps']:.2f} bps |"
                )
        b = item["breadth"]
        boot = item["bootstrap_vs_B1"]
        failed = [k for k, v in item["gates"].items() if not v]
        lines += [
            "",
            f"Breadth: {b['profitable_folds']}/12 profitable folds; {b['profitable_years']} profitable years; concentration {b['positive_fold_concentration']:.2%}.",
            f"Residual Sharpe versus B1: {item['residual_sharpe_vs_B1']:.3f}.",
            f"Annualised mean delta 95% CI: [{boot['annualized_mean_delta_ci95'][0]:.2%}, {boot['annualized_mean_delta_ci95'][1]:.2%}].",
            f"Sharpe delta 95% CI: [{boot['sharpe_delta_ci95'][0]:.3f}, {boot['sharpe_delta_ci95'][1]:.3f}].",
            f"High-volatility occupancy: {item['diagnostics']['oos_high_vol_ratio_occupancy']:.2%}; non-midnight high-vol refreshes: {item['diagnostics']['oos_non_midnight_high_vol_refresh_decisions']}.",
            f"Failed gates: {', '.join(failed) if failed else 'none'}.",
            "",
        ]
    lines += [
        "## Verdict",
        "",
        result["verdict"],
        "",
        "The exact family is accepted only if both fixed markets pass every frozen gate. No same-cohort rescue is authorised.",
        "",
    ]
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--data-root", required=True)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--instrument", action="append", required=True)
    p.add_argument("--resamples", type=int, default=5000)
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument("--source-workflow-run", default="")
    p.add_argument("--source-artifact-id", default="")
    p.add_argument("--tested-sha", default="")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if len(args.instrument) != 2 or len(set(args.instrument)) != 2:
        raise ValueError("exactly two unique instruments are required")
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    markets: dict[str, Any] = {}
    for offset, instrument in enumerate(args.instrument):
        source = load_market(find_csv(Path(args.data_root), instrument), instrument)
        paths = build_paths(source)
        markets[instrument] = evaluate_market(
            instrument, source, paths, args.resamples, args.seed + offset
        )
    accepted = all(item["accepted"] for item in markets.values())
    verdict = (
        "accept_volatility_gated_cadence_state_family"
        if accepted
        else "reject_volatility_gated_cadence_state_family"
    )
    result = {
        "schema_version": 1,
        "family_id": "volatility-gated-cadence-state-1h-v1",
        "issue": 764,
        "candidate_count": 1,
        "parameter_grid": 0,
        "bar": "1H",
        "fee_bps_one_way": 5.0,
        "execution": "completed_bar_t_to_open_t_plus_1_then_open_to_open_payoff",
        "research_parent": "5a0fcc97d1a882f8223656c51f5bb8055f534e38",
        "tested_sha": args.tested_sha,
        "source_workflow_run": args.source_workflow_run,
        "source_artifact_id": args.source_artifact_id,
        "sample": {"train": list(TRAIN), "oos": list(OOS), "full": list(FULL)},
        "bootstrap": {"block_hours": BLOCK_HOURS, "resamples": args.resamples, "seed_base": args.seed},
        "markets": markets,
        "accepted_markets": int(sum(item["accepted"] for item in markets.values())),
        "verdict": verdict,
    }
    payload = canonical_bytes(result)
    (out / "result.json").write_bytes(payload)
    summary = {
        "family_id": result["family_id"],
        "issue": result["issue"],
        "candidate_count": 1,
        "parameter_grid": 0,
        "markets": {
            k: {
                "accepted": v["accepted"],
                "oos_candidate": v["performance"]["oos"]["candidate"],
                "oos_B1": v["performance"]["oos"]["B1"],
                "breadth": v["breadth"],
                "residual_sharpe_vs_B1": v["residual_sharpe_vs_B1"],
                "bootstrap_vs_B1": v["bootstrap_vs_B1"],
                "failed_gates": [name for name, passed in v["gates"].items() if not passed],
            }
            for k, v in markets.items()
        },
        "verdict": verdict,
        "result_sha256": hashlib.sha256(payload).hexdigest(),
    }
    (out / "result-summary.json").write_bytes(canonical_bytes(summary))
    (out / "report.md").write_text(render_report(result), encoding="utf-8")
    print(f"result_sha256={hashlib.sha256(payload).hexdigest()}")
    print(f"verdict={verdict}")
    for instrument, item in markets.items():
        m = item["performance"]["oos"]["candidate"]
        print(
            f"{instrument}: net={m['net_return']:.8f} sharpe={m['sharpe']:.6f} "
            f"dd={m['max_drawdown']:.8f} turnover={m['turnover']:.3f} accepted={item['accepted']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
