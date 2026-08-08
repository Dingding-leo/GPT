from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd

from gpt_quant.okx_1h import fetch_okx_one_hour_candles

FAMILY_ID = "causal-own-price-positive-block-trend-breadth-opportunity-1h-v1"
START = "2023-04-01T00:00:00Z"
END = "2025-12-31T23:00:00Z"
EXPECTED_ROWS = 24_144
TRAIN_START = 2_208
TRAIN_END = 10_800
OOS_END = 23_760
SOURCE_END = 24_144
FEATURE_EMBARGO_HOURS = 25
BLOCK_HOURS = 24
TREND_HOURS = 2_160
BLOCK_COUNT = 90
FEE_ONE_WAY = 0.0005
ROUND_TRIP_FEE = 0.0010
BOOTSTRAP_DRAWS = 5_000
BOOTSTRAP_BLOCK = 7
BOOTSTRAP_SEED = 20260808
TARGETS = ("SOL-USDT", "ADA-USDT")
OUTPUT = Path("reports/research/positive-block-trend-breadth-1h-v1")
REJECT_VERDICT = (
    "reject_causal_own_price_positive_block_trend_breadth_"
    "information_premise_1h_v1"
)
SUPPORT_VERDICT = (
    "support_causal_own_price_positive_block_trend_breadth_"
    "for_separate_candidate_preregistration_1h_v1"
)


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()


def _csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.reset_index(names="timestamp").to_csv(
        index=False,
        date_format="%Y-%m-%dT%H:%M:%S.%fZ",
        float_format="%.12g",
        lineterminator="\n",
    ).encode()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _finite_valid_market(frame: pd.DataFrame) -> bool:
    prices = frame[["open", "high", "low", "close"]].to_numpy(dtype=float)
    if not np.isfinite(prices).all() or not (prices > 0).all():
        return False
    return bool(
        (frame["high"] >= frame[["open", "close", "low"]].max(axis=1)).all()
        and (frame["low"] <= frame[["open", "close", "high"]].min(axis=1)).all()
    )


def _write_primary_snapshot(inst_id: str, snapshot: object) -> dict[str, str]:
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
        pause_seconds=0.08,
        timeout=20.0,
        safety_pages=64,
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
    if not candles.index.is_unique or not candles.index.is_monotonic_increasing:
        raise ValueError(f"{inst_id}: source timestamps are not unique and monotonic")
    if not candles.equals(repeat_candles):
        raise ValueError(f"{inst_id}: repeated normalized acquisition is not identical")
    if not _finite_valid_market(candles):
        raise ValueError(f"{inst_id}: source contains invalid OHLC values")
    if primary.metadata.get("instrument_id") != inst_id or primary.metadata.get("bar") != "1H":
        raise ValueError(f"{inst_id}: provider instrument/bar identity mismatch")
    if primary.metadata.get("missing_intervals") not in (0, None):
        raise ValueError(f"{inst_id}: provider reports missing intervals")

    persisted = _write_primary_snapshot(inst_id, primary)
    repeat_sha = str(repeat.metadata.get("normalized_csv_sha256"))
    if repeat_sha != persisted["normalized_csv_sha256"]:
        raise ValueError(f"{inst_id}: repeated source hash differs")
    training_prefix = _csv_bytes(candles.iloc[:TRAIN_END])
    return candles, {
        "instrument": inst_id,
        "rows": int(len(candles)),
        "start": str(candles.index[0]),
        "end": str(candles.index[-1]),
        "normalized_csv_sha256": persisted["normalized_csv_sha256"],
        "raw_pages_sha256": persisted["raw_pages_sha256"],
        "metadata_sha256": persisted["metadata_sha256"],
        "repeat_normalized_csv_sha256": repeat_sha,
        "training_prefix_sha256": _sha256(training_prefix),
        "repeat_identity": True,
        "finite_positive_ohlc": True,
        "completed_hourly_grid": True,
        "unique_monotonic_timestamps": True,
        "missing_intervals": int(primary.metadata.get("missing_intervals") or 0),
        "incomplete_rows_removed": int(primary.metadata.get("incomplete_rows_removed") or 0),
    }


def _training_anchors() -> list[int]:
    return [anchor for anchor in range(TRAIN_START, TRAIN_END, 24) if anchor + 25 < TRAIN_END]


