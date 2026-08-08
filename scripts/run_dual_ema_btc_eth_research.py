from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ANNUALIZATION_HOURS = 8760
FAST_SPAN = 720
SLOW_SPAN = 2160
ALPHA_FAST = 2.0 / (FAST_SPAN + 1.0)
ALPHA_SLOW = 2.0 / (SLOW_SPAN + 1.0)
FEE_ONE_WAY = 0.0005
TRAIN_START = 4320
TRAIN_END = 17520
OOS_START = 17520
OOS_END = 43440
BLOCK_HOURS = 168
BOOTSTRAP_RESAMPLES = 5000
BOOTSTRAP_SEEDS = {"BTC-USDT": 2026080822, "ETH-USDT": 2026080823}
SOURCE_ARTIFACT_IDS = {"BTC-USDT": 8704977298, "ETH-USDT": 8704978112}
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
    actual_sha256 = _sha256(path)
    if actual_sha256 != EXPECTED_SHA256[instrument]:
        raise ValueError(f"unexpected {instrument} CSV SHA-256: {actual_sha256}")

    frame = pd.read_csv(path, nrows=TRAIN_END + 1)
    required = {"timestamp", "open", "high", "low", "close", "confirm"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"missing required columns: {sorted(missing)}")
    if len(frame) != TRAIN_END + 1:
        raise ValueError("training prefix plus exclusive-end next-open row is incomplete")

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
    if not (frame["low"] <= frame[["open", "close"]].min(axis=1)).all():
        raise ValueError("low must not exceed open/close")
    if not (frame["high"] >= frame[["open", "close"]].max(axis=1)).all():
        raise ValueError("high must not be below open/close")

    if frame["timestamp"].iloc[0] != pd.Timestamp("2021-07-24T00:00:00Z"):
        raise ValueError("unexpected source start timestamp")
    if frame["timestamp"].iloc[TRAIN_END] != pd.Timestamp("2023-07-24T00:00:00Z"):
        raise ValueError("unexpected training next-open boundary")
    return frame


