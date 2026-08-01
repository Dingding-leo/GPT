from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import random
import statistics
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

FAMILY_ID = "causal-stablecoin-quote-stress-entry-veto-1h-v1"
SYMBOLS = ("SOLUSDT", "XRPUSDT", "USDCUSDT")
TARGETS = ("SOLUSDT", "XRPUSDT")
INTERVAL = "1h"
ARCHIVE_BASE = "https://data.binance.vision/data/spot/monthly/klines"
START_MS = 1_640_995_200_000
END_MS_EXCLUSIVE = 1_767_225_600_000
EXPECTED_ROWS = 35_064
HOUR_MS = 3_600_000
HORIZON = 2_160
TRAIN_START = 2_160
TRAIN_END = 17_520
OOS_START = 17_520
OOS_END = 34_800
FULL_START = 2_160
FULL_END = 34_800
FOLD_HOURS = 2_160
DECISION_HOUR_UTC = 0
FEE = 0.0005
BOOTSTRAP_BLOCK = 168
BOOTSTRAP_REPS = 5_000
BOOTSTRAP_SEED = 20_260_801
EXPECTED_SOURCE_OBJECTS = 144
EXPECTED_CHECKSUM_OBJECTS = 144
ANNUAL_HOURS = 8_760.0


@dataclass(frozen=True)
class Bar:
    open_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_ms: int


def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000.0, tz=UTC).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def fetch_bytes(url: str, timeout: int = 60) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "prospective-strategy-research/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        final_url = response.geturl()
        if final_url != url:
            raise RuntimeError(f"redirect prohibited: {url} -> {final_url}")
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}: {url}")
        return response.read()


def normalize_timestamp(raw: str, *, require_ms_aligned: bool) -> int:
    value = int(raw)
    if value >= 100_000_000_000_000:
        if require_ms_aligned and value % 1_000:
            raise ValueError(f"microsecond open timestamp not millisecond aligned: {value}")
        value //= 1_000
    return value


def months() -> Iterable[tuple[int, int]]:
    for year in range(2022, 2026):
        for month in range(1, 13):
            yield year, month


