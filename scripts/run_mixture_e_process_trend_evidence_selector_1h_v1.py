from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from gpt_quant.okx import _canonical_csv_bytes, _canonical_json_bytes
from gpt_quant.okx_1h import (
    fetch_okx_one_hour_candles,
    replay_persisted_okx_one_hour_snapshot,
)

FAMILY_ID = "causal-own-price-mixture-e-process-trend-evidence-selector-1h-v1"
REJECT_VERDICT = "reject_causal_own_price_mixture_e_process_trend_evidence_selector_1h_v1"
ACCEPT_VERDICT = (
    "accept_causal_own_price_mixture_e_process_trend_evidence_selector_"
    "for_canonical_review_1h_v1"
)
TARGETS = ("XRP-USDT", "ADA-USDT")
SOURCE_START = pd.Timestamp("2023-04-01T00:00:00Z")
SOURCE_END = pd.Timestamp("2026-07-31T23:00:00Z")
EXPECTED_ROWS = 29_232
PREFIX_END = pd.Timestamp("2024-03-31T23:00:00Z")
VALIDATION_START = pd.Timestamp("2024-04-01T01:00:00Z")
VALIDATION_END = pd.Timestamp("2024-12-31T23:00:00Z")
OOS_START = pd.Timestamp("2025-01-01T01:00:00Z")
OOS_END = SOURCE_END
FULL_START = VALIDATION_START
DECISION_HOUR = 1
HORIZON_HOURS = 24
E2160_HOURS = 2_160
FEE_ONE_WAY = 0.0005
OPPORTUNITY_HURDLE = 0.001
UTILITY_SCALE = 0.05
MIXTURE_LAMBDAS = np.array([0.125, 0.25, 0.5, 1.0], dtype=float)
EVIDENCE_THRESHOLD = 20.0
MIN_SUPPORT = 120
MIN_VALIDATION_LONG_ANCHORS = 20
BOOTSTRAP_DRAWS = 5_000
BOOTSTRAP_BLOCK_ANCHORS = 28
BOOTSTRAP_SEED = 2026080401
FOLD_COUNT = 12


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def _finite(value: float | np.floating[Any]) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("non-finite numeric result")
    return result


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _timestamp_index(frame: pd.DataFrame, timestamp: pd.Timestamp) -> int:
    location = frame.index.get_indexer([timestamp])
    if len(location) != 1 or int(location[0]) < 0:
        raise ValueError(f"required timestamp unavailable: {timestamp.isoformat()}")
    return int(location[0])


