#!/usr/bin/env python3
"""Frozen issue #891 evaluation using immutable public 1H data only."""
from __future__ import annotations

import math
import os
import statistics
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

import onchain_activity_metrics_core as core
from onchain_activity_source import (
    BAR,
    CM_ASSET_METRICS_ENDPOINT,
    CM_BASE_URL,
    CM_FREQUENCY,
    END_MS,
    EXPECTED_ROWS,
    FAMILY_ID,
    FEE,
    FULL_END,
    HOUR_MS,
    MARKETS,
    MIN_SIGNAL_INDEX,
    OKX_BASE_URL,
    OKX_CANDLE_ENDPOINT,
    OOS_END,
    OUT,
    PROTOCOL_SIGNATURE,
    SOURCE,
    START_MS,
    TRAIN_END,
    WARMUP_END,
    ActivitySeries,
    PriceSeries,
    SourceContractError,
    acquire_coinmetrics_activity,
    acquire_okx_price,
    canonical_bytes,
    sha256_bytes,
    sha256_file,
    utc_iso,
)


@dataclass(frozen=True)
class ActivityView:
    """Activity series with the identity expected by the verified metrics core."""

    asset: str
    open_ms: np.ndarray
    tx_count: np.ndarray

    @property
    def inst_id(self) -> str:
        return self.asset


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def quarter_key(ms: int) -> str:
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    return f"{dt.year}-Q{(dt.month - 1) // 3 + 1}"


def first_decision_at_or_after(start: int) -> int:
    return math.ceil(max(start, MIN_SIGNAL_INDEX) / 24) * 24


def signal_values(
    spot: PriceSeries, activity: ActivityView, t: int
) -> tuple[float, float, bool, bool]:
    spot_margin = math.log(spot.closes[t - 1] / spot.closes[t - 2161])
    old_activity = float(np.median(np.log1p(activity.tx_count[t - 1464 : t - 744])))
    new_activity = float(np.median(np.log1p(activity.tx_count[t - 744 : t - 24])))
    activity_margin = new_activity - old_activity
    if not math.isfinite(activity_margin):
        raise RuntimeError(f"{activity.asset}: non-finite activity margin at index {t}")
    return spot_margin, activity_margin, spot_margin > 0, activity_margin > 0


