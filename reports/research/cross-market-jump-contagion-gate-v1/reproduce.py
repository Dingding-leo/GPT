from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

HOURS_PER_YEAR = 8760.0
FEE = 0.0005
WINDOW = 720
QUANTILE = 0.01
BLOCK = 168
RESAMPLES = 5000
SEED = 20260728
EXPECTED_ZIP = {
    "BTC-USDT": "e9bdc2cee531f0b71539a6f4c2b306f2ae702e64bbbe8443ec16bf69c558147a",
    "ETH-USDT": "1f865024ae9d3ce7aa51bfe72bbab054b0377eef01780c75f60f6e8aa2cdc51e",
}
EXOGENOUS = {"BTC-USDT": "ETH-USDT", "ETH-USDT": "BTC-USDT"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_manifest(root: Path) -> None:
    rows = (root / "artifact-manifest.sha256").read_text().splitlines()
    if len(rows) != 13:
        raise ValueError(f"expected 13 manifest rows, got {len(rows)}")
    for row in rows:
        expected, relative = row.split("  ", 1)
        actual = sha256(root / relative)
        if actual != expected:
            raise ValueError(f"manifest mismatch: {relative}")


def load_market(root: Path, market: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    snapshot = pd.read_csv(root / "snapshot" / f"okx-{market}-1H.csv")
    oos = pd.read_csv(root / "walk_forward_returns.csv")
    for label, frame in (("snapshot", snapshot), ("oos", oos)):
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
        if frame["timestamp"].duplicated().any() or not frame["timestamp"].is_monotonic_increasing:
            raise ValueError(f"{market} {label}: invalid chronology")
        if not (frame["timestamp"].diff().dropna() == pd.Timedelta(hours=1)).all():
            raise ValueError(f"{market} {label}: hourly gap")
    if not (snapshot["confirm"] == 1).all():
        raise ValueError(f"{market}: unconfirmed bar")
    if len(oos) != 25920 or oos["fold"].nunique() != 12:
        raise ValueError(f"{market}: unexpected OOS shape")
    snapshot["asset_return"] = snapshot["close"].pct_change()
    aligned = snapshot.set_index("timestamp").loc[oos["timestamp"], "asset_return"].to_numpy()
    if np.nanmax(np.abs(aligned - oos["asset_return"].to_numpy())) > 1e-12:
        raise ValueError(f"{market}: return reconstruction mismatch")
    return snapshot, oos


def jump_feature(snapshot: pd.DataFrame) -> pd.DataFrame:
    returns = snapshot["asset_return"].astype(float)
    q01 = returns.shift(1).rolling(WINDOW, min_periods=WINDOW).quantile(QUANTILE)
    return pd.DataFrame(
        {
            "timestamp": snapshot["timestamp"],
            "q01": q01,
            "event": (returns < q01) & (returns < 0) & q01.notna(),
        }
    )


def strategy_metrics(
    returns: np.ndarray,
    turnover: np.ndarray,
    position: np.ndarray,
) -> dict[str, float | int]:
    nav = np.cumprod(1.0 + returns)
    total_return = float(nav[-1] - 1.0)
    annualized_mean = float(np.mean(returns) * HOURS_PER_YEAR)
    annualized_volatility = float(np.std(returns, ddof=0) * math.sqrt(HOURS_PER_YEAR))
    sharpe = annualized_mean / annualized_volatility
    peak = np.maximum.accumulate(nav)
    max_drawdown = float((nav / peak - 1.0).min())
    years = len(returns) / HOURS_PER_YEAR
    cagr = float(nav[-1] ** (1.0 / years) - 1.0)
    turnover_sum = float(turnover.sum())
    return {
        "net_total_return": total_return,
        "cagr": cagr,
        "sharpe": float(sharpe),
        "max_drawdown": max_drawdown,
        "annualized_turnover": float(turnover.mean() * HOURS_PER_YEAR),
        "fee_sum": float(FEE * turnover_sum),
        "edge_per_turnover_bps": float(10000.0 * returns.sum() / turnover_sum),
        "adjustment_count": int(np.count_nonzero(turnover > 1e-15)),
        "time_in_cash": float(np.mean(np.abs(position) <= 1e-15)),
    }


def candidate(oos: pd.DataFrame, event: pd.Series) -> pd.DataFrame:
    gate = (~event.shift(1, fill_value=False)).astype(float).to_numpy()
    position = oos["position"].to_numpy(dtype=float) * gate
    turnover = np.empty_like(position)
    turnover[0] = abs(position[0])
    turnover[1:] = np.abs(np.diff(position))
    gross = position * oos["asset_return"].to_numpy(dtype=float)
    net = gross - FEE * turnover
    return pd.DataFrame(
        {
            "fold": oos["fold"],
            "position": position,
            "turnover": turnover,
            "strategy_return": net,
        }
    )


def sharpe(returns: np.ndarray) -> float:
    return float(np.mean(returns) / np.std(returns, ddof=0) * math.sqrt(HOURS_PER_YEAR))


def bootstrap_indices(length: int, rng: np.random.Generator) -> np.ndarray:
    output = [np.array([0], dtype=int)]
    remaining = length - 1
    while remaining > 0:
        max_start = max(0, length - 1 - BLOCK)
        start = int(rng.integers(0, max_start + 1))
        take = min(BLOCK, length - 1 - start, remaining)
        output.append(1 + np.arange(start, start + take))
        remaining -= take
    return np.concatenate(output)


def paired_bootstrap(
    base: pd.DataFrame,
    alt: pd.DataFrame,
    rng: np.random.Generator,
) -> dict[str, list[float] | float]:
    folds = base["fold"].to_numpy(dtype=int)
    fold_rows = [np.flatnonzero(folds == fold) for fold in np.unique(folds)]
    base_return = base["strategy_return"].to_numpy(dtype=float)
    alt_return = alt["strategy_return"].to_numpy(dtype=float)
    base_turnover = base["turnover"].to_numpy(dtype=float)
    alt_turnover = alt["turnover"].to_numpy(dtype=float)
    sharpe_delta = np.empty(RESAMPLES)
    edge_delta = np.empty(RESAMPLES)
    for draw in range(RESAMPLES):
        index = np.concatenate([rows[bootstrap_indices(len(rows), rng)] for rows in fold_rows])
        br, ar = base_return[index], alt_return[index]
        bt, at = base_turnover[index].sum(), alt_turnover[index].sum()
        sharpe_delta[draw] = sharpe(ar) - sharpe(br)
        edge_delta[draw] = 10000.0 * ar.sum() / at - 10000.0 * br.sum() / bt
    observed_sharpe = sharpe(alt_return) - sharpe(base_return)
    observed_edge = (
        10000.0 * alt_return.sum() / alt_turnover.sum()
        - 10000.0 * base_return.sum() / base_turnover.sum()
    )

    def basic_ci(samples: np.ndarray, observed: float) -> list[float]:
        lo, hi = np.quantile(samples, [0.025, 0.975])
        return [float(2 * observed - hi), float(2 * observed - lo)]

    def lower(samples: np.ndarray, observed: float) -> float:
        return float(observed - np.quantile(samples - observed, 0.95))

    return {
        "sharpe_delta": float(observed_sharpe),
        "sharpe_basic_95_ci": basic_ci(sharpe_delta, observed_sharpe),
        "sharpe_one_sided_95_lower": lower(sharpe_delta, observed_sharpe),
        "edge_delta_bps": float(observed_edge),
        "edge_basic_95_ci": basic_ci(edge_delta, observed_edge),
        "edge_one_sided_95_lower": lower(edge_delta, observed_edge),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--btc-artifact-dir", type=Path, required=True)
    parser.add_argument("--eth-artifact-dir", type=Path, required=True)
    parser.add_argument("--btc-zip", type=Path, required=True)
    parser.add_argument("--eth-zip", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    roots = {"BTC-USDT": args.btc_artifact_dir, "ETH-USDT": args.eth_artifact_dir}
    zips = {"BTC-USDT": args.btc_zip, "ETH-USDT": args.eth_zip}
    snapshots: dict[str, pd.DataFrame] = {}
    oos: dict[str, pd.DataFrame] = {}
    for market in roots:
        if sha256(zips[market]) != EXPECTED_ZIP[market]:
            raise ValueError(f"{market}: ZIP digest mismatch")
        validate_manifest(roots[market])
        snapshots[market], oos[market] = load_market(roots[market], market)
    if not oos["BTC-USDT"]["timestamp"].equals(oos["ETH-USDT"]["timestamp"]):
        raise ValueError("unaligned OOS timestamps")

    features = {market: jump_feature(snapshot) for market, snapshot in snapshots.items()}
    rng = np.random.default_rng(SEED)
    result: dict[str, object] = {
        "family_id": "cross-market-jump-contagion-gate-v1",
        "parameters": {"lookback_hours": WINDOW, "quantile": QUANTILE, "fee": FEE},
        "markets": {},
    }
    for target, exogenous in EXOGENOUS.items():
        target_oos = oos[target]
        aligned_feature = features[exogenous].set_index("timestamp").loc[target_oos["timestamp"]]
        event = pd.Series(aligned_feature["event"].to_numpy(), index=target_oos.index)
        base = pd.DataFrame(
            {
                "fold": target_oos["fold"],
                "position": target_oos["position"],
                "turnover": target_oos["turnover"],
                "strategy_return": target_oos["strategy_return"],
            }
        )
        alt = candidate(target_oos, event)
        base_metrics = strategy_metrics(
            base["strategy_return"].to_numpy(),
            base["turnover"].to_numpy(),
            base["position"].to_numpy(),
        )
        alt_metrics = strategy_metrics(
            alt["strategy_return"].to_numpy(),
            alt["turnover"].to_numpy(),
            alt["position"].to_numpy(),
        )
        next_return = target_oos["asset_return"].to_numpy()[1:]
        event_for_next = event.to_numpy()[:-1]
        result["markets"][target] = {
            "exogenous_market": exogenous,
            "feature_missing_hours": int(aligned_feature["q01"].isna().sum()),
            "event_count": int(event.sum()),
            "event_occupancy": float(event.mean()),
            "event_minus_non_event_next_hour_bps": float(
                10000.0
                * (next_return[event_for_next].mean() - next_return[~event_for_next].mean())
            ),
            "baseline": base_metrics,
            "candidate": alt_metrics,
            "bootstrap": paired_bootstrap(base, alt, rng),
        }
    canonical = json.dumps(
        result,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    result["content_sha256"] = hashlib.sha256(canonical).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
