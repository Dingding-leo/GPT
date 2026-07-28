from __future__ import annotations

import argparse
import hashlib
import json
import math
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from gpt_quant.okx_1h import fetch_okx_one_hour_candles

BASE_URL = "https://www.okx.com"
QUAL_START = pd.Timestamp("2023-04-25T00:00:00Z")
QUAL_END = pd.Timestamp("2023-07-23T23:00:00Z")
EVAL_START = pd.Timestamp("2023-07-24T00:00:00Z")
EVAL_END = pd.Timestamp("2026-07-07T23:00:00Z")
LISTED_BEFORE = pd.Timestamp("2022-01-01T00:00:00Z")
LOOKBACK = 2160
FOLD_HOURS = 2160
FOLDS = 12
FEE_BPS = 5.0
ANNUALIZATION = 8760
LIQUIDITY_THRESHOLD = 10_000_000.0
BOOTSTRAP_BLOCK = 168
BOOTSTRAP_RESAMPLES = 5000
BOOTSTRAP_SEED = 20260728
STABLE_BASES = {"USDT", "USDC", "DAI", "TUSD", "USDP", "FDUSD", "EURT", "EUR", "USD"}

POLICY_SPEC = {
    "bar": "1H",
    "fee_bps_one_way": FEE_BPS,
    "initial_position": 0.0,
    "lookback_hours": LOOKBACK,
    "position_rule": "long iff close_t / close_t_minus_2160 - 1 > 0, else cash",
    "execution_delay_hours": 1,
    "position_set": [0.0, 1.0],
    "fold_boundary_reset": False,
}


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def write_json(path: Path, value: Any) -> str:
    payload = canonical_json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return sha256_bytes(payload)


def fetch_public_json(path: str, params: dict[str, str], timeout: float = 30.0) -> tuple[Any, bytes, str]:
    url = BASE_URL + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "GPT-independent-replication/1"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read(5_000_001)
    if not raw or len(raw) > 5_000_000:
        raise ValueError("public response is empty or exceeds the bounded byte limit")
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict) or value.get("code") != "0" or not isinstance(value.get("data"), list):
        raise ValueError(f"unexpected OKX public response from {path}")
    return value, raw, url


def normalize_snapshot_frame(candles: pd.DataFrame) -> pd.DataFrame:
    frame = candles.copy()
    frame.index = pd.DatetimeIndex(frame.index).tz_convert("UTC")
    frame.index.name = "timestamp"
    return frame.sort_index()


def persist_snapshot(root: Path, inst_id: str, label: str, snapshot: Any) -> dict[str, Any]:
    directory = root / "data" / inst_id / label
    directory.mkdir(parents=True, exist_ok=True)
    frame = normalize_snapshot_frame(snapshot.candles)
    csv_bytes = frame.reset_index().to_csv(index=False, lineterminator="\n").encode("utf-8")
    raw_bytes = canonical_json_bytes(list(snapshot.raw_pages))
    metadata_bytes = canonical_json_bytes(dict(snapshot.metadata))
    (directory / "candles.csv").write_bytes(csv_bytes)
    (directory / "raw-pages.json").write_bytes(raw_bytes)
    (directory / "metadata.json").write_bytes(metadata_bytes)
    return {
        "rows": int(len(frame)),
        "start": frame.index[0].isoformat(),
        "end": frame.index[-1].isoformat(),
        "candles_csv_sha256": sha256_bytes(csv_bytes),
        "raw_pages_sha256": sha256_bytes(raw_bytes),
        "metadata_sha256": sha256_bytes(metadata_bytes),
    }


