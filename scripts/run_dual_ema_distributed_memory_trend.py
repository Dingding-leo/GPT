from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from gpt_quant.okx_1h import fetch_okx_one_hour_candles

FAMILY_ID = "causal-own-price-dual-ema-distributed-memory-trend-1h-v1"
START = "2023-04-01T00:00:00Z"
END = "2025-12-31T23:00:00Z"
SUFFIX_END = "2026-01-01T00:00:00Z"
EXPECTED_ROWS = 24_144
WARMUP_END = 4_320
TRAIN_START = 4_320
TRAIN_END = 10_800
OOS_START = 10_800
OOS_END = 23_760
SCORE_END = 23_760
FAST_SPAN = 720
SLOW_SPAN = 2_160
ALPHA_FAST = 2.0 / (FAST_SPAN + 1.0)
ALPHA_SLOW = 2.0 / (SLOW_SPAN + 1.0)
FEE = 0.0005
BOOTSTRAP_DRAWS = 5_000
BOOTSTRAP_BLOCK = 168
SEEDS = {"LTC-USDT": 2026080803, "DOGE-USDT": 2026080804}
TARGETS = ("LTC-USDT", "DOGE-USDT")
OUTPUT = Path("reports/research/dual-ema-distributed-memory-trend-1h-v1")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: object) -> bytes:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return (text + "\n").encode()


def _csv_bytes(frame: pd.DataFrame) -> bytes:
    text = frame.reset_index(names="timestamp").to_csv(
        index=False,
        date_format="%Y-%m-%dT%H:%M:%S.%fZ",
        float_format="%.12g",
        lineterminator="\n",
    )
    return text.encode()


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, np.generic):
        return _clean(value.item())
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return value


def _finite_positive_ohlc(frame: pd.DataFrame) -> bool:
    values = frame[["open", "high", "low", "close"]].to_numpy(dtype=float)
    if not np.isfinite(values).all() or not (values > 0).all():
        return False
    return bool(
        (frame["high"] >= frame[["open", "close"]].max(axis=1)).all()
        and (frame["low"] <= frame[["open", "close"]].min(axis=1)).all()
        and (frame["high"] >= frame["low"]).all()
    )


def _fetch(inst_id: str, *, end: str) -> object:
    return fetch_okx_one_hour_candles(
        inst_id=inst_id,
        start=START,
        end=end,
        limit=100,
        pause_seconds=0.10,
        timeout=20.0,
        safety_pages=12,
    )


def _persist_source(inst_id: str, snapshot: object) -> dict[str, str]:
    source_dir = OUTPUT / "source" / inst_id
    source_dir.mkdir(parents=True, exist_ok=True)
    stem = f"okx-{inst_id}-1H"
    csv_data = _csv_bytes(snapshot.candles)
    raw_data = _json_bytes(snapshot.raw_pages)
    metadata_data = _json_bytes(snapshot.metadata)
    (source_dir / f"{stem}.csv").write_bytes(csv_data)
    (source_dir / f"{stem}.raw.json").write_bytes(raw_data)
    (source_dir / f"{stem}.metadata.json").write_bytes(metadata_data)
    normalized_sha = str(snapshot.metadata.get("normalized_csv_sha256"))
    raw_sha = str(snapshot.metadata.get("raw_pages_sha256"))
    if _sha256(csv_data) != normalized_sha:
        raise ValueError(f"{inst_id}: persisted normalized CSV hash mismatch")
    if _sha256(raw_data) != raw_sha:
        raise ValueError(f"{inst_id}: persisted raw pages hash mismatch")
    return {
        "normalized_csv_sha256": normalized_sha,
        "raw_pages_sha256": raw_sha,
        "metadata_sha256": _sha256(metadata_data),
    }


