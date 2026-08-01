from __future__ import annotations

import math
import statistics
from collections import Counter
from datetime import datetime, timezone
from typing import Any

import numpy as np

from same_asset_index_source import (
    BOOTSTRAP_BLOCK,
    BOOTSTRAP_DRAWS,
    BOOTSTRAP_SEED,
    FEE,
    FULL_END,
    HOUR_MS,
    OOS_END,
    START_MS,
    TRAIN_END,
    WARMUP_END,
    Series,
    canonical_bytes,
    sha256_bytes,
    utc_iso,
)


def quarter_key(ms: int) -> str:
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    return f"{dt.year}-Q{(dt.month - 1) // 3 + 1}"


def year_key(ms: int) -> int:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).year


def first_decision_at_or_after(start: int) -> int:
    if start <= WARMUP_END:
        return WARMUP_END
    offset = start - WARMUP_END
    return WARMUP_END + math.ceil(offset / 24) * 24


def signal_values(
    spot: Series, index: Series, t: int
) -> tuple[float, float, bool, bool]:
    spot_margin = math.log(spot.closes[t - 1] / spot.closes[t - 2161])
    index_margin = math.log(index.closes[t - 1] / index.closes[t - 2161])
    return spot_margin, index_margin, spot_margin > 0, index_margin > 0


