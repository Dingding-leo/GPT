from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from gpt_quant.okx_1h import fetch_okx_one_hour_candles

FAMILY_ID = "causal-own-price-dfa-persistence-opportunity-1h-v1"
START = "2023-04-01T00:00:00Z"
END = "2025-12-31T23:00:00Z"
EXPECTED_ROWS = 24_144
TRAIN_START = 2_208
TRAIN_END = 10_800
OOS_END = 23_760
SOURCE_END = 24_144
FEATURE_EMBARGO_HOURS = 25
DFA_WINDOW = 720
DFA_SCALES = (12, 24, 48, 72, 120, 144, 180)
E2160_HOURS = 2_160
FEE_ONE_WAY = 0.0005
ROUND_TRIP_FEE = 2 * FEE_ONE_WAY
BOOTSTRAP_DRAWS = 5_000
BOOTSTRAP_BLOCK = 7
BOOTSTRAP_SEED = 20260808
TARGETS = ("ATOM-USDT", "LINK-USDT")
OUTPUT = Path("reports/research/dfa-persistence-1h-v1")
REJECT_VERDICT = "reject_causal_own_price_dfa_persistence_information_premise_1h_v1"
SUPPORT_VERDICT = (
    "support_causal_own_price_dfa_persistence_for_separate_candidate_preregistration_1h_v1"
)


def _json_bytes(value: object) -> bytes:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return (text + "\n").encode()


def _csv_bytes(frame: pd.DataFrame) -> bytes:
    text = frame.reset_index(names="timestamp").to_csv(
        index=False,
        date_format="%Y-%m-%dT%H:%M:%S.%fZ",
        float_format="%.12g",
        lineterminator="\n",
    )
    return text.encode()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _finite_positive_ohlc(candles: pd.DataFrame) -> bool:
    columns = ["open", "high", "low", "close"]
    values = candles[columns].to_numpy(dtype=float)
    if not np.isfinite(values).all() or not (values > 0).all():
        return False
    return bool(
        (candles["high"] >= candles[["open", "close"]].max(axis=1)).all()
        and (candles["low"] <= candles[["open", "close"]].min(axis=1)).all()
        and (candles["high"] >= candles["low"]).all()
    )


def _write_primary_snapshot(inst_id: str, snapshot: object) -> dict[str, str]:
    source_dir = OUTPUT / "source" / inst_id
    source_dir.mkdir(parents=True, exist_ok=True)
    stem = f"okx-{inst_id}-1H"
    candles = snapshot.candles
    csv_data = _csv_bytes(candles)
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
        raise ValueError(f"{inst_id}: persisted raw-page hash mismatch")
    return {
        "normalized_csv_sha256": normalized_sha,
        "raw_pages_sha256": raw_sha,
        "metadata_sha256": _sha256(metadata_data),
    }


def _fetch(inst_id: str) -> object:
    return fetch_okx_one_hour_candles(
        inst_id=inst_id,
        start=START,
        end=END,
        limit=100,
        pause_seconds=0.12,
        timeout=20.0,
        safety_pages=2,
    )


