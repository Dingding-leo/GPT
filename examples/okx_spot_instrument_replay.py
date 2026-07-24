from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

from gpt_quant.okx_execution_quote import fetch_okx_top_of_book
from gpt_quant.okx_execution_quote_replay import ReconstructableOKXTopOfBookEvidence
from gpt_quant.okx_instrument_archive import write_okx_spot_instrument_observation
from gpt_quant.okx_instruments import (
    OKXSpotInstrumentSnapshot,
    OKXUpcomingInstrumentChange,
    fetch_okx_spot_instrument_snapshot,
)
from gpt_quant.okx_live import OKXServerTimeSample
from gpt_quant.okx_order_constraints import validate_okx_spot_limit_order_constraints

_INSTRUMENT_FIXTURE_DIR = (
    Path(__file__).resolve().parents[1] / "tests/fixtures/okx/public_instruments_btc_usdt_20251125"
)
_QUOTE_FIXTURE_DIR = (
    Path(__file__).resolve().parents[1] / "tests/fixtures/okx/order-book-btc-usdt-docs-20210826"
)
_EXPECTED_INSTRUMENT_URL = (
    "https://www.okx.com/api/v5/public/instruments?instType=SPOT&instId=BTC-USDT"
)
_EXPECTED_INSTRUMENT_RAW_SHA256 = "290bd86ecbb1683351993197b0ec18001dfb604b9ba1cb864d9d6d327855f0eb"
_EXPECTED_QUOTE_URL = "https://test.okx.com/api/v5/market/books?instId=BTC-USDT&sz=1"
_EXPECTED_QUOTE_RAW_SHA256 = "7d12a351f8f51320d1c8beee0063557e1c90388d66ac63412bf66ca544aeb3e3"
_SERVER_TIME_RESPONSE = b'{"code":"0","msg":"","data":[{"ts":"1629966436500"}]}'
_EXPECTED_SERVER_TIME_SHA256 = "2ab44b9abd247acb72cf79b22b30e14c4e80cc00a96384a4535b31a37f6dfeb0"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay immutable public OKX instrument, quote, and order-constraint evidence."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reports/examples/okx-spot-instrument"),
    )
    return parser.parse_args()


