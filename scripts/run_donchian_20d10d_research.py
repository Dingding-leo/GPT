from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ANNUALIZATION = 8760
ENTRY_HOURS = 480
EXIT_HOURS = 240
FEE_ONE_WAY = 0.0005
TRAIN_START = 2880
TRAIN_END = 17520
BLOCK_HOURS = 168
BOOTSTRAP_RESAMPLES = 5000
BOOTSTRAP_SEED = 2026080821
SOURCE_ARTIFACT_ID = {"BTC-USDT": 8704977298, "ETH-USDT": 8704978112}
EXPECTED_SHA256 = {
    "BTC-USDT": "92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9",
    "ETH-USDT": "2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_training_prefix(path: Path, instrument: str) -> pd.DataFrame:
    actual_sha = _sha256(path)
    if actual_sha != EXPECTED_SHA256[instrument]:
        raise ValueError(f"unexpected {instrument} CSV SHA-256: {actual_sha}")

    frame = pd.read_csv(path, nrows=TRAIN_END + 1)
    required = {"timestamp", "open", "high", "low", "close", "confirm"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"missing required columns: {sorted(missing)}")
    if len(frame) != TRAIN_END + 1:
        raise ValueError("training prefix plus next-open boundary is incomplete")

    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    if not frame["timestamp"].is_unique or not frame["timestamp"].is_monotonic_increasing:
        raise ValueError("timestamps must be unique and strictly increasing")
    if not (frame["timestamp"].diff().dropna() == pd.Timedelta(hours=1)).all():
        raise ValueError("timestamps must be contiguous native 1H bars")
    if not (pd.to_numeric(frame["confirm"], errors="raise") == 1).all():
        raise ValueError("all parsed rows must be provider-confirmed completed bars")

    for column in ("open", "high", "low", "close"):
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype(float)
    ohlc = frame[["open", "high", "low", "close"]].to_numpy()
    if not np.isfinite(ohlc).all() or not (ohlc > 0.0).all():
        raise ValueError("OHLC must be finite and positive")
    if not ((frame["low"] <= frame[["open", "close"]].min(axis=1)).all()):
        raise ValueError("low must not exceed open/close")
    if not ((frame["high"] >= frame[["open", "close"]].max(axis=1)).all()):
        raise ValueError("high must not be below open/close")
    expected_start = pd.Timestamp("2021-07-24T00:00:00Z")
    expected_boundary = pd.Timestamp("2023-07-24T00:00:00Z")
    if frame["timestamp"].iloc[0] != expected_start:
        raise ValueError("unexpected source start timestamp")
    if frame["timestamp"].iloc[TRAIN_END] != expected_boundary:
        raise ValueError("unexpected training next-open boundary")
    return frame


def _desired_targets(frame: pd.DataFrame, start: int, end: int) -> dict[int, int]:
    highs = frame["high"].to_numpy()
    lows = frame["low"].to_numpy()
    closes = frame["close"].to_numpy()
    state = 0
    targets: dict[int, int] = {}
    for bar in range(start, end):
        entry_high = float(np.max(highs[bar - ENTRY_HOURS : bar]))
        exit_low = float(np.min(lows[bar - EXIT_HOURS : bar]))
        if state == 0 and closes[bar] > entry_high:
            state = 1
        elif state == 1 and closes[bar] < exit_low:
            state = 0
        targets[bar] = state
    return targets


def _metrics(
    returns: np.ndarray,
    position: np.ndarray,
    turnover: np.ndarray,
    fees: np.ndarray,
    transition_count: int,
) -> dict[str, float | int]:
    mean = float(returns.mean())
    std = float(returns.std(ddof=0))
    annualized_mean = mean * ANNUALIZATION
    sharpe = mean / std * math.sqrt(ANNUALIZATION) if std > 0.0 else 0.0
    nav = np.concatenate(([1.0], np.cumprod(1.0 + returns)))
    running_peak = np.maximum.accumulate(nav)
    max_drawdown = float(np.min(nav / running_peak - 1.0))
    annualized_turnover = float(turnover.mean() * ANNUALIZATION)
    edge_per_turnover = (
        annualized_mean / annualized_turnover * 10000.0 if annualized_turnover > 0.0 else 0.0
    )
    return {
        "observations": int(len(returns)),
        "net_total_return": float(np.prod(1.0 + returns) - 1.0),
        "annualized_arithmetic_mean": annualized_mean,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
        "average_exposure": float(position.mean()),
        "turnover_sum": float(turnover.sum()),
        "annualized_turnover": annualized_turnover,
        "transition_count": int(transition_count),
        "modeled_fee_drag_sum": float(fees.sum()),
        "net_edge_per_turnover_bps": edge_per_turnover,
    }


def _evaluate_segment(
    frame: pd.DataFrame,
    start: int,
    end: int,
    *,
    extra_delay_hours: int = 0,
) -> tuple[dict[str, float | int], np.ndarray, np.ndarray, np.ndarray]:
    if start < ENTRY_HOURS or end >= len(frame):
        raise ValueError("segment lacks required lookback or next-open boundary")

    targets = _desired_targets(frame, start, end)
    scheduled: dict[int, list[int]] = {}
    previous_target = 0
    for bar in range(start, end):
        target = targets[bar]
        if target != previous_target:
            execute_at = bar + 1 + extra_delay_hours
            scheduled.setdefault(execute_at, []).append(target)
        previous_target = target

    opens = frame["open"].to_numpy()
    position_now = 0
    returns: list[float] = []
    positions: list[float] = []
    turnovers: list[float] = []
    fees: list[float] = []
    transition_count = 0

    for bar in range(start, end):
        turnover = 0.0
        for new_target in scheduled.get(bar, []):
            change = abs(new_target - position_now)
            if change:
                turnover += float(change)
                transition_count += 1
                position_now = new_target

        asset_return = float(opens[bar + 1] / opens[bar] - 1.0)
        gross_return = float(position_now * asset_return)
        fee = FEE_ONE_WAY * turnover

        if bar == end - 1 and position_now != 0:
            turnover += float(abs(position_now))
            fee += FEE_ONE_WAY * abs(position_now)
            transition_count += 1

        returns.append(gross_return - fee)
        positions.append(float(position_now))
        turnovers.append(turnover)
        fees.append(fee)

    returns_array = np.asarray(returns, dtype=float)
    position_array = np.asarray(positions, dtype=float)
    turnover_array = np.asarray(turnovers, dtype=float)
    fee_array = np.asarray(fees, dtype=float)
    result = _metrics(
        returns_array,
        position_array,
        turnover_array,
        fee_array,
        transition_count,
    )
    return result, returns_array, position_array, turnover_array


def _moving_block_bootstrap(returns: np.ndarray) -> dict[str, float | int]:
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    observations = len(returns)
    blocks_per_draw = math.ceil(observations / BLOCK_HOURS)
    max_start = observations - BLOCK_HOURS
    means = np.empty(BOOTSTRAP_RESAMPLES, dtype=float)
    sharpes = np.empty(BOOTSTRAP_RESAMPLES, dtype=float)

    for draw in range(BOOTSTRAP_RESAMPLES):
        starts = rng.integers(0, max_start + 1, size=blocks_per_draw)
        indexes = np.concatenate(
            [np.arange(start, start + BLOCK_HOURS, dtype=int) for start in starts]
        )[:observations]
        sample = returns[indexes]
        mean = float(sample.mean())
        std = float(sample.std(ddof=0))
        means[draw] = mean * ANNUALIZATION
        sharpes[draw] = mean / std * math.sqrt(ANNUALIZATION) if std > 0.0 else 0.0

    return {
        "resamples": BOOTSTRAP_RESAMPLES,
        "block_hours": BLOCK_HOURS,
        "seed": BOOTSTRAP_SEED,
        "annualized_mean_q025": float(np.quantile(means, 0.025)),
        "annualized_mean_q05": float(np.quantile(means, 0.05)),
        "annualized_mean_median": float(np.quantile(means, 0.5)),
        "sharpe_q025": float(np.quantile(sharpes, 0.025)),
        "sharpe_q05": float(np.quantile(sharpes, 0.05)),
        "sharpe_median": float(np.quantile(sharpes, 0.5)),
    }


def _folds(frame: pd.DataFrame) -> list[dict[str, float | int]]:
    rows: list[dict[str, float | int]] = []
    for fold in range(6):
        start = TRAIN_START + fold * 2160
        end = start + 2160
        metrics, _, _, _ = _evaluate_segment(frame, start, end)
        rows.append({"fold": fold + 1, "start": start, "end": end, **metrics})
    return rows


def _end_anchored_fold_diagnostic(frame: pd.DataFrame) -> dict[str, object]:
    first = TRAIN_END - 6 * 2160
    returns: list[float] = []
    for fold in range(6):
        start = first + fold * 2160
        end = start + 2160
        metrics, _, _, _ = _evaluate_segment(frame, start, end)
        returns.append(float(metrics["net_total_return"]))
    return {
        "classification": "nonselective_fold_anchor_ambiguity_diagnostic_only",
        "positive_folds": sum(value > 0.0 for value in returns),
        "returns": returns,
    }


def _years(frame: pd.DataFrame) -> list[dict[str, float | int]]:
    timestamps = frame["timestamp"]
    rows: list[dict[str, float | int]] = []
    for year in (2021, 2022, 2023):
        mask = (timestamps.iloc[TRAIN_START:TRAIN_END].dt.year == year).to_numpy()
        indexes = np.flatnonzero(mask)
        if not len(indexes):
            continue
        start = TRAIN_START + int(indexes[0])
        end = TRAIN_START + int(indexes[-1]) + 1
        metrics, _, _, _ = _evaluate_segment(frame, start, end)
        rows.append({"year": year, "start": start, "end": end, **metrics})
    return rows


def _market_evidence(frame: pd.DataFrame) -> dict[str, object]:
    training, returns, positions, turnover = _evaluate_segment(frame, TRAIN_START, TRAIN_END)
    delayed, _, _, _ = _evaluate_segment(
        frame,
        TRAIN_START,
        TRAIN_END,
        extra_delay_hours=1,
    )
    folds = _folds(frame)
    years = _years(frame)
    positive_fold_returns = [
        float(row["net_total_return"]) for row in folds if float(row["net_total_return"]) > 0.0
    ]
    concentration = (
        max(positive_fold_returns) / sum(positive_fold_returns)
        if positive_fold_returns
        else None
    )
    bootstrap = _moving_block_bootstrap(returns)
    gates = {
        "positive_return_and_sharpe": (
            float(training["net_total_return"]) > 0.0 and float(training["sharpe"]) > 0.0
        ),
        "max_drawdown_above_minus_50pct": float(training["max_drawdown"]) > -0.5,
        "edge_per_turnover_above_10bps": float(training["net_edge_per_turnover_bps"]) > 10.0,
        "at_least_4_of_6_positive_folds": sum(
            float(row["net_total_return"]) > 0.0 for row in folds
        )
        >= 4,
        "at_least_2_of_3_positive_years": sum(
            float(row["net_total_return"]) > 0.0 for row in years
        )
        >= 2,
        "positive_fold_concentration_at_most_60pct": (
            concentration is not None and concentration <= 0.60
        ),
        "moving_block_q025_mean_and_sharpe_positive": (
            float(bootstrap["annualized_mean_q025"]) > 0.0
            and float(bootstrap["sharpe_q025"]) > 0.0
        ),
        "extra_1h_delay_positive_return_and_sharpe": (
            float(delayed["net_total_return"]) > 0.0 and float(delayed["sharpe"]) > 0.0
        ),
    }
    full_gate_vector = {
        "source_chronology_next_open_fee_terminal_liquidation": True,
        **gates,
        "prefix_invariant_by_bounded_prefix_reader": True,
        "no_posthoc_market_fold_year_or_trade_deletion_ranking": True,
    }
    return {
        "training": training,
        "delay_plus_1h": delayed,
        "folds": folds,
        "positive_fold_count": sum(float(row["net_total_return"]) > 0.0 for row in folds),
        "positive_fold_concentration": concentration,
        "years": years,
        "positive_year_count": sum(float(row["net_total_return"]) > 0.0 for row in years),
        "moving_block_bootstrap": bootstrap,
        "fold_anchor_sensitivity": _end_anchored_fold_diagnostic(frame),
        "gates": full_gate_vector,
        "path_hashes": {
            "returns_float64_sha256": hashlib.sha256(returns.tobytes()).hexdigest(),
            "positions_float64_sha256": hashlib.sha256(positions.tobytes()).hexdigest(),
            "turnover_float64_sha256": hashlib.sha256(turnover.tobytes()).hexdigest(),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--btc-csv", type=Path, required=True)
    parser.add_argument("--eth-csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    markets = {
        "BTC-USDT": _market_evidence(_load_training_prefix(args.btc_csv, "BTC-USDT")),
        "ETH-USDT": _market_evidence(_load_training_prefix(args.eth_csv, "ETH-USDT")),
    }
    all_training_gates_pass = all(
        all(bool(value) for value in market["gates"].values()) for market in markets.values()
    )
    evidence = {
        "family_id": "causal-own-price-donchian-20d10d-long-cash-1h-v1",
        "issue": 1117,
        "candidate_count": 1,
        "parameter_grid_count": 0,
        "fee_one_way": FEE_ONE_WAY,
        "annualization_hours": ANNUALIZATION,
        "training": [TRAIN_START, TRAIN_END],
        "oos": [17520, 43440],
        "oos_accessed": False,
        "full_metrics": None,
        "oos_metrics": None,
        "source_artifacts": {
            instrument: {
                "artifact_id": SOURCE_ARTIFACT_ID[instrument],
                "csv_sha256": EXPECTED_SHA256[instrument],
                "parsed_training_rows_plus_boundary": TRAIN_END + 1,
            }
            for instrument in EXPECTED_SHA256
        },
        "descriptive_b1_training_reference": {
            "BTC-USDT": {"net_total_return": -0.41290619, "sharpe": -0.840267},
            "ETH-USDT": {"net_total_return": -0.40588784, "sharpe": -0.584178},
        },
        "markets": markets,
        "bilateral_training_pass": all_training_gates_pass,
        "verdict": (
            "support_training_gate_only_open_frozen_oos"
            if all_training_gates_pass
            else "reject_causal_own_price_donchian_20d10d_training_economics_1h_v1"
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, sort_keys=True, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
