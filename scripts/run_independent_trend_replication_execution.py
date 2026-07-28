from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import run_independent_trend_replication as base
from run_independent_trend_replication_bounded import fetch_bounded_one_hour_candles

EXTRA_END = base.EVAL_END + pd.Timedelta(hours=1)
PATHS = {
    "C0_close_to_close_attribution": {
        "return_source": "close[t-1] to close[t]",
        "position_source": "target[t-1]",
        "qualification_path": False,
    },
    "C1_next_open": {
        "return_source": "open[t] to open[t+1]",
        "position_source": "target[t-1]",
        "qualification_path": True,
    },
    "C2_extra_hour_latency": {
        "return_source": "open[t] to open[t+1]",
        "position_source": "target[t-2]",
        "qualification_path": True,
    },
}


def _strategy_path(
    frame: pd.DataFrame,
    *,
    path_name: str,
) -> pd.DataFrame:
    close = frame["close"].astype(float)
    open_price = frame["open"].astype(float)
    target = (close.pct_change(base.LOOKBACK) > 0.0).astype(float)

    if path_name == "C0_close_to_close_attribution":
        asset_return = close.pct_change()
        position = target.shift(1)
    elif path_name == "C1_next_open":
        asset_return = open_price.shift(-1) / open_price - 1.0
        position = target.shift(1)
    elif path_name == "C2_extra_hour_latency":
        asset_return = open_price.shift(-1) / open_price - 1.0
        position = target.shift(2)
    else:
        raise ValueError(f"unknown path {path_name}")

    result = pd.DataFrame(
        {
            "target": target,
            "position": position.fillna(0.0),
            "asset_return": asset_return,
        }
    ).loc[base.EVAL_START : base.EVAL_END].copy()
    expected = base.FOLD_HOURS * base.FOLDS
    if len(result) != expected:
        raise ValueError(f"{path_name} has {len(result)} rows, expected {expected}")
    if result["asset_return"].isna().any():
        raise ValueError(f"{path_name} contains unavailable execution returns")

    # The frozen replication starts from cash; later fold/year boundaries do not reset.
    result.iloc[0, result.columns.get_loc("position")] = 0.0
    result["turnover"] = result["position"].diff().abs()
    result.iloc[0, result.columns.get_loc("turnover")] = abs(
        float(result.iloc[0]["position"])
    )
    result["gross_return"] = result["position"] * result["asset_return"]
    result["fee"] = result["turnover"] * base.FEE_BPS / 10_000.0
    result["net_return"] = result["gross_return"] - result["fee"]

    buy_hold_position = pd.Series(1.0, index=result.index)
    buy_hold_turnover = buy_hold_position.diff().abs().fillna(1.0)
    result["buy_hold_return"] = (
        buy_hold_position * result["asset_return"]
        - buy_hold_turnover * base.FEE_BPS / 10_000.0
    )
    result["residual_return"] = result["net_return"] - result["buy_hold_return"]
    result["fold"] = np.repeat(np.arange(1, base.FOLDS + 1), base.FOLD_HOURS)
    return result


