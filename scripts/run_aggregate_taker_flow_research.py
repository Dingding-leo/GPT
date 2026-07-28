#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

from gpt_quant import fetch_okx_history_candles

BASE_URL = "https://www.okx.com"
BEGIN = pd.Timestamp("2026-06-28T10:00:00Z")
END = pd.Timestamp("2026-07-28T10:00:00Z")
CANDLE_START = pd.Timestamp("2026-04-01T00:00:00Z")
FEE = 0.0005
ANNUAL_HOURS = 8760.0
LOOKBACK = 168
FLOW_HORIZON = 6
TREND_LOOKBACK = 2160
BLOCK = 24
RESAMPLES = 5000
SEED = 20260728
MARKETS = {"BTC-USDT": "BTC", "ETH-USDT": "ETH"}


def canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def request_bytes(path: str, params: Mapping[str, str], timeout: float = 30.0) -> bytes:
    url = f"{BASE_URL}{path}?{urlencode(params)}"
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "gpt-quant-lab/0.2 (+https://github.com/Dingding-leo/GPT)",
        },
    )
    error: Exception | None = None
    for attempt in range(4):
        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310
                return response.read()
        except HTTPError as exc:
            error = exc
            if exc.code not in {408, 429, 500, 502, 503, 504} or attempt == 3:
                raise RuntimeError(f"OKX HTTP error {exc.code}") from exc
        except (URLError, TimeoutError) as exc:
            error = exc
            if attempt == 3:
                raise RuntimeError("OKX request failed after retries") from exc
        time.sleep(0.5 * (2**attempt))
    raise RuntimeError("OKX request failed") from error


def parse_taker_volume(raw: bytes, *, ccy: str) -> pd.DataFrame:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("taker-volume response is not valid UTF-8 JSON") from exc
    if not isinstance(payload, Mapping) or payload.get("code") != "0":
        raise ValueError(f"taker-volume request failed for {ccy}: {payload!r}")
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise ValueError("taker-volume data must be an array")

    normalized: list[tuple[pd.Timestamp, float, float]] = []
    for number, row in enumerate(rows, start=1):
        if not isinstance(row, Sequence) or isinstance(row, (str, bytes)) or len(row) != 3:
            raise ValueError(f"taker-volume row {number} must be [ts, sellVol, buyVol]")
        ts_raw, sell_raw, buy_raw = row
        if not isinstance(ts_raw, str) or not ts_raw.isascii() or not ts_raw.isdecimal():
            raise ValueError(f"taker-volume row {number} has invalid timestamp")
        timestamp = pd.to_datetime(int(ts_raw), unit="ms", utc=True)
        if timestamp.floor("h") != timestamp:
            raise ValueError(f"taker-volume row {number} is not UTC-hour aligned")
        try:
            sell = float(sell_raw)
            buy = float(buy_raw)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"taker-volume row {number} has invalid volume") from exc
        if not np.isfinite(sell) or not np.isfinite(buy) or sell < 0 or buy < 0:
            raise ValueError(f"taker-volume row {number} has non-finite/negative volume")
        if sell + buy <= 0:
            raise ValueError(f"taker-volume row {number} has zero total volume")
        normalized.append((timestamp, sell, buy))

    frame = pd.DataFrame(normalized, columns=["timestamp", "sell_volume", "buy_volume"])
    frame = frame.sort_values("timestamp", kind="stable").set_index("timestamp")
    validate_flow_grid(frame)
    expected = pd.date_range(BEGIN, END - pd.Timedelta(hours=1), freq="1h")
    frame = frame.loc[(frame.index >= BEGIN) & (frame.index < END)]
    if not frame.index.equals(expected):
        missing = expected.difference(frame.index)
        extra = frame.index.difference(expected)
        raise ValueError(
            f"{ccy} taker-volume grid mismatch: rows={len(frame)}, "
            f"missing={len(missing)}, extra={len(extra)}"
        )
    return frame


def validate_flow_grid(frame: pd.DataFrame) -> None:
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
        raise ValueError("flow index must be timezone-aware")
    if frame.index.has_duplicates:
        raise ValueError("flow index contains duplicate timestamps")
    if not frame.index.is_monotonic_increasing:
        raise ValueError("flow index must be strictly increasing")
    if len(frame) > 1:
        delta = frame.index[1:] - frame.index[:-1]
        if not bool(np.all(delta == pd.Timedelta(hours=1))):
            raise ValueError("flow index must be contiguous 1H")
    required = {"sell_volume", "buy_volume"}
    if set(frame.columns) != required:
        raise ValueError("flow frame has unexpected columns")
    values = frame[["sell_volume", "buy_volume"]].to_numpy(float)
    if not np.isfinite(values).all() or bool((values < 0).any()):
        raise ValueError("flow frame contains invalid volumes")
    if bool((values.sum(axis=1) <= 0).any()):
        raise ValueError("flow frame contains zero-total-volume rows")


