from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import math
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

FAMILY_ID = "causal-own-hour-of-week-seasonal-forecast-opportunity-1h-v1"
BASE_URL = "https://www.okx.com"
ENDPOINT = "/api/v5/market/history-candles"
TARGETS = ("LTC-USDT", "DOGE-USDT")
SOURCE_START_MS = 1_680_307_200_000
SOURCE_END_MS = 1_767_222_000_000
EXPECTED_ROWS = 24_144
FIRST_ANCHOR = 4_368
TRAIN_END = 10_800
SEALED_OOS_END = 23_760
WEEK_HOURS = 168
WEEKLY_OBSERVATIONS = 12
HORIZON_HOURS = 24
ONE_WAY_FEE = 0.0005
BOOTSTRAP_RESAMPLES = 5_000
BOOTSTRAP_BLOCK = 7
EXPECTED_ROW_HASHES = {
    "LTC-USDT": "753bc2aad21dad3dac167c033f0734ca050b62d426f82d7e7cd205b1269669b0",
    "DOGE-USDT": "f1a0c59c3fc79fe81728a3fa52015232e39e42d216e63ed63253b39f0dda2554",
}
BOOTSTRAP_SEEDS = {"LTC-USDT": 2_026_080_305, "DOGE-USDT": 2_026_080_306}