def _gate(
    market_results: dict[str, dict[str, Any]],
    frozen_count: int,
) -> dict[str, bool]:
    complete_markets = sorted(market_results)
    metrics = [market_results[market]["metrics"] for market in complete_markets]
    complete_count = len(complete_markets)
    net_returns = [float(item["net_total_return"]) for item in metrics]
    sharpes = [float(item["net_sharpe"]) for item in metrics]
    edges = [
        float(item["net_edge_per_turnover_bps"])
        for item in metrics
        if item["net_edge_per_turnover_bps"] is not None
    ]
    residuals = [float(item["buy_hold_residual_sharpe"]) for item in metrics]
    return {
        "at_least_three_complete_markets": complete_count >= 3,
        "all_frozen_markets_materialized": (
            complete_count == frozen_count and frozen_count > 0
        ),
        "two_thirds_positive_net_return": (
            frozen_count > 0
            and sum(value > 0.0 for value in net_returns) / frozen_count >= 2.0 / 3.0
        ),
        "positive_median_net_return": bool(
            net_returns and float(np.median(net_returns)) > 0.0
        ),
        "positive_median_sharpe": bool(
            sharpes and float(np.median(sharpes)) > 0.0
        ),
        "worst_market_above_minus_15pct": bool(
            net_returns and min(net_returns) > -0.15
        ),
        "two_thirds_have_six_profitable_folds": (
            frozen_count > 0
            and sum(int(item["profitable_folds"]) >= 6 for item in metrics)
            / frozen_count
            >= 2.0 / 3.0
        ),
        "no_positive_fold_concentration_above_half": (
            complete_count == frozen_count
            and all(
                item["largest_positive_fold_share"] is not None
                and float(item["largest_positive_fold_share"]) <= 0.5
                for item in metrics
            )
        ),
        "positive_median_edge_per_turnover": bool(
            edges and float(np.median(edges)) > 0.0
        ),
        "positive_median_buy_hold_residual_sharpe": bool(
            residuals and float(np.median(residuals)) > 0.0
        ),
    }