def validate_candles(frame: pd.DataFrame) -> None:
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
        raise ValueError("candle index must be timezone-aware")
    if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise ValueError("candle timestamps must be unique and increasing")
    delta = frame.index[1:] - frame.index[:-1]
    if not bool(np.all(delta == pd.Timedelta(hours=1))):
        raise ValueError("candles must be contiguous 1H")
    if "confirm" not in frame or not bool((frame["confirm"].astype(str) == "1").all()):
        raise ValueError("all candles must be confirmed")
    for column in ("open", "high", "low", "close"):
        values = frame[column].to_numpy(float)
        if not np.isfinite(values).all() or bool((values <= 0).any()):
            raise ValueError(f"invalid candle values in {column}")


def shifted_median_and_mad(series: pd.Series, lookback: int) -> tuple[pd.Series, pd.Series]:
    median = series.shift(1).rolling(lookback, min_periods=lookback).median()
    mad_values = np.full(len(series), np.nan, dtype=float)
    values = series.to_numpy(float)
    for index in range(lookback, len(series)):
        history = values[index - lookback : index]
        center = float(np.median(history))
        mad_values[index] = float(np.median(np.abs(history - center)))
    return median, pd.Series(mad_values, index=series.index, name="mad")


def build_targets(flow: pd.DataFrame, candles: pd.DataFrame) -> pd.DataFrame:
    common = flow.join(candles[["close"]], how="inner")
    if not common.index.equals(flow.index):
        raise ValueError("flow and candle grids do not align exactly")
    total = common.buy_volume + common.sell_volume
    common["imbalance"] = (common.buy_volume - common.sell_volume) / total
    signed6 = (common.buy_volume - common.sell_volume).rolling(FLOW_HORIZON).sum()
    total6 = total.rolling(FLOW_HORIZON).sum()
    common["flow6"] = signed6 / total6
    median, mad = shifted_median_and_mad(common.flow6, LOOKBACK)
    z_flow = (common.flow6 - median) / mad
    common["d0_target"] = np.maximum(0.0, np.tanh(z_flow)).where(mad > 0, 0.0)

    same_hour_return = common.close.pct_change()
    residual_z = np.full(len(common), np.nan, dtype=float)
    x = common.imbalance.to_numpy(float)
    y = same_hour_return.to_numpy(float)
    for index in range(LOOKBACK + 1, len(common)):
        history_x = x[index - LOOKBACK : index]
        history_y = y[index - LOOKBACK : index]
        if not np.isfinite(history_x).all() or not np.isfinite(history_y).all():
            continue
        design = np.column_stack([np.ones(LOOKBACK), history_x])
        coefficients, *_ = np.linalg.lstsq(design, history_y, rcond=None)
        fitted = design @ coefficients
        residuals = history_y - fitted
        scale = float(np.median(np.abs(residuals - np.median(residuals))))
        if not np.isfinite(scale) or scale <= 0:
            continue
        current = y[index] - float(coefficients[0] + coefficients[1] * x[index])
        residual_z[index] = current / scale
    common["residual_z"] = residual_z
    resilience = common.residual_z.rolling(FLOW_HORIZON, min_periods=FLOW_HORIZON).mean()
    common["d1_target"] = np.maximum(0.0, np.tanh(resilience)).fillna(0.0)

    trend = common.close / candles.close.shift(TREND_LOOKBACK).reindex(common.index) - 1.0
    common["trend_target"] = (trend > 0).astype(float)
    common["next_return"] = candles.close.shift(-1).reindex(common.index) / common.close - 1.0
    return common


def strategy_path(target: pd.Series, next_return: pd.Series, evaluation: pd.Index) -> pd.DataFrame:
    position = target.reindex(evaluation).astype(float)
    market_return = next_return.reindex(evaluation).astype(float)
    if not np.isfinite(position).all() or not np.isfinite(market_return).all():
        raise ValueError("strategy evaluation contains unavailable values")
    previous = np.r_[0.0, position.to_numpy()[:-1]]
    turnover = np.abs(position.to_numpy() - previous)
    gross = position.to_numpy() * market_return.to_numpy()
    fee = FEE * turnover
    return pd.DataFrame(
        {
            "position": position.to_numpy(),
            "market_return": market_return.to_numpy(),
            "gross_return": gross,
            "turnover": turnover,
            "fee": fee,
            "net_return": gross - fee,
        },
        index=evaluation,
    )