def instrument_candidates(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: str(item.get("instId", ""))):
        inst_id = str(row.get("instId", ""))
        base = str(row.get("baseCcy", ""))
        quote = str(row.get("quoteCcy", ""))
        reason: str | None = None
        try:
            list_time = pd.Timestamp(int(str(row.get("listTime", "0"))), unit="ms", tz="UTC")
        except (TypeError, ValueError, OverflowError):
            list_time = pd.NaT
        if row.get("instType") != "SPOT":
            reason = "not_spot"
        elif row.get("state") != "live":
            reason = "not_live"
        elif quote != "USDT":
            reason = "not_usdt_quoted"
        elif inst_id in {"BTC-USDT", "ETH-USDT"}:
            reason = "development_market_excluded"
        elif base in STABLE_BASES:
            reason = "stable_or_fiat_base_excluded"
        elif pd.isna(list_time):
            reason = "invalid_list_time"
        elif list_time >= LISTED_BEFORE:
            reason = "listed_after_cutoff"
        item = {
            "inst_id": inst_id,
            "base_ccy": base,
            "quote_ccy": quote,
            "state": row.get("state"),
            "list_time": None if pd.isna(list_time) else list_time.isoformat(),
        }
        if reason is None:
            candidates.append(item)
        else:
            item["reason"] = reason
            rejected.append(item)
    return candidates, rejected


def qualification_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    expected = int((QUAL_END - QUAL_START) / pd.Timedelta(hours=1)) + 1
    exact_grid = pd.date_range(QUAL_START, QUAL_END, freq="h")
    complete = len(frame) == expected and frame.index.equals(exact_grid)
    volume_col = "volume_quote_alt" if "volume_quote_alt" in frame.columns else "volume_quote"
    daily = frame[volume_col].astype(float).groupby(frame.index.floor("D")).sum()
    median_daily = float(daily.median()) if len(daily) else float("nan")
    return {
        "complete_hourly_grid": bool(complete),
        "observations": int(len(frame)),
        "expected_observations": expected,
        "median_utc_daily_quote_volume": median_daily,
        "liquidity_pass": bool(math.isfinite(median_daily) and median_daily >= LIQUIDITY_THRESHOLD),
    }


def compound_return(values: pd.Series | np.ndarray) -> float:
    arr = np.asarray(values, dtype=float)
    return float(np.prod(1.0 + arr) - 1.0)


def sharpe(values: pd.Series | np.ndarray) -> float:
    arr = np.asarray(values, dtype=float)
    if len(arr) < 2:
        return 0.0
    std = float(np.std(arr, ddof=1))
    return 0.0 if std <= 0.0 else float(np.mean(arr) / std * math.sqrt(ANNUALIZATION))


def max_drawdown(values: pd.Series | np.ndarray) -> float:
    nav = np.cumprod(1.0 + np.asarray(values, dtype=float))
    if not len(nav):
        return 0.0
    peaks = np.maximum.accumulate(nav)
    return float(np.min(nav / peaks - 1.0))


def worst_window(values: pd.Series, hours: int) -> float:
    rolling = (1.0 + values).rolling(hours).apply(np.prod, raw=True) - 1.0
    return float(rolling.min()) if rolling.notna().any() else 0.0


def build_strategy_frame(frame: pd.DataFrame) -> pd.DataFrame:
    close = frame["close"].astype(float)
    asset_return = close.pct_change().fillna(0.0)
    trailing = close.pct_change(LOOKBACK)
    target = (trailing > 0.0).astype(float)
    position = target.shift(1).fillna(0.0)
    full_turnover = position.diff().abs().fillna(position.abs())
    result = pd.DataFrame(
        {
            "close": close,
            "asset_return": asset_return,
            "target": target,
            "position": position,
            "turnover": full_turnover,
        }
    ).loc[EVAL_START:EVAL_END].copy()
    if len(result) != FOLD_HOURS * FOLDS:
        raise ValueError(f"evaluation window has {len(result)} rows, expected {FOLD_HOURS * FOLDS}")
    # Evaluation begins from cash, but subsequent fold/year slices preserve the actual continuous path.
    first = result.index[0]
    result.at[first, "turnover"] = abs(float(result.at[first, "position"]))
    result["gross_return"] = result["position"] * result["asset_return"]
    result["fee"] = result["turnover"] * FEE_BPS / 10_000.0
    result["net_return"] = result["gross_return"] - result["fee"]

    buy_hold_position = pd.Series(1.0, index=result.index)
    buy_hold_turnover = buy_hold_position.diff().abs().fillna(1.0)
    result["buy_hold_return"] = (
        buy_hold_position * result["asset_return"] - buy_hold_turnover * FEE_BPS / 10_000.0
    )
    result["residual_return"] = result["net_return"] - result["buy_hold_return"]
    result["fold"] = np.repeat(np.arange(1, FOLDS + 1), FOLD_HOURS)
    return result


