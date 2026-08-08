from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

FAMILY_ID = "causal-public-forced-liquidation-intensity-source-contract-1h-v1"
ISSUE_NUMBER = 1149
BASE_MAIN = "5a0fcc97d1a882f8223656c51f5bb8055f534e38"
BAR = "1H"
FEE_BPS_ONE_WAY = 5.0
CANDIDATE_COUNT = 0
PARAMETER_GRID_COUNT = 0
DOCUMENTATION_SNAPSHOT_UTC_DATE = "2026-08-08"
VERDICT = "reject_causal_public_forced_liquidation_intensity_source_contract_1h_v1"
OUT = Path("reports/research") / FAMILY_ID


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def null_performance() -> dict[str, None]:
    return {
        "train_return": None,
        "train_sharpe": None,
        "oos_return": None,
        "oos_sharpe": None,
        "full_return": None,
        "full_sharpe": None,
        "benchmark_comparison": None,
        "turnover": None,
        "modeled_fee_drag": None,
        "maximum_drawdown": None,
        "edge_per_turnover": None,
        "fold_breadth": None,
        "calendar_year_breadth": None,
        "dependence_uncertainty": None,
        "signal_frequency": None,
        "calibration": None,
        "one_hour_execution_delay": None,
    }


def provider_audit() -> list[dict[str, Any]]:
    return [
        {
            "provider": "Binance",
            "official_interfaces": [
                "https://developers.binance.info/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data",
                "https://developers.binance.info/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/websocket-market-streams",
            ],
            "documentation_facts": [
                "The current USD-M public market-data REST catalog does not expose a historical forced-liquidation aggregate endpoint.",
                "The public liquidation interface is a WebSocket liquidation-order snapshot stream rather than replayable historical 1H observations.",
                "The all-market force-order stream emits at most the latest liquidation order per symbol within a 1000 ms interval when liquidation occurs.",
            ],
            "forced_liquidation_semantics_present": True,
            "anonymous_public_surface_present": True,
            "direct_historical_1h_aggregate": False,
            "historical_replayable": False,
            "observed_native_cadence": "event snapshot / 1000ms WebSocket",
            "btc_eth_same_underlying_realtime_symbols_possible": True,
            "data_acquisition_attempted": False,
            "passes": False,
            "failure_gate": "03_direct_provider_defined_completed_1h_history",
        },
        {
            "provider": "OKX",
            "official_interfaces": [
                "https://www.okx.com/docs-v5/log_en/",
                "https://www.okx.com/docs-v5/",
            ],
            "documentation_facts": [
                "OKX documented on 2023-04-03 that platform historical liquidation orders would no longer be retrievable through REST by the end of April 2023.",
                "The former public endpoint GET /api/v5/public/liquidation-orders was delisted from the documentation in March 2023.",
                "The documented replacement is a real-time Liquidation orders WebSocket channel, not provider-defined historical 1H aggregates.",
            ],
            "forced_liquidation_semantics_present": True,
            "anonymous_public_surface_present": True,
            "direct_historical_1h_aggregate": False,
            "historical_replayable": False,
            "observed_native_cadence": "real-time WebSocket after historical REST retirement",
            "btc_eth_same_underlying_realtime_symbols_possible": True,
            "data_acquisition_attempted": False,
            "passes": False,
            "failure_gate": "05_replayable_historical_interface",
        },
        {
            "provider": "Bybit",
            "official_interfaces": [
                "https://bybit-exchange.github.io/docs/v5/websocket/public/all-liquidation",
                "https://bybit-exchange.github.io/docs/changelog/v5",
            ],
            "documentation_facts": [
                "The current official All Liquidation interface is a public WebSocket topic that pushes liquidation events every 500 ms.",
                "The topic carries symbol, liquidated position side, executed size and bankruptcy price at event timestamps.",
                "The official changelog introduced All Liquidation as a WebSocket topic in 2025; the audited public API catalog exposes no direct historical provider-defined 1H liquidation aggregate.",
            ],
            "forced_liquidation_semantics_present": True,
            "anonymous_public_surface_present": True,
            "direct_historical_1h_aggregate": False,
            "historical_replayable": False,
            "observed_native_cadence": "event snapshot / 500ms WebSocket",
            "btc_eth_same_underlying_realtime_symbols_possible": True,
            "data_acquisition_attempted": False,
            "passes": False,
            "failure_gate": "03_direct_provider_defined_completed_1h_history",
        },
    ]