def sharpe(values: np.ndarray) -> float:
    standard_deviation = float(np.std(values, ddof=1))
    if standard_deviation <= 0:
        return 0.0
    return float(np.mean(values) / standard_deviation * math.sqrt(ANNUAL_HOURS))


def max_drawdown(values: np.ndarray) -> float:
    wealth = np.cumprod(1.0 + values)
    return float(np.min(wealth / np.maximum.accumulate(wealth) - 1.0))


def edge_per_turnover(values: np.ndarray, turnover: np.ndarray) -> float | None:
    annual_turnover = float(np.sum(turnover) / (len(values) / ANNUAL_HOURS))
    if annual_turnover <= 0:
        return None
    annual_mean = float(np.mean(values) * ANNUAL_HOURS)
    return float(annual_mean / annual_turnover * 1e4)


def path_metrics(path: pd.DataFrame) -> dict[str, object]:
    values = path.net_return.to_numpy(float)
    turnover = path.turnover.to_numpy(float)
    block_returns = []
    for start in range(0, len(path) - LOOKBACK + 1, LOOKBACK):
        block_returns.append(float(np.prod(1.0 + values[start : start + LOOKBACK]) - 1.0))
    positive = [value for value in block_returns if value > 0]
    concentration = max(positive) / sum(positive) if positive else None
    rolling_24h = pd.Series(values).rolling(24).apply(lambda x: np.prod(1.0 + x) - 1.0)
    years = len(path) / ANNUAL_HOURS
    return {
        "observations": len(path),
        "gross_return": float(np.prod(1.0 + path.gross_return.to_numpy(float)) - 1.0),
        "net_return": float(np.prod(1.0 + values) - 1.0),
        "annualized_arithmetic_mean": float(np.mean(values) * ANNUAL_HOURS),
        "annualized_sharpe": sharpe(values),
        "max_drawdown": max_drawdown(values),
        "absolute_turnover": float(np.sum(turnover)),
        "annualized_turnover": float(np.sum(turnover) / years),
        "modeled_fee_sum": float(np.sum(path.fee)),
        "edge_per_turnover_bps": edge_per_turnover(values, turnover),
        "mean_exposure": float(np.mean(path.position)),
        "adjustment_count": int(np.count_nonzero(turnover > 1e-15)),
        "profitable_168h_blocks": int(sum(value > 0 for value in block_returns)),
        "complete_168h_blocks": len(block_returns),
        "positive_block_concentration": concentration,
        "worst_24h_return": float(rolling_24h.min()),
    }


def residual_sharpe(candidate: pd.DataFrame, benchmark: pd.DataFrame) -> float:
    return sharpe(candidate.net_return.to_numpy(float) - benchmark.net_return.to_numpy(float))


def bootstrap_indices(length: int, rng: np.random.Generator) -> np.ndarray:
    blocks: list[np.ndarray] = []
    while sum(len(block) for block in blocks) < length:
        start = int(rng.integers(0, length - BLOCK + 1))
        blocks.append(np.arange(start, start + BLOCK))
    return np.concatenate(blocks)[:length]


def holm_adjust(raw: dict[str, float]) -> dict[str, float]:
    ordered = sorted(raw.items(), key=lambda item: item[1])
    adjusted: dict[str, float] = {}
    running = 0.0
    for index, (name, value) in enumerate(ordered):
        running = max(running, min(1.0, (len(ordered) - index) * value))
        adjusted[name] = running
    return adjusted


