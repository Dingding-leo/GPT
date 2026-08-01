from __future__ import annotations

import argparse
import json
from base64 import b64encode
from pathlib import Path
from typing import Any

import run_okx_l2_bid_replenishment_diagnostic as core
import run_okx_l2_concentration_diagnostic as experiment

VERDICT = "reject_public_okx_l2_concentration_source_feasibility"


def terminal_evidence(
    output_dir: Path,
    *,
    responses: list[dict[str, Any]],
    records: list[dict[str, Any]],
    market: str,
    anchor: str,
    reason: str,
) -> dict[str, Any]:
    source_manifest = {
        "family_id": experiment.FAMILY_ID,
        "provider": "OKX",
        "endpoint": f"https://www.okx.com{core.ENDPOINT_PATH}",
        "module": core.MODULE,
        "module_description": "400-level order-book history",
        "markets": list(experiment.MARKETS),
        "anchor_dates_utc": list(experiment.ANCHOR_DATES),
        "metadata_responses": responses,
        "source_objects_resolved_before_failure": records,
        "required_source_object_count": 48,
        "resolved_source_object_count": len(records),
        "failed_market": market,
        "failed_anchor_date_utc": anchor,
        "failure_reason": reason,
        "source_feasible": False,
        "economic_values_read": False,
    }
    manifest_bytes = core.canonical_json(source_manifest)
    (output_dir / "source-manifest.json").write_bytes(manifest_bytes)
    evidence = {
        "family_id": experiment.FAMILY_ID,
        "classification": "training-only information diagnostic",
        "candidate_count": 0,
        "diagnostic_count": 1,
        "parameter_grid_count": 0,
        "markets": list(experiment.MARKETS),
        "timeframe": "1H",
        "label_horizon_hours": experiment.LABEL_HOURS,
        "fee_one_way": experiment.FEE_ONE_WAY,
        "round_trip_label_fee": experiment.ROUND_TRIP_LABEL_FEE,
        "new_oos_consumed": False,
        "source_feasible": False,
        "required_source_objects": 48,
        "resolved_source_objects": len(records),
        "attempted_metadata_responses": len(responses),
        "failed_market": market,
        "failed_anchor_date_utc": anchor,
        "failure_reason": reason,
        "economic_values_read": False,
        "source_manifest_sha256": core.sha256(manifest_bytes),
        "accepted": False,
        "verdict": VERDICT,
        "performance": {
            "training_return": None,
            "training_sharpe": None,
            "oos_return": None,
            "oos_sharpe": None,
            "full_return": None,
            "full_sharpe": None,
            "benchmark_comparison": None,
            "maximum_drawdown": None,
            "turnover": None,
            "edge_per_turnover": None,
            "reason": "complete mandatory immutable public source cohort is infeasible",
        },
    }
    (output_dir / "evidence.json").write_bytes(core.canonical_json(evidence))
    report = f"""# OKX L2 persistent near-touch concentration source gate

```text
family              {experiment.FAMILY_ID}
candidate count     0
required objects    48
resolved objects    {len(records)}
attempted responses {len(responses)}
failed object       {market} {anchor}
economic values     unread
verdict             {VERDICT}
```

The official anonymous OKX metadata endpoint returned no usable mandatory 400-level SPOT order-book object for the failed market/date. The preregistered contract prohibits partial days, replacement dates, another venue, live capture, REST books, synthetic books, or sampled top-of-book substitution. Training/OOS/full performance, benchmark comparison, drawdown, turnover and edge per turnover were therefore not computed.

Failure detail: `{reason}`
"""
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    return evidence


def acquire(base_url: str, output_dir: Path) -> dict[str, Any]:
    experiment.configure_core()
    if base_url.rstrip("/") != "https://www.okx.com":
        raise ValueError("base URL must be exactly https://www.okx.com")
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = output_dir / "metadata-responses"
    raw_dir.mkdir(exist_ok=True)
    responses: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    for market in experiment.MARKETS:
        for anchor in experiment.ANCHOR_DATES:
            evidence = core.fetch_json(core.metadata_url(base_url, market, anchor))
            raw_path = raw_dir / f"{market}-{anchor}.json"
            raw_path.write_bytes(evidence.response_bytes)
            responses.append(
                {
                    "market": market,
                    "anchor_date_utc": anchor,
                    "request_url": evidence.request_url,
                    "final_url": evidence.final_url,
                    "elapsed_seconds": evidence.elapsed_seconds,
                    "response_path": str(raw_path.relative_to(output_dir)),
                    "response_bytes": len(evidence.response_bytes),
                    "response_sha256": core.sha256(evidence.response_bytes),
                    "response_base64": b64encode(evidence.response_bytes).decode("ascii"),
                }
            )
            try:
                records.extend(
                    core.parse_file_records(
                        evidence,
                        expected_market=market,
                        expected_anchor=anchor,
                    )
                )
            except core.SourceFeasibilityError as exc:
                return terminal_evidence(
                    output_dir,
                    responses=responses,
                    records=records,
                    market=market,
                    anchor=anchor,
                    reason=str(exc),
                )
    urls = [record["url"] for record in records]
    if len(records) != 48 or len(set(urls)) != 48:
        return terminal_evidence(
            output_dir,
            responses=responses,
            records=records,
            market="cohort",
            anchor="cohort",
            reason="mandatory cohort did not resolve to 48 unique source objects",
        )
    declared_total = sum(item["declared_compressed_bytes_decimal_mb"] for item in records)
    largest = max(item["declared_compressed_bytes_decimal_mb"] for item in records)
    if largest > core.MAX_OBJECT_BYTES or declared_total > core.MAX_CUMULATIVE_BYTES:
        return terminal_evidence(
            output_dir,
            responses=responses,
            records=records,
            market="cohort",
            anchor="cohort",
            reason="frozen byte ceiling exceeded",
        )
    manifest = {
        "family_id": experiment.FAMILY_ID,
        "provider": "OKX",
        "endpoint": f"https://www.okx.com{core.ENDPOINT_PATH}",
        "module": core.MODULE,
        "module_description": "400-level order-book history",
        "markets": list(experiment.MARKETS),
        "anchor_dates_utc": list(experiment.ANCHOR_DATES),
        "metadata_responses": responses,
        "source_objects": sorted(records, key=lambda item: (item["market"], item["anchor_date_utc"])),
        "source_object_count": 48,
        "declared_compressed_bytes": declared_total,
        "largest_object_bytes": largest,
        "per_object_ceiling_bytes": core.MAX_OBJECT_BYTES,
        "cumulative_ceiling_bytes": core.MAX_CUMULATIVE_BYTES,
        "working_set_ceiling_bytes": core.MAX_WORKING_SET_BYTES,
        "byte_gate_passed": True,
        "source_feasible": True,
        "economic_values_read": False,
    }
    raw = core.canonical_json(manifest)
    (output_dir / "source-manifest.json").write_bytes(raw)
    status = {
        "family_id": experiment.FAMILY_ID,
        "source_feasible": True,
        "source_object_count": 48,
        "source_manifest_sha256": core.sha256(raw),
    }
    (output_dir / "source-status.json").write_bytes(core.canonical_json(status))
    return status


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://www.okx.com")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(acquire(args.base_url, args.output_dir), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
