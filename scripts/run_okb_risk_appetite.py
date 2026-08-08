from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from gpt_quant.okx_1h import fetch_okx_one_hour_candles

START = "2023-04-01T00:00:00Z"
END = "2025-12-31T23:00:00Z"
SUFFIX_END = "2026-01-01T00:00:00Z"
EXPECTED_ROWS = 24_144
TRAIN_START = 2_208
TRAIN_END = 10_800
FEE_ONE_WAY = 0.0005
ROUND_TRIP_FEE = 2 * FEE_ONE_WAY
BOOTSTRAP_DRAWS = 5_000
BOOTSTRAP_BLOCK = 7
BOOTSTRAP_SEED = 20260808
EXOGENOUS = "OKB-USDT"
TARGETS = ("HBAR-USDT", "CHZ-USDT")
SERIES = (EXOGENOUS, *TARGETS)
OUTPUT = Path("reports/research/okb-risk-appetite-1h-v1")


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
    csv_path = source_dir / f"{stem}.csv"
    raw_path = source_dir / f"{stem}.raw.json"
    metadata_path = source_dir / f"{stem}.metadata.json"
    csv_path.write_bytes(csv_data)
    raw_path.write_bytes(raw_data)
    metadata_path.write_bytes(metadata_data)

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


def _fetch(inst_id: str, *, end: str) -> object:
    return fetch_okx_one_hour_candles(
        inst_id=inst_id,
        start=START,
        end=end,
        limit=100,
        pause_seconds=0.12,
        timeout=20.0,
        safety_pages=2,
    )


def _acquire_series(inst_id: str) -> tuple[pd.DataFrame, dict[str, object]]:
    primary = _fetch(inst_id, end=END)
    repeat = _fetch(inst_id, end=END)
    suffix = _fetch(inst_id, end=SUFFIX_END)

    candles = primary.candles.copy()
    candles.columns = [str(column).lower() for column in candles.columns]
    repeat_candles = repeat.candles.copy()
    repeat_candles.columns = [str(column).lower() for column in repeat_candles.columns]
    suffix_candles = suffix.candles.copy()
    suffix_candles.columns = [str(column).lower() for column in suffix_candles.columns]

    if len(candles) != EXPECTED_ROWS:
        raise ValueError(f"{inst_id}: frozen source row count is not {EXPECTED_ROWS}")
    if len(repeat_candles) != EXPECTED_ROWS:
        raise ValueError(f"{inst_id}: repeated source row count is not {EXPECTED_ROWS}")
    if len(suffix_candles) != EXPECTED_ROWS + 1:
        raise ValueError(f"{inst_id}: suffix source does not contain exactly one extra hour")
    if not candles.equals(repeat_candles):
        raise ValueError(f"{inst_id}: repeated normalized source is not identical")
    if not candles.equals(suffix_candles.iloc[:EXPECTED_ROWS]):
        raise ValueError(f"{inst_id}: future suffix changes the frozen historical prefix")
    if not _finite_positive_ohlc(candles):
        raise ValueError(f"{inst_id}: frozen source contains invalid OHLC")

    expected_index = pd.date_range(START, END, freq="h")
    if not candles.index.equals(expected_index):
        raise ValueError(f"{inst_id}: source does not match the exact frozen UTC-hour grid")
    if primary.metadata.get("instrument_id") != inst_id:
        raise ValueError(f"{inst_id}: provider instrument identity mismatch")
    if primary.metadata.get("bar") != "1H":
        raise ValueError(f"{inst_id}: provider bar identity mismatch")
    if primary.metadata.get("missing_intervals") not in (0, None):
        raise ValueError(f"{inst_id}: provider reports missing intervals")

    persisted = _write_primary_snapshot(inst_id, primary)
    evidence = {
        "instrument": inst_id,
        "rows": len(candles),
        "start": str(candles.index[0]),
        "end": str(candles.index[-1]),
        "pages": primary.metadata.get("pages"),
        "normalized_csv_sha256": persisted["normalized_csv_sha256"],
        "raw_pages_sha256": persisted["raw_pages_sha256"],
        "metadata_sha256": persisted["metadata_sha256"],
        "repeat_normalized_csv_sha256": repeat.metadata.get("normalized_csv_sha256"),
        "repeat_identity": candles.equals(repeat_candles),
        "suffix_rows": len(suffix_candles),
        "suffix_prefix_identity": candles.equals(suffix_candles.iloc[:EXPECTED_ROWS]),
        "finite_positive_ohlc": True,
        "completed_hourly_grid": True,
    }
    return candles, evidence