def download_sources(output_dir: Path) -> tuple[dict[str, list[Bar]], dict[str, Any]]:
    source_dir = output_dir / "sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    bars_by_symbol: dict[str, list[Bar]] = {}
    manifest_objects: list[dict[str, Any]] = []
    source_count = 0
    checksum_count = 0

    for symbol in SYMBOLS:
        symbol_bars: list[Bar] = []
        for year, month in months():
            stem = f"{symbol}-{INTERVAL}-{year:04d}-{month:02d}.zip"
            url = f"{ARCHIVE_BASE}/{symbol}/{INTERVAL}/{stem}"
            checksum_url = f"{url}.CHECKSUM"
            archive = fetch_bytes(url)
            checksum_bytes = fetch_bytes(checksum_url)
            source_count += 1
            checksum_count += 1
            checksum_text = checksum_bytes.decode("ascii").strip()
            expected_sha = checksum_text.split()[0].lower()
            if len(expected_sha) != 64 or any(c not in "0123456789abcdef" for c in expected_sha):
                raise ValueError(f"invalid checksum object: {checksum_url}")
            archive_sha = sha256_bytes(archive)
            if archive_sha != expected_sha:
                raise ValueError(f"checksum mismatch: {url}")

            archive_path = source_dir / symbol / stem
            checksum_path = source_dir / symbol / f"{stem}.CHECKSUM"
            archive_path.parent.mkdir(parents=True, exist_ok=True)
            archive_path.write_bytes(archive)
            checksum_path.write_bytes(checksum_bytes)

            with zipfile.ZipFile(io.BytesIO(archive)) as zf:
                names = zf.namelist()
                expected_csv = stem.removesuffix(".zip") + ".csv"
                if names != [expected_csv]:
                    raise ValueError(f"unexpected ZIP members for {stem}: {names}")
                payload = zf.read(expected_csv)
            reader = csv.reader(io.TextIOWrapper(io.BytesIO(payload), encoding="utf-8", newline=""))
            rows = 0
            for row in reader:
                if len(row) != 12:
                    raise ValueError(f"unexpected Binance kline width in {stem}: {len(row)}")
                open_ms = normalize_timestamp(row[0], require_ms_aligned=True)
                close_ms = normalize_timestamp(row[6], require_ms_aligned=False)
                values = [float(row[index]) for index in (1, 2, 3, 4, 5)]
                open_price, high, low, close, volume = values
                if not all(math.isfinite(value) for value in values):
                    raise ValueError(f"non-finite kline value in {stem}")
                if min(open_price, high, low, close) <= 0.0 or volume < 0.0:
                    raise ValueError(f"invalid price/volume in {stem}")
                if high < max(open_price, close, low) or low > min(open_price, close, high):
                    raise ValueError(f"invalid OHLC ordering in {stem}")
                if close_ms != open_ms + HOUR_MS - 1:
                    raise ValueError(f"invalid close timestamp in {stem}: {open_ms}, {close_ms}")
                symbol_bars.append(Bar(open_ms, open_price, high, low, close, volume, close_ms))
                rows += 1
            manifest_objects.append(
                {
                    "symbol": symbol,
                    "interval": INTERVAL,
                    "year": year,
                    "month": month,
                    "archive_url": url,
                    "checksum_url": checksum_url,
                    "archive_sha256": archive_sha,
                    "checksum_sha256": sha256_bytes(checksum_bytes),
                    "csv_sha256": sha256_bytes(payload),
                    "rows": rows,
                }
            )
        bars_by_symbol[symbol] = symbol_bars

    if source_count != EXPECTED_SOURCE_OBJECTS or checksum_count != EXPECTED_CHECKSUM_OBJECTS:
        raise ValueError("unexpected source/checksum object count")

    expected_calendar = [START_MS + HOUR_MS * i for i in range(EXPECTED_ROWS)]
    for symbol, bars in bars_by_symbol.items():
        if len(bars) != EXPECTED_ROWS:
            raise ValueError(f"{symbol}: expected {EXPECTED_ROWS} rows, got {len(bars)}")
        timestamps = [bar.open_ms for bar in bars]
        if timestamps != expected_calendar:
            raise ValueError(f"{symbol}: non-contiguous or incorrect calendar")
        if len(set(timestamps)) != EXPECTED_ROWS:
            raise ValueError(f"{symbol}: duplicate timestamps")
        if timestamps[0] != START_MS or timestamps[-1] + HOUR_MS != END_MS_EXCLUSIVE:
            raise ValueError(f"{symbol}: incorrect calendar endpoints")

    common = [[bar.open_ms for bar in bars_by_symbol[symbol]] for symbol in SYMBOLS]
    if not all(calendar == common[0] for calendar in common[1:]):
        raise ValueError("symbols do not share an exact common calendar")

    manifest = {
        "archive_base": ARCHIVE_BASE,
        "symbols": list(SYMBOLS),
        "interval": INTERVAL,
        "source_period": {"start": iso(START_MS), "end_exclusive": iso(END_MS_EXCLUSIVE)},
        "expected_rows_per_symbol": EXPECTED_ROWS,
        "source_object_count": source_count,
        "checksum_object_count": checksum_count,
        "objects": manifest_objects,
    }
    (output_dir / "source_manifest.json").write_bytes(canonical_bytes(manifest))
    return bars_by_symbol, manifest


def decision_indices(start: int, end: int, delay: int = 0) -> list[int]:
    indices = []
    for t in range(start, end):
        if t <= HORIZON:
            continue
        if datetime.fromtimestamp((START_MS + t * HOUR_MS) / 1000.0, tz=UTC).hour != DECISION_HOUR_UTC:
            continue
        execution = t + delay
        if execution < end:
            indices.append(t)
    return indices


