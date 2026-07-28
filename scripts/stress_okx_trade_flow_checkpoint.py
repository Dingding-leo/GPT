from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Any

import acquire_okx_historical_trades as source

HOUR_MS = 3_600_000
DAY_MS = 24 * HOUR_MS


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def manifest_groups(root: Path) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for path in sorted(root.glob("manifest-*.json")):
        payload = json.loads(path.read_text())
        for datum in payload.get("data", []):
            for detail in datum.get("details", []):
                for group in detail.get("groupDetails", []):
                    if isinstance(group, dict):
                        groups.append(group)
    return groups


def archive_instrument_attack(data: bytes, inst_id: str) -> dict[str, Any]:
    text = data.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    fieldnames = reader.fieldnames
    rows = list(reader)
    if not fieldnames or not rows:
        raise ValueError("archive CSV is empty")
    instrument_field = next(
        (field for field in ("instrument_name", "instId", "inst_id") if field in fieldnames),
        None,
    )
    if instrument_field is None:
        return {
            "archive_instrument_field": None,
            "current_parser_accepted_mutation": True,
            "feature_bytes_unchanged": True,
        }

    other = "ETH-USDT" if inst_id == "BTC-USDT" else "BTC-USDT"
    rows[0][instrument_field] = other
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    mutated = output.getvalue().encode()

    baseline = source.hourly_features(source.parse_archive_csv(data, inst_id))
    accepted = True
    unchanged = False
    try:
        parsed = source.parse_archive_csv(mutated, inst_id)
        unchanged = source.hourly_features(parsed) == baseline
    except ValueError:
        accepted = False

    return {
        "archive_instrument_field": instrument_field,
        "mutated_to": other,
        "current_parser_accepted_mutation": accepted,
        "feature_bytes_unchanged": unchanged,
    }


