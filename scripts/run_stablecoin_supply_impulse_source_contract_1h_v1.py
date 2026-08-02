#!/usr/bin/env python3
"""Reject or accept the frozen stablecoin-supply 1H source contract."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

FAMILY_ID = "causal-stablecoin-supply-impulse-source-contract-1h-v1"
ACCEPT_VERDICT = "accept_causal_stablecoin_supply_impulse_source_contract_1h_v1"
REJECT_VERDICT = "reject_causal_stablecoin_supply_impulse_source_contract_1h_v1"
MAIN_HEAD = "5a0fcc97d1a882f8223656c51f5bb8055f534e38"
BAR = "1H"
ONE_WAY_FEE_BPS = 5.0
RECORDS_PATH = Path(__file__).with_name(
    "stablecoin_supply_impulse_source_contract_1h_v1_records.json"
)


def canonical_bytes(value: Any) -> bytes:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return f"{payload}\n".encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def write_json(path: Path, value: Any) -> str:
    payload = canonical_bytes(value)
    path.write_bytes(payload)
    return sha256_bytes(payload)


def write_text(path: Path, value: str) -> str:
    payload = value.encode()
    path.write_bytes(payload)
    return sha256_bytes(payload)


def load_records() -> dict[str, Any]:
    records = json.loads(RECORDS_PATH.read_text())
    if records["family_id"] != FAMILY_ID:
        raise SystemExit("unexpected family identity")
    if records["canonical_main_head"] != MAIN_HEAD:
        raise SystemExit("unexpected canonical main identity")
    if records["bar"] != BAR:
        raise SystemExit("source contract is not exact 1H")
    if records["one_way_fee_bps_if_later_authorized"] != ONE_WAY_FEE_BPS:
        raise SystemExit("fee contract drifted from exactly 5 bps one way")
    if [row["stablecoin"] for row in records["source_arms"]] != ["USDT", "USDC"]:
        raise SystemExit("unexpected source-arm identity or order")
    return records


def build_summary(records: dict[str, Any]) -> dict[str, Any]:
    providers = records["providers"]
    arms = records["source_arms"]
    qualifying = [row for row in providers if row["qualifies"]]
    return {
        "provider_interfaces_audited": len(providers),
        "qualifying_provider_interfaces": len(qualifying),
        "anonymous_direct_historical_1h_interfaces": sum(
            bool(row["anonymous_public_access"] is True)
            and bool(row["historical_access"])
            and bool(row["documented_exact_utc_1h_contract"])
            and bool(row["complete_frozen_1h_history_proven"])
            and not bool(row["reconstruction_required_for_exact_1h"])
            for row in providers
        ),
        "source_arms_expected": len(arms),
        "source_arms_passing": sum(bool(row["passed"]) for row in arms),
        "expected_rows_per_arm": records["frozen_sample"]["expected_rows_per_arm"],
        "observed_qualifying_rows_total": sum(
            int(row["observed_qualifying_rows"]) for row in arms
        ),
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "performance_accessed": False,
        "oos_accessed": False,
        "new_target_prices_or_returns": 0,
        "canonical_mutation": False,
    }


def build_gates(records: dict[str, Any], summary: dict[str, Any]) -> dict[str, bool]:
    providers = records["providers"]
    arms = records["source_arms"]
    return {
        "fixed_provider_catalog_bound": (
            records["provider_catalog_frozen_before_source_verdict"]
            and [row["provider_id"] for row in providers]
            == [
                "defillama-stablecoins",
                "coin-metrics-community",
                "coingecko",
                "circle",
                "tether",
                "etherscan-token-supply",
            ]
        ),
        "direct_supply_semantics_audited": all(
            bool(row["supply_semantics"]) for row in providers
        ),
        "exact_completed_utc_1h_history_proven": all(
            bool(row["documented_exact_utc_1h_contract"])
            and bool(row["complete_frozen_1h_history_proven"])
            for row in providers
            if row["qualifies"]
        )
        and bool(summary["qualifying_provider_interfaces"]),
        "anonymous_public_access_proven": all(
            row["anonymous_public_access"] is True
            and not bool(row["credentials_or_paid_entitlement_required"])
            for row in providers
            if row["qualifies"]
        )
        and bool(summary["qualifying_provider_interfaces"]),
        "no_reconstruction_or_expansion_required": all(
            not bool(row["reconstruction_required_for_exact_1h"])
            for row in providers
            if row["qualifies"]
        )
        and bool(summary["qualifying_provider_interfaces"]),
        "identical_provider_semantics_for_usdt_and_usdc": (
            len(arms[0]["qualifying_provider_ids"]) > 0
            and arms[0]["qualifying_provider_ids"]
            == arms[1]["qualifying_provider_ids"]
        ),
        "complete_bilateral_source_arms": (
            summary["source_arms_passing"] == summary["source_arms_expected"]
            and all(
                row["observed_qualifying_rows"] == row["expected_rows"]
                for row in arms
            )
        ),
        "performance_and_oos_remained_sealed": (
            not summary["performance_accessed"]
            and not summary["oos_accessed"]
            and summary["new_target_prices_or_returns"] == 0
        ),
    }


def build_report(evidence: dict[str, Any]) -> str:
    summary = evidence["summary"]
    lines = [
        "# Stablecoin Supply Impulse Source Contract — 1H V1",
        "",
        "## Verdict",
        "",
        f"`{evidence['verdict']}`",
        "",
        (
            "No audited provider supplied a complete, direct, anonymous, "
            "provider-defined historical UTC 1H aggregate circulating-supply "
            "series for both USDT and USDC over the frozen sample."
        ),
        "",
        "## Frozen scope",
        "",
        f"- Tested head: `{evidence['tested_head']}`",
        f"- Canonical main: `{evidence['canonical_main_head']}`",
        f"- Bar: `{evidence['bar']}`",
        (
            "- Frozen sample: "
            f"`{evidence['frozen_sample']['start_utc']}` through "
            f"`{evidence['frozen_sample']['end_utc']}`"
        ),
        (
            "- Expected rows per stablecoin arm: "
            f"`{summary['expected_rows_per_arm']}`"
        ),
        "- Fixed stablecoin arms: `USDT`, `USDC`",
        "- Candidate count and parameter grid: `0`, `0`",
        "- Target prices, returns, performance and OOS: not accessed",
        "",
        "## Source matrix",
        "",
        (
            "| Provider | Direct supply semantics | Anonymous | Historical | "
            "Exact complete 1H | Reconstruction-free | Result |"
        ),
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for provider in evidence["providers"]:
        anonymous = provider["anonymous_public_access"] is True
        lines.append(
            f"| {provider['provider_id']} | yes | "
            f"{'yes' if anonymous else 'no'} | "
            f"{'yes' if provider['historical_access'] else 'no'} | "
            f"{'yes' if provider['complete_frozen_1h_history_proven'] else 'no'} | "
            f"{'no' if provider['reconstruction_required_for_exact_1h'] else 'yes'} | "
            f"{'pass' if provider['qualifies'] else 'fail'} |"
        )
    lines.extend(
        [
            "",
            "## Provider findings",
            "",
            (
                "- DefiLlama exposes public historical stablecoin chart objects, "
                "but no official exact completed-UTC-hour contract was found; "
                "creating a full 1H calendar would require expansion or reconstruction."
            ),
            (
                "- Coin Metrics defines `SplyCur` at native `1d` frequency, "
                "not direct 1H."
            ),
            (
                "- CoinGecko circulating-supply history requires an API key; "
                "the range endpoint is Enterprise-only and the frozen multi-year "
                "range is documented at daily granularity."
            ),
            (
                "- Circle exposes current aggregate USDC supply but no complete "
                "historical hourly range; Tether describes circulation metrics "
                "as typically refreshed daily."
            ),
            (
                "- Etherscan requires an API key, places historical token supply "
                "behind PRO access, and returns chain-specific supply by block, "
                "which would require forbidden block-time and multi-chain reconstruction."
            ),
            "",
            "## Economic record",
            "",
            (
                "All training, OOS, full-sample, benchmark, turnover, fee-drag, "
                "drawdown, edge-per-turnover, breadth, uncertainty and delay "
                "fields are null rather than zero because no qualifying source "
                "panel or candidate existed."
            ),
            "",
            "## Source-arm result",
            "",
            (
                f"- Source arms passing: `{summary['source_arms_passing']}/"
                f"{summary['source_arms_expected']}`"
            ),
            (
                "- Qualifying historical observations acquired: "
                f"`{summary['observed_qualifying_rows_total']}`"
            ),
            "",
            "## Canonical disposition",
            "",
            (
                "No strategy, target return, feature state, canonical mutation, "
                "paper authority or live authority was created. The exact source "
                "architecture is rejected; the broader hypothesis that supply "
                "changes can matter economically is not tested."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tested-head", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    if len(args.tested_head) != 40 or any(
        character not in "0123456789abcdef" for character in args.tested_head
    ):
        raise SystemExit("tested head must be a lowercase 40-character git SHA")

    records = load_records()
    summary = build_summary(records)
    gates = build_gates(records, summary)
    bilateral_pass = all(
        gates[name]
        for name in (
            "exact_completed_utc_1h_history_proven",
            "anonymous_public_access_proven",
            "no_reconstruction_or_expansion_required",
            "identical_provider_semantics_for_usdt_and_usdc",
            "complete_bilateral_source_arms",
        )
    )
    verdict = ACCEPT_VERDICT if bilateral_pass else REJECT_VERDICT

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    source_records = {
        **records,
        "tested_head": args.tested_head,
    }
    source_records_sha = write_json(
        output_dir / "source_records.json",
        source_records,
    )
    write_text(
        output_dir / "source_records.sha256",
        f"{source_records_sha}  source_records.json\n",
    )

    evidence = {
        "family_id": FAMILY_ID,
        "classification": records["classification"],
        "canonical_main_head": MAIN_HEAD,
        "tested_head": args.tested_head,
        "bar": BAR,
        "one_way_fee_bps_if_later_authorized": ONE_WAY_FEE_BPS,
        "frozen_sample": records["frozen_sample"],
        "fixed_exogenous_arms": records["fixed_exogenous_arms"],
        "fixed_target_mappings": records["fixed_target_mappings"],
        "summary": summary,
        "providers": records["providers"],
        "source_arms": records["source_arms"],
        "gates": gates,
        "economics": records["economics"],
        "hard_boundary": {
            "same_instrument_future_long_cash": True,
            "cross_sectional_ranking_or_selection": False,
            "pairs_spreads_or_cointegration": False,
            "market_neutral_long_short": False,
            "post_hoc_asset_filtering": False,
            "credentials_accounts_orders_or_leverage": False,
            "synthetic_or_repaired_data": False,
            "non_1h_or_15m": False,
        },
        "performance_accessed": False,
        "oos_accessed": False,
        "canonical_mutation": False,
        "paper_trading_authority": False,
        "live_trading_authority": False,
        "verdict": verdict,
        "source_records_sha256": source_records_sha,
    }

    evidence_sha = write_json(output_dir / "evidence.json", evidence)
    write_text(
        output_dir / "evidence.sha256",
        f"{evidence_sha}  evidence.json\n",
    )
    report_sha = write_text(
        output_dir / "report.md",
        build_report(evidence),
    )
    write_text(
        output_dir / "report.sha256",
        f"{report_sha}  report.md\n",
    )

    print(
        json.dumps(
            {
                "verdict": verdict,
                "summary": summary,
                "gates": gates,
                "evidence_sha256": evidence_sha,
                "source_records_sha256": source_records_sha,
                "report_sha256": report_sha,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
