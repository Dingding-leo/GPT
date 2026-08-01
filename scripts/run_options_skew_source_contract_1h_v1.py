from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FAMILY_ID = "causal-options-implied-downside-skew-confirmed-e2160-entry-1h-v1"
VERDICT = (
    "reject_causal_options_implied_downside_skew_confirmed_e2160_entry_1h_v1"
    "_at_source_contract"
)
REPOSITORY_MAIN = "5a0fcc97d1a882f8223656c51f5bb8055f534e38"
CANONICAL_FEE_BPS_ONE_WAY = 5.0
MAX_SOURCE_BYTES = 8_000_000

SOURCES: tuple[dict[str, Any], ...] = (
    {
        "id": "deribit_api_catalog",
        "provider": "Deribit",
        "url": "https://docs.deribit.com/llms.txt",
        "official": True,
        "role": "official public API endpoint inventory",
    },
    {
        "id": "deribit_volatility_index",
        "provider": "Deribit",
        "url": (
            "https://docs.deribit.com/api-reference/market-data/"
            "public-get_volatility_index_data.md"
        ),
        "official": True,
        "role": "official volatility-index candle semantics",
    },
    {
        "id": "deribit_recent_option_trades",
        "provider": "Deribit",
        "url": (
            "https://docs.deribit.com/api-reference/market-data/"
            "public-get_last_trades_by_currency_and_time.md"
        ),
        "official": True,
        "role": "official public option-trade IV retention semantics",
    },
    {
        "id": "okx_public_api_catalog",
        "provider": "OKX",
        "url": "https://www.okx.com/docs-v5/en/",
        "official": True,
        "role": "official public market-data endpoint inventory",
    },
    {
        "id": "bybit_market_api_catalog",
        "provider": "Bybit",
        "url": "https://bybit-exchange.github.io/docs/api-explorer/v5/market/market",
        "official": True,
        "role": "official public market-data endpoint inventory",
    },
    {
        "id": "binance_derivatives_api_catalog",
        "provider": "Binance",
        "url": "https://developers.binance.com/docs/derivatives",
        "official": True,
        "role": "official derivatives API documentation catalog",
    },
)

PROVIDER_AUDIT: tuple[dict[str, Any], ...] = (
    {
        "provider": "Deribit",
        "official_public_inventory_reviewed": True,
        "direct_historical_1h_downside_skew_series": False,
        "available_public_alternatives": [
            {
                "endpoint": "public/get_volatility_index_data",
                "data": "BTC/ETH volatility-index OHLC candles",
                "supports_1h": True,
                "why_not_contract": (
                    "provider semantics are aggregate implied-volatility index, "
                    "not downside skew"
                ),
            },
            {
                "endpoint": "public/get_last_trades_by_currency_and_time",
                "data": "option trades containing trade-level IV",
                "supports_1h": False,
                "why_not_contract": (
                    "only the last 24 hours are exposed and repository-side "
                    "strike/expiry cross-section reconstruction is prohibited"
                ),
            },
            {
                "endpoint": "public/get_book_summary_by_currency",
                "data": "current option-instrument summaries containing mark IV",
                "supports_1h": False,
                "why_not_contract": (
                    "current cross-sectional snapshot rather than a direct "
                    "historical hourly skew series"
                ),
            },
        ],
    },
    {
        "provider": "OKX",
        "official_public_inventory_reviewed": True,
        "direct_historical_1h_downside_skew_series": False,
        "available_public_alternatives": [
            {
                "endpoint_class": (
                    "public option tickers, instruments, trades and candles"
                ),
                "why_not_contract": (
                    "no provider-defined direct historical hourly downside-skew "
                    "series; local option-chain reconstruction is prohibited"
                ),
            }
        ],
    },
    {
        "provider": "Bybit",
        "official_public_inventory_reviewed": True,
        "direct_historical_1h_downside_skew_series": False,
        "available_public_alternatives": [
            {
                "endpoint_class": (
                    "current option tickers, recent trades and historical volatility"
                ),
                "why_not_contract": (
                    "no provider-defined direct historical hourly downside-skew "
                    "series; aggregate volatility is not skew"
                ),
            }
        ],
    },
    {
        "provider": "Binance",
        "official_public_inventory_reviewed": True,
        "direct_historical_1h_downside_skew_series": False,
        "available_public_alternatives": [
            {
                "endpoint_class": "documented options and derivatives market data",
                "why_not_contract": (
                    "official public catalog does not expose a direct historical "
                    "hourly BTC/ETH downside-skew series"
                ),
            }
        ],
    },
)