def missing_hour_attack(rows: list[source.Trade]) -> dict[str, Any]:
    ordered = source.canonicalize(rows)
    hours = sorted({row[5] // HOUR_MS for row in ordered})
    removed_hour = hours[len(hours) // 2]
    mutated = [row for row in ordered if row[5] // HOUR_MS != removed_hour]
    diagnostic = source.strategy_diagnostic(mutated)
    current_pass_logic = all(
        (
            diagnostic["same_timestamp_group_count"] > 0,
            diagnostic["permutation_invariant"],
            diagnostic["future_suffix_invariant"],
            diagnostic["trade_id_time_inversion_count"] == 0,
            diagnostic.get("exact_byte_replay_passed", True),
        )
    )
    return {
        "removed_hour_start_ms": removed_hour * HOUR_MS,
        "removed_trade_count": len(ordered) - len(mutated),
        "remaining_hours": diagnostic["hours"],
        "current_diagnostic_passed": current_pass_logic,
        "feature_sha256_after": diagnostic["feature_sha256"],
    }


def rest_overlap(root: Path, inst_id: str, archive_rows: list[source.Trade]) -> dict[str, Any]:
    archive_by_id = {(row[0], row[1]): row for row in archive_rows}
    pages: dict[str, Any] = {}
    for stem in ("rest-after", "rest-before"):
        rows = source.parse_rest((root / f"{stem}.json").read_bytes(), inst_id)
        overlap = [row for row in rows if (row[0], row[1]) in archive_by_id]
        mismatches = [
            row
            for row in overlap
            if archive_by_id[(row[0], row[1])][2:] != row[2:]
        ]
        pages[stem] = {
            "rows": len(rows),
            "overlap_rows": len(overlap),
            "mismatch_rows": len(mismatches),
            "minimum_trade_id": min(row[1] for row in rows),
            "maximum_trade_id": max(row[1] for row in rows),
            "minimum_ts_ms": min(row[5] for row in rows),
            "maximum_ts_ms": max(row[5] for row in rows),
        }
    return pages


def audit_market(output_dir: Path, market: dict[str, Any]) -> dict[str, Any]:
    inst_id = market["inst_id"]
    root = output_dir / inst_id
    archive_data = (root / "archive.csv").read_bytes()
    archive_rows = source.canonicalize(source.parse_archive_csv(archive_data, inst_id))
    features = source.hourly_features(archive_rows)
    hours = sorted({row[5] // HOUR_MS for row in archive_rows})

    groups = manifest_groups(root)
    archive_url = market["archive"]["url"]
    selected = next((group for group in groups if group.get("url") == archive_url), None)
    declared_start = int(selected["dateTs"]) if selected else None
    observed_min = archive_rows[0][5]
    observed_max = archive_rows[-1][5]
    contiguous_hours = len(hours) == 24 and all(
        right - left == 1 for left, right in zip(hours, hours[1:], strict=False)
    )
    declared_interval = bool(
        selected
        and selected.get("instId", inst_id) == inst_id
        and declared_start is not None
        and declared_start <= observed_min < declared_start + HOUR_MS
        and declared_start + 23 * HOUR_MS <= observed_max < declared_start + DAY_MS
    )

    instrument_attack = archive_instrument_attack(archive_data, inst_id)
    hour_attack = missing_hour_attack(archive_rows)
    pages = rest_overlap(root, inst_id, archive_rows)

    defects: list[str] = []
    if instrument_attack["current_parser_accepted_mutation"]:
        defects.append("archive_instrument_column_ignored")
    if hour_attack["current_diagnostic_passed"]:
        defects.append("missing_complete_hour_not_rejected")
    if any(page["overlap_rows"] < 20 for page in pages.values()):
        defects.append("two_sided_rest_overlap_not_proven")
    if not contiguous_hours:
        defects.append("daily_archive_not_24_contiguous_hours")
    if not declared_interval:
        defects.append("manifest_archive_interval_mismatch")

    return {
        "inst_id": inst_id,
        "archive_rows": len(archive_rows),
        "hour_count": len(hours),
        "first_hour_start_ms": hours[0] * HOUR_MS,
        "last_hour_start_ms": hours[-1] * HOUR_MS,
        "declared_archive_start_ms": declared_start,
        "archive_day_boundary_utc_hour": (
            declared_start % DAY_MS / HOUR_MS if declared_start is not None else None
        ),
        "declared_interval_pass": declared_interval,
        "contiguous_24h_pass": contiguous_hours,
        "baseline_feature_sha256": sha256(canonical_json(features)),
        "mixed_instrument_attack": instrument_attack,
        "missing_hour_attack": hour_attack,
        "rest_page_overlap": pages,
        "defects": defects,
        "status": "blocked" if defects else "passed",
    }


def run(output_dir: Path) -> dict[str, Any]:
    source_result_path = output_dir / "result.json"
    source_result = json.loads(source_result_path.read_text())
    markets = [audit_market(output_dir, market) for market in source_result["markets"]]
    defects = sorted({defect for market in markets for defect in market["defects"]})
    verdict = (
        "trade_flow_source_schema_checkpoint_blocked_by_adversarial_stress"
        if defects
        else "trade_flow_source_schema_checkpoint_survived_adversarial_stress"
    )
    result = {
        "schema_version": "trade-flow-checkpoint-adversarial-stress-v1",
        "architecture_family_id": source_result["architecture_family_id"],
        "candidate_count": source_result["candidate_count"],
        "canonical_fee_bps_one_way": source_result["canonical_fee_bps_one_way"],
        "performance_inspected": False,
        "oos_consumed": False,
        "attacks": [
            "archive mixed-instrument mutation",
            "complete-hour deletion",
            "two-sided REST overlap decomposition",
            "manifest/file boundary reconciliation",
        ],
        "markets": markets,
        "defects": defects,
        "verdict": verdict,
        "strategy_consequence": (
            "V1/V2 performance remains prohibited until the source checkpoint is repaired."
            if defects
            else "Checkpoint may proceed to substantive review."
        ),
    }
    stress_bytes = canonical_json(result)
    stress_path = output_dir / "stress-result.json"
    stress_path.write_bytes(stress_bytes)
    (output_dir / "stress-result.sha256").write_text(sha256(stress_bytes) + "\n")

    source_result["adversarial_stress"] = {
        "schema_version": result["schema_version"],
        "verdict": verdict,
        "defects": defects,
        "sha256": sha256(stress_bytes),
    }
    if defects:
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
