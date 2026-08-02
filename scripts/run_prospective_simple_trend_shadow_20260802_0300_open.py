from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_1800 as engine
import run_prospective_simple_trend_shadow_20260802_0300 as prior

PAYOFF_END_OPEN_HOUR_MS = 1_785_639_600_000


def require_completed_or_payoff_open(
    candles: dict[int, dict[str, Any]], timestamp_ms: int, instrument: str
) -> dict[str, Any]:
    if timestamp_ms != PAYOFF_END_OPEN_HOUR_MS:
        return ORIGINAL_REQUIRE_CANDLE(candles, timestamp_ms, instrument)

    candle = candles.get(timestamp_ms)
    if candle is None:
        raise ValueError(
            f"missing payoff-end open {engine.iso_utc(timestamp_ms)}: {instrument}"
        )
    if candle.get("confirm") not in {"0", "1"}:
        raise ValueError(
            f"invalid payoff-end confirm flag {engine.iso_utc(timestamp_ms)}: {instrument}"
        )
    open_price = float(candle["open"])
    if not math.isfinite(open_price) or open_price <= 0.0:
        raise ValueError(
            f"invalid payoff-end open {engine.iso_utc(timestamp_ms)}: {instrument}"
        )
    return candle


ORIGINAL_REQUIRE_CANDLE = engine.require_candle


def write_outputs(output_dir: Path, result: dict[str, Any]) -> None:
    payload = json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n"
    (output_dir / "result.json").write_text(payload)
    (output_dir / "result.sha256").write_text(
        hashlib.sha256(payload.encode()).hexdigest() + "\n"
    )

    report = (output_dir / "report.md").read_text()
    insertion = (
        "\n## Payoff-end open boundary\n\n"
        "The 03:00 UTC candle was still forming at acquisition. Only its already fixed opening "
        "price was used as the end of the 02:00–03:00 UTC open-to-open payoff. The incomplete "
        "candle supplied no close, high, low, volume, signal, feature, target or future return. "
        "The 02:00 UTC signal candle and every 2,160H-history observation remained "
        "provider-confirmed completed bars.\n"
    )
    marker = "\n## Drift diagnosis\n"
    if marker not in report:
        raise ValueError("report insertion marker missing")
    report = report.replace(marker, insertion + marker, 1)
    (output_dir / "report.md").write_text(report)


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    engine.require_candle = require_completed_or_payoff_open
    try:
        result = prior.run(output_dir, base_url)
    finally:
        engine.require_candle = ORIGINAL_REQUIRE_CANDLE

    result["generated_at"] = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    result["payoff_end_open_boundary"] = {
        "timestamp_ms": PAYOFF_END_OPEN_HOUR_MS,
        "timestamp": engine.iso_utc(PAYOFF_END_OPEN_HOUR_MS),
        "field_used": "open",
        "provider_confirm_required": False,
        "provider_confirm_values_allowed": ["0", "1"],
        "used_for_signal": False,
        "used_for_feature": False,
        "used_for_target": False,
        "used_for_position": False,
        "used_for_turnover": False,
        "used_for_fee": False,
        "used_only_as_realized_payoff_endpoint": True,
        "open_is_fixed_at_bar_start": True,
    }
    result["payoff_boundary_repair"] = {
        "applied": True,
        "type": "fixed_open_endpoint_for_realized_payoff",
        "failed_attempt_workflow_run": 30730365112,
        "open_endpoint_timestamp": engine.iso_utc(PAYOFF_END_OPEN_HOUR_MS),
        "open_endpoint_only": True,
        "incomplete_close_accessed": False,
        "incomplete_high_accessed": False,
        "incomplete_low_accessed": False,
        "incomplete_volume_accessed": False,
        "future_signal_accessed": False,
        "strategy_value_changed": False,
        "source_changed": False,
        "fee_changed": False,
        "architecture_changed": False,
    }
    result["machine_readable_verdict"].update(
        {
            "payoff_end_open_timestamp": engine.iso_utc(PAYOFF_END_OPEN_HOUR_MS),
            "payoff_end_open_confirm_required": False,
            "payoff_end_open_only": True,
            "future_signal_accessed": False,
            "strategy_value_changed": False,
            "payoff_boundary_repair_applied": True,
        }
    )
    write_outputs(output_dir, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--base-url", default=os.environ.get("OKX_BASE_URL", "https://www.okx.com")
    )
    args = parser.parse_args()
    print(
        json.dumps(
            run(args.output_dir, args.base_url.rstrip("/")),
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