def _acquire_series(inst_id: str) -> tuple[pd.DataFrame, dict[str, object]]:
    primary = _fetch(inst_id)
    repeat = _fetch(inst_id)

    candles = primary.candles.copy()
    repeat_candles = repeat.candles.copy()
    candles.columns = [str(column).lower() for column in candles.columns]
    repeat_candles.columns = [str(column).lower() for column in repeat_candles.columns]

    expected_index = pd.date_range(START, END, freq="h")
    if len(candles) != EXPECTED_ROWS or len(repeat_candles) != EXPECTED_ROWS:
        raise ValueError(f"{inst_id}: frozen source row count is not {EXPECTED_ROWS}")
    if not candles.index.equals(expected_index):
        raise ValueError(f"{inst_id}: source does not match exact frozen UTC-hour grid")
    if not repeat_candles.index.equals(expected_index):
        raise ValueError(f"{inst_id}: repeated source grid differs from frozen grid")
    if not candles.equals(repeat_candles):
        raise ValueError(f"{inst_id}: repeated normalized acquisition is not identical")
    if not _finite_positive_ohlc(candles):
        raise ValueError(f"{inst_id}: source contains invalid OHLC")
    if primary.metadata.get("instrument_id") != inst_id:
        raise ValueError(f"{inst_id}: provider instrument identity mismatch")
    if primary.metadata.get("bar") != "1H":
        raise ValueError(f"{inst_id}: provider bar identity mismatch")
    if primary.metadata.get("missing_intervals") not in (0, None):
        raise ValueError(f"{inst_id}: provider reports missing intervals")
    if primary.metadata.get("incomplete_rows_removed") not in (0, None):
        raise ValueError(f"{inst_id}: requested historical grid contained incomplete candles")

    persisted = _write_primary_snapshot(inst_id, primary)
    repeat_sha = str(repeat.metadata.get("normalized_csv_sha256"))
    if repeat_sha != persisted["normalized_csv_sha256"]:
        raise ValueError(f"{inst_id}: repeated source hash differs")
    evidence = {
        "instrument": inst_id,
        "rows": int(len(candles)),
        "start": str(candles.index[0]),
        "end": str(candles.index[-1]),
        "pages": int(primary.metadata.get("pages", 0)),
        "normalized_csv_sha256": persisted["normalized_csv_sha256"],
        "raw_pages_sha256": persisted["raw_pages_sha256"],
        "metadata_sha256": persisted["metadata_sha256"],
        "repeat_normalized_csv_sha256": repeat_sha,
        "repeat_identity": True,
        "finite_positive_ohlc": True,
        "completed_hourly_grid": True,
        "missing_intervals": int(primary.metadata.get("missing_intervals") or 0),
        "incomplete_rows_removed": int(primary.metadata.get("incomplete_rows_removed") or 0),
    }
    return candles, evidence


def _training_anchors() -> list[int]:
    return [
        anchor
        for anchor in range(TRAIN_START, TRAIN_END, 24)
        if anchor + 25 < TRAIN_END
    ]


