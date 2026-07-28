from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

HOUR_MS = 3_600_000
MARKETS = ("BTC-USDT", "ETH-USDT")

Trade = tuple[str, int, str, Decimal, Decimal, int]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def parse_archive(path: Path, inst_id: str) -> list[Trade]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("archive CSV has no header")
        required = {
            "instrument_name",
            "trade_id",
            "side",
            "price",
            "size",
            "created_time",
        }
        if not required.issubset(reader.fieldnames):
            raise ValueError("archive CSV schema mismatch")
        rows: list[Trade] = []
        for row in reader:
            observed = str(row["instrument_name"]).strip()
            if observed != inst_id:
                raise ValueError(f"archive instrument mismatch: {observed}")
            rows.append(
                (
                    observed,
                    int(row["trade_id"]),
                    str(row["side"]).lower(),
                    Decimal(row["price"]),
                    Decimal(row["size"]),
                    int(row["created_time"]),
                )
            )
    if not rows:
        raise ValueError("empty archive")
    return rows


def parse_rest(path: Path, inst_id: str) -> list[Trade]:
    payload = json.loads(path.read_text())
    if str(payload.get("code")) != "0" or not isinstance(payload.get("data"), list):
        raise ValueError("invalid REST response")
    rows: list[Trade] = []
    for row in payload["data"]:
        if row.get("instId") != inst_id:
            raise ValueError("REST instrument mismatch")
        rows.append(
            (
                inst_id,
                int(row["tradeId"]),
                str(row["side"]).lower(),
                Decimal(row["px"]),
                Decimal(row["sz"]),
                int(row["ts"]),
            )
        )
    return rows


def canonicalize(rows: list[Trade], *, descending_ties: bool = False) -> list[Trade]:
    unique: dict[tuple[str, int], Trade] = {}
    for row in rows:
        key = row[0], row[1]
        if key in unique and unique[key][2:] != row[2:]:
            raise ValueError("conflicting duplicate identity")
        unique[key] = row
    if descending_ties:
        return sorted(unique.values(), key=lambda row: (row[5], -row[1]))
    return sorted(unique.values(), key=lambda row: (row[5], row[1]))