def _acquire(inst_id: str) -> tuple[pd.DataFrame, dict[str, object]]:
    primary = _fetch(inst_id, end=END)
    repeat = _fetch(inst_id, end=END)
    suffix = _fetch(inst_id, end=SUFFIX_END)
    frame = primary.candles.copy()
    repeated = repeat.candles.copy()
    suffix_frame = suffix.candles.copy()
    for item in (frame, repeated, suffix_frame):
        item.columns = [str(column).lower() for column in item.columns]

    if len(frame) != EXPECTED_ROWS or len(repeated) != EXPECTED_ROWS:
        raise ValueError(f"{inst_id}: frozen source row count is not {EXPECTED_ROWS}")
    if len(suffix_frame) != EXPECTED_ROWS + 1:
        raise ValueError(f"{inst_id}: suffix source does not add exactly one hour")
    if not frame.equals(repeated):
        raise ValueError(f"{inst_id}: repeated normalized source is not identical")
    if not frame.equals(suffix_frame.iloc[:EXPECTED_ROWS]):
        raise ValueError(f"{inst_id}: future suffix changes the frozen prefix")
    expected = pd.date_range(START, END, freq="h")
    if not frame.index.equals(expected):
        raise ValueError(f"{inst_id}: source does not match exact UTC-hour grid")
    if not _finite_positive_ohlc(frame):
        raise ValueError(f"{inst_id}: invalid OHLC")
    if primary.metadata.get("instrument_id") != inst_id:
        raise ValueError(f"{inst_id}: provider instrument identity mismatch")
    if primary.metadata.get("bar") != "1H":
        raise ValueError(f"{inst_id}: provider bar identity mismatch")
    if primary.metadata.get("missing_intervals") not in (0, None):
        raise ValueError(f"{inst_id}: provider reports missing intervals")

    persisted = _persist_source(inst_id, primary)
    return frame, {
        "instrument": inst_id,
        "rows": len(frame),
        "start": str(frame.index[0]),
        "end": str(frame.index[-1]),
        "pages": primary.metadata.get("pages"),
        **persisted,
        "repeat_normalized_csv_sha256": repeat.metadata.get("normalized_csv_sha256"),
        "repeat_identity": frame.equals(repeated),
        "suffix_rows": len(suffix_frame),
        "suffix_prefix_identity": frame.equals(suffix_frame.iloc[:EXPECTED_ROWS]),
        "finite_positive_ohlc": True,
        "completed_hourly_grid": True,
    }


def _ema(values: np.ndarray, alpha: float) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    if values.ndim != 1 or len(values) == 0 or not np.isfinite(values).all():
        raise ValueError("EMA input must be finite non-empty one-dimensional values")
    result = np.empty_like(values)
    result[0] = values[0]
    one_minus = 1.0 - alpha
    for index in range(1, len(values)):
        result[index] = alpha * values[index] + one_minus * result[index - 1]
    return result


def _signals(frame: pd.DataFrame) -> dict[str, np.ndarray]:
    close = frame["close"].to_numpy(dtype=float)
    log_close = np.log(close)
    fast = _ema(log_close, ALPHA_FAST)
    slow = _ema(log_close, ALPHA_SLOW)
    score = fast - slow
    candidate = np.zeros(len(frame), dtype=np.int8)
    e2160 = np.zeros(len(frame), dtype=np.int8)
    always = np.ones(len(frame), dtype=np.int8)
    for anchor in range(WARMUP_END, min(SCORE_END, len(frame)), 24):
        candidate[anchor] = int(score[anchor - 1] > 0.0)
        e2160[anchor] = int(close[anchor - 1] > close[anchor - 2161])
    return {
        "fast": fast,
        "slow": slow,
        "score": score,
        "candidate": candidate,
        "e2160": e2160,
        "always_long": always,
    }


def _run_stats(positions: np.ndarray, state: int) -> dict[str, object]:
    mask = np.asarray(positions, dtype=np.int8) == state
    durations: list[int] = []
    start: int | None = None
    for index, active in enumerate(mask):
        if active and start is None:
            start = index
        elif not active and start is not None:
            durations.append(index - start)
            start = None
    if start is not None:
        durations.append(len(mask) - start)
    if not durations:
        return {"episodes": 0, "mean_hours": 0.0, "median_hours": 0.0, "max_hours": 0}
    array = np.asarray(durations, dtype=float)
    return {
        "episodes": len(durations),
        "mean_hours": float(array.mean()),
        "median_hours": float(np.median(array)),
        "max_hours": int(array.max()),
    }


