from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from gpt_quant.okx_1h import fetch_okx_one_hour_candles

START = "2023-04-01T00:00:00Z"
END = "2025-12-31T23:00:00Z"
SUFFIX_END = "2026-01-01T00:00:00Z"
EXPECTED_ROWS = 24_144
TRAIN_START = 2_880
TRAIN_END = 10_800
FEE_ONE_WAY = 0.0005
ROUND_TRIP_FEE = 2 * FEE_ONE_WAY
BOOTSTRAP_DRAWS = 5_000
BOOTSTRAP_BLOCK = 7
TARGETS = ("ARB-USDT", "OP-USDT")
BOOTSTRAP_SEEDS = {"ARB-USDT": 2026080801, "OP-USDT": 2026080802}
OUTPUT = Path("reports/research/negative-e2160-margin-recovery-1h-v1")
FAMILY_ID = "causal-own-price-negative-e2160-margin-recovery-opportunity-1h-v1"


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.reset_index(names="timestamp").to_csv(
        index=False,
        date_format="%Y-%m-%dT%H:%M:%S.%fZ",
        float_format="%.12g",
        lineterminator="\n",
    ).encode()


def _fetch(inst_id: str, end: str) -> object:
    return fetch_okx_one_hour_candles(
        inst_id=inst_id,
        start=START,
        end=end,
        limit=100,
        pause_seconds=0.10,
        timeout=20.0,
        safety_pages=2,
    )


def _finite_positive_ohlc(frame: pd.DataFrame) -> bool:
    cols = ["open", "high", "low", "close"]
    values = frame[cols].to_numpy(dtype=float)
    if not np.isfinite(values).all() or not (values > 0).all():
        return False
    return bool(
        (frame["high"] >= frame[["open", "close"]].max(axis=1)).all()
        and (frame["low"] <= frame[["open", "close"]].min(axis=1)).all()
        and (frame["high"] >= frame["low"]).all()
    )


def _persist_primary(inst_id: str, snapshot: object) -> dict[str, str]:
    directory = OUTPUT / "source" / inst_id
    directory.mkdir(parents=True, exist_ok=True)
    frame = snapshot.candles
    csv_data = _csv_bytes(frame)
    raw_data = _json_bytes(snapshot.raw_pages)
    metadata_data = _json_bytes(snapshot.metadata)

    (directory / f"okx-{inst_id}-1H.csv").write_bytes(csv_data)
    (directory / f"okx-{inst_id}-1H.raw.json").write_bytes(raw_data)
    (directory / f"okx-{inst_id}-1H.metadata.json").write_bytes(metadata_data)

    normalized_sha = str(snapshot.metadata.get("normalized_csv_sha256"))
    raw_sha = str(snapshot.metadata.get("raw_pages_sha256"))
    if _sha256(csv_data) != normalized_sha:
        raise ValueError(f"{inst_id}: normalized CSV hash mismatch after persistence")
    if _sha256(raw_data) != raw_sha:
        raise ValueError(f"{inst_id}: raw response hash mismatch after persistence")
    return {
        "normalized_csv_sha256": normalized_sha,
        "raw_pages_sha256": raw_sha,
        "metadata_sha256": _sha256(metadata_data),
    }