def bootstrap(paths: dict[str, dict[str, pd.DataFrame]]) -> dict[str, object]:
    rng = np.random.default_rng(SEED)
    length = len(next(iter(paths.values()))["d1"])
    samples: dict[str, list[float]] = {
        "d1_minus_d0_sharpe": [],
        "d1_minus_d0_edge": [],
        "d1_minus_trend_sharpe": [],
        "d1_minus_trend_edge": [],
    }
    undefined = {name: 0 for name in samples}
    for _ in range(RESAMPLES):
        indices = bootstrap_indices(length, rng)
        market_values: dict[str, list[float]] = {name: [] for name in samples}
        for policies in paths.values():
            resampled = {name: frame.iloc[indices] for name, frame in policies.items()}
            d1 = resampled["d1"]
            d0 = resampled["d0"]
            trend = resampled["trend"]
            market_values["d1_minus_d0_sharpe"].append(
                sharpe(d1.net_return.to_numpy()) - sharpe(d0.net_return.to_numpy())
            )
            market_values["d1_minus_trend_sharpe"].append(
                sharpe(d1.net_return.to_numpy()) - sharpe(trend.net_return.to_numpy())
            )
            d1_edge = edge_per_turnover(d1.net_return.to_numpy(), d1.turnover.to_numpy())
            d0_edge = edge_per_turnover(d0.net_return.to_numpy(), d0.turnover.to_numpy())
            trend_edge = edge_per_turnover(
                trend.net_return.to_numpy(), trend.turnover.to_numpy()
            )
            if d1_edge is None or d0_edge is None:
                market_values["d1_minus_d0_edge"].append(float("nan"))
            else:
                market_values["d1_minus_d0_edge"].append(d1_edge - d0_edge)
            if d1_edge is None or trend_edge is None:
                market_values["d1_minus_trend_edge"].append(float("nan"))
            else:
                market_values["d1_minus_trend_edge"].append(d1_edge - trend_edge)
        for name, values in market_values.items():
            array = np.asarray(values, dtype=float)
            if not np.isfinite(array).all():
                undefined[name] += 1
                continue
            samples[name].append(float(np.min(array)))

    raw_p: dict[str, float] = {}
    endpoints: dict[str, object] = {}
    for name, values in samples.items():
        array = np.asarray(values, dtype=float)
        if len(array) != RESAMPLES:
            endpoints[name] = {
                "valid_resamples": len(array),
                "undefined_resamples": undefined[name],
                "one_sided_95pct_lower_bound": None,
                "raw_p": None,
            }
            continue
        lower = float(np.quantile(array, 0.05))
        raw = float((1 + np.count_nonzero(array <= 0)) / (RESAMPLES + 1))
        raw_p[name] = raw
        endpoints[name] = {
            "valid_resamples": len(array),
            "undefined_resamples": undefined[name],
            "one_sided_95pct_lower_bound": lower,
            "raw_p": raw,
        }
    adjusted = holm_adjust(raw_p)
    for name, value in adjusted.items():
        endpoints[name]["holm_adjusted_p"] = value
    return {
        "block_hours": BLOCK,
        "resamples": RESAMPLES,
        "seed": SEED,
        "endpoints": endpoints,
    }