def sample_std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    return statistics.stdev(values)


def safe_sharpe(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    sigma = sample_std(values)
    if sigma == 0.0:
        return None
    return statistics.fmean(values) / sigma * math.sqrt(ANNUAL_HOURS)


def compound(values: list[float]) -> float:
    equity = 1.0
    for value in values:
        equity *= 1.0 + value
    return equity - 1.0


def max_drawdown(values: list[float]) -> float:
    equity = 1.0
    peak = 1.0
    worst = 0.0
    for value in values:
        equity *= 1.0 + value
        peak = max(peak, equity)
        worst = min(worst, equity / peak - 1.0)
    return worst


def loss_cluster(positions: list[int], returns: list[float]) -> tuple[int, float | None]:
    exposed = 0
    losses = 0
    run = 0
    longest = 0
    for position, value in zip(positions, returns, strict=True):
        if position:
            exposed += 1
            if value < 0.0:
                losses += 1
                run += 1
                longest = max(longest, run)
            else:
                run = 0
        else:
            run = 0
    return longest, None if exposed == 0 else losses / exposed


def metrics(path: dict[str, Any]) -> dict[str, Any]:
    returns = path["net_returns"]
    positions = path["positions"]
    longest, loss_rate = loss_cluster(positions, returns)
    turnover = float(sum(abs(change) for change in path["changes"]))
    net_compound = compound(returns)
    return {
        "hours": len(returns),
        "compounded_net_return": net_compound,
        "arithmetic_net_return": sum(returns),
        "annualized_hourly_sharpe": safe_sharpe(returns),
        "maximum_drawdown": max_drawdown(returns),
        "exposure_hours": sum(positions),
        "mean_exposure": statistics.fmean(positions) if positions else 0.0,
        "exposure_change_count": sum(1 for change in path["changes"] if change != 0),
        "modeled_fees": sum(path["fees"]),
        "turnover": turnover,
        "edge_per_turnover_bps": None if turnover == 0.0 else net_compound * 10_000.0 / turnover,
        "longest_exposed_loss_cluster_hours": longest,
        "exposed_loss_hour_rate": loss_rate,
    }


def run_strategy(
    target: list[Bar],
    quote: list[Bar],
    start: int,
    end: int,
    kind: str,
    delay: int = 0,
) -> dict[str, Any]:
    if kind not in {"candidate", "b1", "always_long"}:
        raise ValueError(kind)
    signals: dict[int, dict[str, Any]] = {}
    state = 0
    candidate_vetoes: list[dict[str, Any]] = []
    base_entries = 0
    for t in decision_indices(start, end, delay):
        own_margin = math.log(target[t - 1].close / target[t - 2161].close)
        quote_drift = math.log(quote[t - 1].close / quote[t - 2161].close)
        adjusted = own_margin - quote_drift
        if kind == "always_long":
            desired = 1
        elif kind == "b1":
            desired = int(own_margin > 0.0)
            if state == 0 and desired == 1:
                base_entries += 1
        else:
            if state == 0:
                desired = int(own_margin > 0.0 and adjusted > 0.0)
                if own_margin > 0.0:
                    base_entries += 1
                if own_margin > 0.0 and adjusted <= 0.0:
                    candidate_vetoes.append(
                        {
                            "decision_index": t,
                            "decision_time": iso(START_MS + t * HOUR_MS),
                            "own_margin": own_margin,
                            "quote_drift": quote_drift,
                            "adjusted_margin": adjusted,
                        }
                    )
            else:
                desired = int(own_margin > 0.0)
        execution = t + delay
        signals[execution] = {
            "desired": desired,
            "decision_index": t,
            "own_margin": own_margin,
            "quote_drift": quote_drift,
            "adjusted_margin": adjusted,
        }
        state = desired

    position = 0
    net_returns: list[float] = []
    gross_returns: list[float] = []
    positions: list[int] = []
    changes: list[int] = []
    fees: list[float] = []
    hour_indices: list[int] = []
    decision_records: list[dict[str, Any]] = []
    for h in range(start, end - 1):
        change = 0
        if h in signals:
            desired = int(signals[h]["desired"])
            change = desired - position
            position = desired
            decision_records.append({"execution_index": h, "change": change, **signals[h]})
        fee = FEE * abs(change)
        asset_return = target[h + 1].open / target[h].open - 1.0
        gross = position * asset_return
        net = gross - fee
        hour_indices.append(h)
        positions.append(position)
        changes.append(change)
        fees.append(fee)
        gross_returns.append(gross)
        net_returns.append(net)
    return {
        "kind": kind,
        "start_index": start,
        "end_index": end,
        "delay_hours": delay,
        "hour_indices": hour_indices,
        "positions": positions,
        "changes": changes,
        "fees": fees,
        "gross_returns": gross_returns,
        "net_returns": net_returns,
        "decision_records": decision_records,
        "candidate_vetoes": candidate_vetoes,
        "base_positive_entry_decisions": base_entries,
    }


def quantile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("empty quantile")
    index = (len(ordered) - 1) * p
    lo = math.floor(index)
    hi = math.ceil(index)
    if lo == hi:
        return ordered[lo]
    weight = index - lo
    return ordered[lo] * (1.0 - weight) + ordered[hi] * weight


def summary_stats(values: list[float]) -> dict[str, float | int]:
    return {
        "count": len(values),
        "median": statistics.median(values),
        "q1": quantile(values, 0.25),
        "q3": quantile(values, 0.75),
        "iqr": quantile(values, 0.75) - quantile(values, 0.25),
        "positive_rate": sum(value > 0.0 for value in values) / len(values),
    }


def correlation(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    ml = statistics.fmean(left)
    mr = statistics.fmean(right)
    dl = [value - ml for value in left]
    dr = [value - mr for value in right]
    denom = math.sqrt(sum(value * value for value in dl) * sum(value * value for value in dr))
    if denom == 0.0:
        return None
    return sum(a * b for a, b in zip(dl, dr, strict=True)) / denom


def contiguous_episodes(vetoes: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    if not vetoes:
        return []
    episodes: list[list[dict[str, Any]]] = [[vetoes[0]]]
    for veto in vetoes[1:]:
        if veto["decision_index"] - episodes[-1][-1]["decision_index"] == 24:
            episodes[-1].append(veto)
        else:
            episodes.append([veto])
    return episodes


def prefix(values: list[float]) -> list[float]:
    out = [0.0]
    running = 0.0
    for value in values:
        running += value
        out.append(running)
    return out


def block_sum(pref: list[float], start: int, length: int) -> float:
    return pref[start + length] - pref[start]


def bootstrap_delta(
    candidate: list[float],
    benchmark: list[float],
    reps: int = BOOTSTRAP_REPS,
    block: int = BOOTSTRAP_BLOCK,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    if len(candidate) != len(benchmark) or len(candidate) < block:
        raise ValueError("invalid bootstrap inputs")
    n = len(candidate)
    rng = random.Random(seed)
    pc = prefix(candidate)
    pb = prefix(benchmark)
    pc2 = prefix([value * value for value in candidate])
    pb2 = prefix([value * value for value in benchmark])
    mean_deltas: list[float] = []
    sharpe_deltas: list[float] = []
    blocks_needed = math.ceil(n / block)
    for _ in range(reps):
        remaining = n
        sc = sb = sc2 = sb2 = 0.0
        for _block_index in range(blocks_needed):
            length = min(block, remaining)
            start = rng.randrange(0, n - length + 1)
            sc += block_sum(pc, start, length)
            sb += block_sum(pb, start, length)
            sc2 += block_sum(pc2, start, length)
            sb2 += block_sum(pb2, start, length)
            remaining -= length
            if remaining == 0:
                break
        mc = sc / n
        mb = sb / n
        vc = max(0.0, (sc2 - n * mc * mc) / (n - 1))
        vb = max(0.0, (sb2 - n * mb * mb) / (n - 1))
        shc = 0.0 if vc == 0.0 else mc / math.sqrt(vc) * math.sqrt(ANNUAL_HOURS)
        shb = 0.0 if vb == 0.0 else mb / math.sqrt(vb) * math.sqrt(ANNUAL_HOURS)
        mean_deltas.append((mc - mb) * ANNUAL_HOURS)
        sharpe_deltas.append(shc - shb)
    return {
        "repetitions": reps,
        "block_hours": block,
        "seed": seed,
        "annualized_mean_return_delta": {
            "median": statistics.median(mean_deltas),
            "lower_95": quantile(mean_deltas, 0.025),
            "upper_95": quantile(mean_deltas, 0.975),
        },
        "sharpe_delta": {
            "median": statistics.median(sharpe_deltas),
            "lower_95": quantile(sharpe_deltas, 0.025),
            "upper_95": quantile(sharpe_deltas, 0.975),
        },
    }


def slice_path(path: dict[str, Any], start: int, end: int) -> dict[str, Any]:
    selected = [i for i, h in enumerate(path["hour_indices"]) if start <= h < end - 1]
    return {
        key: [path[key][i] for i in selected]
        for key in ("hour_indices", "positions", "changes", "fees", "gross_returns", "net_returns")
    }


def mechanism_diagnostics(
    target: list[Bar], quote: list[Bar], candidate_train: dict[str, Any], candidate_oos: dict[str, Any]
) -> dict[str, Any]:
    def daily_values(start: int, end: int) -> tuple[list[float], list[float]]:
        quote_values: list[float] = []
        own_values: list[float] = []
        for t in decision_indices(start, end):
            own_values.append(math.log(target[t - 1].close / target[t - 2161].close))
            quote_values.append(math.log(quote[t - 1].close / quote[t - 2161].close))
        return quote_values, own_values

    train_quote, train_own = daily_values(TRAIN_START, TRAIN_END)
    oos_quote, oos_own = daily_values(OOS_START, OOS_END)
    train_episodes = contiguous_episodes(candidate_train["candidate_vetoes"])
    oos_episodes = contiguous_episodes(candidate_oos["candidate_vetoes"])
    train_counts = [len(episode) for episode in train_episodes]
    support_count = len(candidate_train["candidate_vetoes"])
    max_share = 0.0 if support_count == 0 else max(train_counts, default=0) / support_count
    return {
        "training_quote_drift": summary_stats(train_quote),
        "oos_quote_drift": summary_stats(oos_quote),
        "training_veto_rate": support_count / max(1, len(train_quote)),
        "oos_veto_rate": len(candidate_oos["candidate_vetoes"]) / max(1, len(oos_quote)),
        "training_quote_target_margin_correlation": correlation(train_quote, train_own),
        "oos_quote_target_margin_correlation": correlation(oos_quote, oos_own),
        "training_affected_decisions": support_count,
        "training_episode_count": len(train_episodes),
        "training_max_episode_decision_share": max_share,
        "oos_affected_decisions": len(candidate_oos["candidate_vetoes"]),
        "oos_episode_count": len(oos_episodes),
        "training_support_pass": support_count >= 20 and len(train_episodes) >= 3 and max_share <= 0.5,
        "training_episodes": [
            {
                "start": episode[0]["decision_time"],
                "end": episode[-1]["decision_time"],
                "affected_decisions": len(episode),
            }
            for episode in train_episodes
        ],
        "oos_episodes": [
            {
                "start": episode[0]["decision_time"],
                "end": episode[-1]["decision_time"],
                "affected_decisions": len(episode),
            }
            for episode in oos_episodes
        ],
    }


def path_identity(candidate: dict[str, Any], benchmark: dict[str, Any]) -> dict[str, Any]:
    direct = sum(candidate["net_returns"]) - sum(benchmark["net_returns"])
    gross_difference = sum(candidate["gross_returns"]) - sum(benchmark["gross_returns"])
    fee_difference = sum(candidate["fees"]) - sum(benchmark["fees"])
    reconstructed = gross_difference - fee_difference
    error = direct - reconstructed
    return {
        "candidate_minus_b1_arithmetic_net": direct,
        "gross_exposure_return_difference": gross_difference,
        "modeled_fee_difference": fee_difference,
        "reconstructed_difference": reconstructed,
        "identity_error": error,
        "identity_pass": abs(error) <= 1e-12,
        "differing_exposure_hours": sum(
            pc != pb for pc, pb in zip(candidate["positions"], benchmark["positions"], strict=True)
        ),
    }


def evaluate_target(target_symbol: str, bars: dict[str, list[Bar]]) -> dict[str, Any]:
    target = bars[target_symbol]
    quote = bars["USDCUSDT"]
    segments = {
        "training": (TRAIN_START, TRAIN_END),
        "oos": (OOS_START, OOS_END),
        "full": (FULL_START, FULL_END),
    }
    paths: dict[str, dict[str, dict[str, Any]]] = {}
    segment_metrics: dict[str, Any] = {}
    for segment, (start, end) in segments.items():
        paths[segment] = {
            kind: run_strategy(target, quote, start, end, kind)
            for kind in ("candidate", "b1", "always_long")
        }
        segment_metrics[segment] = {
            kind: metrics(path) for kind, path in paths[segment].items()
        }
        segment_metrics[segment]["candidate_minus_b1_identity"] = path_identity(
            paths[segment]["candidate"], paths[segment]["b1"]
        )

    delayed_candidate = run_strategy(target, quote, OOS_START, OOS_END, "candidate", delay=1)
    delayed_b1 = run_strategy(target, quote, OOS_START, OOS_END, "b1", delay=1)
    delayed = {
        "candidate": metrics(delayed_candidate),
        "b1": metrics(delayed_b1),
        "identity": path_identity(delayed_candidate, delayed_b1),
    }

    oos_candidate = paths["oos"]["candidate"]
    oos_b1 = paths["oos"]["b1"]
    folds: list[dict[str, Any]] = []
    for fold in range(8):
        start = OOS_START + fold * FOLD_HOURS
        end = start + FOLD_HOURS
        c_slice = slice_path(oos_candidate, start, end)
        b_slice = slice_path(oos_b1, start, end)
        c_return = compound(c_slice["net_returns"])
        b_return = compound(b_slice["net_returns"])
        folds.append(
            {
                "fold": fold + 1,
                "start": iso(START_MS + start * HOUR_MS),
                "end_exclusive": iso(START_MS + end * HOUR_MS),
                "candidate_net_return": c_return,
                "b1_net_return": b_return,
                "candidate_minus_b1": c_return - b_return,
            }
        )

    years: dict[str, Any] = {}
    for year in (2024, 2025):
        selected = [
            i
            for i, h in enumerate(oos_candidate["hour_indices"])
            if datetime.fromtimestamp((START_MS + h * HOUR_MS) / 1000.0, tz=UTC).year == year
        ]
        c_values = [oos_candidate["net_returns"][i] for i in selected]
        b_values = [oos_b1["net_returns"][i] for i in selected]
        c_ret = compound(c_values)
        b_ret = compound(b_values)
        years[str(year)] = {
            "hours": len(selected),
            "candidate_net_return": c_ret,
            "b1_net_return": b_ret,
            "candidate_minus_b1": c_ret - b_ret,
        }

    positive_folds = [fold for fold in folds if fold["candidate_net_return"] > 0.0]
    positive_sum = sum(fold["candidate_net_return"] for fold in positive_folds)
    concentration = (
        None
        if positive_sum <= 0.0
        else max(fold["candidate_net_return"] for fold in positive_folds) / positive_sum
    )
    bootstrap = bootstrap_delta(oos_candidate["net_returns"], oos_b1["net_returns"])
    mechanism = mechanism_diagnostics(
        target, quote, paths["training"]["candidate"], paths["oos"]["candidate"]
    )

    oos_c = segment_metrics["oos"]["candidate"]
    oos_b = segment_metrics["oos"]["b1"]
    full_c = segment_metrics["full"]["candidate"]
    gates = {
        "positive_oos_full_and_sharpe": (
            oos_c["compounded_net_return"] > 0.0
            and full_c["compounded_net_return"] > 0.0
            and (oos_c["annualized_hourly_sharpe"] or -math.inf) > 0.0
        ),
        "strictly_superior_oos_net_and_sharpe": (
            oos_c["compounded_net_return"] > oos_b["compounded_net_return"]
            and (oos_c["annualized_hourly_sharpe"] or -math.inf)
            > (oos_b["annualized_hourly_sharpe"] or -math.inf)
        ),
        "drawdown_no_worse": oos_c["maximum_drawdown"] >= oos_b["maximum_drawdown"],
        "turnover_and_edge": (
            oos_c["turnover"] <= oos_b["turnover"]
            and oos_c["edge_per_turnover_bps"] is not None
            and oos_b["edge_per_turnover_bps"] is not None
            and oos_c["edge_per_turnover_bps"] > oos_b["edge_per_turnover_bps"]
        ),
        "positive_uncertainty_lower_bounds": (
            bootstrap["annualized_mean_return_delta"]["lower_95"] > 0.0
            and bootstrap["sharpe_delta"]["lower_95"] > 0.0
        ),
        "fold_breadth": (
            sum(fold["candidate_net_return"] > 0.0 for fold in folds) >= 5
            and sum(fold["candidate_minus_b1"] > 0.0 for fold in folds) >= 5
        ),
        "year_breadth": all(
            values["candidate_net_return"] > 0.0 and values["candidate_minus_b1"] > 0.0
            for values in years.values()
        ),
        "positive_fold_concentration": concentration is not None and concentration <= 0.5,
        "training_support": mechanism["training_support_pass"],
        "delay_transport": (
            delayed["candidate"]["compounded_net_return"] > 0.0
            and (delayed["candidate"]["annualized_hourly_sharpe"] or -math.inf) > 0.0
            and delayed["candidate"]["compounded_net_return"]
            >= delayed["b1"]["compounded_net_return"]
            and (delayed["candidate"]["annualized_hourly_sharpe"] or -math.inf)
            >= (delayed["b1"]["annualized_hourly_sharpe"] or -math.inf)
        ),
        "identities": all(
            segment_metrics[segment]["candidate_minus_b1_identity"]["identity_pass"]
            for segment in segments
        )
        and delayed["identity"]["identity_pass"],
    }
    passed = all(gates.values())
    return {
        "target": target_symbol,
        "segments": segment_metrics,
        "oos_folds": folds,
        "oos_years": years,
        "positive_fold_contribution_concentration": concentration,
        "bootstrap": bootstrap,
        "one_hour_delay": delayed,
        "mechanism": mechanism,
        "gates": gates,
        "passed_all_gates": passed,
    }


def write_report(output_dir: Path, evidence: dict[str, Any]) -> None:
    lines = [
        "# Stablecoin quote-stress entry-veto evidence",
        "",
        f"- Family: `{FAMILY_ID}`",
        f"- Generated: `{evidence['generated_at']}`",
        f"- Public source objects: `{evidence['source']['source_object_count']}` ZIP + `{evidence['source']['checksum_object_count']}` checksums",
        f"- Bar: `1H`; fee: exactly `{FEE * 10_000:.1f}` bps one way",
        f"- Verdict: `{evidence['verdict']}`",
        "",
        "| Target | OOS candidate | OOS B1 | Candidate Sharpe | B1 Sharpe | Turnover | B1 turnover | Gates |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for target in evidence["targets"]:
        c = target["segments"]["oos"]["candidate"]
        b = target["segments"]["oos"]["b1"]
        lines.append(
            f"| {target['target']} | {100*c['compounded_net_return']:+.4f}% | "
            f"{100*b['compounded_net_return']:+.4f}% | "
            f"{c['annualized_hourly_sharpe']} | {b['annualized_hourly_sharpe']} | "
            f"{c['turnover']} | {b['turnover']} | "
            f"{sum(target['gates'].values())}/{len(target['gates'])} |"
        )
    lines.extend(
        [
            "",
            "## Disposition",
            "",
            f"Markets passing every gate: `{evidence['markets_passing_all_gates']}/2`.",
            "",
            "No account, order, adapter, credential, leverage, cross-sectional selection, pair/spread, short, synthetic-price, or 15-minute path was used.",
            "",
            "Prospective evidence may support only a newly frozen shadow epoch; it never authorizes live trading.",
            "",
        ]
    )
    (output_dir / "report.md").write_text("\n".join(lines))


def run(output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    bars, manifest = download_sources(output_dir)
    targets = [evaluate_target(symbol, bars) for symbol in TARGETS]
    markets_passing = sum(target["passed_all_gates"] for target in targets)
    accepted = markets_passing == len(TARGETS)
    evidence = {
        "family_id": FAMILY_ID,
        "classification": "executable_causal_exogenous_information_strategy",
        "generated_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        "candidate_count": 2,
        "parameter_grid_count": 0,
        "bar": "1H",
        "canonical_fee_bps_one_way": 5.0,
        "markets": list(TARGETS),
        "fixed_lagged_exogenous_series": "USDCUSDT",
        "source": {
            "archive_base": manifest["archive_base"],
            "source_object_count": manifest["source_object_count"],
            "checksum_object_count": manifest["checksum_object_count"],
            "rows_per_symbol": EXPECTED_ROWS,
            "calendar_start": iso(START_MS),
            "calendar_end_exclusive": iso(END_MS_EXCLUSIVE),
            "manifest_sha256": sha256_bytes(canonical_bytes(manifest)),
            "coverage_pass": True,
            "checksum_pass": True,
            "common_calendar_pass": True,
        },
        "sample": {
            "training": [TRAIN_START, TRAIN_END],
            "sealed_oos": [OOS_START, OOS_END],
            "full_scored": [FULL_START, FULL_END],
            "unscored_suffix": [FULL_END, EXPECTED_ROWS],
            "fold_hours": FOLD_HOURS,
            "oos_fold_count": 8,
            "decision_cadence": "daily_00_UTC",
            "execution": "next_hour_open",
        },
        "hard_boundary": {
            "cross_sectional_selection": False,
            "pairs_or_spreads": False,
            "shorting": False,
            "credentials_used": False,
            "private_endpoints_used": False,
            "accounts_accessed": False,
            "orders_placed": False,
            "enabled_adapters": False,
            "leverage_used": False,
            "synthetic_prices_used": False,
            "fifteen_minute_data_used": False,
        },
        "targets": targets,
        "markets_passing_all_gates": markets_passing,
        "training_authorized_correction": {
            "permitted": accepted,
            "canonical_policy_changed": False,
            "new_shadow_epoch_required_before_any_further_disposition": accepted,
            "live_trading_authorized": False,
        },
        "verdict": (
            "support_causal_stablecoin_quote_stress_entry_veto_for_new_shadow_epoch_only"
            if accepted
            else "reject_causal_stablecoin_quote_stress_entry_veto_1h_v1"
        ),
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
    }
    evidence_bytes = canonical_bytes(evidence)
    (output_dir / "evidence.json").write_bytes(evidence_bytes)
    (output_dir / "evidence.sha256").write_text(sha256_bytes(evidence_bytes) + "\n")
    write_report(output_dir, evidence)
    report_sha = sha256_bytes((output_dir / "report.md").read_bytes())
    (output_dir / "report.sha256").write_text(report_sha + "\n")
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.output_dir), sort_keys=True, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