def _utc(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _clock(*values: datetime):
    iterator = iter(values)
    return lambda: next(iterator)


def _verify_instrument_fixture_identity(
    raw_response: bytes, fixture_metadata: dict[str, Any]
) -> None:
    raw_sha256 = hashlib.sha256(raw_response).hexdigest()
    if raw_sha256 != _EXPECTED_INSTRUMENT_RAW_SHA256:
        raise ValueError(
            "immutable OKX instrument fixture does not match the pinned SHA-256 digest"
        )
    if fixture_metadata.get("fixture_sha256") != _EXPECTED_INSTRUMENT_RAW_SHA256:
        raise ValueError("OKX instrument fixture metadata does not match the pinned SHA-256 digest")


def _verify_quote_fixture_identity(raw_response: bytes, fixture_metadata: dict[str, Any]) -> None:
    raw_sha256 = hashlib.sha256(raw_response).hexdigest()
    if raw_sha256 != _EXPECTED_QUOTE_RAW_SHA256:
        raise ValueError("immutable OKX quote fixture does not match the pinned SHA-256 digest")
    if fixture_metadata.get("response_sha256") != _EXPECTED_QUOTE_RAW_SHA256:
        raise ValueError("OKX quote fixture metadata does not match the pinned SHA-256 digest")
    if fixture_metadata.get("instrument_snapshot_sha256") != _EXPECTED_INSTRUMENT_RAW_SHA256:
        raise ValueError("OKX quote fixture is not bound to the pinned instrument evidence")


def _replay_snapshot(metadata: dict[str, Any], raw_response: bytes) -> OKXSpotInstrumentSnapshot:
    return OKXSpotInstrumentSnapshot(
        base_url=metadata["base_url"],
        request_started_utc=_utc(metadata["request_started_utc"]),
        response_received_utc=_utc(metadata["response_received_utc"]),
        server_time_request_started_utc=_utc(metadata["server_time_request_started_utc"]),
        exchange_observed_at_utc=_utc(metadata["exchange_observed_at_utc"]),
        server_time_response_received_utc=_utc(metadata["server_time_response_received_utc"]),
        server_round_trip_seconds=metadata["server_round_trip_seconds"],
        midpoint_clock_skew_seconds=metadata["midpoint_clock_skew_seconds"],
        max_server_round_trip_seconds=metadata["max_server_round_trip_seconds"],
        max_abs_midpoint_clock_skew_seconds=metadata["max_abs_midpoint_clock_skew_seconds"],
        instrument_id=metadata["instrument_id"],
        base_currency=metadata["base_currency"],
        quote_currency=metadata["quote_currency"],
        state=metadata["state"],
        tick_size=metadata["tick_size"],
        lot_size=metadata["lot_size"],
        minimum_order_size_base=metadata["minimum_order_size_base"],
        listed_at_utc=_utc(metadata["listed_at_utc"]),
        continuous_trading_started_at_utc=_utc(metadata["continuous_trading_started_at_utc"]),
        expires_at_utc=_utc(metadata["expires_at_utc"]),
        valid_until_utc=_utc(metadata["valid_until_utc"]),
        upcoming_changes=tuple(
            OKXUpcomingInstrumentChange(
                parameter=change["parameter"],
                new_value=change["new_value"],
                effective_at_utc=_utc(change["effective_at_utc"]),
            )
            for change in metadata["upcoming_changes"]
        ),
        raw_response_json=raw_response,
    )


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _format_utc(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def main() -> int:
    args = _parse_args()
    instrument_metadata = json.loads((_INSTRUMENT_FIXTURE_DIR / "metadata.json").read_text())
    instrument_raw_response = (_INSTRUMENT_FIXTURE_DIR / "response.json").read_bytes()
    _verify_instrument_fixture_identity(instrument_raw_response, instrument_metadata)

    instrument_request_started = datetime(2026, 7, 24, 0, 0, tzinfo=UTC)
    instrument_response_received = instrument_request_started + timedelta(milliseconds=125)
    instrument_server_started = instrument_response_received + timedelta(milliseconds=1)
    instrument_server_received = instrument_server_started + timedelta(milliseconds=100)
    instrument_exchange_observed = instrument_server_started + timedelta(milliseconds=50)
    instrument_server_time = OKXServerTimeSample(
        base_url="https://www.okx.com",
        endpoint="/api/v5/public/time",
        local_request_started_utc=pd.Timestamp(instrument_server_started),
        local_response_received_utc=pd.Timestamp(instrument_server_received),
        server_time_utc=pd.Timestamp(instrument_exchange_observed),
        round_trip_seconds=0.1,
        midpoint_clock_skew_seconds=0.0,
    )

    def get_instrument_bytes(url: str, timeout: float) -> bytes:
        if url != _EXPECTED_INSTRUMENT_URL or timeout != 20.0:
            raise ValueError("unexpected public OKX instrument request")
        return instrument_raw_response

    snapshot = fetch_okx_spot_instrument_snapshot(
        inst_id="BTC-USDT",
        server_time_sample=instrument_server_time,
        get_bytes=get_instrument_bytes,
        now=_clock(instrument_request_started, instrument_response_received),
    )
    paths = write_okx_spot_instrument_observation(snapshot, args.output_dir)
    persisted_raw = paths["raw"].read_bytes()
    persisted_metadata_bytes = paths["metadata"].read_bytes()
    persisted_metadata = json.loads(persisted_metadata_bytes)
    replayed_instrument = _replay_snapshot(persisted_metadata, persisted_raw)

    if replayed_instrument.metadata_bytes() != persisted_metadata_bytes:
        raise ValueError("persisted instrument metadata is not canonical replay evidence")
    if replayed_instrument.raw_response_sha256 != _EXPECTED_INSTRUMENT_RAW_SHA256:
        raise ValueError("persisted instrument provider bytes do not match the pinned fixture")
    if replayed_instrument.metadata_sha256 != snapshot.metadata_sha256:
        raise ValueError("instrument observation identity changed during replay")

    quote_metadata = json.loads((_QUOTE_FIXTURE_DIR / "metadata.json").read_text())
    quote_raw_response = (_QUOTE_FIXTURE_DIR / "response.json").read_bytes()
    _verify_quote_fixture_identity(quote_raw_response, quote_metadata)

    def get_quote_bytes(url: str, timeout: float) -> bytes:
        if url != _EXPECTED_QUOTE_URL or timeout != 20.0:
            raise ValueError("unexpected public OKX books request")
        return quote_raw_response

    def get_server_time_bytes(url: str, timeout: float) -> bytes:
        if url != "https://test.okx.com/api/v5/public/time" or timeout != 20.0:
            raise ValueError("unexpected public OKX server-time request")
        return _SERVER_TIME_RESPONSE

    quote_observation = fetch_okx_top_of_book(
        instrument_id="BTC-USDT",
        instrument_snapshot_sha256=replayed_instrument.raw_response_sha256,
        base_url="https://test.okx.com",
        maximum_quote_age_ms=200,
        get_bytes=get_quote_bytes,
        get_server_time_bytes=get_server_time_bytes,
        now=_clock(
            datetime(2021, 8, 26, 8, 27, 16, 420_000, tzinfo=UTC),
            datetime(2021, 8, 26, 8, 27, 16, 450_000, tzinfo=UTC),
            datetime(2021, 8, 26, 8, 27, 16, 460_000, tzinfo=UTC),
            datetime(2021, 8, 26, 8, 27, 16, 540_000, tzinfo=UTC),
        ),
    )
    quote_evidence = ReconstructableOKXTopOfBookEvidence(observation=quote_observation)
    quote_evidence_bytes = quote_evidence.to_json_bytes()
    replayed_quote_evidence = ReconstructableOKXTopOfBookEvidence.from_json_bytes(
        quote_evidence_bytes
    )
    if replayed_quote_evidence.to_json_bytes() != quote_evidence_bytes:
        raise ValueError("OKX quote replay evidence is not canonical")
    if replayed_quote_evidence.observation != quote_observation:
        raise ValueError("OKX quote evidence changed during replay")
    if quote_observation.server_time_response_sha256 != _EXPECTED_SERVER_TIME_SHA256:
        raise ValueError("OKX server-time evidence does not match the expected exact bytes")

    quote = replayed_quote_evidence.observation.quote
    constraint_submitted_at = replayed_instrument.server_time_response_received_utc + timedelta(
        milliseconds=1
    )
    validated_quantity, validated_limit_price = validate_okx_spot_limit_order_constraints(
        replayed_instrument,
        submitted_at_utc=constraint_submitted_at,
        maximum_snapshot_age_ms=1_000,
        base_quantity=replayed_instrument.minimum_order_size_base,
        limit_price=quote.ask_price,
    )

    minimum_base = replayed_instrument.minimum_order_size_base_decimal
    minimum_buy_quote_equivalent = minimum_base * Decimal(quote.ask_price)
    minimum_sell_quote_equivalent = minimum_base * Decimal(quote.bid_price)

    summary = {
        "account_connectivity": "disabled",
        "constraint_probe": {
            "base_quantity": validated_quantity,
            "limit_price": validated_limit_price,
            "maximum_instrument_snapshot_age_ms": 1_000,
            "submitted_at_utc": _format_utc(constraint_submitted_at),
            "status": "passed",
        },
        "exchange_fee_baseline_bps_one_way": 5.0,
        "instrument_archive_files": sorted(path.name for path in paths.values()),
        "instrument_id": replayed_instrument.instrument_id,
        "instrument_observation_id": replayed_instrument.metadata_sha256,
        "instrument_raw_response_sha256": replayed_instrument.raw_response_sha256,
        "instrument_replay_equal": replayed_instrument == snapshot,
        "lot_size": replayed_instrument.lot_size,
        "minimum_buy_quote_equivalent_at_observed_ask": _decimal_text(minimum_buy_quote_equivalent),
        "minimum_order_size_base": replayed_instrument.minimum_order_size_base,
        "minimum_quote_notional_constraint": "not_reported_by_public_instrument_endpoint",
        "minimum_sell_quote_equivalent_at_observed_bid": _decimal_text(
            minimum_sell_quote_equivalent
        ),
        "order_submission": "not_performed",
        "paper_order_blockers": [
            "documentation_fixtures_are_not_contemporaneous",
            "minimum_quote_notional_constraint_not_available",
            "risk_approval_not_present",
            "broker_and_portfolio_state_not_present",
        ],
        "paper_order_eligible": False,
        "quote": {
            "ask_price": quote.ask_price,
            "ask_quantity": quote.ask_quantity,
            "bid_price": quote.bid_price,
            "bid_quantity": quote.bid_quantity,
            "evidence_id": replayed_quote_evidence.evidence_id,
            "exchange_observed_at_utc": _format_utc(
                quote_observation.exchange_time_observed_utc
            ),
            "fixture_scope": (
                "official_documentation_parser_and_timing_evidence_not_contemporaneous"
            ),
            "maximum_age_ms": quote_observation.maximum_quote_age_ms,
            "observed_at_utc": _format_utc(quote.observed_at_utc),
            "received_at_utc": _format_utc(quote.received_at_utc),
            "replay_equal": replayed_quote_evidence.observation == quote_observation,
            "server_time_response_sha256": quote_observation.server_time_response_sha256,
            "source_response_sha256": quote_observation.source_response_sha256,
        },
        "separate_cost_inputs": {
            "latency": "timestamp_evidence_only_not_priced",
            "market_impact": "not_modeled",
            "observed_spread_bps": _decimal_text(quote.spread_bps),
            "slippage": "not_modeled",
            "stress_bps_all_in": [7.5, 10.0, 15.0],
        },
        "state": replayed_instrument.state,
        "tick_size": replayed_instrument.tick_size,
        "timing_replay_scope": "complete_instrument_and_quote_server_time_envelopes",
        "valid_until_utc": (
            None
            if replayed_instrument.valid_until_utc is None
            else _format_utc(replayed_instrument.valid_until_utc)
        ),
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
