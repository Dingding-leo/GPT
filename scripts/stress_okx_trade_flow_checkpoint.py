from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Any

import acquire_okx_historical_trades as source


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def archive_instrument_attack(data: bytes, inst_id: str) -> dict[str, Any]:
    text = data.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    fieldnames = reader.fieldnames
    rows = list(reader)
    if not fieldnames or not rows:
        raise ValueError("archive CSV is empty")
    field_by_lower = {field.lower(): field for field in fieldnames}
    instrument_field = next(
        (
            field_by_lower[name]
            for name in ("instrument_name", "instid", "inst_id", "instrument")
            if name in field_by_lower
        ),
        None,
    )
    if instrument_field is None:
        return {
            "archive_instrument_field": None,
            "mutation_rejected": False,
        }

    other = "ETH-USDT" if inst_id == "BTC-USDT" else "BTC-USDT"
    rows[0][instrument_field] = other
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)

    rejected = False
    try:
        source.parse_archive_csv(output.getvalue().encode(), inst_id)
    except ValueError:
        rejected = True
    return {
        "archive_instrument_field": instrument_field,
        "mutated_to": other,
        "mutation_rejected": rejected,
    }


def missing_hour_attack(
    rows: list[source.Trade],
    expected_start_ms: int,
) -> dict[str, Any]:
    ordered = source.canonicalize(rows)
    hours = sorted({row[5] // source.HOUR_MS for row in ordered})
    removed_hour = hours[len(hours) // 2]
    mutated = [row for row in ordered if row[5] // source.HOUR_MS != removed_hour]
    rejected = False
    try:
        source.validate_complete_exchange_day(
            mutated,
            expected_start_ms=expected_start_ms,
        )
    except ValueError:
        rejected = True
    return {
        "removed_hour_start_ms": removed_hour * source.HOUR_MS,
        "removed_trade_count": len(ordered) - len(mutated),
        "mutation_rejected": rejected,
    }


def conflicting_duplicate_attack(rows: list[source.Trade]) -> dict[str, Any]:
    ordered = source.canonicalize(rows)
    mutated = list(ordered)
    duplicate = list(ordered[len(ordered) // 2])
    duplicate[3] *= source.Decimal("1.01")
    mutated.append(tuple(duplicate))  # type: ignore[arg-type]
    rejected = False
    try:
        source.canonicalize(mutated)
    except ValueError:
        rejected = True
    return {"mutation_rejected": rejected}


def rest_overlap_attack(
    root: Path,
    inst_id: str,
    archive_rows: list[source.Trade],
    market: dict[str, Any],
) -> dict[str, Any]:
    older = source.parse_rest((root / "rest-older.json").read_bytes(), inst_id)
    newer = source.parse_rest((root / "rest-newer-bounded.json").read_bytes(), inst_id)
    contract = market["rest_overlap"]
    anchor = int(contract["anchor_trade_id"])
    newer_bound = int(contract["newer_bound_trade_id"])

    archive_ids = {row[1] for row in archive_rows}
    older_ids = {row[1] for row in older}
    newer_ids = {row[1] for row in newer}
    combined = older + newer
    timestamp_counts: dict[int, int] = {}
    for row in combined:
        timestamp_counts[row[5]] = timestamp_counts.get(row[5], 0) + 1

    return {
        "older_rows": len(older),
        "newer_rows": len(newer),
        "older_unique": len(older_ids) == source.REST_PAGE_SIZE,
        "newer_unique": len(newer_ids) == source.REST_PAGE_SIZE,
        "cross_page_unique": not (older_ids & newer_ids),
        "older_cursor_direction": all(row[1] < anchor for row in older),
        "newer_cursor_direction": all(anchor < row[1] < newer_bound for row in newer),
        "all_archive_matched": all(row[1] in archive_ids for row in combined),
        "equal_ms_collision_in_overlap": any(count > 1 for count in timestamp_counts.values()),
        "reported_matched_count": contract["archive_matched_trade_ids"],
        "reported_parity_passed": contract["parity_passed"],
    }


def result_hash_attack(output_dir: Path) -> dict[str, Any]:
    data = (output_dir / "result.json").read_bytes()
    declared = (output_dir / "result.sha256").read_text().strip()
    return {
        "declared_sha256": declared,
        "recomputed_sha256": sha256(data),
        "match": declared == sha256(data),
    }


def audit_market(output_dir: Path, market: dict[str, Any]) -> dict[str, Any]:
    inst_id = market["inst_id"]
    root = output_dir / inst_id
    archive_data = (root / "archive.csv").read_bytes()
    archive_rows = source.canonicalize(source.parse_archive_csv(archive_data, inst_id))
    expected_start_ms = int(market["archive"]["expected_start_ms"])

    instrument_attack = archive_instrument_attack(archive_data, inst_id)
    hour_attack = missing_hour_attack(archive_rows, expected_start_ms)
    duplicate_attack = conflicting_duplicate_attack(archive_rows)
    overlap = rest_overlap_attack(root, inst_id, archive_rows, market)

    defects: list[str] = []
    if not instrument_attack["mutation_rejected"]:
        defects.append("archive_instrument_mutation_not_rejected")
    if not hour_attack["mutation_rejected"]:
        defects.append("missing_complete_hour_not_rejected")
    if not duplicate_attack["mutation_rejected"]:
        defects.append("conflicting_duplicate_not_rejected")
    if overlap["older_rows"] != source.REST_PAGE_SIZE:
        defects.append("older_rest_page_not_exactly_100")
    if overlap["newer_rows"] != source.REST_PAGE_SIZE:
        defects.append("newer_rest_page_not_exactly_100")
    if not overlap["older_unique"] or not overlap["newer_unique"]:
        defects.append("within_page_duplicate_identity")
    if not overlap["cross_page_unique"]:
        defects.append("cross_page_duplicate_identity")
    if not overlap["older_cursor_direction"]:
        defects.append("older_cursor_direction_invalid")
    if not overlap["newer_cursor_direction"]:
        defects.append("newer_cursor_direction_invalid")
    if not overlap["all_archive_matched"]:
        defects.append("rest_id_absent_from_archive")
    if not overlap["equal_ms_collision_in_overlap"]:
        defects.append("no_equal_ms_collision_in_matched_overlap")
    if overlap["reported_matched_count"] != 2 * source.REST_PAGE_SIZE:
        defects.append("reported_archive_match_count_not_200")
    if not overlap["reported_parity_passed"]:
        defects.append("reported_parity_failed")

    return {
        "inst_id": inst_id,
        "archive_rows": len(archive_rows),
        "expected_start_ms": expected_start_ms,
        "mixed_instrument_attack": instrument_attack,
        "missing_hour_attack": hour_attack,
        "conflicting_duplicate_attack": duplicate_attack,
        "rest_overlap_attack": overlap,
        "defects": defects,
        "status": "passed" if not defects else "blocked",
    }


def run(output_dir: Path) -> dict[str, Any]:
    source_result_path = output_dir / "result.json"
    source_result = json.loads(source_result_path.read_text())
    markets: list[dict[str, Any]] = []
    for market in source_result["markets"]:
        if market.get("status") != "checkpoint_passed":
            markets.append(
                {
                    "inst_id": market.get("inst_id"),
                    "status": "blocked",
                    "defects": ["source_checkpoint_not_passed"],
                }
            )
        else:
            markets.append(audit_market(output_dir, market))

    defects = sorted({defect for market in markets for defect in market["defects"]})
    hash_attack = result_hash_attack(output_dir)
    if not hash_attack["match"]:
        defects.append("result_sha256_mismatch")

    verdict = (
        "trade_flow_source_schema_checkpoint_survived_adversarial_stress"
        if not defects
        else "trade_flow_source_schema_checkpoint_blocked_by_adversarial_stress"
    )
    result = {
        "schema_version": "trade-flow-checkpoint-adversarial-stress-v2",
        "architecture_family_id": source_result["architecture_family_id"],
        "candidate_count": source_result["candidate_count"],
        "canonical_fee_bps_one_way": source_result["canonical_fee_bps_one_way"],
        "performance_inspected": False,
        "oos_consumed": False,
        "attacks": [
            "archive mixed-instrument mutation",
            "complete-hour deletion",
            "conflicting duplicate mutation",
            "two-sided cursor and archive parity",
            "equal-millisecond collision inside matched overlap",
            "result SHA-256 reconstruction",
        ],
        "markets": markets,
        "pre_stress_result_hash": hash_attack,
        "defects": defects,
        "verdict": verdict,
        "strategy_consequence": (
            "Checkpoint may proceed to substantive review."
            if not defects
            else "V1/V2 performance remains prohibited until the source checkpoint is repaired."
        ),
    }
    stress_bytes = canonical_json(result)
    (output_dir / "stress-result.json").write_bytes(stress_bytes)
    (output_dir / "stress-result.sha256").write_text(sha256(stress_bytes) + "\n")

    source_result["adversarial_stress"] = {
        "schema_version": result["schema_version"],
        "verdict": verdict,
        "defects": defects,
        "sha256": sha256(stress_bytes),
    }
    source_result["verdict"] = verdict
    source_bytes = canonical_json(source_result)
    source_result_path.write_bytes(source_bytes)
    (output_dir / "result.sha256").write_text(sha256(source_bytes) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        default="reports/okx/trade-flow-schema-checkpoint",
    )
    args = parser.parse_args()
    result = run(Path(args.output_dir))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