def _trend_state(close: np.ndarray, anchor: int) -> dict[str, float | int]:
    latest = anchor - FEATURE_EMBARGO_HOURS
    earliest = latest - TREND_HOURS
    if earliest < 0 or latest >= len(close):
        raise ValueError("trend state exceeds available source prefix")
    points = np.arange(earliest, latest + 1, BLOCK_HOURS, dtype=int)
    if len(points) != BLOCK_COUNT + 1 or int(points[-1]) != latest:
        raise ValueError("trend breadth did not construct exactly 91 daily closes")
    levels = np.asarray(close[points], dtype=float)
    if not np.isfinite(levels).all() or not (levels > 0).all():
        raise ValueError("trend breadth received invalid close values")
    block_returns = np.diff(np.log(levels))
    if len(block_returns) != BLOCK_COUNT:
        raise ValueError("trend breadth did not construct exactly 90 blocks")
    breadth = float(np.count_nonzero(block_returns > 0.0) / BLOCK_COUNT)
    margin = float(math.log(float(levels[-1]) / float(levels[0])))
    decomposition_error = float(abs(float(block_returns.sum()) - margin))

    scale = 7.25
    scaled_levels = levels * scale
    scaled_returns = np.diff(np.log(scaled_levels))
    scaled_breadth = float(np.count_nonzero(scaled_returns > 0.0) / BLOCK_COUNT)
    scaled_margin = float(math.log(float(scaled_levels[-1]) / float(scaled_levels[0])))
    return {
        "breadth": breadth,
        "margin": margin,
        "earliest_feature_index": int(earliest),
        "latest_feature_index": int(latest),
        "block_count": int(len(block_returns)),
        "margin_decomposition_error": decomposition_error,
        "scale_breadth_error": float(abs(scaled_breadth - breadth)),
        "scale_margin_error": float(abs(scaled_margin - margin)),
    }


