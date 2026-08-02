from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from gpt_quant.okx import _canonical_csv_bytes, write_okx_snapshot
from gpt_quant.okx_1h import fetch_okx_one_hour_candles

FAMILY_ID = "causal-own-price-e2160-noise-band-hysteresis-1h-v1"
PASS_VERDICT = (
    "accept_causal_own_price_e2160_noise_band_hysteresis_1h_v1_for_canonical_review"
)
FAIL_VERDICT = "reject_causal_own_price_e2160_noise_band_hysteresis_1h_v1"
INSTRUMENTS = ("BTC-USDT", "ETH-USDT")
START = pd.Timestamp("2023-04-01T00:00:00Z")
END = pd.Timestamp("2025-12-31T23:00:00Z")
EXPECTED_ROWS = 24_144
SCORED_START = 2_952
TRAIN_END = 10_800
OOS_END = 23_760
FULL_END = OOS_END
HORIZON = 2_160
INFO_LAG = 25
MARGIN_HISTORY = 30
DECISION_STEP = 24
FEE = 0.0005
ANNUALIZATION = 8_760
BOOTSTRAP_DRAWS = 5_000
BOOTSTRAP_BLOCK = 168
BOOTSTRAP_SEED = 2_026_080_302


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_with_hash(root: Path, name: str, data: bytes) -> str:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    digest = sha256(data)
    path.with_name(path.name + ".sha256").write_text(digest + "\n")
    return digest


def exact_index() -> pd.DatetimeIndex:
    return pd.date_range(START, END, freq="h", inclusive="both")


