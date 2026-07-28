from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

HOUR_MS = 3_600_000
LOOKBACK_HOURS = 2_160
FEE_BPS_ONE_WAY = 5.0
FEE_RATE = FEE_BPS_ONE_WAY / 10_000.0
MARKETS = ("BTC-USDT", "ETH-USDT")
BAR = "1H"
PRIOR_LAST_SIGNAL_HOUR_MS = 1_785_243_600_000  # 2026-07-28T13:00:00Z
LAST_COMPLETE_SIGNAL_HOUR_MS = 1_785_250_800_000  # 2026-07-28T15:00:00Z
POLICY_SIGNATURE = (
    "simple-trend-next-open-v1|lookback=2160H|"
    "target=1[close[t]/close[t-2160H]-1>0]|"
    "execution=open[t+1]|position=long-cash|fee=5bps-one-way"
)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def iso_utc(timestamp_ms: int) -> str:
    value = datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)
    return value.isoformat().replace("+00:00", "Z")


def request_bytes(url: str, attempts: int = 5) -> tuple[bytes, str]:
    last_error: Exception | None = None
    for attempt in range(attempts):
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "Dingding-leo-GPT-prospective-shadow/1.0",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:  # noqa: S310
                return response.read(), response.geturl()
        except (HTTPError, URLError, TimeoutError) as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(2**attempt)
    raise RuntimeError(f"public request failed: {url}") from last_error


def parse_response(payload: bytes) -> list[list[str]]:
    document = json.loads(payload)
    if document.get("code") != "0" or document.get("msg") not in ("", None):
        raise ValueError(f"OKX returned an error: {document}")
    rows = document.get("data")
    if not isinstance(rows, list):
        raise ValueError("OKX response data is not a list")
    parsed: list[list[str]] = []
    for row in rows:
        valid_row = (
            isinstance(row, list)
            and len(row) == 9
            and all(isinstance(item, str) for item in row)
        )
        if not valid_row:
            raise ValueError("unexpected OKX candle row schema")
        parsed.append(row)
    return parsed


def fetch_server_time(base_url: str, source_dir: Path) -> tuple[int, dict[str, Any]]:
    url = f"{base_url}/api/v5/public/time"
    payload, final_url = request_bytes(url)
    source_dir.mkdir(parents=True, exist_ok=True)
    path = source_dir / "server-time.json"
    path.write_bytes(payload)
    document = json.loads(payload)
    data = document.get("data")
    if document.get("code") != "0" or not isinstance(data, list) or len(data) != 1:
        raise ValueError("invalid OKX server-time response")
    server_ms = int(data[0]["ts"])
    return server_ms, {
        "request_url": url,
        "final_url": final_url,
        "path": str(path),
        "sha256": sha256_bytes(payload),
        "server_time_ms": server_ms,
        "server_time": iso_utc(server_ms),
    }


