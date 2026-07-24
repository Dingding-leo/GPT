from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from gpt_quant.execution_quote_evidence import record_execution_quote_evidence
from gpt_quant.okx_execution_quote import fetch_okx_top_of_book

INSTRUMENTS = ("BTC-USDT", "ETH-USDT")
SAMPLES_PER_INSTRUMENT = 12
INTERVAL_SECONDS = 2.0
MAX_ATTEMPTS = 2
HALF_SPREAD_P95_LIMIT_BPS = 2.5
REQUEST_RTT_P95_LIMIT_SECONDS = 1.0
SERVER_RTT_P95_LIMIT_SECONDS = 1.0
MAXIMUM_QUOTE_AGE_MS = 1_000
MAX_ABS_CLOCK_SKEW_SECONDS = 5.0
BASE_URL = "https://www.okx.com"
CANONICAL_SIGNATURE = (
    "prospective-top-of-book-friction-v1|provider=OKX-public|"
    "markets=BTC-USDT,ETH-USDT|samples=12-per-market|interval=2s|max-attempts=2|"
    "metric=half-spread-bps,books-rtt,server-rtt,exchange-quote-age,"
    "midpoint-clock-skew|pass=p95-half-spread<=2.5bps,p95-books-rtt<=1s,"
    "p95-server-rtt<=1s,max-quote-age<=1000ms,max-abs-skew<=5s,"
    "zero-unrecovered-failures-in-both-markets|candidate-count=1"
)
_MAX_RESPONSE_BYTES = 1_000_000


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _reject_duplicate_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"public OKX JSON contains duplicate field {key!r}")
        result[key] = value
    return result


def _parse_json(raw: bytes) -> Mapping[str, object]:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_fields)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("public OKX response must be UTF-8 JSON") from exc
    if not isinstance(value, Mapping):
        raise ValueError("public OKX response must be an object")
    return value


def _read_public_response(url: str, timeout: float) -> bytes:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "gpt-quant-lab/0.2 (+https://github.com/Dingding-leo/GPT)",
        },
    )
    with urlopen(request, timeout=timeout) as response:  # noqa: S310
        payload = response.read(_MAX_RESPONSE_BYTES + 1)
    if len(payload) > _MAX_RESPONSE_BYTES:
        raise RuntimeError("public OKX response exceeds the configured safety limit")
    return payload


def _fetch_instrument_snapshot(instrument_id: str, output_dir: Path) -> str:
    query = urlencode({"instType": "SPOT", "instId": instrument_id})
    url = f"{BASE_URL}/api/v5/public/instruments?{query}"
    requested_at = datetime.now(UTC)
    raw = _read_public_response(url, 20.0)
    received_at = datetime.now(UTC)
    payload = _parse_json(raw)
    if payload.get("code") != "0" or not isinstance(payload.get("msg"), str):
        raise RuntimeError("OKX instrument endpoint returned an error")
    data = payload.get("data")
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], Mapping):
        raise ValueError("OKX instrument response must contain exactly one instrument")
    instrument = data[0]
    if instrument.get("instId") != instrument_id or instrument.get("instType") != "SPOT":
        raise ValueError("OKX instrument response does not match the requested spot market")
    if instrument.get("state") != "live":
        raise ValueError("OKX instrument is not live")

    digest = hashlib.sha256(raw).hexdigest()
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "instrument.raw.json").write_bytes(raw)
    metadata = {
        "provider": "OKX",
        "endpoint": "/api/v5/public/instruments",
        "instrument_id": instrument_id,
        "requested_at_utc": requested_at.isoformat().replace("+00:00", "Z"),
        "received_at_utc": received_at.isoformat().replace("+00:00", "Z"),
        "raw_response_sha256": digest,
        "state": instrument.get("state"),
        "tick_size": instrument.get("tickSz"),
        "lot_size": instrument.get("lotSz"),
        "minimum_order_size_base": instrument.get("minSz"),
    }
    (output_dir / "instrument.metadata.json").write_bytes(_canonical_json_bytes(metadata))
    return digest