def _signal_at(signal: np.ndarray, anchor: int, name: str) -> int:
    if name == "always_long":
        return 1
    return int(signal[anchor])


def _simulate(
    frame: pd.DataFrame,
    signal: np.ndarray,
    *,
    signal_name: str,
    start: int,
    end: int,
    delay_hours: int = 0,
) -> dict[str, object]:
    if not (0 <= start < end < len(frame)):
        raise ValueError("invalid simulation bounds")
    opens = frame["open"].to_numpy(dtype=float)
    scheduled: dict[int, int] = {}
    for anchor in range(start, end, 24):
        execution = anchor + delay_hours
        if execution < end:
            scheduled[execution] = _signal_at(signal, anchor, signal_name)

    position = 0
    turnover = 0.0
    transitions = 0
    net_factors = np.ones(end - start, dtype=float)
    gross_factors = np.ones(end - start, dtype=float)
    held = np.zeros(end - start, dtype=np.int8)
    net_wealth_path = np.ones(end - start + 1, dtype=float)
    gross_wealth_path = np.ones(end - start + 1, dtype=float)

    for offset, hour in enumerate(range(start, end)):
        fee_factor = 1.0
        if hour in scheduled:
            desired = int(scheduled[hour])
            change = abs(desired - position)
            if change:
                turnover += float(change)
                transitions += 1
                fee_factor *= 1.0 - FEE * change
                position = desired
        held[offset] = position
        market_return = float(opens[hour + 1] / opens[hour] - 1.0)
        market_factor = 1.0 + position * market_return
        gross_factors[offset] = market_factor
        net_factors[offset] = fee_factor * market_factor
        if hour == end - 1 and position:
            turnover += float(position)
            transitions += 1
            net_factors[offset] *= 1.0 - FEE * abs(position)
            position = 0
        gross_wealth_path[offset + 1] = gross_wealth_path[offset] * gross_factors[offset]
        net_wealth_path[offset + 1] = net_wealth_path[offset] * net_factors[offset]

    hourly_net = net_factors - 1.0
    mean = float(hourly_net.mean())
    std = float(hourly_net.std(ddof=0))
    sharpe = float(mean / std * math.sqrt(8760.0)) if std > 0 else float("nan")
    annual_mean = mean * 8760.0
    peaks = np.maximum.accumulate(net_wealth_path)
    drawdown = net_wealth_path / peaks - 1.0
    net_return = float(net_wealth_path[-1] - 1.0)
    gross_return = float(gross_wealth_path[-1] - 1.0)
    edge_turn = float(hourly_net.sum() / turnover * 10_000.0) if turnover > 0 else float("nan")
    return {
        "start_index": start,
        "end_index": end,
        "delay_hours": delay_hours,
        "gross_return": gross_return,
        "net_return": net_return,
        "annualized_arithmetic_mean": annual_mean,
        "sharpe": sharpe,
        "maximum_drawdown": float(drawdown.min()),
        "exposure_fraction": float(held.mean()),
        "exposure_hours": int(held.sum()),
        "one_way_turnover": turnover,
        "transition_count_including_terminal_liquidation": transitions,
        "modeled_fee_notional_fraction": float(FEE * turnover),
        "compounded_fee_drag": float(gross_return - net_return),
        "edge_per_turnover_bps": edge_turn,
        "long_episodes": _run_stats(held, 1),
        "cash_episodes": _run_stats(held, 0),
        "hourly_net_returns": hourly_net,
        "hourly_positions": held,
        "net_wealth_path": net_wealth_path,
    }


def _compact(path: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in path.items()
        if key not in {"hourly_net_returns", "hourly_positions", "net_wealth_path"}
    }