def _common_index_bootstrap(
    path_returns: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    per_path = {
        name: base.bootstrap_median_annualized_mean(values)
        for name, values in path_returns.items()
    }
    rng = np.random.default_rng(base.BOOTSTRAP_SEED)
    arrays = {
        name: values.to_numpy(dtype=float)
        for name, values in path_returns.items()
    }
    samples = {
        "C1_minus_C0": np.empty(base.BOOTSTRAP_RESAMPLES, dtype=float),
        "C2_minus_C1": np.empty(base.BOOTSTRAP_RESAMPLES, dtype=float),
    }
    fold_starts = np.arange(0, base.FOLD_HOURS * base.FOLDS, base.FOLD_HOURS)
    valid_start_count = base.FOLD_HOURS - base.BOOTSTRAP_BLOCK + 1
    for sample_index in range(base.BOOTSTRAP_RESAMPLES):
        sampled_indices: list[np.ndarray] = []
        for fold_start in fold_starts:
            pieces: list[np.ndarray] = []
            remaining = base.FOLD_HOURS
            while remaining > 0:
                offset = int(rng.integers(0, valid_start_count))
                block = np.arange(
                    fold_start + offset,
                    fold_start + offset + base.BOOTSTRAP_BLOCK,
                )
                take = min(remaining, len(block))
                pieces.append(block[:take])
                remaining -= take
            sampled_indices.append(np.concatenate(pieces))
        indices = np.concatenate(sampled_indices)
        annualized = {
            name: np.mean(values[indices], axis=0) * base.ANNUALIZATION
            for name, values in arrays.items()
        }
        medians = {
            name: float(np.median(values))
            for name, values in annualized.items()
        }
        samples["C1_minus_C0"][sample_index] = (
            medians["C1_next_open"] - medians["C0_close_to_close_attribution"]
        )
        samples["C2_minus_C1"][sample_index] = (
            medians["C2_extra_hour_latency"] - medians["C1_next_open"]
        )

    observed = {
        name: float(np.median(np.mean(values, axis=0) * base.ANNUALIZATION))
        for name, values in arrays.items()
    }
    deltas: dict[str, Any] = {}
    for name, values in samples.items():
        if name == "C1_minus_C0":
            point = (
                observed["C1_next_open"]
                - observed["C0_close_to_close_attribution"]
            )
        else:
            point = (
                observed["C2_extra_hour_latency"] - observed["C1_next_open"]
            )
        errors = values - point
        deltas[name] = {
            "observed_delta": point,
            "basic_95_interval": [
                float(point - np.quantile(errors, 0.975)),
                float(point - np.quantile(errors, 0.025)),
            ],
            "one_sided_95_lower_bound": float(
                point - np.quantile(errors, 0.95)
            ),
        }
    return {
        "per_path": per_path,
        "paired_stress_deltas": deltas,
        "resamples": base.BOOTSTRAP_RESAMPLES,
        "block_hours": base.BOOTSTRAP_BLOCK,
        "seed": base.BOOTSTRAP_SEED,
        "sampling": (
            "common non-circular 168H indices across C0/C1/C2 and all markets, "
            "sampled independently within each fixed 2160H fold"
        ),
    }


def _future_suffix_check(frame: pd.DataFrame) -> bool:
    mutated = frame.copy()
    mutated.loc[EXTRA_END, "close"] = float(mutated.loc[EXTRA_END, "close"]) * 1.01
    for path_name in PATHS:
        original = _strategy_path(frame, path_name=path_name)
        changed = _strategy_path(mutated, path_name=path_name)
        if not original["position"].equals(changed["position"]):
            return False
        if not original["net_return"].equals(changed["net_return"]):
            return False
    return True


def _clean(value: Any) -> Any:
    if isinstance(value, float):
        return base.finite_or_none(value)
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean(item) for item in value]
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)

    policy_hash = base.sha256_bytes(base.canonical_json_bytes(base.POLICY_SPEC))
    instruments_payload, instruments_raw, instruments_url = base.fetch_public_json(
        "/api/v5/public/instruments",
        {"instType": "SPOT"},
    )
    (output / "source").mkdir(parents=True, exist_ok=True)
    (output / "source" / "instruments.raw.json").write_bytes(instruments_raw)
    candidates, instrument_rejections = base.instrument_candidates(
        instruments_payload["data"]
    )

    qualification_rows: list[dict[str, Any]] = []
    qualified: list[str] = []
    for candidate in candidates:
        inst_id = candidate["inst_id"]
        row: dict[str, Any] = dict(candidate)
        try:
            snapshot = fetch_bounded_one_hour_candles(
                inst_id=inst_id,
                start=base.QUAL_START,
                end=base.QUAL_END,
                pause_seconds=0.11,
                timeout=30.0,
            )
            provenance = base.persist_snapshot(
                output,
                inst_id,
                "qualification",
                snapshot,
            )
            metrics = base.qualification_metrics(
                base.normalize_snapshot_frame(snapshot.candles)
            )
            row.update(metrics)
            row["provenance"] = provenance
            row["qualified"] = bool(
                metrics["complete_hourly_grid"] and metrics["liquidity_pass"]
            )
            row["reason"] = (
                None if row["qualified"] else "grid_or_liquidity_failure"
            )
            if row["qualified"]:
                qualified.append(inst_id)
        except Exception as exc:  # noqa: BLE001
            row.update(
                {
                    "qualified": False,
                    "reason": "qualification_acquisition_failure",
                    "error": str(exc),
                }
            )
        qualification_rows.append(row)

    frozen_universe = sorted(qualified)
    universe_payload = {
        "family_id": "simple-trend-2160h-independent-replication-v1",
        "policy_sha256": policy_hash,
        "frozen_before_performance": True,
        "universe_type": "current-live survivorship-conditioned",
        "survivorship_limit": (
            "The current public instruments endpoint omits historically delisted "
            "spot markets; passing results cannot authorize promotion."
        ),
        "instrument_source": {
            "url": instruments_url,
            "raw_sha256": base.sha256_bytes(instruments_raw),
            "rows": len(instruments_payload["data"]),
        },
        "eligibility": {
            "instrument_type": "SPOT",
            "state": "live",
            "quote_ccy": "USDT",
            "listed_before": base.LISTED_BEFORE.isoformat(),
            "excluded_development_markets": ["BTC-USDT", "ETH-USDT"],
            "excluded_stable_or_fiat_bases": sorted(base.STABLE_BASES),
            "qualification_start": base.QUAL_START.isoformat(),
            "qualification_end": base.QUAL_END.isoformat(),
            "median_utc_daily_quote_volume_min_usdt": base.LIQUIDITY_THRESHOLD,
            "complete_hourly_grid_required": True,
        },
        "candidate_instruments": candidates,
        "instrument_filter_rejections": instrument_rejections,
        "qualification_results": qualification_rows,
        "frozen_instruments": frozen_universe,
    }
    universe_hash = base.write_json(output / "universe.json", universe_payload)

    market_results: dict[str, dict[str, Any]] = {}
    unavailable: list[dict[str, str]] = []
    aligned_returns: dict[str, dict[str, pd.Series]] = {
        path_name: {} for path_name in PATHS
    }
    for inst_id in frozen_universe:
        try:
            snapshot = fetch_bounded_one_hour_candles(
                inst_id=inst_id,
                start=base.QUAL_START,
                end=EXTRA_END,
                pause_seconds=0.11,
                timeout=30.0,
            )
            provenance = base.persist_snapshot(output, inst_id, "full", snapshot)
            frame = base.normalize_snapshot_frame(snapshot.candles)
            expected_grid = pd.date_range(base.QUAL_START, EXTRA_END, freq="h")
            if len(frame) != len(expected_grid) or not frame.index.equals(
                expected_grid
            ):
                raise ValueError(
                    "full sample is not the exact complete frozen hourly grid"
                )
            if not _future_suffix_check(frame):
                raise AssertionError("future-suffix timing invariance failed")

            market_results[inst_id] = {
                "provenance": provenance,
                "causal_checks": {
                    "exact_grid": True,
                    "future_suffix_invariance": True,
                    "fold_boundary_reset": False,
                    "fee_bps_one_way": base.FEE_BPS,
                },
                "paths": {},
            }
            for path_name in PATHS:
                strategy = _strategy_path(frame, path_name=path_name)
                concatenated = pd.concat(
                    [group for _, group in strategy.groupby("fold", sort=True)]
                )
                if not concatenated.index.equals(strategy.index):
                    raise AssertionError("fold slicing changed chronological order")
                if not concatenated["net_return"].equals(strategy["net_return"]):
                    raise AssertionError("fold slicing changed return state")
                metrics = base.summarize_strategy(strategy)
                csv_bytes = (
                    strategy.reset_index()
                    .to_csv(index=False, lineterminator="\n")
                    .encode("utf-8")
                )
                result_path = (
                    output
                    / "markets"
                    / inst_id
                    / f"{path_name}-strategy-returns.csv"
                )
                result_path.parent.mkdir(parents=True, exist_ok=True)
                result_path.write_bytes(csv_bytes)
                market_results[inst_id]["paths"][path_name] = {
                    "metrics": metrics,
                    "strategy_returns_sha256": base.sha256_bytes(csv_bytes),
                }
                aligned_returns[path_name][inst_id] = strategy["net_return"]
        except Exception as exc:  # noqa: BLE001
            unavailable.append({"inst_id": inst_id, "reason": str(exc)})

    complete_markets = sorted(market_results)
    frozen_count = len(frozen_universe)
    path_summaries: dict[str, Any] = {}
    bootstrap_inputs: dict[str, pd.DataFrame] = {}
    for path_name in PATHS:
        per_market = {
            market: {
                "metrics": market_results[market]["paths"][path_name]["metrics"]
            }
            for market in complete_markets
        }
        gate = _gate(per_market, frozen_count)
        pooled = pd.concat(aligned_returns[path_name], axis=1).sort_index()
        if len(pooled.columns) and pooled.isna().any().any():
            raise ValueError("complete markets do not share the evaluation grid")
        bootstrap_inputs[path_name] = pooled
        pooled_returns = (
            pooled.mean(axis=1)
            if len(pooled.columns)
            else pd.Series(dtype=float)
        )
        path_summaries[path_name] = {
            "specification": PATHS[path_name],
            "gate_without_bootstrap": gate,
            "pooled_diagnostic": (
                {
                    "diagnostic_equal_weight_not_executable": True,
                    "net_total_return": base.compound_return(pooled_returns),
                    "net_sharpe": base.sharpe(pooled_returns),
                    "max_drawdown": base.max_drawdown(pooled_returns),
                    "annualized_mean_return": float(
                        pooled_returns.mean() * base.ANNUALIZATION
                    ),
                }
                if len(pooled_returns)
                else None
            ),
        }

    bootstrap = _common_index_bootstrap(bootstrap_inputs) if complete_markets else None
    for path_name in PATHS:
        gate = path_summaries[path_name]["gate_without_bootstrap"]
        gate["bootstrap_lower_bound_positive"] = bool(
            bootstrap is not None
            and bootstrap["per_path"][path_name]["one_sided_95_lower_bound"] > 0.0
        )
        gate["causal_reconstruction_and_fee_checks"] = (
            len(complete_markets) == frozen_count and frozen_count > 0
        )
        path_summaries[path_name]["gate"] = gate
        path_summaries[path_name]["all_gates_pass"] = all(gate.values())

    c1_pass = path_summaries["C1_next_open"]["all_gates_pass"]
    c2_pass = path_summaries["C2_extra_hour_latency"]["all_gates_pass"]
    if not c1_pass:
        verdict = "rejected_under_executable_next_open_replication"
    elif not c2_pass:
        verdict = "rejected_under_one_extra_hour_latency"
    else:
        verdict = "replication_supported_survivorship_blocked"

    result = _clean(
        {
            "schema_version": 2,
            "family_id": "simple-trend-2160h-independent-replication-v1",
            "policy": base.POLICY_SPEC,
            "policy_sha256": policy_hash,
            "universe_sha256": universe_hash,
            "sample": {
                "warmup_start": base.QUAL_START.isoformat(),
                "evaluation_start": base.EVAL_START.isoformat(),
                "evaluation_end": base.EVAL_END.isoformat(),
                "extra_open_timestamp": EXTRA_END.isoformat(),
                "observations_per_complete_market": base.FOLD_HOURS * base.FOLDS,
                "folds": base.FOLDS,
                "fold_hours": base.FOLD_HOURS,
            },
            "candidate_count": 1,
            "stress_path_count": 3,
            "frozen_universe_count": frozen_count,
            "complete_market_count": len(complete_markets),
            "frozen_universe": frozen_universe,
            "complete_markets": complete_markets,
            "rejected_or_unavailable_markets_without_deletion": unavailable,
            "markets": market_results,
            "paths": path_summaries,
            "bootstrap": bootstrap,
            "verdict": verdict,
            "survivorship_classification": (
                "current-live survivorship-conditioned; promotion blocked even on pass"
            ),
            "multiple_testing": {
                "new_family_count": 0,
                "new_candidate_count": 0,
                "rule_is_existing_frozen_benchmark": True,
                "dsr": None,
                "dsr_reason": (
                    "repository-wide independently deduplicated architecture count "
                    "is incomplete"
                ),
                "pbo": None,
                "pbo_reason": (
                    "one fixed rule has no valid candidate-by-split selection matrix"
                ),
            },
        }
    )
    result_hash = base.write_json(output / "result.json", result)
    report = [
        "# Independent 2160H simple-trend replication",
        "",
        f"- Policy SHA-256: `{policy_hash}`",
        f"- Universe SHA-256: `{universe_hash}`",
        f"- Result SHA-256: `{result_hash}`",
        f"- Frozen universe: `{', '.join(frozen_universe) or 'none'}`",
        f"- Complete markets: `{', '.join(complete_markets) or 'none'}`",
        f"- Verdict: `{verdict}`",
        "",
        "C0 is attribution only. C1 and C2 must both pass every frozen gate.",
        "The universe is current-live survivorship-conditioned; a pass cannot promote.",
    ]
    (output / "README.md").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "verdict": verdict,
                "policy_sha256": policy_hash,
                "universe": frozen_universe,
                "result_sha256": result_hash,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
