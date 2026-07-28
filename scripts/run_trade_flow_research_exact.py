from __future__ import annotations

import hashlib
import json
import math
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import run_trade_flow_research as base


ORIGINAL_FETCH_CANDLES = base.fetch_okx_one_hour_candles


def acquire_trade_features(
    base_url: str,
    inst_id: str,
    start_ms: int,
    end_ms: int,
    output_dir: Path,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    records, manifests = base.collect_monthly_records(
        base_url,
        inst_id,
        start_ms,
        end_ms,
        output_dir,
    )
    parsed_files: list[base.ParsedFile] = []
    file_inventory: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix=f"{inst_id}-archives-") as temporary:
        temp_root = Path(temporary)
        for index, record in enumerate(records):
            archive_path = temp_root / f"archive-{index:03d}.bin"
            csv_path = temp_root / f"archive-{index:03d}.csv"
            download = base.download_to_file(record["url"], archive_path)
            member = base.extract_member(archive_path, csv_path)
            parsed = base.parse_csv_file(csv_path, inst_id, start_ms, end_ms)
            parsed_files.append(parsed)
            file_inventory.append(
                {
                    "manifest_record": record["manifest_record"],
                    "download": download,
                    "member": member,
                    "observed": parsed.metadata,
                    "raw_archive_retained_in_artifact": False,
                    "replay_contract": (
                        "trusted URL plus exact compressed and decompressed SHA-256"
                    ),
                }
            )
            archive_path.unlink(missing_ok=True)
            csv_path.unlink(missing_ok=True)
    merged = base.merge_hours(parsed_files, start_ms, end_ms)
    rows: list[dict[str, Any]] = []
    for hour in sorted(merged):
        item = merged[hour]
        if item.total <= 0 or item.first_price is None or item.last_price is None:
            raise ValueError("invalid hourly trade aggregate")
        rows.append(
            {
                "timestamp": pd.Timestamp(hour, unit="ms", tz="UTC"),
                "trade_count": item.count,
                "signed_quote_notional": float(item.signed),
                "total_quote_notional": float(item.total),
                "flow": float(item.signed / item.total),
                "impact_return": math.log(float(item.last_price / item.first_price)),
                "first_trade_id": str(item.first_trade_id),
                "last_trade_id": str(item.last_trade_id),
            }
        )
    frame = pd.DataFrame(rows).set_index("timestamp")
    csv_bytes = frame.to_csv(
        index=True,
        lineterminator="\n",
        float_format="%.18g",
    ).encode()
    feature_record = base.persist(
        output_dir / "hourly-trade-features.csv",
        csv_bytes,
    )
    metadata = {
        "instrument": inst_id,
        "manifest_queries": manifests,
        "archive_files": file_inventory,
        "archive_file_count": len(file_inventory),
        "selected_trade_rows": int(frame["trade_count"].sum()),
        "complete_hours": len(frame),
        "missing_hours": 0,
        "feature_record": feature_record,
        "raw_archive_bytes_retained": False,
        "flow6_accounting": (
            "exact signed quote notional divided by exact total quote notional"
        ),
        "streaming_disk_policy": (
            "each compressed and decompressed archive is deleted after hashing and parsing"
        ),
    }
    base.persist(
        output_dir / "archive-inventory.json",
        base.canonical_json(metadata),
    )
    return frame, metadata