def fetch_candles(
    base_url: str,
    instrument: str,
    source_dir: Path,
) -> tuple[dict[int, dict[str, Any]], list[dict[str, Any]]]:
    earliest_required = PRIOR_LAST_SIGNAL_HOUR_MS - (LOOKBACK_HOURS + 1) * HOUR_MS
    pages: list[dict[str, Any]] = []
    candles: dict[int, dict[str, Any]] = {}
    cursor: int | None = None

    for page_index in range(20):
        endpoint = (
            "/api/v5/market/candles"
            if page_index == 0
            else "/api/v5/market/history-candles"
        )
        query = {"instId": instrument, "bar": BAR, "limit": "300"}
        if cursor is not None:
            query["after"] = str(cursor)
        url = f"{base_url}{endpoint}?{urlencode(query)}"
        payload, final_url = request_bytes(url)
        source_dir.mkdir(parents=True, exist_ok=True)
        path = source_dir / f"page-{page_index:02d}.json"
        path.write_bytes(payload)
        rows = parse_response(payload)
        if not rows:
            raise ValueError(f"empty candle page for {instrument}")

        timestamps: list[int] = []
        for row in rows:
            timestamp_ms = int(row[0])
            timestamps.append(timestamp_ms)
            record = {
                "timestamp_ms": timestamp_ms,
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume_base": float(row[5]),
                "volume_quote": float(row[7]),
                "confirm": row[8],
            }
            prior = candles.get(timestamp_ms)
            if prior is not None and prior != record:
                raise ValueError(
                    f"conflicting duplicate at {iso_utc(timestamp_ms)}: {instrument}"
                )
            candles[timestamp_ms] = record

        oldest = min(timestamps)
        newest = max(timestamps)
        pages.append(
            {
                "request_url": url,
                "final_url": final_url,
                "path": str(path),
                "sha256": sha256_bytes(payload),
                "row_count": len(rows),
                "oldest_timestamp_ms": oldest,
                "oldest_timestamp": iso_utc(oldest),
                "newest_timestamp_ms": newest,
                "newest_timestamp": iso_utc(newest),
            }
        )
        if oldest <= earliest_required:
            break
        if cursor is not None and oldest >= cursor:
            raise ValueError(f"candle pagination did not advance: {instrument}")
        cursor = oldest
    else:
        raise ValueError(f"candle pagination budget exhausted: {instrument}")

    return candles, pages


def require_candle(
    candles: dict[int, dict[str, Any]],
    timestamp_ms: int,
    instrument: str,
) -> dict[str, Any]:
    candle = candles.get(timestamp_ms)
    if candle is None:
        raise ValueError(f"missing candle {iso_utc(timestamp_ms)}: {instrument}")
    if candle["confirm"] != "1":
        raise ValueError(f"incomplete candle {iso_utc(timestamp_ms)}: {instrument}")
    for field in ("open", "high", "low", "close", "volume_base", "volume_quote"):
        value = float(candle[field])
        if not math.isfinite(value) or value < 0.0:
            raise ValueError(f"invalid {field} at {iso_utc(timestamp_ms)}: {instrument}")
    if float(candle["open"]) <= 0.0 or float(candle["close"]) <= 0.0:
        raise ValueError(f"non-positive price at {iso_utc(timestamp_ms)}: {instrument}")
    return candle


def validate_grid(
    candles: dict[int, dict[str, Any]],
    instrument: str,
) -> dict[str, Any]:
    first = PRIOR_LAST_SIGNAL_HOUR_MS - (LOOKBACK_HOURS + 1) * HOUR_MS
    last = LAST_COMPLETE_SIGNAL_HOUR_MS
    expected = range(first, last + HOUR_MS, HOUR_MS)
    count = 0
    for timestamp_ms in expected:
        require_candle(candles, timestamp_ms, instrument)
        count += 1
    return {
        "first_required_bar_start_ms": first,
        "first_required_bar_start": iso_utc(first),
        "last_required_bar_start_ms": last,
        "last_required_bar_start": iso_utc(last),
        "required_bar_count": count,
        "missing_bar_count": 0,
        "incomplete_bar_count": 0,
        "contiguous_confirmed_grid_passed": True,
    }


def signal_margin(
    candles: dict[int, dict[str, Any]],
    timestamp_ms: int,
    instrument: str,
) -> float:
    current = require_candle(candles, timestamp_ms, instrument)
    lagged = require_candle(
        candles,
        timestamp_ms - LOOKBACK_HOURS * HOUR_MS,
        instrument,
    )
    return float(current["close"]) / float(lagged["close"]) - 1.0