def _target_opportunities(candles: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    close = candles["close"].to_numpy(dtype=float)
    open_price = candles["open"].to_numpy(dtype=float)
    low = candles["low"].to_numpy(dtype=float)
    rows: list[dict[str, object]] = []
    positive_margin_anchors = 0

    for anchor in _training_anchors():
        state = _trend_state(close, anchor)
        margin = float(state["margin"])
        if margin <= 0.0:
            continue
        positive_margin_anchors += 1

        entry = float(open_price[anchor])
        exit_price = float(open_price[anchor + 24])
        net = float(math.log(exit_price / entry) - ROUND_TRIP_FEE)
        adverse = float(
            np.min(np.log(low[anchor : anchor + 25] / entry) - ROUND_TRIP_FEE)
        )

        delay_entry = float(open_price[anchor + 1])
        delay_exit = float(open_price[anchor + 25])
        delay_net = float(math.log(delay_exit / delay_entry) - ROUND_TRIP_FEE)
        delay_adverse = float(
            np.min(
                np.log(low[anchor + 1 : anchor + 26] / delay_entry) - ROUND_TRIP_FEE
            )
        )
        rows.append(
            {
                "anchor_index": int(anchor),
                "anchor": candles.index[anchor],
                "feature": float(state["breadth"]),
                "margin": margin,
                "net": net,
                "adverse": adverse,
                "delay_net": delay_net,
                "delay_adverse": delay_adverse,
                "earliest_feature_index": int(state["earliest_feature_index"]),
                "latest_feature_index": int(state["latest_feature_index"]),
                "block_count": int(state["block_count"]),
                "margin_decomposition_error": float(state["margin_decomposition_error"]),
                "scale_breadth_error": float(state["scale_breadth_error"]),
                "scale_margin_error": float(state["scale_margin_error"]),
            }
        )
    return pd.DataFrame(rows), {
        "scheduled_training_anchors": int(len(_training_anchors())),
        "positive_e2160_anchors": int(positive_margin_anchors),
    }


def _rank_corr(x: np.ndarray, y: np.ndarray) -> float:
    return float(
        pd.Series(np.asarray(x, dtype=float)).rank(method="average").corr(
            pd.Series(np.asarray(y, dtype=float)).rank(method="average")
        )
    )


def _standardized_slope(x: np.ndarray, y: np.ndarray) -> float:
    xv = np.asarray(x, dtype=float)
    yv = np.asarray(y, dtype=float)
    scale = float(xv.std(ddof=0))
    if not np.isfinite(scale) or scale <= 0:
        return float("nan")
    z = (xv - float(xv.mean())) / scale
    return float(np.mean(z * (yv - float(yv.mean()))))


def _stats(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    return _rank_corr(x, y), _standardized_slope(x, y)


def _tercile_effect(x: np.ndarray, y: np.ndarray) -> float:
    xv = np.asarray(x, dtype=float)
    yv = np.asarray(y, dtype=float)
    order = np.argsort(xv, kind="mergesort")
    count = len(order) // 3
    if count == 0:
        return float("nan")
    return float(np.mean(yv[order[-count:]]) - np.mean(yv[order[:count]]))


def _moving_block_bootstrap(
    feature: np.ndarray,
    net: np.ndarray,
    adverse: np.ndarray,
) -> dict[str, list[float]]:
    fv = np.asarray(feature, dtype=float)
    nv = np.asarray(net, dtype=float)
    av = np.asarray(adverse, dtype=float)
    n = len(fv)
    keys = ("net_rho", "net_slope", "adverse_rho", "adverse_slope")
    if n < BOOTSTRAP_BLOCK:
        return {key: [float("nan"), float("nan")] for key in keys}

    rng = np.random.default_rng(BOOTSTRAP_SEED)
    draws = np.empty((BOOTSTRAP_DRAWS, 4), dtype=float)
    max_start = n - BOOTSTRAP_BLOCK + 1
    for draw in range(BOOTSTRAP_DRAWS):
        sampled: list[int] = []
        while len(sampled) < n:
            start = int(rng.integers(0, max_start))
            sampled.extend(range(start, start + BOOTSTRAP_BLOCK))
        idx = np.asarray(sampled[:n], dtype=int)
        nr, ns = _stats(fv[idx], nv[idx])
        ar, ads = _stats(fv[idx], av[idx])
        draws[draw] = (nr, ns, ar, ads)

    result: dict[str, list[float]] = {}
    for column, key in enumerate(keys):
        values = draws[:, column]
        if not np.isfinite(values).all():
            result[key] = [float("nan"), float("nan")]
        else:
            result[key] = [
                float(np.quantile(values, 0.025)),
                float(np.quantile(values, 0.975)),
            ]
    return result


def _fold_metrics(opportunities: pd.DataFrame) -> tuple[list[dict[str, object]], float]:
    ordered = opportunities.sort_values("anchor_index").reset_index(drop=True)
    fold_indices = np.array_split(np.arange(len(ordered), dtype=int), 4)
    folds: list[dict[str, object]] = []
    for fold_index, indices in enumerate(fold_indices, start=1):
        part = ordered.iloc[indices]
        if len(part) < 2:
            net_slope = float("nan")
            adverse_slope = float("nan")
        else:
            feature = part["feature"].to_numpy(dtype=float)
            net_slope = _standardized_slope(feature, part["net"].to_numpy(dtype=float))
            adverse_slope = _standardized_slope(
                feature, part["adverse"].to_numpy(dtype=float)
            )
        folds.append(
            {
                "fold": int(fold_index),
                "opportunities": int(len(part)),
                "first_anchor_index": int(part["anchor_index"].iloc[0]),
                "last_anchor_index": int(part["anchor_index"].iloc[-1]),
                "net_slope": float(net_slope),
                "adverse_slope": float(adverse_slope),
            }
        )
    positives = [
        float(fold["net_slope"])
        for fold in folds
        if np.isfinite(float(fold["net_slope"])) and float(fold["net_slope"]) > 0
    ]
    concentration = float("inf") if not positives else float(max(positives) / sum(positives))
    return folds, concentration


def _feature_distribution(values: np.ndarray) -> dict[str, float | int]:
    x = np.asarray(values, dtype=float)
    return {
        "count": int(len(x)),
        "distinct": int(len(np.unique(x))),
        "min": float(np.min(x)),
        "q25": float(np.quantile(x, 0.25)),
        "median": float(np.median(x)),
        "q75": float(np.quantile(x, 0.75)),
        "max": float(np.max(x)),
        "mean": float(np.mean(x)),
        "std": float(np.std(x, ddof=0)),
        "iqr": float(np.quantile(x, 0.75) - np.quantile(x, 0.25)),
    }


def _margin_strata(opportunities: pd.DataFrame) -> dict[str, object]:
    median_margin = float(np.median(opportunities["margin"].to_numpy(dtype=float)))
    lower = opportunities[opportunities["margin"] <= median_margin]
    upper = opportunities[opportunities["margin"] > median_margin]

    def _effects(part: pd.DataFrame) -> dict[str, float | int]:
        if len(part) < 3:
            return {
                "opportunities": int(len(part)),
                "net_tercile_effect": float("nan"),
                "adverse_tercile_effect": float("nan"),
            }
        feature = part["feature"].to_numpy(dtype=float)
        return {
            "opportunities": int(len(part)),
            "net_tercile_effect": float(
                _tercile_effect(feature, part["net"].to_numpy(dtype=float))
            ),
            "adverse_tercile_effect": float(
                _tercile_effect(feature, part["adverse"].to_numpy(dtype=float))
            ),
        }

    return {
        "median_positive_margin": median_margin,
        "lower_margin": _effects(lower),
        "upper_margin": _effects(upper),
    }


def _opportunity_hash(opportunities: pd.DataFrame) -> str:
    stable = opportunities.copy()
    stable["anchor"] = pd.to_datetime(stable["anchor"], utc=True).dt.strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    return _sha256(
        stable.to_csv(index=False, float_format="%.12g", lineterminator="\n").encode()
    )


def _target_result(candles: pd.DataFrame, target: str) -> dict[str, object]:
    opportunities, support = _target_opportunities(candles)
    prefix_opportunities, _ = _target_opportunities(candles.iloc[:TRAIN_END].copy())
    compare_columns = [
        "anchor_index",
        "feature",
        "margin",
        "net",
        "adverse",
        "delay_net",
        "delay_adverse",
        "earliest_feature_index",
        "latest_feature_index",
        "block_count",
    ]
    prefix_invariant = bool(
        len(opportunities) == len(prefix_opportunities)
        and opportunities[compare_columns].reset_index(drop=True).equals(
            prefix_opportunities[compare_columns].reset_index(drop=True)
        )
    )
    if not prefix_invariant:
        raise ValueError(f"{target}: future-suffix invariance failed")
    if opportunities.empty:
        raise ValueError(f"{target}: no positive-E2160 training opportunities")

    feature = opportunities["feature"].to_numpy(dtype=float)
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
    intervals = _moving_block_bootstrap(feature, net, adverse)
    folds, concentration = _fold_metrics(opportunities)
    distribution = _feature_distribution(feature)
    strata = _margin_strata(opportunities)

    positive_net_folds = sum(float(fold["net_slope"]) > 0.0 for fold in folds)
    positive_adverse_folds = sum(float(fold["adverse_slope"]) > 0.0 for fold in folds)
    lower = strata["lower_margin"]
    upper = strata["upper_margin"]
    margin_stratification_pass = bool(
        float(lower["net_tercile_effect"]) > 0.0
        and float(lower["adverse_tercile_effect"]) > 0.0
        and float(upper["net_tercile_effect"]) > 0.0
        and float(upper["adverse_tercile_effect"]) > 0.0
    )
    max_decomposition_error = float(opportunities["margin_decomposition_error"].max())
    max_scale_breadth_error = float(opportunities["scale_breadth_error"].max())
    max_scale_margin_error = float(opportunities["scale_margin_error"].max())
    structural = bool(
        (opportunities["block_count"] == BLOCK_COUNT).all()
        and ((opportunities["feature"] >= 0.0) & (opportunities["feature"] <= 1.0)).all()
        and (
            opportunities["latest_feature_index"]
            <= opportunities["anchor_index"] - FEATURE_EMBARGO_HOURS
        ).all()
        and max_decomposition_error <= 1e-12
        and max_scale_breadth_error == 0.0
        and max_scale_margin_error <= 1e-12
    )

    gates = {
        "minimum_opportunities": bool(len(opportunities) >= 180),
        "feature_support": bool(
            int(distribution["distinct"]) >= 15
            and float(distribution["iqr"]) >= (2.0 / BLOCK_COUNT)
        ),
        "positive_net_association": bool(net_rho > 0.0 and net_slope > 0.0),
        "positive_adverse_association": bool(adverse_rho > 0.0 and adverse_slope > 0.0),
        "positive_tercile_effects": bool(net_tercile > 0.0 and adverse_tercile > 0.0),
        "positive_bootstrap_lower_bounds": bool(
            all(
                np.isfinite(intervals[key][0]) and intervals[key][0] > 0.0
                for key in intervals
            )
        ),
        "fold_breadth": bool(positive_net_folds >= 3 and positive_adverse_folds >= 3),
        "fold_concentration": bool(np.isfinite(concentration) and concentration <= 0.60),
        "endpoint_margin_stratification": margin_stratification_pass,
        "delay_transport": bool(
            delay_net_rho > 0.0
            and delay_net_slope > 0.0
            and delay_net_tercile > 0.0
            and delay_adverse_rho > 0.0
            and delay_adverse_slope > 0.0
            and delay_adverse_tercile > 0.0
        ),
        "future_suffix_invariance": prefix_invariant,
        "structural_identities": structural,
    }

    opportunity_dir = OUTPUT / "opportunities"
    opportunity_dir.mkdir(parents=True, exist_ok=True)
    opportunity_path = opportunity_dir / f"{target}.csv"
    opportunities.to_csv(opportunity_path, index=False, float_format="%.12g")
    return {
        **support,
        "opportunities": int(len(opportunities)),
        "opportunity_sha256": _opportunity_hash(opportunities),
        "feature_distribution": distribution,
        "net_rho": float(net_rho),
        "net_slope": float(net_slope),
        "net_tercile_effect": float(net_tercile),
        "adverse_rho": float(adverse_rho),
        "adverse_slope": float(adverse_slope),
        "adverse_tercile_effect": float(adverse_tercile),
        "bootstrap_95": intervals,
        "folds": folds,
        "positive_net_folds": int(positive_net_folds),
        "positive_adverse_folds": int(positive_adverse_folds),
        "positive_net_fold_concentration": float(concentration),
        "margin_strata": strata,
        "delay_net_rho": float(delay_net_rho),
        "delay_net_slope": float(delay_net_slope),
        "delay_net_tercile_effect": float(delay_net_tercile),
        "delay_adverse_rho": float(delay_adverse_rho),
        "delay_adverse_slope": float(delay_adverse_slope),
        "delay_adverse_tercile_effect": float(delay_adverse_tercile),
        "max_margin_decomposition_error": max_decomposition_error,
        "max_scale_breadth_error": max_scale_breadth_error,
        "max_scale_margin_error": max_scale_margin_error,
        "gates": gates,
        "all_training_gates_pass": bool(all(gates.values())),
    }


def _render_report(result: dict[str, object]) -> str:
    lines = [
        "# Positive-block trend breadth — 1H training diagnostic",
        "",
        f"- Family: `{FAMILY_ID}`",
        f"- Exact head: `{result['code_head']}`",
        "- Candidate/grid: `0/0`",
        "- OOS: sealed and unused",
        "- Fee: exactly 5 bps one way; 10 bps round trip in each 24H label",
        f"- Verdict: `{result['verdict']}`",
        "",
        (
            "| Target | Opps | Distinct | IQR | Net rho | Net slope | Net tercile bp | "
            "Adverse rho | Adverse slope | Adverse tercile bp | Net/adverse folds |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for target in TARGETS:
        item = result["targets"][target]
        dist = item["feature_distribution"]
        lines.append(
            f"| {target} | {item['opportunities']} | {dist['distinct']} | "
            f"{dist['iqr']:.6f} | {item['net_rho']:+.6f} | "
            f"{item['net_slope']:+.6f} | {10000 * item['net_tercile_effect']:+.2f} | "
            f"{item['adverse_rho']:+.6f} | {item['adverse_slope']:+.6f} | "
            f"{10000 * item['adverse_tercile_effect']:+.2f} | "
            f"{item['positive_net_folds']}/4 / {item['positive_adverse_folds']}/4 |"
        )

    lines.extend(["", "## Dependence uncertainty", ""])
    for target in TARGETS:
        item = result["targets"][target]
        lines.append(f"### {target}")
        for key, interval in item["bootstrap_95"].items():
            lines.append(f"- {key}: [{interval[0]:+.6f}, {interval[1]:+.6f}]")
        lines.append("")

    lines.extend(["## Endpoint-margin stratification", ""])
    for target in TARGETS:
        strata = result["targets"][target]["margin_strata"]
        lines.append(
            f"- {target} median positive margin: {strata['median_positive_margin']:+.6f}"
        )
        for name in ("lower_margin", "upper_margin"):
            item = strata[name]
            lines.append(
                f"  - {name}: n={item['opportunities']}, net tercile "
                f"{10000 * item['net_tercile_effect']:+.2f} bp, adverse tercile "
                f"{10000 * item['adverse_tercile_effect']:+.2f} bp"
            )

    lines.extend(["", "## One-hour delay", ""])
    for target in TARGETS:
        item = result["targets"][target]
        lines.append(
            f"- {target}: net rho/slope/tercile = {item['delay_net_rho']:+.6f} / "
            f"{item['delay_net_slope']:+.6f} / "
            f"{10000 * item['delay_net_tercile_effect']:+.2f} bp; adverse = "
            f"{item['delay_adverse_rho']:+.6f} / {item['delay_adverse_slope']:+.6f} / "
            f"{10000 * item['delay_adverse_tercile_effect']:+.2f} bp"
        )

    lines.extend(
        [
            "",
            "## Strategy-performance accounting",
            "",
            "This zero-candidate issue authorizes no executable mapping. Train/OOS/full "
            "strategy return and Sharpe, benchmark comparison, turnover, fee drag, maximum "
            "drawdown, calendar-year strategy breadth and edge per turnover are null rather "
            "than zero.",
            "",
            "## Exact source and opportunity hashes",
            "",
        ]
    )
    for target in TARGETS:
        source = result["sources"][target]
        item = result["targets"][target]
        lines.append(
            f"- {target}: source `{source['normalized_csv_sha256']}`; "
            f"training prefix `{source['training_prefix_sha256']}`; "
            f"opportunities `{item['opportunity_sha256']}`"
        )

    lines.extend(["", "## Gate audit", ""])
    for target in TARGETS:
        lines.append(f"### {target}")
        for gate, passed in result["targets"][target]["gates"].items():
            lines.append(f"- {gate}: {'PASS' if passed else 'FAIL'}")
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    sources: dict[str, object] = {}
    targets: dict[str, object] = {}
    for target in TARGETS:
        candles, source = _acquire_series(target)
        sources[target] = source
        targets[target] = _target_result(candles, target)

    bilateral = bool(all(targets[target]["all_training_gates_pass"] for target in TARGETS))
    verdict = SUPPORT_VERDICT if bilateral else REJECT_VERDICT
    result: dict[str, object] = {
        "family_id": FAMILY_ID,
        "code_head": os.environ.get("GITHUB_SHA", "local"),
        "base_main": "5a0fcc97d1a882f8223656c51f5bb8055f534e38",
        "targets_fixed_preperformance": list(TARGETS),
        "bar": "1H",
        "provider": "anonymous public OKX SPOT history-candles",
        "source_start": START,
        "source_end": END,
        "expected_rows_per_target": EXPECTED_ROWS,
        "training": [TRAIN_START, TRAIN_END],
        "sealed_oos": [TRAIN_END, OOS_END],
        "unread_suffix": [OOS_END, SOURCE_END],
        "decision_step_hours": 24,
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "fee_bps_one_way": 5.0,
        "fee_one_way": FEE_ONE_WAY,
        "round_trip_fee": ROUND_TRIP_FEE,
        "feature_embargo_hours": FEATURE_EMBARGO_HOURS,
        "trend_hours": TREND_HOURS,
        "positive_block_count": BLOCK_COUNT,
        "bootstrap_draws": BOOTSTRAP_DRAWS,
        "bootstrap_block_opportunities": BOOTSTRAP_BLOCK,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "sources": sources,
        "targets": targets,
        "bilateral_training_pass": bilateral,
        "sealed_oos_accessed": False,
        "canonical_mutation": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "strategy_metrics": {
            "train_return": None,
            "train_sharpe": None,
            "oos_return": None,
            "oos_sharpe": None,
            "full_return": None,
            "full_sharpe": None,
            "benchmark_comparison": None,
            "turnover": None,
            "fee_drag": None,
            "max_drawdown": None,
            "calendar_year_breadth": None,
            "edge_per_turnover": None,
        },
        "verdict": verdict,
    }
    evidence = _json_bytes(result)
    report = _render_report(result)
    (OUTPUT / "evidence.json").write_bytes(evidence)
    (OUTPUT / "report.md").write_text(report, encoding="utf-8")
    manifest = {
        "evidence_sha256": _sha256(evidence),
        "report_sha256": _sha256(report.encode()),
        "verdict": verdict,
        "code_head": result["code_head"],
    }
    (OUTPUT / "manifest.json").write_bytes(_json_bytes(manifest))
    print(report)


if __name__ == "__main__":
    main()
