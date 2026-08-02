from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FAMILY_ID = "causal-options-term-structure-shape-source-contract-1h-v1"
PASS_VERDICT = (
    "accept_options_term_structure_shape_1h_source_for_separate_training_only_predeclaration"
)
FAIL_VERDICT = "reject_causal_options_term_structure_shape_source_contract_1h_v1"
REPOSITORY_MAIN = "5a0fcc97d1a882f8223656c51f5bb8055f534e38"
START = "2023-04-01T00:00:00Z"
END = "2025-12-31T23:00:00Z"
EXPECTED_ROWS = 24_144
MAX_BYTES = 12_000_000

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

# The interface catalog is frozen before retrieval. Classification expresses the
# documented API object, not a post-result statistical interpretation.
INTERFACES: tuple[dict[str, Any], ...] = (
    {
        "interface_id": "deribit_volatility_index_data",
        "provider": "Deribit",
        "url": (
            "https://docs.deribit.com/api-reference/market-data/public-get_volatility_index_data.md"
        ),
        "documented_object": "aggregate provider volatility-index OHLC history",
        "historical": True,
        "direct_1h": True,
        "implied_volatility": True,
        "realized_volatility": False,
        "fixed_maturity_dimension": False,
        "direct_term_structure_shape": False,
        "reconstruction_required": False,
        "bilateral_btc_eth": True,
        "failure_reason": (
            "one aggregate forward-IV index per currency; no near/far maturity dimension"
        ),
        "markers": ("volatility index", "3600", "open", "high", "low", "close"),
    },
    {
        "interface_id": "deribit_mark_price_history",
        "provider": "Deribit",
        "url": (
            "https://docs.deribit.com/api-reference/market-data/public-get_mark_price_history.md"
        ),
        "documented_object": "per-instrument historical mark prices",
        "historical": True,
        "direct_1h": False,
        "implied_volatility": False,
        "realized_volatility": False,
        "fixed_maturity_dimension": False,
        "direct_term_structure_shape": False,
        "reconstruction_required": True,
        "bilateral_btc_eth": True,
        "failure_reason": (
            "5-minute per-contract mark history requires dynamic "
            "option/expiry/strike reconstruction"
        ),
        "markers": ("instrument_name", "start_timestamp", "end_timestamp"),
    },
    {
        "interface_id": "deribit_option_ticker",
        "provider": "Deribit",
        "url": "https://docs.deribit.com/api-reference/market-data/public-ticker",
        "documented_object": "current per-instrument ticker including option IV fields",
        "historical": False,
        "direct_1h": False,
        "implied_volatility": True,
        "realized_volatility": False,
        "fixed_maturity_dimension": False,
        "direct_term_structure_shape": False,
        "reconstruction_required": True,
        "bilateral_btc_eth": True,
        "failure_reason": (
            "current per-option snapshot; no direct historical hourly maturity-shape series"
        ),
        "markers": ("mark_iv", "bid_iv", "ask_iv", "instrument_name"),
    },
    {
        "interface_id": "deribit_historical_volatility",
        "provider": "Deribit",
        "url": (
            "https://docs.deribit.com/api-reference/market-data/public-get_historical_volatility"
        ),
        "documented_object": "historical realised-volatility observations",
        "historical": True,
        "direct_1h": True,
        "implied_volatility": False,
        "realized_volatility": True,
        "fixed_maturity_dimension": False,
        "direct_term_structure_shape": False,
        "reconstruction_required": False,
        "bilateral_btc_eth": True,
        "failure_reason": (
            "backward-looking realised volatility, not option-implied maturity term structure"
        ),
        "markers": ("historical volatility", "currency"),
    },
    {
        "interface_id": "bybit_historical_volatility",
        "provider": "Bybit",
        "url": "https://bybit-exchange.github.io/docs/v5/market/iv",
        "documented_object": "historical-volatility series with trailing period choices",
        "historical": True,
        "direct_1h": True,
        "implied_volatility": False,
        "realized_volatility": True,
        "fixed_maturity_dimension": False,
        "direct_term_structure_shape": False,
        "reconstruction_required": False,
        "bilateral_btc_eth": True,
        "failure_reason": (
            "periods are historical-volatility lookbacks, not option expiry tenors or forward IV"
        ),
        "markers": ("historical volatility", "period", "7", "14", "30", "180"),
    },
    {
        "interface_id": "okx_option_trades",
        "provider": "OKX",
        "url": "https://www.okx.com/docs-v5/en/#rest-api-public-data-get-option-trades",
        "documented_object": "recent public option trades by contract",
        "historical": False,
        "direct_1h": False,
        "implied_volatility": False,
        "realized_volatility": False,
        "fixed_maturity_dimension": False,
        "direct_term_structure_shape": False,
        "reconstruction_required": True,
        "bilateral_btc_eth": True,
        "failure_reason": (
            "recent per-contract trades require chain, expiry and moneyness reconstruction"
        ),
        "markers": ("option trades", "instId", "tradeId"),
    },
)