def calculate_market(
    candles: dict[int, dict[str, Any]],
    instrument: str,
) -> dict[str, Any]:
    new_signal_hours = [
        PRIOR_LAST_SIGNAL_HOUR_MS + HOUR_MS,
        LAST_COMPLETE_SIGNAL_HOUR_MS,
    ]
    previous_decision_hour = PRIOR_LAST_SIGNAL_HOUR_MS - HOUR_MS
    realized_decision_hour = PRIOR_LAST_SIGNAL_HOUR_MS
    payoff_open_start = realized_decision_hour + HOUR_MS
    payoff_open_end = payoff_open_start + HOUR_MS
    required_signal_hours = [
        previous_decision_hour,
        realized_decision_hour,
        *new_signal_hours,
    ]
    margins = {
        timestamp_ms: signal_margin(candles, timestamp_ms, instrument)
        for timestamp_ms in required_signal_hours
    }
    targets = {timestamp_ms: int(value > 0.0) for timestamp_ms, value in margins.items()}

    previous_position = targets[previous_decision_hour]
    position = targets[realized_decision_hour]
    turnover = abs(position - previous_position)
    fee = turnover * FEE_RATE
    start_open = float(require_candle(candles, payoff_open_start, instrument)["open"])
    end_open = float(require_candle(candles, payoff_open_end, instrument)["open"])
    asset_return = end_open / start_open - 1.0
    gross_return = position * asset_return
    net_return = gross_return - fee

    decisions = []
    for timestamp_ms in new_signal_hours:
        decisions.append(
            {
                "signal_hour_start_ms": timestamp_ms,
                "signal_hour_start": iso_utc(timestamp_ms),
                "signal_available_at": iso_utc(timestamp_ms + HOUR_MS),
                "margin": margins[timestamp_ms],
                "target": targets[timestamp_ms],
                "execution_open": iso_utc(timestamp_ms + HOUR_MS),
                "realized_payoff_available": False,
            }
        )
    no_trade_frequency = sum(item["target"] == 0 for item in decisions) / len(decisions)
    pending_target_changes = sum(
        decisions[index]["target"] != decisions[index - 1]["target"]
        for index in range(1, len(decisions))
    )

    return {
        "instrument": instrument,
        "lookback_hours": LOOKBACK_HOURS,
        "new_signal_observations": len(decisions),
        "new_decisions": decisions,
        "new_long_targets": sum(item["target"] for item in decisions),
        "no_trade_frequency": no_trade_frequency,
        "pending_target_changes": pending_target_changes,
        "realized_interval": {
            "decision_hour_start_ms": realized_decision_hour,
            "decision_hour_start": iso_utc(realized_decision_hour),
            "signal_available_at": iso_utc(realized_decision_hour + HOUR_MS),
            "payoff_open_start_ms": payoff_open_start,
            "payoff_open_start": iso_utc(payoff_open_start),
            "payoff_open_end_ms": payoff_open_end,
            "payoff_open_end": iso_utc(payoff_open_end),
            "previous_position": previous_position,
            "position": position,
            "turnover": turnover,
            "modeled_fee": fee,
            "asset_return": asset_return,
            "gross_strategy_return": gross_return,
            "net_strategy_return": net_return,
            "strategy_residual_vs_buy_and_hold": net_return - asset_return,
            "maximum_drawdown": min(0.0, net_return),
            "edge_per_turnover_bps": (
                net_return / turnover * 10_000.0 if turnover > 0.0 else None
            ),
        },
        "signal_drift": {
            "margin_at_prior_reported_signal_hour": margins[
                PRIOR_LAST_SIGNAL_HOUR_MS
            ],
            "margin_at_latest_complete_signal_hour": margins[
                LAST_COMPLETE_SIGNAL_HOUR_MS
            ],
            "margin_change": (
                margins[LAST_COMPLETE_SIGNAL_HOUR_MS]
                - margins[PRIOR_LAST_SIGNAL_HOUR_MS]
            ),
            "target_changed_since_prior_reported_signal_hour": (
                targets[LAST_COMPLETE_SIGNAL_HOUR_MS]
                != targets[PRIOR_LAST_SIGNAL_HOUR_MS]
            ),
        },
        "sharpe": None,
        "sharpe_reason": "one newly realized payoff interval is insufficient",
        "loss_clustering": None,
        "loss_clustering_reason": "one newly realized payoff interval is insufficient",
    }


