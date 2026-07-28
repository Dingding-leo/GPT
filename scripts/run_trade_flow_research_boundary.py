from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import run_trade_flow_research as base
import run_trade_flow_research_exact as exact


@dataclass
class BoundaryParsedFile:
    metadata: dict[str, Any]
    hours: dict[int, base.HourAggregate]
    boundary_rows: dict[int, list[base.source.Trade]]


BOUNDARY_MERGE_DIAGNOSTIC: dict[str, Any] = {
    "overlapping_boundary_hours": 0,
    "cross_file_duplicate_trades_removed": 0,
    "maximum_files_per_boundary_hour": 1,
    "all_overlaps_limited_to_boundary_hours": True,
    "canonical_timestamp_numeric_id_order": True,
}


def parse_csv_file(
    csv_path: Path,
    inst_id: str,
    start_ms: int,
    end_ms: int,
) -> BoundaryParsedFile:
    hours: dict[int, base.HourAggregate] = {}
    rows = 0
    selected_rows = 0
    duplicate_rows = 0
    min_ts: int | None = None
    max_ts: int | None = None
    previous: base.source.Trade | None = None
    first_selected_hour: int | None = None
    first_hour_rows: list[base.source.Trade] = []
    last_selected_hour: int | None = None
    last_hour_rows: list[base.source.Trade] = []

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = base.archive_fields(reader.fieldnames)
        inst_field, id_field, side_field, price_field, size_field, ts_field = fields
        header = list(reader.fieldnames or [])
        for raw in reader:
            observed_inst = str(raw.get(inst_field, "")).strip()
            if observed_inst != inst_id:
                raise ValueError(f"mixed archive instrument: {observed_inst}")
            trade = base.source.normalize_trade(
                inst_id,
                raw.get(id_field),
                raw.get(side_field),
                raw.get(price_field),
                raw.get(size_field),
                raw.get(ts_field),
            )
            rows += 1
            if previous is not None:
                if trade[1] == previous[1]:
                    if trade != previous:
                        raise ValueError("conflicting duplicate trade identity")
                    duplicate_rows += 1
                    continue
                if trade[1] < previous[1] or trade[5] < previous[5]:
                    raise ValueError("archive provider order is not chronological")
            previous = trade
            min_ts = trade[5] if min_ts is None else min(min_ts, trade[5])
            max_ts = trade[5] if max_ts is None else max(max_ts, trade[5])
            if not start_ms <= trade[5] < end_ms:
                continue

            selected_rows += 1
            hour = trade[5] // base.HOUR_MS * base.HOUR_MS
            aggregate = hours.setdefault(hour, base.HourAggregate())
            quote = trade[3] * trade[4]
            aggregate.total += quote
            aggregate.signed += quote if trade[2] == "buy" else -quote
            aggregate.count += 1
            if aggregate.first_price is None:
                aggregate.first_price = trade[3]
                aggregate.first_trade_id = trade[1]
            aggregate.last_price = trade[3]
            aggregate.last_trade_id = trade[1]

            if first_selected_hour is None:
                first_selected_hour = hour
            if hour == first_selected_hour:
                first_hour_rows.append(trade)
            if last_selected_hour != hour:
                last_selected_hour = hour
                last_hour_rows = []
            last_hour_rows.append(trade)

    if rows == 0 or min_ts is None or max_ts is None:
        raise ValueError("archive CSV contains no trades")

    boundary_rows: dict[int, list[base.source.Trade]] = {}
    if first_selected_hour is not None:
        boundary_rows[first_selected_hour] = first_hour_rows
    if last_selected_hour is not None:
        boundary_rows[last_selected_hour] = last_hour_rows
    return BoundaryParsedFile(
        metadata={
            "header": header,
            "rows": rows,
            "selected_rows": selected_rows,
            "exact_duplicate_rows_removed": duplicate_rows,
            "min_ts_ms": min_ts,
            "max_ts_ms": max_ts,
            "min_ts": base.utc_timestamp(min_ts),
            "max_ts": base.utc_timestamp(max_ts),
            "first_selected_hour_ms": first_selected_hour,
            "last_selected_hour_ms": last_selected_hour,
            "boundary_hour_rows_retained_for_cross_file_deduplication": True,
        },
        hours=hours,
        boundary_rows=boundary_rows,
    )