def _persist_and_replay_source(
    *,
    instrument: str,
    output_dir: Path,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    snapshot = fetch_okx_one_hour_candles(
        inst_id=instrument,
        start=SOURCE_START,
        end=SOURCE_END,
        pause_seconds=0.12,
        timeout=20.0,
        safety_pages=4,
    )
    frame = snapshot.candles.copy()
    expected_index = pd.date_range(SOURCE_START, SOURCE_END, freq="h")
    if len(frame) != EXPECTED_ROWS or not frame.index.equals(expected_index):
        raise ValueError(f"{instrument} source does not match the frozen hourly grid")
    if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise ValueError(f"{instrument} source chronology is invalid")
    required = ["open", "high", "low", "close"]
    values = frame[required].to_numpy(dtype=float)
    if not np.isfinite(values).all() or np.any(values <= 0):
        raise ValueError(f"{instrument} contains non-positive or non-finite OHLC")
    if np.any(frame["high"].to_numpy(dtype=float) < frame[["open", "close"]].max(axis=1)):
        raise ValueError(f"{instrument} has invalid high values")
    if np.any(frame["low"].to_numpy(dtype=float) > frame[["open", "close"]].min(axis=1)):
        raise ValueError(f"{instrument} has invalid low values")

    source_dir = output_dir / "source" / instrument
    source_dir.mkdir(parents=True, exist_ok=True)
    stem = f"okx-{instrument}-1H"
    csv_bytes = _canonical_csv_bytes(frame)
    raw_bytes = _canonical_json_bytes(snapshot.raw_pages)
    metadata_bytes = _canonical_json_bytes(snapshot.metadata)
    (source_dir / f"{stem}.csv").write_bytes(csv_bytes)
    (source_dir / f"{stem}.raw.json").write_bytes(raw_bytes)
    (source_dir / f"{stem}.metadata.json").write_bytes(metadata_bytes)

    replayed = replay_persisted_okx_one_hour_snapshot(source_dir, inst_id=instrument)
    replay_csv = _canonical_csv_bytes(replayed.candles)
    if replay_csv != csv_bytes or not replayed.candles.equals(frame):
        raise ValueError(f"{instrument} exact-byte replay changed the normalized source")
    repeated_normalization_identical = bool(
        _canonical_csv_bytes(replayed.candles.copy()) == replay_csv
    )
    prefix = frame.loc[:VALIDATION_END]
    prefix_bytes = _canonical_csv_bytes(prefix)
    return frame, {
        "provider": "OKX",
        "market_type": "SPOT",
        "bar": "1H",
        "instrument": instrument,
        "requested_start": SOURCE_START.isoformat(),
        "requested_end": SOURCE_END.isoformat(),
        "rows": len(frame),
        "start": frame.index[0].isoformat(),
        "end": frame.index[-1].isoformat(),
        "normalized_csv_sha256": _sha256_bytes(csv_bytes),
        "raw_pages_sha256": _sha256_bytes(raw_bytes),
        "metadata_sha256": _sha256_bytes(metadata_bytes),
        "validation_prefix_sha256": _sha256_bytes(prefix_bytes),
        "response_count": int(snapshot.metadata.get("source_response_count", 0)),
        "completed_hour_grid": True,
        "gap_count": 0,
        "duplicate_count": 0,
        "exact_byte_replay_identical": True,
        "repeated_normalization_identical": repeated_normalization_identical,
        "credentials_used": False,
        "private_endpoints_used": False,
        "synthetic_rows": 0,
        "interpolated_rows": 0,
        "resampled_rows": 0,
    }


def _logsumexp(values: np.ndarray) -> float:
    finite_values = values[np.isfinite(values)]
    if len(finite_values) == 0:
        raise ValueError("all e-process mixture components are zero")
    maximum = float(np.max(finite_values))
    return _finite(maximum + math.log(float(np.exp(finite_values - maximum).sum())))


def _build_evidence_records(frame: pd.DataFrame) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    opens = frame["open"].to_numpy(dtype=float)
    closes = frame["close"].to_numpy(dtype=float)
    anchors = [
        index
        for index, timestamp in enumerate(frame.index)
        if timestamp.hour == DECISION_HOUR and index >= E2160_HOURS + 1
    ]
    log_wealth = np.zeros(len(MIXTURE_LAMBDAS), dtype=float)
    pending: list[dict[str, Any]] = []
    pending_index = 0
    support = 0
    records: list[dict[str, Any]] = []
    update_utilities: list[float] = []

    for anchor in anchors:
        while pending_index < len(pending) and pending[pending_index]["exit_index"] <= anchor - 1:
            utility = float(pending[pending_index]["utility"])
            factors = 1.0 + MIXTURE_LAMBDAS * utility
            if np.any(factors < 0.0):
                raise ValueError("e-process factor became negative")
            with np.errstate(divide="ignore", invalid="raise"):
                log_wealth = log_wealth + np.log(factors)
            support += 1
            update_utilities.append(utility)
            pending_index += 1

        log_evidence = _finite(_logsumexp(log_wealth) - math.log(len(MIXTURE_LAMBDAS)))
        evidence = _finite(math.exp(log_evidence))
        e2160_margin = _finite(closes[anchor - 1] / closes[anchor - 2161] - 1.0)
        e2160 = int(e2160_margin > 0.0)
        candidate = int(e2160 == 1 and support >= MIN_SUPPORT and evidence >= EVIDENCE_THRESHOLD)
        record: dict[str, Any] = {
            "anchor": anchor,
            "timestamp": frame.index[anchor],
            "signal_close_index": anchor - 1,
            "oldest_trend_close_index": anchor - 2161,
            "e2160_margin": e2160_margin,
            "e2160": e2160,
            "support": support,
            "log_component_wealth": log_wealth.copy(),
            "log_evidence": log_evidence,
            "evidence": evidence,
            "candidate": candidate,
        }
        if anchor + HORIZON_HOURS < len(frame):
            gross_opportunity = _finite(opens[anchor + HORIZON_HOURS] / opens[anchor] - 1.0)
            record["gross_opportunity_return"] = gross_opportunity
            if e2160 == 1:
                net_opportunity = _finite(gross_opportunity - OPPORTUNITY_HURDLE)
                utility = _finite(np.clip(net_opportunity / UTILITY_SCALE, -1.0, 1.0))
                record["net_opportunity_return"] = net_opportunity
                record["utility"] = utility
                record["exit_index"] = anchor + HORIZON_HOURS
                pending.append(record)
        records.append(record)

    if any(record["signal_close_index"] >= record["anchor"] for record in records):
        raise ValueError("signal chronology is not strictly lagged")
    if any(record["oldest_trend_close_index"] < 0 for record in records):
        raise ValueError("trend history underflow")
    if support != len(update_utilities):
        raise ValueError("support and e-process update count disagree")
    if not all(0.0 < record["evidence"] < math.inf for record in records):
        raise ValueError("mixture evidence is non-positive or non-finite")
    return records, {
        "anchors": len(records),
        "matured_positive_e2160_outcomes": support,
        "utility_updates": len(update_utilities),
        "utility_minimum": None if not update_utilities else _finite(min(update_utilities)),
        "utility_maximum": None if not update_utilities else _finite(max(update_utilities)),
        "mixture_lambdas": MIXTURE_LAMBDAS.tolist(),
        "minimum_support": MIN_SUPPORT,
        "evidence_threshold": EVIDENCE_THRESHOLD,
        "all_signal_inputs_strictly_lagged": True,
        "all_evidence_inputs_matured_by_anchor_minus_one": True,
        "finite_positive_mixture_evidence": True,
        "log_space_accumulation": True,
        "reset_count": 0,
    }


def _complete_segment_records(
    records: list[dict[str, Any]],
    frame: pd.DataFrame,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    delay_hours: int = 0,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for record in records:
        timestamp = record["timestamp"]
        exit_index = record["anchor"] + delay_hours + HORIZON_HOURS
        if timestamp < start or exit_index >= len(frame):
            continue
        if frame.index[exit_index] <= end:
            selected.append(record)
    return selected


def _asset_returns_for_records(
    frame: pd.DataFrame,
    records: list[dict[str, Any]],
    *,
    delay_hours: int = 0,
) -> np.ndarray:
    opens = frame["open"].to_numpy(dtype=float)
    returns = [
        opens[record["anchor"] + delay_hours + HORIZON_HOURS]
        / opens[record["anchor"] + delay_hours]
        - 1.0
        for record in records
    ]
    sample = np.asarray(returns, dtype=float)
    if len(sample) != len(records) or not np.isfinite(sample).all():
        raise ValueError("invalid 24-hour asset-return vector")
    return sample


def _net_daily_returns(asset_returns: np.ndarray, positions: np.ndarray) -> dict[str, Any]:
    if len(asset_returns) != len(positions) or len(asset_returns) == 0:
        raise ValueError("daily path requires aligned non-empty arrays")
    previous = np.concatenate([np.array([0.0]), positions[:-1]])
    turnover_by_anchor = np.abs(positions - previous)
    gross_factors = 1.0 + positions * asset_returns
    fee_factors = 1.0 - FEE_ONE_WAY * turnover_by_anchor
    net_factors = gross_factors * fee_factors
    terminal_turnover = abs(float(positions[-1]))
    net_factors[-1] *= 1.0 - FEE_ONE_WAY * terminal_turnover
    net_returns = net_factors - 1.0
    turnover = _finite(turnover_by_anchor.sum() + terminal_turnover)
    return {
        "gross_factors": gross_factors,
        "net_factors": net_factors,
        "net_returns": net_returns,
        "turnover_by_anchor": turnover_by_anchor,
        "turnover": turnover,
        "terminal_turnover": terminal_turnover,
    }


def _max_loss_cluster(net_returns: np.ndarray) -> int:
    maximum = 0
    current = 0
    for value in net_returns:
        if value < 0.0:
            current += 1
            maximum = max(maximum, current)
        else:
            current = 0
    return maximum


def _path_metrics(
    frame: pd.DataFrame,
    records: list[dict[str, Any]],
    *,
    key: str,
    delay_hours: int = 0,
) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    if not records:
        raise ValueError("strategy segment contains no complete decision intervals")
    positions = np.asarray([float(record[key]) for record in records], dtype=float)
    asset_returns = _asset_returns_for_records(frame, records, delay_hours=delay_hours)
    daily = _net_daily_returns(asset_returns, positions)
    net_returns = daily["net_returns"]
    net_factors = daily["net_factors"]
    gross_factors = daily["gross_factors"]
    net_equity = np.cumprod(net_factors)
    gross_equity = np.cumprod(gross_factors)
    equity_with_start = np.concatenate([np.array([1.0]), net_equity])
    peaks = np.maximum.accumulate(equity_with_start)
    drawdowns = equity_with_start / peaks - 1.0
    volatility = float(net_returns.std(ddof=0))
    sharpe = 0.0 if volatility == 0.0 else net_returns.mean() / volatility * math.sqrt(365.0)
    net_return = _finite(net_equity[-1] - 1.0)
    gross_return = _finite(gross_equity[-1] - 1.0)
    turnover = float(daily["turnover"])
    edge_per_turnover = None if turnover == 0.0 else _finite(10_000.0 * net_return / turnover)
    return {
        "decision_intervals": len(records),
        "start_anchor": records[0]["timestamp"].isoformat(),
        "end_anchor": records[-1]["timestamp"].isoformat(),
        "delay_hours": delay_hours,
        "gross_return": gross_return,
        "net_return": net_return,
        "annualized_daily_sharpe": _finite(sharpe),
        "maximum_drawdown": _finite(drawdowns.min()),
        "long_anchors": int(positions.sum()),
        "exposure_fraction": _finite(positions.mean()),
        "one_way_turnover": turnover,
        "modeled_fee_notional": _finite(FEE_ONE_WAY * turnover),
        "fee_drag": _finite(gross_return - net_return),
        "edge_per_turnover_bps": edge_per_turnover,
        "loss_count": int(np.count_nonzero(net_returns < 0.0)),
        "maximum_consecutive_loss_anchors": _max_loss_cluster(net_returns),
    }, {
        "positions": positions,
        "asset_returns": asset_returns,
        "net_returns": net_returns,
    }


def _segment_scorecard(
    frame: pd.DataFrame,
    records: list[dict[str, Any]],
    *,
    delay_hours: int = 0,
) -> tuple[dict[str, Any], dict[str, dict[str, np.ndarray]]]:
    candidate, candidate_arrays = _path_metrics(
        frame, records, key="candidate", delay_hours=delay_hours
    )
    e2160, e2160_arrays = _path_metrics(frame, records, key="e2160", delay_hours=delay_hours)
    always_records = [{**record, "always_long": 1} for record in records]
    always, always_arrays = _path_metrics(
        frame, always_records, key="always_long", delay_hours=delay_hours
    )
    return {
        "candidate": candidate,
        "e2160": e2160,
        "always_long": always,
        "candidate_minus_e2160_net_return": _finite(
            candidate["net_return"] - e2160["net_return"]
        ),
        "candidate_minus_e2160_sharpe": _finite(
            candidate["annualized_daily_sharpe"] - e2160["annualized_daily_sharpe"]
        ),
        "candidate_minus_always_long_net_return": _finite(
            candidate["net_return"] - always["net_return"]
        ),
        "candidate_minus_always_long_sharpe": _finite(
            candidate["annualized_daily_sharpe"] - always["annualized_daily_sharpe"]
        ),
    }, {
        "candidate": candidate_arrays,
        "e2160": e2160_arrays,
        "always_long": always_arrays,
    }


def _rank_correlation(x: np.ndarray, y: np.ndarray) -> float | None:
    if len(x) < 3 or np.unique(x).size < 2 or np.unique(y).size < 2:
        return None
    value = pd.Series(x).rank(method="average").corr(pd.Series(y).rank(method="average"))
    return None if pd.isna(value) else _finite(value)


def _evidence_diagnostics(
    records: list[dict[str, Any]],
    frame: pd.DataFrame,
) -> dict[str, Any]:
    complete = [record for record in records if "gross_opportunity_return" in record]
    log_evidence = np.asarray([record["log_evidence"] for record in complete], dtype=float)
    realised = np.asarray(
        [record["gross_opportunity_return"] - OPPORTUNITY_HURDLE for record in complete],
        dtype=float,
    )
    candidate_mask = np.asarray([record["candidate"] for record in complete], dtype=bool)
    e2160_mask = np.asarray([record["e2160"] for record in complete], dtype=bool)
    threshold_mask = np.asarray(
        [record["evidence"] >= EVIDENCE_THRESHOLD for record in complete], dtype=bool
    )
    candidate_realised = realised[candidate_mask]
    suppressed = e2160_mask & ~candidate_mask
    return {
        "complete_anchor_count": len(complete),
        "candidate_anchor_count": int(candidate_mask.sum()),
        "e2160_anchor_count": int(e2160_mask.sum()),
        "evidence_threshold_anchor_count": int(threshold_mask.sum()),
        "suppressed_positive_e2160_anchors": int(suppressed.sum()),
        "log_evidence_minimum": _finite(log_evidence.min()),
        "log_evidence_median": _finite(np.median(log_evidence)),
        "log_evidence_maximum": _finite(log_evidence.max()),
        "log_evidence_realised_return_spearman": _rank_correlation(log_evidence, realised),
        "candidate_mean_fee_clearing_opportunity_return": (
            None if len(candidate_realised) == 0 else _finite(candidate_realised.mean())
        ),
        "suppressed_mean_fee_clearing_opportunity_return": (
            None if not suppressed.any() else _finite(realised[suppressed].mean())
        ),
        "first_candidate_anchor": next(
            (record["timestamp"].isoformat() for record in complete if record["candidate"]),
            None,
        ),
        "last_candidate_anchor": next(
            (
                record["timestamp"].isoformat()
                for record in reversed(complete)
                if record["candidate"]
            ),
            None,
        ),
        "source_rows_visible": len(frame),
    }


def _validation_gates(scorecard: dict[str, Any]) -> dict[str, bool]:
    candidate = scorecard["candidate"]
    return {
        "minimum_long_anchors": candidate["long_anchors"] >= MIN_VALIDATION_LONG_ANCHORS,
        "positive_net_return": candidate["net_return"] > 0.0,
        "positive_sharpe": candidate["annualized_daily_sharpe"] > 0.0,
        "positive_edge_per_turnover": (
            candidate["edge_per_turnover_bps"] is not None
            and candidate["edge_per_turnover_bps"] > 0.0
        ),
    }


def _fold_breadth(
    frame: pd.DataFrame,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    chunks = [list(chunk) for chunk in np.array_split(np.asarray(records, dtype=object), FOLD_COUNT)]
    folds: list[dict[str, Any]] = []
    positive_returns: list[float] = []
    for index, chunk in enumerate(chunks, start=1):
        scorecard, _ = _segment_scorecard(frame, chunk)
        candidate_return = float(scorecard["candidate"]["net_return"])
        if candidate_return > 0.0:
            positive_returns.append(candidate_return)
        folds.append(
            {
                "fold": index,
                "anchors": len(chunk),
                "start": chunk[0]["timestamp"].isoformat(),
                "end": chunk[-1]["timestamp"].isoformat(),
                "candidate_net_return": candidate_return,
                "candidate_sharpe": scorecard["candidate"]["annualized_daily_sharpe"],
                "e2160_net_return": scorecard["e2160"]["net_return"],
                "relative_net_return": scorecard["candidate_minus_e2160_net_return"],
            }
        )
    positive_sum = sum(positive_returns)
    concentration = 1.0 if positive_sum <= 0.0 else max(positive_returns) / positive_sum
    return {
        "folds": folds,
        "profitable_candidate_folds": sum(row["candidate_net_return"] > 0.0 for row in folds),
        "positive_relative_folds": sum(row["relative_net_return"] > 0.0 for row in folds),
        "largest_positive_fold_contribution": _finite(concentration),
    }


def _calendar_year_breadth(
    frame: pd.DataFrame,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    years: list[dict[str, Any]] = []
    for year in sorted({record["timestamp"].year for record in records}):
        group = [record for record in records if record["timestamp"].year == year]
        scorecard, _ = _segment_scorecard(frame, group)
        years.append(
            {
                "year": year,
                "anchors": len(group),
                "candidate_net_return": scorecard["candidate"]["net_return"],
                "candidate_sharpe": scorecard["candidate"]["annualized_daily_sharpe"],
                "e2160_net_return": scorecard["e2160"]["net_return"],
                "relative_net_return": scorecard["candidate_minus_e2160_net_return"],
            }
        )
    return {
        "years": years,
        "positive_candidate_years": sum(row["candidate_net_return"] > 0.0 for row in years),
        "all_candidate_years_positive": all(row["candidate_net_return"] > 0.0 for row in years),
    }


def _moving_block_indices(
    rng: np.random.Generator,
    observations: int,
    block_length: int,
) -> np.ndarray:
    if observations < block_length:
        raise ValueError("moving-block sample is shorter than the frozen block")
    block_count = math.ceil(observations / block_length)
    starts = rng.integers(0, observations - block_length + 1, size=block_count)
    indices = np.concatenate(
        [np.arange(start, start + block_length, dtype=int) for start in starts]
    )
    return indices[:observations]


def _sharpe(net_returns: np.ndarray) -> float:
    volatility = float(net_returns.std(ddof=0))
    return 0.0 if volatility == 0.0 else _finite(
        net_returns.mean() / volatility * math.sqrt(365.0)
    )


def _paired_moving_block_uncertainty(
    arrays: dict[str, dict[str, np.ndarray]],
) -> dict[str, Any]:
    candidate = arrays["candidate"]
    benchmark = arrays["e2160"]
    observations = len(candidate["asset_returns"])
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    mean_deltas = np.empty(BOOTSTRAP_DRAWS, dtype=float)
    sharpe_deltas = np.empty(BOOTSTRAP_DRAWS, dtype=float)
    for draw in range(BOOTSTRAP_DRAWS):
        indices = _moving_block_indices(rng, observations, BOOTSTRAP_BLOCK_ANCHORS)
        asset = candidate["asset_returns"][indices]
        candidate_path = _net_daily_returns(asset, candidate["positions"][indices])
        benchmark_path = _net_daily_returns(asset, benchmark["positions"][indices])
        candidate_returns = candidate_path["net_returns"]
        benchmark_returns = benchmark_path["net_returns"]
        mean_deltas[draw] = 365.0 * (candidate_returns.mean() - benchmark_returns.mean())
        sharpe_deltas[draw] = _sharpe(candidate_returns) - _sharpe(benchmark_returns)
    mean_ci = np.quantile(mean_deltas, [0.025, 0.975])
    sharpe_ci = np.quantile(sharpe_deltas, [0.025, 0.975])
    return {
        "method": "paired_non_circular_moving_block",
        "draws": BOOTSTRAP_DRAWS,
        "block_anchors": BOOTSTRAP_BLOCK_ANCHORS,
        "seed": BOOTSTRAP_SEED,
        "observations": observations,
        "annualized_mean_return_delta": {
            "point": _finite(
                365.0
                * (
                    candidate["net_returns"].mean()
                    - benchmark["net_returns"].mean()
                )
            ),
            "lower_95": _finite(mean_ci[0]),
            "upper_95": _finite(mean_ci[1]),
        },
        "annualized_sharpe_delta": {
            "point": _finite(
                _sharpe(candidate["net_returns"]) - _sharpe(benchmark["net_returns"])
            ),
            "lower_95": _finite(sharpe_ci[0]),
            "upper_95": _finite(sharpe_ci[1]),
        },
    }


def _prefix_identity(
    left: list[dict[str, Any]],
    right: list[dict[str, Any]],
) -> dict[str, Any]:
    keys = ("anchor", "e2160", "support", "log_evidence", "evidence", "candidate")
    left_rows = [record for record in left if record["timestamp"] <= VALIDATION_END]
    right_rows = [record for record in right if record["timestamp"] <= VALIDATION_END]
    if len(left_rows) != len(right_rows):
        return {"identical": False, "rows": min(len(left_rows), len(right_rows))}
    identical = all(
        all(
            (a[key] == b[key])
            if key not in {"log_evidence", "evidence"}
            else np.array_equal(np.asarray([a[key]]), np.asarray([b[key]]))
            for key in keys
        )
        for a, b in zip(left_rows, right_rows, strict=True)
    )
    return {"identical": bool(identical), "rows": len(left_rows)}


def _promotion_gates(
    *,
    oos: dict[str, Any],
    full: dict[str, Any],
    folds: dict[str, Any],
    years: dict[str, Any],
    uncertainty: dict[str, Any],
    delayed_oos: dict[str, Any],
    delayed_full: dict[str, Any],
) -> dict[str, bool]:
    candidate_oos = oos["candidate"]
    candidate_full = full["candidate"]
    return {
        "positive_oos_return_and_sharpe": (
            candidate_oos["net_return"] > 0.0
            and candidate_oos["annualized_daily_sharpe"] > 0.0
        ),
        "positive_full_return_and_sharpe": (
            candidate_full["net_return"] > 0.0
            and candidate_full["annualized_daily_sharpe"] > 0.0
        ),
        "oos_beats_e2160_and_always_long": (
            oos["candidate_minus_e2160_net_return"] > 0.0
            and oos["candidate_minus_e2160_sharpe"] > 0.0
            and oos["candidate_minus_always_long_net_return"] > 0.0
            and oos["candidate_minus_always_long_sharpe"] > 0.0
        ),
        "full_beats_e2160_and_always_long": (
            full["candidate_minus_e2160_net_return"] > 0.0
            and full["candidate_minus_e2160_sharpe"] > 0.0
            and full["candidate_minus_always_long_net_return"] > 0.0
            and full["candidate_minus_always_long_sharpe"] > 0.0
        ),
        "turnover_no_greater_than_e2160": (
            candidate_oos["one_way_turnover"] <= oos["e2160"]["one_way_turnover"]
            and candidate_full["one_way_turnover"] <= full["e2160"]["one_way_turnover"]
        ),
        "drawdown_within_five_percentage_points": (
            candidate_oos["maximum_drawdown"]
            >= oos["e2160"]["maximum_drawdown"] - 0.05
            and candidate_full["maximum_drawdown"]
            >= full["e2160"]["maximum_drawdown"] - 0.05
        ),
        "fold_breadth": folds["profitable_candidate_folds"] >= 8,
        "calendar_year_breadth": years["all_candidate_years_positive"],
        "fold_concentration": folds["largest_positive_fold_contribution"] <= 0.45,
        "dependence_supported_mean_delta": (
            uncertainty["annualized_mean_return_delta"]["lower_95"] > 0.0
        ),
        "dependence_supported_sharpe_delta": (
            uncertainty["annualized_sharpe_delta"]["lower_95"] > 0.0
        ),
        "one_hour_delay_robustness": (
            delayed_oos["candidate"]["net_return"] > 0.0
            and delayed_oos["candidate"]["annualized_daily_sharpe"] > 0.0
            and delayed_oos["candidate"]["edge_per_turnover_bps"] is not None
            and delayed_oos["candidate"]["edge_per_turnover_bps"] > 0.0
            and delayed_full["candidate"]["net_return"] > 0.0
            and delayed_full["candidate"]["annualized_daily_sharpe"] > 0.0
            and delayed_full["candidate"]["edge_per_turnover_bps"] is not None
            and delayed_full["candidate"]["edge_per_turnover_bps"] > 0.0
        ),
    }


def _serializable_record(record: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in record.items():
        if key == "log_component_wealth":
            result[key] = [None if not math.isfinite(float(item)) else float(item) for item in value]
        elif isinstance(value, pd.Timestamp):
            result[key] = value.isoformat()
        elif isinstance(value, np.generic):
            result[key] = value.item()
        else:
            result[key] = value
    return result


def _target_validation(
    *,
    instrument: str,
    frame: pd.DataFrame,
    source: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    validation_end_index = _timestamp_index(frame, VALIDATION_END)
    validation_frame = frame.iloc[: validation_end_index + 1].copy()
    records, identities = _build_evidence_records(validation_frame)
    repeated_records, _ = _build_evidence_records(validation_frame.copy())
    deterministic_prefix = _prefix_identity(records, repeated_records)
    selected = _complete_segment_records(
        records,
        validation_frame,
        start=VALIDATION_START,
        end=VALIDATION_END,
    )
    scorecard, arrays = _segment_scorecard(validation_frame, selected)
    diagnostics = _evidence_diagnostics(selected, validation_frame)
    gates = _validation_gates(scorecard)
    source_gates = {
        "row_count": source["rows"] == EXPECTED_ROWS,
        "exact_byte_replay": source["exact_byte_replay_identical"],
        "repeated_normalization": source["repeated_normalization_identical"],
        "completed_grid": source["completed_hour_grid"],
        "no_synthetic_or_repaired_rows": (
            source["synthetic_rows"] == 0
            and source["interpolated_rows"] == 0
            and source["resampled_rows"] == 0
        ),
        "prefix_determinism": deterministic_prefix["identical"],
    }
    validation_pass = all(source_gates.values()) and all(gates.values())
    result = {
        "instrument": instrument,
        "source": source,
        "e_process_identities": identities,
        "validation_prefix_determinism": deterministic_prefix,
        "validation": scorecard,
        "validation_arrays_summary": {
            "candidate_daily_return_mean": _finite(arrays["candidate"]["net_returns"].mean()),
            "e2160_daily_return_mean": _finite(arrays["e2160"]["net_returns"].mean()),
        },
        "evidence_diagnostics": diagnostics,
        "source_gates": source_gates,
        "validation_gates": gates,
        "validation_pass": validation_pass,
        "oos": None,
        "full": None,
        "fold_breadth": None,
        "calendar_year_breadth": None,
        "uncertainty": None,
        "one_hour_delay": None,
        "promotion_gates": None,
        "promotion_pass": False,
    }
    return result, records


def _target_oos(
    *,
    frame: pd.DataFrame,
    validation_records: list[dict[str, Any]],
    result: dict[str, Any],
) -> dict[str, Any]:
    full_records, full_identities = _build_evidence_records(frame)
    prefix_identity = _prefix_identity(validation_records, full_records)
    if not prefix_identity["identical"]:
        raise ValueError("validation e-process path changed when the OOS suffix was revealed")
    oos_records = _complete_segment_records(
        full_records, frame, start=OOS_START, end=OOS_END
    )
    full_segment_records = _complete_segment_records(
        full_records, frame, start=FULL_START, end=OOS_END
    )
    oos, oos_arrays = _segment_scorecard(frame, oos_records)
    full, _ = _segment_scorecard(frame, full_segment_records)
    folds = _fold_breadth(frame, oos_records)
    years = _calendar_year_breadth(frame, full_segment_records)
    uncertainty = _paired_moving_block_uncertainty(oos_arrays)
    delayed_oos, _ = _segment_scorecard(frame, oos_records, delay_hours=1)
    delayed_full, _ = _segment_scorecard(frame, full_segment_records, delay_hours=1)
    promotion_gates = _promotion_gates(
        oos=oos,
        full=full,
        folds=folds,
        years=years,
        uncertainty=uncertainty,
        delayed_oos=delayed_oos,
        delayed_full=delayed_full,
    )
    result.update(
        {
            "full_e_process_identities": full_identities,
            "future_suffix_prefix_invariance": prefix_identity,
            "oos": oos,
            "full": full,
            "fold_breadth": folds,
            "calendar_year_breadth": years,
            "uncertainty": uncertainty,
            "one_hour_delay": {"oos": delayed_oos, "full": delayed_full},
            "promotion_gates": promotion_gates,
            "promotion_pass": all(promotion_gates.values()),
            "oos_evidence_diagnostics": _evidence_diagnostics(oos_records, frame),
        }
    )
    return result


def _report(evidence: dict[str, Any]) -> str:
    lines = [
        "# Mixture e-process trend evidence selector 1H v1",
        "",
        "```text",
        f"family                  {evidence['family_id']}",
        f"exact head              {evidence['exact_head']}",
        f"candidate/grid          {evidence['candidate_count']}/{evidence['parameter_grid_count']}",
        f"validation pass         {evidence['bilateral_validation_pass']}",
        f"sealed OOS accessed     {evidence['sealed_oos_performance_accessed']}",
        f"verdict                 {evidence['verdict']}",
        "```",
        "",
        "## Frozen rule",
        "",
        "A target is long only when its own delayed E2160 state is positive, at least 120",
        "strictly matured positive-E2160 opportunities exist, and the fixed equal-weight",
        "mixture e-process over utility fractions 0.125, 0.25, 0.5 and 1.0 is at least 20.",
        "The strategy uses completed provider-native OKX 1H candles and charges exactly 5 bps",
        "for each actual exposure change.",
        "",
        "## Target results",
        "",
    ]
    for target in evidence["targets"]:
        validation = target["validation"]["candidate"]
        lines.extend(
            [
                f"### {target['instrument']}",
                "",
                f"- source rows: `{target['source']['rows']}`",
                f"- normalized SHA-256: `{target['source']['normalized_csv_sha256']}`",
                f"- validation long anchors: `{validation['long_anchors']}`",
                f"- validation net return: `{validation['net_return']:.8f}`",
                f"- validation Sharpe: `{validation['annualized_daily_sharpe']:.6f}`",
                f"- validation turnover: `{validation['one_way_turnover']:.4f}`",
                f"- validation drawdown: `{validation['maximum_drawdown']:.8f}`",
                f"- validation edge/turnover: `{validation['edge_per_turnover_bps']}`",
                f"- validation pass: `{target['validation_pass']}`",
                "",
            ]
        )
        if target["oos"] is None:
            lines.append("OOS and full-period economics remained sealed because bilateral validation failed.\n")
        else:
            for label in ("oos", "full"):
                score = target[label]
                candidate = score["candidate"]
                benchmark = score["e2160"]
                lines.extend(
                    [
                        f"**{label.upper()}** candidate return/Sharpe: "
                        f"`{candidate['net_return']:.8f}` / "
                        f"`{candidate['annualized_daily_sharpe']:.6f}`; "
                        f"E2160: `{benchmark['net_return']:.8f}` / "
                        f"`{benchmark['annualized_daily_sharpe']:.6f}`; "
                        f"turnover `{candidate['one_way_turnover']:.4f}`; "
                        f"drawdown `{candidate['maximum_drawdown']:.8f}`.",
                        "",
                    ]
                )
            lines.extend(
                [
                    f"Profitable folds: `{target['fold_breadth']['profitable_candidate_folds']}/12`; "
                    f"largest positive-fold contribution: "
                    f"`{target['fold_breadth']['largest_positive_fold_contribution']:.6f}`.",
                    "",
                    f"Mean-delta CI: `[{target['uncertainty']['annualized_mean_return_delta']['lower_95']:.8f}, "
                    f"{target['uncertainty']['annualized_mean_return_delta']['upper_95']:.8f}]`; "
                    f"Sharpe-delta CI: `[{target['uncertainty']['annualized_sharpe_delta']['lower_95']:.6f}, "
                    f"{target['uncertainty']['annualized_sharpe_delta']['upper_95']:.6f}]`.",
                    "",
                    f"Promotion pass: `{target['promotion_pass']}`.",
                    "",
                ]
            )
    lines.extend(
        [
            "## Strategy boundary",
            "",
            "No cross-sectional ranking, pooling, pairs, spreads, shorting, leverage, credentials,",
            "private endpoints, orders, adapters, synthetic rows, interpolation, resampling or non-1H",
            "market input was used. Paper and live trading remain prohibited.",
            "",
            "## Remaining blocker",
            "",
            evidence["remaining_blocker"],
            "",
            "## Next strategy experiment",
            "",
            f"`{evidence['next_strategy_experiment']}`",
            "",
        ]
    )
    return "\n".join(lines)


def run(output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    frames: dict[str, pd.DataFrame] = {}
    sources: dict[str, dict[str, Any]] = {}
    for instrument in TARGETS:
        frame, source = _persist_and_replay_source(
            instrument=instrument,
            output_dir=output_dir,
        )
        frames[instrument] = frame
        sources[instrument] = source

    targets: list[dict[str, Any]] = []
    validation_records: dict[str, list[dict[str, Any]]] = {}
    for instrument in TARGETS:
        target, records = _target_validation(
            instrument=instrument,
            frame=frames[instrument],
            source=sources[instrument],
        )
        targets.append(target)
        validation_records[instrument] = records

    bilateral_validation_pass = all(target["validation_pass"] for target in targets)
    sealed_oos_accessed = False
    if bilateral_validation_pass:
        sealed_oos_accessed = True
        targets = [
            _target_oos(
                frame=frames[target["instrument"]],
                validation_records=validation_records[target["instrument"]],
                result=target,
            )
            for target in targets
        ]

    bilateral_promotion_pass = sealed_oos_accessed and all(
        target["promotion_pass"] for target in targets
    )
    verdict = ACCEPT_VERDICT if bilateral_promotion_pass else REJECT_VERDICT
    if not bilateral_validation_pass:
        blocker = (
            "The fixed anytime-valid evidence process failed bilateral validation activation or "
            "fee-adjusted validation economics, so sealed OOS strategy, benchmark and label "
            "economics remained unread."
        )
    elif not bilateral_promotion_pass:
        blocker = (
            "The unchanged rule reached sealed OOS but failed at least one bilateral benchmark, "
            "turnover, drawdown, breadth, dependence or one-hour-delay gate."
        )
    else:
        blocker = (
            "The strategy passed the frozen research gates; the remaining blocker is a separate "
            "canonical review on a newly frozen observation epoch."
        )

    evidence: dict[str, Any] = {
        "family_id": FAMILY_ID,
        "exact_head": os.environ.get("GITHUB_SHA", "local-unverified"),
        "canonical_main": "5a0fcc97d1a882f8223656c51f5bb8055f534e38",
        "candidate_count": 1,
        "parameter_grid_count": 0,
        "fixed_targets": list(TARGETS),
        "bar": "1H",
        "source_start": SOURCE_START.isoformat(),
        "source_end": SOURCE_END.isoformat(),
        "expected_rows_per_target": EXPECTED_ROWS,
        "decision_hour_utc": DECISION_HOUR,
        "canonical_fee_bps_one_way": 5.0,
        "opportunity_hurdle_bps_round_trip": 10.0,
        "utility_scale": UTILITY_SCALE,
        "mixture_lambdas": MIXTURE_LAMBDAS.tolist(),
        "evidence_threshold": EVIDENCE_THRESHOLD,
        "minimum_support": MIN_SUPPORT,
        "bilateral_validation_pass": bilateral_validation_pass,
        "sealed_oos_performance_accessed": sealed_oos_accessed,
        "bilateral_promotion_pass": bool(bilateral_promotion_pass),
        "targets": targets,
        "controls": {
            "cross_sectional_selection": False,
            "target_pooling": False,
            "pairs_or_spreads": False,
            "shorting": False,
            "leverage": False,
            "credentials_used": False,
            "private_endpoints_used": False,
            "orders_or_adapters_enabled": False,
            "synthetic_market_data_used": False,
            "non_1h_market_input_used": False,
            "paper_trading_authorized": False,
            "live_trading_authorized": False,
            "canonical_mutation_authorized": False,
        },
        "verdict": verdict,
        "remaining_blocker": blocker,
        "next_strategy_experiment": (
            "causal-own-price-multiorigin-trend-consensus-turnover-selector-1h-v1"
            if verdict == REJECT_VERDICT
            else "canonical-mixture-e-process-new-epoch-review-1h-v1"
        ),
    }
    evidence_text = _canonical_json(evidence)
    (output_dir / "evidence.json").write_text(evidence_text)
    (output_dir / "evidence.sha256").write_text(
        _sha256_bytes(evidence_text.encode()) + "\n"
    )
    report = _report(evidence)
    (output_dir / "report.md").write_text(report)
    (output_dir / "report.md.sha256").write_text(_sha256_bytes(report.encode()) + "\n")
    compact_records = {
        target["instrument"]: [
            _serializable_record(record)
            for record in validation_records[target["instrument"]]
            if VALIDATION_START <= record["timestamp"] <= VALIDATION_END
        ]
        for target in targets
    }
    records_text = _canonical_json(compact_records)
    (output_dir / "validation-records.json").write_text(records_text)
    (output_dir / "validation-records.json.sha256").write_text(
        _sha256_bytes(records_text.encode()) + "\n"
    )
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args()
    evidence = run(arguments.output_dir)
    compact = {
        "exact_head": evidence["exact_head"],
        "verdict": evidence["verdict"],
        "bilateral_validation_pass": evidence["bilateral_validation_pass"],
        "sealed_oos_performance_accessed": evidence["sealed_oos_performance_accessed"],
        "bilateral_promotion_pass": evidence["bilateral_promotion_pass"],
        "targets": [
            {
                "instrument": target["instrument"],
                "validation": target["validation"],
                "validation_gates": target["validation_gates"],
                "validation_pass": target["validation_pass"],
                "oos": target["oos"],
                "full": target["full"],
                "fold_breadth": target["fold_breadth"],
                "calendar_year_breadth": target["calendar_year_breadth"],
                "uncertainty": target["uncertainty"],
                "one_hour_delay": target["one_hour_delay"],
                "promotion_gates": target["promotion_gates"],
                "promotion_pass": target["promotion_pass"],
            }
            for target in evidence["targets"]
        ],
    }
    print("STRATEGY_COMPACT_JSON=" + json.dumps(compact, sort_keys=True))


if __name__ == "__main__":
    main()