def build_targets(features: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    flow = features["flow"].astype(float)
    impact = features["impact_return"].astype(float)
    signed = features["signed_quote_notional"].astype(float)
    total = features["total_quote_notional"].astype(float)
    flow6 = signed.rolling(6, min_periods=6).sum() / total.rolling(
        6,
        min_periods=6,
    ).sum()
    prior_flow6 = flow6.shift(1)
    median_flow = prior_flow6.rolling(
        base.WARMUP_HOURS,
        min_periods=base.WARMUP_HOURS,
    ).median()
    mad_flow = base.rolling_mad(prior_flow6, base.WARMUP_HOURS)
    z_flow = (flow6 - median_flow) / mad_flow.replace(0.0, np.nan)
    v1 = np.tanh(z_flow).clip(lower=0.0)

    x = flow.to_numpy(dtype=float)
    y = impact.to_numpy(dtype=float)
    z_residual = np.full(len(features), np.nan)
    for index in range(base.WARMUP_HOURS, len(features)):
        train_x = x[index - base.WARMUP_HOURS : index]
        train_y = y[index - base.WARMUP_HOURS : index]
        if not np.isfinite(train_x).all() or not np.isfinite(train_y).all():
            continue
        x_mean = float(train_x.mean())
        y_mean = float(train_y.mean())
        denominator = float(np.square(train_x - x_mean).sum())
        if denominator <= 0:
            continue
        beta = float(
            ((train_x - x_mean) * (train_y - y_mean)).sum() / denominator
        )
        alpha = y_mean - beta * x_mean
        residuals = train_y - (alpha + beta * train_x)
        scale = float(np.median(np.abs(residuals - np.median(residuals))))
        if not math.isfinite(scale) or scale <= 0:
            continue
        z_residual[index] = (y[index] - (alpha + beta * x[index])) / scale
    z_series = pd.Series(z_residual, index=features.index)
    resilience6 = z_series.rolling(6, min_periods=6).mean()
    v2 = np.tanh(resilience6).clip(lower=0.0)
    targets = pd.DataFrame({"V1": v1, "V2": v2}, index=features.index)
    invalid = {
        "V1": int(targets["V1"].isna().sum()),
        "V2": int(targets["V2"].isna().sum()),
    }
    return targets.fillna(0.0), invalid


def fetch_candles_with_benchmark_prehistory(
    *,
    inst_id: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    base_url: str,
    pause_seconds: float,
    timeout: float,
) -> Any:
    benchmark_start = start - pd.Timedelta(hours=base.TREND_LOOKBACK)
    return ORIGINAL_FETCH_CANDLES(
        inst_id=inst_id,
        start=benchmark_start,
        end=end,
        base_url=base_url,
        pause_seconds=pause_seconds,
        timeout=timeout,
    )


def evaluate_market_with_benchmark_prehistory(
    inst_id: str,
    features: pd.DataFrame,
    close: pd.Series,
    development_start: pd.Timestamp,
    development_end: pd.Timestamp,
    output_dir: Path,
) -> tuple[dict[str, Any], dict[str, pd.DataFrame]]:
    development_close = close.reindex(features.index)
    if development_close.isna().any():
        raise ValueError(f"feature/candle development index mismatch for {inst_id}")
    prehistory = close.loc[close.index < development_start]
    if len(prehistory) != base.TREND_LOOKBACK:
        raise ValueError(
            f"benchmark prehistory mismatch for {inst_id}: "
            f"expected={base.TREND_LOOKBACK} observed={len(prehistory)}"
        )

    targets, invalid = build_targets(features)
    frames = {
        variant: base.strategy_frame(targets[variant], development_close)
        for variant in ("V1", "V2")
    }
    trend_full = base.trend_frame(close)
    evaluation_start = development_start + pd.Timedelta(hours=base.WARMUP_HOURS)
    evaluation_end = development_end - pd.Timedelta(hours=1)
    evaluation_frames = {
        name: frame.loc[evaluation_start:evaluation_end].copy()
        for name, frame in frames.items()
    }
    evaluation_frames["trend"] = trend_full.loc[
        evaluation_start:evaluation_end
    ].copy()
    if any(
        len(frame) != base.EVALUATION_HOURS
        for frame in evaluation_frames.values()
    ):
        raise ValueError("evaluation window is not exactly twelve 90-day folds")

    per_policy: dict[str, Any] = {}
    for name, frame in evaluation_frames.items():
        fold_rows: list[dict[str, Any]] = []
        for fold in range(base.FOLDS):
            fold_frame = frame.iloc[
                fold * base.FOLD_HOURS : (fold + 1) * base.FOLD_HOURS
            ]
            fold_rows.append({"fold": fold + 1, **base.metrics(fold_frame)})
        positive = [
            row["net_return"]
            for row in fold_rows
            if row["net_return"] > 0
        ]
        blocks = [
            base.metrics(frame.iloc[index * 8640 : (index + 1) * 8640])
            for index in range(3)
        ]
        aggregate = base.metrics(frame)
        aggregate.update(
            {
                "invalid_feature_hours_in_full_development": invalid.get(name, 0),
                "profitable_folds": sum(
                    row["net_return"] > 0 for row in fold_rows
                ),
                "positive_fold_concentration": (
                    None if not positive else max(positive) / sum(positive)
                ),
                "folds": fold_rows,
                "blocks_360d": blocks,
            }
        )
        per_policy[name] = aggregate

    for variant in ("V1", "V2"):
        residual = (
            evaluation_frames[variant]["net_return"]
            - evaluation_frames["trend"]["net_return"]
        )
        per_policy[variant]["residual_return_vs_trend_arithmetic"] = float(
            residual.sum()
        )
        per_policy[variant]["residual_sharpe_vs_trend"] = base.sharpe(
            residual
        )
        trend_edge = per_policy["trend"]["edge_per_turnover_bps"]
        variant_edge = per_policy[variant]["edge_per_turnover_bps"]
        per_policy[variant]["edge_per_turnover_delta_vs_trend_bps"] = (
            None
            if variant_edge is None or trend_edge is None
            else variant_edge - trend_edge
        )

    output = pd.concat(evaluation_frames, axis=1)
    base.persist(
        output_dir / "evaluation-paths.csv",
        output.to_csv(
            lineterminator="\n",
            float_format="%.18g",
        ).encode(),
    )
    return {
        "instrument": inst_id,
        "development_start": development_start.isoformat(),
        "development_end_exclusive": development_end.isoformat(),
        "evaluation_start": evaluation_start.isoformat(),
        "evaluation_end_inclusive": evaluation_end.isoformat(),
        "candidate_fold_evaluations": 2 * base.FOLDS,
        "benchmark": {
            "policy": "simple_trend_long_cash_2160h",
            "lookback_hours": base.TREND_LOOKBACK,
            "prehistory_hours": len(prehistory),
            "evaluation_window_identical": True,
        },
        "policies": per_policy,
    }, evaluation_frames


def main() -> None:
    if base.TREND_LOOKBACK != 2160:
        raise ValueError("frozen simple-trend benchmark lookback changed")
    base.acquire_trade_features = acquire_trade_features
    base.build_targets = build_targets
    base.fetch_okx_one_hour_candles = fetch_candles_with_benchmark_prehistory
    base.evaluate_market = evaluate_market_with_benchmark_prehistory
    args = base.parse_args()
    result = base.run(args.base_url, args.output_dir)
    executed = {
        "verdict": result["verdict"],
        "failures": result["qualification_failures"],
        "result_sha256": hashlib.sha256(
            (args.output_dir / "result.json").read_bytes()
        ).hexdigest(),
    }
    print(json.dumps(executed, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