def _acquire(inst_id: str) -> tuple[pd.DataFrame, dict[str, object]]:
    primary = _fetch(inst_id, END)
    repeat = _fetch(inst_id, END)
    suffix = _fetch(inst_id, SUFFIX_END)

    frame = primary.candles.copy()
    repeat_frame = repeat.candles.copy()
    suffix_frame = suffix.candles.copy()
    for current in (frame, repeat_frame, suffix_frame):
        current.columns = [str(column).lower() for column in current.columns]

    if len(frame) != EXPECTED_ROWS:
        raise ValueError(f"{inst_id}: expected {EXPECTED_ROWS} rows, observed {len(frame)}")
    if len(repeat_frame) != EXPECTED_ROWS:
        raise ValueError(
            f"{inst_id}: repeat expected {EXPECTED_ROWS} rows, observed {len(repeat_frame)}"
        )
    if len(suffix_frame) != EXPECTED_ROWS + 1:
        raise ValueError(
            f"{inst_id}: suffix expected {EXPECTED_ROWS + 1} rows, observed {len(suffix_frame)}"
        )
    if not frame.equals(repeat_frame):
        raise ValueError(f"{inst_id}: repeated normalized acquisition differs")
    if not frame.equals(suffix_frame.iloc[:EXPECTED_ROWS]):
        raise ValueError(f"{inst_id}: future suffix changes frozen source prefix")
    if not _finite_positive_ohlc(frame):
        raise ValueError(f"{inst_id}: invalid finite-positive OHLC contract")

    expected_index = pd.date_range(START, END, freq="h")
    if not frame.index.equals(expected_index):
        raise ValueError(f"{inst_id}: source does not match exact UTC-hour grid")
    if primary.metadata.get("instrument_id") != inst_id:
        raise ValueError(f"{inst_id}: provider instrument identity mismatch")
    if primary.metadata.get("bar") != "1H":
        raise ValueError(f"{inst_id}: provider bar identity mismatch")
    if primary.metadata.get("missing_intervals") not in (0, None):
        raise ValueError(f"{inst_id}: provider reports missing intervals")

    hashes = _persist_primary(inst_id, primary)
    return frame, {
        "instrument": inst_id,
        "rows": len(frame),
        "start": str(frame.index[0]),
        "end": str(frame.index[-1]),
        "pages": primary.metadata.get("pages"),
        "normalized_csv_sha256": hashes["normalized_csv_sha256"],
        "raw_pages_sha256": hashes["raw_pages_sha256"],
        "metadata_sha256": hashes["metadata_sha256"],
        "repeat_normalized_csv_sha256": repeat.metadata.get(
            "normalized_csv_sha256"
        ),
        "repeat_identity": True,
        "suffix_rows": len(suffix_frame),
        "suffix_prefix_identity": True,
        "finite_positive_ohlc": True,
        "completed_hourly_grid": True,
    }


def _anchors() -> list[int]:
    # t+25 must stay strictly inside the training partition so delayed labels
    # can never touch sealed OOS.
    return [
        t
        for t in range(TRAIN_START, TRAIN_END, 24)
        if t + 25 < TRAIN_END and t - 2353 >= 0
    ]


def _rank_corr(x: np.ndarray, y: np.ndarray) -> float:
    return float(
        pd.Series(x).rank(method="average").corr(pd.Series(y).rank(method="average"))
    )


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


def _tercile_effect(x: np.ndarray, y: np.ndarray) -> tuple[float, int]:
    order = np.argsort(x, kind="mergesort")
    count = len(order) // 3
    if count <= 0:
        return float("nan"), 0
    return float(np.mean(y[order[-count:]]) - np.mean(y[order[:count]])), count


def _build_opportunities(frame: pd.DataFrame) -> pd.DataFrame:
    close = frame["close"].to_numpy(dtype=float)
    open_ = frame["open"].to_numpy(dtype=float)
    rows: list[dict[str, object]] = []

    for t in _anchors():
        margin_now = math.log(float(close[t - 25]) / float(close[t - 2185]))
        margin_7d = math.log(float(close[t - 193]) / float(close[t - 2353]))
        recovery = margin_now - margin_7d
        if not all(np.isfinite([margin_now, margin_7d, recovery])):
            continue
        if margin_now > 0:
            continue

        entry = float(open_[t])
        exit_price = float(open_[t + 24])
        net = exit_price / entry - 1.0 - ROUND_TRIP_FEE
        adverse = float(np.min(open_[t : t + 25] / entry - 1.0))

        delayed_entry = float(open_[t + 1])
        delayed_exit = float(open_[t + 25])
        delayed_net = delayed_exit / delayed_entry - 1.0 - ROUND_TRIP_FEE
        delayed_adverse = float(
            np.min(open_[t + 1 : t + 26] / delayed_entry - 1.0)
        )

        rows.append(
            {
                "anchor_index": t,
                "anchor": frame.index[t],
                "margin_now": margin_now,
                "margin_7d": margin_7d,
                "recovery": recovery,
                "net": net,
                "adverse": adverse,
                "delay_net": delayed_net,
                "delay_adverse": delayed_adverse,
            }
        )

    return pd.DataFrame(rows)


