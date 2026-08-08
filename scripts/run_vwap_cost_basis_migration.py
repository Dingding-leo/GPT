from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd

from gpt_quant.okx_1h import fetch_okx_one_hour_candles

FAMILY_ID = "causal-own-price-volume-weighted-cost-basis-migration-opportunity-1h-v1"
START = "2023-04-01T00:00:00Z"
END = "2025-12-31T23:00:00Z"
EXPECTED_ROWS = 24_144
TRAIN_START = 2_208
TRAIN_END = 10_800
OOS_END = 23_760
SOURCE_END = 24_144
FEATURE_EMBARGO_HOURS = 25
RECENT_HOURS = 168
BASELINE_HOURS = 720
E2160_HOURS = 2_160
FEE_ONE_WAY = 0.0005
BOOTSTRAP_DRAWS = 5_000
BOOTSTRAP_BLOCK = 7
BOOTSTRAP_SEED = 20260808
TARGETS = ("1INCH-USDT", "SNX-USDT")
OUTPUT = Path("reports/research/vwap-cost-basis-migration-1h-v1")
REJECT_VERDICT = (
    "reject_causal_own_price_volume_weighted_cost_basis_migration_"
    "information_premise_1h_v1"
)
SUPPORT_VERDICT = (
    "support_causal_own_price_volume_weighted_cost_basis_migration_"
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
    price_columns = ["open", "high", "low", "close"]
    volume_columns = ["volume_base", "volume_quote", "volume_quote_alt"]
    prices = frame[price_columns].to_numpy(dtype=float)
    volumes = frame[volume_columns].to_numpy(dtype=float)
    if not np.isfinite(prices).all() or not np.isfinite(volumes).all():
        return False
    if not (prices > 0).all() or (volumes < 0).any():
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
    if not candles.equals(repeat_candles):
        raise ValueError(f"{inst_id}: repeated normalized acquisition is not identical")
    if not _finite_valid_market(candles):
        raise ValueError(f"{inst_id}: source contains invalid market values")
    if primary.metadata.get("instrument_id") != inst_id or primary.metadata.get("bar") != "1H":
        raise ValueError(f"{inst_id}: provider instrument/bar identity mismatch")
    if primary.metadata.get("missing_intervals") not in (0, None):
        raise ValueError(f"{inst_id}: provider reports missing intervals")

    persisted = _write_primary_snapshot(inst_id, primary)
    repeat_sha = str(repeat.metadata.get("normalized_csv_sha256"))
    if repeat_sha != persisted["normalized_csv_sha256"]:
        raise ValueError(f"{inst_id}: repeated source hash differs")
    return candles, {
        "instrument": inst_id,
        "rows": int(len(candles)),
        "start": str(candles.index[0]),
        "end": str(candles.index[-1]),
        "normalized_csv_sha256": persisted["normalized_csv_sha256"],
        "raw_pages_sha256": persisted["raw_pages_sha256"],
        "metadata_sha256": persisted["metadata_sha256"],
        "repeat_normalized_csv_sha256": repeat_sha,
        "repeat_identity": True,
        "finite_positive_ohlc_nonnegative_volume": True,
        "completed_hourly_grid": True,
        "requested_grid_completed_bar_coverage": True,
        "missing_intervals": int(primary.metadata.get("missing_intervals") or 0),
        "pagination_incomplete_rows_removed": int(
            primary.metadata.get("incomplete_rows_removed") or 0
        ),
    }


def _training_anchors() -> list[int]:
    return [anchor for anchor in range(TRAIN_START, TRAIN_END, 24) if anchor + 25 < TRAIN_END]


def _e2160_positive(close: np.ndarray, anchor: int) -> bool:
    u = anchor - FEATURE_EMBARGO_HOURS
    prior = u - E2160_HOURS
    if prior < 0 or u >= len(close):
        return False
    return bool(float(close[u]) > float(close[prior]))


def _window_bias(
    low: np.ndarray,
    high: np.ndarray,
    volume_base: np.ndarray,
    volume_quote: np.ndarray,
    start: int,
    stop: int,
) -> tuple[float, float, float, float]:
    """Return bias, VWAP, TWAP, and maximum pbar candle-bound violation."""

    if start < 0 or stop > len(low) or start >= stop:
        return float("nan"), float("nan"), float("nan"), float("inf")
    base = np.asarray(volume_base[start:stop], dtype=float)
    quote = np.asarray(volume_quote[start:stop], dtype=float)
    lo = np.asarray(low[start:stop], dtype=float)
    hi = np.asarray(high[start:stop], dtype=float)
    if (
        not np.isfinite(base).all()
        or not np.isfinite(quote).all()
        or not np.isfinite(lo).all()
        or not np.isfinite(hi).all()
        or not (base > 0).all()
        or not (quote > 0).all()
    ):
        return float("nan"), float("nan"), float("nan"), float("inf")

    pbar = quote / base
    tolerance = 1e-10 * np.maximum(np.maximum(np.abs(lo), np.abs(hi)), 1.0)
    below = np.maximum(lo - pbar - tolerance, 0.0)
    above = np.maximum(pbar - hi - tolerance, 0.0)
    violation = float(np.max(np.maximum(below, above)))
    if violation > 0 or not np.isfinite(pbar).all() or not (pbar > 0).all():
        return float("nan"), float("nan"), float("nan"), violation

    base_sum = float(base.sum())
    quote_sum = float(quote.sum())
    if base_sum <= 0 or quote_sum <= 0:
        return float("nan"), float("nan"), float("nan"), float("inf")
    vwap = quote_sum / base_sum
    twap = float(pbar.mean())
    if not np.isfinite(vwap) or not np.isfinite(twap) or vwap <= 0 or twap <= 0:
        return float("nan"), float("nan"), float("nan"), float("inf")
    bias = float(math.log(vwap / twap))
    return bias, float(vwap), float(twap), violation


def _feature(candles: pd.DataFrame, anchor: int) -> tuple[float, dict[str, float]]:
    u = anchor - FEATURE_EMBARGO_HOURS
    low = candles["low"].to_numpy(dtype=float)
    high = candles["high"].to_numpy(dtype=float)
    volume_base = candles["volume_base"].to_numpy(dtype=float)
    volume_quote = candles["volume_quote"].to_numpy(dtype=float)

    recent_start = u - RECENT_HOURS + 1
    recent_stop = u + 1
    baseline_start = u - RECENT_HOURS - BASELINE_HOURS + 1
    baseline_stop = u - RECENT_HOURS + 1
    recent = _window_bias(low, high, volume_base, volume_quote, recent_start, recent_stop)
    baseline = _window_bias(low, high, volume_base, volume_quote, baseline_start, baseline_stop)
    if not np.isfinite(recent[0]) or not np.isfinite(baseline[0]):
        return float("nan"), {}
    value = float(recent[0] - baseline[0])
    return value, {
        "recent_bias": float(recent[0]),
        "baseline_bias": float(baseline[0]),
        "recent_vwap": float(recent[1]),
        "recent_twap": float(recent[2]),
        "baseline_vwap": float(baseline[1]),
        "baseline_twap": float(baseline[2]),
        "max_pbar_candle_violation": float(max(recent[3], baseline[3])),
    }


def _target_opportunities(candles: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    close = candles["close"].to_numpy(dtype=float)
    open_price = candles["open"].to_numpy(dtype=float)
    low = candles["low"].to_numpy(dtype=float)
    rows: list[dict[str, object]] = []
    positive_base = 0
    invalid_feature = 0

    for anchor in _training_anchors():
        if not _e2160_positive(close, anchor):
            continue
        positive_base += 1
        feature, detail = _feature(candles, anchor)
        if not np.isfinite(feature):
            invalid_feature += 1
            continue

        entry = float(open_price[anchor])
        exit_price = float(open_price[anchor + 24])
        fee_factor = (1.0 - FEE_ONE_WAY) ** 2
        net = float((exit_price / entry) * fee_factor - 1.0)
        adverse = float(np.min((low[anchor : anchor + 24] / entry) * fee_factor - 1.0))

        delay_entry = float(open_price[anchor + 1])
        delay_exit = float(open_price[anchor + 25])
        delay_net = float((delay_exit / delay_entry) * fee_factor - 1.0)
        delay_adverse = float(
            np.min((low[anchor + 1 : anchor + 25] / delay_entry) * fee_factor - 1.0)
        )
        rows.append(
            {
                "anchor_index": int(anchor),
                "anchor": candles.index[anchor],
                "feature": feature,
                "net": net,
                "adverse": adverse,
                "delay_net": delay_net,
                "delay_adverse": delay_adverse,
                **detail,
            }
        )
    return pd.DataFrame(rows), {
        "scheduled_training_anchors": int(len(_training_anchors())),
        "positive_e2160_anchors": int(positive_base),
        "invalid_feature_anchors": int(invalid_feature),
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
        ar, ass = _stats(fv[idx], av[idx])
        draws[draw] = (nr, ns, ar, ass)

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
    edges = np.linspace(TRAIN_START, TRAIN_END, 5, dtype=int)
    folds: list[dict[str, object]] = []
    for fold_index in range(4):
        lo = int(edges[fold_index])
        hi = int(edges[fold_index + 1])
        part = opportunities[
            (opportunities["anchor_index"] >= lo) & (opportunities["anchor_index"] < hi)
        ]
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
                "fold": int(fold_index + 1),
                "anchor_start": lo,
                "anchor_end_exclusive": hi,
                "opportunities": int(len(part)),
                "net_slope": float(net_slope),
                "adverse_slope": float(adverse_slope),
            }
        )
    positives = [
        float(fold["net_slope"])
        for fold in folds
        if np.isfinite(float(fold["net_slope"])) and float(fold["net_slope"]) > 0
    ]
    if not positives:
        concentration = float("inf")
    else:
        concentration = float(max(positives) / sum(positives))
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


def _target_result(candles: pd.DataFrame) -> dict[str, object]:
    opportunities, support = _target_opportunities(candles)
    prefix_opportunities, _ = _target_opportunities(candles.iloc[:TRAIN_END].copy())
    if len(opportunities) != len(prefix_opportunities):
        raise ValueError("future-suffix invariance failed: opportunity count changed")
    compare_columns = [
        "anchor_index",
        "feature",
        "net",
        "adverse",
        "delay_net",
        "delay_adverse",
        "recent_bias",
        "baseline_bias",
    ]
    if not opportunities[compare_columns].reset_index(drop=True).equals(
        prefix_opportunities[compare_columns].reset_index(drop=True)
    ):
        raise ValueError("future-suffix invariance failed: training values changed")
    if opportunities.empty:
        raise ValueError("no valid positive-E2160 training opportunities")

    feature = opportunities["feature"].to_numpy(dtype=float)
    net = opportunities["net"].to_numpy(dtype=float)
    adverse = opportunities["adverse"].to_numpy(dtype=float)
    delay_net = opportunities["delay_net"].to_numpy(dtype=float)
    delay_adverse = opportunities["delay_adverse"].to_numpy(dtype=float)
    net_rho, net_slope = _stats(feature, net)
    adverse_rho, adverse_slope = _stats(feature, adverse)
    delay_net_rho, delay_net_slope = _stats(feature, delay_net)
    delay_adverse_rho, delay_adverse_slope = _stats(feature, delay_adverse)
    folds, concentration = _fold_metrics(opportunities)
    intervals = _moving_block_bootstrap(feature, net, adverse)
    distribution = _feature_distribution(feature)
    net_tercile = _tercile_effect(feature, net)
    adverse_tercile = _tercile_effect(feature, adverse)
    delay_net_tercile = _tercile_effect(feature, delay_net)
    delay_adverse_tercile = _tercile_effect(feature, delay_adverse)
    max_violation = float(opportunities["max_pbar_candle_violation"].max())

    positive_net_folds = sum(float(fold["net_slope"]) > 0 for fold in folds)
    positive_adverse_folds = sum(float(fold["adverse_slope"]) > 0 for fold in folds)
    gates = {
        "source_and_structural": bool(max_violation == 0.0),
        "minimum_opportunities": bool(len(opportunities) >= 180),
        "feature_support": bool(distribution["distinct"] >= 100 and distribution["iqr"] > 0),
        "positive_point_association": bool(
            net_rho > 0 and net_slope > 0 and adverse_rho > 0 and adverse_slope > 0
        ),
        "positive_tercile_effects": bool(net_tercile > 0 and adverse_tercile > 0),
        "positive_bootstrap_lower_bounds": bool(
            all(np.isfinite(intervals[key][0]) and intervals[key][0] > 0 for key in intervals)
        ),
        "fold_breadth": bool(positive_net_folds >= 3 and positive_adverse_folds >= 3),
        "fold_concentration": bool(np.isfinite(concentration) and concentration <= 0.60),
        "delay_transport": bool(
            delay_net_rho > 0
            and delay_net_slope > 0
            and delay_net_tercile > 0
            and delay_adverse_rho > 0
            and delay_adverse_slope > 0
            and delay_adverse_tercile > 0
        ),
        "future_suffix_invariance": True,
    }

    opportunity_file = OUTPUT / "opportunities" / f"{opportunities.iloc[0]['anchor']:%Y%m%d}-{len(opportunities)}.csv"
    opportunity_file.parent.mkdir(parents=True, exist_ok=True)
    opportunities.to_csv(opportunity_file, index=False, float_format="%.12g")
    return {
        **support,
        "opportunities": int(len(opportunities)),
        "feature_distribution": distribution,
        "max_pbar_candle_violation": max_violation,
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
        "delay_net_rho": float(delay_net_rho),
        "delay_net_slope": float(delay_net_slope),
        "delay_net_tercile_effect": float(delay_net_tercile),
        "delay_adverse_rho": float(delay_adverse_rho),
        "delay_adverse_slope": float(delay_adverse_slope),
        "delay_adverse_tercile_effect": float(delay_adverse_tercile),
        "gates": gates,
        "all_training_gates_pass": bool(all(gates.values())),
    }


def _render_report(result: dict[str, object]) -> str:
    lines = [
        "# Volume-weighted transaction-cost-basis migration — 1H training diagnostic",
        "",
        f"- Family: `{FAMILY_ID}`",
        f"- Exact head: `{result['code_head']}`",
        "- Candidate/grid: `0/0`",
        "- OOS: sealed and unused",
        "- Fee: exactly 5 bps one way in each independent 24H opportunity label",
        f"- Verdict: `{result['verdict']}`",
        "",
        "| Target | Opps | Net rho | Net slope | Net tercile bp | Adverse rho | Adverse slope | Adverse tercile bp | Net/adverse folds |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for target in TARGETS:
        item = result["targets"][target]
        lines.append(
            f"| {target} | {item['opportunities']} | {item['net_rho']:+.6f} | "
            f"{item['net_slope']:+.6f} | {10000*item['net_tercile_effect']:+.2f} | "
            f"{item['adverse_rho']:+.6f} | {item['adverse_slope']:+.6f} | "
            f"{10000*item['adverse_tercile_effect']:+.2f} | "
            f"{item['positive_net_folds']}/4 / {item['positive_adverse_folds']}/4 |"
        )
    lines.extend(
        [
            "",
            "## Strategy-performance accounting",
            "",
            "This issue authorizes no executable candidate. Train/OOS/full strategy return and Sharpe, benchmark comparison, turnover, drawdown, edge per turnover, and strategy calendar-year breadth are null rather than zero.",
            "",
            "## Exact source hashes",
            "",
        ]
    )
    for target in TARGETS:
        source = result["sources"][target]
        lines.append(f"- {target}: `{source['normalized_csv_sha256']}` ({source['rows']} rows)")
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
        targets[target] = _target_result(candles)

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
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "fee_one_way": FEE_ONE_WAY,
        "fee_round_trip_factor": float((1.0 - FEE_ONE_WAY) ** 2),
        "feature_embargo_hours": FEATURE_EMBARGO_HOURS,
        "recent_hours": RECENT_HOURS,
        "baseline_hours": BASELINE_HOURS,
        "bootstrap_draws": BOOTSTRAP_DRAWS,
        "bootstrap_block_opportunities": BOOTSTRAP_BLOCK,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "sources": sources,
        "targets": targets,
        "bilateral_training_pass": bilateral,
        "oos_accessed": False,
        "strategy_metrics": {
            "train": None,
            "oos": None,
            "full": None,
            "benchmark_comparison": None,
            "turnover": None,
            "max_drawdown": None,
            "edge_per_turnover": None,
            "calendar_year_breadth": None,
        },
        "verdict": verdict,
    }
    evidence = _json_bytes(result)
    (OUTPUT / "evidence.json").write_bytes(evidence)
    report = _render_report(result)
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