def canonical(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def retrieve(url: str) -> tuple[bytes | None, dict[str, Any]]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Dingding-leo-GPT-options-term-structure-source-contract/1.0",
            "Accept": "text/markdown,text/html,text/plain;q=0.9,*/*;q=0.8",
        },
    )
    errors: list[str] = []
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                body = response.read(MAX_BYTES + 1)
                if len(body) > MAX_BYTES:
                    raise ValueError("official document exceeds byte cap")
                return body, {
                    "retrieval_succeeded": True,
                    "attempt": attempt,
                    "request_url": url,
                    "final_url": response.geturl(),
                    "http_status": getattr(response, "status", 200),
                    "content_type": response.headers.get("Content-Type"),
                    "bytes": len(body),
                    "sha256": digest(body),
                }
        except (OSError, ValueError, urllib.error.URLError) as exc:
            errors.append(f"attempt {attempt}: {type(exc).__name__}: {exc}")
            if attempt < 3:
                time.sleep(attempt)
    return None, {
        "retrieval_succeeded": False,
        "request_url": url,
        "final_url": None,
        "http_status": None,
        "bytes": 0,
        "sha256": None,
        "errors": errors,
    }


def audit_interface(root: Path, spec: dict[str, Any]) -> dict[str, Any]:
    body, metadata = retrieve(spec["url"])
    path = root / "official-docs" / f"{spec['interface_id']}.bin"
    path.parent.mkdir(parents=True, exist_ok=True)
    if body is not None:
        path.write_bytes(body)
        text = body.decode("utf-8", errors="replace").lower()
    else:
        text = ""
    marker_counts = {marker: text.count(marker.lower()) for marker in spec["markers"]}
    qualifies = all(
        (
            spec["historical"],
            spec["direct_1h"],
            spec["implied_volatility"],
            spec["fixed_maturity_dimension"],
            spec["direct_term_structure_shape"],
            not spec["reconstruction_required"],
            spec["bilateral_btc_eth"],
        )
    )
    return {
        **{key: value for key, value in spec.items() if key != "markers"},
        **metadata,
        "saved_path": path.as_posix() if body is not None else None,
        "marker_counts": marker_counts,
        "qualifies_direct_source_contract": qualifies,
    }


def render_report(evidence: dict[str, Any]) -> str:
    rows = []
    for interface in evidence["interfaces"]:
        rows.append(
            "| {provider} | {interface_id} | {historical} | {direct_1h} | {implied_volatility} | "
            "{fixed_maturity_dimension} | {reconstruction_required} | "
            "{qualifies_direct_source_contract} | {failure_reason} |".format(**interface)
        )
    table = "\n".join(rows)
    table_header = (
        "| Provider | Interface | Historical | Direct 1H | Implied vol | "
        "Fixed maturity | Reconstruction | Qualifies | Terminal reason |"
    )
    table_separator = "|---|---|---:|---:|---:|---:|---:|---:|---|"
    gates = "\n".join(
        f"- Gate {index}: {'PASS' if gate['passed'] else 'FAIL'} — {gate['name']}"
        for index, gate in enumerate(evidence["source_gates"], start=1)
    )
    return f"""# Direct public 1H options term-structure source contract

```text
family                 {evidence["family_id"]}
tested head            {evidence["tested_head"]}
fixed arms             BTC options -> BTC-USDT; ETH options -> ETH-USDT
source interval        {evidence["source_interval"]["start"]}
                       through {evidence["source_interval"]["end"]}
expected rows          {evidence["source_interval"]["expected_rows"]} per arm
interfaces audited     {len(evidence["interfaces"])}
qualifying interfaces  {evidence["qualifying_interface_count"]}
source arms passing    {evidence["markets_passing_source_contract"]}/2
candidate count        0
performance accessed   no
OOS accessed           no
verdict                {evidence["verdict"]}
```

## Interface audit

{table_header}
{table_separator}
{table}

## Frozen source gates

{gates}

No reviewed official interface supplies a provider-defined historical BTC and ETH
near-versus-far implied-volatility shape at direct UTC 1H resolution. Aggregate
DVOL lacks a maturity axis; historical-volatility endpoints are realised-volatility
series; option ticker, trade and mark-price interfaces are current, recent,
per-contract or sub-hourly and require prohibited chain/expiry/strike reconstruction.

No target prices, returns, feature states, candidate economics or sealed OOS values
were accessed. All economic fields are null rather than zero. The result rejects
this exact direct-public source architecture, not the economic possibility that
options term structure contains information.
"""