def _block_bootstrap(
    feature: np.ndarray,
    net: np.ndarray,
    adverse: np.ndarray,
    *,
    seed: int,
) -> dict[str, list[float]]:
    n = len(feature)
    if n < BOOTSTRAP_BLOCK:
        nan = [float("nan"), float("nan")]
        return {
            "net_spearman": nan.copy(),
            "net_standardized_slope": nan.copy(),
            "adverse_spearman": nan.copy(),
            "adverse_standardized_slope": nan.copy(),
        }

    rng = np.random.default_rng(seed)
    values = np.empty((BOOTSTRAP_DRAWS, 4), dtype=float)
    for draw in range(BOOTSTRAP_DRAWS):
        sampled: list[int] = []
        while len(sampled) < n:
            start = int(rng.integers(0, n - BOOTSTRAP_BLOCK + 1))
            sampled.extend(range(start, start + BOOTSTRAP_BLOCK))
        idx = np.asarray(sampled[:n], dtype=int)
        values[draw, 0], values[draw, 1] = _stats(feature[idx], net[idx])
        values[draw, 2], values[draw, 3] = _stats(feature[idx], adverse[idx])

    def interval(column: int) -> list[float]:
        series = values[:, column]
        if not np.isfinite(series).all():
            return [float("nan"), float("nan")]
        return [float(np.quantile(series, 0.025)), float(np.quantile(series, 0.975))]

    return {
        "net_spearman": interval(0),
        "net_standardized_slope": interval(1),
        "adverse_spearman": interval(2),
        "adverse_standardized_slope": interval(3),
    }


def _folds(opportunities: pd.DataFrame) -> tuple[list[dict[str, object]], float]:
    scheduled = np.asarray(_anchors(), dtype=int)
    chunks = np.array_split(scheduled, 4)
    evidence: list[dict[str, object]] = []
    positive_net_slopes: list[float] = []

    for index, chunk in enumerate(chunks, start=1):
        part = opportunities[opportunities["anchor_index"].isin(chunk)]
        if len(part) >= 2:
            feature = part["recovery"].to_numpy(dtype=float)
            net_slope = _standardized_slope(feature, part["net"].to_numpy(dtype=float))
            adverse_slope = _standardized_slope(
                feature, part["adverse"].to_numpy(dtype=float)
            )
        else:
            net_slope = float("nan")
            adverse_slope = float("nan")
        if np.isfinite(net_slope) and net_slope > 0:
            positive_net_slopes.append(net_slope)
        evidence.append(
            {
                "fold": index,
                "scheduled_start": int(chunk[0]),
                "scheduled_end": int(chunk[-1]),
                "opportunities": int(len(part)),
                "net_standardized_slope": net_slope,
                "adverse_standardized_slope": adverse_slope,
            }
        )

    total = float(sum(positive_net_slopes))
    concentration = (
        float(max(positive_net_slopes) / total) if total > 0 else float("nan")
    )
    return evidence, concentration


def _prefix_invariant(frame: pd.DataFrame, full: pd.DataFrame) -> bool:
    truncated = frame.iloc[:TRAIN_END].copy()
    replay = _build_opportunities(truncated)
    columns = list(full.columns)
    if list(replay.columns) != columns:
        return False
    return full.equals(replay)