NULL_ECONOMICS = {
    "train_net_return": None,
    "train_sharpe": None,
    "oos_net_return": None,
    "oos_sharpe": None,
    "full_net_return": None,
    "full_sharpe": None,
    "e2160_train_net_return": None,
    "e2160_train_sharpe": None,
    "e2160_oos_net_return": None,
    "e2160_oos_sharpe": None,
    "e2160_full_net_return": None,
    "e2160_full_sharpe": None,
    "always_long_net_return": None,
    "always_long_sharpe": None,
    "turnover": None,
    "modeled_fees": None,
    "maximum_drawdown": None,
    "edge_per_turnover_bps": None,
    "fold_breadth": None,
    "calendar_year_breadth": None,
    "dependence_aware_uncertainty": None,
    "one_hour_delayed_net_return": None,
    "one_hour_delayed_sharpe": None,
}


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def safe_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def fetch_source(source: dict[str, Any], source_dir: Path) -> dict[str, Any]:
    request = urllib.request.Request(
        source["url"],
        headers={
            "User-Agent": "Dingding-leo-GPT-research-source-audit/1.0",
            "Accept": (
                "text/plain,text/markdown,text/html,"
                "application/json;q=0.9,*/*;q=0.8"
            ),
        },
    )
    record = {
        "id": source["id"],
        "provider": source["provider"],
        "url": source["url"],
        "official": source["official"],
        "role": source["role"],
        "retrieval_succeeded": False,
        "http_status": None,
        "content_type": None,
        "bytes": 0,
        "sha256": None,
        "saved_path": None,
        "error": None,
        "semantic_marker_counts": None,
    }
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            body = response.read(MAX_SOURCE_BYTES + 1)
            if len(body) > MAX_SOURCE_BYTES:
                raise ValueError(
                    f"official document exceeded {MAX_SOURCE_BYTES} byte audit cap"
                )
            record["http_status"] = getattr(response, "status", 200)
            record["content_type"] = response.headers.get("Content-Type")
    except (OSError, ValueError, urllib.error.URLError) as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
        return record

    suffix = ".txt"
    lowered_type = (record["content_type"] or "").lower()
    if "html" in lowered_type:
        suffix = ".html"
    elif "json" in lowered_type:
        suffix = ".json"
    filename = f"{safe_slug(source['id'])}{suffix}"
    path = source_dir / filename
    path.write_bytes(body)
    lowered = body.decode("utf-8", errors="replace").lower()
    phrases = (
        "downside skew",
        "risk reversal",
        "25-delta",
        "25 delta",
        "volatility index",
        "get_volatility_index_data",
        "get_last_trades_by_currency_and_time",
        "last 24 hours",
        "mark_iv",
    )
    record.update(
        {
            "retrieval_succeeded": True,
            "bytes": len(body),
            "sha256": sha256_bytes(body),
            "saved_path": str(path.as_posix()),
            "semantic_marker_counts": {
                phrase: lowered.count(phrase) for phrase in phrases
            },
        }
    )
    return record


