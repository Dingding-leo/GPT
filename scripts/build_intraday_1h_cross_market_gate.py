#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from gpt_quant.artifact_manifest import verify_manifest
from gpt_quant.intraday_1h_source_provenance import (
    verify_intraday_1h_source_provenance,
)

_OUTPUT_NAME = "intraday-cross-market-gate.json"
_EXPECTED_INSTRUMENTS = ("BTC-USDT", "ETH-USDT")
_SEPARATE_DIAGNOSTIC = "separate_not_modeled"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"required persisted artifact is missing: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"persisted artifact is not valid JSON: {path.name}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"persisted artifact must contain a JSON object: {path.name}")
    return value


def _require_mapping(parent: Mapping[str, Any], key: str, *, label: str) -> Mapping[str, Any]:
    value = parent.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"{label}.{key} must be a JSON object")
    return value


def _require_bool(value: Any, *, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be a boolean")
    return value


def _require_string_sequence(value: Any, *, label: str) -> list[str]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise ValueError(f"{label} must be a list of strings")
    parsed = list(value)
    if not all(isinstance(item, str) and item for item in parsed):
        raise ValueError(f"{label} must be a list of strings")
    return parsed


def _modeled_economics() -> dict[str, Any]:
    return {
        "one_way_exchange_fee_bps": 5.0,
        "cost_multipliers": [1.0],
        "spread": _SEPARATE_DIAGNOSTIC,
        "slippage": _SEPARATE_DIAGNOSTIC,
        "market_impact": _SEPARATE_DIAGNOSTIC,
        "latency": _SEPARATE_DIAGNOSTIC,
    }


def _write_payload(output_dir: Path, payload: Mapping[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / _OUTPUT_NAME).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _failure_payload(upstream_result: str, blocker: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "canonical_timeframe": "1H",
        "benchmark_timeframe": "1Dutc",
        "optional_next_timeframe": "15m",
        "upstream_research_result": upstream_result,
        "evidence_integrity_passes": False,
        "modeled_economics": _modeled_economics(),
        "markets": {},
        "research_gate": {
            "cross_market_candidate_eligible": False,
            "blockers": [blocker],
        },
        "promotion": {
            "allow_15m_evaluation": False,
            "allow_paper_promotion": False,
            "allow_limited_capital": False,
            "blockers": [blocker],
        },
    }


def _artifact_directory(artifacts_root: Path, instrument_id: str) -> Path:
    prefix = f"canonical-{instrument_id}-1h-"
    matches = sorted(
        path for path in artifacts_root.iterdir() if path.is_dir() and path.name.startswith(prefix)
    )
    if len(matches) != 1:
        raise ValueError(f"expected exactly one downloaded artifact for {instrument_id}")
    return matches[0]


def _expected_source_binding(
    artifact_dir: Path,
    instrument_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    provenance_path = artifact_dir / "intraday-1h-source-provenance.json"
    provenance = verify_intraday_1h_source_provenance(
        artifact_dir,
        inst_id=instrument_id,
    )
    binding = {
        "source_provenance_sha256": _sha256_file(provenance_path),
        "source_response_inventory_sha256": provenance["source_response_inventory_sha256"],
        "source_response_count": provenance["source_response_count"],
        "source_response_total_bytes": provenance["source_response_total_bytes"],
        "normalized_csv_sha256": provenance["normalized_csv_sha256"],
        "raw_pages_sha256": provenance["raw_pages_sha256"],
        "metadata_sha256": provenance["metadata_sha256"],
        "effective_start": provenance["effective_start"],
        "effective_end": provenance["effective_end"],
        "observations": provenance["observations"],
    }
    return provenance, binding


def _validate_market_artifact(artifact_dir: Path, instrument_id: str) -> dict[str, Any]:
    verify_manifest(artifact_dir)
    manifest_path = artifact_dir / "artifact-manifest.sha256"
    gate_path = artifact_dir / "intraday-promotion-gate.json"
    gate = _load_json_object(gate_path)
    provenance, expected_source_binding = _expected_source_binding(
        artifact_dir,
        instrument_id,
    )

    if gate.get("schema_version") != 1:
        raise ValueError(f"{instrument_id} promotion gate schema must equal 1")
    if gate.get("instrument_id") != instrument_id:
        raise ValueError(f"{instrument_id} promotion gate instrument mismatch")
    if gate.get("bar") != "1H":
        raise ValueError(f"{instrument_id} promotion gate bar must equal 1H")

    economics = _require_mapping(gate, "modeled_economics", label=instrument_id)
    if dict(economics) != _modeled_economics():
        raise ValueError(f"{instrument_id} modeled economics must remain exactly 5 bps-only")

    source_artifacts = _require_mapping(gate, "source_artifacts", label=instrument_id)
    for key, expected in expected_source_binding.items():
        if source_artifacts.get(key) != expected:
            raise ValueError(f"{instrument_id} promotion gate does not bind exact source {key}")

    research = _require_mapping(gate, "research_gate", label=instrument_id)
    eligible = _require_bool(
        research.get("research_candidate_eligible"),
        label=f"{instrument_id}.research_gate.research_candidate_eligible",
    )
    research_blockers = _require_string_sequence(
        research.get("blockers"),
        label=f"{instrument_id}.research_gate.blockers",
    )
    if eligible and research_blockers:
        raise ValueError(f"{instrument_id} eligible research gate cannot contain blockers")
    if not eligible and not research_blockers:
        raise ValueError(f"{instrument_id} rejected research gate must contain blockers")

    promotion = _require_mapping(gate, "promotion", label=instrument_id)
    allow_15m = _require_bool(
        promotion.get("allow_15m_evaluation"),
        label=f"{instrument_id}.promotion.allow_15m_evaluation",
    )
    allow_paper = _require_bool(
        promotion.get("allow_paper_promotion"),
        label=f"{instrument_id}.promotion.allow_paper_promotion",
    )
    allow_capital = _require_bool(
        promotion.get("allow_limited_capital"),
        label=f"{instrument_id}.promotion.allow_limited_capital",
    )
    paper_blockers = _require_string_sequence(
        promotion.get("paper_blockers"),
        label=f"{instrument_id}.promotion.paper_blockers",
    )
    if allow_15m != eligible:
        raise ValueError(f"{instrument_id} 15m permission must equal research eligibility")
    if allow_paper or allow_capital or not paper_blockers:
        raise ValueError(f"{instrument_id} paper and capital promotion must remain blocked")

    return {
        "artifact_manifest_sha256": _sha256_file(manifest_path),
        "promotion_gate_sha256": _sha256_file(gate_path),
        "source_provenance_sha256": expected_source_binding["source_provenance_sha256"],
        "source_response_inventory_sha256": provenance["source_response_inventory_sha256"],
        "source_response_count": provenance["source_response_count"],
        "source_response_total_bytes": provenance["source_response_total_bytes"],
        "effective_start": provenance["effective_start"],
        "effective_end": provenance["effective_end"],
        "observations": provenance["observations"],
        "research_candidate_eligible": eligible,
        "research_blockers": research_blockers,
        "paper_blockers": paper_blockers,
    }


def build_intraday_1h_cross_market_gate(
    artifacts_root: str | Path,
    output_dir: str | Path,
    *,
    upstream_result: str,
) -> dict[str, Any]:
    output = Path(output_dir)
    if upstream_result != "success":
        payload = _failure_payload(
            upstream_result,
            f"canonical_1h_research_{upstream_result}",
        )
        _write_payload(output, payload)
        return payload

    root = Path(artifacts_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("downloaded artifact root must be a directory")

    markets: dict[str, dict[str, Any]] = {}
    research_blockers: list[str] = []
    paper_blockers: set[str] = set()
    for instrument_id in _EXPECTED_INSTRUMENTS:
        market = _validate_market_artifact(
            _artifact_directory(root, instrument_id),
            instrument_id,
        )
        markets[instrument_id] = market
        research_blockers.extend(
            f"{instrument_id}:{blocker}" for blocker in market["research_blockers"]
        )
        paper_blockers.update(market["paper_blockers"])

    eligible = all(markets[item]["research_candidate_eligible"] for item in _EXPECTED_INSTRUMENTS)
    launch_blockers = research_blockers + sorted(paper_blockers)
    payload = {
        "schema_version": 1,
        "canonical_timeframe": "1H",
        "benchmark_timeframe": "1Dutc",
        "optional_next_timeframe": "15m",
        "upstream_research_result": upstream_result,
        "evidence_integrity_passes": True,
        "modeled_economics": _modeled_economics(),
        "markets": markets,
        "research_gate": {
            "cross_market_candidate_eligible": eligible,
            "blockers": research_blockers,
        },
        "promotion": {
            "allow_15m_evaluation": eligible,
            "allow_paper_promotion": False,
            "allow_limited_capital": False,
            "blockers": launch_blockers,
        },
    }
    _write_payload(output, payload)
    return payload


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Aggregate verified BTC and ETH 1h artifacts into one launch-blocker gate."
    )
    parser.add_argument("--artifacts-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--upstream-result", required=True)
    parser.add_argument(
        "--enforce-research-promotion",
        action="store_true",
        help="Exit nonzero unless both canonical 1h candidates clear the research gate.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_args(argv)
    output_dir = Path(arguments.output_dir)
    try:
        payload = build_intraday_1h_cross_market_gate(
            arguments.artifacts_root,
            output_dir,
            upstream_result=arguments.upstream_result,
        )
    except (OSError, ValueError) as exc:
        payload = _failure_payload(
            arguments.upstream_result,
            "cross_market_evidence_validation_failed",
        )
        _write_payload(output_dir, payload)
        print(str(exc), file=sys.stderr)
        return 2

    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    if (
        arguments.enforce_research_promotion
        and not payload["research_gate"]["cross_market_candidate_eligible"]
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