def _analyze(inst_id: str, frame: pd.DataFrame) -> dict[str, object]:
    opportunities = _build_opportunities(frame)
    if opportunities.empty:
        return {
            "instrument": inst_id,
            "opportunities": 0,
            "gates": {"minimum_support": False},
            "pass_all_gates": False,
        }

    x = opportunities["recovery"].to_numpy(dtype=float)
    net = opportunities["net"].to_numpy(dtype=float)
    adverse = opportunities["adverse"].to_numpy(dtype=float)
    delay_net = opportunities["delay_net"].to_numpy(dtype=float)
    delay_adverse = opportunities["delay_adverse"].to_numpy(dtype=float)

    net_rho, net_slope = _stats(x, net)
    adverse_rho, adverse_slope = _stats(x, adverse)
    delay_net_rho, delay_net_slope = _stats(x, delay_net)
    delay_adverse_rho, delay_adverse_slope = _stats(x, delay_adverse)
    net_tercile, tercile_count = _tercile_effect(x, net)
    adverse_tercile, _ = _tercile_effect(x, adverse)
    delay_net_tercile, _ = _tercile_effect(x, delay_net)
    delay_adverse_tercile, _ = _tercile_effect(x, delay_adverse)
    intervals = _block_bootstrap(
        x,
        net,
        adverse,
        seed=BOOTSTRAP_SEEDS[inst_id],
    )
    folds, concentration = _folds(opportunities)
    positive_net_folds = sum(
        1
        for fold in folds
        if np.isfinite(float(fold["net_standardized_slope"]))
        and float(fold["net_standardized_slope"]) > 0
    )
    positive_adverse_folds = sum(
        1
        for fold in folds
        if np.isfinite(float(fold["adverse_standardized_slope"]))
        and float(fold["adverse_standardized_slope"]) > 0
    )

    q25, q75 = np.quantile(x, [0.25, 0.75])
    iqr = float(q75 - q25)
    distinct = int(pd.Series(x).nunique())
    finite_intervals = all(
        np.isfinite(bounds).all() for bounds in intervals.values()
    )
    positive_lower_bounds = finite_intervals and all(
        bounds[0] > 0 for bounds in intervals.values()
    )
    prefix_ok = _prefix_invariant(frame, opportunities)

    gates = {
        "minimum_support": len(opportunities) >= 120,
        "feature_dispersion": distinct >= 30 and iqr > 0,
        "outer_tercile_support": tercile_count >= 35,
        "positive_point_information": all(
            value > 0
            for value in (net_rho, net_slope, adverse_rho, adverse_slope)
        ),
        "positive_tercile_effects": net_tercile > 0 and adverse_tercile > 0,
        "positive_dependence_lower_bounds": positive_lower_bounds,
        "fold_breadth": positive_net_folds >= 3 and positive_adverse_folds >= 3,
        "positive_effect_concentration": bool(
            np.isfinite(concentration) and concentration <= 0.60
        ),
        "one_hour_delay": all(
            value > 0
            for value in (
                delay_net_rho,
                delay_net_slope,
                delay_adverse_rho,
                delay_adverse_slope,
                delay_net_tercile,
                delay_adverse_tercile,
            )
        ),
        "prefix_invariance": prefix_ok,
    }

    records_path = OUTPUT / f"{inst_id}-training-opportunities.csv"
    opportunities.to_csv(
        records_path,
        index=False,
        date_format="%Y-%m-%dT%H:%M:%S.%fZ",
        float_format="%.12g",
        lineterminator="\n",
    )

    return {
        "instrument": inst_id,
        "opportunities": int(len(opportunities)),
        "feature": {
            "minimum": float(np.min(x)),
            "maximum": float(np.max(x)),
            "median": float(np.median(x)),
            "iqr": iqr,
            "distinct_values": distinct,
            "outer_tercile_count": tercile_count,
        },
        "point_information": {
            "net_spearman": net_rho,
            "net_standardized_slope": net_slope,
            "adverse_spearman": adverse_rho,
            "adverse_standardized_slope": adverse_slope,
            "net_upper_minus_lower_tercile": net_tercile,
            "adverse_upper_minus_lower_tercile": adverse_tercile,
        },
        "dependence_uncertainty": {
            "draws": BOOTSTRAP_DRAWS,
            "block_opportunities": BOOTSTRAP_BLOCK,
            "seed": BOOTSTRAP_SEEDS[inst_id],
            "intervals": intervals,
        },
        "fold_breadth": {
            "folds": folds,
            "positive_net_slope_folds": positive_net_folds,
            "positive_adverse_slope_folds": positive_adverse_folds,
            "positive_net_slope_concentration": concentration,
        },
        "one_hour_delay": {
            "net_spearman": delay_net_rho,
            "net_standardized_slope": delay_net_slope,
            "adverse_spearman": delay_adverse_rho,
            "adverse_standardized_slope": delay_adverse_slope,
            "net_upper_minus_lower_tercile": delay_net_tercile,
            "adverse_upper_minus_lower_tercile": delay_adverse_tercile,
        },
        "prefix_invariance": prefix_ok,
        "gates": gates,
        "failed_gates": [name for name, passed in gates.items() if not passed],
        "pass_all_gates": all(gates.values()),
        "training_records_sha256": _sha256(records_path.read_bytes()),
    }