def _bootstrap(candidate: np.ndarray, benchmark: np.ndarray, seed: int) -> dict[str, list[float]]:
    candidate = np.asarray(candidate, dtype=float)
    benchmark = np.asarray(benchmark, dtype=float)
    n = len(candidate)
    if len(benchmark) != n or n < BOOTSTRAP_BLOCK:
        raise ValueError("invalid bootstrap vectors")
    rng = np.random.default_rng(seed)
    blocks_needed = math.ceil(n / BOOTSTRAP_BLOCK)
    mean_delta = np.empty(BOOTSTRAP_DRAWS, dtype=float)
    sharpe_delta = np.empty(BOOTSTRAP_DRAWS, dtype=float)
    max_start = n - BOOTSTRAP_BLOCK
    for draw in range(BOOTSTRAP_DRAWS):
        starts = rng.integers(0, max_start + 1, size=blocks_needed)
        indices = np.concatenate(
            [np.arange(start, start + BOOTSTRAP_BLOCK, dtype=int) for start in starts]
        )[:n]
        cand = candidate[indices]
        base = benchmark[indices]
        mean_delta[draw] = float(cand.mean() - base.mean())
        cand_std = float(cand.std(ddof=0))
        base_std = float(base.std(ddof=0))
        cand_sharpe = float(cand.mean() / cand_std * math.sqrt(8760.0)) if cand_std > 0 else np.nan
        base_sharpe = float(base.mean() / base_std * math.sqrt(8760.0)) if base_std > 0 else np.nan
        sharpe_delta[draw] = cand_sharpe - base_sharpe

    def interval(values: np.ndarray) -> list[float]:
        finite = values[np.isfinite(values)]
        if len(finite) != len(values):
            return [float("nan"), float("nan")]
        return [float(np.quantile(finite, 0.025)), float(np.quantile(finite, 0.975))]

    raw = interval(mean_delta)
    return {
        "mean_hourly_net_return_delta": raw,
        "annualized_arithmetic_mean_delta": [raw[0] * 8760.0, raw[1] * 8760.0],
        "annualized_sharpe_delta": interval(sharpe_delta),
    }


def _year_segments(frame: pd.DataFrame) -> list[tuple[int, int, int]]:
    result: list[tuple[int, int, int]] = []
    timestamps = frame.index
    for year in sorted(set(timestamps[OOS_START:OOS_END].year)):
        indices = np.flatnonzero((timestamps.year == year) & (np.arange(len(frame)) >= OOS_START) & (np.arange(len(frame)) < OOS_END))
        if len(indices) == 0:
            continue
        start = int(indices[0])
        end = int(indices[-1] + 1)
        if start % 24 != 0 or end % 24 != 0:
            raise ValueError(f"calendar-year segment {year} is not daily aligned")
        result.append((int(year), start, end))
    return result