def source_gate() -> list[dict[str, Any]]:
    return [
        {
            "gate": 1,
            "name": "provider_defined_downside_skew_semantics",
            "BTC": False,
            "ETH": False,
            "reason": (
                "no reviewed official provider exposes a direct historical series "
                "whose provider-defined meaning is downside skew"
            ),
        },
        {
            "gate": 2,
            "name": "direct_exact_utc_1h_resolution",
            "BTC": False,
            "ETH": False,
            "reason": "no qualifying direct skew endpoint exists to supply hourly rows",
        },
        {
            "gate": 3,
            "name": "sufficient_common_historical_calendar",
            "BTC": False,
            "ETH": False,
            "reason": (
                "no qualifying dataset exists from which a common calendar "
                "can be frozen"
            ),
        },
        {
            "gate": 4,
            "name": "strict_unique_utc_hour_openings",
            "BTC": False,
            "ETH": False,
            "reason": "no qualifying hourly observations exist to validate",
        },
        {
            "gate": 5,
            "name": "causal_available_from_utc",
            "BTC": False,
            "ETH": False,
            "reason": "no qualifying provider publication timestamp contract exists",
        },
        {
            "gate": 6,
            "name": "complete_replayable_pagination_and_retention",
            "BTC": False,
            "ETH": False,
            "reason": (
                "trade-level option IV is retained only for a short recent window "
                "and is not a direct hourly skew history"
            ),
        },
        {
            "gate": 7,
            "name": "response_metadata_rows_and_coverage_hashes",
            "BTC": False,
            "ETH": False,
            "reason": (
                "documentation bytes are hashed, but no qualifying skew dataset exists"
            ),
        },
        {
            "gate": 8,
            "name": "historical_prefix_invariance",
            "BTC": False,
            "ETH": False,
            "reason": (
                "cannot test prefix invariance without a qualifying paginated series"
            ),
        },
        {
            "gate": 9,
            "name": "prohibited_capabilities_absent",
            "BTC": True,
            "ETH": True,
            "reason": (
                "the audit used official public documentation only; no credentials, "
                "chains, strike/expiry selection, pairs or portfolio operation"
            ),
        },
        {
            "gate": 10,
            "name": "fail_closed_on_missing_or_ambiguous_source",
            "BTC": True,
            "ETH": True,
            "reason": (
                "the architecture rejects before feature, candidate or return access"
            ),
        },
    ]


def build_evidence(
    tested_head: str, source_records: list[dict[str, Any]]
) -> dict[str, Any]:
    gates = source_gate()
    market_arms = []
    for market in ("BTC-USDT", "ETH-USDT"):
        market_arms.append(
            {
                "market": market,
                "underlying": market.split("-")[0],
                "direct_source_available": False,
                "source_contract_passed": False,
                "requested_boundary": None,
                "observed_boundary": None,
                "expected_1h_rows": None,
                "observed_1h_rows": None,
                "gaps": None,
                "longest_gap_hours": None,
                "duplicates": None,
                "conflicts": None,
                "availability_lag": None,
                "continuation_behavior": None,
                "dataset_sha256": None,
                "economics": dict(NULL_ECONOMICS),
                "economics_null_reason": (
                    "source contract failed before feature definition, candidate "
                    "creation, target-return access or sealed OOS access"
                ),
            }
        )

    return {
        "family_id": FAMILY_ID,
        "classification": "source-contract-first information experiment",
        "tested_head": tested_head,
        "repository_main": REPOSITORY_MAIN,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "bar": "1H",
        "canonical_fee_bps_one_way": CANONICAL_FEE_BPS_ONE_WAY,
        "fixed_targets": ["BTC-USDT", "ETH-USDT"],
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "new_market_data_downloaded": 0,
        "target_returns_downloaded": False,
        "feature_defined": False,
        "candidate_created": False,
        "performance_accessed": False,
        "oos_accessed": False,
        "performance_recomputed": False,
        "synthetic_data_used": False,
        "cross_sectional_selection": False,
        "pairs_or_spreads": False,
        "market_neutral_or_long_short": False,
        "credentials_used": False,
        "private_endpoints_used": False,
        "accounts_or_orders": False,
        "leverage_used": False,
        "official_document_sources": source_records,
        "provider_audit": list(PROVIDER_AUDIT),
        "source_gate": gates,
        "source_gate_passes_by_market": {
            market: sum(1 for gate in gates if gate[market])
            for market in ("BTC", "ETH")
        },
        "market_arms": market_arms,
        "source_contract_passed": False,
        "markets_passing_source_contract": 0,
        "documents_retrieved": sum(
            1 for record in source_records if record["retrieval_succeeded"]
        ),
        "documents_expected": len(source_records),
        "decision_basis": {
            "highest_value_failure": (
                "the required information object does not exist as a direct, "
                "credential-free, provider-defined historical 1H series"
            ),
            "deribit_1h_dvol": (
                "available but semantically aggregate implied volatility, not skew"
            ),
            "deribit_trade_iv": (
                "available only for recent trades and would require prohibited "
                "cross-sectional strike/expiry reconstruction"
            ),
            "other_official_provider_catalogs": (
                "no direct historical hourly BTC/ETH downside-skew endpoint identified"
            ),
            "paid_or_keyed_historical_skew": (
                "excluded by frozen credential-free contract"
            ),
        },
        "closed_rescues": [
            "Deribit DVOL or another aggregate volatility index as a skew proxy",
            "realised or historical volatility",
            "put/call volume or open-interest ratios",
            "current option-chain summaries",
            "dynamic delta, moneyness, strike or expiry selection",
            "local aggregation of sub-hourly trades, quotes or order books",
            "private, paid, keyed or credentialed history",
            "synthetic or interpolated skew",
            "single-market promotion or provider switching",
        ],
        "canonical_strategy_changed": False,
        "correction_permitted": False,
        "correction_applied": False,
        "observation_epoch_restarted": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "verdict": VERDICT,
        "next_experiment_constraint": (
            "no feature or candidate is defined in this source-contract run; a "
            "subsequent architecture must be separately preregistered"
        ),
    }


