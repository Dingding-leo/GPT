from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import acquire_okx_historical_trades as source

MARKETS = ("BTC-USDT", "ETH-USDT")


def strict_descending(values: list[int]) -> bool:
    return all(left > right for left, right in zip(values, values[1:], strict=False))


def nonincreasing(values: list[int]) -> bool:
    return all(left >= right for left, right in zip(values, values[1:], strict=False))


def archive_sequence(
    archive_rows: list[source.Trade],
    rest_rows: list[source.Trade],
) -> tuple[int, int]:
    if len(rest_rows) != source.REST_PAGE_SIZE:
        raise ValueError("REST page is not exactly 100 rows")

    rest_ids = [row[1] for row in rest_rows]
    rest_timestamps = [row[5] for row in rest_rows]
    if not strict_descending(rest_ids):
        raise ValueError("REST page is not strict newest-first trade-ID order")
    if not nonincreasing(rest_timestamps):
        raise ValueError("REST page timestamps are not newest-first")

    archive_index = {(row[0], row[1]): index for index, row in enumerate(archive_rows)}
    chronological = list(reversed(rest_rows))
    indices = [archive_index[(row[0], row[1])] for row in chronological]
    if any(right - left != 1 for left, right in zip(indices, indices[1:], strict=False)):
        raise ValueError("REST page is not one contiguous archive sequence")
    if chronological != archive_rows[indices[0] : indices[-1] + 1]:
        raise ValueError("REST chronology does not equal archive chronology")
    return indices[0], indices[-1]


def equal_ms_groups(rows: list[source.Trade]) -> list[list[source.Trade]]:
    groups: dict[int, list[source.Trade]] = defaultdict(list)
    for row in rows:
        groups[row[5]].append(row)
    return [group for group in groups.values() if len(group) > 1]


def legacy_set_gate_accepts(
    archive_rows: list[source.Trade],
    original_rows: list[source.Trade],
    mutated_rows: list[source.Trade],
) -> bool:
    if {(row[0], row[1]) for row in original_rows} != {
        (row[0], row[1]) for row in mutated_rows
    }:
        return False
    archive_by_id = {(row[0], row[1]): row for row in archive_rows}
    return all(archive_by_id.get((row[0], row[1])) == row for row in mutated_rows)


def equal_ms_order_attack(
    archive_rows: list[source.Trade],
    rest_rows: list[source.Trade],
) -> dict[str, Any]:
    groups: dict[int, list[int]] = defaultdict(list)
    for index, row in enumerate(rest_rows):
        groups[row[5]].append(index)
    collision = next((indices for indices in groups.values() if len(indices) > 1), None)
    if collision is None:
        raise ValueError("REST page has no equal-millisecond group")

    mutated = list(rest_rows)
    left, right = collision[0], collision[1]
    mutated[left], mutated[right] = mutated[right], mutated[left]
    legacy_accepts = legacy_set_gate_accepts(archive_rows, rest_rows, mutated)

    strengthened_rejects = False
    try:
        archive_sequence(archive_rows, mutated)
    except ValueError:
        strengthened_rejects = True

    return {
        "legacy_set_only_gate_false_pass_reproduced": legacy_accepts,
        "sequence_gate_rejected_mutation": strengthened_rejects,
    }


def tie_break_impact(rows: list[source.Trade]) -> dict[str, Any]:
    ascending = source.hourly_features(rows)
    descending_rows = sorted(source.canonicalize(rows), key=lambda row: (row[5], -row[1]))
    descending = source.hourly_features(descending_rows, reorder=False)

    deltas = [
        float(alternative["impact_return"]) - float(canonical["impact_return"])
        for canonical, alternative in zip(ascending, descending, strict=True)
        if alternative["impact_return"] != canonical["impact_return"]
    ]
    if not deltas:
        raise ValueError("tie-break reversal did not change V2 impact_return")
    return {
        "complete_hours": len(ascending),
        "impact_return_changed_hours": len(deltas),
        "mean_absolute_impact_delta_bps": (
            sum(abs(value) for value in deltas) / len(deltas) * 10_000
        ),
        "maximum_absolute_impact_delta_bps": (
            max(abs(value) for value in deltas) * 10_000
        ),
        "signed_mean_impact_delta_bps": sum(deltas) / len(deltas) * 10_000,
    }


