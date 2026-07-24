from __future__ import annotations

import argparse
import hashlib
import json
import resource
import statistics
import time
from datetime import UTC, datetime, timedelta

import gpt_quant.execution_quote_binding_journal as journal_module
from gpt_quant.execution_intent import TargetPositionIntent
from gpt_quant.execution_quote import ExecutionQuoteSnapshot
from gpt_quant.execution_quote_binding import bind_execution_quote

_SOURCE_SHA256 = "dcb30e58e10f8415aefe8c206f99c21fc8862b3b4f5ea65679a01262980c5481"
_QUOTE_SHA256 = "7d12a351f8f51320d1c8beee0063557e1c90388d66ac63412bf66ca544aeb3e3"
_INSTRUMENT_SHA256 = "290bd86ecbb1683351993197b0ec18001dfb604b9ba1cb864d9d6d327855f0eb"
_CONFIG_SHA256 = "6b06037376bce5df483311704f7b701c5e03a2a2735b2dd3361036fccd94da1a"


def _build_payload(count: int) -> bytes:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    bindings = []
    for index in range(count):
        signal_open = start + timedelta(hours=index)
        signal_close = signal_open + timedelta(hours=1)
        decision_not_before = signal_close + timedelta(milliseconds=100)
        intent = TargetPositionIntent(
            instrument_id="BTC-USDT",
            bar="1H",
            strategy_id="binding-replay-benchmark",
            strategy_revision="390d98361ccd62b58c18c3999cbcc62287208fdf",
            source_data_sha256=_SOURCE_SHA256,
            config_sha256=_CONFIG_SHA256,
            signal_bar_open_utc=signal_open,
            signal_bar_close_utc=signal_close,
            decision_not_before_utc=decision_not_before,
            expires_at_utc=decision_not_before + timedelta(minutes=1),
            target_position=(index % 10) / 10,
            minimum_position=0.0,
            maximum_position=1.0,
        )
        observed_at = decision_not_before + timedelta(milliseconds=5)
        quote = ExecutionQuoteSnapshot(
            provider="okx",
            instrument_id="BTC-USDT",
            observed_at_utc=observed_at,
            received_at_utc=observed_at + timedelta(milliseconds=5),
            bid_price="41006.3",
            bid_quantity="0.30178218",
            ask_price="41006.8",
            ask_quantity="0.60038921",
            source_response_sha256=_QUOTE_SHA256,
            instrument_snapshot_sha256=_INSTRUMENT_SHA256,
        )
        bindings.append(
            bind_execution_quote(
                intent,
                quote,
                decision_at_utc=quote.received_at_utc + timedelta(milliseconds=5),
                maximum_age_ms=250,
            )
        )
    return b"".join(binding.to_json_bytes() for binding in bindings)


def _legacy_parse(value: bytes):
    if not value:
        raise ValueError("execution quote binding journal must not be empty")
    lines = value.splitlines(keepends=True)
    if any(not line.endswith(b"\n") or line == b"\n" for line in lines):
        raise ValueError(
            "execution quote binding journal must contain canonical newline-terminated bindings"
        )
    journal = journal_module._journal_from_bindings(
        tuple(journal_module.ExecutionQuoteBinding.from_json_bytes(line) for line in lines)
    )
    if journal.to_bytes() != value:
        raise ValueError(
            "execution quote binding journal entries must use canonical chronological ordering"
        )
    return journal


def _run_worker(variant: str, count: int, repetitions: int) -> dict[str, object]:
    payload = _build_payload(count)
    parser = _legacy_parse if variant == "baseline" else journal_module._parse_journal_bytes
    expected = hashlib.sha256(payload).hexdigest()
    for _ in range(2):
        parsed = parser(payload)
        assert parsed.sha256 == expected
        assert parsed.to_bytes() == payload

    elapsed_ms = []
    for _ in range(repetitions):
        started = time.perf_counter_ns()
        parsed = parser(payload)
        elapsed_ms.append((time.perf_counter_ns() - started) / 1_000_000)
        assert parsed.sha256 == expected
    return {
        "variant": variant,
        "count": count,
        "payload_bytes": len(payload),
        "median_ms": statistics.median(elapsed_ms),
        "minimum_ms": min(elapsed_ms),
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "journal_sha256": expected,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", choices=("baseline", "optimized"), required=True)
    parser.add_argument("--count", type=int, default=2_000)
    parser.add_argument("--repetitions", type=int, default=15)
    args = parser.parse_args()
    if args.count <= 0 or args.repetitions <= 0:
        raise SystemExit("count and repetitions must be positive")
    print(
        json.dumps(
            _run_worker(args.variant, args.count, args.repetitions),
            sort_keys=True,
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