def main() -> None:
    exact_head = os.environ.get("RESEARCH_HEAD_SHA", "UNBOUND")
    providers = provider_audit()
    for provider in providers:
        snapshot = {
            "provider": provider["provider"],
            "official_interfaces": provider["official_interfaces"],
            "documentation_facts": provider["documentation_facts"],
            "snapshot_utc_date": DOCUMENTATION_SNAPSHOT_UTC_DATE,
        }
        provider["documentation_snapshot_sha256"] = sha256(canonical_json(snapshot))

    assert len(providers) == 3
    assert all(p["forced_liquidation_semantics_present"] for p in providers)
    assert all(p["anonymous_public_surface_present"] for p in providers)
    assert all(not p["direct_historical_1h_aggregate"] for p in providers)
    assert all(not p["historical_replayable"] for p in providers)
    assert all(not p["data_acquisition_attempted"] for p in providers)
    assert all(not p["passes"] for p in providers)

    source_gates = {
        "01_forced_liquidation_semantics_identified": True,
        "02_anonymous_public_official_interfaces_only": True,
        "03_direct_provider_defined_completed_1h_history_exists": False,
        "04_btc_and_eth_available_under_same_direct_1h_semantics": False,
        "05_replayable_historical_interface_exists": False,
        "06_common_historical_calendar_declared": False,
        "07_unique_strict_utc_hour_chronology_proven": False,
        "08_finite_nonnegative_nonconstant_value_support_proven": False,
        "09_deterministic_pagination_boundary_coverage_proven": False,
        "10_repeat_acquisition_identity_proven": False,
        "11_later_hour_prefix_invariance_proven": False,
        "12_data_request_raw_normalized_hashes_bound": False,
        "13_bilateral_same_provider_source_semantics_pass": False,
        "14_no_target_or_oos_access_before_bilateral_source_pass": True,
    }
    assert not source_gates["03_direct_provider_defined_completed_1h_history_exists"]
    assert source_gates["14_no_target_or_oos_access_before_bilateral_source_pass"]

    evidence = {
        "schema_version": 1,
        "family_id": FAMILY_ID,
        "issue_number": ISSUE_NUMBER,
        "base_main": BASE_MAIN,
        "exact_head": exact_head,
        "documentation_snapshot_utc_date": DOCUMENTATION_SNAPSHOT_UTC_DATE,
        "bar": BAR,
        "future_executable_fee_bps_one_way": FEE_BPS_ONE_WAY,
        "candidate_count": CANDIDATE_COUNT,
        "parameter_grid_count": PARAMETER_GRID_COUNT,
        "fixed_future_targets": ["BTC-USDT", "ETH-USDT"],
        "information_object": "same-underlying forced-liquidation intensity",
        "providers_audited": providers,
        "provider_count": len(providers),
        "providers_passing": 0,
        "source_arms_acquired": 0,
        "new_market_rows": 0,
        "new_target_labels": 0,
        "new_oos_observations": 0,
        "new_fitting_or_tuning": 0,
        "target_price_accessed": False,
        "target_return_accessed": False,
        "oos_accessed": False,
        "source_gates": source_gates,
        "source_gates_passed": sum(source_gates.values()),
        "source_gates_total": len(source_gates),
        "data_request_raw_normalized_hashes": None,
        "performance": null_performance(),
        "closed_rescue_surface": [
            "locally aggregated liquidation events",
            "websocket capture presented as historical data",
            "liquidation heatmaps or estimated liquidation levels",
            "open-interest drops relabelled as liquidation",
            "taker-flow spikes or funding/basis proxies",
            "sub-hour inputs or daily expansion",
            "third-party vendors or credentialed access",
            "shortened calendars or provider stitching",
            "target deletion or single-market promotion",
        ],
        "canonical_mutation": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "verdict": VERDICT,
    }

    OUT.mkdir(parents=True, exist_ok=True)
    evidence_raw = canonical_json(evidence)
    (OUT / "evidence.json").write_bytes(evidence_raw)

    report = f"""# Public forced-liquidation intensity 1H source-contract audit

- family: `{FAMILY_ID}`
- issue: `#{ISSUE_NUMBER}`
- exact head: `{exact_head}`
- canonical main: `{BASE_MAIN}`
- documentation snapshot UTC date: `{DOCUMENTATION_SNAPSHOT_UTC_DATE}`
- required bar: direct provider-defined completed `1H`
- candidate/grid: `0/0`
- target-price / target-return / OOS access: `false / false / false`
- source arms acquired: `0`
- future executable fee contract: exactly `5 bps` one way
- source gates passed: `{sum(source_gates.values())}/{len(source_gates)}`
- terminal verdict: `{VERDICT}`

The frozen official-interface catalog fails before market-data acquisition. Binance exposes liquidation as real-time WebSocket force-order snapshots rather than replayable historical 1H aggregates. OKX explicitly retired its historical liquidation-orders REST retrieval in April 2023 and directs users to a real-time WebSocket channel. Bybit exposes All Liquidation as a 500 ms public WebSocket event stream and the audited catalog contains no direct historical provider-defined 1H liquidation aggregate.

Because no audited provider satisfies the native historical 1H gate, no common calendar is declared, no BTC/ETH target candles or returns are requested, and all executable strategy economics remain null. This rejects only the frozen public-source contract; it does not claim forced deleveraging has no economic information.
"""
    report_raw = report.encode()
    (OUT / "report.md").write_bytes(report_raw)

    evidence_sha = sha256(evidence_raw)
    report_sha = sha256(report_raw)
    (OUT / "evidence.sha256").write_text(evidence_sha + "\n")
    (OUT / "report.sha256").write_text(report_sha + "\n")
    manifest = {
        "family_id": FAMILY_ID,
        "exact_head": exact_head,
        "evidence_sha256": evidence_sha,
        "report_sha256": report_sha,
        "documentation_snapshot_sha256": {
            p["provider"]: p["documentation_snapshot_sha256"] for p in providers
        },
        "files": ["evidence.json", "report.md", "evidence.sha256", "report.sha256"],
    }
    manifest_raw = canonical_json(manifest)
    manifest_sha = sha256(manifest_raw)
    (OUT / "manifest.json").write_bytes(manifest_raw)
    (OUT / "manifest.sha256").write_text(manifest_sha + "\n")

    print(
        json.dumps(
            {
                "family_id": FAMILY_ID,
                "exact_head": exact_head,
                "providers_passing": "0/3",
                "source_gates": f"{sum(source_gates.values())}/{len(source_gates)}",
                "verdict": VERDICT,
                "evidence_sha256": evidence_sha,
                "report_sha256": report_sha,
                "manifest_sha256": manifest_sha,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