def _protocol() -> dict[str, object]:
    return {
        "family_id": FAMILY_ID,
        "targets": list(TARGETS),
        "bar": "1H",
        "source_start": START,
        "source_end": END,
        "expected_rows": EXPECTED_ROWS,
        "train_start": TRAIN_START,
        "train_end": TRAIN_END,
        "information_exclusion_hours": 24,
        "trend_horizon_hours": 2160,
        "recovery_interval_hours": 168,
        "eligibility": "margin_now<=0",
        "feature": "log(close[t-25]/close[t-2185])-log(close[t-193]/close[t-2353])",
        "label_horizon_hours": 24,
        "fee_bps_one_way": 5.0,
        "bootstrap_draws": BOOTSTRAP_DRAWS,
        "bootstrap_block_opportunities": BOOTSTRAP_BLOCK,
        "bootstrap_seeds": BOOTSTRAP_SEEDS,
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "sealed_oos_accessed": False,
    }


def _write_report(evidence: dict[str, object]) -> None:
    lines = [
        "# Negative-E2160 margin-recovery information diagnostic",
        "",
        f"- Family: `{FAMILY_ID}`",
        f"- Generated: `{evidence['generated_at']}`",
        f"- Source contract passed: `{str(evidence['source_contract_passed']).lower()}`",
        f"- Candidate / parameter grid: `0 / 0`",
        f"- Sealed OOS accessed: `false`",
        f"- Strategy performance accessed: `false`",
        "- Canonical fee in every independent opportunity label: exactly `5 bps` entry + `5 bps` exit",
        "",
    ]
    if not evidence["source_contract_passed"]:
        lines.extend(
            [
                "## Source rejection",
                "",
                f"`{evidence['source_failure']}`",
                "",
                f"Verdict: `{evidence['verdict']}`",
            ]
        )
    else:
        lines.extend(["## Training-only results", ""])
        for target in evidence["targets"]:
            point = target["point_information"]
            delay = target["one_hour_delay"]
            lines.extend(
                [
                    f"### {target['instrument']}",
                    "",
                    f"Opportunities: `{target['opportunities']}`; feature IQR: `{target['feature']['iqr']:.8f}`.",
                    "",
                    f"Net rho/slope: `{point['net_spearman']:+.6f}` / `{point['net_standardized_slope']:+.6f}`; adverse rho/slope: `{point['adverse_spearman']:+.6f}` / `{point['adverse_standardized_slope']:+.6f}`.",
                    "",
                    f"Upper-minus-lower tercile net/adverse: `{point['net_upper_minus_lower_tercile']:+.6%}` / `{point['adverse_upper_minus_lower_tercile']:+.6%}`.",
                    "",
                    f"Positive fold breadth net/adverse: `{target['fold_breadth']['positive_net_slope_folds']}/4` / `{target['fold_breadth']['positive_adverse_slope_folds']}/4`.",
                    "",
                    f"Delayed net rho/slope: `{delay['net_spearman']:+.6f}` / `{delay['net_standardized_slope']:+.6f}`; delayed adverse rho/slope: `{delay['adverse_spearman']:+.6f}` / `{delay['adverse_standardized_slope']:+.6f}`.",
                    "",
                    f"Failed gates: `{', '.join(target['failed_gates']) if target['failed_gates'] else 'none'}`.",
                    "",
                ]
            )
        lines.extend(
            [
                "## Verdict",
                "",
                f"`{evidence['verdict']}`",
                "",
                "No executable rule, OOS result, canonical mutation, paper authority or live authority was created.",
            ]
        )
    (OUTPUT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    protocol = _protocol()
    protocol_bytes = _json_bytes(protocol)
    (OUTPUT / "protocol.json").write_bytes(protocol_bytes)

    source_evidence: list[dict[str, object]] = []
    frames: dict[str, pd.DataFrame] = {}
    source_failure: str | None = None
    for inst_id in TARGETS:
        try:
            frame, source = _acquire(inst_id)
            frames[inst_id] = frame
            source_evidence.append(source)
        except Exception as exc:  # fail closed into machine-readable evidence
            source_failure = f"{inst_id}: {type(exc).__name__}: {exc}"
            break

    generated_at = datetime.now(UTC).isoformat()
    if source_failure is not None or len(frames) != len(TARGETS):
        evidence: dict[str, object] = {
            "schema_version": "negative-e2160-margin-recovery-evidence-v1",
            "generated_at": generated_at,
            "family_id": FAMILY_ID,
            "protocol_sha256": _sha256(protocol_bytes),
            "source_contract_passed": False,
            "source_failure": source_failure,
            "sources": source_evidence,
            "candidate_count": 0,
            "parameter_grid_count": 0,
            "target_returns_accessed": False,
            "strategy_performance_accessed": False,
            "sealed_oos_accessed": False,
            "canonical_mutation": False,
            "correction_authority": False,
            "paper_trading_authorized": False,
            "live_trading_authorized": False,
            "targets": [],
            "targets_passing": 0,
            "verdict": "reject_causal_own_price_negative_e2160_margin_recovery_source_contract_1h_v1",
        }
    else:
        targets = [_analyze(inst_id, frames[inst_id]) for inst_id in TARGETS]
        targets_passing = sum(bool(target["pass_all_gates"]) for target in targets)
        bilateral = targets_passing == len(TARGETS)
        evidence = {
            "schema_version": "negative-e2160-margin-recovery-evidence-v1",
            "generated_at": generated_at,
            "family_id": FAMILY_ID,
            "protocol_sha256": _sha256(protocol_bytes),
            "source_contract_passed": True,
            "source_failure": None,
            "sources": source_evidence,
            "candidate_count": 0,
            "parameter_grid_count": 0,
            "target_returns_accessed": True,
            "strategy_performance_accessed": False,
            "sealed_oos_accessed": False,
            "canonical_mutation": False,
            "correction_authority": False,
            "paper_trading_authorized": False,
            "live_trading_authorized": False,
            "targets": targets,
            "targets_passing": targets_passing,
            "bilateral_information_pass": bilateral,
            "strategy_metrics": {
                "training_return": None,
                "oos_return": None,
                "full_return": None,
                "sharpe": None,
                "turnover": None,
                "fees": None,
                "maximum_drawdown": None,
                "edge_per_turnover_bps": None,
            },
            "verdict": (
                "accept_causal_own_price_negative_e2160_margin_recovery_information_premise_1h_v1"
                if bilateral
                else "reject_causal_own_price_negative_e2160_margin_recovery_information_premise_1h_v1"
            ),
        }

    evidence_bytes = _json_bytes(evidence)
    (OUTPUT / "evidence.json").write_bytes(evidence_bytes)
    (OUTPUT / "evidence.sha256").write_text(_sha256(evidence_bytes) + "\n", encoding="utf-8")
    _write_report(evidence)
    print(json.dumps(evidence, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