def render_report(evidence: dict[str, Any]) -> str:
    lines = [
        "# Direct public 1H options-downside-skew source contract",
        "",
        "```text",
        f"Family                 {evidence['family_id']}",
        f"Tested head            {evidence['tested_head']}",
        f"Candidate count        {evidence['candidate_count']}",
        f"Parameter grid         {evidence['parameter_grid_count']}",
        (
            "Documents retrieved    "
            f"{evidence['documents_retrieved']}/{evidence['documents_expected']}"
        ),
        f"Source arms passing    {evidence['markets_passing_source_contract']}/2",
        f"Performance accessed   {str(evidence['performance_accessed']).lower()}",
        f"OOS accessed           {str(evidence['oos_accessed']).lower()}",
        f"Verdict                {evidence['verdict']}",
        "```",
        "",
        "## Source result",
        "",
        "No reviewed official credential-free provider exposes a direct historical "
        "BTC and ETH downside-skew series at exact UTC 1H resolution. Deribit's "
        "public 1H volatility-index candles are aggregate implied volatility, not "
        "downside skew. Its public option-trade IV history is limited to recent "
        "trades and would require prohibited strike/expiry cross-section "
        "reconstruction.",
        "",
        "## Frozen gate matrix",
        "",
        "| Gate | BTC | ETH | Reason |",
        "|---|---:|---:|---|",
    ]
    for gate in evidence["source_gate"]:
        lines.append(
            f"| {gate['gate']}. {gate['name']} | "
            f"{'PASS' if gate['BTC'] else 'FAIL'} | "
            f"{'PASS' if gate['ETH'] else 'FAIL'} | {gate['reason']} |"
        )
    lines.extend(
        [
            "",
            "## Economics",
            "",
            "Training, OOS, full, benchmark, turnover, drawdown, fold/year, "
            "uncertainty and delay metrics are null rather than zero because the "
            "source contract failed before any target-return access.",
            "",
            "## Disposition",
            "",
            "The exact architecture is rejected at the source contract. No feature, "
            "candidate, target return, sealed OOS observation, strategy mutation, "
            "paper authority or live authority was created.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tested-head", required=True)
    parser.add_argument(
        "--output-dir",
        default="reports/research/options-skew-source-contract-1h-v1",
    )
    args = parser.parse_args()

    if not re.fullmatch(r"[0-9a-f]{40}", args.tested_head):
        raise SystemExit("--tested-head must be a lowercase 40-character SHA")

    output_dir = Path(args.output_dir)
    source_dir = output_dir / "official-documents"
    source_dir.mkdir(parents=True, exist_ok=True)

    source_records = [fetch_source(source, source_dir) for source in SOURCES]
    manifest_bytes = canonical_bytes(source_records)
    (output_dir / "source_manifest.json").write_bytes(manifest_bytes)
    (output_dir / "source_manifest.sha256").write_text(
        sha256_bytes(manifest_bytes) + "\n"
    )

    evidence = build_evidence(args.tested_head, source_records)
    evidence_bytes = canonical_bytes(evidence)
    (output_dir / "evidence.json").write_bytes(evidence_bytes)
    (output_dir / "evidence.sha256").write_text(sha256_bytes(evidence_bytes) + "\n")
    report = render_report(evidence)
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    (output_dir / "report.sha256").write_text(
        sha256_bytes(report.encode()) + "\n"
    )

    print(
        json.dumps(
            {
                "family_id": FAMILY_ID,
                "tested_head": args.tested_head,
                "documents_retrieved": evidence["documents_retrieved"],
                "source_contract_passed": False,
                "performance_accessed": False,
                "oos_accessed": False,
                "verdict": VERDICT,
                "evidence_sha256": sha256_bytes(evidence_bytes),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