def run(tested_head: str, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    interfaces = [audit_interface(output_dir, spec) for spec in INTERFACES]
    qualifying = [item for item in interfaces if item["qualifies_direct_source_contract"]]
    source_passed = bool(qualifying)

    source_gates = [
        {
            "name": "official interface catalog retrieved and hash-bound",
            "passed": all(item["retrieval_succeeded"] for item in interfaces),
        },
        {
            "name": "provider-defined implied volatility rather than realised volatility",
            "passed": any(item["implied_volatility"] for item in qualifying),
        },
        {
            "name": "fixed provider-defined near/far maturity dimension",
            "passed": any(item["fixed_maturity_dimension"] for item in qualifying),
        },
        {
            "name": "direct provider 1H historical observations",
            "passed": any(item["historical"] and item["direct_1h"] for item in qualifying),
        },
        {
            "name": "no option-chain, strike, expiry or moneyness reconstruction",
            "passed": any(not item["reconstruction_required"] for item in qualifying),
        },
        {
            "name": "complete frozen bilateral BTC and ETH coverage possible",
            "passed": source_passed,
        },
        {
            "name": "causal availability and replayable pagination can be established",
            "passed": source_passed,
        },
        {
            "name": "repeat acquisition and future-prefix invariance can be established",
            "passed": source_passed,
        },
        {"name": "prohibited trading and private capabilities absent", "passed": True},
        {
            "name": "missing or ambiguous source fails closed before performance",
            "passed": not source_passed,
        },
    ]

    evidence = {
        "family_id": FAMILY_ID,
        "tested_head": tested_head,
        "repository_main": REPOSITORY_MAIN,
        "created_at_utc": utc_now(),
        "classification": "source-contract-first options-information experiment",
        "bar": "1H",
        "canonical_fee_bps_one_way": 5.0,
        "source_interval": {"start": START, "end": END, "expected_rows": EXPECTED_ROWS},
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "interface_count": len(interfaces),
        "qualifying_interface_count": len(qualifying),
        "interfaces": interfaces,
        "source_gates": source_gates,
        "source_contract_passed": source_passed,
        "markets_passing_source_contract": 2 if source_passed else 0,
        "market_arms": [
            {
                "currency": currency,
                "target": f"{currency}-USDT",
                "expected_rows": EXPECTED_ROWS,
                "observed_rows": 0,
                "source_contract_passed": source_passed,
                "economics": dict(NULL_ECONOMICS),
            }
            for currency in ("BTC", "ETH")
        ],
        "target_spot_data_downloaded": False,
        "target_returns_downloaded": False,
        "options_market_data_downloaded": False,
        "feature_defined": False,
        "candidate_created": False,
        "performance_accessed": False,
        "oos_accessed": False,
        "synthetic_data_used": False,
        "cross_sectional_selection": False,
        "pairs_or_spreads": False,
        "market_neutral_or_long_short": False,
        "credentials_used": False,
        "private_endpoints_used": False,
        "accounts_or_orders": False,
        "enabled_adapters": False,
        "leverage_used": False,
        "canonical_strategy_changed": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "verdict": PASS_VERDICT if source_passed else FAIL_VERDICT,
        "remaining_blocker": (
            "no direct provider-defined credential-free historical BTC/ETH "
            "1H implied-volatility maturity-shape series"
        ),
    }

    manifest = {
        "family_id": FAMILY_ID,
        "tested_head": tested_head,
        "documents": [
            {
                "interface_id": item["interface_id"],
                "provider": item["provider"],
                "request_url": item["request_url"],
                "final_url": item["final_url"],
                "http_status": item["http_status"],
                "bytes": item["bytes"],
                "sha256": item["sha256"],
                "saved_path": item["saved_path"],
            }
            for item in interfaces
        ],
    }

    evidence_bytes = canonical(evidence)
    manifest_bytes = canonical(manifest)
    report = render_report(evidence)
    (output_dir / "evidence.json").write_bytes(evidence_bytes)
    (output_dir / "evidence.sha256").write_text(digest(evidence_bytes) + "\n")
    (output_dir / "source_manifest.json").write_bytes(manifest_bytes)
    (output_dir / "source_manifest.sha256").write_text(digest(manifest_bytes) + "\n")
    (output_dir / "report.md").write_text(report)
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tested-head", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    evidence = run(args.tested_head, args.output_dir)
    print(
        json.dumps(
            {
                "verdict": evidence["verdict"],
                "qualifying_interfaces": evidence["qualifying_interface_count"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
