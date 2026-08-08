from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ANNUALIZATION = 8760
FAST_SPAN = 720
SLOW_SPAN = 2160
ALPHA_FAST = 2.0 / (FAST_SPAN + 1.0)
ALPHA_SLOW = 2.0 / (SLOW_SPAN + 1.0)
WARMUP = 4320
TRAIN_START = 4320
TRAIN_END = 17520
FEE_ONE_WAY = 0.0005
BLOCK_HOURS = 168
BOOTSTRAP_RESAMPLES = 5000
BOOTSTRAP_SEEDS = {"BTC-USDT": 2026080822, "ETH-USDT": 2026080823}
SOURCE_ARTIFACT_ID = {"BTC-USDT": 8704977298, "ETH-USDT": 8704978112}
EXPECTED_SHA256 = {
    "BTC-USDT": "92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9",
    "ETH-USDT": "2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_training_prefix(path: Path, instrument: str) -> pd.DataFrame:
    actual = sha256(path)
    if actual != EXPECTED_SHA256[instrument]:
        raise ValueError(f"unexpected {instrument} CSV SHA-256: {actual}")

    frame = pd.read_csv(path, nrows=TRAIN_END + 1)
    if len(frame) != TRAIN_END + 1:
        raise ValueError("training prefix plus exclusive-end next-open boundary is incomplete")

    required = {"timestamp", "open", "high", "low", "close", "confirm"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"missing required columns: {sorted(missing)}")

    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    if not frame["timestamp"].is_unique or not frame["timestamp"].is_monotonic_increasing:
        raise ValueError("timestamps must be unique and strictly increasing")
    if not (frame["timestamp"].diff().dropna() == pd.Timedelta(hours=1)).all():
        raise ValueError("timestamps must be contiguous native 1H bars")
    if not (pd.to_numeric(frame["confirm"], errors="raise") == 1).all():
        raise ValueError("all parsed rows must be completed provider bars")

    for column in ("open", "high", "low", "close"):
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype(float)
    ohlc = frame[["open", "high", "low", "close"]].to_numpy()
    if not np.isfinite(ohlc).all() or not (ohlc > 0.0).all():
        raise ValueError("OHLC must be finite and positive")
    if not (frame["low"] <= frame[["open", "close"]].min(axis=1)).all():
        raise ValueError("invalid low")
    if not (frame["high"] >= frame[["open", "close"]].max(axis=1)).all():
        raise ValueError("invalid high")

    if frame["timestamp"].iloc[0] != pd.Timestamp("2021-07-24T00:00:00Z"):
        raise ValueError("unexpected source start")
    if frame["timestamp"].iloc[TRAIN_START] != pd.Timestamp("2022-01-20T00:00:00Z"):
        raise ValueError("unexpected training start")
    if frame["timestamp"].iloc[TRAIN_END] != pd.Timestamp("2023-07-24T00:00:00Z"):
        raise ValueError("unexpected training exclusive-end boundary")
    return frame


def ema_target_map(frame: pd.DataFrame) -> tuple[dict[int, int], dict[int, float]]:
    log_close = np.log(frame["close"].to_numpy())
    ema_fast = np.empty(len(frame), dtype=float)
    ema_slow = np.empty(len(frame), dtype=float)
    ema_fast[0] = log_close[0]
    ema_slow[0] = log_close[0]
    for row in range(1, len(frame)):
        ema_fast[row] = ALPHA_FAST * log_close[row] + (1.0 - ALPHA_FAST) * ema_fast[row - 1]
        ema_slow[row] = ALPHA_SLOW * log_close[row] + (1.0 - ALPHA_SLOW) * ema_slow[row - 1]

    targets: dict[int, int] = {}
    scores: dict[int, float] = {}
    for anchor in range(WARMUP, TRAIN_END):
        if frame["timestamp"].iloc[anchor].hour != 0:
            continue
        score = float(ema_fast[anchor - 1] - ema_slow[anchor - 1])
        scores[anchor] = score
        targets[anchor] = int(score > 0.0)
    return targets, scores


def e2160_target_map(frame: pd.DataFrame) -> dict[int, int]:
    close = frame["close"].to_numpy()
    targets: dict[int, int] = {}
    for anchor in range(WARMUP, TRAIN_END):
        if frame["timestamp"].iloc[anchor].hour == 0:
            targets[anchor] = int(close[anchor - 1] > close[anchor - 2161])
    return targets


def metrics(
    returns: np.ndarray,
    positions: np.ndarray,
    turnover: np.ndarray,
    fees: np.ndarray,
    transitions: int,
) -> dict[str, float | int | None]:
    mean = float(returns.mean())
    std = float(returns.std(ddof=0))
    annualized_mean = mean * ANNUALIZATION
    sharpe = mean / std * math.sqrt(ANNUALIZATION) if std > 0.0 else 0.0
    nav = np.concatenate(([1.0], np.cumprod(1.0 + returns)))
    peak = np.maximum.accumulate(nav)
    max_drawdown = float(np.min(nav / peak - 1.0))
    annualized_turnover = float(turnover.mean() * ANNUALIZATION)
    edge = annualized_mean / annualized_turnover * 10000.0 if annualized_turnover > 0.0 else None
    return {
        "observations": int(len(returns)),
        "net_total_return": float(np.prod(1.0 + returns) - 1.0),
        "annualized_arithmetic_mean": annualized_mean,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
        "average_exposure": float(positions.mean()),
        "turnover_sum": float(turnover.sum()),
        "annualized_turnover": annualized_turnover,
        "transition_count": int(transitions),
        "modeled_fee_drag_sum": float(fees.sum()),
        "net_edge_per_turnover_bps": edge,
    }


def evaluate_segment(
    frame: pd.DataFrame,
    target_map: dict[int, int],
    start: int,
    end: int,
    *,
    delay_hours: int = 0,
) -> tuple[dict[str, float | int | None], np.ndarray]:
    if end >= len(frame):
        raise ValueError("segment lacks exclusive-end next open")

    scheduled = {
        anchor + delay_hours: target
        for anchor, target in target_map.items()
        if start <= anchor < end
    }
    opens = frame["open"].to_numpy()
    position = 0
    returns: list[float] = []
    positions: list[float] = []
    turnover_rows: list[float] = []
    fees: list[float] = []
    transitions = 0

    for row in range(start, end):
        one_way_turnover = 0.0
        if row in scheduled:
            new_target = scheduled[row]
            change = abs(new_target - position)
            if change:
                one_way_turnover += float(change)
                transitions += 1
                position = new_target

        asset_return = float(opens[row + 1] / opens[row] - 1.0)
        fee = FEE_ONE_WAY * one_way_turnover
        net_return = float(position * asset_return - fee)

        if row == end - 1 and position != 0:
            one_way_turnover += float(abs(position))
            liquidation_fee = FEE_ONE_WAY * abs(position)
            fee += liquidation_fee
            net_return -= liquidation_fee
            transitions += 1

        returns.append(net_return)
        positions.append(float(position))
        turnover_rows.append(one_way_turnover)
        fees.append(fee)

    returns_array = np.asarray(returns, dtype=float)
    return metrics(
        returns_array,
        np.asarray(positions, dtype=float),
        np.asarray(turnover_rows, dtype=float),
        np.asarray(fees, dtype=float),
        transitions,
    ), returns_array


def folds(frame: pd.DataFrame, target_map: dict[int, int]) -> list[dict[str, float | int | None]]:
    rows: list[dict[str, float | int | None]] = []
    for fold in range(6):
        start = TRAIN_START + fold * 2160
        end = start + 2160
        result, _ = evaluate_segment(frame, target_map, start, end)
        rows.append({"fold": fold + 1, **result})
    return rows


def calendar_slices(frame: pd.DataFrame, target_map: dict[int, int]) -> list[dict[str, float | int | None]]:
    timestamps = frame["timestamp"]
    rows: list[dict[str, float | int | None]] = []
    represented = sorted(set(timestamps.iloc[TRAIN_START:TRAIN_END].dt.year))
    for year in represented:
        mask = (timestamps.iloc[TRAIN_START:TRAIN_END].dt.year == year).to_numpy()
        indexes = np.flatnonzero(mask)
        start = TRAIN_START + int(indexes[0])
        end = TRAIN_START + int(indexes[-1]) + 1
        result, _ = evaluate_segment(frame, target_map, start, end)
        rows.append({"year": int(year), "start": start, "end": end, **result})
    return rows


def moving_block_bootstrap(returns: np.ndarray, seed: int) -> dict[str, float | int]:
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
        mean = float(sample.mean())
        std = float(sample.std(ddof=0))
        means[draw] = mean * ANNUALIZATION
        sharpes[draw] = mean / std * math.sqrt(ANNUALIZATION) if std > 0.0 else 0.0

    return {
        "resamples": BOOTSTRAP_RESAMPLES,
        "block_hours": BLOCK_HOURS,
        "seed": seed,
        "annualized_mean_q025": float(np.quantile(means, 0.025)),
        "annualized_mean_median": float(np.quantile(means, 0.5)),
        "sharpe_q025": float(np.quantile(sharpes, 0.025)),
        "sharpe_median": float(np.quantile(sharpes, 0.5)),
    }


def market_evidence(frame: pd.DataFrame, instrument: str) -> dict[str, object]:
    candidate_targets, scores = ema_target_map(frame)
    training, returns = evaluate_segment(frame, candidate_targets, TRAIN_START, TRAIN_END)
    delayed, _ = evaluate_segment(
        frame,
        candidate_targets,
        TRAIN_START,
        TRAIN_END,
        delay_hours=1,
    )
    fold_rows = folds(frame, candidate_targets)
    year_rows = calendar_slices(frame, candidate_targets)
    bootstrap = moving_block_bootstrap(returns, BOOTSTRAP_SEEDS[instrument])
    positive_folds = [float(row["net_total_return"]) for row in fold_rows if float(row["net_total_return"]) > 0.0]
    concentration = max(positive_folds) / sum(positive_folds) if positive_folds else None

    e2160, _ = evaluate_segment(frame, e2160_target_map(frame), TRAIN_START, TRAIN_END)
    always_long, _ = evaluate_segment(frame, {TRAIN_START: 1}, TRAIN_START, TRAIN_END)

    gates = {
        "source_hash_chronology_next_open_ema_fee_terminal_checks": True,
        "positive_training_net_and_sharpe": float(training["net_total_return"]) > 0.0 and float(training["sharpe"]) > 0.0,
        "training_max_drawdown_above_minus_50pct": float(training["max_drawdown"]) > -0.5,
        "training_edge_per_turnover_above_10bps": float(training["net_edge_per_turnover_bps"] or 0.0) > 10.0,
        "at_least_4_of_6_positive_2160h_folds": sum(float(row["net_total_return"]) > 0.0 for row in fold_rows) >= 4,
        "at_least_2_positive_calendar_slices": sum(float(row["net_total_return"]) > 0.0 for row in year_rows) >= 2,
        "positive_fold_concentration_at_most_60pct": concentration is not None and concentration <= 0.60,
        "moving_block_q025_annualized_mean_and_sharpe_positive": bootstrap["annualized_mean_q025"] > 0.0 and bootstrap["sharpe_q025"] > 0.0,
        "plus_1h_delay_positive_net_sharpe_and_edge": float(delayed["net_total_return"]) > 0.0 and float(delayed["sharpe"]) > 0.0 and float(delayed["net_edge_per_turnover_bps"] or 0.0) > 0.0,
        "no_pooling_or_single_market_promotion": True,
    }

    return {
        "training": training,
        "descriptive_e2160_training": e2160,
        "descriptive_always_long_training": always_long,
        "plus_1h_delay_training": delayed,
        "folds_2160h": fold_rows,
        "positive_fold_count": sum(float(row["net_total_return"]) > 0.0 for row in fold_rows),
        "positive_fold_concentration": concentration,
        "calendar_slices": year_rows,
        "represented_calendar_slice_count": len(year_rows),
        "positive_calendar_slice_count": sum(float(row["net_total_return"]) > 0.0 for row in year_rows),
        "moving_block_bootstrap": bootstrap,
        "ema_score_min": min(scores.values()),
        "ema_score_max": max(scores.values()),
        "ema_score_last_training_anchor": list(scores.values())[-1],
        "daily_anchor_count": len(candidate_targets),
        "daily_long_target_fraction": float(np.mean(list(candidate_targets.values()))),
        "gates": gates,
        "all_training_gates_pass": all(gates.values()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--btc-csv", type=Path, required=True)
    parser.add_argument("--eth-csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    markets = {
        "BTC-USDT": market_evidence(load_training_prefix(args.btc_csv, "BTC-USDT"), "BTC-USDT"),
        "ETH-USDT": market_evidence(load_training_prefix(args.eth_csv, "ETH-USDT"), "ETH-USDT"),
    }
    bilateral = all(bool(market["all_training_gates_pass"]) for market in markets.values())
    verdict = (
        "training_pass_requires_separate_oos_run"
        if bilateral
        else "reject_causal_own_price_dual_ema_distributed_memory_trend_canonical_replication_training_1h_v1"
    )
    evidence = {
        "schema_version": "dual-ema-distributed-memory-trend-canonical-replication-evidence-v1",
        "family_id": "causal-own-price-dual-ema-distributed-memory-trend-canonical-replication-1h-v1",
        "issue": 1120,
        "candidate_count": 1,
        "parameter_grid_count": 0,
        "fee_one_way": FEE_ONE_WAY,
        "source_contract": {
            instrument: {
                "artifact_id": SOURCE_ARTIFACT_ID[instrument],
                "csv_sha256": EXPECTED_SHA256[instrument],
            }
            for instrument in EXPECTED_SHA256
        },
        "training_sample": {"start_row": TRAIN_START, "end_row_exclusive": TRAIN_END},
        "markets": markets,
        "bilateral_training_pass": bilateral,
        "development_oos_accessed": False,
        "full_performance_accessed": False,
        "canonical_mutation_authority": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "verdict": verdict,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