def _analyze(inst_id: str, frame: pd.DataFrame) -> dict[str, object]:
    signals = _signals(frame)
    candidate_signal = signals["candidate"]
    base_signal = signals["e2160"]
    always_signal = signals["always_long"]
    segments = {
        "training": (TRAIN_START, TRAIN_END),
        "oos": (OOS_START, OOS_END),
        "full": (TRAIN_START, SCORE_END),
    }
    paths: dict[str, dict[str, dict[str, object]]] = {}
    raw_paths: dict[str, dict[str, dict[str, object]]] = {}
    for segment_name, (start, end) in segments.items():
        raw_paths[segment_name] = {}
        paths[segment_name] = {}
        for name, signal in (
            ("candidate", candidate_signal),
            ("e2160", base_signal),
            ("always_long", always_signal),
        ):
            result = _simulate(frame, signal, signal_name=name, start=start, end=end)
            raw_paths[segment_name][name] = result
            paths[segment_name][name] = _compact(result)

    delayed_candidate = _simulate(
        frame, candidate_signal, signal_name="candidate", start=OOS_START, end=OOS_END, delay_hours=1
    )
    delayed_base = _simulate(
        frame, base_signal, signal_name="e2160", start=OOS_START, end=OOS_END, delay_hours=1
    )

    folds: list[dict[str, object]] = []
    for fold in range(6):
        start = OOS_START + fold * 2160
        end = start + 2160
        candidate = _simulate(frame, candidate_signal, signal_name="candidate", start=start, end=end)
        base = _simulate(frame, base_signal, signal_name="e2160", start=start, end=end)
        folds.append(
            {
                "fold": fold + 1,
                "start": str(frame.index[start]),
                "end_exclusive": str(frame.index[end]),
                "candidate_net_return": candidate["net_return"],
                "e2160_net_return": base["net_return"],
                "relative_return": float(candidate["net_return"] - base["net_return"]),
            }
        )

    positive_relative = [max(float(item["relative_return"]), 0.0) for item in folds]
    positive_total = sum(positive_relative)
    concentration = max(positive_relative) / positive_total if positive_total > 0 else 1.0

    years: list[dict[str, object]] = []
    for year, start, end in _year_segments(frame):
        candidate = _simulate(frame, candidate_signal, signal_name="candidate", start=start, end=end)
        base = _simulate(frame, base_signal, signal_name="e2160", start=start, end=end)
        years.append(
            {
                "year": year,
                "candidate_net_return": candidate["net_return"],
                "e2160_net_return": base["net_return"],
                "relative_return": float(candidate["net_return"] - base["net_return"]),
            }
        )

    oos_candidate = raw_paths["oos"]["candidate"]
    oos_base = raw_paths["oos"]["e2160"]
    uncertainty = _bootstrap(
        np.asarray(oos_candidate["hourly_net_returns"], dtype=float),
        np.asarray(oos_base["hourly_net_returns"], dtype=float),
        SEEDS[inst_id],
    )

    positions_candidate = np.asarray(oos_candidate["hourly_positions"], dtype=float)
    positions_base = np.asarray(oos_base["hourly_positions"], dtype=float)
    opens = frame["open"].to_numpy(dtype=float)
    gross_hourly = opens[OOS_START + 1 : OOS_END + 1] / opens[OOS_START:OOS_END] - 1.0
    gross_timing_delta = float(np.sum((positions_candidate - positions_base) * gross_hourly))
    decomposition = {
        "candidate_only_hours": int(np.sum((positions_candidate == 1) & (positions_base == 0))),
        "e2160_only_hours": int(np.sum((positions_candidate == 0) & (positions_base == 1))),
        "shared_long_hours": int(np.sum((positions_candidate == 1) & (positions_base == 1))),
        "candidate_only_gross_arithmetic_contribution": float(
            gross_hourly[(positions_candidate == 1) & (positions_base == 0)].sum()
        ),
        "e2160_only_gross_arithmetic_contribution": float(
            gross_hourly[(positions_candidate == 0) & (positions_base == 1)].sum()
        ),
        "gross_timing_delta": gross_timing_delta,
        "relative_fee_notional_fraction": float(
            FEE * (float(oos_candidate["one_way_turnover"]) - float(oos_base["one_way_turnover"]))
        ),
        "relative_exposure_hours": int(positions_candidate.sum() - positions_base.sum()),
    }

    score_anchors = np.asarray(
        [signals["score"][anchor - 1] for anchor in range(OOS_START, OOS_END, 24)], dtype=float
    )
    disagreement = np.asarray(
        [candidate_signal[anchor] != base_signal[anchor] for anchor in range(OOS_START, OOS_END, 24)], dtype=bool
    )

    log_close = np.log(frame["close"].to_numpy(dtype=float))
    replay_fast = _ema(log_close, ALPHA_FAST)
    replay_slow = _ema(log_close, ALPHA_SLOW)
    truncated = frame.iloc[: SCORE_END + 1].copy()
    truncated_signals = _signals(truncated)
    truncated_oos = _simulate(
        truncated,
        truncated_signals["candidate"],
        signal_name="candidate",
        start=OOS_START,
        end=OOS_END,
    )
    structural = {
        "alpha_fast_in_0_1": bool(0.0 < ALPHA_FAST < 1.0),
        "alpha_slow_in_0_1": bool(0.0 < ALPHA_SLOW < 1.0),
        "fast_alpha_gt_slow_alpha": bool(ALPHA_FAST > ALPHA_SLOW),
        "ema_fast_exact_replay": bool(np.array_equal(signals["fast"], replay_fast)),
        "ema_slow_exact_replay": bool(np.array_equal(signals["slow"], replay_slow)),
        "finite_scores": bool(np.isfinite(score_anchors).all()),
        "warmup_exceeds_five_slow_half_lives": bool(
            WARMUP_END > 5.0 * math.log(0.5) / math.log(1.0 - ALPHA_SLOW)
        ),
        "daily_utc_midnight_anchors": bool(
            all(frame.index[anchor].hour == 0 for anchor in range(TRAIN_START, SCORE_END, 24))
        ),
        "signal_prefix_invariant": bool(
            np.array_equal(
                candidate_signal[TRAIN_START:SCORE_END],
                truncated_signals["candidate"][TRAIN_START:SCORE_END],
            )
        ),
        "position_prefix_invariant": bool(
            np.array_equal(
                np.asarray(oos_candidate["hourly_positions"]),
                np.asarray(truncated_oos["hourly_positions"]),
            )
        ),
        "return_prefix_invariant": bool(
            np.array_equal(
                np.asarray(oos_candidate["hourly_net_returns"]),
                np.asarray(truncated_oos["hourly_net_returns"]),
            )
        ),
    }
    structural_pass = all(structural.values())

    train_c = paths["training"]["candidate"]
    oos_c = paths["oos"]["candidate"]
    full_c = paths["full"]["candidate"]
    oos_b = paths["oos"]["e2160"]
    full_b = paths["full"]["e2160"]
    oos_a = paths["oos"]["always_long"]

    gates = {
        "candidate_train_oos_full_return_positive": all(
            float(item["net_return"]) > 0 for item in (train_c, oos_c, full_c)
        ),
        "candidate_oos_full_sharpe_positive": all(
            float(item["sharpe"]) > 0 for item in (oos_c, full_c)
        ),
        "candidate_beats_e2160_oos_return_sharpe": bool(
            float(oos_c["net_return"]) > float(oos_b["net_return"])
            and float(oos_c["sharpe"]) > float(oos_b["sharpe"])
        ),
        "candidate_beats_e2160_full_return_sharpe": bool(
            float(full_c["net_return"]) > float(full_b["net_return"])
            and float(full_c["sharpe"]) > float(full_b["sharpe"])
        ),
        "candidate_beats_always_long_oos_return_sharpe": bool(
            float(oos_c["net_return"]) > float(oos_a["net_return"])
            and float(oos_c["sharpe"]) > float(oos_a["sharpe"])
        ),
        "drawdown_gate": bool(
            float(oos_c["maximum_drawdown"]) >= float(oos_b["maximum_drawdown"]) - 0.05
            and float(oos_c["maximum_drawdown"]) > float(oos_a["maximum_drawdown"])
        ),
        "turnover_gate": bool(
            float(oos_c["one_way_turnover"]) <= 2.0 * float(oos_b["one_way_turnover"])
            and float(oos_c["one_way_turnover"]) <= 80.0
        ),
        "edge_per_turnover_gate": bool(
            float(oos_c["edge_per_turnover_bps"]) > 0
            and float(oos_c["edge_per_turnover_bps"]) > float(oos_b["edge_per_turnover_bps"])
        ),
        "fold_breadth_gate": bool(
            sum(float(item["candidate_net_return"]) > 0 for item in folds) >= 4
            and sum(float(item["relative_return"]) > 0 for item in folds) >= 4
        ),
        "year_breadth_gate": bool(
            len(years) >= 2
            and all(float(item["candidate_net_return"]) > 0 for item in years)
            and sum(float(item["relative_return"]) > 0 for item in years) >= 2
        ),
        "positive_relative_fold_concentration_gate": bool(concentration <= 0.50),
        "dependence_lower_bounds_positive": bool(
            uncertainty["mean_hourly_net_return_delta"][0] > 0
            and uncertainty["annualized_sharpe_delta"][0] > 0
        ),
        "one_hour_delay_gate": bool(
            float(delayed_candidate["net_return"]) > 0
            and float(delayed_candidate["sharpe"]) > 0
            and float(delayed_candidate["net_return"]) > float(delayed_base["net_return"])
            and float(delayed_candidate["sharpe"]) > float(delayed_base["sharpe"])
        ),
        "gross_timing_delta_positive": bool(gross_timing_delta > 0),
        "structural_and_prefix_gate": bool(structural_pass),
    }
    passed = all(gates.values())

    return {
        "instrument": inst_id,
        "candidate_count": 1,
        "parameter_grid_count": 0,
        "ema": {
            "fast_span": FAST_SPAN,
            "slow_span": SLOW_SPAN,
            "alpha_fast": ALPHA_FAST,
            "alpha_slow": ALPHA_SLOW,
            "oos_score_quantiles": {
                "q05": float(np.quantile(score_anchors, 0.05)),
                "q25": float(np.quantile(score_anchors, 0.25)),
                "q50": float(np.quantile(score_anchors, 0.50)),
                "q75": float(np.quantile(score_anchors, 0.75)),
                "q95": float(np.quantile(score_anchors, 0.95)),
            },
            "oos_candidate_e2160_disagreement_rate": float(disagreement.mean()),
        },
        "paths": paths,
        "oos_folds": folds,
        "oos_years": years,
        "largest_positive_relative_fold_contribution": float(concentration),
        "uncertainty": uncertainty,
        "one_hour_delay": {
            "candidate": _compact(delayed_candidate),
            "e2160": _compact(delayed_base),
            "net_return_delta": float(delayed_candidate["net_return"] - delayed_base["net_return"]),
            "sharpe_delta": float(delayed_candidate["sharpe"] - delayed_base["sharpe"]),
        },
        "oos_decomposition": decomposition,
        "structural": structural,
        "gates": gates,
        "passed": bool(passed),
    }


