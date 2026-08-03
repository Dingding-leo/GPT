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

from gpt_quant.okx_1h import fetch_okx_one_hour_candles

FAMILY_ID = "causal-own-price-ridge-lag-strip-utility-selector-1h-v1"
TARGETS = ("ETC-USDT", "FIL-USDT")
START = pd.Timestamp("2023-04-01T00:00:00Z")
END = pd.Timestamp("2025-12-31T23:00:00Z")
EXPECTED_ROWS = 24_144
WARMUP_END = 2_208
FIT_END = 7_200
VALIDATION_END = 10_800
OOS_END = 23_760
UNREAD_SUFFIX_START = 23_760
DECISION_STEP = 24
HORIZON = 24
FEATURE_BLOCKS = 30
FEATURE_HOURS = 720
E2160_HOURS = 2_160
FEE_ONE_WAY = 0.0005
RIDGE_LAMBDA = 1.0
BOOTSTRAP_DRAWS = 5_000
BOOTSTRAP_BLOCK_HOURS = 168
BOOTSTRAP_SEED = 2026080313


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def _finite(value: float | np.floating[Any]) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("non-finite value")
    return result


def _summary(values: np.ndarray) -> dict[str, float]:
    sample = np.asarray(values, dtype=float)
    if sample.ndim != 1 or len(sample) == 0 or not np.isfinite(sample).all():
        raise ValueError("summary requires finite one-dimensional values")
    quantiles = np.quantile(sample, [0.0, 0.05, 0.25, 0.5, 0.75, 0.95, 1.0])
    return {
        "minimum": _finite(quantiles[0]),
        "q05": _finite(quantiles[1]),
        "q25": _finite(quantiles[2]),
        "median": _finite(quantiles[3]),
        "q75": _finite(quantiles[4]),
        "q95": _finite(quantiles[5]),
        "maximum": _finite(quantiles[6]),
        "mean": _finite(sample.mean()),
        "standard_deviation": _finite(sample.std(ddof=0)),
    }


def _feature_at(closes: np.ndarray, anchor: int) -> tuple[np.ndarray, float, bool]:
    signal_index = anchor - 25
    oldest_index = signal_index - FEATURE_HOURS
    if oldest_index < 0 or signal_index - E2160_HOURS < 0:
        raise ValueError("insufficient causal history")
    window = np.asarray(closes[oldest_index : signal_index + 1], dtype=float)
    if len(window) != FEATURE_HOURS + 1:
        raise ValueError("lag strip window length mismatch")
    if not np.isfinite(window).all() or not (window > 0).all():
        raise ValueError("lag strip requires finite positive closes")
    hourly_returns = np.diff(np.log(window))
    if len(hourly_returns) != FEATURE_HOURS:
        raise ValueError("hourly scale window length mismatch")
    scale = math.sqrt(_finite(np.mean(hourly_returns * hourly_returns))) * math.sqrt(24.0)
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("non-positive lag strip scale")
    daily = np.log(window[24::24] / window[:-24:24])
    if len(daily) != FEATURE_BLOCKS:
        raise ValueError("lag strip block count mismatch")
    features = daily / scale
    if not np.isfinite(features).all():
        raise ValueError("lag strip contains non-finite values")
    eligible = bool(closes[signal_index] > closes[signal_index - E2160_HOURS])
    return features.astype(float), _finite(scale), eligible


def _build_anchor_table(
    frame: pd.DataFrame,
    *,
    start: int,
    end: int,
    labels: bool,
    exclude_last_label: bool,
) -> list[dict[str, Any]]:
    opens = frame["open"].to_numpy(dtype=float)
    closes = frame["close"].to_numpy(dtype=float)
    rows: list[dict[str, Any]] = []
    for anchor in range(start, end, DECISION_STEP):
        if labels and exclude_last_label and anchor + HORIZON >= end:
            continue
        features, scale, eligible = _feature_at(closes, anchor)
        record: dict[str, Any] = {
            "anchor": anchor,
            "signal_index": anchor - 25,
            "features": features,
            "scale": scale,
            "eligible": eligible,
        }
        if labels:
            if anchor + HORIZON >= len(opens):
                raise ValueError("label endpoint unavailable")
            record["utility"] = _finite(
                opens[anchor + HORIZON] / opens[anchor] - 1.0 - 2.0 * FEE_ONE_WAY
            )
        rows.append(record)
    return rows


