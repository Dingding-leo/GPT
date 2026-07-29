from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_1800 as base

HOUR_MS = base.HOUR_MS
PREVIOUS_DECISION_HOUR_MS = 1_785_272_400_000  # 2026-07-28T21:00:00Z
REALIZED_DECISION_HOUR_MS = 1_785_276_000_000  # 2026-07-28T22:00:00Z
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_279_600_000  # 2026-07-28T23:00:00Z
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_283_200_000  # 2026-07-29T00:00:00Z
PRIOR_RESULT_SHA256 = "d623c4ad4f24796ba4c79463d272f9bbf24c814a6e9b9bdbac3cdb951644f88f"
PRIOR_ARTIFACT_SHA256 = "ec34a6dfaad6d80b5c08c066a59957a585722a25d9e6a0e7f1fdae927b829a22"


def configure_frozen_epoch() -> None:
    base.PREVIOUS_DECISION_HOUR_MS = PREVIOUS_DECISION_HOUR_MS
    base.REALIZED_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
    base.PRIOR_REPORTED_SIGNAL_HOUR_MS = PRIOR_REPORTED_SIGNAL_HOUR_MS
    base.LATEST_COMPLETE_SIGNAL_HOUR_MS = LATEST_COMPLETE_SIGNAL_HOUR_MS
    base.PRIOR_RESULT_SHA256 = PRIOR_RESULT_SHA256
    base.PRIOR_ARTIFACT_SHA256 = PRIOR_ARTIFACT_SHA256


def close_at(
    candles: dict[int, dict[str, Any]], timestamp_ms: int, instrument: str
) -> float:
    return float(base.require_candle(candles, timestamp_ms, instrument)["close"])


def drift_attribution(
    candles: dict[int, dict[str, Any]], instrument: str
) -> dict[str, Any]:
    prior_current = close_at(candles, PRIOR_REPORTED_SIGNAL_HOUR_MS, instrument)
    latest_current = close_at(candles, LATEST_COMPLETE_SIGNAL_HOUR_MS, instrument)
    prior_reference = close_at(
        candles,
        PRIOR_REPORTED_SIGNAL_HOUR_MS - base.LOOKBACK_HOURS * HOUR_MS,
        instrument,
    )
    latest_reference = close_at(
        candles,
        LATEST_COMPLETE_SIGNAL_HOUR_MS - base.LOOKBACK_HOURS * HOUR_MS,
        instrument,
    )
    return {
        "prior_current_close": prior_current,
        "latest_current_close": latest_current,
        "current_close_return": latest_current / prior_current - 1.0,
        "prior_lagged_reference_close": prior_reference,
        "latest_lagged_reference_close": latest_reference,
        "lagged_reference_return": latest_reference / prior_reference - 1.0,
        "interpretation": (
            "margin change is jointly determined by the current close and the rolling "
            "2160H reference close; no policy parameter changed"
        ),
    }


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    configure_frozen_epoch()
    source_root = output_dir / "source"
    server_ms, server_source = base.fetch_server_time(base_url, source_root)
    minimum_server_ms = LATEST_COMPLETE_SIGNAL_HOUR_MS + HOUR_MS
    if server_ms < minimum_server_ms:
        raise ValueError(
            "frozen cutoff bar was not complete at acquisition: "
            f"server={base.iso_utc(server_ms)} required={base.iso_utc(minimum_server_ms)}"
        )

    market_results: list[dict[str, Any]] = []
    source_markets: list[dict[str, Any]] = []
    for instrument in base.MARKETS:
        candles, pages = base.fetch_candles(base_url, instrument, source_root / instrument)
        grid = base.validate_grid(candles, instrument)
        market = base.calculate_market(candles, instrument)
        market["drift_attribution"] = drift_attribution(candles, instrument)
        market_results.append(market)
        source_markets.append(
            {
                "instrument": instrument,
                "pages": pages,
                "unique_candle_count": len(candles),
                "grid": grid,
            }
        )

    all_cash = all(
        market["realized_interval"]["position"] == 0
        and market["new_long_targets"] == 0
        for market in market_results
    )
    verdict = (
        "prospective_simple_trend_no_trade_continues"
        if all_cash
        else "prospective_simple_trend_exposure_observed_continue_shadow_only"
    )
    result = {
        "schema_version": 1,
        "generated_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        "policy_name": "simple_trend_long_cash_2160h_next_open",
        "policy_signature": base.POLICY_SIGNATURE,
        "policy_sha256": base.sha256_bytes(base.POLICY_SIGNATURE.encode()),
        "architecture_status": "frozen_benchmark_shadow_only",
        "nomination_status": (
            "no_statistically_eligible_strategy_adaptive_state_training_gate_active"
        ),
        "bar": base.BAR,
        "markets_independent": True,
        "cross_sectional_selection": False,
        "canonical_fee_bps_one_way": base.FEE_BPS_ONE_WAY,
        "actual_orders": False,
        "credentials_used": False,
        "private_endpoints_used": False,
        "enabled_adapters": False,
        "live_trading_authorized": False,
        "paper_trading_authorized": False,
        "reserved_trade_flow_oos_consumed": False,
        "adaptive_state_official_oos_consumed": False,
        "prospective_lineage": {
            "prior_result_sha256": PRIOR_RESULT_SHA256,
            "prior_artifact_sha256": PRIOR_ARTIFACT_SHA256,
            "prior_last_signal_bar_start": base.iso_utc(PRIOR_REPORTED_SIGNAL_HOUR_MS),
            "latest_complete_signal_bar_start": base.iso_utc(
                LATEST_COMPLETE_SIGNAL_HOUR_MS
            ),
            "policy_unchanged": True,
        },
        "window": {
            "prior_last_signal_bar_start_ms": PRIOR_REPORTED_SIGNAL_HOUR_MS,
            "prior_last_signal_bar_start": base.iso_utc(PRIOR_REPORTED_SIGNAL_HOUR_MS),
            "latest_complete_signal_bar_start_ms": LATEST_COMPLETE_SIGNAL_HOUR_MS,
            "latest_complete_signal_bar_start": base.iso_utc(
                LATEST_COMPLETE_SIGNAL_HOUR_MS
            ),
            "new_signal_bar_count": 1,
            "new_realized_payoff_intervals": 1,
            "prior_cumulative_realized_hours": 502,
            "updated_cumulative_realized_hours": 503,
        },
        "acquisition": server_source,
        "sources": source_markets,
        "markets": market_results,
        "abort_conditions": {
            "triggered": False,
            "conditions": [
                "server time before frozen cutoff completion",
                "missing or incomplete required 1H candle",
                "non-contiguous required 1H grid",
                "conflicting duplicate candle",
                "non-finite or non-positive required price",
                "public OKX response error or pagination non-advance",
            ],
        },
        "verdict": verdict,
        "next_strategy_action": (
            "continue the immutable benchmark-shadow epoch without policy changes; "
            "the active adaptive-state family remains blocked at its exact all-member "
            "training gate and no strategy is nominated for paper or live use"
        ),
    }
    base.write_outputs(output_dir, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("OKX_BASE_URL", "https://www.okx.com"),
    )
    args = parser.parse_args()
    result = run(args.output_dir, args.base_url.rstrip("/"))
    print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
