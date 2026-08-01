from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import run_okx_l2_bid_replenishment_diagnostic as core


def _process_archive_once(
    manifest_path: Path,
    market: str,
    anchor: str,
    output_dir: Path,
) -> dict[str, Any]:
    """Replay one official provider-ordered OKX L2 daily archive once.

    The archive emits a new row only when the order book changes. Its `ts`
    field is therefore validated as a unique, strictly increasing provider
    generation timestamp, not as a gap-free clock lattice.
    """

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("family_id") != core.FAMILY_ID
        or manifest.get("byte_gate_passed") is not True
    ):
        raise core.SourceFeasibilityError("invalid or unapproved source manifest")

    matches = [
        item
        for item in manifest.get("source_objects", [])
        if item.get("market") == market and item.get("anchor_date_utc") == anchor
    ]
    if len(matches) != 1:
        raise core.SourceFeasibilityError(
            "source manifest does not identify exactly one archive"
        )
    source = matches[0]
    url = source["url"]
    day_start_ms, day_end_ms = core.utc_day_bounds(anchor)
    boundary_times = [
        day_start_ms + index * core.BOUNDARY_STEP_MS for index in range(289)
    ]
    boundaries: list[dict[str, Any] | None] = []
    boundary_index = 0
    bids: dict[float, float] = {}
    asks: dict[float, float] = {}
    snapshot_seen = False
    first_ts: int | None = None
    previous_ts: int | None = None
    last_ts: int | None = None
    maximum_message_gap_ms = 0
    row_count = 0
    snapshot_count = 0
    update_count = 0
    member_count = 0
    member_name: str | None = None
    member_bytes = 0
    member_hasher = core.hashlib.sha256()
    started = time.monotonic()

    with core.request(
        url,
        accept="application/gzip,application/octet-stream,*/*",
        timeout=120,
    ) as response:
        final_url = response.geturl()
        if not core.trusted_okx_url(final_url):
            raise core.SourceFeasibilityError(
                f"untrusted archive final URL: {final_url}"
            )
        reader = core.HashingReader(response, byte_limit=core.MAX_OBJECT_BYTES)
        with core.tarfile.open(fileobj=reader, mode="r|gz") as archive:
            for member in archive:
                if not member.isfile():
                    continue
                member_count += 1
                if member_count > 1:
                    raise core.SourceFeasibilityError(
                        "archive contains more than one regular file"
                    )
                member_name = member.name
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise core.SourceFeasibilityError(
                        "archive member cannot be read"
                    )
                for raw_line in extracted:
                    member_bytes += len(raw_line)
                    member_hasher.update(raw_line)
                    if len(raw_line) > 1_000_000:
                        raise core.SourceFeasibilityError(
                            "order-book message exceeds 1 MB"
                        )
                    try:
                        message = json.loads(
                            raw_line.decode("utf-8"),
                            object_pairs_hook=core.reject_duplicate_keys,
                        )
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        raise core.SourceFeasibilityError(
                            "invalid order-book JSON line"
                        ) from exc
                    if not isinstance(message, dict) or set(message) != {
                        "instId",
                        "action",
                        "ts",
                        "asks",
                        "bids",
                    }:
                        raise core.SourceFeasibilityError(
                            "order-book message schema drift"
                        )
                    if message["instId"] != market:
                        raise core.SourceFeasibilityError(
                            "archive contains wrong instrument"
                        )
                    ts_text = str(message["ts"])
                    if not ts_text.isascii() or not ts_text.isdecimal():
                        raise core.SourceFeasibilityError(
                            "invalid order-book timestamp"
                        )
                    ts = int(ts_text)
                    if not day_start_ms <= ts < day_end_ms:
                        raise core.SourceFeasibilityError(
                            "order-book timestamp outside anchor day"
                        )
                    if previous_ts is not None:
                        delta = ts - previous_ts
                        if delta <= 0:
                            raise core.SourceFeasibilityError(
                                "provider timestamp ordering violation: "
                                f"{previous_ts} -> {ts}"
                            )
                        maximum_message_gap_ms = max(
                            maximum_message_gap_ms,
                            delta,
                        )
                    if first_ts is None:
                        first_ts = ts
                    previous_ts = ts
                    last_ts = ts

                    while (
                        boundary_index < len(boundary_times)
                        and boundary_times[boundary_index] < ts
                    ):
                        boundaries.append(
                            core.boundary_state(bids, asks)
                            if snapshot_seen
                            else None
                        )
                        boundary_index += 1

                    action = message["action"]
                    if action == "snapshot":
                        bids.clear()
                        asks.clear()
                        snapshot_count += 1
                        snapshot_seen = True
                    elif action == "update":
                        if not snapshot_seen:
                            raise core.SourceFeasibilityError(
                                "incremental update precedes initial snapshot"
                            )
                        update_count += 1
                    else:
                        raise core.SourceFeasibilityError(
                            f"unsupported order-book action: {action!r}"
                        )
                    core.apply_levels(asks, message["asks"], side="ask")
                    core.apply_levels(bids, message["bids"], side="bid")

                    while (
                        boundary_index < len(boundary_times)
                        and boundary_times[boundary_index] == ts
                    ):
                        boundaries.append(core.boundary_state(bids, asks))
                        boundary_index += 1
                    row_count += 1

        while reader.read(1 << 20):
            pass
        compressed_bytes = reader.bytes_read
        compressed_sha256 = reader.digest

    if member_count != 1 or member_name is None:
        raise core.SourceFeasibilityError(
            "archive contains no regular data member"
        )
    if first_ts is None or last_ts is None:
        raise core.SourceFeasibilityError(
            "archive contains no order-book messages"
        )
    while boundary_index < len(boundary_times):
        boundaries.append(
            core.boundary_state(bids, asks) if snapshot_seen else None
        )
        boundary_index += 1
    if first_ts - day_start_ms >= core.BOUNDARY_STEP_MS:
        raise core.SourceFeasibilityError(
            "daily archive lacks a causal opening snapshot before first boundary"
        )
    if snapshot_count < 1 or update_count < 1:
        raise core.SourceFeasibilityError(
            "archive lacks snapshot/update semantics"
        )

    states = core.hourly_states(
        boundaries,
        market=market,
        anchor=anchor,
        day_start_ms=day_start_ms,
    )
    valid_states = sum(bool(item["valid"]) for item in states)
    invalid_after_first = [item for item in states[1:] if not item["valid"]]
    if invalid_after_first:
        raise core.SourceFeasibilityError(
            "missing five-minute boundary after the day-opening causal edge"
        )

    result = {
        "family_id": core.FAMILY_ID,
        "market": market,
        "anchor_date_utc": anchor,
        "source_url": url,
        "final_url": final_url,
        "declared_size_mb": source["size_mb_decimal"],
        "compressed_bytes": compressed_bytes,
        "compressed_sha256": compressed_sha256,
        "member_name": member_name,
        "member_bytes": member_bytes,
        "member_sha256": member_hasher.hexdigest(),
        "message_count": row_count,
        "snapshot_count": snapshot_count,
        "update_count": update_count,
        "first_ts": first_ts,
        "last_ts": last_ts,
        "maximum_message_gap_ms": maximum_message_gap_ms,
        "sequence_identity": (
            "unique strictly increasing provider generation timestamps; "
            "gaps represent no-change suppression"
        ),
        "sequence_continuity_passed": True,
        "source_day_complete": True,
        "boundary_count": len(boundaries),
        "valid_hour_count": valid_states,
        "invalid_hour_count": 24 - valid_states,
        "first_hour_missing_reason": states[0]["invalid_reason"],
        "processing_seconds": time.monotonic() - started,
        "hourly_states": states,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{market}-{anchor}.json"
    output_path.write_bytes(core.canonical_json(result))
    return result


def process_archive(
    manifest_path: Path,
    market: str,
    anchor: str,
    output_dir: Path,
) -> dict[str, Any]:
    """Replay an archive, restarting cleanly after transient stream truncation."""

    transient_errors = (
        core.tarfile.ReadError,
        EOFError,
        OSError,
        TimeoutError,
    )
    last_error: BaseException | None = None
    for attempt in range(3):
        try:
            result = _process_archive_once(
                manifest_path,
                market,
                anchor,
                output_dir,
            )
            result["archive_replay_attempts"] = attempt + 1
            output_path = output_dir / f"{market}-{anchor}.json"
            output_path.write_bytes(core.canonical_json(result))
            return result
        except transient_errors as exc:
            last_error = exc
            if attempt == 2:
                raise
            time.sleep(2**attempt)
    raise RuntimeError("unreachable archive replay retry state") from last_error


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest-path", type=Path, required=True)
    parser.add_argument("--market", choices=core.MARKETS, required=True)
    parser.add_argument("--anchor", choices=core.ANCHOR_DATES, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = process_archive(
        args.manifest_path,
        args.market,
        args.anchor,
        args.output_dir,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