def _dfa_alpha_from_returns(returns: np.ndarray) -> float:
    values = np.asarray(returns, dtype=float)
    if values.shape != (DFA_WINDOW,) or not np.isfinite(values).all():
        return float("nan")
    profile = np.cumsum(values - float(values.mean()))
    fluctuation: list[float] = []
    for scale in DFA_SCALES:
        if DFA_WINDOW % scale != 0:
            raise ValueError("DFA scale must divide the frozen 720H window")
        boxes = profile.reshape(DFA_WINDOW // scale, scale)
        x = np.arange(scale, dtype=float)
        x_centered = x - float(x.mean())
        denominator = float(np.dot(x_centered, x_centered))
        residual_sum_squares = 0.0
        for box in boxes:
            box_mean = float(box.mean())
            slope = float(np.dot(x_centered, box - box_mean) / denominator)
            intercept = box_mean - slope * float(x.mean())
            residual = box - (intercept + slope * x)
            residual_sum_squares += float(np.dot(residual, residual))
        f_scale = float(np.sqrt(residual_sum_squares / DFA_WINDOW))
        if not np.isfinite(f_scale) or f_scale <= 0:
            return float("nan")
        fluctuation.append(f_scale)

    log_scale = np.log(np.asarray(DFA_SCALES, dtype=float))
    log_f = np.log(np.asarray(fluctuation, dtype=float))
    x_centered = log_scale - float(log_scale.mean())
    denominator = float(np.dot(x_centered, x_centered))
    if denominator <= 0:
        return float("nan")
    slope = float(np.dot(x_centered, log_f - float(log_f.mean())) / denominator)
    return slope if np.isfinite(slope) else float("nan")


def _dfa_alpha(close: np.ndarray, anchor: int) -> float:
    u = anchor - FEATURE_EMBARGO_HOURS
    first_close = u - DFA_WINDOW
    if first_close < 0 or u >= len(close):
        return float("nan")
    segment = np.asarray(close[first_close : u + 1], dtype=float)
    if segment.shape != (DFA_WINDOW + 1,):
        return float("nan")
    if not np.isfinite(segment).all() or not (segment > 0).all():
        return float("nan")
    returns = np.diff(np.log(segment))
    return _dfa_alpha_from_returns(returns)


def _e2160_positive(close: np.ndarray, anchor: int) -> bool:
    u = anchor - FEATURE_EMBARGO_HOURS
    prior = u - E2160_HOURS
    if prior < 0 or u >= len(close):
        return False
    return bool(np.log(float(close[u]) / float(close[prior])) > 0.0)


def _target_opportunities(candles: pd.DataFrame) -> pd.DataFrame:
    close = candles["close"].to_numpy(dtype=float)
    open_price = candles["open"].to_numpy(dtype=float)
    low = candles["low"].to_numpy(dtype=float)
    rows: list[dict[str, object]] = []

    for anchor in _training_anchors():
        if anchor + 25 >= len(candles):
            continue
        if not _e2160_positive(close, anchor):
            continue
        alpha = _dfa_alpha(close, anchor)
        if not np.isfinite(alpha):
            continue

        entry = float(open_price[anchor])
        exit_price = float(open_price[anchor + 24])
        net = float(np.log(exit_price / entry) - ROUND_TRIP_FEE)
        adverse = float(
            np.min(np.log(low[anchor : anchor + 24] / entry) - ROUND_TRIP_FEE)
        )

        delay_entry = float(open_price[anchor + 1])
        delay_exit = float(open_price[anchor + 25])
        delay_net = float(np.log(delay_exit / delay_entry) - ROUND_TRIP_FEE)
        delay_adverse = float(
            np.min(
                np.log(low[anchor + 1 : anchor + 25] / delay_entry) - ROUND_TRIP_FEE
            )
        )
        rows.append(
            {
                "anchor_index": int(anchor),
                "anchor": candles.index[anchor],
                "alpha": float(alpha),
                "net": net,
                "adverse": adverse,
                "delay_net": delay_net,
                "delay_adverse": delay_adverse,
            }
        )
    return pd.DataFrame(rows)


def _rank_corr(x: np.ndarray, y: np.ndarray) -> float:
    x_rank = pd.Series(np.asarray(x, dtype=float)).rank(method="average")
    y_rank = pd.Series(np.asarray(y, dtype=float)).rank(method="average")
    return float(x_rank.corr(y_rank))


def _standardized_slope(x: np.ndarray, y: np.ndarray) -> float:
    x_values = np.asarray(x, dtype=float)
    y_values = np.asarray(y, dtype=float)
    scale = float(x_values.std(ddof=0))
    if not np.isfinite(scale) or scale <= 0:
        return float("nan")
    z = (x_values - float(x_values.mean())) / scale
    return float(np.mean(z * (y_values - float(y_values.mean()))))


def _stats(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    return _rank_corr(x, y), _standardized_slope(x, y)


def _tercile_effect(x: np.ndarray, y: np.ndarray) -> float:
    x_values = np.asarray(x, dtype=float)
    y_values = np.asarray(y, dtype=float)
    order = np.argsort(x_values, kind="mergesort")
    count = len(order) // 3
    if count == 0:
        return float("nan")
    return float(np.mean(y_values[order[-count:]]) - np.mean(y_values[order[:count]]))


def _moving_block_bootstrap(
    feature: np.ndarray,
    outcomes: np.ndarray,
    *,
    seed: int,
) -> dict[str, list[float]]:
    feature_values = np.asarray(feature, dtype=float)
    outcome_values = np.asarray(outcomes, dtype=float)
    n = len(feature_values)
    keys = ("net_rho", "net_slope", "adverse_rho", "adverse_slope")
    if n < BOOTSTRAP_BLOCK:
        return {key: [float("nan"), float("nan")] for key in keys}

    rng = np.random.default_rng(seed)
    draws = np.empty((BOOTSTRAP_DRAWS, 4), dtype=float)
    for draw in range(BOOTSTRAP_DRAWS):
        indices: list[int] = []
        while len(indices) < n:
            start = int(rng.integers(0, n - BOOTSTRAP_BLOCK + 1))
            indices.extend(range(start, start + BOOTSTRAP_BLOCK))
        sampled = np.asarray(indices[:n], dtype=int)
        net_rho, net_slope = _stats(feature_values[sampled], outcome_values[sampled, 0])
        adverse_rho, adverse_slope = _stats(
            feature_values[sampled], outcome_values[sampled, 1]
        )
        draws[draw] = (net_rho, net_slope, adverse_rho, adverse_slope)

    intervals: dict[str, list[float]] = {}
    for column, key in enumerate(keys):
        values = draws[:, column]
        if not np.isfinite(values).all():
            intervals[key] = [float("nan"), float("nan")]
        else:
            intervals[key] = [
                float(np.quantile(values, 0.025)),
                float(np.quantile(values, 0.975)),
            ]
    return intervals


def _fold_metrics(opportunities: pd.DataFrame) -> tuple[list[dict[str, object]], float]:
    indices = np.arange(len(opportunities), dtype=int)
    chunks = np.array_split(indices, 4)
    folds: list[dict[str, object]] = []
    for fold_index, chunk in enumerate(chunks, start=1):
        part = opportunities.iloc[chunk]
        if len(part) < 2:
            net_slope = float("nan")
            adverse_slope = float("nan")
        else:
            feature = part["alpha"].to_numpy(dtype=float)
            net_slope = _standardized_slope(feature, part["net"].to_numpy(dtype=float))
            adverse_slope = _standardized_slope(
                feature,
                part["adverse"].to_numpy(dtype=float),
            )
        folds.append(
            {
                "fold": int(fold_index),
                "first_anchor": int(part.iloc[0]["anchor_index"]) if len(part) else None,
                "last_anchor": int(part.iloc[-1]["anchor_index"]) if len(part) else None,
                "opportunities": int(len(part)),
                "net_slope": float(net_slope),
                "adverse_slope": float(adverse_slope),
            }
        )

    positive_net = [
        max(float(fold["net_slope"]), 0.0)
        for fold in folds
        if np.isfinite(float(fold["net_slope"]))
    ]
    total = float(sum(positive_net))
    concentration = float(max(positive_net) / total) if total > 0 else 1.0
    return folds, concentration


def _prefix_invariance(candles: pd.DataFrame, full: pd.DataFrame) -> dict[str, object]:
    truncated = candles.iloc[:TRAIN_END].copy()
    replay = _target_opportunities(truncated)
    equal = full.equals(replay)
    full_bytes = full.to_csv(index=False, float_format="%.17g").encode()
    replay_bytes = replay.to_csv(index=False, float_format="%.17g").encode()
    return {
        "passed": bool(equal),
        "full_training_opportunity_sha256": _sha256(full_bytes),
        "truncated_training_opportunity_sha256": _sha256(replay_bytes),
    }


def _structural_identities(candles: pd.DataFrame) -> dict[str, object]:
    scale_coverage = all(DFA_WINDOW % scale == 0 for scale in DFA_SCALES)
    total_points = {str(scale): int((DFA_WINDOW // scale) * scale) for scale in DFA_SCALES}
    anchor = _training_anchors()[0]
    close = candles["close"].to_numpy(dtype=float)
    base_alpha = _dfa_alpha(close, anchor)
    scaled_alpha = _dfa_alpha(close * 7.0, anchor)
    affine_invariant = bool(
        np.isfinite(base_alpha)
        and np.isfinite(scaled_alpha)
        and np.isclose(base_alpha, scaled_alpha, rtol=0.0, atol=1e-12)
    )
    latest_used = anchor - FEATURE_EMBARGO_HOURS
    chronology_ok = latest_used <= anchor - 25
    return {
        "scale_order_strict": bool(
            all(
                a < b
                for a, b in zip(DFA_SCALES, DFA_SCALES[1:], strict=False)
            )
        ),
        "all_scales_divide_720": bool(scale_coverage),
        "box_coverage_points": total_points,
        "all_scales_cover_exactly_720": bool(
            all(value == DFA_WINDOW for value in total_points.values())
        ),
        "affine_close_unit_invariance": affine_invariant,
        "first_anchor_latest_feature_index": int(latest_used),
        "feature_embargo_at_least_24_completed_hours": bool(chronology_ok),
    }


def _positive_finite(value: object) -> bool:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return False
    return bool(np.isfinite(numeric) and numeric > 0.0)


def _analyze_target(inst_id: str, candles: pd.DataFrame) -> dict[str, object]:
    opportunities = _target_opportunities(candles)
    structural = _structural_identities(candles)
    prefix = _prefix_invariance(candles, opportunities)
    if opportunities.empty:
        return {
            "instrument": inst_id,
            "opportunities": 0,
            "passed": False,
            "structural": structural,
            "prefix_invariance": prefix,
            "gates": {"minimum_opportunities": False},
        }

    feature = opportunities["alpha"].to_numpy(dtype=float)
    net = opportunities["net"].to_numpy(dtype=float)
    adverse = opportunities["adverse"].to_numpy(dtype=float)
    delay_net = opportunities["delay_net"].to_numpy(dtype=float)
    delay_adverse = opportunities["delay_adverse"].to_numpy(dtype=float)

    net_rho, net_slope = _stats(feature, net)
    adverse_rho, adverse_slope = _stats(feature, adverse)
    delay_net_rho, delay_net_slope = _stats(feature, delay_net)
    delay_adverse_rho, delay_adverse_slope = _stats(feature, delay_adverse)
    net_tercile = _tercile_effect(feature, net)
    adverse_tercile = _tercile_effect(feature, adverse)
    delay_net_tercile = _tercile_effect(feature, delay_net)
    delay_adverse_tercile = _tercile_effect(feature, delay_adverse)
    intervals = _moving_block_bootstrap(
        feature,
        np.column_stack([net, adverse]),
        seed=BOOTSTRAP_SEED,
    )
    folds, concentration = _fold_metrics(opportunities)
    positive_net_folds = sum(_positive_finite(fold["net_slope"]) for fold in folds)
    positive_adverse_folds = sum(_positive_finite(fold["adverse_slope"]) for fold in folds)

    q25, median, q75 = np.quantile(feature, [0.25, 0.5, 0.75])
    distinct = int(np.unique(feature).size)
    iqr = float(q75 - q25)
    all_bootstrap_lower_positive = all(
        np.isfinite(interval[0]) and interval[0] > 0.0 for interval in intervals.values()
    )
    structural_pass = bool(
        structural["scale_order_strict"]
        and structural["all_scales_divide_720"]
        and structural["all_scales_cover_exactly_720"]
        and structural["affine_close_unit_invariance"]
        and structural["feature_embargo_at_least_24_completed_hours"]
    )
    gates = {
        "minimum_opportunities": bool(len(opportunities) >= 180),
        "feature_support": bool(distinct >= 100 and iqr > 0.0),
        "net_association": bool(net_rho > 0.0 and net_slope > 0.0),
        "adverse_association": bool(adverse_rho > 0.0 and adverse_slope > 0.0),
        "positive_tercile_effects": bool(net_tercile > 0.0 and adverse_tercile > 0.0),
        "fold_breadth": bool(positive_net_folds >= 3 and positive_adverse_folds >= 3),
        "fold_concentration": bool(concentration <= 0.60),
        "bootstrap_lower_bounds": bool(all_bootstrap_lower_positive),
        "one_hour_delay": bool(
            delay_net_rho > 0.0
            and delay_net_slope > 0.0
            and delay_net_tercile > 0.0
            and delay_adverse_rho > 0.0
            and delay_adverse_slope > 0.0
            and delay_adverse_tercile > 0.0
        ),
        "prefix_invariance": bool(prefix["passed"]),
        "structural_identities": structural_pass,
    }
    result = {
        "instrument": inst_id,
        "opportunities": int(len(opportunities)),
        "distinct_feature_values": distinct,
        "feature_q25": float(q25),
        "feature_median": float(median),
        "feature_q75": float(q75),
        "feature_iqr": iqr,
        "net_rho": float(net_rho),
        "net_slope": float(net_slope),
        "net_tercile_effect_bp": float(net_tercile * 10_000.0),
        "adverse_rho": float(adverse_rho),
        "adverse_slope": float(adverse_slope),
        "adverse_tercile_effect_bp": float(adverse_tercile * 10_000.0),
        "bootstrap_intervals": intervals,
        "folds": folds,
        "positive_net_folds": int(positive_net_folds),
        "positive_adverse_folds": int(positive_adverse_folds),
        "positive_net_fold_concentration": float(concentration),
        "delay": {
            "net_rho": float(delay_net_rho),
            "net_slope": float(delay_net_slope),
            "net_tercile_effect_bp": float(delay_net_tercile * 10_000.0),
            "adverse_rho": float(delay_adverse_rho),
            "adverse_slope": float(delay_adverse_slope),
            "adverse_tercile_effect_bp": float(delay_adverse_tercile * 10_000.0),
        },
        "prefix_invariance": prefix,
        "structural": structural,
        "gates": gates,
        "gate_pass_count": int(sum(gates.values())),
        "gate_count": int(len(gates)),
        "passed": bool(all(gates.values())),
    }
    opportunity_dir = OUTPUT / "opportunities"
    opportunity_dir.mkdir(parents=True, exist_ok=True)
    persisted = opportunities.copy()
    persisted["anchor"] = persisted["anchor"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    opportunity_bytes = persisted.to_csv(index=False, float_format="%.17g").encode()
    path = opportunity_dir / f"{inst_id}.csv"
    path.write_bytes(opportunity_bytes)
    result["opportunities_sha256"] = _sha256(opportunity_bytes)
    return result


def _render_report(payload: dict[str, object]) -> str:
    lines = [
        "# DFA persistence 1H training-information diagnostic",
        "",
        f"- Family: `{payload['family_id']}`",
        f"- Exact head: `{payload['exact_head']}`",
        f"- Candidate/grid: `{payload['candidate_count']}/{payload['parameter_grid_count']}`",
        f"- Fee: `{FEE_ONE_WAY:.4f}` one way",
        "- OOS: sealed; executable performance fields are null",
        f"- Verdict: `{payload['verdict']}`",
        "",
        "## Target results",
        "",
        "| Target | Opps | rho net | slope net | tercile net bp | rho adverse | "
        "slope adverse | tercile adverse bp | folds net/adverse | gates |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    targets = payload["targets"]
    assert isinstance(targets, dict)
    for inst_id in TARGETS:
        result = targets[inst_id]
        assert isinstance(result, dict)
        if int(result.get("opportunities", 0)) == 0:
            lines.append(f"| {inst_id} | 0 | — | — | — | — | — | — | — | 0 |")
            continue
        lines.append(
            f"| {inst_id} | {result['opportunities']} | {result['net_rho']:.6f} | "
            f"{result['net_slope']:.6f} | {result['net_tercile_effect_bp']:.2f} | "
            f"{result['adverse_rho']:.6f} | {result['adverse_slope']:.6f} | "
            f"{result['adverse_tercile_effect_bp']:.2f} | "
            f"{result['positive_net_folds']}/4 / {result['positive_adverse_folds']}/4 | "
            f"{result['gate_pass_count']}/{result['gate_count']} |"
        )
    lines.extend(
        [
            "",
            "## Frozen accounting",
            "",
            "No threshold, position path, sizing rule or equity curve is authorised by this "
            "diagnostic. Training/OOS/full strategy return and Sharpe, benchmark deltas, "
            "turnover, fee drag, maximum drawdown, calendar-year breadth and edge per turnover "
            "are null rather than zero.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    sources: dict[str, object] = {}
    frames: dict[str, pd.DataFrame] = {}
    for inst_id in TARGETS:
        frame, source = _acquire_series(inst_id)
        frames[inst_id] = frame
        sources[inst_id] = source

    target_results = {
        inst_id: _analyze_target(inst_id, frames[inst_id]) for inst_id in TARGETS
    }
    bilateral_pass = bool(all(bool(target_results[item]["passed"]) for item in TARGETS))
    verdict = SUPPORT_VERDICT if bilateral_pass else REJECT_VERDICT
    exact_head = os.environ.get("RESEARCH_HEAD_SHA", "unknown")
    payload: dict[str, object] = {
        "family_id": FAMILY_ID,
        "exact_head": exact_head,
        "canonical_main": "5a0fcc97d1a882f8223656c51f5bb8055f534e38",
        "provider": "OKX",
        "market": "SPOT",
        "bar": "1H",
        "source_start": START,
        "source_end": END,
        "source_rows_per_target": EXPECTED_ROWS,
        "training_range": [TRAIN_START, TRAIN_END],
        "sealed_oos_range": [TRAIN_END, OOS_END],
        "unread_suffix_range": [OOS_END, SOURCE_END],
        "scheduled_training_anchors": len(_training_anchors()),
        "feature_embargo_hours": FEATURE_EMBARGO_HOURS,
        "dfa_window_hours": DFA_WINDOW,
        "dfa_scales_hours": list(DFA_SCALES),
        "e2160_hours": E2160_HOURS,
        "fee_one_way": FEE_ONE_WAY,
        "round_trip_opportunity_fee": ROUND_TRIP_FEE,
        "bootstrap_draws": BOOTSTRAP_DRAWS,
        "bootstrap_block_opportunities": BOOTSTRAP_BLOCK,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "oos_accessed": False,
        "canonical_mutation": False,
        "paper_authority": False,
        "live_authority": False,
        "sources": sources,
        "targets": target_results,
        "targets_passing": int(sum(bool(target_results[item]["passed"]) for item in TARGETS)),
        "targets_total": len(TARGETS),
        "bilateral_pass": bilateral_pass,
        "verdict": verdict,
        "executable_metrics": {
            "train_return": None,
            "train_sharpe": None,
            "oos_return": None,
            "oos_sharpe": None,
            "full_return": None,
            "full_sharpe": None,
            "benchmark_comparison": None,
            "turnover": None,
            "fee_drag": None,
            "maximum_drawdown": None,
            "calendar_year_breadth": None,
            "edge_per_turnover": None,
        },
    }
    result_bytes = _json_bytes(payload)
    result_path = OUTPUT / "dfa-persistence-result.json"
    result_path.write_bytes(result_bytes)
    report = _render_report(payload).encode()
    report_path = OUTPUT / "dfa-persistence-report.md"
    report_path.write_bytes(report)
    manifest = {
        "result_sha256": _sha256(result_bytes),
        "report_sha256": _sha256(report),
        "source_normalized_sha256": {
            key: value["normalized_csv_sha256"] for key, value in sources.items()
        },
        "opportunities_sha256": {
            key: target_results[key].get("opportunities_sha256") for key in TARGETS
        },
    }
    manifest_bytes = _json_bytes(manifest)
    (OUTPUT / "manifest.json").write_bytes(manifest_bytes)
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