def aggregate_rows(rows: list[base.source.Trade], hour: int) -> base.HourAggregate:
    unique: dict[tuple[str, int], base.source.Trade] = {}
    duplicate_count = 0
    for row in rows:
        key = row[0], row[1]
        previous = unique.get(key)
        if previous is not None:
            if previous != row:
                raise ValueError("conflicting cross-file duplicate trade identity")
            duplicate_count += 1
            continue
        unique[key] = row
    ordered = sorted(unique.values(), key=lambda row: (row[5], row[1]))
    if not ordered:
        raise ValueError("boundary-hour reconstruction is empty")
    if any(row[5] // base.HOUR_MS * base.HOUR_MS != hour for row in ordered):
        raise ValueError("boundary reconstruction contains a trade from another hour")
    if any(
        left[1] >= right[1] or left[5] > right[5]
        for left, right in zip(ordered, ordered[1:], strict=False)
    ):
        raise ValueError("cross-file boundary chronology is not strictly causal")

    aggregate = base.HourAggregate()
    for row in ordered:
        quote = row[3] * row[4]
        aggregate.total += quote
        aggregate.signed += quote if row[2] == "buy" else -quote
        aggregate.count += 1
        if aggregate.first_price is None:
            aggregate.first_price = row[3]
            aggregate.first_trade_id = row[1]
        aggregate.last_price = row[3]
        aggregate.last_trade_id = row[1]
    BOUNDARY_MERGE_DIAGNOSTIC["cross_file_duplicate_trades_removed"] += duplicate_count
    return aggregate


def merge_hours(
    parsed_files: list[BoundaryParsedFile],
    start_ms: int,
    end_ms: int,
) -> dict[int, base.HourAggregate]:
    ordered_files = sorted(parsed_files, key=lambda item: item.metadata["min_ts_ms"])
    for left, right in zip(ordered_files, ordered_files[1:], strict=False):
        if left.metadata["min_ts_ms"] >= right.metadata["min_ts_ms"]:
            raise ValueError("monthly archive files do not have strict start chronology")
        if left.metadata["max_ts_ms"] > right.metadata["max_ts_ms"]:
            raise ValueError("monthly archive files invert terminal event chronology")

    merged: dict[int, base.HourAggregate] = {}
    boundary_rows: dict[int, list[base.source.Trade]] = {}
    overlap_file_counts: dict[int, int] = {}
    for parsed in ordered_files:
        for hour, item in sorted(parsed.hours.items()):
            if hour not in merged:
                merged[hour] = item
                if hour in parsed.boundary_rows:
                    boundary_rows[hour] = list(parsed.boundary_rows[hour])
                continue

            existing_rows = boundary_rows.get(hour)
            incoming_rows = parsed.boundary_rows.get(hour)
            if existing_rows is None or incoming_rows is None:
                BOUNDARY_MERGE_DIAGNOSTIC[
                    "all_overlaps_limited_to_boundary_hours"
                ] = False
                raise ValueError("monthly archives overlap outside retained boundary hours")
            combined = existing_rows + incoming_rows
            merged[hour] = aggregate_rows(combined, hour)
            boundary_rows[hour] = sorted(
                {(row[0], row[1]): row for row in combined}.values(),
                key=lambda row: (row[5], row[1]),
            )
            overlap_file_counts[hour] = overlap_file_counts.get(hour, 1) + 1

    expected = list(range(start_ms, end_ms, base.HOUR_MS))
    if sorted(merged) != expected:
        missing = sorted(set(expected) - set(merged))
        extra = sorted(set(merged) - set(expected))
        raise ValueError(
            "hourly trade coverage mismatch after boundary repair: "
            f"missing={len(missing)} extra={len(extra)}"
        )
    BOUNDARY_MERGE_DIAGNOSTIC["overlapping_boundary_hours"] = len(
        overlap_file_counts
    )
    BOUNDARY_MERGE_DIAGNOSTIC["maximum_files_per_boundary_hour"] = max(
        overlap_file_counts.values(),
        default=1,
    )
    return merged


def main() -> None:
    if base.TREND_LOOKBACK != 2160:
        raise ValueError("frozen simple-trend benchmark lookback changed")
    if math.isfinite(exact.strict_cross_market_min([1.0, float("nan")])):
        raise AssertionError("undefined-market fail-closed diagnostic failed")

    base.parse_csv_file = parse_csv_file
    base.merge_hours = merge_hours
    base.acquire_trade_features = exact.acquire_trade_features
    base.build_targets = exact.build_targets
    base.fetch_okx_one_hour_candles = exact.fetch_candles_with_benchmark_prehistory
    base.evaluate_market = exact.evaluate_market_with_benchmark_prehistory
    base.inference = exact.inference_with_strict_cross_market_undefined
    args = base.parse_args()
    result = base.run(args.base_url, args.output_dir)
    result["review_driven_month_boundary_repair"] = BOUNDARY_MERGE_DIAGNOSTIC
    result_bytes = base.canonical_json(result)
    base.persist(args.output_dir / "result.json", result_bytes)
    base.persist(
        args.output_dir / "result.sha256",
        (hashlib.sha256(result_bytes).hexdigest() + "\n").encode(),
    )
    print(
        json.dumps(
            {
                "verdict": result["verdict"],
                "failures": result["qualification_failures"],
                "result_sha256": hashlib.sha256(result_bytes).hexdigest(),
                "boundary_repair": BOUNDARY_MERGE_DIAGNOSTIC,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