def run_causal_attacks(flow: pd.DataFrame, candles: pd.DataFrame) -> dict[str, bool]:
    validate_flow_grid(flow)
    duplicate = pd.concat([flow, flow.iloc[[-1]]]).sort_index(kind="stable")
    gap = flow.drop(flow.index[len(flow) // 2])
    shuffled = flow.iloc[::-1]
    failures = []
    for altered in (duplicate, gap, shuffled):
        try:
            validate_flow_grid(altered)
        except ValueError:
            failures.append(True)
        else:
            failures.append(False)

    original = build_targets(flow, candles)
    cutoff = flow.index[-120]
    mutated = flow.copy()
    suffix = mutated.index > cutoff
    mutated.loc[suffix, "buy_volume"] *= 1.37
    mutated.loc[suffix, "sell_volume"] *= 0.73
    changed = build_targets(mutated, candles)
    prefix = original.index <= cutoff
    invariant = bool(
        np.allclose(
            original.loc[prefix, ["d0_target", "d1_target"]],
            changed.loc[prefix, ["d0_target", "d1_target"]],
            atol=0.0,
            rtol=0.0,
        )
    )
    return {
        "duplicate_rejected": failures[0],
        "gap_rejected": failures[1],
        "shuffle_rejected": failures[2],
        "future_suffix_invariance": invariant,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    paths: dict[str, dict[str, pd.DataFrame]] = {}
    result: dict[str, object] = {
        "family_id": "okx-aggregate-spot-taker-flow-resilience-v1",
        "issue": 566,
        "source_head_sha": "fda3c8cc5fe8c1902ce7fbaf3fe51edd5c337791",
        "window": {"begin": BEGIN.isoformat(), "end_exclusive": END.isoformat()},
        "candidate_count": 2,
        "fee_one_way_bps": 5.0,
        "markets": {},
    }

    for instrument, ccy in MARKETS.items():
        raw = request_bytes(
            "/api/v5/rubik/stat/taker-volume",
            {
                "instType": "SPOT",
                "ccy": ccy,
                "period": "1H",
                "begin": str(int(BEGIN.timestamp() * 1000)),
                "end": str(int(END.timestamp() * 1000)),
            },
        )
        raw_path = args.output_dir / f"{instrument}-taker-volume.raw.json"
        raw_path.write_bytes(raw)
        flow = parse_taker_volume(raw, ccy=ccy)
        snapshot = fetch_okx_history_candles(
            inst_id=instrument,
            bar="1H",
            start=CANDLE_START,
            end=END,
            base_url=BASE_URL,
            limit=100,
            max_pages=40,
            pause_seconds=0.15,
            timeout=30.0,
        )
        candles = snapshot.candles.copy()
        validate_candles(candles)
        features = build_targets(flow, candles)
        valid = features.index[
            features.d0_target.notna()
            & features.d1_target.notna()
            & features.next_return.notna()
            & (features.index >= BEGIN + pd.Timedelta(hours=LOOKBACK + FLOW_HORIZON - 1))
        ]
        if len(valid) < 500:
            raise ValueError(f"{instrument} has insufficient fixed evaluation coverage: {len(valid)}")
        d0 = strategy_path(features.d0_target, features.next_return, valid)
        d1 = strategy_path(features.d1_target, features.next_return, valid)
        trend = strategy_path(features.trend_target, features.next_return, valid)
        paths[instrument] = {"d0": d0, "d1": d1, "trend": trend}
        checks = run_causal_attacks(flow, candles)
        if not all(checks.values()):
            raise ValueError(f"{instrument} causal attack failed: {checks}")
        market_result = {
            "flow_rows": len(flow),
            "feature_missingness": {
                "d0": int(features.d0_target.isna().sum()),
                "d1": int(features.d1_target.isna().sum()),
            },
            "evaluation_start": valid[0].isoformat(),
            "evaluation_end": valid[-1].isoformat(),
            "evaluation_rows": len(valid),
            "raw_taker_response_sha256": sha256_bytes(raw),
            "canonical_flow_sha256": sha256_bytes(
                flow.reset_index().to_csv(index=False, lineterminator="\n").encode()
            ),
            "candle_raw_pages_sha256": sha256_bytes(canonical_json(snapshot.raw_pages)),
            "candle_metadata_sha256": sha256_bytes(canonical_json(snapshot.metadata)),
            "causal_attacks": checks,
            "policies": {
                "d0_signed_flow_persistence": path_metrics(d0),
                "d1_flow_response_residual": path_metrics(d1),
                "simple_trend_2160h": path_metrics(trend),
            },
            "benchmark_residual_sharpe": {
                "d0_minus_simple_trend": residual_sharpe(d0, trend),
                "d1_minus_simple_trend": residual_sharpe(d1, trend),
            },
        }
        result["markets"][instrument] = market_result

    result["bootstrap"] = bootstrap(paths)
    gates = []
    for market in MARKETS:
        policies = result["markets"][market]["policies"]
        d1_metrics = policies["d1_flow_response_residual"]
        trend_metrics = policies["simple_trend_2160h"]
        blocks = d1_metrics["complete_168h_blocks"]
        profitable = d1_metrics["profitable_168h_blocks"]
        gates.extend(
            [
                d1_metrics["net_return"] > 0,
                d1_metrics["annualized_sharpe"] > 0,
                d1_metrics["edge_per_turnover_bps"] is not None
                and d1_metrics["edge_per_turnover_bps"] > 0,
                blocks < 3 or profitable >= 2,
                result["markets"][market]["benchmark_residual_sharpe"][
                    "d1_minus_simple_trend"
                ]
                > 0,
                trend_metrics["edge_per_turnover_bps"] is not None
                and d1_metrics["edge_per_turnover_bps"]
                > trend_metrics["edge_per_turnover_bps"],
            ]
        )
    endpoint_gates = []
    for endpoint in result["bootstrap"]["endpoints"].values():
        endpoint_gates.append(
            endpoint.get("one_sided_95pct_lower_bound") is not None
            and endpoint["one_sided_95pct_lower_bound"] > 0
            and endpoint.get("holm_adjusted_p", 1.0) < 0.05
        )
    supported = all(gates) and all(endpoint_gates)
    result["verdict"] = (
        "diagnostic_supported_for_archive_attribution_only"
        if supported
        else "aggregate_taker_flow_family_rejected_exact_window"
    )
    result["dsr"] = None
    result["pbo"] = None
    result["untouched_archive_consumed"] = False

    output = canonical_json(result)
    (args.output_dir / "result-summary.json").write_bytes(output)
    (args.output_dir / "result-summary.sha256").write_text(
        f"{sha256_bytes(output)}  result-summary.json\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