def write_outputs(output_dir: Path, result: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = canonical_json(result)
    (output_dir / "result.json").write_bytes(payload)
    (output_dir / "result.sha256").write_text(sha256_bytes(payload) + "\n")

    lines = [
        "# Prospective simple-trend shadow update",
        "",
        f"- Policy SHA-256: `{result['policy_sha256']}`",
        f"- Acquisition server time: `{result['acquisition']['server_time']}`",
        f"- New complete signal bars: `{result['window']['new_signal_bar_count']}`",
        (
            "- Newly realized payoff intervals: "
            f"`{result['window']['new_realized_payoff_intervals']}`"
        ),
        "",
        (
            "| Market | Position | Net return | Turnover | Fee | "
            "Latest margin | No-trade frequency |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for market in result["markets"]:
        realized = market["realized_interval"]
        drift = market["signal_drift"]
        lines.append(
            "| {instrument} | {position} | {net:.6%} | {turnover:.4f} | "
            "{fee:.6%} | {margin:.6%} | {no_trade:.2%} |".format(
                instrument=market["instrument"],
                position=realized["position"],
                net=realized["net_strategy_return"],
                turnover=realized["turnover"],
                fee=realized["modeled_fee"],
                margin=drift["margin_at_latest_complete_signal_hour"],
                no_trade=market["no_trade_frequency"],
            )
        )
    lines.extend(
        [
            "",
            f"Verdict: `{result['verdict']}`",
            "",
            "No live or paper-trading authorization is implied.",
        ]
    )
    (output_dir / "report.md").write_text("\n".join(lines) + "\n")


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    source_root = output_dir / "source"
    server_ms, server_source = fetch_server_time(base_url, source_root)
    minimum_server_ms = LAST_COMPLETE_SIGNAL_HOUR_MS + HOUR_MS
    if server_ms < minimum_server_ms:
        raise ValueError(
            "frozen cutoff bar was not complete at acquisition: "
            f"server={iso_utc(server_ms)} required={iso_utc(minimum_server_ms)}"
        )

    market_results = []
    source_markets = []
    for instrument in MARKETS:
        candles, pages = fetch_candles(base_url, instrument, source_root / instrument)
        grid = validate_grid(candles, instrument)
        market_results.append(calculate_market(candles, instrument))
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
        and all(item["target"] == 0 for item in market["new_decisions"])
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
        "policy_signature": POLICY_SIGNATURE,
        "policy_sha256": sha256_bytes(POLICY_SIGNATURE.encode()),
        "architecture_status": "frozen_benchmark_shadow_only",
        "bar": BAR,
        "markets_independent": True,
        "cross_sectional_selection": False,
        "canonical_fee_bps_one_way": FEE_BPS_ONE_WAY,
        "actual_orders": False,
        "credentials_used": False,
        "private_endpoints_used": False,
        "enabled_adapters": False,
        "live_trading_authorized": False,
        "paper_trading_authorized": False,
        "reserved_trade_flow_oos_consumed": False,
        "window": {
            "prior_last_signal_bar_start_ms": PRIOR_LAST_SIGNAL_HOUR_MS,
            "prior_last_signal_bar_start": iso_utc(PRIOR_LAST_SIGNAL_HOUR_MS),
            "latest_complete_signal_bar_start_ms": LAST_COMPLETE_SIGNAL_HOUR_MS,
            "latest_complete_signal_bar_start": iso_utc(
                LAST_COMPLETE_SIGNAL_HOUR_MS
            ),
            "new_signal_bar_count": 2,
            "new_realized_payoff_intervals": 1,
            "prior_cumulative_realized_hours": 494,
            "updated_cumulative_realized_hours": 495,
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
            "continue the immutable shadow epoch until exposed payoff observations "
            "accumulate; do not alter lookback, threshold, sizing, fee, or timing"
        ),
    }
    write_outputs(output_dir, result)
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