def nearest_rank_percentile(values: Sequence[float], probability: float) -> float:
    if not values:
        raise ValueError("percentile values cannot be empty")
    if not 0.0 < probability <= 1.0:
        raise ValueError("percentile probability must be in (0, 1]")
    ordered = sorted(float(value) for value in values)
    rank = max(1, math.ceil(probability * len(ordered)))
    return ordered[rank - 1]


def _quote_age_ms(raw_books: bytes, exchange_observed_at: datetime) -> int:
    payload = _parse_json(raw_books)
    data = payload.get("data")
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], Mapping):
        raise ValueError("OKX books response must contain exactly one object")
    timestamp = data[0].get("ts")
    if not isinstance(timestamp, str) or not timestamp.isascii() or not timestamp.isdecimal():
        raise ValueError("OKX books timestamp must be Unix milliseconds")
    exchange_ms = int(exchange_observed_at.timestamp() * 1_000)
    age = exchange_ms - int(timestamp)
    if age < 0:
        raise ValueError("OKX books timestamp is after the exchange-time observation")
    return age


def _market_summary(
    observations: list[dict[str, object]], failures: list[str]
) -> dict[str, object]:
    half_spreads = [float(item["half_spread_bps"]) for item in observations]
    books_rtts = [float(item["books_round_trip_seconds"]) for item in observations]
    server_rtts = [float(item["server_round_trip_seconds"]) for item in observations]
    quote_ages = [int(item["quote_age_ms"]) for item in observations]
    clock_skews = [abs(float(item["midpoint_clock_skew_seconds"])) for item in observations]

    complete = len(observations) == SAMPLES_PER_INSTRUMENT and not failures
    metrics = {
        "observations": len(observations),
        "unrecovered_failures": len(failures),
        "median_half_spread_bps": nearest_rank_percentile(half_spreads, 0.5),
        "p95_half_spread_bps": nearest_rank_percentile(half_spreads, 0.95),
        "p95_books_round_trip_seconds": nearest_rank_percentile(books_rtts, 0.95),
        "p95_server_round_trip_seconds": nearest_rank_percentile(server_rtts, 0.95),
        "maximum_quote_age_ms": max(quote_ages),
        "maximum_abs_midpoint_clock_skew_seconds": max(clock_skews),
    }
    checks = {
        "complete_observation_count": complete,
        "p95_half_spread": metrics["p95_half_spread_bps"] <= HALF_SPREAD_P95_LIMIT_BPS,
        "p95_books_round_trip": (
            metrics["p95_books_round_trip_seconds"] <= REQUEST_RTT_P95_LIMIT_SECONDS
        ),
        "p95_server_round_trip": (
            metrics["p95_server_round_trip_seconds"] <= SERVER_RTT_P95_LIMIT_SECONDS
        ),
        "maximum_quote_age": metrics["maximum_quote_age_ms"] <= MAXIMUM_QUOTE_AGE_MS,
        "maximum_abs_clock_skew": (
            metrics["maximum_abs_midpoint_clock_skew_seconds"] <= MAX_ABS_CLOCK_SKEW_SECONDS
        ),
    }
    return {
        "metrics": metrics,
        "checks": checks,
        "passes": all(checks.values()),
        "failures": failures,
        "observation_records": observations,
    }