def summarize_strategy(result: pd.DataFrame) -> dict[str, Any]:
    hours = len(result)
    years = hours / ANNUALIZATION
    total_turnover = float(result["turnover"].sum())
    net_sum = float(result["net_return"].sum())
    fold_returns = [compound_return(group["net_return"]) for _, group in result.groupby("fold", sort=True)]
    positive = [value for value in fold_returns if value > 0.0]
    concentration = max(positive) / sum(positive) if positive else None
    year_returns = {
        str(int(year)): compound_return(group["net_return"])
        for year, group in result.groupby(result.index.year, sort=True)
    }
    return {
        "observations": hours,
        "net_total_return": compound_return(result["net_return"]),
        "gross_total_return": compound_return(result["gross_return"]),
        "net_sharpe": sharpe(result["net_return"]),
        "max_drawdown": max_drawdown(result["net_return"]),
        "annualized_turnover": total_turnover / years,
        "total_turnover": total_turnover,
        "modeled_fee_sum": float(result["fee"].sum()),
        "net_edge_per_turnover_bps": None if total_turnover == 0.0 else net_sum / total_turnover * 10_000.0,
        "time_in_market": float(result["position"].mean()),
        "position_changes": int((result["turnover"] > 0.0).sum()),
        "profitable_folds": int(sum(value > 0.0 for value in fold_returns)),
        "fold_returns": fold_returns,
        "largest_positive_fold_share": concentration,
        "profitable_years": int(sum(value > 0.0 for value in year_returns.values())),
        "year_returns": year_returns,
        "worst_24h_return": worst_window(result["net_return"], 24),
        "worst_168h_return": worst_window(result["net_return"], 168),
        "buy_hold_total_return": compound_return(result["buy_hold_return"]),
        "buy_hold_sharpe": sharpe(result["buy_hold_return"]),
        "buy_hold_residual_sharpe": sharpe(result["residual_return"]),
    }


def bootstrap_median_annualized_mean(returns: pd.DataFrame) -> dict[str, Any]:
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    arrays = returns.to_numpy(dtype=float)
    samples = np.empty(BOOTSTRAP_RESAMPLES, dtype=float)
    fold_starts = np.arange(0, len(returns), FOLD_HOURS)
    valid_start_count = FOLD_HOURS - BOOTSTRAP_BLOCK + 1
    for sample_idx in range(BOOTSTRAP_RESAMPLES):
        pieces: list[np.ndarray] = []
        for fold_start in fold_starts:
            selected: list[np.ndarray] = []
            remaining = FOLD_HOURS
            while remaining > 0:
                offset = int(rng.integers(0, valid_start_count))
                block = arrays[fold_start + offset : fold_start + offset + BOOTSTRAP_BLOCK]
                take = min(remaining, len(block))
                selected.append(block[:take])
                remaining -= take
            pieces.append(np.concatenate(selected, axis=0))
        sampled = np.concatenate(pieces, axis=0)
        annualized_means = np.mean(sampled, axis=0) * ANNUALIZATION
        samples[sample_idx] = float(np.median(annualized_means))
    observed = float(np.median(np.mean(arrays, axis=0) * ANNUALIZATION))
    return {
        "observed_cross_market_median_annualized_mean": observed,
        "percentile_95_interval": [float(np.quantile(samples, 0.025)), float(np.quantile(samples, 0.975))],
        "one_sided_95_lower_bound": float(np.quantile(samples, 0.05)),
        "resamples": BOOTSTRAP_RESAMPLES,
        "block_hours": BOOTSTRAP_BLOCK,
        "seed": BOOTSTRAP_SEED,
        "sampling": (
            "non-circular 168H blocks sampled independently within each fixed 2160H fold; "
            "common indices across markets"
        ),
    }