def _training_anchors() -> list[int]:
    anchors = []
    for anchor in range(TRAIN_START, TRAIN_END, 24):
        if anchor + 25 < TRAIN_END:
            anchors.append(anchor)
    return anchors


def _rank_corr(x: np.ndarray, y: np.ndarray) -> float:
    x_rank = pd.Series(x).rank(method="average")
    y_rank = pd.Series(y).rank(method="average")
    return float(x_rank.corr(y_rank))


def _standardized_slope(x: np.ndarray, y: np.ndarray) -> float:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    scale = float(x.std(ddof=0))
    if not np.isfinite(scale) or scale <= 0:
        return float("nan")
    z = (x - x.mean()) / scale
    return float(np.mean(z * (y - y.mean())))


def _stats(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    return _rank_corr(x, y), _standardized_slope(x, y)


def _tercile_effect(x: np.ndarray, y: np.ndarray) -> float:
    order = np.argsort(x, kind="mergesort")
    count = len(order) // 3
    if count == 0:
        return float("nan")
    return float(np.mean(y[order[-count:]]) - np.mean(y[order[:count]]))


def _okb_feature(okb_close: np.ndarray, anchor: int) -> float:
    latest = anchor - 25
    prior_24h = anchor - 49
    start_close = anchor - 745
    if start_close < 0:
        return float("nan")
    segment = np.asarray(okb_close[start_close : latest + 1], dtype=float)
    if len(segment) != 721 or not np.isfinite(segment).all() or not (segment > 0).all():
        return float("nan")
    returns = np.diff(np.log(segment))
    if len(returns) != 720:
        return float("nan")
    rms = float(np.sqrt(np.mean(np.square(returns))))
    if not np.isfinite(rms) or rms <= 0:
        return float("nan")
    impulse = math.log(float(okb_close[latest]) / float(okb_close[prior_24h]))
    return float(impulse / (math.sqrt(24.0) * rms))


def _target_opportunities(
    target: pd.DataFrame,
    okb: pd.DataFrame,
) -> pd.DataFrame:
    target_close = target["close"].to_numpy(dtype=float)
    target_open = target["open"].to_numpy(dtype=float)
    okb_close = okb["close"].to_numpy(dtype=float)
    rows: list[dict[str, object]] = []

    for anchor in _training_anchors():
        if anchor + 25 >= len(target) or anchor - 2185 < 0 or anchor - 745 < 0:
            continue
        if anchor - 25 >= len(okb):
            continue
        latest = anchor - 25
        if target_close[latest] <= target_close[anchor - 2185]:
            continue
        feature = _okb_feature(okb_close, anchor)
        if not np.isfinite(feature):
            continue

        entry = float(target_open[anchor])
        exit_price = float(target_open[anchor + 24])
        net = exit_price / entry - 1.0 - ROUND_TRIP_FEE
        path = target_open[anchor : anchor + 25] / entry - 1.0
        adverse = float(np.min(path))

        delay_entry = float(target_open[anchor + 1])
        delay_exit = float(target_open[anchor + 25])
        delay_net = delay_exit / delay_entry - 1.0 - ROUND_TRIP_FEE
        delay_path = target_open[anchor + 1 : anchor + 26] / delay_entry - 1.0
        delay_adverse = float(np.min(delay_path))

        rows.append(
            {
                "anchor_index": anchor,
                "anchor": target.index[anchor],
                "feature": feature,
                "net": net,
                "adverse": adverse,
                "delay_net": delay_net,
                "delay_adverse": delay_adverse,
            }
        )

    return pd.DataFrame(rows)


def _moving_block_bootstrap(
    feature: np.ndarray,
    outcomes: np.ndarray,
    *,
    seed: int,
) -> dict[str, list[float]]:
    rng = np.random.default_rng(seed)
    n = len(feature)
    if n < BOOTSTRAP_BLOCK:
        nan_interval = [float("nan"), float("nan")]
        return {
            "net_rho": nan_interval.copy(),
            "net_slope": nan_interval.copy(),
            "adverse_rho": nan_interval.copy(),
            "adverse_slope": nan_interval.copy(),
        }

    draws = np.empty((BOOTSTRAP_DRAWS, 2, 2), dtype=float)
    for draw in range(BOOTSTRAP_DRAWS):
        indices: list[int] = []
        while len(indices) < n:
            start = int(rng.integers(0, n - BOOTSTRAP_BLOCK + 1))
            indices.extend(range(start, start + BOOTSTRAP_BLOCK))
        sampled = np.asarray(indices[:n], dtype=int)
        for outcome_index in range(2):
            draws[draw, outcome_index] = _stats(
                feature[sampled],
                outcomes[sampled, outcome_index],
            )

    def interval(values: np.ndarray) -> list[float]:
        finite = values[np.isfinite(values)]
        if len(finite) != len(values):
            return [float("nan"), float("nan")]
        return [float(np.quantile(finite, 0.025)), float(np.quantile(finite, 0.975))]

    return {
        "net_rho": interval(draws[:, 0, 0]),
        "net_slope": interval(draws[:, 0, 1]),
        "adverse_rho": interval(draws[:, 1, 0]),
        "adverse_slope": interval(draws[:, 1, 1]),
    }


def _fold_metrics(opportunities: pd.DataFrame) -> tuple[list[dict[str, object]], float]:
    scheduled = np.asarray(_training_anchors(), dtype=int)
    chunks = np.array_split(scheduled, 4)
    folds: list[dict[str, object]] = []

    for fold_index, chunk in enumerate(chunks, start=1):
        part = opportunities[opportunities["anchor_index"].isin(chunk)]
        if len(part) < 2:
            net_slope = float("nan")
            adverse_slope = float("nan")
        else:
            net_slope = _standardized_slope(
                part["feature"].to_numpy(dtype=float),
                part["net"].to_numpy(dtype=float),
            )
            adverse_slope = _standardized_slope(
                part["feature"].to_numpy(dtype=float),
                part["adverse"].to_numpy(dtype=float),
            )
        folds.append(
            {
                "fold": fold_index,
                "scheduled_start": int(chunk[0]),
                "scheduled_end": int(chunk[-1]),
                "opportunities": len(part),
                "net_slope": net_slope,
                "adverse_slope": adverse_slope,
            }
        )

    positive = [
        max(float(fold["net_slope"]), 0.0)
        for fold in folds
        if np.isfinite(float(fold["net_slope"]))
    ]
    positive_total = sum(positive)
    concentration = max(positive) / positive_total if positive_total > 0 else 1.0
    return folds, float(concentration)


def _prefix_invariant(
    target: pd.DataFrame,
    okb: pd.DataFrame,
    full_opportunities: pd.DataFrame,
) -> bool:
    truncated_target = target.iloc[:TRAIN_END].copy()
    truncated_okb = okb.iloc[:TRAIN_END].copy()
    truncated = _target_opportunities(truncated_target, truncated_okb)
    return full_opportunities.equals(truncated)


def _analyze_target(
    inst_id: str,
    target: pd.DataFrame,
    okb: pd.DataFrame,
) -> dict[str, object]:
    opportunities = _target_opportunities(target, okb)
    if opportunities.empty:
        return {
            "instrument": inst_id,
            "opportunities": 0,
            "passed": False,
            "gates": {"min_opportunities": False},
        }

    feature = opportunities["feature"].to_numpy(dtype=float)
    net = opportunities["net"].to_numpy(dtype=float)
    adverse = opportunities["adverse"].to_numpy(dtype=float)
    delay_net = opportunities["delay_net"].to_numpy(dtype=float)
    delay_adverse = opportunities["delay_adverse"].to_numpy(dtype=float)

    net_rho, net_slope = _stats(feature, net)
    adverse_rho, adverse_slope = _stats(feature, adverse)
    delay_net_rho, delay_net_slope = _stats(feature, delay_net)
    delay_adverse_rho, delay_adverse_slope = _stats(feature, delay_adverse)

    effects = {
        "net_bp": _tercile_effect(feature, net) * 10_000.0,
        "adverse_bp": _tercile_effect(feature, adverse) * 10_000.0,
    }
    delay_effects = {
        "net_bp": _tercile_effect(feature, delay_net) * 10_000.0,
        "adverse_bp": _tercile_effect(feature, delay_adverse) * 10_000.0,
    }
    bootstrap = _moving_block_bootstrap(
        feature,
        np.column_stack((net, adverse)),
        seed=BOOTSTRAP_SEED,
    )
    folds, concentration = _fold_metrics(opportunities)
    prefix_invariance = _prefix_invariant(target, okb, opportunities)

    net_positive_folds = sum(
        np.isfinite(float(fold["net_slope"])) and float(fold["net_slope"]) > 0
        for fold in folds
    )
    adverse_positive_folds = sum(
        np.isfinite(float(fold["adverse_slope"])) and float(fold["adverse_slope"]) > 0
        for fold in folds
    )
    distinct = int(opportunities["feature"].nunique())
    q25 = float(opportunities["feature"].quantile(0.25))
    q75 = float(opportunities["feature"].quantile(0.75))
    tercile_count = len(opportunities) // 3

    gates = {
        "min_opportunities": len(opportunities) >= 120,
        "distinct_features": distinct >= 100 and q75 > q25,
        "tercile_size": tercile_count >= 35,
        "positive_continuous": (
            net_rho > 0
            and net_slope > 0
            and adverse_rho > 0
            and adverse_slope > 0
        ),
        "positive_tercile_effects": effects["net_bp"] > 0 and effects["adverse_bp"] > 0,
        "bootstrap_lower_bounds": all(
            np.isfinite(interval[0]) and interval[0] > 0 for interval in bootstrap.values()
        ),
        "fold_breadth": net_positive_folds >= 3 and adverse_positive_folds >= 3,
        "fold_concentration": concentration <= 0.60,
        "one_hour_delay": (
            delay_net_rho > 0
            and delay_net_slope > 0
            and delay_adverse_rho > 0
            and delay_adverse_slope > 0
            and delay_effects["net_bp"] > 0
            and delay_effects["adverse_bp"] > 0
        ),
        "prefix_invariance": prefix_invariance,
        "chronology": all(
            int(anchor) + 25 < TRAIN_END
            for anchor in opportunities["anchor_index"].to_numpy(dtype=int)
        ),
    }

    quantiles = {
        str(probability): float(opportunities["feature"].quantile(probability))
        for probability in (0.05, 0.25, 0.50, 0.75, 0.95)
    }
    return {
        "instrument": inst_id,
        "opportunities": len(opportunities),
        "feature": {
            "distinct": distinct,
            "iqr": q75 - q25,
            "quantiles": quantiles,
        },
        "continuous": {
            "net": {"rho": net_rho, "standardized_slope": net_slope},
            "adverse": {"rho": adverse_rho, "standardized_slope": adverse_slope},
        },
        "tercile_effect_bp": effects,
        "bootstrap_95": bootstrap,
        "folds": folds,
        "positive_net_folds": net_positive_folds,
        "positive_adverse_folds": adverse_positive_folds,
        "positive_net_fold_concentration": concentration,
        "delay": {
            "net": {
                "rho": delay_net_rho,
                "standardized_slope": delay_net_slope,
                "tercile_bp": delay_effects["net_bp"],
            },
            "adverse": {
                "rho": delay_adverse_rho,
                "standardized_slope": delay_adverse_slope,
                "tercile_bp": delay_effects["adverse_bp"],
            },
        },
        "gates": gates,
        "passed": all(gates.values()),
    }


def _null_strategy_metrics() -> dict[str, None]:
    return {
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
        "edge_per_turnover": None,
        "calendar_year_breadth": None,
    }


def _write_result(report: dict[str, object]) -> str:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    result_path = OUTPUT / "result-summary.json"
    data = (json.dumps(report, indent=2, sort_keys=True, allow_nan=True) + "\n").encode()
    result_path.write_bytes(data)
    digest = _sha256(data)
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=True))
    print(f"result_sha256={digest}")
    return digest


