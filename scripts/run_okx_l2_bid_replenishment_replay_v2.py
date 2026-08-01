from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import tarfile
import time
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import Any, BinaryIO
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


MODULE_PATH = Path(__file__).with_name("run_okx_l2_bid_replenishment_diagnostic.py")
SPEC = importlib.util.spec_from_file_location("okx_l2_bid_replenishment_v1", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load frozen diagnostic implementation")
base = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(base)


class RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        raise base.SourceFeasibilityError(
            f"redirect rejected before destination contact: {req.full_url} -> {newurl}"
        )


def secure_request(url: str, *, accept: str, timeout: float = 90.0) -> BinaryIO:
    if not base.trusted_okx_url(url):
        raise base.SourceFeasibilityError(f"untrusted request URL: {url}")
    request = Request(
        url,
        headers={
            "Accept": accept,
            "User-Agent": "gpt-quant-lab/0.2 (+https://github.com/Dingding-leo/GPT)",
        },
    )
    opener = build_opener(RejectRedirects())
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = opener.open(request, timeout=timeout)  # noqa: S310
            final_url = response.geturl()
            if final_url != url or not base.trusted_okx_url(final_url):
                response.close()
                raise base.SourceFeasibilityError(f"unexpected final URL: {final_url}")
            return response
        except HTTPError as exc:
            last_error = exc
            if exc.code not in base.RETRYABLE_STATUS or attempt == 2:
                raise base.SourceFeasibilityError(f"HTTP {exc.code}: {url}") from exc
        except base.SourceFeasibilityError:
            raise
        except (TimeoutError, URLError) as exc:
            last_error = exc
            if attempt == 2:
                raise base.SourceFeasibilityError(f"request failed: {url}") from exc
        time.sleep(0.5 * 2**attempt)
    raise base.SourceFeasibilityError(f"request failed: {url}") from last_error


base.request = secure_request


def expected_day_start_ms(anchor: str) -> int:
    return int(datetime.strptime(anchor, "%Y-%m-%d").replace(tzinfo=UTC).timestamp() * 1000)


def acquire_metadata(base_url: str, output_dir: Path) -> dict[str, Any]:
    result = base.acquire_metadata(base_url, output_dir)
    manifest_path = output_dir / "source-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    total = 0
    largest = 0
    for record in manifest["source_objects"]:
        anchor = record["anchor_date_utc"]
        market = record["market"]
        if int(record["date_ts"]) != expected_day_start_ms(anchor):
            raise base.SourceFeasibilityError(
                f"archive day identity mismatch for {market} {anchor}: {record['date_ts']}"
            )
        expected_name = f"{market}-L2orderbook-400lv-{anchor}.tar.gz"
        if record["filename"] != expected_name or not record["url"].endswith("/" + expected_name):
            raise base.SourceFeasibilityError(
                f"archive filename identity mismatch for {market} {anchor}"
            )
        size_mb = Decimal(record["size_mb_decimal"])
        size_bytes = int((size_mb * Decimal(1_000_000)).to_integral_value(rounding=ROUND_CEILING))
        record["declared_compressed_bytes"] = size_bytes
        record.pop("declared_compressed_bytes_decimal_mb", None)
        total += size_bytes
        largest = max(largest, size_bytes)
    for response in manifest["metadata_responses"]:
        response.pop("response_base64", None)
    manifest["declared_compressed_bytes"] = total
    manifest["largest_object_bytes"] = largest
    if largest > base.MAX_OBJECT_BYTES:
        raise base.SourceFeasibilityError("declared archive exceeds 1.5 GiB object ceiling")
    if total > base.MAX_CUMULATIVE_BYTES:
        raise base.SourceFeasibilityError("declared cohort exceeds 20 GiB cumulative ceiling")
    manifest["byte_gate_passed"] = True
    manifest["metadata_contract_revision"] = "v2-ceiling-date-identity-no-redirect"
    manifest_bytes = base.canonical_json(manifest)
    manifest_path.write_bytes(manifest_bytes)
    return {"source_manifest_sha256": base.sha256(manifest_bytes), **manifest}


def process_archive(
    manifest_path: Path,
    market: str,
    anchor: str,
    output_dir: Path,
) -> dict[str, Any]:
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest.get("family_id") != base.FAMILY_ID or manifest.get("byte_gate_passed") is not True:
        raise base.SourceFeasibilityError("invalid or unapproved source manifest")
    matches = [
        item
        for item in manifest.get("source_objects", [])
        if item.get("market") == market and item.get("anchor_date_utc") == anchor
    ]
    if len(matches) != 1:
        raise base.SourceFeasibilityError("source manifest does not identify exactly one archive")
    source = matches[0]
    url = source["url"]
    day_start_ms, day_end_ms = base.utc_day_bounds(anchor)
    boundary_times = [day_start_ms + index * base.BOUNDARY_STEP_MS for index in range(289)]
    boundaries: list[dict[str, Any] | None] = []
    boundary_index = 0
    bids: dict[float, float] = {}
    asks: dict[float, float] = {}
    snapshot_seen = False
    first_ts: int | None = None
    previous_ts: int | None = None
    last_ts: int | None = None
    timestamp_residue: int | None = None
    positive_gap_count = 0
    maximum_gap_ms = 0
    row_count = 0
    snapshot_count = 0
    update_count = 0
    member_count = 0
    member_name: str | None = None
    member_bytes = 0
    member_hasher = hashlib.sha256()
    started = time.monotonic()

    with secure_request(url, accept="application/gzip,application/octet-stream,*/*", timeout=120) as response:
        final_url = response.geturl()
        reader = base.HashingReader(response, byte_limit=base.MAX_OBJECT_BYTES)
        with tarfile.open(fileobj=reader, mode="r|gz") as archive:
            for member in archive:
                if not member.isfile():
                    continue
                member_count += 1
                if member_count > 1:
                    raise base.SourceFeasibilityError("archive contains more than one regular file")
                member_name = member.name
                member_path = Path(member_name)
                expected_prefix = source["filename"].removesuffix(".tar.gz")
                if (
                    member_path.name != member_name
                    or not member_name.startswith(expected_prefix)
                    or member_path.suffix.lower() not in {".json", ".jsonl", ".log", ".txt"}
                ):
                    raise base.SourceFeasibilityError(f"unexpected archive member name: {member_name}")
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise base.SourceFeasibilityError("archive member cannot be read")
                for raw_line in extracted:
                    member_bytes += len(raw_line)
                    member_hasher.update(raw_line)
                    if len(raw_line) > 1_000_000:
                        raise base.SourceFeasibilityError("order-book message exceeds 1 MB")
                    try:
                        message = json.loads(
                            raw_line.decode("utf-8"), object_pairs_hook=base.reject_duplicate_keys
                        )
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        raise base.SourceFeasibilityError("invalid order-book JSON line") from exc
                    if not isinstance(message, dict) or set(message) != {
                        "instId",
                        "action",
                        "ts",
                        "asks",
                        "bids",
                    }:
                        raise base.SourceFeasibilityError("order-book message schema drift")
                    if message["instId"] != market:
                        raise base.SourceFeasibilityError("archive contains wrong instrument")
                    ts_text = str(message["ts"])
                    if not ts_text.isascii() or not ts_text.isdecimal():
                        raise base.SourceFeasibilityError("invalid order-book timestamp")
                    ts = int(ts_text)
                    if not day_start_ms <= ts < day_end_ms:
                        raise base.SourceFeasibilityError("order-book timestamp outside anchor day")
                    if first_ts is None:
                        first_ts = ts
                        timestamp_residue = ts % 10
                    else:
                        assert previous_ts is not None and timestamp_residue is not None
                        gap = ts - previous_ts
                        if gap <= 0:
                            raise base.SourceFeasibilityError(
                                f"non-unique or non-increasing provider order: {previous_ts} -> {ts}"
                            )
                        if ts % 10 != timestamp_residue or gap % 10 != 0:
                            raise base.SourceFeasibilityError(
                                f"timestamp left provider 10 ms generation grid: {previous_ts} -> {ts}"
                            )
                        if gap > 10:
                            positive_gap_count += 1
                            maximum_gap_ms = max(maximum_gap_ms, gap)
                    previous_ts = last_ts = ts
                    while boundary_index < len(boundary_times) and boundary_times[boundary_index] < ts:
                        boundaries.append(base.boundary_state(bids, asks) if snapshot_seen else None)
                        boundary_index += 1
                    action = message["action"]
                    if action == "snapshot":
                        bids.clear()
                        asks.clear()
                        snapshot_count += 1
                        snapshot_seen = True
                    elif action == "update":
                        if not snapshot_seen:
                            raise base.SourceFeasibilityError("incremental update precedes initial snapshot")
                        update_count += 1
                    else:
                        raise base.SourceFeasibilityError(f"unsupported order-book action: {action!r}")
                    base.apply_levels(asks, message["asks"], side="ask")
                    base.apply_levels(bids, message["bids"], side="bid")
                    while boundary_index < len(boundary_times) and boundary_times[boundary_index] == ts:
                        boundaries.append(base.boundary_state(bids, asks))
                        boundary_index += 1
                    row_count += 1
        while reader.read(1 << 20):
            pass
        compressed_bytes = reader.bytes_read
        compressed_sha256 = reader.digest

    if member_count != 1 or member_name is None or first_ts is None or last_ts is None:
        raise base.SourceFeasibilityError("archive lacks one complete regular data member")
    while boundary_index < len(boundary_times):
        boundaries.append(base.boundary_state(bids, asks) if snapshot_seen else None)
        boundary_index += 1
    if first_ts - day_start_ms >= base.BOUNDARY_STEP_MS:
        raise base.SourceFeasibilityError("archive has no event before first five-minute boundary")
    if day_end_ms - last_ts > base.BOUNDARY_STEP_MS:
        raise base.SourceFeasibilityError("archive has no event in final five-minute interval")
    if snapshot_count < 1 or update_count < 1:
        raise base.SourceFeasibilityError("archive lacks snapshot/update semantics")
    if compressed_bytes != int(source["declared_compressed_bytes"]):
        # Provider sizeMB is rounded display metadata; exact bytes are authoritative and may differ.
        declared_delta = compressed_bytes - int(source["declared_compressed_bytes"])
    else:
        declared_delta = 0
    states = base.hourly_states(boundaries, market=market, anchor=anchor, day_start_ms=day_start_ms)
    valid_states = sum(bool(item["valid"]) for item in states)
    if any(not item["valid"] for item in states[1:]):
        raise base.SourceFeasibilityError("missing five-minute boundary after opening causal edge")

    result = {
        "family_id": base.FAMILY_ID,
        "market": market,
        "anchor_date_utc": anchor,
        "source_manifest_sha256": base.sha256(manifest_bytes),
        "source_url": url,
        "final_url": final_url,
        "declared_size_mb": source["size_mb_decimal"],
        "declared_size_bytes_ceiling": source["declared_compressed_bytes"],
        "declared_minus_exact_bytes": -declared_delta,
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
        "timestamp_residue_mod_10": timestamp_residue,
        "positive_no_emission_gap_count": positive_gap_count,
        "maximum_no_emission_gap_ms": maximum_gap_ms,
        "sequence_identity": (
            "exact provider file order; unique strictly increasing sparse event timestamps on one "
            "10 ms generation grid; absent grid slots are no-emission intervals"
        ),
        "sequence_continuity_passed": True,
        "source_day_complete": True,
        "boundary_count": len(boundaries),
        "valid_hour_count": valid_states,
        "invalid_hour_count": 24 - valid_states,
        "first_hour_missing_reason": states[0]["invalid_reason"],
        "streaming_working_set": True,
        "processing_seconds": time.monotonic() - started,
        "hourly_states": states,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{market}-{anchor}.json"
    output_path.write_bytes(base.canonical_json(result))
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    metadata = commands.add_parser("metadata")
    metadata.add_argument("--base-url", default="https://www.okx.com")
    metadata.add_argument("--output-dir", type=Path, required=True)
    day = commands.add_parser("process-day")
    day.add_argument("--manifest-path", type=Path, required=True)
    day.add_argument("--market", choices=base.MARKETS, required=True)
    day.add_argument("--anchor", choices=base.ANCHOR_DATES, required=True)
    day.add_argument("--output-dir", type=Path, required=True)
    aggregate = commands.add_parser("aggregate")
    aggregate.add_argument("--manifest-path", type=Path, required=True)
    aggregate.add_argument("--days-root", type=Path, required=True)
    aggregate.add_argument("--output-dir", type=Path, required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "metadata":
        result = acquire_metadata(args.base_url, args.output_dir)
    elif args.command == "process-day":
        result = process_archive(args.manifest_path, args.market, args.anchor, args.output_dir)
    else:
        result = base.aggregate(args.manifest_path, args.days_root, args.output_dir)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
