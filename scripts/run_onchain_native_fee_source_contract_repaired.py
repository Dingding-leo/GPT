#!/usr/bin/env python3
"""Repair official FeeTotNtv semantics binding, then execute issue #1030."""
from __future__ import annotations

import html
import json
import re
import urllib.parse
from typing import Any

import run_onchain_native_fee_source_contract as core

DOCS_URL = (
    "https://gitbook-docs.coinmetrics.io/network-data/network-data-overview/"
    "fees-and-revenue/fees"
)
REFERENCE_DOCS_URL = (
    "https://docs.coinmetrics.io/network-data/network-data-overview/"
    "fees-and-revenue/fees"
)


def normalize_document(raw: bytes) -> str:
    """Convert the official rendered documentation into searchable plain text."""
    try:
        value = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise core.SourceContractError("official fee documentation is not UTF-8") from exc
    value = html.unescape(value).lower()
    replacements = {
        "\\n": " ",
        "\\t": " ",
        '\\"': '"',
        "\\u0026": "&",
        "\\u002f": "/",
    }
    for source, replacement in replacements.items():
        value = value.replace(source, replacement)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value)


def validate_docs_url(url: str) -> None:
    """Require the exact public Coin Metrics documentation origin and path."""
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "gitbook-docs.coinmetrics.io"
        or parsed.path
        != "/network-data/network-data-overview/fees-and-revenue/fees"
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise core.SourceContractError(f"untrusted Coin Metrics documentation URL: {url}")


def freeze_semantics() -> dict[str, Any]:
    """Bind compact API reference metadata to the detailed official metric definition."""
    payloads, manifest = core.follow_pages(
        initial_url=core.reference_url(),
        path=core.REFERENCE_PATH,
        directory=core.SOURCE / "reference",
        purpose="FeeTotNtv official reference",
    )
    rows = [row for payload in payloads for row in payload["data"]]
    matches = [
        row
        for row in rows
        if isinstance(row, dict) and row.get("metric") == core.METRIC
    ]
    if len(matches) != 1:
        raise core.SourceContractError(
            f"official reference returned {len(matches)} exact {core.METRIC} rows"
        )
    row = matches[0]
    full_name = row.get("full_name")
    description = row.get("description")
    unit = row.get("unit")
    metric_type = row.get("type")
    docs_url = row.get("docs_url")
    if not all(
        isinstance(value, str) and value
        for value in (full_name, description, unit, docs_url)
    ):
        raise core.SourceContractError(
            "FeeTotNtv official reference semantics are incomplete"
        )
    compact_semantics = " ".join((full_name, description, unit)).lower()
    if "fee" not in compact_semantics or "native" not in unit.lower():
        raise core.SourceContractError(
            "FeeTotNtv compact reference does not identify native-unit fees"
        )
    if docs_url != REFERENCE_DOCS_URL:
        raise core.SourceContractError(
            f"FeeTotNtv reference bound an unexpected documentation URL: {docs_url}"
        )

    validate_docs_url(DOCS_URL)
    raw = core.fetch(DOCS_URL, byte_limit=15_000_000)
    docs_record = core.persist_response(
        directory=core.SOURCE / "reference",
        filename="fees-doc.html",
        url=DOCS_URL,
        raw=raw,
        provider="Coin Metrics official documentation",
        page=None,
    )
    text = normalize_document(raw)
    required_terms = (
        "feetotntv",
        "native units",
        "miner",
        "validator",
        "staker",
        "block producer",
        "burn",
        "included in total fees",
    )
    missing = [term for term in required_terms if term not in text]
    hourly_supported = bool(
        re.search(r"1\s*day\s*,\s*1\s*hour", text)
        or re.search(r"1\s*hour\s*,\s*1\s*day", text)
    )
    if missing or not hourly_supported:
        raise core.SourceContractError(
            "official detailed FeeTotNtv documentation failed semantic binding: "
            f"missing_terms={missing} hourly_supported={hourly_supported}"
        )
    if metric_type is not None and not isinstance(metric_type, str):
        raise core.SourceContractError("FeeTotNtv reference type has invalid schema")
    return {
        "metric": core.METRIC,
        "full_name": full_name,
        "description": description,
        "unit": unit,
        "type": metric_type,
        "reference_docs_url": docs_url,
        "reference_manifest": manifest,
        "reference_rows_sha256": core.sha256_bytes(core.canonical_bytes(matches)),
        "detailed_documentation": docs_record,
        "detailed_documentation_sha256": core.sha256_bytes(raw),
        "direct_1h_documentation_support": True,
        "burned_fee_accounting_documented": True,
        "semantic_gate_passed": True,
    }


def main() -> None:
    """Execute the unchanged source contract with repaired semantic evidence binding."""
    core.freeze_semantics = freeze_semantics
    result = core.run()
    print(
        json.dumps(
            {
                "family_id": result["family_id"],
                "exact_head": result["exact_head"],
                "source_arms_passing": result["source_arms_passing"],
                "source_contract_passed": result["source_contract_passed"],
                "performance_accessed": result["performance_accessed"],
                "oos_accessed": result["oos_accessed"],
                "verdict": result["verdict"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
