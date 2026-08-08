from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from range_energy_source import EXPECTED_ROWS, START, END, TRAIN_END, acquire, range_share
from range_energy_stats import BOOTSTRAP_BLOCK, BOOTSTRAP_DRAWS, BOOTSTRAP_SEEDS, summarize

FAMILY_ID = "causal-same-asset-perpetual-vs-spot-range-energy-share-opportunity-1h-v1"
TRAIN_START = 2_208
OOS_START = 10_800
OOS_END = 23_760
SOURCE_END = 24_144
ROUND_TRIP_FEE = 0.0010
TARGETS = ("BTCUSDT", "ETHUSDT")
OUTPUT = Path("reports/research/perpetual-vs-spot-range-energy-share-1h-v1")
REJECT = "reject_causal_same_asset_perpetual_vs_spot_range_energy_share_information_premise_1h_v1"
SOURCE_REJECT = "reject_causal_same_asset_perpetual_vs_spot_range_energy_share_source_contract_1h_v1"
SUPPORT = "support_causal_same_asset_perpetual_vs_spot_range_energy_share_for_separate_candidate_predeclaration_1h_v1"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def anchors() -> list[int]:
    return [t for t in range(TRAIN_START, TRAIN_END, 24) if t + 25 < TRAIN_END]


def opportunity_frame(
    spot: pd.DataFrame,
    perpetual: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, object]]:
    share, structural = range_share(spot, perpetual)
    share_values = share.to_numpy(float)
    close = spot["close"].to_numpy(float)
    open_px = spot["open"].to_numpy(float)
    rows: list[dict[str, object]] = []
    for t in anchors():
        if t + 25 >= len(spot):
            continue
        margin = float(close[t - 25] / close[t - 2185] - 1.0)
        if margin <= 0:
            continue
        recent = share_values[t - 192 : t - 24]
        baseline = share_values[t - 912 : t - 192]
        if len(recent) != 168 or len(baseline) != 720:
            raise ValueError("feature window length mismatch")
        if not np.isfinite(recent).all() or not np.isfinite(baseline).all():
            continue
        feature = float(np.mean(recent) - np.mean(baseline))
        entry = float(open_px[t])
        gross = float(open_px[t + 24] / entry - 1.0)
        net = gross - ROUND_TRIP_FEE
        adverse = float(np.min(open_px[t : t + 25] / entry - 1.0))
        delayed_entry = float(open_px[t + 1])
        delayed_gross = float(open_px[t + 25] / delayed_entry - 1.0)
        delayed_net = delayed_gross - ROUND_TRIP_FEE
        delayed_adverse = float(
            np.min(open_px[t + 1 : t + 26] / delayed_entry - 1.0)
        )
        rows.append(
            {
                "t": t,
                "timestamp": str(spot.index[t]),
                "feature": feature,
                "e2160_margin": margin,
                "gross": gross,
                "net": net,
                "adverse": adverse,
                "delay_net": delayed_net,
                "delay_adverse": delayed_adverse,
            }
        )
    return pd.DataFrame(rows), structural


def null_strategy_metrics() -> dict[str, None]:
    return {
        "training_return": None,
        "training_sharpe": None,
        "oos_return": None,
        "oos_sharpe": None,
        "full_return": None,
        "full_sharpe": None,
        "benchmark_comparison": None,
        "turnover": None,
        "modeled_fee_drag": None,
        "maximum_drawdown": None,
        "edge_per_turnover": None,
        "calendar_year_strategy_breadth": None,
    }


