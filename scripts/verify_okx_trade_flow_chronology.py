from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

import acquire_okx_historical_trades as source

MARKETS = ("BTC-USDT", "ETH-USDT")


def strict_descending(values: list[int]) -> bool:
    return all(left > right for left, right in zip(values, values[1:], strict=False))


def nonincreasing(values: list[int]) -> bool:
    return all(left >= right for left, right in zip(values, values[1:], strict=False))


def ordered_hourly_impact(
    rows: list[source.Trade], *, descending_ties: bool
) -> list[dict[str, Any]]:
    unique: dict[tuple[str, int], source.Trade] = {}
    for row in rows:
        key = row[0], row[1]
        if key in unique and unique[key][2:] != row[2:]:
            raise ValueError("conflicting duplicate trade identity")
        unique[key] = row
    tie_sign = -1 if descending_ties else 1
    ordered = sorted(unique.values(), key=lambda row: (row[5], tie_sign * row[1]))
    grouped: dict[int, list[source.Trade]] = defaultdict(list)
    for row in ordered:
        grouped[row[5] // source.HOUR_MS].append(row)

    features: list[dict[str, Any]] = []
    for hour in sorted(grouped):
        hour_rows = grouped[hour]
        first_price = hour_rows[0][3]
        last_price = hour_rows[-1][3]
        features.append(
            {
                "hour_start_ms": hour * source.HOUR_MS,
                "first_trade_id": str(hour_rows[0][1]),
                "last_trade_id": str(hour_rows[-1][1]),
                "impact_return": format(
                    math.log(float(last_price / first_price)), ".18g"
                ),
            }
        )
    return features


def validate_page_sequence(
    archive_rows: list[source.Trade], rest_rows: list[source.Trade]
) -> dict[str, Any]:
    if len(rest_rows) != source.REST_PAGE_SIZE:
        raise ValueError("REST page is not exactly 100 rows")

    rest_ids = [row[1] for row in rest_rows]
    rest_timestamps = [row[5] for row in rest_rows]
    if not strict_descending(rest_ids):
        raise ValueError("REST response is not strict newest-first trade-ID order")
    if not nonincreasing(rest_timestamps):
        raise ValueError("REST response timestamp order is not newest-first")

    canonical_archive = source.canonicalize(archive_rows)
    archive_index = {
        (row[0], row[1]): index for index, row in enumerate(canonical_archive)
    }
    chronological = list(reversed(rest_rows))
    try:
        indices = [archive_index[(row[0], row[1])] for row in chronological]
    except KeyError as exc:
        raise ValueError("REST sequence contains an identity absent from archive") from exc
    if any(
        right - left != 1 for left, right in zip(indices, indices[1:], strict=False)
    ):
        raise ValueError("REST page does not map to one contiguous archive sequence")
    archive_slice = canonical_archive[indices[0] : indices[-1] + 1]
    if chronological != archive_slice:
        raise ValueError("reversed REST sequence does not equal archive chronology")

    equal_ms_groups: dict[int, list[int]] = defaultdict(list)
    for row in rest_rows:
        equal_ms_groups[row[5]].append(row[1])
    collided = [ids for ids in equal_ms_groups.values() if len(ids) > 1]
    if not collided:
        raise ValueError("REST page contains no equal-millisecond sequence evidence")
    if not all(strict_descending(ids) for ids in collided):
        raise ValueError("equal-millisecond REST rows do not follow descending trade IDs")

    return {
        "rows": len(rest_rows),
        "response_trade_ids_strictly_descending": True,
        "response_timestamps_nonincreasing": True,
        "reversed_response_matches_contiguous_archive_sequence": True,
        "archive_start_index": indices[0],
        "archive_end_index": indices[-1],
        "equal_millisecond_groups": len(collided),
        "maximum_equal_millisecond_group_size": max(len(ids) for ids in collided),
    }


def legacy_set_only_accepts(
    archive_rows: list[source.Trade],
    original_rows: list[source.Trade],
    mutated_rows: list[source.Trade],
) -> bool:
    archive_by_id = {(row[0], row[1]): row for row in archive_rows}
    if {(row[0], row[1]) for row in original_rows} != {
        (row[0], row[1]) for row in mutated_rows
    }:
        return False
    return all(
        (row[0], row[1]) in archive_by_id
        and archive_by_id[(row[0], row[1])][2:] == row[2:]
        for row in mutated_rows
    )


def equal_ms_order_attack(
    archive_rows: list[source.Trade], rest_rows: list[source.Trade]
) -> dict[str, bool]:
    groups: dict[int, list[int]] = defaultdict(list)
    for index, row in enumerate(rest_rows):
        groups[row[5]].append(index)
    collision = next((indices for indices in groups.values() if len(indices) > 1), None)
    if collision is None:
        raise ValueError("no equal-millisecond group available for mutation")

    mutated = list(rest_rows)
    left, right = collision[0], collision[1]
    mutated[left], mutated[right] = mutated[right], mutated[left]
    legacy_accepts = legacy_set_only_accepts(archive_rows, rest_rows, mutated)
    strengthened_rejects = False
    try:
        validate_page_sequence(archive_rows, mutated)
    except ValueError:
        strengthened_rejects = True
    return {
        "legacy_set_only_gate_false_pass_reproduced": legacy_accepts,
        "sequence_gate_rejected_equal_ms_mutation": strengthened_rejects,
    }


def tie_break_impact(rows: list[source.Trade]) -> dict[str, Any]:
    ascending = ordered_hourly_impact(rows, descending_ties=False)
    descending = ordered_hourly_impact(rows, descending_ties=True)
    deltas: list[float] = []
    for canonical, alternative in zip(ascending, descending, strict=True):
        canonical_impact = float(canonical["impact_return"])
        alternative_impact = float(alternative["impact_return"])
        if canonical_impact != alternative_impact:
            deltas.append(alternative_impact - canonical_impact)
    if not deltas:
        raise ValueError("tie reversal did not alter any V2 hourly impact_return")
    return {
        "complete_hours": len(ascending),
        "impact_return_changed_hours": len(deltas),
        "mean_absolute_impact_delta_bps": (
            sum(abs(value) for value in deltas) / len(deltas) * 10_000
        ),
        "maximum_absolute_impact_delta_bps": max(abs(value) for value in deltas)
        * 10_000,
        "signed_mean_impact_delta_bps": sum(deltas) / len(deltas) * 10_000,
        "ascending_feature_sha256": source.sha256(source.canonical_json(ascending)),
        "descending_feature_sha256": source.sha256(source.canonical_json(descending)),
    }


def market_result(output_dir: Path, inst_id: str) -> dict[str, Any]:
    market_root = output_dir / inst_id
    archive_rows = source.parse_archive_csv(
        (market_root / "archive.csv").read_bytes(), inst_id
    )
    canonical_archive = source.canonicalize(archive_rows)
    raw_ids = [row[1] for row in archive_rows]
    raw_timestamps = [row[5] for row in archive_rows]
    if not all(left < right for left, right in zip(raw_ids, raw_ids[1:], strict=False)):
        raise ValueError("archive file order is not strict ascending trade-ID order")
    if not all(
        left <= right
        for left, right in zip(raw_timestamps, raw_timestamps[1:], strict=False)
    ):
        raise ValueError("archive file order is not nondecreasing event time")
    if archive_rows != canonical_archive:
        raise ValueError("archive file order does not equal canonical chronology")

    older = source.parse_rest((market_root / "rest-older.json").read_bytes(), inst_id)
    newer = source.parse_rest(
        (market_root / "rest-newer-bounded.json").read_bytes(), inst_id
    )
    older_result = validate_page_sequence(archive_rows, older)
    newer_result = validate_page_sequence(archive_rows, newer)
    if older_result["archive_end_index"] >= newer_result["archive_start_index"]:
        raise ValueError("older/newer REST pages overlap or reverse in archive chronology")

    older_attack = equal_ms_order_attack(archive_rows, older)
    newer_attack = equal_ms_order_attack(archive_rows, newer)
    legacy_false_pass = all(
        attack["legacy_set_only_gate_false_pass_reproduced"]
        for attack in (older_attack, newer_attack)
    )
    strengthened_rejection = all(
        attack["sequence_gate_rejected_equal_ms_mutation"]
        for attack in (older_attack, newer_attack)
    )
    if not legacy_false_pass:
        raise ValueError("legacy set-only false pass was not reproduced")
    if not strengthened_rejection:
        raise ValueError("equal-millisecond sequence mutation was not rejected")

    return {
        "inst_id": inst_id,
        "archive_rows": len(archive_rows),
        "archive_file_trade_ids_strictly_ascending": True,
        "archive_file_timestamps_nondecreasing": True,
        "archive_file_equals_canonical_chronology": True,
        "older_page": older_result,
        "newer_page": newer_result,
        "numeric_id_tie_break_matches_public_rest_sequence": True,
        "legacy_set_only_false_pass_reproduced": legacy_false_pass,
        "equal_ms_order_mutation_rejected": strengthened_rejection,
        "v2_tie_break_impact": tie_break_impact(archive_rows),
        "status": "passed",
    }


def run(output_dir: Path) -> dict[str, Any]:
    checkpoint = json.loads((output_dir / "result.json").read_text())
    if checkpoint.get("performance_inspected") is not False:
        raise ValueError("chronology verification must remain pre-performance")
    if checkpoint.get("oos_consumed") is not False:
        raise ValueError("chronology verification must not consume OOS")

    result = {
        "schema_version": "trade-flow-equal-ms-chronology-stress-v1",
        "architecture_family_id": "okx-spot-causal-trade-flow-resilience-v2",
        "candidate_count": 2,
        "canonical_fee_bps_one_way": 5.0,
        "performance_inspected": False,
        "oos_consumed": False,
        "attack": (
            "set parity can falsely pass a shuffled equal-millisecond REST sequence; "
            "the alternative tie break changes V2 hourly impact_return"
        ),
        "markets": [market_result(output_dir, inst_id) for inst_id in MARKETS],
        "verdict": "numeric_trade_id_chronology_proven_and_strategy_material",
    }
    data = source.canonical_json(result)
    (output_dir / "chronology-stress.json").write_bytes(data)
    (output_dir / "chronology-stress.sha256").write_text(source.sha256(data) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir", default="reports/okx/trade-flow-schema-checkpoint"
    )
    args = parser.parse_args()
    print(json.dumps(run(Path(args.output_dir)), indent=2))


if __name__ == "__main__":
    main()