def hourly_features(rows: list[Trade], *, descending_ties: bool = False) -> list[dict[str, Any]]:
    grouped: dict[int, list[Trade]] = defaultdict(list)
    for row in canonicalize(rows, descending_ties=descending_ties):
        grouped[row[5] // HOUR_MS].append(row)
    features: list[dict[str, Any]] = []
    for hour in sorted(grouped):
        hour_rows = grouped[hour]
        total = sum((row[3] * row[4] for row in hour_rows), Decimal())
        signed = sum(
            (
                row[3]
                * row[4]
                * (Decimal(1) if row[2] == "buy" else Decimal(-1))
                for row in hour_rows
            ),
            Decimal(),
        )
        features.append(
            {
                "hour_start_ms": hour * HOUR_MS,
                "flow": format(signed / total, ".18g"),
                "first_trade_id": str(hour_rows[0][1]),
                "first_price": format(hour_rows[0][3], "f"),
                "last_trade_id": str(hour_rows[-1][1]),
                "last_price": format(hour_rows[-1][3], "f"),
            }
        )
    return features


def strict_descending(values: list[int]) -> bool:
    return all(left > right for left, right in zip(values, values[1:], strict=False))


def nonincreasing(values: list[int]) -> bool:
    return all(left >= right for left, right in zip(values, values[1:], strict=False))


def validate_page_sequence(archive_rows: list[Trade], rest_rows: list[Trade]) -> dict[str, Any]:
    if len(rest_rows) != 100:
        raise ValueError("REST page is not exactly 100 rows")
    rest_ids = [row[1] for row in rest_rows]
    rest_ts = [row[5] for row in rest_rows]
    if not strict_descending(rest_ids):
        raise ValueError("REST response is not strict newest-first trade-ID order")
    if not nonincreasing(rest_ts):
        raise ValueError("REST response timestamp order is not newest-first")

    archive_index = {(row[0], row[1]): index for index, row in enumerate(archive_rows)}
    chronological = list(reversed(rest_rows))
    indices = [archive_index[(row[0], row[1])] for row in chronological]
    if any(right - left != 1 for left, right in zip(indices, indices[1:], strict=False)):
        raise ValueError("REST page does not map to one contiguous archive sequence")
    archive_slice = archive_rows[indices[0] : indices[-1] + 1]
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


def legacy_set_only_validator_accepts_mutation(
    archive_rows: list[Trade], original_rows: list[Trade], mutated_rows: list[Trade]
) -> bool:
    archive_by_id = {(row[0], row[1]): row for row in archive_rows}
    same_identities = {(row[0], row[1]) for row in original_rows} == {
        (row[0], row[1]) for row in mutated_rows
    }
    return same_identities and all(
        (row[0], row[1]) in archive_by_id
        and archive_by_id[(row[0], row[1])][2:] == row[2:]
        for row in mutated_rows
    )


def order_mutation_result(archive_rows: list[Trade], rest_rows: list[Trade]) -> dict[str, bool]:
    groups: dict[int, list[int]] = defaultdict(list)
    for index, row in enumerate(rest_rows):
        groups[row[5]].append(index)
    collision = next((indices for indices in groups.values() if len(indices) > 1), None)
    if collision is None:
        raise ValueError("no equal-millisecond group available for mutation")
    mutated = list(rest_rows)
    left, right = collision[0], collision[1]
    mutated[left], mutated[right] = mutated[right], mutated[left]
    legacy_accepts = legacy_set_only_validator_accepts_mutation(archive_rows, rest_rows, mutated)
    strengthened_rejects = False
    try:
        validate_page_sequence(archive_rows, mutated)
    except ValueError:
        strengthened_rejects = True
    return {
        "legacy_set_only_gate_false_pass_reproduced": legacy_accepts,
        "strengthened_sequence_gate_rejected_mutation": strengthened_rejects,
    }


def market_result(root: Path, inst_id: str) -> dict[str, Any]:
    market_root = root / inst_id
    archive_rows = parse_archive(market_root / "archive.csv", inst_id)
    archive_ids = [row[1] for row in archive_rows]
    archive_ts = [row[5] for row in archive_rows]
    if not all(left < right for left, right in zip(archive_ids, archive_ids[1:], strict=False)):
        raise ValueError("archive file order is not strict ascending trade-ID order")
    if not all(left <= right for left, right in zip(archive_ts, archive_ts[1:], strict=False)):
        raise ValueError("archive file order is not nondecreasing event time")

    older = parse_rest(market_root / "rest-older.json", inst_id)
    newer = parse_rest(market_root / "rest-newer-bounded.json", inst_id)
    older_result = validate_page_sequence(archive_rows, older)
    newer_result = validate_page_sequence(archive_rows, newer)
    if older_result["archive_end_index"] >= newer_result["archive_start_index"]:
        raise ValueError("older/newer REST pages overlap or reverse in archive chronology")

    ascending_features = hourly_features(archive_rows)
    descending_tie_features = hourly_features(archive_rows, descending_ties=True)
    changed_hours = sum(
        left != right
        for left, right in zip(ascending_features, descending_tie_features, strict=True)
    )
    if changed_hours == 0:
        raise ValueError("tie-break stress did not affect any hourly first/last-price feature")

    older_mutation = order_mutation_result(archive_rows, older)
    newer_mutation = order_mutation_result(archive_rows, newer)
    legacy_false_pass = (
        older_mutation["legacy_set_only_gate_false_pass_reproduced"]
        and newer_mutation["legacy_set_only_gate_false_pass_reproduced"]
    )
    strengthened_rejection = (
        older_mutation["strengthened_sequence_gate_rejected_mutation"]
        and newer_mutation["strengthened_sequence_gate_rejected_mutation"]
    )
    if not legacy_false_pass:
        raise ValueError("legacy set-only false pass was not reproduced")
    if not strengthened_rejection:
        raise ValueError("within-millisecond REST order mutation was not rejected")

    return {
        "inst_id": inst_id,
        "archive_rows": len(archive_rows),
        "archive_file_trade_ids_strictly_ascending": True,
        "archive_file_timestamps_nondecreasing": True,
        "older_page": older_result,
        "newer_page": newer_result,
        "numeric_id_tie_break_matches_public_rest_sequence": True,
        "alternative_descending_tie_break_changed_hours": changed_hours,
        "hour_count": len(ascending_features),
        "canonical_feature_sha256": sha256(canonical_json(ascending_features)),
        "descending_tie_feature_sha256": sha256(canonical_json(descending_tie_features)),
        "legacy_set_only_false_pass_reproduced": legacy_false_pass,
        "equal_ms_order_mutation_rejected": strengthened_rejection,
        "status": "passed",
    }


def run(output_dir: Path) -> dict[str, Any]:
    source = json.loads((output_dir / "result.json").read_text())
    if source.get("performance_inspected") is not False or source.get("oos_consumed") is not False:
        raise ValueError("chronology stress must remain pre-performance")
    markets = [market_result(output_dir, market) for market in MARKETS]
    result = {
        "schema_version": "trade-flow-equal-ms-chronology-stress-v1",
        "architecture_family_id": "okx-spot-causal-trade-flow-resilience-v2",
        "candidate_count": 2,
        "canonical_fee_bps_one_way": 5.0,
        "performance_inspected": False,
        "oos_consumed": False,
        "attack": "set parity can falsely pass a shuffled equal-millisecond REST sequence",
        "markets": markets,
        "verdict": "trade_flow_numeric_id_chronology_proven_by_rest_sequence",
    }
    data = canonical_json(result)
    (output_dir / "chronology-stress.json").write_bytes(data)
    (output_dir / "chronology-stress.sha256").write_text(sha256(data) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="reports/okx/trade-flow-schema-checkpoint")
    args = parser.parse_args()
    print(json.dumps(run(Path(args.output_dir)), indent=2))


if __name__ == "__main__":
    main()