def write_outputs(payload: dict[str, object]) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    evidence_path = OUTPUT / "evidence.json"
    report_path = OUTPUT / "report.md"
    evidence_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    report = [
        "# Same-asset perpetual-vs-spot range-energy share — frozen 1H training diagnostic",
        "",
        f"Family: `{FAMILY_ID}`",
        f"Code head: `{payload['code_head']}`",
        f"Source contract passed: `{payload['source_contract_passed']}`",
        f"Candidate/grid: `{payload['candidate_count']} / {payload['parameter_grid_count']}`",
        f"Sealed OOS accessed: `{payload['sealed_oos_accessed']}`",
        "",
    ]
    for symbol, result in payload.get("targets", {}).items():
        report.extend(
            [
                f"## {symbol}",
                f"- opportunities: {result['opportunities']}",
                (
                    "- feature distinct/IQR: "
                    f"{result['feature_distribution']['distinct']} / "
                    f"{result['feature_distribution']['iqr']:.8f}"
                ),
                (
                    "- net rho/slope/tercile: "
                    f"{result['net_rho']:+.6f} / {result['net_slope']:+.6f} / "
                    f"{10000 * result['net_tercile_effect']:+.2f} bp"
                ),
                (
                    "- adverse rho/slope/tercile: "
                    f"{result['adverse_rho']:+.6f} / {result['adverse_slope']:+.6f} / "
                    f"{10000 * result['adverse_tercile_effect']:+.2f} bp"
                ),
                (
                    "- negative folds net/adverse: "
                    f"{result['negative_net_folds']}/4 / "
                    f"{result['negative_adverse_folds']}/4"
                ),
                (
                    "- negative-net-fold concentration: "
                    f"{result['negative_net_fold_concentration']}"
                ),
                (
                    "- +1H net rho/slope/tercile: "
                    f"{result['one_hour_delay']['net_rho']:+.6f} / "
                    f"{result['one_hour_delay']['net_slope']:+.6f} / "
                    f"{10000 * result['one_hour_delay']['net_tercile_effect']:+.2f} bp"
                ),
                f"- all gates pass: {result['all_training_gates_pass']}",
                "",
            ]
        )
    report.extend(["## Verdict", "", f"`{payload['verdict']}`", ""])
    report_path.write_text("\n".join(report))
    manifest = {
        "family_id": FAMILY_ID,
        "evidence_sha256": sha(evidence_path.read_bytes()),
        "report_sha256": sha(report_path.read_bytes()),
    }
    (OUTPUT / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    source_dir = OUTPUT / "sources"
    source_dir.mkdir(exist_ok=True)
    code_head = os.environ.get("RESEARCH_HEAD_SHA", "unknown")
    sources: dict[str, object] = {}
    targets: dict[str, object] = {}
    source_passed = False
    target_returns_accessed = False
    source_error: str | None = None
    try:
        panels: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}
        for symbol in TARGETS:
            spot, spot_meta = acquire(symbol, "spot", source_dir)
            perpetual, perpetual_meta = acquire(symbol, "perpetual", source_dir)
            if not spot.index.equals(perpetual.index):
                raise ValueError(f"{symbol}: spot/perpetual common UTC grid mismatch")
            panels[symbol] = (spot, perpetual)
            sources[f"{symbol}_spot"] = spot_meta
            sources[f"{symbol}_perpetual"] = perpetual_meta
        source_passed = True
        target_returns_accessed = True
        for symbol, (spot, perpetual) in panels.items():
            full, structural = opportunity_frame(spot, perpetual)
            prefix, prefix_structural = opportunity_frame(
                spot.iloc[:TRAIN_END].copy(), perpetual.iloc[:TRAIN_END].copy()
            )
            structural_keys = (
                "timestamp_identity",
                "nonnegative_energy",
                "range_share_bounds",
                "positive_price_scale_invariance",
                "zero_total_range_invalidation",
            )
            if any(
                bool(structural[key]) != bool(prefix_structural[key])
                for key in structural_keys
            ):
                raise ValueError(f"{symbol}: structural prefix invariance failed")
            targets[symbol] = summarize(symbol, full, prefix, structural)
    except Exception as exc:
        source_error = f"{type(exc).__name__}: {exc}"

    bilateral = source_passed and len(targets) == 2 and all(
        bool(result["all_training_gates_pass"]) for result in targets.values()
    )
    verdict = SUPPORT if bilateral else (REJECT if source_passed else SOURCE_REJECT)
    payload: dict[str, object] = {
        "schema_version": "perpetual-vs-spot-range-energy-share-1h-v1",
        "family_id": FAMILY_ID,
        "code_head": code_head,
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "bar": "1H",
        "provider": "Binance Public Data monthly archives",
        "source_window": {"start": START, "end": END, "rows_per_arm": EXPECTED_ROWS},
        "training": {
            "start_index": TRAIN_START,
            "end_index_exclusive": TRAIN_END,
            "step_hours": 24,
        },
        "sealed_oos": {"start_index": OOS_START, "end_index_exclusive": OOS_END},
        "unread_suffix": {
            "start_index": OOS_END,
            "end_index_exclusive": SOURCE_END,
        },
        "feature": {
            "spot_energy": "log(spot_high/spot_low)^2",
            "perpetual_energy": "log(perp_high/perp_low)^2",
            "perpetual_range_share": "perp_energy/(spot_energy+perp_energy)",
            "recent_window": "[t-192,t-24) = 168 completed hours through t-25",
            "baseline_window": "[t-912,t-192) = preceding 720 completed hours",
            "feature": "recent_mean - baseline_mean",
            "fixed_sign": "negative",
        },
        "fee_bps_one_way": 5.0,
        "round_trip_label_bps": 10.0,
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "bootstrap_draws": BOOTSTRAP_DRAWS,
        "bootstrap_block_opportunities": BOOTSTRAP_BLOCK,
        "bootstrap_seeds": BOOTSTRAP_SEEDS,
        "targets_fixed_preperformance": list(TARGETS),
        "source_contract_passed": source_passed,
        "source_error": source_error,
        "sources": sources,
        "target_returns_accessed": target_returns_accessed,
        "target_oos_accessed": False,
        "sealed_oos_accessed": False,
        "unread_suffix_accessed": False,
        "strategy_performance_accessed": False,
        "strategy_metrics": null_strategy_metrics(),
        "targets": targets,
        "bilateral_training_pass": bilateral,
        "canonical_mutation": False,
        "correction_authority": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "verdict": verdict,
    }
    write_outputs(payload)
    print(
        json.dumps(
            {"verdict": verdict, "source_passed": source_passed, "bilateral": bilateral},
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