def _ema_paths(close: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    log_close = np.log(close.astype(float))
    fast = np.empty(len(log_close), dtype=float)
    slow = np.empty(len(log_close), dtype=float)
    fast[0] = slow[0] = log_close[0]
    for index in range(1, len(log_close)):
        fast[index] = ALPHA_FAST * log_close[index] + (1.0 - ALPHA_FAST) * fast[index - 1]
        slow[index] = ALPHA_SLOW * log_close[index] + (1.0 - ALPHA_SLOW) * slow[index - 1]
    return fast, slow


def _daily_ema_targets(
    frame: pd.DataFrame,
    fast: np.ndarray,
    slow: np.ndarray,
    start: int,
    end: int,
) -> dict[int, int]:
    targets: dict[int, int] = {}
    for anchor in range(start, end):
        if frame["timestamp"].iloc[anchor].hour == 0:
            targets[anchor] = int(fast[anchor - 1] - slow[anchor - 1] > 0.0)
    return targets


def _daily_e2160_targets(frame: pd.DataFrame, start: int, end: int) -> dict[int, int]:
    closes = frame["close"].to_numpy()
    targets: dict[int, int] = {}
    for anchor in range(start, end):
        if frame["timestamp"].iloc[anchor].hour == 0:
            targets[anchor] = int(closes[anchor - 1] > closes[anchor - 2161])
    return targets


def _metrics(
    returns: np.ndarray,
    positions: np.ndarray,
    turnover: np.ndarray,
    fees: np.ndarray,
    transition_count: int,
) -> dict[str, float | int]:
    mean_return = float(returns.mean())
    standard_deviation = float(returns.std(ddof=0))
    annualized_mean = mean_return * ANNUALIZATION_HOURS
    sharpe = (
        mean_return / standard_deviation * math.sqrt(ANNUALIZATION_HOURS)
        if standard_deviation > 0.0
        else 0.0
    )
    nav = np.concatenate(([1.0], np.cumprod(1.0 + returns)))
    running_peak = np.maximum.accumulate(nav)
    max_drawdown = float(np.min(nav / running_peak - 1.0))
    annualized_turnover = float(turnover.mean() * ANNUALIZATION_HOURS)
    edge_per_turnover = (
        annualized_mean / annualized_turnover * 10000.0 if annualized_turnover > 0.0 else 0.0
    )
    return {
        "observations": int(len(returns)),
        "net_total_return": float(np.prod(1.0 + returns) - 1.0),
        "annualized_arithmetic_mean": annualized_mean,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
        "average_exposure": float(positions.mean()),
        "turnover_sum": float(turnover.sum()),
        "annualized_turnover": annualized_turnover,
        "transition_count": int(transition_count),
        "modeled_fee_drag_sum": float(fees.sum()),
        "net_edge_per_turnover_bps": edge_per_turnover,
    }


def _evaluate_targets(
    frame: pd.DataFrame,
    targets: dict[int, int],
    start: int,
    end: int,
    *,
    extra_delay_hours: int = 0,
) -> tuple[dict[str, float | int], np.ndarray, np.ndarray, np.ndarray]:
    if start < SLOW_SPAN or end >= len(frame):
        raise ValueError("segment lacks required history or exclusive-end next-open row")

    scheduled: dict[int, list[int]] = {}
    previous_target = 0
    for anchor in sorted(targets):
        if not start <= anchor < end:
            continue
        target = int(targets[anchor])
        if target != previous_target:
            scheduled.setdefault(anchor + extra_delay_hours, []).append(target)
        previous_target = target

    opens = frame["open"].to_numpy()
    position = 0
    returns: list[float] = []
    positions: list[float] = []
    turnover: list[float] = []
    fees: list[float] = []
    transition_count = 0

    for bar in range(start, end):
        bar_turnover = 0.0
        for target in scheduled.get(bar, []):
            change = abs(target - position)
            if change:
                bar_turnover += float(change)
                transition_count += 1
                position = target

        asset_return = float(opens[bar + 1] / opens[bar] - 1.0)
        gross_return = float(position * asset_return)
        fee = FEE_ONE_WAY * bar_turnover

        if bar == end - 1 and position != 0:
            bar_turnover += float(abs(position))
            fee += FEE_ONE_WAY * abs(position)
            transition_count += 1

        returns.append(gross_return - fee)
        positions.append(float(position))
        turnover.append(bar_turnover)
        fees.append(fee)

    return_array = np.asarray(returns, dtype=float)
    position_array = np.asarray(positions, dtype=float)
    turnover_array = np.asarray(turnover, dtype=float)
    fee_array = np.asarray(fees, dtype=float)
    result = _metrics(
        return_array,
        position_array,
        turnover_array,
        fee_array,
        transition_count,
    )
    return result, return_array, position_array, turnover_array


def _evaluate_candidate(
    frame: pd.DataFrame,
    fast: np.ndarray,
    slow: np.ndarray,
    start: int,
    end: int,
    *,
    extra_delay_hours: int = 0,
) -> tuple[dict[str, float | int], np.ndarray, np.ndarray, np.ndarray]:
    targets = _daily_ema_targets(frame, fast, slow, start, end)
    return _evaluate_targets(
        frame,
        targets,
        start,
        end,
        extra_delay_hours=extra_delay_hours,
    )


def _moving_block_bootstrap(returns: np.ndarray, seed: int) -> dict[str, float | int]:
    rng = np.random.default_rng(seed)
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
        mean_return = float(sample.mean())
        standard_deviation = float(sample.std(ddof=0))
        means[draw] = mean_return * ANNUALIZATION_HOURS
        sharpes[draw] = (
            mean_return / standard_deviation * math.sqrt(ANNUALIZATION_HOURS)
            if standard_deviation > 0.0
            else 0.0
        )

    return {
        "resamples": BOOTSTRAP_RESAMPLES,
        "block_hours": BLOCK_HOURS,
        "seed": seed,
        "annualized_mean_q025": float(np.quantile(means, 0.025)),
        "annualized_mean_median": float(np.quantile(means, 0.5)),
        "sharpe_q025": float(np.quantile(sharpes, 0.025)),
        "sharpe_median": float(np.quantile(sharpes, 0.5)),
    }


def _training_evidence(frame: pd.DataFrame, instrument: str) -> dict[str, object]:
    fast, slow = _ema_paths(frame["close"].to_numpy())
    training, returns, positions, turnover = _evaluate_candidate(
        frame,
        fast,
        slow,
        TRAIN_START,
        TRAIN_END,
    )
    delayed, _, _, _ = _evaluate_candidate(
        frame,
        fast,
        slow,
        TRAIN_START,
        TRAIN_END,
        extra_delay_hours=1,
    )
    e2160, _, _, _ = _evaluate_targets(
        frame,
        _daily_e2160_targets(frame, TRAIN_START, TRAIN_END),
        TRAIN_START,
        TRAIN_END,
    )
    always_long, _, _, _ = _evaluate_targets(
        frame,
        {TRAIN_START: 1},
        TRAIN_START,
        TRAIN_END,
    )

    folds: list[dict[str, float | int]] = []
    for fold_index in range(6):
        start = TRAIN_START + fold_index * 2160
        end = start + 2160
        fold_metrics, _, _, _ = _evaluate_candidate(frame, fast, slow, start, end)
        folds.append({"fold": fold_index + 1, "start": start, "end": end, **fold_metrics})

    calendar_slices: list[dict[str, float | int]] = []
    timestamps = frame["timestamp"]
    represented_years = sorted(set(timestamps.iloc[TRAIN_START:TRAIN_END].dt.year.tolist()))
    for year in represented_years:
        mask = (timestamps.iloc[TRAIN_START:TRAIN_END].dt.year == year).to_numpy()
        indexes = np.flatnonzero(mask)
        start = TRAIN_START + int(indexes[0])
        end = TRAIN_START + int(indexes[-1]) + 1
        year_metrics, _, _, _ = _evaluate_candidate(frame, fast, slow, start, end)
        calendar_slices.append({"year": int(year), "start": start, "end": end, **year_metrics})

    positive_fold_returns = [
        float(row["net_total_return"])
        for row in folds
        if float(row["net_total_return"]) > 0.0
    ]
    positive_fold_concentration = (
        max(positive_fold_returns) / sum(positive_fold_returns)
        if positive_fold_returns
        else None
    )
    bootstrap = _moving_block_bootstrap(returns, BOOTSTRAP_SEEDS[instrument])
    positive_calendar_count = sum(
        float(row["net_total_return"]) > 0.0 for row in calendar_slices
    )
    gates = {
        "source_chronology_next_open_ema_finite_state": True,
        "positive_training_return_and_sharpe": (
            float(training["net_total_return"]) > 0.0 and float(training["sharpe"]) > 0.0
        ),
        "max_drawdown_above_minus_50pct": float(training["max_drawdown"]) > -0.5,
        "edge_per_turnover_above_10bps": float(training["net_edge_per_turnover_bps"]) > 10.0,
        "at_least_4_of_6_positive_folds": (
            sum(float(row["net_total_return"]) > 0.0 for row in folds) >= 4
        ),
        "at_least_2_positive_represented_calendar_slices": positive_calendar_count >= 2,
        "positive_fold_concentration_at_most_60pct": (
            positive_fold_concentration is not None and positive_fold_concentration <= 0.60
        ),
        "moving_block_q025_mean_and_sharpe_positive": (
            float(bootstrap["annualized_mean_q025"]) > 0.0
            and float(bootstrap["sharpe_q025"]) > 0.0
        ),
        "extra_1h_delay_positive_return_sharpe_edge": (
            float(delayed["net_total_return"]) > 0.0
            and float(delayed["sharpe"]) > 0.0
            and float(delayed["net_edge_per_turnover_bps"]) > 0.0
        ),
    }
    return {
        "training": training,
        "descriptive_e2160_training": e2160,
        "always_long_training": always_long,
        "delay_plus_1h": delayed,
        "folds": folds,
        "positive_fold_count": sum(float(row["net_total_return"]) > 0.0 for row in folds),
        "positive_fold_concentration": positive_fold_concentration,
        "calendar_slices": calendar_slices,
        "represented_calendar_slice_count": len(calendar_slices),
        "positive_calendar_slice_count": positive_calendar_count,
        "moving_block_bootstrap": bootstrap,
        "gates": gates,
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

    paths = {"BTC-USDT": args.btc_csv, "ETH-USDT": args.eth_csv}
    markets = {
        instrument: _training_evidence(_load_training_prefix(path, instrument), instrument)
        for instrument, path in paths.items()
    }
    bilateral_training_pass = all(
        all(bool(value) for value in market["gates"].values()) for market in markets.values()
    )
    if bilateral_training_pass:
        raise RuntimeError(
            "bilateral training unexpectedly passed; sealed OOS requires a separately "
            "reviewed access step"
        )

    evidence = {
        "family_id": (
            "causal-own-price-dual-ema-distributed-memory-trend-"
            "canonical-replication-1h-v1"
        ),
        "issue": 1120,
        "candidate_count": 1,
        "parameter_grid_count": 0,
        "fee_one_way": FEE_ONE_WAY,
        "ema_fast_span_hours": FAST_SPAN,
        "ema_slow_span_hours": SLOW_SPAN,
        "training": [TRAIN_START, TRAIN_END],
        "development_oos": [OOS_START, OOS_END],
        "development_oos_accessed": False,
        "full_metrics": None,
        "bilateral_training_pass": bilateral_training_pass,
        "source_artifact_ids": SOURCE_ARTIFACT_IDS,
        "source_csv_sha256": EXPECTED_SHA256,
        "markets": markets,
        "calendar_gate_note": (
            "The frozen training interval intersects calendar years 2022 and 2023 only. "
            "The frozen threshold is operationalized literally as at least two positive "
            "represented restarted-from-cash calendar slices; both targets have only one."
        ),
        "verdict": (
            "reject_causal_own_price_dual_ema_distributed_memory_trend_"
            "canonical_replication_training_1h_v1"
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