def _source_rejection(inst_id: str, error: Exception) -> int:
    report: dict[str, object] = {
        "family_id": "causal-lagged-okb-risk-appetite-opportunity-1h-v1",
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "fee_one_way": FEE_ONE_WAY,
        "round_trip_opportunity_fee": ROUND_TRIP_FEE,
        "training_interval": [TRAIN_START, TRAIN_END],
        "sealed_oos_accessed": False,
        "strategy_performance_accessed": False,
        "strategy_metrics": _null_strategy_metrics(),
        "source_contract_passed": False,
        "failed_source_arm": inst_id,
        "source_error_type": type(error).__name__,
        "source_error": str(error),
        "targets": [],
        "verdict": (
            "reject_causal_lagged_okb_risk_appetite_"
            "opportunity_information_premise_1h_v1"
        ),
    }
    _write_result(report)
    return 0


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    panels: dict[str, pd.DataFrame] = {}
    source_evidence: dict[str, dict[str, object]] = {}

    for inst_id in SERIES:
        try:
            candles, evidence = _acquire_series(inst_id)
        except (RuntimeError, ValueError) as error:
            return _source_rejection(inst_id, error)
        panels[inst_id] = candles
        source_evidence[inst_id] = evidence

    common_grid = all(panels[inst].index.equals(panels[EXOGENOUS].index) for inst in SERIES)
    if not common_grid:
        return _source_rejection("common_calendar", ValueError("series calendars differ"))

    targets = [
        _analyze_target(target, panels[target], panels[EXOGENOUS])
        for target in TARGETS
    ]
    passed_bilateral = all(bool(target["passed"]) for target in targets)
    verdict = (
        "support_causal_lagged_okb_risk_appetite_information_"
        "for_separate_candidate_preregistration_1h_v1"
        if passed_bilateral
        else "reject_causal_lagged_okb_risk_appetite_"
        "opportunity_information_premise_1h_v1"
    )

    report = {
        "family_id": "causal-lagged-okb-risk-appetite-opportunity-1h-v1",
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "fixed_exogenous": EXOGENOUS,
        "fixed_targets": list(TARGETS),
        "bar": "1H",
        "source_interval": [START, END],
        "expected_rows_per_series": EXPECTED_ROWS,
        "training_interval": [TRAIN_START, TRAIN_END],
        "training_anchor_count_after_maturity_guard": len(_training_anchors()),
        "maturity_guard": "anchor+25 < TRAIN_END",
        "fee_one_way": FEE_ONE_WAY,
        "round_trip_opportunity_fee": ROUND_TRIP_FEE,
        "bootstrap": {
            "draws": BOOTSTRAP_DRAWS,
            "block_length_opportunities": BOOTSTRAP_BLOCK,
            "seed": BOOTSTRAP_SEED,
        },
        "source_contract_passed": True,
        "common_calendar": common_grid,
        "source": source_evidence,
        "targets": targets,
        "passed_bilateral": passed_bilateral,
        "sealed_oos_accessed": False,
        "strategy_performance_accessed": False,
        "strategy_metrics": _null_strategy_metrics(),
        "canonical_mutation_authorized": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "verdict": verdict,
    }
    _write_result(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