def source_arm(output: Path, inst_id: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    snapshot = fetch_okx_one_hour_candles(
        inst_id=inst_id,
        start=START,
        end=END,
        pause_seconds=0.12,
        timeout=30.0,
    )
    source_dir = output / "source" / inst_id / "snapshot"
    paths = write_okx_snapshot(snapshot, source_dir)
    frame = snapshot.candles.copy()
    expected = exact_index()
    if len(frame) != EXPECTED_ROWS or not frame.index.equals(expected):
        raise ValueError(f"{inst_id} source does not match frozen 1H grid")
    if not np.isfinite(frame[["open", "high", "low", "close"]].to_numpy()).all():
        raise ValueError(f"{inst_id} source contains non-finite OHLC")
    if (frame[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError(f"{inst_id} source contains non-positive OHLC")
    evidence = {
        "instrument": inst_id,
        "provider": "OKX",
        "market_type": "SPOT",
        "bar": "1H",
        "rows": len(frame),
        "first_timestamp": frame.index[0].isoformat(),
        "last_timestamp": frame.index[-1].isoformat(),
        "normalized_csv_sha256": snapshot.metadata["normalized_csv_sha256"],
        "raw_pages_sha256": snapshot.metadata["raw_pages_sha256"],
        "metadata_sha256": sha256(paths["metadata"].read_bytes()),
        "slice_sha256": sha256(_canonical_csv_bytes(frame)),
        "pages": snapshot.metadata["pages"],
        "missing_intervals": snapshot.metadata["missing_intervals"],
        "duplicates_removed": snapshot.metadata["duplicates_removed"],
        "incomplete_rows_removed": snapshot.metadata["incomplete_rows_removed"],
    }
    return frame, evidence


def decision_anchors(end: int = FULL_END) -> np.ndarray:
    return np.arange(SCORED_START, end, DECISION_STEP, dtype=int)


def margin_at(close: np.ndarray, t: int) -> float:
    return float(math.log(close[t - INFO_LAG] / close[t - INFO_LAG - HORIZON]))


def features(close: np.ndarray, end: int = FULL_END) -> pd.DataFrame:
    rows: list[dict[str, float | int]] = []
    for t in decision_anchors(end):
        current = margin_at(close, int(t))
        prior_endpoints = [int(t - 49 - 24 * offset) for offset in range(MARGIN_HISTORY)]
        prior_margins = np.asarray(
            [
                math.log(close[index] / close[index - HORIZON])
                for index in prior_endpoints
            ],
            dtype=float,
        )
        changes = np.abs(np.diff(prior_margins))
        band = float(np.median(changes))
        if not np.isfinite(current) or not np.isfinite(band) or band <= 0:
            raise ValueError("invalid E2160 margin or noise band")
        rows.append({"anchor": int(t), "margin": current, "band": band})
    result = pd.DataFrame(rows).set_index("anchor")
    if len(result) == 0 or result.index[0] != SCORED_START:
        raise ValueError("invalid decision-anchor construction")
    return result


def states(feature: pd.DataFrame, end: int = FULL_END) -> tuple[np.ndarray, np.ndarray]:
    candidate = np.zeros(end, dtype=float)
    baseline = np.zeros(end, dtype=float)
    held_candidate = 0.0
    anchors = feature.index.to_numpy(dtype=int)
    for index, t in enumerate(anchors):
        margin = float(feature.loc[t, "margin"])
        band = float(feature.loc[t, "band"])
        if held_candidate == 0.0 and margin > band:
            held_candidate = 1.0
        elif held_candidate == 1.0 and margin < -band:
            held_candidate = 0.0
        next_t = int(anchors[index + 1]) if index + 1 < len(anchors) else end
        candidate[t:next_t] = held_candidate
        baseline[t:next_t] = float(margin > 0.0)
    return candidate, baseline


def returns(
    frame: pd.DataFrame,
    position: np.ndarray,
    *,
    delay: int = 0,
    start: int = SCORED_START,
    end: int = FULL_END,
) -> dict[str, np.ndarray]:
    opens = frame["open"].to_numpy(dtype=float)
    if delay not in {0, 1}:
        raise ValueError("delay must be zero or one hour")
    applied = np.zeros(end, dtype=float)
    if delay == 0:
        applied[start:end] = position[start:end]
    else:
        applied[start + 1 : end] = position[start : end - 1]
    gross = np.zeros(end, dtype=float)
    gross[start + 1 : end] = (
        applied[start : end - 1] * (opens[start + 1 : end] / opens[start : end - 1] - 1.0)
    )
    turnover = np.zeros(end, dtype=float)
    turnover[start] = abs(applied[start])
    turnover[start + 1 : end] = np.abs(
        applied[start + 1 : end] - applied[start : end - 1]
    )
    fee = FEE * turnover
    net = gross - fee
    return {
        "position": applied,
        "gross": gross,
        "turnover": turnover,
        "fee": fee,
        "net": net,
    }


def total_return(values: np.ndarray) -> float:
    return float(np.prod(1.0 + values) - 1.0)


def sharpe(values: np.ndarray) -> float:
    standard = float(np.std(values, ddof=1))
    if standard <= 0 or not np.isfinite(standard):
        return 0.0
    return float(np.mean(values) / standard * math.sqrt(ANNUALIZATION))


def maximum_drawdown(values: np.ndarray) -> float:
    equity = np.cumprod(1.0 + values)
    peaks = np.maximum.accumulate(np.concatenate(([1.0], equity)))[:-1]
    return float(np.min(equity / peaks - 1.0))


def metrics(path: dict[str, np.ndarray], start: int, end: int) -> dict[str, Any]:
    net = path["net"][start:end]
    gross = path["gross"][start:end]
    turnover = path["turnover"][start:end]
    fees = path["fee"][start:end]
    exposure = path["position"][start:end]
    turnover_sum = float(np.sum(turnover))
    net_component = float(np.sum(net))
    return {
        "gross_total_return": total_return(gross),
        "net_total_return": total_return(net),
        "sharpe": sharpe(net),
        "maximum_drawdown": maximum_drawdown(net),
        "turnover": turnover_sum,
        "transitions": int(np.count_nonzero(turnover)),
        "fee_drag_sum": float(np.sum(fees)),
        "average_exposure": float(np.mean(exposure)),
        "net_edge_per_turnover_bps": (
            10_000.0 * net_component / turnover_sum if turnover_sum > 0 else None
        ),
    }


def fixed_blocks(length: int, block: int) -> list[np.ndarray]:
    starts = np.arange(0, length - block + 1, dtype=int)
    return [np.arange(start, start + block, dtype=int) for start in starts]


def bootstrap_delta(
    candidate: np.ndarray,
    baseline: np.ndarray,
) -> dict[str, float]:
    if len(candidate) != len(baseline):
        raise ValueError("bootstrap paths must have equal length")
    blocks = fixed_blocks(len(candidate), BOOTSTRAP_BLOCK)
    if not blocks:
        raise ValueError("bootstrap sample is shorter than one block")
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    block_count = math.ceil(len(candidate) / BOOTSTRAP_BLOCK)
    mean_deltas = np.empty(BOOTSTRAP_DRAWS, dtype=float)
    sharpe_deltas = np.empty(BOOTSTRAP_DRAWS, dtype=float)
    for draw in range(BOOTSTRAP_DRAWS):
        chosen = rng.integers(0, len(blocks), size=block_count)
        indices = np.concatenate([blocks[int(item)] for item in chosen])[: len(candidate)]
        candidate_draw = candidate[indices]
        baseline_draw = baseline[indices]
        mean_deltas[draw] = float(np.mean(candidate_draw - baseline_draw))
        sharpe_deltas[draw] = sharpe(candidate_draw) - sharpe(baseline_draw)
    return {
        "draws": BOOTSTRAP_DRAWS,
        "block_hours": BOOTSTRAP_BLOCK,
        "seed": BOOTSTRAP_SEED,
        "mean_delta_point": float(np.mean(candidate - baseline)),
        "mean_delta_lower_95": float(np.quantile(mean_deltas, 0.025)),
        "mean_delta_upper_95": float(np.quantile(mean_deltas, 0.975)),
        "sharpe_delta_point": sharpe(candidate) - sharpe(baseline),
        "sharpe_delta_lower_95": float(np.quantile(sharpe_deltas, 0.025)),
        "sharpe_delta_upper_95": float(np.quantile(sharpe_deltas, 0.975)),
    }


def period_table(
    candidate_path: dict[str, np.ndarray],
    baseline_path: dict[str, np.ndarray],
    frame: pd.DataFrame,
) -> dict[str, Any]:
    folds = []
    positive_delta = []
    for fold in range(6):
        start = TRAIN_END + fold * 2_160
        end = start + 2_160
        candidate_return = total_return(candidate_path["net"][start:end])
        baseline_return = total_return(baseline_path["net"][start:end])
        delta = candidate_return - baseline_return
        if delta > 0:
            positive_delta.append(delta)
        folds.append(
            {
                "fold": fold + 1,
                "start": frame.index[start].isoformat(),
                "end": frame.index[end - 1].isoformat(),
                "candidate_net_return": candidate_return,
                "baseline_net_return": baseline_return,
                "delta": delta,
            }
        )
    positive_sum = float(sum(positive_delta))
    concentration = (
        float(max(positive_delta) / positive_sum) if positive_delta and positive_sum > 0 else None
    )
    years = {}
    for year in (2024, 2025):
        mask = (
            (frame.index.year == year)
            & (np.arange(len(frame)) >= TRAIN_END)
            & (np.arange(len(frame)) < OOS_END)
        )
        indices = np.flatnonzero(mask)
        candidate_return = total_return(candidate_path["net"][indices])
        baseline_return = total_return(baseline_path["net"][indices])
        years[str(year)] = {
            "candidate_net_return": candidate_return,
            "baseline_net_return": baseline_return,
            "delta": candidate_return - baseline_return,
            "hours": int(len(indices)),
        }
    return {
        "folds": folds,
        "candidate_positive_folds": sum(item["candidate_net_return"] > 0 for item in folds),
        "positive_delta_folds": sum(item["delta"] > 0 for item in folds),
        "largest_positive_delta_fold_share": concentration,
        "years": years,
    }


def prefix_invariance(close: np.ndarray) -> dict[str, bool]:
    full = features(close, FULL_END)
    training = features(close[:TRAIN_END], TRAIN_END)
    oos = features(close[:OOS_END], OOS_END)
    full_train = full.loc[full.index < TRAIN_END]
    full_oos = full.loc[full.index < OOS_END]
    candidate_full, baseline_full = states(full, FULL_END)
    candidate_train, baseline_train = states(training, TRAIN_END)
    candidate_oos, baseline_oos = states(oos, OOS_END)
    return {
        "training_feature_prefix": full_train.equals(training),
        "oos_feature_prefix": full_oos.equals(oos),
        "training_candidate_state_prefix": np.array_equal(
            candidate_full[:TRAIN_END], candidate_train
        ),
        "training_baseline_state_prefix": np.array_equal(
            baseline_full[:TRAIN_END], baseline_train
        ),
        "oos_candidate_state_prefix": np.array_equal(
            candidate_full[:OOS_END], candidate_oos
        ),
        "oos_baseline_state_prefix": np.array_equal(
            baseline_full[:OOS_END], baseline_oos
        ),
    }


def gate_vector(result: dict[str, Any]) -> dict[str, bool]:
    train = result["metrics"]["training"]
    oos = result["metrics"]["oos"]
    full = result["metrics"]["full"]
    delay = result["delay"]["oos"]
    breadth = result["breadth"]
    uncertainty = result["uncertainty"]
    years = breadth["years"]
    prefix = result["prefix_invariance"]
    return {
        "training_positive": (
            train["candidate"]["net_total_return"] > 0
            and train["candidate"]["sharpe"] > 0
        ),
        "oos_beats_e2160": (
            oos["candidate"]["net_total_return"] > 0
            and oos["candidate"]["sharpe"] > 0
            and oos["candidate"]["net_total_return"]
            > oos["e2160"]["net_total_return"]
            and oos["candidate"]["sharpe"] > oos["e2160"]["sharpe"]
        ),
        "full_beats_e2160": (
            full["candidate"]["net_total_return"] > full["e2160"]["net_total_return"]
            and full["candidate"]["sharpe"] > full["e2160"]["sharpe"]
        ),
        "turnover_lower": (
            oos["candidate"]["turnover"] < oos["e2160"]["turnover"]
            and full["candidate"]["turnover"] < full["e2160"]["turnover"]
        ),
        "edge_per_turnover_higher": (
            oos["candidate"]["net_edge_per_turnover_bps"]
            > oos["e2160"]["net_edge_per_turnover_bps"]
            and full["candidate"]["net_edge_per_turnover_bps"]
            > full["e2160"]["net_edge_per_turnover_bps"]
        ),
        "drawdown_gate": (
            oos["candidate"]["maximum_drawdown"]
            >= oos["e2160"]["maximum_drawdown"] - 0.02
            and oos["candidate"]["maximum_drawdown"]
            > oos["always_long"]["maximum_drawdown"]
        ),
        "fold_breadth": (
            breadth["candidate_positive_folds"] >= 4
            and breadth["positive_delta_folds"] >= 4
        ),
        "year_breadth": all(
            item["candidate_net_return"] > 0 and item["delta"] > 0
            for item in years.values()
        ),
        "fold_concentration": (
            breadth["largest_positive_delta_fold_share"] is not None
            and breadth["largest_positive_delta_fold_share"] <= 0.50
        ),
        "dependence_support": (
            uncertainty["mean_delta_lower_95"] > 0
            and uncertainty["sharpe_delta_lower_95"] > 0
        ),
        "delay_support": (
            delay["candidate"]["net_total_return"] > 0
            and delay["candidate"]["sharpe"] > 0
            and delay["candidate"]["net_total_return"]
            > delay["e2160"]["net_total_return"]
            and delay["candidate"]["sharpe"] > delay["e2160"]["sharpe"]
        ),
        "prefix_invariance": all(prefix.values()),
    }


def evaluate(frame: pd.DataFrame) -> dict[str, Any]:
    close = frame["close"].to_numpy(dtype=float)
    feature = features(close)
    candidate, baseline = states(feature)
    always = np.ones(FULL_END, dtype=float)
    candidate_path = returns(frame, candidate)
    baseline_path = returns(frame, baseline)
    always_path = returns(frame, always)
    delayed_candidate = returns(frame, candidate, delay=1)
    delayed_baseline = returns(frame, baseline, delay=1)

    ranges = {
        "training": (SCORED_START, TRAIN_END),
        "oos": (TRAIN_END, OOS_END),
        "full": (SCORED_START, FULL_END),
    }
    metric_table = {}
    for name, (start, end) in ranges.items():
        metric_table[name] = {
            "candidate": metrics(candidate_path, start, end),
            "e2160": metrics(baseline_path, start, end),
            "always_long": metrics(always_path, start, end),
        }
    result = {
        "feature": {
            "anchors": int(len(feature)),
            "margin_min": float(feature["margin"].min()),
            "margin_max": float(feature["margin"].max()),
            "margin_iqr": float(
                feature["margin"].quantile(0.75) - feature["margin"].quantile(0.25)
            ),
            "band_min": float(feature["band"].min()),
            "band_max": float(feature["band"].max()),
            "band_median": float(feature["band"].median()),
        },
        "metrics": metric_table,
        "breadth": period_table(candidate_path, baseline_path, frame),
        "uncertainty": bootstrap_delta(
            candidate_path["net"][TRAIN_END:OOS_END],
            baseline_path["net"][TRAIN_END:OOS_END],
        ),
        "delay": {
            "oos": {
                "candidate": metrics(delayed_candidate, TRAIN_END, OOS_END),
                "e2160": metrics(delayed_baseline, TRAIN_END, OOS_END),
            }
        },
        "prefix_invariance": prefix_invariance(close),
    }
    result["gates"] = gate_vector(result)
    result["passed"] = all(result["gates"].values())
    return result


def build_report(evidence: dict[str, Any]) -> str:
    lines = [
        "# E2160 noise-band hysteresis 1H v1",
        "",
        f"- Tested head: `{evidence['tested_head']}`",
        f"- Verdict: `{evidence['verdict']}`",
        f"- Candidate count: `{evidence['candidate_count']}`",
        f"- Parameter-grid count: `{evidence['parameter_grid_count']}`",
        "- Fee: exactly 5 bps one way",
        "",
    ]
    for inst_id in INSTRUMENTS:
        item = evidence["results"][inst_id]
        lines.extend(
            [
                f"## {inst_id}",
                "",
                "| Period | Policy | Net return | Sharpe | Max DD | Turnover | "
                "Edge/turnover (bp) |",
                "|---|---|---:|---:|---:|---:|---:|",
            ]
        )
        for period in ("training", "oos", "full"):
            for policy in ("candidate", "e2160", "always_long"):
                metric = item["metrics"][period][policy]
                edge = metric["net_edge_per_turnover_bps"]
                edge_text = "null" if edge is None else f"{edge:.4f}"
                lines.append(
                    f"| {period} | {policy} | {metric['net_total_return']:.6%} | "
                    f"{metric['sharpe']:.6f} | {metric['maximum_drawdown']:.6%} | "
                    f"{metric['turnover']:.2f} | {edge_text} |"
                )
        lines.extend(
            [
                "",
                f"- Positive candidate OOS folds: "
                f"{item['breadth']['candidate_positive_folds']}/6",
                f"- Positive candidate-minus-E2160 OOS folds: "
                f"{item['breadth']['positive_delta_folds']}/6",
                f"- Mean-return delta 95% interval: "
                f"[{item['uncertainty']['mean_delta_lower_95']:.10g}, "
                f"{item['uncertainty']['mean_delta_upper_95']:.10g}]",
                f"- Sharpe-delta 95% interval: "
                f"[{item['uncertainty']['sharpe_delta_lower_95']:.6f}, "
                f"{item['uncertainty']['sharpe_delta_upper_95']:.6f}]",
                f"- Passed gates: {sum(item['gates'].values())}/{len(item['gates'])}",
                "",
            ]
        )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tested-head", required=True)
    parser.add_argument(
        "--output-dir",
        default="evidence/e2160-noise-band-hysteresis-1h-v1",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    sources: dict[str, Any] = {}
    results: dict[str, Any] = {}
    frames: dict[str, pd.DataFrame] = {}
    for inst_id in INSTRUMENTS:
        frame, source = source_arm(output, inst_id)
        frames[inst_id] = frame
        sources[inst_id] = source
    if not frames["BTC-USDT"].index.equals(frames["ETH-USDT"].index):
        raise ValueError("BTC and ETH sources do not share one timestamp grid")
    for inst_id in INSTRUMENTS:
        results[inst_id] = evaluate(frames[inst_id])

    passed = all(results[inst_id]["passed"] for inst_id in INSTRUMENTS)
    evidence = {
        "schema_version": 1,
        "family_id": FAMILY_ID,
        "issue": 1008,
        "tested_head": args.tested_head,
        "source_period": {
            "start": START.isoformat(),
            "end": END.isoformat(),
            "rows_per_target": EXPECTED_ROWS,
        },
        "sample": {
            "scored_start": SCORED_START,
            "training_end": TRAIN_END,
            "oos_end": OOS_END,
            "unread_suffix_start": OOS_END,
            "full_source_end": EXPECTED_ROWS,
        },
        "candidate_count": 1,
        "parameter_grid_count": 0,
        "canonical_fee_bps_one_way": 5.0,
        "bootstrap": {
            "draws": BOOTSTRAP_DRAWS,
            "block_hours": BOOTSTRAP_BLOCK,
            "seed": BOOTSTRAP_SEED,
        },
        "sources": sources,
        "results": results,
        "targets_passing": sum(results[item]["passed"] for item in INSTRUMENTS),
        "verdict": PASS_VERDICT if passed else FAIL_VERDICT,
        "controls": {
            "public_data_only": True,
            "credentials_accessed": False,
            "accounts_accessed": False,
            "orders_placed": False,
            "leverage_used": False,
            "cross_sectional_selection": False,
            "pairs_or_spreads": False,
            "synthetic_market_data": False,
            "non_1h_input": False,
            "canonical_mutation_authorized": passed,
            "paper_trading_authorized": False,
            "live_trading_authorized": False,
        },
    }
    evidence_bytes = canonical_bytes(evidence)
    evidence_hash = write_with_hash(output, "evidence.json", evidence_bytes)
    report = build_report(evidence).encode()
    report_hash = write_with_hash(output, "report.md", report)
    manifest_rows = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and not path.name.endswith(".sha256"):
            manifest_rows.append(
                {
                    "path": path.relative_to(output).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path.read_bytes()),
                }
            )
    manifest_bytes = canonical_bytes(manifest_rows)
    manifest_hash = write_with_hash(output, "source_manifest.json", manifest_bytes)
    print(f"tested_head={args.tested_head}")
    print(f"verdict={evidence['verdict']}")
    print(f"targets_passing={evidence['targets_passing']}/2")
    print(f"evidence_sha256={evidence_hash}")
    print(f"report_sha256={report_hash}")
    print(f"source_manifest_sha256={manifest_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