def finite_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    return float(value) if math.isfinite(float(value)) else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)

    policy_hash = sha256_bytes(canonical_json_bytes(POLICY_SPEC))
    instruments_payload, instruments_raw, instruments_url = fetch_public_json(
        "/api/v5/public/instruments", {"instType": "SPOT"}
    )
    (output / "source").mkdir(parents=True, exist_ok=True)
    (output / "source" / "instruments.raw.json").write_bytes(instruments_raw)
    candidates, instrument_rejections = instrument_candidates(instruments_payload["data"])

    qualification_rows: list[dict[str, Any]] = []
    qualified: list[str] = []
    for candidate in candidates:
        inst_id = candidate["inst_id"]
        row: dict[str, Any] = dict(candidate)
        try:
            snapshot = fetch_okx_one_hour_candles(
                inst_id=inst_id,
                start=QUAL_START,
                end=QUAL_END,
                pause_seconds=0.11,
                timeout=30.0,
            )
            provenance = persist_snapshot(output, inst_id, "qualification", snapshot)
            frame = normalize_snapshot_frame(snapshot.candles)
            metrics = qualification_metrics(frame)
            row.update(metrics)
            row["provenance"] = provenance
            row["qualified"] = bool(metrics["complete_hourly_grid"] and metrics["liquidity_pass"])
            row["reason"] = None if row["qualified"] else "grid_or_liquidity_failure"
            if row["qualified"]:
                qualified.append(inst_id)
        except Exception as exc:  # noqa: BLE001 - every failure must be recorded, not hidden
            row.update(
                {
                    "qualified": False,
                    "reason": "qualification_acquisition_failure",
                    "error": str(exc),
                }
            )
        qualification_rows.append(row)

    frozen_universe = sorted(qualified)
    universe_payload = {
        "family_id": "simple-trend-2160h-independent-replication-v1",
        "policy_sha256": policy_hash,
        "frozen_before_performance": True,
        "universe_type": "current-live survivorship-conditioned",
        "survivorship_limit": (
            "The current public instruments endpoint does not enumerate every historically delisted spot market; "
            "passing results cannot authorize promotion without a delisted-market inventory replication."
        ),
        "instrument_source": {
            "url": instruments_url,
            "raw_sha256": sha256_bytes(instruments_raw),
            "rows": len(instruments_payload["data"]),
        },
        "eligibility": {
            "instrument_type": "SPOT",
            "state": "live",
            "quote_ccy": "USDT",
            "listed_before": LISTED_BEFORE.isoformat(),
            "excluded_development_markets": ["BTC-USDT", "ETH-USDT"],
            "excluded_stable_or_fiat_bases": sorted(STABLE_BASES),
            "qualification_start": QUAL_START.isoformat(),
            "qualification_end": QUAL_END.isoformat(),
            "median_utc_daily_quote_volume_min_usdt": LIQUIDITY_THRESHOLD,
            "complete_hourly_grid_required": True,
        },
        "candidate_instruments": candidates,
        "instrument_filter_rejections": instrument_rejections,
        "qualification_results": qualification_rows,
        "frozen_instruments": frozen_universe,
    }
    universe_hash = write_json(output / "universe.json", universe_payload)

    market_results: dict[str, Any] = {}
    unavailable: list[dict[str, str]] = []
    aligned_returns: dict[str, pd.Series] = {}
    for inst_id in frozen_universe:
        try:
            snapshot = fetch_okx_one_hour_candles(
                inst_id=inst_id,
                start=QUAL_START,
                end=EVAL_END,
                pause_seconds=0.11,
                timeout=30.0,
            )
            provenance = persist_snapshot(output, inst_id, "full", snapshot)
            frame = normalize_snapshot_frame(snapshot.candles)
            expected = int((EVAL_END - QUAL_START) / pd.Timedelta(hours=1)) + 1
            expected_grid = pd.date_range(QUAL_START, EVAL_END, freq="h")
            if len(frame) != expected or not frame.index.equals(expected_grid):
                raise ValueError("full sample is not the exact complete frozen hourly grid")
            strategy = build_strategy_frame(frame)
            # Regression evidence: fold slicing must preserve the already-accounted continuous return path.
            concatenated = pd.concat([group for _, group in strategy.groupby("fold", sort=True)])
            if not np.array_equal(concatenated.index.to_numpy(), strategy.index.to_numpy()):
                raise AssertionError("fold concatenation changed the continuous time ordering")
            if not np.allclose(
                concatenated["net_return"], strategy["net_return"], atol=0.0, rtol=0.0
            ):
                raise AssertionError("fold slicing reset position or fee state")
            market_results[inst_id] = {
                "provenance": provenance,
                "metrics": summarize_strategy(strategy),
            }
            result_csv = strategy.reset_index().to_csv(index=False, lineterminator="\n").encode("utf-8")
            result_path = output / "markets" / inst_id / "strategy_returns.csv"
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_bytes(result_csv)
            market_results[inst_id]["strategy_returns_sha256"] = sha256_bytes(result_csv)
            aligned_returns[inst_id] = strategy["net_return"]
        except Exception as exc:  # noqa: BLE001
            unavailable.append({"inst_id": inst_id, "reason": str(exc)})

    complete_markets = sorted(market_results)
    gate: dict[str, bool] = {}
    metric_list = [market_results[m]["metrics"] for m in complete_markets]
    frozen_count = len(frozen_universe)
    complete_count = len(complete_markets)
    if complete_markets:
        net_returns = [float(m["net_total_return"]) for m in metric_list]
        sharpes = [float(m["net_sharpe"]) for m in metric_list]
        edges = [
            float(m["net_edge_per_turnover_bps"])
            for m in metric_list
            if m["net_edge_per_turnover_bps"] is not None
        ]
        residuals = [float(m["buy_hold_residual_sharpe"]) for m in metric_list]
        pooled = pd.concat(aligned_returns, axis=1).sort_index()
        if pooled.isna().any().any():
            raise ValueError("complete replication markets do not share the exact evaluation grid")
        pooled_returns = pooled.mean(axis=1)
        bootstrap = bootstrap_median_annualized_mean(pooled)
        pooled_metrics = {
            "diagnostic_equal_weight_not_executable": True,
            "net_total_return": compound_return(pooled_returns),
            "net_sharpe": sharpe(pooled_returns),
            "max_drawdown": max_drawdown(pooled_returns),
            "annualized_mean_return": float(pooled_returns.mean() * ANNUALIZATION),
        }
        worst_market = min(
            complete_markets,
            key=lambda market: market_results[market]["metrics"]["net_total_return"],
        )
        worst = {"inst_id": worst_market, **market_results[worst_market]["metrics"]}
    else:
        net_returns = []
        sharpes = []
        edges = []
        residuals = []
        bootstrap = None
        pooled_metrics = None
        worst = None

    gate["at_least_three_complete_markets"] = complete_count >= 3
    gate["all_frozen_markets_materialized"] = complete_count == frozen_count and frozen_count > 0
    gate["two_thirds_positive_net_return"] = (
        frozen_count > 0 and sum(value > 0.0 for value in net_returns) / frozen_count >= 2.0 / 3.0
    )
    gate["positive_median_net_return"] = bool(net_returns and float(np.median(net_returns)) > 0.0)
    gate["positive_median_sharpe"] = bool(sharpes and float(np.median(sharpes)) > 0.0)
    gate["worst_market_above_minus_15pct"] = bool(net_returns and min(net_returns) > -0.15)
    gate["two_thirds_have_six_profitable_folds"] = (
        frozen_count > 0
        and sum(int(m["profitable_folds"]) >= 6 for m in metric_list) / frozen_count >= 2.0 / 3.0
    )
    gate["no_positive_fold_concentration_above_half"] = (
        complete_count == frozen_count
        and all(
            m["largest_positive_fold_share"] is not None
            and float(m["largest_positive_fold_share"]) <= 0.5
            for m in metric_list
        )
    )
    gate["positive_median_edge_per_turnover"] = bool(edges and float(np.median(edges)) > 0.0)
    gate["positive_median_buy_hold_residual_sharpe"] = bool(
        residuals and float(np.median(residuals)) > 0.0
    )
    gate["bootstrap_lower_bound_positive"] = bool(
        bootstrap is not None and bootstrap["one_sided_95_lower_bound"] > 0.0
    )
    gate["causal_reconstruction_and_fee_checks"] = complete_count == frozen_count and complete_count > 0

    passed = all(gate.values())
    verdict = (
        "replication_supported_survivorship_blocked"
        if passed
        else "rejected_as_next_active_architecture"
    )
    result = {
        "schema_version": 1,
        "family_id": "simple-trend-2160h-independent-replication-v1",
        "policy": POLICY_SPEC,
        "policy_sha256": policy_hash,
        "universe_sha256": universe_hash,
        "sample": {
            "warmup_start": QUAL_START.isoformat(),
            "evaluation_start": EVAL_START.isoformat(),
            "evaluation_end": EVAL_END.isoformat(),
            "observations_per_complete_market": FOLD_HOURS * FOLDS,
            "folds": FOLDS,
            "fold_hours": FOLD_HOURS,
        },
        "candidate_count": 1,
        "frozen_universe_count": frozen_count,
        "complete_market_count": complete_count,
        "frozen_universe": frozen_universe,
        "complete_markets": complete_markets,
        "rejected_or_unavailable_markets_without_deletion": unavailable,
        "markets": market_results,
        "pooled": pooled_metrics,
        "worst_market": worst,
        "bootstrap": bootstrap,
        "gate": gate,
        "verdict": verdict,
        "survivorship_classification": (
            "current-live survivorship-conditioned; promotion blocked even on pass"
        ),
        "multiple_testing": {
            "new_family_count": 0,
            "new_candidate_count": 0,
            "rule_is_existing_frozen_benchmark": True,
            "dsr": None,
            "dsr_reason": (
                "repository-wide independently deduplicated architecture count is incomplete"
            ),
            "pbo": None,
            "pbo_reason": "one fixed rule has no valid candidate-by-split selection matrix",
        },
    }

    def clean(value: Any) -> Any:
        if isinstance(value, float):
            return finite_or_none(value)
        if isinstance(value, dict):
            return {str(key): clean(item) for key, item in value.items()}
        if isinstance(value, list):
            return [clean(item) for item in value]
        return value

    result = clean(result)
    result_hash = write_json(output / "result.json", result)
    report = [
        "# Independent 2160H simple-trend replication",
        "",
        f"- Policy SHA-256: `{policy_hash}`",
        f"- Universe SHA-256: `{universe_hash}`",
        f"- Result SHA-256: `{result_hash}`",
        f"- Frozen universe: `{', '.join(frozen_universe) or 'none'}`",
        f"- Complete markets: `{', '.join(complete_markets) or 'none'}`",
        f"- Verdict: `{verdict}`",
        "",
        "The universe is explicitly current-live survivorship-conditioned. A pass cannot authorize promotion.",
    ]
    (output / "README.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "verdict": verdict,
                "policy_sha256": policy_hash,
                "universe": frozen_universe,
                "result_sha256": result_hash,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