def _protocol() -> dict[str, object]:
    return {
        "family_id": FAMILY_ID,
        "base_main": "5a0fcc97d1a882f8223656c51f5bb8055f534e38",
        "targets": list(TARGETS),
        "provider": "OKX anonymous public SPOT",
        "bar": "1H",
        "start": START,
        "end": END,
        "expected_rows": EXPECTED_ROWS,
        "warmup_end": WARMUP_END,
        "train": [TRAIN_START, TRAIN_END],
        "oos": [OOS_START, OOS_END],
        "score_end": SCORE_END,
        "candidate_count": 1,
        "parameter_grid_count": 0,
        "fast_span": FAST_SPAN,
        "slow_span": SLOW_SPAN,
        "alpha_fast": ALPHA_FAST,
        "alpha_slow": ALPHA_SLOW,
        "fee_one_way": FEE,
        "bootstrap_draws": BOOTSTRAP_DRAWS,
        "bootstrap_block_hours": BOOTSTRAP_BLOCK,
        "bootstrap_seeds": SEEDS,
    }


def _report(evidence: dict[str, object]) -> str:
    lines = [
        "# Dual-EMA distributed-memory trend 1H v1",
        "",
        f"- verdict: `{evidence['verdict']}`",
        f"- source contract passed: `{evidence['source_contract_passed']}`",
        f"- targets passing: `{evidence['targets_passing']}/{len(TARGETS)}`",
        f"- candidate/grid: `1/0`",
        f"- fee: exactly `{FEE:.4%}` one way on actual exposure changes",
        "",
    ]
    if evidence.get("source_failure"):
        lines += ["## Source failure", "", f"`{evidence['source_failure']}`", ""]
    for target in evidence.get("targets", []):
        lines += [f"## {target['instrument']}", ""]
        for segment in ("training", "oos", "full"):
            lines.append(f"### {segment}")
            lines.append("")
            lines.append("| path | net return | Sharpe | max DD | turnover | edge/turn bp | exposure |")
            lines.append("|---|---:|---:|---:|---:|---:|---:|")
            for name in ("candidate", "e2160", "always_long"):
                item = target["paths"][segment][name]
                lines.append(
                    f"| {name} | {item['net_return']:.6f} | {item['sharpe']:.6f} | "
                    f"{item['maximum_drawdown']:.6f} | {item['one_way_turnover']:.1f} | "
                    f"{item['edge_per_turnover_bps']:.4f} | {item['exposure_fraction']:.4f} |"
                )
            lines.append("")
        lines += [
            "### robustness",
            "",
            f"- profitable / relative-positive OOS folds: "
            f"`{sum(float(x['candidate_net_return']) > 0 for x in target['oos_folds'])}/6` / "
            f"`{sum(float(x['relative_return']) > 0 for x in target['oos_folds'])}/6`",
            f"- positive relative fold concentration: `{target['largest_positive_relative_fold_contribution']:.6f}`",
            f"- mean-return delta CI: `{target['uncertainty']['mean_hourly_net_return_delta']}`",
            f"- Sharpe-delta CI: `{target['uncertainty']['annualized_sharpe_delta']}`",
            f"- delayed net return / Sharpe delta: "
            f"`{target['one_hour_delay']['net_return_delta']:.6f}` / `{target['one_hour_delay']['sharpe_delta']:.6f}`",
            f"- gross timing delta: `{target['oos_decomposition']['gross_timing_delta']:.6f}`",
            f"- passed: `{target['passed']}`",
            "",
            "### gates",
            "",
        ]
        for name, passed in target["gates"].items():
            lines.append(f"- `{name}`: `{passed}`")
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    protocol = _protocol()
    protocol_data = _json_bytes(protocol)
    (OUTPUT / "protocol.json").write_bytes(protocol_data)

    frames: dict[str, pd.DataFrame] = {}
    sources: list[dict[str, object]] = []
    source_failure: str | None = None
    for inst_id in TARGETS:
        try:
            frame, source = _acquire(inst_id)
            frames[inst_id] = frame
            sources.append(source)
        except Exception as exc:
            source_failure = f"{inst_id}: {type(exc).__name__}: {exc}"
            break

    targets: list[dict[str, object]] = []
    if source_failure is None and len(frames) == len(TARGETS):
        for inst_id in TARGETS:
            targets.append(_analyze(inst_id, frames[inst_id]))
    targets_passing = sum(bool(target.get("passed")) for target in targets)
    bilateral = targets_passing == len(TARGETS)
    if source_failure is not None:
        verdict = "reject_causal_own_price_dual_ema_distributed_memory_trend_source_contract_1h_v1"
    elif bilateral:
        verdict = "accept_causal_own_price_dual_ema_distributed_memory_trend_for_canonical_review_1h_v1"
    else:
        verdict = "reject_causal_own_price_dual_ema_distributed_memory_trend_1h_v1"

    evidence = _clean(
        {
            "schema_version": "dual-ema-distributed-memory-trend-evidence-v1",
            "family_id": FAMILY_ID,
            "protocol_sha256": _sha256(protocol_data),
            "candidate_count": 1,
            "parameter_grid_count": 0,
            "source_contract_passed": source_failure is None and len(frames) == len(TARGETS),
            "source_failure": source_failure,
            "sources": sources,
            "strategy_performance_accessed": bool(targets),
            "oos_accessed": bool(targets),
            "canonical_mutation": False,
            "paper_trading_authorized": False,
            "live_trading_authorized": False,
            "targets": targets,
            "targets_passing": targets_passing,
            "bilateral_pass": bilateral,
            "verdict": verdict,
        }
    )
    evidence_data = _json_bytes(evidence)
    report_text = _report(evidence)
    (OUTPUT / "evidence.json").write_bytes(evidence_data)
    (OUTPUT / "report.md").write_text(report_text, encoding="utf-8")
    manifest = {
        "protocol_sha256": _sha256(protocol_data),
        "evidence_sha256": _sha256(evidence_data),
        "report_sha256": _sha256(report_text.encode()),
    }
    (OUTPUT / "manifest.json").write_bytes(_json_bytes(manifest))
    print(json.dumps(evidence, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