def build_path(
    spot: PriceSeries,
    activity: ActivityView,
    start: int,
    end: int,
    *,
    kind: str,
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    position = np.zeros(end - start, dtype=np.int8)
    current = 0
    events: list[dict[str, Any]] = []
    for t in range(first_decision_at_or_after(start), end, 24):
        spot_margin, activity_margin, spot_positive, activity_positive = signal_values(
            spot, activity, t
        )
        veto = False
        if kind == "candidate":
            if current == 0:
                veto = spot_positive and not activity_positive
                current = int(spot_positive and activity_positive)
            else:
                current = int(spot_positive)
        elif kind == "e2160":
            current = int(spot_positive)
        elif kind == "cash":
            current = 0
        else:
            raise ValueError(f"unknown path kind {kind}")
        lo, hi = max(t, start), min(t + 24, end)
        if lo < hi:
            position[lo - start : hi - start] = current
        events.append(
            {
                "execution_index": t,
                "execution_open": utc_iso(int(spot.open_ms[t])),
                "spot_margin": spot_margin,
                "activity_margin": activity_margin,
                "activity_positive": activity_positive,
                "target": current,
                "entry_veto": veto,
                "quarter": quarter_key(int(spot.open_ms[t])),
                "year": datetime.fromtimestamp(
                    int(spot.open_ms[t]) / 1000, tz=timezone.utc
                ).year,
            }
        )
    return position, events


def support_record(
    spot: PriceSeries, activity: ActivityView
) -> tuple[dict[str, Any], list[float]]:
    _, events = build_path(spot, activity, WARMUP_END, TRAIN_END, kind="candidate")
    vetoes = [event for event in events if event["entry_veto"]]
    quarters = Counter(event["quarter"] for event in vetoes)
    largest_share = max(quarters.values(), default=0) / len(vetoes) if vetoes else None
    margins = [float(event["activity_margin"]) for event in events]
    positive_spot = [event for event in events if event["spot_margin"] > 0]
    supported = sum(
        math.isfinite(float(event["activity_margin"]))
        and abs(float(event["activity_margin"])) > 0
        for event in positive_spot
    )
    support_ratio = supported / len(positive_spot) if positive_spot else 0.0
    gates = {
        "at_least_20_training_vetoes": len(vetoes) >= 20,
        "at_least_4_training_quarters": len(quarters) >= 4,
        "largest_quarter_share_at_most_50pct": (
            largest_share is not None and largest_share <= 0.5
        ),
        "activity_margin_has_both_sign_states": (
            any(value > 0 for value in margins) and any(value <= 0 for value in margins)
        ),
        "positive_spot_nonzero_activity_support_at_least_95pct": support_ratio >= 0.95,
        "activity_margin_not_constant": len(set(margins)) > 1,
    }
    record = {
        "training_decisions": len(events),
        "training_vetoes": len(vetoes),
        "vetoes_by_quarter": dict(sorted(quarters.items())),
        "distinct_veto_quarters": len(quarters),
        "largest_veto_quarter_share": largest_share,
        "positive_spot_nonzero_activity_support_ratio": support_ratio,
        "activity_margin_min": min(margins),
        "activity_margin_median": float(statistics.median(margins)),
        "activity_margin_max": max(margins),
        "activity_margin_sha256": sha256_bytes(canonical_bytes(margins)),
        "gates": gates,
        "passes_individual_support": all(gates.values()),
    }
    return record, margins


def bind_metrics_core() -> None:
    core.first_decision_at_or_after = first_decision_at_or_after
    core.signal_values = signal_values
    core.build_path = build_path


def null_market_record(
    target: str, asset: str, support: dict[str, Any] | None
) -> dict[str, Any]:
    return {
        "target": target,
        "asset": asset,
        "training_support": support,
        "performance_accessed": False,
        "strategies": None,
        "oos_folds": None,
        "oos_years": None,
        "paired_uncertainty": None,
        "one_hour_delay_oos": None,
        "gates": None,
        "passes_individual_gates": False,
    }


def write_evidence(evidence: dict[str, Any]) -> str:
    evidence_path = OUT / "evidence.json"
    evidence_path.write_bytes(canonical_bytes(evidence))
    digest = sha256_file(evidence_path)
    (OUT / "evidence.sha256").write_text(digest + "\n")
    return digest


def display(value: float | None, spec: str) -> str:
    return "undefined" if value is None else format(value, spec)


def make_report(evidence: dict[str, Any]) -> str:
    lines = [
        "# On-chain transaction-activity confirmed E2160 entry",
        "",
        f"- Family: `{FAMILY_ID}`",
        f"- Exact head: `{evidence['exact_head']}`",
        f"- Fee: exactly `{FEE * 10_000:.1f}` bps one way",
        f"- Candidate count: `{evidence['candidate_count']}`",
        f"- Parameter grid: `{evidence['parameter_grid_count']}`",
        f"- Verdict: `{evidence['verdict']}`",
        "",
    ]
    if not evidence["source_contract_passed"]:
        lines += [
            "## Source-contract rejection",
            "",
            f"`{evidence['source_failure']}`",
            "",
            "Performance fields are null and sealed OOS was not evaluated.",
        ]
        return "\n".join(lines) + "\n"
    source = evidence["source_contract"]
    lines += [
        "## Immutable source",
        "",
        f"- Grid: `{source['requested_start']}` through "
        f"`{source['requested_end_inclusive']}`.",
        f"- Rows per series: `{source['expected_rows_per_series']}`.",
        f"- Provider responses: `{source['response_count']}`; bytes: "
        f"`{source['response_total_bytes']}`.",
        "",
        "## Training-only support",
        "",
        "| Target | Decisions | Vetoes | Quarters | Largest quarter | Support | Pass |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for market in evidence["markets"]:
        support = market["training_support"]
        lines.append(
            f"| {market['target']} | {support['training_decisions']} | "
            f"{support['training_vetoes']} | {support['distinct_veto_quarters']} | "
            f"{display(support['largest_veto_quarter_share'], '.2%')} | "
            f"{support['positive_spot_nonzero_activity_support_ratio']:.2%} | "
            f"{support['passes']} |"
        )
    if not evidence["bilateral_training_support_passed"]:
        lines += ["", evidence["highest_value_failure"]]
        return "\n".join(lines) + "\n"
    lines += [
        "",
        "## Performance",
        "",
        "| Market | Segment | Candidate net | Sharpe | E2160 net | E2160 Sharpe | "
        "Always-long | Turnover | Edge/turn | Max DD |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for market in evidence["markets"]:
        for segment in ("training", "oos", "full"):
            candidate = market["strategies"]["candidate"][segment]
            benchmark = market["strategies"]["e2160"][segment]
            always = market["strategies"]["always_long"][segment]
            lines.append(
                f"| {market['target']} | {segment} | "
                f"{candidate['net_compound_return']:+.4%} | "
                f"{display(candidate['annualised_hourly_sharpe'], '+.4f')} | "
                f"{benchmark['net_compound_return']:+.4%} | "
                f"{display(benchmark['annualised_hourly_sharpe'], '+.4f')} | "
                f"{always['net_compound_return']:+.4%} | "
                f"{candidate['one_way_turnover']:.0f} | "
                f"{display(candidate['edge_per_turnover_bps'], '+.2f')} bps | "
                f"{candidate['maximum_drawdown']:+.4%} |"
            )
    lines += ["", "## Verdict driver", "", evidence["highest_value_failure"]]
    return "\n".join(lines) + "\n"


def source_rejection(
    *, exact_head: str, manifest: list[dict[str, Any]], failure: Exception
) -> dict[str, Any]:
    return {
        "family_id": FAMILY_ID,
        "classification": "executable causal exogenous-information strategy",
        "exact_head": exact_head,
        "generated_at": now_iso(),
        "canonical_fee_bps_one_way": 5.0,
        "bar_interval": "1H",
        "public_data_only": True,
        "credentials_private_endpoints_accounts_orders_adapters_leverage_funds": False,
        "cross_sectional_or_contemporaneous_selection": False,
        "candidate_count": 2,
        "parameter_grid_count": 0,
        "source_contract_passed": False,
        "source_failure": f"{type(failure).__name__}: {failure}",
        "source_manifest_partial": manifest,
        "performance_accessed": False,
        "oos_accessed": False,
        "bilateral_training_support_passed": False,
        "markets": [
            null_market_record(pair["target"], pair["asset"], None) for pair in MARKETS
        ],
        "markets_passing_all_gates": 0,
        "highest_value_failure": "The frozen immutable source contract failed.",
        "verdict": (
            "reject_causal_onchain_transaction_activity_confirmed_e2160_entry_"
            "source_contract"
        ),
        "canonical_strategy_changed": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
    }


def normalized_hashes(
    prices: dict[str, PriceSeries], activities: dict[str, ActivityView]
) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for name, series in prices.items():
        result[name] = {
            "open_ms_sha256": sha256_bytes(series.open_ms.tobytes()),
            "open_sha256": sha256_bytes(series.opens.tobytes()),
            "close_sha256": sha256_bytes(series.closes.tobytes()),
        }
    for name, series in activities.items():
        result[name] = {
            "open_ms_sha256": sha256_bytes(series.open_ms.tobytes()),
            "tx_count_sha256": sha256_bytes(series.tx_count.tobytes()),
        }
    return result


def finish(evidence: dict[str, Any]) -> None:
    digest = write_evidence(evidence)
    report = make_report(evidence)
    (OUT / "report.md").write_text(report)
    print(report)
    print(f"evidence_sha256={digest}")


def main() -> None:
    bind_metrics_core()
    OUT.mkdir(parents=True, exist_ok=True)
    SOURCE.mkdir(parents=True, exist_ok=True)
    exact_head = os.environ.get("GITHUB_SHA", "local")
    manifest: list[dict[str, Any]] = []
    prices: dict[str, PriceSeries] = {}
    activities: dict[str, ActivityView] = {}
    try:
        for pair in MARKETS:
            price, price_manifest = acquire_okx_price(pair["target"])
            raw_activity, activity_manifest = acquire_coinmetrics_activity(pair["asset"])
            prices[pair["target"]] = price
            activities[pair["asset"]] = ActivityView(
                raw_activity.asset, raw_activity.open_ms, raw_activity.tx_count
            )
            manifest.extend(price_manifest)
            manifest.extend(activity_manifest)
        reference = prices[MARKETS[0]["target"]].open_ms
        for series in [*prices.values(), *activities.values()]:
            if not np.array_equal(reference, series.open_ms):
                raise SourceContractError("fixed price/activity calendars do not match")
    except SourceContractError as exc:
        finish(source_rejection(exact_head=exact_head, manifest=manifest, failure=exc))
        return

    source_contract = {
        "providers": ["OKX public market data", "Coin Metrics Community"],
        "okx_base_url": OKX_BASE_URL,
        "okx_candle_endpoint": OKX_CANDLE_ENDPOINT,
        "coinmetrics_base_url": CM_BASE_URL,
        "coinmetrics_endpoint": CM_ASSET_METRICS_ENDPOINT,
        "bar": BAR,
        "coinmetrics_frequency": CM_FREQUENCY,
        "requested_start": utc_iso(START_MS),
        "requested_end_inclusive": utc_iso(END_MS - HOUR_MS),
        "expected_rows_per_series": EXPECTED_ROWS,
        "series": [item for pair in MARKETS for item in pair.values()],
        "response_count": len(manifest),
        "response_total_bytes": sum(row["response_bytes"] for row in manifest),
        "normalized_hashes": normalized_hashes(prices, activities),
        "manifest": manifest,
    }
    manifest_path = OUT / "source-manifest.json"
    manifest_path.write_bytes(canonical_bytes(source_contract))

    support_by_target: dict[str, dict[str, Any]] = {}
    margins_by_target: dict[str, list[float]] = {}
    for pair in MARKETS:
        support, margins = support_record(
            prices[pair["target"]], activities[pair["asset"]]
        )
        support_by_target[pair["target"]] = support
        margins_by_target[pair["target"]] = margins
    targets = [pair["target"] for pair in MARKETS]
    distinct = canonical_bytes(margins_by_target[targets[0]]) != canonical_bytes(
        margins_by_target[targets[1]]
    )
    for support in support_by_target.values():
        support["gates"]["activity_state_not_byte_identical_across_assets"] = distinct
        support["passes"] = support["passes_individual_support"] and distinct

    freeze = {
        "family_id": FAMILY_ID,
        "protocol_signature": PROTOCOL_SIGNATURE,
        "protocol_sha256": sha256_bytes(PROTOCOL_SIGNATURE.encode()),
        "script_sha256": sha256_file(Path(__file__)),
        "source_module_sha256": sha256_file(
            Path(__file__).with_name("onchain_activity_source.py")
        ),
        "metrics_core_sha256": sha256_file(
            Path(__file__).with_name("onchain_activity_metrics_core.py")
        ),
        "source_manifest_sha256": sha256_file(manifest_path),
        "exact_head": exact_head,
        "performance_seen_before_freeze": False,
        "oos_accessed_before_freeze": False,
        "training_support": support_by_target,
        "frozen_at": now_iso(),
    }
    (OUT / "freeze.json").write_bytes(canonical_bytes(freeze))

    bilateral_support = all(item["passes"] for item in support_by_target.values())
    if not bilateral_support:
        markets = [
            null_market_record(
                pair["target"], pair["asset"], support_by_target[pair["target"]]
            )
            for pair in MARKETS
        ]
        failures = {
            target: [name for name, passed in support["gates"].items() if not passed]
            for target, support in support_by_target.items()
        }
        finish(
            {
                "family_id": FAMILY_ID,
                "classification": "executable causal exogenous-information strategy",
                "exact_head": exact_head,
                "generated_at": now_iso(),
                "canonical_fee_bps_one_way": 5.0,
                "bar_interval": "1H",
                "public_data_only": True,
                "credentials_private_endpoints_accounts_orders_adapters_leverage_funds": False,
                "cross_sectional_or_contemporaneous_selection": False,
                "candidate_count": 2,
                "parameter_grid_count": 0,
                "source_contract_passed": True,
                "source_contract": source_contract,
                "freeze": freeze,
                "bilateral_training_support_passed": False,
                "performance_accessed": False,
                "oos_accessed": False,
                "markets": markets,
                "markets_passing_all_gates": 0,
                "highest_value_failure": "Training support failed before OOS: "
                + "; ".join(
                    f"{target}: {', '.join(names) if names else 'none'}"
                    for target, names in failures.items()
                ),
                "verdict": (
                    "reject_causal_onchain_transaction_activity_confirmed_"
                    "e2160_entry_1h_v1"
                ),
                "canonical_strategy_changed": False,
                "paper_trading_authorized": False,
                "live_trading_authorized": False,
            }
        )
        return

    markets = []
    for pair in MARKETS:
        market = core.evaluate_market(
            prices[pair["target"]],
            activities[pair["asset"]],
            support_by_target[pair["target"]],
        )
        market["asset"] = market.pop("index")
        markets.append(market)
    bilateral = all(market["passes_individual_gates"] for market in markets)
    for market in markets:
        market["gates"]["16_bilateral_replication"] = bilateral
        market["gates_passed_with_bilateral"] = sum(market["gates"].values())
        market["passes_all_gates"] = all(market["gates"].values())
        market["performance_accessed"] = True
    accepted = all(market["passes_all_gates"] for market in markets)
    failures = []
    for market in markets:
        candidate = market["strategies"]["candidate"]["oos"]
        benchmark = market["strategies"]["e2160"]["oos"]
        failed = [name for name, passed in market["gates"].items() if not passed]
        failures.append(
            f"{market['target']} failed {len(failed)}/16 gates "
            f"({', '.join(failed) if failed else 'none'}); candidate OOS net "
            f"{candidate['net_compound_return']:+.4%} versus E2160 "
            f"{benchmark['net_compound_return']:+.4%}."
        )
    verdict = (
        "accept_causal_onchain_transaction_activity_confirmed_e2160_entry_1h_v1"
        if accepted
        else "reject_causal_onchain_transaction_activity_confirmed_e2160_entry_1h_v1"
    )
    finish(
        {
            "family_id": FAMILY_ID,
            "classification": "executable causal exogenous-information strategy",
            "exact_head": exact_head,
            "generated_at": now_iso(),
            "canonical_fee_bps_one_way": 5.0,
            "bar_interval": "1H",
            "public_data_only": True,
            "credentials_private_endpoints_accounts_orders_adapters_leverage_funds": False,
            "cross_sectional_or_contemporaneous_selection": False,
            "candidate_count": 2,
            "parameter_grid_count": 0,
            "source_contract_passed": True,
            "source_contract": source_contract,
            "freeze": freeze,
            "bilateral_training_support_passed": True,
            "performance_accessed": True,
            "oos_accessed": True,
            "sample": {
                "warmup": [0, WARMUP_END],
                "training": [WARMUP_END, TRAIN_END],
                "sealed_oos": [TRAIN_END, OOS_END],
                "full_scored": [WARMUP_END, FULL_END],
                "unscored_suffix": [FULL_END, EXPECTED_ROWS],
                "oos_folds": 6,
                "oos_calendar_labels": [2024, 2025],
            },
            "markets": markets,
            "markets_passing_all_gates": sum(
                market["passes_all_gates"] for market in markets
            ),
            "highest_value_failure": " ".join(failures),
            "verdict": verdict,
            "canonical_strategy_changed": False,
            "paper_trading_authorized": False,
            "live_trading_authorized": False,
        }
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ABORT: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
