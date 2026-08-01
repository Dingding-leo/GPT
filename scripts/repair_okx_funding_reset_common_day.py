#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from research_okx_funding_reset_episode import (
    FUNDING_END,
    FUNDING_START,
    SPOT_END,
    SPOT_START,
    build_labels,
    canonical_json_bytes,
)


def parse_float(value: Any) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("non-finite source value")
    return result


def reconstruct_labels(
    source_manifest: dict[str, Any],
    *,
    market: str,
) -> pd.DataFrame:
    funding_records: dict[int, dict[str, Any]] = {}
    candle_records: dict[int, tuple[int, float, float, float, float]] = {}
    swap_id = f"{market}-SWAP"
    for page in source_manifest["pages"]:
        if page["market"] != market:
            continue
        rows = page["payload"]["data"]
        if page["kind"] == "funding_rate_history":
            for raw in rows:
                if raw.get("instId") != swap_id or "realizedRate" not in raw:
                    raise ValueError(f"{market} funding replay identity mismatch")
                timestamp = int(raw["fundingTime"])
                funding_records[timestamp] = {
                    "funding_time_ms": timestamp,
                    "realized_rate": parse_float(raw["realizedRate"]),
                }
        elif page["kind"] == "spot_history_candles":
            for raw in rows:
                if len(raw) != 9 or raw[8] != "1":
                    continue
                timestamp = int(raw[0])
                candle_records[timestamp] = (
                    timestamp,
                    parse_float(raw[1]),
                    parse_float(raw[2]),
                    parse_float(raw[3]),
                    parse_float(raw[4]),
                )

    funding = pd.DataFrame(
        sorted(funding_records.values(), key=lambda row: row["funding_time_ms"])
    )
    funding["timestamp"] = pd.to_datetime(funding["funding_time_ms"], unit="ms", utc=True)
    funding = funding[
        (funding["timestamp"] >= FUNDING_START) & (funding["timestamp"] <= FUNDING_END)
    ].reset_index(drop=True)

    candles = pd.DataFrame(
        list(candle_records.values()),
        columns=["timestamp_ms", "open", "high", "low", "close"],
    )
    candles["timestamp"] = pd.to_datetime(candles["timestamp_ms"], unit="ms", utc=True)
    candles = candles[
        (candles["timestamp"] >= SPOT_START) & (candles["timestamp"] <= SPOT_END)
    ].sort_values("timestamp").reset_index(drop=True)
    return build_labels(funding=funding, candles=candles, delay_hours=1)


def daily_effects(labels: pd.DataFrame) -> dict[str, dict[str, float]]:
    effects: dict[str, dict[str, float]] = {}
    for day, rows in labels.groupby("decision_day", sort=True):
        events = rows[rows["event"]]
        controls = rows[~rows["event"]]
        if events.empty or controls.empty:
            continue
        effects[pd.Timestamp(day).date().isoformat()] = {
            "net_difference": float(
                events["net_24h"].mean() - controls["net_24h"].mean()
            ),
            "adverse_difference": float(
                events["adverse_24h"].mean() - controls["adverse_24h"].mean()
            ),
            "events": int(len(events)),
            "controls": int(len(controls)),
        }
    return effects


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    args = parser.parse_args()

    evidence_path = args.artifact_dir / "evidence.json"
    source_path = args.artifact_dir / "source-manifest.json"
    report_path = args.artifact_dir / "report.md"
    identities_path = args.artifact_dir / "identities.json"

    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    source_manifest = json.loads(source_path.read_text(encoding="utf-8"))
    if evidence.get("source_feasible") is not True:
        return 0

    market_effects = {
        market: daily_effects(reconstruct_labels(source_manifest, market=market))
        for market in evidence["markets_required"]
    }
    common_days = sorted(set.intersection(*(set(value) for value in market_effects.values())))
    rows: list[dict[str, Any]] = []
    for day in common_days:
        net_values = [
            market_effects[market][day]["net_difference"]
            for market in evidence["markets_required"]
        ]
        adverse_values = [
            market_effects[market][day]["adverse_difference"]
            for market in evidence["markets_required"]
        ]
        rows.append(
            {
                "day": day,
                "market_effects": {
                    market: market_effects[market][day]
                    for market in evidence["markets_required"]
                },
                "paired_market_median_net_difference": float(np.median(net_values)),
                "paired_market_median_adverse_difference": float(np.median(adverse_values)),
            }
        )

    summary = {
        "common_day_count": len(rows),
        "median_net_difference_across_common_days": (
            float(np.median([row["paired_market_median_net_difference"] for row in rows]))
            if rows
            else None
        ),
        "median_adverse_difference_across_common_days": (
            float(
                np.median(
                    [row["paired_market_median_adverse_difference"] for row in rows]
                )
            )
            if rows
            else None
        ),
        "positive_net_common_days": sum(
            row["paired_market_median_net_difference"] > 0 for row in rows
        ),
        "positive_adverse_common_days": sum(
            row["paired_market_median_adverse_difference"] > 0 for row in rows
        ),
        "days": rows,
        "can_rescue_independent_market_gate": False,
    }
    evidence["supplementary_paired_common_day_median"] = summary

    evidence_bytes = canonical_json_bytes(evidence)
    evidence_path.write_bytes(evidence_bytes)
    evidence_hash = hashlib.sha256(evidence_bytes).hexdigest()
    (args.artifact_dir / "evidence.sha256").write_text(
        f"{evidence_hash}  evidence.json\n", encoding="utf-8"
    )

    report = report_path.read_text(encoding="utf-8").rstrip()
    report += (
        "\n\n## Supplementary paired common-day median\n\n"
        f"Common event/control days: {summary['common_day_count']}. "
        f"Median paired-market net difference: "
        f"{summary['median_net_difference_across_common_days']}. "
        f"Median paired-market adverse difference: "
        f"{summary['median_adverse_difference_across_common_days']}. "
        f"Positive net common days: {summary['positive_net_common_days']}/"
        f"{summary['common_day_count']}; positive adverse common days: "
        f"{summary['positive_adverse_common_days']}/{summary['common_day_count']}.\n\n"
        "This supplementary statistic is descriptive only and cannot rescue either "
        "independent market gate.\n"
    )
    report_path.write_text(report, encoding="utf-8")

    identities = json.loads(identities_path.read_text(encoding="utf-8"))
    identities["evidence_sha256"] = evidence_hash
    identities["report_sha256"] = hashlib.sha256(report_path.read_bytes()).hexdigest()
    identities["repair"] = "add_preregistered_paired_common_day_median_only"
    identities_path.write_bytes(canonical_json_bytes(identities))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