def collect(output_dir: Path) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    market_results: dict[str, object] = {}

    for instrument_id in INSTRUMENTS:
        market_dir = output_dir / instrument_id
        snapshot_hash = _fetch_instrument_snapshot(instrument_id, market_dir)
        observations: list[dict[str, object]] = []
        failures: list[str] = []

        for sample_index in range(1, SAMPLES_PER_INSTRUMENT + 1):
            observation = None
            last_error: Exception | None = None
            for _attempt in range(1, MAX_ATTEMPTS + 1):
                try:
                    observation = fetch_okx_top_of_book(
                        instrument_id=instrument_id,
                        instrument_snapshot_sha256=snapshot_hash,
                        timeout=20.0,
                        maximum_quote_age_ms=MAXIMUM_QUOTE_AGE_MS,
                        max_request_round_trip_seconds=2.0,
                        max_server_round_trip_seconds=2.0,
                        max_abs_midpoint_clock_skew_seconds=MAX_ABS_CLOCK_SKEW_SECONDS,
                    )
                    break
                except Exception as exc:  # noqa: BLE001 - bounded evidence retry records failure
                    last_error = exc
                    time.sleep(0.5)
            if observation is None:
                failures.append(f"sample {sample_index}: {type(last_error).__name__}: {last_error}")
                continue

            record_execution_quote_evidence(market_dir / "quotes", observation.quote)
            raw_dir = market_dir / "raw"
            raw_dir.mkdir(parents=True, exist_ok=True)
            (raw_dir / f"{sample_index:02d}.books.json").write_bytes(observation.raw_response_json)
            (raw_dir / f"{sample_index:02d}.server-time.json").write_bytes(
                observation.raw_server_time_response_json
            )

            spread_bps = Decimal(observation.quote.spread_bps)
            record = {
                "sample_index": sample_index,
                "observed_at_utc": observation.quote.observed_at_utc.isoformat().replace(
                    "+00:00", "Z"
                ),
                "received_at_utc": observation.quote.received_at_utc.isoformat().replace(
                    "+00:00", "Z"
                ),
                "bid_price": observation.quote.bid_price,
                "ask_price": observation.quote.ask_price,
                "bid_quantity": observation.quote.bid_quantity,
                "ask_quantity": observation.quote.ask_quantity,
                "full_spread_bps": float(spread_bps),
                "half_spread_bps": float(spread_bps / Decimal(2)),
                "books_round_trip_seconds": observation.request_round_trip_seconds,
                "server_round_trip_seconds": observation.server_round_trip_seconds,
                "midpoint_clock_skew_seconds": observation.midpoint_clock_skew_seconds,
                "quote_age_ms": _quote_age_ms(
                    observation.raw_response_json,
                    observation.exchange_time_observed_utc,
                ),
                "books_response_sha256": observation.source_response_sha256,
                "server_time_response_sha256": observation.server_time_response_sha256,
                "quote_snapshot_id": observation.quote.snapshot_id,
                "instrument_snapshot_sha256": snapshot_hash,
            }
            observations.append(record)
            if sample_index < SAMPLES_PER_INSTRUMENT:
                time.sleep(INTERVAL_SECONDS)

        market_results[instrument_id] = _market_summary(observations, failures)

    joint_pass = all(bool(result["passes"]) for result in market_results.values())
    result = {
        "schema_version": 1,
        "canonical_signature": CANONICAL_SIGNATURE,
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "provider": "OKX",
        "market_type": "spot",
        "candidate_accounting": {
            "searched": 1,
            "passed": 1 if joint_pass else 0,
            "rejected": 0 if joint_pass else 1,
        },
        "method": {
            "instruments": list(INSTRUMENTS),
            "samples_per_instrument": SAMPLES_PER_INSTRUMENT,
            "interval_seconds": INTERVAL_SECONDS,
            "maximum_attempts_per_sample": MAX_ATTEMPTS,
            "exchange_fee_baseline_bps_one_way": 5.0,
            "aggregate_cost_sensitivities_bps_one_way": [7.5, 10.0, 15.0],
            "half_spread_p95_limit_bps": HALF_SPREAD_P95_LIMIT_BPS,
            "books_rtt_p95_limit_seconds": REQUEST_RTT_P95_LIMIT_SECONDS,
            "server_rtt_p95_limit_seconds": SERVER_RTT_P95_LIMIT_SECONDS,
            "maximum_quote_age_ms": MAXIMUM_QUOTE_AGE_MS,
            "maximum_abs_midpoint_clock_skew_seconds": MAX_ABS_CLOCK_SKEW_SECONDS,
        },
        "markets": market_results,
        "hypothesis_passes": joint_pass,
        "live_eligible": False,
        "limitations": [
            (
                "This bounded sample establishes collection feasibility only, not "
                "prospective strategy performance."
            ),
            "Top-of-book half-spread is measured separately from the 5 bps exchange fee.",
            (
                "Slippage, nonlinear impact, decision-to-order latency, fills and "
                "rejections remain unmeasured."
            ),
            (
                "BTC-USDT and ETH-USDT remain development markets; SOL-USDT remains a "
                "consumed holdout."
            ),
        ],
    }
    (output_dir / "result.json").write_bytes(_canonical_json_bytes(result))
    return result


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    result = collect(args.output_dir)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["hypothesis_passes"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