def page_result(archive_rows: list[source.Trade], rest_rows: list[source.Trade]) -> dict[str, Any]:
    start, end = archive_sequence(archive_rows, rest_rows)
    collisions = equal_ms_groups(rest_rows)
    if not collisions:
        raise ValueError("REST page has no equal-millisecond sequence evidence")
    if not all(strict_descending([row[1] for row in group]) for group in collisions):
        raise ValueError("equal-millisecond REST rows are not newest-first by trade ID")
    attack = equal_ms_order_attack(archive_rows, rest_rows)
    if not all(attack.values()):
        raise ValueError("equal-millisecond order attack did not fail closed")
    return {
        "rows": len(rest_rows),
        "response_trade_ids_strictly_descending": True,
        "response_timestamps_nonincreasing": True,
        "reversed_response_matches_contiguous_archive_sequence": True,
        "archive_start_index": start,
        "archive_end_index": end,
        "equal_millisecond_groups": len(collisions),
        "maximum_equal_millisecond_group_size": max(len(group) for group in collisions),
        "order_mutation_attack": attack,
    }


def market_result(output_dir: Path, inst_id: str) -> dict[str, Any]:
    root = output_dir / inst_id
    archive_rows = source.parse_archive_csv((root / "archive.csv").read_bytes(), inst_id)
    archive_ids = [row[1] for row in archive_rows]
    archive_timestamps = [row[5] for row in archive_rows]
    if not all(left < right for left, right in zip(archive_ids, archive_ids[1:], strict=False)):
        raise ValueError("archive raw trade IDs are not strict ascending")
    if not nonincreasing(list(reversed(archive_timestamps))):
        raise ValueError("archive raw timestamps are not nondecreasing")

    older = source.parse_rest((root / "rest-older.json").read_bytes(), inst_id)
    newer = source.parse_rest((root / "rest-newer-bounded.json").read_bytes(), inst_id)
    older_result = page_result(archive_rows, older)
    newer_result = page_result(archive_rows, newer)
    if older_result["archive_end_index"] >= newer_result["archive_start_index"]:
        raise ValueError("two REST pages overlap or reverse in archive chronology")

    return {
        "inst_id": inst_id,
        "archive_rows": len(archive_rows),
        "archive_file_trade_ids_strictly_ascending": True,
        "archive_file_timestamps_nondecreasing": True,
        "older_page": older_result,
        "newer_page": newer_result,
        "tie_break_impact": tie_break_impact(archive_rows),
        "status": "passed",
    }


def run(output_dir: Path) -> dict[str, Any]:
    source_result = json.loads((output_dir / "result.json").read_text())
    if source_result["performance_inspected"] is not False:
        raise ValueError("chronology stress must remain pre-performance")
    if source_result["oos_consumed"] is not False:
        raise ValueError("chronology stress must not consume OOS")

    result = {
        "schema_version": "trade-flow-equal-ms-chronology-stress-v1",
        "architecture_family_id": source_result["architecture_family_id"],
        "candidate_count": source_result["candidate_count"],
        "canonical_fee_bps_one_way": source_result["canonical_fee_bps_one_way"],
        "performance_inspected": False,
        "oos_consumed": False,
        "attack": (
            "set parity can falsely accept a shuffled equal-millisecond REST sequence and "
            "thereby alter V2 first/last-price impact_return"
        ),
        "markets": [market_result(output_dir, inst_id) for inst_id in MARKETS],
        "verdict": "trade_flow_numeric_id_chronology_proven_by_public_rest_sequence",
    }
    data = source.canonical_json(result)
    (output_dir / "chronology-stress.json").write_bytes(data)
    (output_dir / "chronology-stress.sha256").write_text(source.sha256(data) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        default="reports/okx/trade-flow-schema-checkpoint",
    )
    args = parser.parse_args()
    print(json.dumps(run(Path(args.output_dir)), indent=2))


if __name__ == "__main__":
    main()
