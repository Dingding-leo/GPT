from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

MARKETS = ("BTC-USDT", "ETH-USDT")
EXPECTED_PAGE_SIZE = 100


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_archive(path: Path, inst_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {
            "instrument_name",
            "trade_id",
            "side",
            "price",
            "size",
            "created_time",
        }
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise ValueError(f"{inst_id}: incomplete archive schema")
        for raw in reader:
            if raw["instrument_name"] != inst_id:
                raise ValueError(f"{inst_id}: mixed archive instrument")
            rows.append(
                {
                    "inst_id": inst_id,
                    "trade_id": int(raw["trade_id"]),
                    "side": raw["side"],
                    "price": Decimal(raw["price"]),
                    "size": Decimal(raw["size"]),
                    "ts_ms": int(raw["created_time"]),
                }
            )
    if not rows:
        raise ValueError(f"{inst_id}: empty archive")
    return rows


def parse_rest(path: Path, inst_id: str) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text())
    if str(payload.get("code")) != "0" or not isinstance(payload.get("data"), list):
        raise ValueError(f"{inst_id}: invalid REST payload")
    rows: list[dict[str, Any]] = []
    for raw in payload["data"]:
        if raw.get("instId") != inst_id:
            raise ValueError(f"{inst_id}: mixed REST instrument")
        rows.append(
            {
                "inst_id": inst_id,
                "trade_id": int(raw["tradeId"]),
                "side": raw["side"],
                "price": Decimal(raw["px"]),
                "size": Decimal(raw["sz"]),
                "ts_ms": int(raw["ts"]),
            }
        )
    return rows


def economic_tuple(row: dict[str, Any]) -> tuple[Any, ...]:
    return row["side"], row["price"], row["size"], row["ts_ms"]


def page_audit(
    rows: list[dict[str, Any]],
    archive_by_id: dict[int, dict[str, Any]],
    anchor: int,
    expected_side: str,
) -> dict[str, Any]:
    overlaps = [row for row in rows if row["trade_id"] in archive_by_id]
    mismatches = [
        row
        for row in overlaps
        if economic_tuple(row) != economic_tuple(archive_by_id[row["trade_id"]])
    ]
    ids = [row["trade_id"] for row in rows]
    direction_ok = (
        all(value < anchor for value in ids)
        if expected_side == "older"
        else all(value > anchor for value in ids)
    )
    exact_archive_overlap = (
        len(rows) == EXPECTED_PAGE_SIZE
        and len(overlaps) == EXPECTED_PAGE_SIZE
        and not mismatches
        and direction_ok
    )
    return {
        "rows": len(rows),
        "minimum_trade_id": min(ids),
        "maximum_trade_id": max(ids),
        "minimum_ts_ms": min(row["ts_ms"] for row in rows),
        "maximum_ts_ms": max(row["ts_ms"] for row in rows),
        "archive_overlap_rows": len(overlaps),
        "economic_mismatch_rows": len(mismatches),
        "expected_side": expected_side,
        "direction_ok": direction_ok,
        "nearest_trade_id_distance_to_anchor": min(abs(value - anchor) for value in ids),
        "exact_100_row_archive_overlap_passed": exact_archive_overlap,
    }


def audit_market(root: Path, inst_id: str) -> dict[str, Any]:
    market_root = root / inst_id
    archive_path = market_root / "archive.csv"
    archive_rows = parse_archive(archive_path, inst_id)
    archive_by_id = {row["trade_id"]: row for row in archive_rows}
    if len(archive_by_id) != len(archive_rows):
        raise ValueError(f"{inst_id}: duplicate archive trade identity")
    ordered_ids = sorted(archive_by_id)
    anchor = ordered_ids[len(ordered_ids) // 2]
    after = page_audit(
        parse_rest(market_root / "rest-after.json", inst_id),
        archive_by_id,
        anchor,
        "older",
    )
    before = page_audit(
        parse_rest(market_root / "rest-before.json", inst_id),
        archive_by_id,
        anchor,
        "newer",
    )
    combined_overlap = after["archive_overlap_rows"] + before["archive_overlap_rows"]
    old_aggregate_gate_passed = (
        combined_overlap >= 20
        and after["economic_mismatch_rows"] + before["economic_mismatch_rows"] == 0
    )
    frozen_two_sided_gate_passed = (
        after["exact_100_row_archive_overlap_passed"]
        and before["exact_100_row_archive_overlap_passed"]
    )
    minimum_ts_ms = min(row["ts_ms"] for row in archive_rows)
    maximum_ts_ms = max(row["ts_ms"] for row in archive_rows)
    return {
        "archive_csv_sha256": sha256_file(archive_path),
        "archive_rows": len(archive_rows),
        "archive_minimum_trade_id": ordered_ids[0],
        "archive_maximum_trade_id": ordered_ids[-1],
        "archive_minimum_ts_ms": minimum_ts_ms,
        "archive_maximum_ts_ms": maximum_ts_ms,
        "archive_minimum_utc": datetime.fromtimestamp(
            minimum_ts_ms / 1000, UTC
        ).isoformat(),
        "archive_maximum_utc": datetime.fromtimestamp(
            maximum_ts_ms / 1000, UTC
        ).isoformat(),
        "anchor_trade_id": anchor,
        "anchor_ts_ms": archive_by_id[anchor]["ts_ms"],
        "after_page": after,
        "before_page": before,
        "combined_archive_overlap_rows": combined_overlap,
        "legacy_aggregate_overlap_gate_passed": old_aggregate_gate_passed,
        "frozen_two_sided_overlap_gate_passed": frozen_two_sided_gate_passed,
        "false_pass_reproduced": (
            old_aggregate_gate_passed and not frozen_two_sided_gate_passed
        ),
    }


def run(artifact_root: Path, artifact_sha256: str) -> dict[str, Any]:
    markets = {market: audit_market(artifact_root, market) for market in MARKETS}
    false_pass = all(item["false_pass_reproduced"] for item in markets.values())
    return {
        "schema_version": "trade-flow-source-checkpoint-integration-audit-v1",
        "architecture_family_id": "okx-spot-causal-trade-flow-resilience-v2",
        "candidate_count": 2,
        "canonical_fee_bps_one_way": 5.0,
        "source_workflow_run": 30367844773,
        "source_workflow_artifact_id": 8691619707,
        "source_workflow_artifact_sha256": artifact_sha256,
        "source_execution_head": "554df30de28da4b6600b61e37d793c60f911da69",
        "performance_inspected": False,
        "oos_consumed": False,
        "attack": (
            "separate each REST cursor page before archive overlap qualification; "
            "require the frozen 100-row overlap on both sides of the archive anchor"
        ),
        "markets": markets,
        "false_pass_reproduced": false_pass,
        "verdict": (
            "checkpoint_rejected_frozen_two_sided_archive_rest_overlap_not_proven"
            if false_pass
            else "checkpoint_not_falsified_by_two_sided_overlap_attack"
        ),
        "integration_decision": "do_not_merge_or_authorize_performance",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact_root", type=Path)
    parser.add_argument("--artifact-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.artifact_root, args.artifact_sha256)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