def _fit_ridge(records: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [record for record in records if record["eligible"]]
    if len(eligible) < 1:
        raise ValueError("ridge fit has no eligible anchors")
    x = np.vstack([record["features"] for record in eligible])
    y = np.array([record["utility"] for record in eligible], dtype=float)
    means = x.mean(axis=0)
    stds = x.std(axis=0, ddof=0)
    if len(means) != FEATURE_BLOCKS or len(stds) != FEATURE_BLOCKS:
        raise ValueError("ridge feature dimension mismatch")
    if not np.isfinite(means).all() or not np.isfinite(stds).all() or np.any(stds <= 0):
        raise ValueError("ridge feature moments invalid")
    z = (x - means) / stds
    centered_y = y - y.mean()
    gram = z.T @ z + RIDGE_LAMBDA * np.eye(FEATURE_BLOCKS)
    rhs = z.T @ centered_y
    beta = np.linalg.solve(gram, rhs)
    intercept = _finite(y.mean())
    predictions = intercept + z @ beta
    if not np.isfinite(beta).all() or not np.isfinite(predictions).all():
        raise ValueError("ridge solution invalid")
    repeat_beta = np.linalg.solve(gram, rhs)
    repeat_identical = bool(np.array_equal(beta, repeat_beta))
    model_hash = hashlib.sha256(
        np.concatenate([means, stds, np.array([intercept]), beta]).astype("<f8").tobytes()
    ).hexdigest()
    return {
        "support": len(eligible),
        "feature_means": means,
        "feature_stds": stds,
        "intercept": intercept,
        "beta": beta,
        "beta_norm": _finite(np.linalg.norm(beta)),
        "condition_number": _finite(np.linalg.cond(gram)),
        "repeat_fit_identical": repeat_identical,
        "model_hash": model_hash,
        "fit_prediction_summary": _summary(predictions),
        "fit_utility_summary": _summary(y),
    }


def _predict(records: list[dict[str, Any]], model: dict[str, Any]) -> list[dict[str, Any]]:
    means = np.asarray(model["feature_means"], dtype=float)
    stds = np.asarray(model["feature_stds"], dtype=float)
    beta = np.asarray(model["beta"], dtype=float)
    predicted: list[dict[str, Any]] = []
    for record in records:
        z = (np.asarray(record["features"], dtype=float) - means) / stds
        value = _finite(model["intercept"] + z @ beta)
        predicted.append(
            {
                **record,
                "predicted_utility": value,
                "candidate": int(record["eligible"] and value > 0.0),
                "e2160": int(record["eligible"]),
            }
        )
    return predicted


def _hourly_positions(
    records: list[dict[str, Any]],
    *,
    start: int,
    end: int,
    key: str,
    delay_hours: int = 0,
) -> np.ndarray:
    positions = np.zeros(end - start, dtype=float)
    by_anchor = {int(record["anchor"]): float(record[key]) for record in records}
    current = 0.0
    for hour in range(start, end):
        decision_anchor = hour - delay_hours
        if decision_anchor in by_anchor:
            current = by_anchor[decision_anchor]
        positions[hour - start] = current
    return positions


def _strategy_path(
    frame: pd.DataFrame,
    records: list[dict[str, Any]],
    *,
    start: int,
    end: int,
    key: str,
    delay_hours: int = 0,
) -> dict[str, Any]:
    if end <= start or end >= len(frame):
        raise ValueError("invalid scored segment")
    opens = frame["open"].to_numpy(dtype=float)
    positions = _hourly_positions(records, start=start, end=end, key=key, delay_hours=delay_hours)
    asset_returns = opens[start + 1 : end + 1] / opens[start:end] - 1.0
    if len(asset_returns) != len(positions):
        raise ValueError("hourly strategy path mismatch")
    previous = np.concatenate([np.array([0.0]), positions[:-1]])
    turnover_by_hour = np.abs(positions - previous)
    gross_factors = 1.0 + positions * asset_returns
    fee_factors = 1.0 - FEE_ONE_WAY * turnover_by_hour
    net_factors = gross_factors * fee_factors
    terminal_turnover = abs(float(positions[-1]))
    net_factors[-1] *= 1.0 - FEE_ONE_WAY * terminal_turnover
    gross_equity = np.cumprod(gross_factors)
    net_equity = np.cumprod(net_factors)
    hourly_net = net_factors - 1.0
    hourly_gross = gross_factors - 1.0
    volatility = hourly_net.std(ddof=0)
    sharpe = 0.0 if volatility == 0 else hourly_net.mean() / volatility * math.sqrt(8_760.0)
    peaks = np.maximum.accumulate(np.concatenate([np.array([1.0]), net_equity]))
    equity_with_start = np.concatenate([np.array([1.0]), net_equity])
    drawdowns = equity_with_start / peaks - 1.0
    turnover = _finite(turnover_by_hour.sum() + terminal_turnover)
    transitions = int(np.count_nonzero(turnover_by_hour) + (terminal_turnover > 0))
    net_return = _finite(net_equity[-1] - 1.0)
    gross_return = _finite(gross_equity[-1] - 1.0)
    edge_per_turnover = None if turnover == 0 else _finite(10_000.0 * net_return / turnover)
    return {
        "start": start,
        "end": end,
        "hours": end - start,
        "gross_return": gross_return,
        "net_return": net_return,
        "annualized_hourly_sharpe": _finite(sharpe),
        "maximum_drawdown": _finite(drawdowns.min()),
        "exposure_hours": int(positions.sum()),
        "exposure_fraction": _finite(positions.mean()),
        "one_way_turnover": turnover,
        "transitions_including_liquidation": transitions,
        "modeled_fee_notional": _finite(FEE_ONE_WAY * turnover),
        "fee_drag": _finite(gross_return - net_return),
        "edge_per_turnover_bps": edge_per_turnover,
        "hourly_net_returns": hourly_net,
        "hourly_gross_returns": hourly_gross,
        "positions": positions,
    }


def _serializable_path(path: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in path.items() if not isinstance(value, np.ndarray)}


def _segment_metrics(
    frame: pd.DataFrame,
    records: list[dict[str, Any]],
    *,
    start: int,
    end: int,
    delay_hours: int = 0,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    paths = {
        "candidate": _strategy_path(
            frame,
            records,
            start=start,
            end=end,
            key="candidate",
            delay_hours=delay_hours,
        ),
        "e2160": _strategy_path(
            frame,
            records,
            start=start,
            end=end,
            key="e2160",
            delay_hours=delay_hours,
        ),
        "always_long": _strategy_path(
            frame,
            [{"anchor": start, "always_long": 1}],
            start=start,
            end=end,
            key="always_long",
            delay_hours=delay_hours,
        ),
    }
    return {name: _serializable_path(path) for name, path in paths.items()}, paths


def _folds(
    frame: pd.DataFrame,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    positive_relative: list[float] = []
    for fold in range(12):
        start = VALIDATION_END + fold * 1_080
        end = start + 1_080
        metrics, _ = _segment_metrics(frame, records, start=start, end=end)
        relative = metrics["candidate"]["net_return"] - metrics["e2160"]["net_return"]
        if relative > 0:
            positive_relative.append(relative)
        results.append(
            {
                "fold": fold + 1,
                "start": start,
                "end": end,
                "candidate_return": metrics["candidate"]["net_return"],
                "candidate_sharpe": metrics["candidate"]["annualized_hourly_sharpe"],
                "e2160_return": metrics["e2160"]["net_return"],
                "relative_return": _finite(relative),
            }
        )
    total_positive = sum(positive_relative)
    concentration = 1.0 if total_positive <= 0 else max(positive_relative) / total_positive
    return {
        "folds": results,
        "positive_candidate_return_folds": sum(row["candidate_return"] > 0 for row in results),
        "positive_relative_return_folds": sum(row["relative_return"] > 0 for row in results),
        "largest_positive_relative_fold_share": _finite(concentration),
    }


def _year_breadth(
    frame: pd.DataFrame,
    candidate_path: dict[str, Any],
    e2160_path: dict[str, Any],
    *,
    start: int,
) -> dict[str, Any]:
    timestamps = frame.index[start : start + len(candidate_path["hourly_net_returns"])]
    years = np.asarray([timestamp.year for timestamp in timestamps])
    results: list[dict[str, Any]] = []
    for year in sorted(set(years.tolist())):
        mask = years == year
        candidate_return = _finite(np.prod(1.0 + candidate_path["hourly_net_returns"][mask]) - 1.0)
        e2160_return = _finite(np.prod(1.0 + e2160_path["hourly_net_returns"][mask]) - 1.0)
        results.append(
            {
                "year": int(year),
                "hours": int(mask.sum()),
                "candidate_return": candidate_return,
                "e2160_return": e2160_return,
                "relative_return": _finite(candidate_return - e2160_return),
            }
        )
    return {
        "years": results,
        "positive_candidate_years": sum(row["candidate_return"] > 0 for row in results),
        "positive_relative_years": sum(row["relative_return"] > 0 for row in results),
    }


def _moving_block_indices(
    rng: np.random.Generator,
    observations: int,
    block: int,
) -> np.ndarray:
    if observations < block:
        raise ValueError("insufficient observations for moving-block bootstrap")
    count = math.ceil(observations / block)
    starts = rng.integers(0, observations - block + 1, size=count)
    offsets = np.arange(block)
    return (starts[:, None] + offsets[None, :]).reshape(-1)[:observations]


def _sharpe(values: np.ndarray) -> float:
    volatility = values.std(ddof=0)
    return 0.0 if volatility == 0 else _finite(values.mean() / volatility * math.sqrt(8_760.0))


def _bootstrap(candidate: np.ndarray, e2160: np.ndarray) -> dict[str, Any]:
    if len(candidate) != len(e2160):
        raise ValueError("paired bootstrap length mismatch")
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    mean_deltas = np.empty(BOOTSTRAP_DRAWS)
    sharpe_deltas = np.empty(BOOTSTRAP_DRAWS)
    for draw in range(BOOTSTRAP_DRAWS):
        indices = _moving_block_indices(rng, len(candidate), BOOTSTRAP_BLOCK_HOURS)
        c = candidate[indices]
        b = e2160[indices]
        mean_deltas[draw] = (c.mean() - b.mean()) * 8_760.0
        sharpe_deltas[draw] = _sharpe(c) - _sharpe(b)
    mean_bounds = np.quantile(mean_deltas, [0.025, 0.975])
    sharpe_bounds = np.quantile(sharpe_deltas, [0.025, 0.975])
    return {
        "draws": BOOTSTRAP_DRAWS,
        "block_hours": BOOTSTRAP_BLOCK_HOURS,
        "seed": BOOTSTRAP_SEED,
        "annualized_mean_return_delta": {
            "point": _finite((candidate.mean() - e2160.mean()) * 8_760.0),
            "lower_95": _finite(mean_bounds[0]),
            "upper_95": _finite(mean_bounds[1]),
        },
        "annualized_sharpe_delta": {
            "point": _finite(_sharpe(candidate) - _sharpe(e2160)),
            "lower_95": _finite(sharpe_bounds[0]),
            "upper_95": _finite(sharpe_bounds[1]),
        },
    }


def _source_summary(instrument: str, primary: Any, repeat: Any) -> dict[str, Any]:
    frame = primary.candles
    repeated = repeat.candles
    expected_index = pd.date_range(START, END, freq="h")
    if len(frame) != EXPECTED_ROWS or not frame.index.equals(expected_index):
        raise ValueError(f"{instrument} source does not match frozen hourly calendar")
    if not frame.equals(repeated):
        raise ValueError(f"{instrument} repeated normalization differs")
    for column in ("open", "high", "low", "close"):
        values = frame[column].to_numpy(dtype=float)
        if not np.isfinite(values).all() or not (values > 0).all():
            raise ValueError(f"{instrument} contains invalid {column} values")
    if frame.index.has_duplicates:
        raise ValueError(f"{instrument} source has duplicate hours")
    return {
        "instrument": instrument,
        "provider": primary.metadata.get("provider", "OKX"),
        "bar": primary.metadata.get("bar"),
        "rows": len(frame),
        "start": frame.index[0].isoformat(),
        "end": frame.index[-1].isoformat(),
        "normalized_csv_sha256": primary.metadata.get("normalized_csv_sha256"),
        "repeat_normalization_identical": True,
        "strict_hourly_grid": True,
        "finite_positive_ohlc": True,
        "duplicates": 0,
        "missing_intervals": int(primary.metadata.get("missing_intervals") or 0),
        "requested_start_reached": bool(primary.metadata.get("requested_start_reached")),
    }


def _fetch_source(instrument: str) -> tuple[Any, Any]:
    kwargs = {
        "inst_id": instrument,
        "start": START,
        "end": END,
        "pause_seconds": 0.12,
        "timeout": 20.0,
        "safety_pages": 100,
    }
    return fetch_okx_one_hour_candles(**kwargs), fetch_okx_one_hour_candles(**kwargs)


def _target_evidence(instrument: str, primary: Any, repeat: Any) -> dict[str, Any]:
    source = _source_summary(instrument, primary, repeat)
    frame = primary.candles
    fit_records = _build_anchor_table(
        frame,
        start=WARMUP_END,
        end=FIT_END,
        labels=True,
        exclude_last_label=True,
    )
    model = _fit_ridge(fit_records)
    fit_scored = _predict(fit_records, model)
    training_metrics, _ = _segment_metrics(
        frame,
        fit_scored,
        start=WARMUP_END,
        end=FIT_END,
    )
    validation_records = _build_anchor_table(
        frame,
        start=FIT_END,
        end=VALIDATION_END,
        labels=True,
        exclude_last_label=False,
    )
    validation_scored = _predict(validation_records, model)
    validation_metrics, validation_paths = _segment_metrics(
        frame,
        validation_scored,
        start=FIT_END,
        end=VALIDATION_END,
    )
    eligible_validation = [record for record in validation_scored if record["eligible"]]
    active_validation = [record for record in eligible_validation if record["candidate"]]
    prediction_values = np.array(
        [record["predicted_utility"] for record in eligible_validation], dtype=float
    )
    activity_fraction = (
        0.0 if not eligible_validation else len(active_validation) / len(eligible_validation)
    )

    prefix_frame = frame.iloc[: VALIDATION_END + 1].copy()
    prefix_fit_records = _build_anchor_table(
        prefix_frame,
        start=WARMUP_END,
        end=FIT_END,
        labels=True,
        exclude_last_label=True,
    )
    prefix_model = _fit_ridge(prefix_fit_records)
    prefix_validation = _predict(
        _build_anchor_table(
            prefix_frame,
            start=FIT_END,
            end=VALIDATION_END,
            labels=True,
            exclude_last_label=False,
        ),
        prefix_model,
    )
    prefix_predictions = np.array(
        [record["predicted_utility"] for record in prefix_validation], dtype=float
    )
    full_predictions = np.array(
        [record["predicted_utility"] for record in validation_scored], dtype=float
    )
    prefix_invariant = bool(
        model["model_hash"] == prefix_model["model_hash"]
        and np.array_equal(prefix_predictions, full_predictions)
    )

    gates = {
        "source_rows_and_chronology": source["rows"] == EXPECTED_ROWS,
        "fit_support_at_least_100": model["support"] >= 100,
        "validation_support_at_least_70": len(eligible_validation) >= 70,
        "thirty_finite_nonconstant_features": bool(
            len(model["feature_stds"]) == FEATURE_BLOCKS
            and np.isfinite(model["feature_stds"]).all()
            and np.all(model["feature_stds"] > 0)
        ),
        "finite_repeatable_ridge_solution": bool(
            model["repeat_fit_identical"]
            and math.isfinite(model["condition_number"])
            and np.isfinite(model["beta"]).all()
        ),
        "positive_validation_prediction_std": bool(
            len(prediction_values) > 1 and prediction_values.std(ddof=0) > 0
        ),
        "validation_activity_between_10_and_90_percent": bool(
            0.10 <= activity_fraction <= 0.90
        ),
        "positive_validation_net_return": validation_metrics["candidate"]["net_return"] > 0,
        "positive_validation_sharpe": (
            validation_metrics["candidate"]["annualized_hourly_sharpe"] > 0
        ),
        "prefix_invariance": prefix_invariant,
        "causal_signal_cutoff": all(
            record["signal_index"] == record["anchor"] - 25
            for record in fit_records + validation_records
        ),
        "exact_fee_contract": FEE_ONE_WAY == 0.0005,
    }
    validation_pass = all(gates.values())

    oos: dict[str, Any] | None = None
    full: dict[str, Any] | None = None
    robustness: dict[str, Any] | None = None
    all_scored_records: list[dict[str, Any]] | None = None
    if validation_pass:
        oos_records = _predict(
            _build_anchor_table(
                frame,
                start=VALIDATION_END,
                end=OOS_END,
                labels=False,
                exclude_last_label=False,
            ),
            model,
        )
        all_scored_records = fit_scored + validation_scored + oos_records
        oos_metrics, oos_paths = _segment_metrics(
            frame,
            oos_records,
            start=VALIDATION_END,
            end=OOS_END,
        )
        full_metrics, full_paths = _segment_metrics(
            frame,
            all_scored_records,
            start=WARMUP_END,
            end=OOS_END,
        )
        delayed_metrics, _ = _segment_metrics(
            frame,
            oos_records,
            start=VALIDATION_END,
            end=OOS_END,
            delay_hours=1,
        )
        fold_evidence = _folds(frame, oos_records)
        year_evidence = _year_breadth(
            frame,
            full_paths["candidate"],
            full_paths["e2160"],
            start=WARMUP_END,
        )
        bootstrap = _bootstrap(
            oos_paths["candidate"]["hourly_net_returns"],
            oos_paths["e2160"]["hourly_net_returns"],
        )
        oos = oos_metrics
        full = full_metrics
        robustness = {
            "fold_breadth": fold_evidence,
            "year_breadth": year_evidence,
            "bootstrap": bootstrap,
            "one_hour_delay": delayed_metrics,
            "candidate_exposure_return": _finite(
                np.prod(1.0 + oos_paths["candidate"]["hourly_gross_returns"]) - 1.0
            ),
            "e2160_exposure_return": _finite(
                np.prod(1.0 + oos_paths["e2160"]["hourly_gross_returns"]) - 1.0
            ),
            "full_candidate_hourly_return_hash": hashlib.sha256(
                full_paths["candidate"]["hourly_net_returns"].astype("<f8").tobytes()
            ).hexdigest(),
        }

    serial_model = {
        "support": model["support"],
        "feature_means": model["feature_means"].tolist(),
        "feature_stds": model["feature_stds"].tolist(),
        "intercept": model["intercept"],
        "beta": model["beta"].tolist(),
        "beta_norm": model["beta_norm"],
        "condition_number": model["condition_number"],
        "repeat_fit_identical": model["repeat_fit_identical"],
        "model_hash": model["model_hash"],
        "fit_prediction_summary": model["fit_prediction_summary"],
        "fit_utility_summary": model["fit_utility_summary"],
    }
    return {
        "instrument": instrument,
        "source": source,
        "model": serial_model,
        "training": {
            "metrics": training_metrics,
            "in_sample_descriptive_only": True,
        },
        "validation": {
            "scheduled_anchors": len(validation_records),
            "eligible_anchors": len(eligible_validation),
            "active_candidate_anchors": len(active_validation),
            "activity_fraction_of_eligible": _finite(activity_fraction),
            "prediction_summary": _summary(prediction_values),
            "metrics": validation_metrics,
        },
        "gates": gates,
        "validation_pass": validation_pass,
        "sealed_oos_accessed": validation_pass,
        "oos": oos,
        "full": full,
        "robustness": robustness,
        "prefix_invariance": {
            "model_hash_identical": model["model_hash"] == prefix_model["model_hash"],
            "validation_predictions_exactly_identical": bool(
                np.array_equal(prefix_predictions, full_predictions)
            ),
            "sealed_oos_and_unread_suffix_removed": True,
        },
        "all_scored_records": all_scored_records,
    }


def _acceptance(target: dict[str, Any]) -> dict[str, bool]:
    if not target["validation_pass"] or target["oos"] is None or target["full"] is None:
        return {"validation_authorized_oos": False}
    oos = target["oos"]
    full = target["full"]
    robust = target["robustness"]
    candidate = oos["candidate"]
    base = oos["e2160"]
    always = oos["always_long"]
    full_candidate = full["candidate"]
    full_base = full["e2160"]
    folds = robust["fold_breadth"]
    years = robust["year_breadth"]
    bootstrap = robust["bootstrap"]
    delayed = robust["one_hour_delay"]
    return {
        "validation_authorized_oos": True,
        "oos_candidate_positive": candidate["net_return"] > 0
        and candidate["annualized_hourly_sharpe"] > 0,
        "full_candidate_positive": full_candidate["net_return"] > 0
        and full_candidate["annualized_hourly_sharpe"] > 0,
        "oos_beats_e2160": candidate["net_return"] > base["net_return"]
        and candidate["annualized_hourly_sharpe"] > base["annualized_hourly_sharpe"],
        "full_beats_e2160": full_candidate["net_return"] > full_base["net_return"]
        and full_candidate["annualized_hourly_sharpe"]
        > full_base["annualized_hourly_sharpe"],
        "oos_beats_always_long": candidate["net_return"] > always["net_return"]
        and candidate["annualized_hourly_sharpe"] > always["annualized_hourly_sharpe"],
        "turnover_not_above_e2160": candidate["one_way_turnover"] <= base["one_way_turnover"],
        "edge_per_turnover_beats_e2160": bool(
            candidate["edge_per_turnover_bps"] is not None
            and base["edge_per_turnover_bps"] is not None
            and candidate["edge_per_turnover_bps"] > 0
            and candidate["edge_per_turnover_bps"] > base["edge_per_turnover_bps"]
        ),
        "drawdown_gate": candidate["maximum_drawdown"]
        >= base["maximum_drawdown"] - 0.05
        and candidate["maximum_drawdown"] > always["maximum_drawdown"],
        "fold_breadth": folds["positive_candidate_return_folds"] >= 7
        and folds["positive_relative_return_folds"] >= 7,
        "year_breadth": years["positive_candidate_years"] >= 3
        and years["positive_relative_years"] >= 2,
        "fold_concentration": folds["largest_positive_relative_fold_share"] <= 0.50,
        "bootstrap_lower_bounds_positive": (
            bootstrap["annualized_mean_return_delta"]["lower_95"] > 0
            and bootstrap["annualized_sharpe_delta"]["lower_95"] > 0
        ),
        "one_hour_delay_positive_relative": (
            delayed["candidate"]["net_return"] > 0
            and delayed["candidate"]["annualized_hourly_sharpe"] > 0
            and delayed["candidate"]["net_return"] > delayed["e2160"]["net_return"]
            and delayed["candidate"]["annualized_hourly_sharpe"]
            > delayed["e2160"]["annualized_hourly_sharpe"]
        ),
    }


def _report(evidence: dict[str, Any]) -> str:
    lines = [
        "# Frozen ridge lag-strip utility selector 1H",
        "",
        f"- Exact head: `{evidence['exact_head']}`",
        f"- Verdict: `{evidence['verdict']}`",
        f"- Candidate/grid: `{evidence['candidate_count']}/{evidence['parameter_grid_count']}`",
        f"- OOS accessed: `{evidence['sealed_oos_performance_accessed']}`",
        "- Fee: exactly 5 bps one way on actual exposure changes",
        "",
        "## Validation",
        "",
        "| Target | Fit | Validation eligible | Active share | Net return | Sharpe | Verdict |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for target in evidence["targets"]:
        validation = target["validation"]
        candidate = validation["metrics"]["candidate"]
        lines.append(
            "| {instrument} | {support} | {eligible} | {activity:.2%} | {net:.2%} | "
            "{sharpe:.3f} | {verdict} |".format(
                instrument=target["instrument"],
                support=target["model"]["support"],
                eligible=validation["eligible_anchors"],
                activity=validation["activity_fraction_of_eligible"],
                net=candidate["net_return"],
                sharpe=candidate["annualized_hourly_sharpe"],
                verdict="PASS" if target["validation_pass"] else "REJECT",
            )
        )
    lines.extend(["", "## Gate failures", ""])
    for target in evidence["targets"]:
        failed = [name for name, passed in target["gates"].items() if not passed]
        lines.append(f"- **{target['instrument']}**: {', '.join(failed) if failed else 'none'}")
    if evidence["sealed_oos_performance_accessed"]:
        lines.extend(["", "## OOS and full economics", ""])
        for target in evidence["targets"]:
            lines.append(f"### {target['instrument']}")
            lines.append("")
            for segment_name in ("oos", "full"):
                segment = target[segment_name]
                candidate = segment["candidate"]
                base = segment["e2160"]
                lines.append(
                    f"- {segment_name.upper()} candidate: {candidate['net_return']:.2%}, "
                    f"Sharpe {candidate['annualized_hourly_sharpe']:.3f}, "
                    f"DD {candidate['maximum_drawdown']:.2%}, turnover "
                    f"{candidate['one_way_turnover']:.1f}."
                )
                lines.append(
                    f"- {segment_name.upper()} E2160: {base['net_return']:.2%}, "
                    f"Sharpe {base['annualized_hourly_sharpe']:.3f}, "
                    f"DD {base['maximum_drawdown']:.2%}, turnover "
                    f"{base['one_way_turnover']:.1f}."
                )
    else:
        lines.extend(
            [
                "",
                "## OOS accounting",
                "",
                "OOS, full-period, fold/year, uncertainty, and delay metrics are null because the "
                "bilateral validation gate failed before OOS access.",
            ]
        )
    lines.extend(
        [
            "",
            "## Remaining blocker",
            "",
            evidence["remaining_blocker"],
            "",
            "## Next experiment",
            "",
            f"`{evidence['next_strategy_experiment']}`",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    exact_head = os.environ.get("GITHUB_SHA", "").strip()
    if len(exact_head) != 40:
        raise ValueError("GITHUB_SHA must be an exact 40-character revision")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    targets: list[dict[str, Any]] = []
    for instrument in TARGETS:
        primary, repeat = _fetch_source(instrument)
        targets.append(_target_evidence(instrument, primary, repeat))

    bilateral_validation = all(target["validation_pass"] for target in targets)
    acceptance_vectors = [_acceptance(target) for target in targets]
    bilateral_acceptance = bilateral_validation and all(
        all(vector.values()) for vector in acceptance_vectors
    )
    verdict = (
        "accept_causal_own_price_ridge_lag_strip_utility_selector_for_canonical_review_1h_v1"
        if bilateral_acceptance
        else "reject_causal_own_price_ridge_lag_strip_utility_selector_1h_v1"
    )
    remaining_blocker = (
        "The frozen supervised selector did not establish bilateral validation transport with "
        "sufficient support, activity, positive fee-adjusted return, and positive Sharpe."
        if not bilateral_validation
        else "The selector passed validation but failed at least one bilateral OOS economics, "
        "turnover-efficiency, breadth, dependence, drawdown, or delay gate."
    )
    next_experiment = (
        "causal-own-price-ridge-lag-strip-utility-selector-canonical-review-1h-v1"
        if bilateral_acceptance
        else "causal-own-price-linear-supervised-selector-programme-closure-1h-v1"
    )

    for target in targets:
        target.pop("all_scored_records", None)
    evidence = {
        "family_id": FAMILY_ID,
        "exact_head": exact_head,
        "canonical_main": "5a0fcc97d1a882f8223656c51f5bb8055f534e38",
        "candidate_count": 1,
        "parameter_grid_count": 0,
        "fixed_targets": list(TARGETS),
        "bar": "1H",
        "canonical_fee_bps_one_way": 5.0,
        "source_calendar": {"start": START.isoformat(), "end": END.isoformat()},
        "segments": {
            "warmup": [0, WARMUP_END],
            "model_fit": [WARMUP_END, FIT_END],
            "validation": [FIT_END, VALIDATION_END],
            "development_oos": [VALIDATION_END, OOS_END],
            "unread_suffix": [UNREAD_SUFFIX_START, EXPECTED_ROWS],
        },
        "targets": targets,
        "bilateral_validation_pass": bilateral_validation,
        "sealed_oos_performance_accessed": bilateral_validation,
        "acceptance_vectors": acceptance_vectors,
        "bilateral_acceptance": bilateral_acceptance,
        "verdict": verdict,
        "remaining_blocker": remaining_blocker,
        "next_strategy_experiment": next_experiment,
        "cross_sectional_selection": False,
        "target_pooling": False,
        "shorting": False,
        "leverage": False,
        "credentials_used": False,
        "private_endpoints_used": False,
        "orders_or_adapters_enabled": False,
        "synthetic_market_data_used": False,
        "canonical_mutation_authorized": bilateral_acceptance,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
    }
    evidence_text = _canonical_json(evidence)
    evidence_sha = hashlib.sha256(evidence_text.encode("utf-8")).hexdigest()
    report = _report(evidence)
    (output_dir / "evidence.json").write_text(evidence_text, encoding="utf-8")
    (output_dir / "evidence.sha256").write_text(evidence_sha + "\n", encoding="utf-8")
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    print("STRATEGY_EVIDENCE=" + evidence_text.strip())
    print("EVIDENCE_SHA256=" + evidence_sha)


if __name__ == "__main__":
    main()