def build_path(
    spot: Series,
    index: Series,
    start: int,
    end: int,
    *,
    kind: str,
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    position = np.zeros(end - start, dtype=np.int8)
    current = 0
    events: list[dict[str, Any]] = []
    for t in range(first_decision_at_or_after(start), end, 24):
        spot_margin, index_margin, spot_positive, index_positive = signal_values(
            spot, index, t
        )
        veto = False
        if kind == "candidate":
            if current == 0:
                veto = spot_positive and not index_positive
                current = int(spot_positive and index_positive)
            else:
                current = int(spot_positive)
        elif kind == "e2160":
            current = int(spot_positive)
        elif kind == "cash":
            current = 0
        else:
            raise ValueError(f"unknown path kind {kind}")
        lo, hi = max(t, start), min(t + 24, end)
        if lo < hi:
            position[lo - start : hi - start] = current
        events.append(
            {
                "execution_index": t,
                "execution_open": utc_iso(int(spot.open_ms[t])),
                "spot_margin": spot_margin,
                "index_margin": index_margin,
                "target": current,
                "entry_veto": veto,
                "quarter": quarter_key(int(spot.open_ms[t])),
                "year": year_key(int(spot.open_ms[t])),
            }
        )
    return position, events


def shifted_path(position: np.ndarray) -> np.ndarray:
    delayed = np.zeros_like(position)
    if len(position) > 1:
        delayed[1:] = position[:-1]
    return delayed


def always_long(start: int, end: int) -> np.ndarray:
    return np.ones(end - start, dtype=np.int8)


def max_drawdown(hourly: np.ndarray) -> float:
    equity = np.concatenate(([1.0], np.cumprod(1.0 + hourly)))
    return float(np.min(equity / np.maximum.accumulate(equity) - 1.0))


def finite_or_none(value: float | None) -> float | None:
    if value is None or not math.isfinite(float(value)):
        return None
    return float(value)


def episodes(position: np.ndarray) -> dict[str, Any]:
    runs: dict[int, list[int]] = {0: [], 1: []}
    if len(position):
        current = int(position[0])
        length = 1
        for raw in position[1:]:
            value = int(raw)
            if value == current:
                length += 1
            else:
                runs[current].append(length)
                current, length = value, 1
        runs[current].append(length)
    return {
        "long_count": len(runs[1]),
        "cash_count": len(runs[0]),
        "long_median_hours": finite_or_none(
            statistics.median(runs[1]) if runs[1] else None
        ),
        "long_max_hours": max(runs[1], default=0),
        "cash_median_hours": finite_or_none(
            statistics.median(runs[0]) if runs[0] else None
        ),
        "cash_max_hours": max(runs[0], default=0),
    }


def simulate(
    spot: Series, position: np.ndarray, start: int, end: int
) -> dict[str, Any]:
    asset = spot.opens[start + 1 : end + 1] / spot.opens[start:end] - 1.0
    prior = np.concatenate((np.zeros(1, dtype=np.int8), position[:-1]))
    changes = np.abs(position - prior).astype(float)
    fees = FEE * changes
    terminal = float(position[-1]) if len(position) else 0.0
    if len(fees):
        fees[-1] += FEE * terminal
    turnover = float(np.sum(changes) + terminal)
    gross = position.astype(float) * asset
    net = gross - fees
    mean = float(np.mean(net))
    std = float(np.std(net, ddof=1)) if len(net) > 1 else 0.0
    exposure_hours = int(np.sum(position))
    return {
        "start_index": start,
        "end_index": end,
        "hours": end - start,
        "start_open": utc_iso(int(spot.open_ms[start])),
        "end_open": utc_iso(int(spot.open_ms[end])),
        "gross_compound_return": float(np.prod(1.0 + gross) - 1.0),
        "net_compound_return": float(np.prod(1.0 + net) - 1.0),
        "arithmetic_net_return": float(np.sum(net)),
        "annualised_arithmetic_mean": mean * 8760,
        "annualised_hourly_sharpe": finite_or_none(
            mean / std * math.sqrt(8760) if std > 0 else None
        ),
        "maximum_drawdown": max_drawdown(net),
        "exposure_hours": exposure_hours,
        "exposure_fraction": exposure_hours / len(position),
        "one_way_turnover": turnover,
        "transition_count": int(np.count_nonzero(changes) + (1 if terminal else 0)),
        "modeled_fees": float(np.sum(fees)),
        "edge_per_turnover_bps": finite_or_none(
            float(np.sum(net)) / turnover * 10_000 if turnover else None
        ),
        "episodes": episodes(position),
        "hourly_net_returns": net,
        "hourly_gross_returns": gross,
        "asset_returns": asset,
        "position": position,
        "fees": fees,
    }


def strip_arrays(record: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in record.items() if not isinstance(value, np.ndarray)
    }


def vector_sharpe(matrix: np.ndarray) -> np.ndarray:
    means = np.mean(matrix, axis=1)
    stds = np.std(matrix, axis=1, ddof=1)
    return (
        np.divide(means, stds, out=np.zeros_like(means), where=stds > 0)
        * math.sqrt(8760)
    )


def paired_bootstrap(candidate: np.ndarray, benchmark: np.ndarray) -> dict[str, Any]:
    n = len(candidate)
    blocks = math.ceil(n / BOOTSTRAP_BLOCK)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    mean_deltas: list[np.ndarray] = []
    sharpe_deltas: list[np.ndarray] = []
    for offset in range(0, BOOTSTRAP_DRAWS, 50):
        batch = min(50, BOOTSTRAP_DRAWS - offset)
        starts = rng.integers(
            0, n - BOOTSTRAP_BLOCK + 1, size=(batch, blocks)
        )
        indices = (
            starts[:, :, None] + np.arange(BOOTSTRAP_BLOCK)[None, None, :]
        ).reshape(batch, -1)[:, :n]
        candidate_draw = candidate[indices]
        benchmark_draw = benchmark[indices]
        mean_deltas.append(
            np.mean(candidate_draw - benchmark_draw, axis=1) * 8760
        )
        sharpe_deltas.append(
            vector_sharpe(candidate_draw) - vector_sharpe(benchmark_draw)
        )

    def summary(chunks: list[np.ndarray]) -> dict[str, float]:
        values = np.concatenate(chunks)
        lower, median, upper = np.percentile(values, [2.5, 50, 97.5])
        return {
            "lower_95": float(lower),
            "median": float(median),
            "upper_95": float(upper),
            "zero_mass": float(np.mean(values == 0.0)),
            "nonpositive_mass": float(np.mean(values <= 0.0)),
        }

    return {
        "draws": BOOTSTRAP_DRAWS,
        "block_hours": BOOTSTRAP_BLOCK,
        "seed": BOOTSTRAP_SEED,
        "non_circular_common_index": True,
        "annualised_mean_return_difference": summary(mean_deltas),
        "annualised_sharpe_difference": summary(sharpe_deltas),
    }


def support_record(spot: Series, index: Series) -> dict[str, Any]:
    _, events = build_path(spot, index, WARMUP_END, TRAIN_END, kind="candidate")
    vetoes = [event for event in events if event["entry_veto"]]
    quarters = Counter(event["quarter"] for event in vetoes)
    largest_share = max(quarters.values(), default=0) / len(vetoes) if vetoes else None
    spot_close_bytes = canonical_bytes([float(value) for value in spot.closes])
    index_close_bytes = canonical_bytes([float(value) for value in index.closes])
    gates = {
        "at_least_20_training_vetoes": len(vetoes) >= 20,
        "at_least_4_training_quarters": len(quarters) >= 4,
        "largest_quarter_share_at_most_50pct": (
            largest_share is not None and largest_share <= 0.5
        ),
        "index_not_byte_identical_to_spot": spot_close_bytes != index_close_bytes,
    }
    return {
        "training_decisions": len(events),
        "training_vetoes": len(vetoes),
        "vetoes_by_quarter": dict(sorted(quarters.items())),
        "distinct_veto_quarters": len(quarters),
        "largest_veto_quarter_share": finite_or_none(largest_share),
        "spot_close_series_sha256": sha256_bytes(spot_close_bytes),
        "index_close_series_sha256": sha256_bytes(index_close_bytes),
        "gates": gates,
        "passes": all(gates.values()),
    }


def evaluate_market(spot: Series, index: Series, support: dict[str, Any]) -> dict[str, Any]:
    segments = {
        "training": (WARMUP_END, TRAIN_END),
        "oos": (TRAIN_END, OOS_END),
        "full": (WARMUP_END, FULL_END),
    }
    strategies: dict[str, dict[str, Any]] = {
        "candidate": {},
        "e2160": {},
        "always_long": {},
    }
    raw: dict[str, dict[str, dict[str, Any]]] = {
        "candidate": {},
        "e2160": {},
        "always_long": {},
    }
    event_sets: dict[str, list[dict[str, Any]]] = {}
    for segment, (start, end) in segments.items():
        candidate_position, candidate_events = build_path(
            spot, index, start, end, kind="candidate"
        )
        e2160_position, _ = build_path(spot, index, start, end, kind="e2160")
        paths = {
            "candidate": candidate_position,
            "e2160": e2160_position,
            "always_long": always_long(start, end),
        }
        event_sets[segment] = candidate_events
        for name, position in paths.items():
            result = simulate(spot, position, start, end)
            raw[name][segment] = result
            strategies[name][segment] = strip_arrays(result)

    candidate_oos = raw["candidate"]["oos"]
    e2160_oos = raw["e2160"]["oos"]
    candidate_delayed = simulate(
        spot,
        shifted_path(candidate_oos["position"]),
        TRAIN_END,
        OOS_END,
    )
    e2160_delayed = simulate(
        spot,
        shifted_path(e2160_oos["position"]),
        TRAIN_END,
        OOS_END,
    )

    folds: list[dict[str, Any]] = []
    for fold in range(6):
        start = TRAIN_END + fold * 2160
        end = start + 2160
        candidate_position, events = build_path(
            spot, index, start, end, kind="candidate"
        )
        e2160_position, _ = build_path(spot, index, start, end, kind="e2160")
        candidate_result = simulate(spot, candidate_position, start, end)
        e2160_result = simulate(spot, e2160_position, start, end)
        folds.append(
            {
                "fold": fold + 1,
                "start": utc_iso(int(spot.open_ms[start])),
                "end": utc_iso(int(spot.open_ms[end])),
                "candidate_net_return": candidate_result["net_compound_return"],
                "e2160_net_return": e2160_result["net_compound_return"],
                "relative_effect": candidate_result["net_compound_return"]
                - e2160_result["net_compound_return"],
                "entry_vetoes": sum(event["entry_veto"] for event in events),
            }
        )

    years: list[dict[str, Any]] = []
    for year in (2024, 2025):
        start = max(
            TRAIN_END,
            int(
                (
                    int(datetime(year, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
                    - START_MS
                )
                // HOUR_MS
            ),
        )
        end = min(
            OOS_END,
            int(
                (
                    int(
                        datetime(year + 1, 1, 1, tzinfo=timezone.utc).timestamp()
                        * 1000
                    )
                    - START_MS
                )
                // HOUR_MS
            ),
        )
        if start >= end:
            continue
        candidate_position, events = build_path(
            spot, index, start, end, kind="candidate"
        )
        e2160_position, _ = build_path(spot, index, start, end, kind="e2160")
        candidate_result = simulate(spot, candidate_position, start, end)
        e2160_result = simulate(spot, e2160_position, start, end)
        years.append(
            {
                "year": year,
                "candidate_net_return": candidate_result["net_compound_return"],
                "e2160_net_return": e2160_result["net_compound_return"],
                "relative_effect": candidate_result["net_compound_return"]
                - e2160_result["net_compound_return"],
                "entry_vetoes": sum(event["entry_veto"] for event in events),
            }
        )

    positive_relative = [max(0.0, fold["relative_effect"]) for fold in folds]
    positive_total = sum(positive_relative)
    concentration = (
        max(positive_relative, default=0.0) / positive_total
        if positive_total > 0
        else None
    )
    uncertainty = paired_bootstrap(
        candidate_oos["hourly_net_returns"], e2160_oos["hourly_net_returns"]
    )
    gross_timing = float(
        np.sum(
            candidate_oos["hourly_gross_returns"]
            - e2160_oos["hourly_gross_returns"]
        )
    )
    relative_fee = float(np.sum(e2160_oos["fees"] - candidate_oos["fees"]))
    net_difference = float(
        np.sum(candidate_oos["hourly_net_returns"] - e2160_oos["hourly_net_returns"])
    )
    decomposition = {
        "gross_timing_arithmetic": gross_timing,
        "relative_fee_arithmetic": relative_fee,
        "net_arithmetic": net_difference,
        "identity_error": net_difference - gross_timing - relative_fee,
    }
    if abs(decomposition["identity_error"]) > 1e-12:
        raise RuntimeError(f"{spot.inst_id}: return decomposition identity failed")

    candidate = strategies["candidate"]["oos"]
    e2160 = strategies["e2160"]["oos"]
    always = strategies["always_long"]["oos"]
    candidate_full = strategies["candidate"]["full"]
    negative_infinity = lambda value: -math.inf if value is None else value
    gates = {
        "1_positive_oos_net_and_sharpe": (
            candidate["net_compound_return"] > 0
            and negative_infinity(candidate["annualised_hourly_sharpe"]) > 0
        ),
        "2_exceeds_e2160_net_and_sharpe": (
            candidate["net_compound_return"] > e2160["net_compound_return"]
            and negative_infinity(candidate["annualised_hourly_sharpe"])
            > negative_infinity(e2160["annualised_hourly_sharpe"])
        ),
        "3_exceeds_always_long_net_and_sharpe": (
            candidate["net_compound_return"] > always["net_compound_return"]
            and negative_infinity(candidate["annualised_hourly_sharpe"])
            > negative_infinity(always["annualised_hourly_sharpe"])
        ),
        "4_positive_full_net_and_sharpe": (
            candidate_full["net_compound_return"] > 0
            and negative_infinity(candidate_full["annualised_hourly_sharpe"]) > 0
        ),
        "5_drawdown_no_worse_than_e2160": (
            candidate["maximum_drawdown"] >= e2160["maximum_drawdown"]
        ),
        "6_turnover_no_greater_than_e2160": (
            candidate["one_way_turnover"] <= e2160["one_way_turnover"]
        ),
        "7_edge_per_turnover_exceeds_e2160": (
            negative_infinity(candidate["edge_per_turnover_bps"])
            > negative_infinity(e2160["edge_per_turnover_bps"])
        ),
        "8_positive_fold_breadth": (
            sum(fold["candidate_net_return"] > 0 for fold in folds) >= 4
        ),
        "9_relative_fold_breadth": (
            sum(fold["relative_effect"] > 0 for fold in folds) >= 4
        ),
        "10_year_breadth": (
            len(years) == 2
            and all(
                year["candidate_net_return"] > 0 and year["relative_effect"] > 0
                for year in years
            )
        ),
        "11_positive_fold_concentration": (
            concentration is not None and concentration <= 0.5
        ),
        "12_positive_dependence_aware_lower_bounds": (
            uncertainty["annualised_mean_return_difference"]["lower_95"] > 0
            and uncertainty["annualised_sharpe_difference"]["lower_95"] > 0
        ),
        "13_positive_gross_timing_contribution": gross_timing > 0,
        "14_one_hour_delay": (
            candidate_delayed["net_compound_return"] > 0
            and negative_infinity(candidate_delayed["annualised_hourly_sharpe"])
            > negative_infinity(e2160_delayed["annualised_hourly_sharpe"])
            and candidate_delayed["net_compound_return"]
            > e2160_delayed["net_compound_return"]
            and negative_infinity(candidate_delayed["edge_per_turnover_bps"]) > 0
        ),
        "15_oos_veto_support": (
            sum(fold["entry_vetoes"] > 0 for fold in folds) >= 4
            and len(years) == 2
            and all(year["entry_vetoes"] > 0 for year in years)
        ),
    }
    return {
        "target": spot.inst_id,
        "index": index.inst_id,
        "source_rows": len(spot.open_ms),
        "training_support": support,
        "strategies": strategies,
        "oos_folds": folds,
        "oos_years": years,
        "positive_relative_fold_contribution_concentration": finite_or_none(
            concentration
        ),
        "paired_uncertainty": uncertainty,
        "candidate_minus_e2160_oos": decomposition,
        "one_hour_delay_oos": {
            "candidate": strip_arrays(candidate_delayed),
            "e2160": strip_arrays(e2160_delayed),
        },
        "oos_entry_vetoes": sum(
            event["entry_veto"] for event in event_sets["oos"]
        ),
        "gates": gates,
        "gates_passed": sum(gates.values()),
        "passes_individual_gates": all(gates.values()),
    }