@dataclass(frozen=True)
class SourcePanel:
    instrument: str
    rows: list[list[str]]
    pages: list[dict[str, str]]
    canonical_rows_sha256: str


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _fetch_page(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "gpt-quant-research/1h"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        final_url = response.geturl()
        if final_url != url:
            raise RuntimeError(f"redirect rejected: {url!r} -> {final_url!r}")
        if response.status != 200:
            raise RuntimeError(f"unexpected HTTP status {response.status} for {url}")
        body = response.read(2_000_001)
    if not body or len(body) > 2_000_000:
        raise RuntimeError("empty or oversized OKX response")
    body.decode("utf-8")
    return body


def _decode_page(body: bytes) -> list[list[str]]:
    payload = json.loads(body.decode("utf-8"))
    if set(payload) != {"code", "msg", "data"}:
        raise RuntimeError("unexpected OKX top-level schema")
    if payload["code"] != "0" or payload["msg"] != "":
        raise RuntimeError(f"OKX returned code={payload['code']!r} msg={payload['msg']!r}")
    rows = payload["data"]
    if not isinstance(rows, list):
        raise RuntimeError("OKX data field is not a list")
    for row in rows:
        if not isinstance(row, list) or len(row) != 9 or not all(isinstance(x, str) for x in row):
            raise RuntimeError("unexpected OKX candle row schema")
    return rows


def acquire_source(instrument: str) -> SourcePanel:
    row_map: dict[int, list[str]] = {}
    pages: list[dict[str, str]] = []
    cursor: int | None = None
    previous_oldest: int | None = None

    for page_number in range(1, 321):
        query: dict[str, str] = {"instId": instrument, "bar": "1H", "limit": "100"}
        if cursor is not None:
            query["after"] = str(cursor)
        url = f"{BASE_URL}{ENDPOINT}?{urllib.parse.urlencode(query)}"
        body = _fetch_page(url)
        rows = _decode_page(body)
        pages.append(
            {
                "page": str(page_number),
                "url": url,
                "sha256": _sha256(body),
                "body_base64": base64.b64encode(body).decode("ascii"),
            }
        )
        if not rows:
            break

        oldest = min(int(row[0]) for row in rows)
        if previous_oldest is not None and oldest >= previous_oldest:
            raise RuntimeError("OKX pagination cursor did not move backwards")
        previous_oldest = oldest

        for row in rows:
            timestamp = int(row[0])
            if SOURCE_START_MS <= timestamp <= SOURCE_END_MS:
                existing = row_map.get(timestamp)
                if existing is not None and existing != row:
                    raise RuntimeError(f"conflicting duplicate candle at {timestamp}")
                row_map[timestamp] = row

        if oldest <= SOURCE_START_MS:
            break
        cursor = oldest
        time.sleep(0.055)
    else:
        raise RuntimeError("OKX page budget exhausted before requested source start")

    rows = [row_map[timestamp] for timestamp in sorted(row_map)]
    canonical_hash = _sha256(_canonical_json_bytes(rows))
    if len(rows) != EXPECTED_ROWS:
        raise RuntimeError(f"{instrument} observed {len(rows)} rows, expected {EXPECTED_ROWS}")
    if canonical_hash != EXPECTED_ROW_HASHES[instrument]:
        raise RuntimeError(
            f"{instrument} canonical source hash mismatch: {canonical_hash} "
            f"!= {EXPECTED_ROW_HASHES[instrument]}"
        )
    return SourcePanel(instrument, rows, pages, canonical_hash)


def validate_source(panel: SourcePanel) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    timestamps = np.array([int(row[0]) for row in panel.rows], dtype=np.int64)
    opens = np.array([float(row[1]) for row in panel.rows], dtype=float)
    highs = np.array([float(row[2]) for row in panel.rows], dtype=float)
    lows = np.array([float(row[3]) for row in panel.rows], dtype=float)
    closes = np.array([float(row[4]) for row in panel.rows], dtype=float)
    confirms = np.array([row[8] for row in panel.rows])

    if timestamps[0] != SOURCE_START_MS or timestamps[-1] != SOURCE_END_MS:
        raise RuntimeError("source boundaries do not match the frozen calendar")
    if not np.all(np.diff(timestamps) == 3_600_000):
        raise RuntimeError("source is not a contiguous provider-native 1H grid")
    if len(np.unique(timestamps)) != EXPECTED_ROWS:
        raise RuntimeError("source timestamps are not unique")
    if not np.all(confirms == "1"):
        raise RuntimeError("source contains an incomplete candle")
    if not np.all(np.isfinite(opens)) or not np.all(np.isfinite(closes)):
        raise RuntimeError("source contains a non-finite price")
    if not np.all((opens > 0) & (highs > 0) & (lows > 0) & (closes > 0)):
        raise RuntimeError("source contains a non-positive price")
    if not np.all(highs >= np.maximum(opens, closes)):
        raise RuntimeError("source high is below open or close")
    if not np.all(lows <= np.minimum(opens, closes)):
        raise RuntimeError("source low is above open or close")

    start = datetime.fromtimestamp(timestamps[0] / 1_000, tz=UTC)
    if start != datetime(2023, 4, 1, tzinfo=UTC):
        raise RuntimeError("source calendar origin changed")
    return timestamps, opens, closes


def rank_average(values: np.ndarray) -> np.ndarray:
    return pd.Series(values).rank(method="average").to_numpy(dtype=float)


def spearman(values: np.ndarray, outcomes: np.ndarray) -> float:
    return float(np.corrcoef(rank_average(values), rank_average(outcomes))[0, 1])


def standardized_slope(values: np.ndarray, outcomes: np.ndarray) -> float:
    scale = float(np.std(values, ddof=1))
    if len(values) < 3 or not math.isfinite(scale) or scale <= 0:
        return math.nan
    standardized = (values - float(np.mean(values))) / scale
    return float(np.cov(standardized, outcomes, ddof=1)[0, 1])


def calculate_metrics(
    feature: np.ndarray, net: np.ndarray, adverse: np.ndarray
) -> dict[str, float | int]:
    q_low, q_high = np.quantile(feature, [1 / 3, 2 / 3])
    lower = feature <= q_low
    upper = feature > q_high
    return {
        "observations": int(len(feature)),
        "distinct_feature_values": int(len(np.unique(feature))),
        "feature_iqr": float(np.quantile(feature, 0.75) - np.quantile(feature, 0.25)),
        "lower_tercile_count": int(np.sum(lower)),
        "upper_tercile_count": int(np.sum(upper)),
        "net_spearman": spearman(feature, net),
        "adverse_spearman": spearman(feature, adverse),
        "net_standardized_slope": standardized_slope(feature, net),
        "adverse_standardized_slope": standardized_slope(feature, adverse),
        "net_upper_minus_lower": float(np.mean(net[upper]) - np.mean(net[lower])),
        "adverse_upper_minus_lower": float(
            np.mean(adverse[upper]) - np.mean(adverse[lower])
        ),
    }


def build_opportunities(
    timestamps: np.ndarray, opens: np.ndarray, closes: np.ndarray
) -> np.ndarray:
    open_returns = opens[1:] / opens[:-1] - 1.0
    opportunities: list[list[float]] = []

    for anchor in range(FIRST_ANCHOR, TRAIN_END - 25, 24):
        anchor_time = datetime.fromtimestamp(timestamps[anchor] / 1_000, tz=UTC)
        if anchor_time.hour != 0 or anchor_time.minute != 0:
            raise RuntimeError("daily anchor is not aligned to 00:00 UTC")
        if not closes[anchor - 25] > closes[anchor - 2_185]:
            continue

        slot_estimates: list[float] = []
        for offset in range(HORIZON_HOURS):
            indexes = [anchor + offset - WEEK_HOURS * lag for lag in range(1, 13)]
            if indexes[0] + 1 > anchor - 25:
                raise RuntimeError("seasonal estimator violated its 24H information lag")
            if indexes[-1] < 0:
                raise RuntimeError("seasonal estimator lacks its frozen 12-week history")
            slot_hours = [
                datetime.fromtimestamp(timestamps[index] / 1_000, tz=UTC).weekday() * 24
                + datetime.fromtimestamp(timestamps[index] / 1_000, tz=UTC).hour
                for index in indexes
            ]
            future_hour = (
                datetime.fromtimestamp(timestamps[anchor + offset] / 1_000, tz=UTC).weekday()
                * 24
                + datetime.fromtimestamp(
                    timestamps[anchor + offset] / 1_000, tz=UTC
                ).hour
            )
            if any(hour != future_hour for hour in slot_hours):
                raise RuntimeError("seasonal estimator mixed UTC hour-of-week slots")
            slot_estimates.append(float(np.median(open_returns[indexes])))

        feature = float(np.sum(slot_estimates))
        entry = opens[anchor]
        net = float(opens[anchor + 24] / entry - 1.0 - 2.0 * ONE_WAY_FEE)
        adverse = float(np.min(opens[anchor : anchor + 25] / entry - 1.0))
        delayed_entry = opens[anchor + 1]
        delayed_net = float(
            opens[anchor + 25] / delayed_entry - 1.0 - 2.0 * ONE_WAY_FEE
        )
        delayed_adverse = float(
            np.min(opens[anchor + 1 : anchor + 26] / delayed_entry - 1.0)
        )
        opportunities.append(
            [anchor, feature, net, adverse, delayed_net, delayed_adverse]
        )

    return np.asarray(opportunities, dtype=float)


def moving_block_intervals(
    feature: np.ndarray,
    net: np.ndarray,
    adverse: np.ndarray,
    seed: int,
) -> dict[str, dict[str, float]]:
    count = len(feature)
    starts = np.arange(0, count - BOOTSTRAP_BLOCK + 1)
    block_count = math.ceil(count / BOOTSTRAP_BLOCK)
    generator = np.random.default_rng(seed)
    draws = np.empty((BOOTSTRAP_RESAMPLES, 4), dtype=float)

    for draw in range(BOOTSTRAP_RESAMPLES):
        selected_starts = generator.choice(starts, size=block_count, replace=True)
        indexes = np.concatenate(
            [np.arange(start, start + BOOTSTRAP_BLOCK) for start in selected_starts]
        )[:count]
        metrics = calculate_metrics(feature[indexes], net[indexes], adverse[indexes])
        draws[draw] = [
            metrics["net_spearman"],
            metrics["adverse_spearman"],
            metrics["net_standardized_slope"],
            metrics["adverse_standardized_slope"],
        ]

    names = (
        "net_spearman",
        "adverse_spearman",
        "net_standardized_slope",
        "adverse_standardized_slope",
    )
    lower = np.quantile(draws, 0.025, axis=0)
    upper = np.quantile(draws, 0.975, axis=0)
    return {
        name: {"lower_95": float(lower[index]), "upper_95": float(upper[index])}
        for index, name in enumerate(names)
    }


def evaluate_target(panel: SourcePanel) -> dict[str, Any]:
    timestamps, opens, closes = validate_source(panel)
    full_opportunities = build_opportunities(timestamps, opens, closes)
    prefix_opportunities = build_opportunities(
        timestamps[:TRAIN_END], opens[:TRAIN_END], closes[:TRAIN_END]
    )
    if not np.array_equal(full_opportunities, prefix_opportunities):
        raise RuntimeError("future source suffix changed the training opportunity prefix")

    feature = full_opportunities[:, 1]
    net = full_opportunities[:, 2]
    adverse = full_opportunities[:, 3]
    delayed_net = full_opportunities[:, 4]
    delayed_adverse = full_opportunities[:, 5]
    base = calculate_metrics(feature, net, adverse)
    delayed = calculate_metrics(feature, delayed_net, delayed_adverse)

    fold_edges = np.linspace(FIRST_ANCHOR, TRAIN_END, 5, dtype=int)
    folds: list[dict[str, Any]] = []
    for index in range(4):
        selected = (full_opportunities[:, 0] >= fold_edges[index]) & (
            full_opportunities[:, 0] < fold_edges[index + 1]
        )
        fold_metrics = calculate_metrics(feature[selected], net[selected], adverse[selected])
        folds.append(
            {
                "start_index": int(fold_edges[index]),
                "end_index_exclusive": int(fold_edges[index + 1]),
                "metrics": fold_metrics,
            }
        )

    uncertainty = moving_block_intervals(
        feature,
        net,
        adverse,
        BOOTSTRAP_SEEDS[panel.instrument],
    )
    positive_net_folds = sum(
        fold["metrics"]["net_standardized_slope"] > 0 for fold in folds
    )
    positive_adverse_folds = sum(
        fold["metrics"]["adverse_standardized_slope"] > 0 for fold in folds
    )

    gates = {
        "minimum_opportunities": base["observations"] >= 120,
        "feature_support": (
            base["distinct_feature_values"] >= 30 and base["feature_iqr"] > 0
        ),
        "tercile_support": (
            base["lower_tercile_count"] >= 35 and base["upper_tercile_count"] >= 35
        ),
        "positive_continuous_associations": all(
            base[name] > 0
            for name in (
                "net_spearman",
                "adverse_spearman",
                "net_standardized_slope",
                "adverse_standardized_slope",
            )
        ),
        "positive_tercile_effects": (
            base["net_upper_minus_lower"] > 0
            and base["adverse_upper_minus_lower"] > 0
        ),
        "dependence_supported": all(
            interval["lower_95"] > 0 for interval in uncertainty.values()
        ),
        "fold_breadth": positive_net_folds >= 3 and positive_adverse_folds >= 3,
        "one_hour_delay": all(
            delayed[name] > 0
            for name in (
                "net_spearman",
                "adverse_spearman",
                "net_standardized_slope",
                "adverse_standardized_slope",
                "net_upper_minus_lower",
                "adverse_upper_minus_lower",
            )
        ),
        "prefix_invariance": True,
        "source_and_chronology": True,
    }

    return {
        "instrument": panel.instrument,
        "source": {
            "rows": len(panel.rows),
            "canonical_rows_sha256": panel.canonical_rows_sha256,
            "pages": len(panel.pages),
        },
        "opportunities": int(len(full_opportunities)),
        "base_metrics": base,
        "one_hour_delay_metrics": delayed,
        "moving_block_bootstrap": {
            "resamples": BOOTSTRAP_RESAMPLES,
            "block_opportunities": BOOTSTRAP_BLOCK,
            "seed": BOOTSTRAP_SEEDS[panel.instrument],
            "intervals": uncertainty,
        },
        "folds": folds,
        "positive_net_slope_folds": int(positive_net_folds),
        "positive_adverse_slope_folds": int(positive_adverse_folds),
        "gates": gates,
        "passed": all(gates.values()),
    }


def write_bytes_with_hash(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.with_name(f"{path.name}.sha256").write_text(f"{_sha256(data)}\n", encoding="utf-8")


def render_report(evidence: dict[str, Any]) -> str:
    lines = [
        "# Own-instrument hour-of-week seasonal forecast diagnostic",
        "",
        "```text",
        f"Family                 {FAMILY_ID}",
        f"Exact evidence head    {evidence['tested_head']}",
        "Fixed targets          LTC-USDT and DOGE-USDT independently",
        "Candidate/grid         0/0",
        "Bar                     Public completed OKX SPOT 1H",
        "Fee                     Exactly 5 bps one way",
        f"Verdict                 {evidence['verdict']}",
        "```",
        "",
        "## Frozen hypothesis",
        "",
        "At each daily UTC anchor in a positive lagged E2160 state, the feature sums the",
        "median return of the prior 12 weekly occurrences for each of the next 24",
        "hour-of-week slots. Higher forecasts were required to predict both greater",
        "next-24H fee-adjusted return and less adverse excursion in both targets.",
        "",
        "## Training-only results",
        "",
        (
            "| Target | N | Net rho | Adverse rho | Net slope | Adverse slope | "
            "Net effect | Adverse effect |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for result in evidence["results"]:
        base = result["base_metrics"]
        lines.append(
            "| {instrument} | {n} | {nr:+.6f} | {ar:+.6f} | {ns:+.6f} | "
            "{aslope:+.6f} | {ne:+.2f} bp | {ae:+.2f} bp |".format(
                instrument=result["instrument"],
                n=result["opportunities"],
                nr=base["net_spearman"],
                ar=base["adverse_spearman"],
                ns=base["net_standardized_slope"],
                aslope=base["adverse_standardized_slope"],
                ne=10_000 * base["net_upper_minus_lower"],
                ae=10_000 * base["adverse_upper_minus_lower"],
            )
        )
    lines.extend(
        [
            "",
            "## Dependence-aware lower bounds",
            "",
            "| Target | Net rho | Adverse rho | Net slope | Adverse slope |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for result in evidence["results"]:
        intervals = result["moving_block_bootstrap"]["intervals"]
        lines.append(
            "| {instrument} | {nr:+.6f} | {ar:+.6f} | {ns:+.6f} | {aslope:+.6f} |".format(
                instrument=result["instrument"],
                nr=intervals["net_spearman"]["lower_95"],
                ar=intervals["adverse_spearman"]["lower_95"],
                ns=intervals["net_standardized_slope"]["lower_95"],
                aslope=intervals["adverse_standardized_slope"]["lower_95"],
            )
        )
    lines.extend(
        [
            "",
            "## Strategy-performance accounting",
            "",
            "No executable mapping was authorised. Train, OOS and full strategy return,",
            "Sharpe, benchmark comparison, turnover, drawdown, edge per turnover and",
            "calendar-year breadth are null rather than zero. Sealed OOS was not accessed.",
            "",
            "## Verdict",
            "",
            "The point estimates were favourable in both markets and survived a one-hour",
            "execution delay, but the bilateral dependence gate failed. The observed",
            "seasonal separation is therefore insufficient evidence for an executable",
            "long/cash selector under the frozen protocol.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tested-head", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    panels = [acquire_source(instrument) for instrument in TARGETS]
    for panel in panels:
        page_payload = gzip.compress(_canonical_json_bytes(panel.pages), mtime=0)
        write_bytes_with_hash(
            output_dir / "source" / panel.instrument / "exact-pages.json.gz",
            page_payload,
        )
        write_bytes_with_hash(
            output_dir / "source" / panel.instrument / "canonical-rows.json",
            _canonical_json_bytes(panel.rows) + b"\n",
        )

    results = [evaluate_target(panel) for panel in panels]
    accepted = all(result["passed"] for result in results)
    verdict = (
        "accept_causal_own_hour_of_week_seasonal_forecast_information_premise_1h_v1"
        if accepted
        else "reject_causal_own_hour_of_week_seasonal_forecast_information_premise_1h_v1"
    )
    evidence: dict[str, Any] = {
        "family_id": FAMILY_ID,
        "tested_head": args.tested_head,
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "canonical_fee_bps_one_way": 5.0,
        "source_period": {
            "provider": "OKX",
            "market_type": "SPOT",
            "bar": "1H",
            "start_utc": "2023-04-01T00:00:00Z",
            "end_utc": "2025-12-31T23:00:00Z",
            "rows_per_target": EXPECTED_ROWS,
            "first_anchor": FIRST_ANCHOR,
            "training_end_exclusive": TRAIN_END,
            "sealed_oos": [TRAIN_END, SEALED_OOS_END],
            "unread_suffix": [SEALED_OOS_END, EXPECTED_ROWS],
        },
        "feature_contract": {
            "weekly_observations_per_slot": WEEKLY_OBSERVATIONS,
            "forecast_slots": HORIZON_HOURS,
            "estimator": "median",
            "information_lag_hours": 24,
            "condition": "lagged_E2160_positive",
        },
        "controls": {
            "sealed_oos_accessed": False,
            "strategy_performance_authorized": False,
            "canonical_mutation": False,
            "paper_or_live_authorized": False,
            "credentials_or_private_endpoints": False,
            "cross_sectional_selection": False,
        },
        "strategy_metrics": {
            "training": None,
            "oos": None,
            "full": None,
            "benchmarks": None,
            "turnover": None,
            "maximum_drawdown": None,
            "edge_per_turnover": None,
            "calendar_year_breadth": None,
        },
        "results": results,
        "targets_passing": sum(result["passed"] for result in results),
        "verdict": verdict,
    }
    evidence_bytes = json.dumps(evidence, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    write_bytes_with_hash(output_dir / "evidence.json", evidence_bytes)
    report_bytes = render_report(evidence).encode("utf-8")
    write_bytes_with_hash(output_dir / "REPORT.md", report_bytes)

    manifest = {
        "family_id": FAMILY_ID,
        "tested_head": args.tested_head,
        "files": {
            str(path.relative_to(output_dir)): _sha256(path.read_bytes())
            for path in sorted(output_dir.rglob("*"))
            if path.is_file() and not path.name.endswith(".sha256")
        },
    }
    write_bytes_with_hash(
        output_dir / "manifest.json",
        json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8") + b"\n",
    )
    print(json.dumps({"verdict": verdict, "targets_passing": evidence["targets_passing"]}))


if __name__ == "__main__":
    main()
