from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_stablecoin_quote_stress_entry_veto_1h_v1 as engine

CLOSE_TIME_ERROR = re.compile(
    r"^invalid close timestamp in (?P<stem>[^:]+): "
    r"(?P<open_ms>\d+), (?P<close_ms>\d+)$"
)


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode()


def sha256_path(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000.0, tz=UTC).isoformat().replace(
        "+00:00", "Z"
    )


def count_files(output_dir: Path, suffix: str) -> int:
    source_dir = output_dir / "sources"
    if not source_dir.exists():
        return 0
    return sum(path.is_file() and path.name.endswith(suffix) for path in source_dir.rglob("*"))


def write_abort_evidence(output_dir: Path, error: ValueError) -> dict[str, Any]:
    match = CLOSE_TIME_ERROR.fullmatch(str(error))
    if match is None:
        raise error

    stem = match.group("stem")
    open_ms = int(match.group("open_ms"))
    close_ms = int(match.group("close_ms"))
    symbol = stem.split("-", maxsplit=1)[0]
    archive_path = output_dir / "sources" / symbol / stem
    checksum_path = archive_path.with_name(f"{stem}.CHECKSUM")
    observed_duration_ms = close_ms - open_ms + 1
    expected_duration_ms = engine.HOUR_MS

    evidence = {
        "family_id": engine.FAMILY_ID,
        "classification": "executable_causal_exogenous_information_strategy",
        "generated_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        "candidate_count": 2,
        "parameter_grid_count": 0,
        "bar": "1H",
        "canonical_fee_bps_one_way": 5.0,
        "markets": list(engine.TARGETS),
        "fixed_lagged_exogenous_series": "USDCUSDT",
        "rejection_stage": "immutable_public_source_contract_before_performance",
        "abort_triggered": True,
        "abort_reason": "a checksummed public archive row has a close timestamp inconsistent with its hourly open; the preregistered contract prohibits row filtering, interpolation, source substitution or relaxed chronology",
        "source_contract": {
            "archive_base": engine.ARCHIVE_BASE,
            "required_source_objects": engine.EXPECTED_SOURCE_OBJECTS,
            "required_checksum_objects": engine.EXPECTED_CHECKSUM_OBJECTS,
            "downloaded_source_objects_before_abort": count_files(output_dir, ".zip"),
            "downloaded_checksum_objects_before_abort": count_files(
                output_dir, ".CHECKSUM"
            ),
            "coverage_pass": False,
            "checksum_for_offending_object_pass": archive_path.is_file()
            and checksum_path.is_file(),
            "close_time_consistency_pass": False,
            "common_calendar_pass": False,
            "offending_observation": {
                "symbol": symbol,
                "interval": engine.INTERVAL,
                "archive_name": stem,
                "archive_url": f"{engine.ARCHIVE_BASE}/{symbol}/{engine.INTERVAL}/{stem}",
                "checksum_url": f"{engine.ARCHIVE_BASE}/{symbol}/{engine.INTERVAL}/{stem}.CHECKSUM",
                "archive_sha256": sha256_path(archive_path),
                "checksum_sha256": sha256_path(checksum_path),
                "open_time_ms": open_ms,
                "open_time": iso(open_ms),
                "observed_close_time_ms": close_ms,
                "observed_close_time": iso(close_ms),
                "observed_duration_ms": observed_duration_ms,
                "expected_duration_ms": expected_duration_ms,
                "duration_shortfall_ms": expected_duration_ms - observed_duration_ms,
                "raw_validation_error": str(error),
            },
        },
        "performance": {
            "accessed": False,
            "training_metrics_computed": False,
            "oos_metrics_computed": False,
            "full_metrics_computed": False,
            "bootstrap_draws_executed": 0,
            "target_results": [],
            "markets_passing_all_gates": 0,
            "sharpe": None,
            "turnover": None,
            "fees": None,
            "edge_per_turnover": None,
            "drawdown": None,
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
        "training_authorized_correction": {
            "permitted": False,
            "applied": False,
            "policy_changed": False,
            "observation_epoch_restarted": False,
            "reason": "the frozen source contract failed before any training or OOS performance access",
        },
        "verdict": "reject_causal_stablecoin_quote_stress_entry_veto_1h_v1",
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "next_strategy_action": "keep the source-contract-failed candidate closed; preregister a materially orthogonal architecture whose immutable public source calendar is proven before performance access",
    }

    evidence_bytes = canonical_bytes(evidence)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "evidence.json").write_bytes(evidence_bytes)
    (output_dir / "evidence.sha256").write_text(
        hashlib.sha256(evidence_bytes).hexdigest() + "\n"
    )
    report = "\n".join(
        [
            "# Stablecoin quote-stress entry-veto terminal source-contract rejection",
            "",
            f"- Family: `{engine.FAMILY_ID}`",
            "- Performance accessed: `false`",
            "- Abort stage: immutable public source validation",
            f"- Offending object: `{stem}`",
            f"- Open: `{iso(open_ms)}`",
            f"- Observed close: `{iso(close_ms)}`",
            f"- Observed duration: `{observed_duration_ms / 1000.0:.3f}` seconds",
            f"- Required duration: `{expected_duration_ms / 1000.0:.3f}` seconds",
            "",
            "The checksummed archive row violates the preregistered hourly close-time contract. Row filtering, interpolation, fallback data, source substitution and relaxed chronology are prohibited, so the run stopped before any strategy return, Sharpe, turnover, fee, drawdown, bootstrap or gate calculation.",
            "",
            f"Verdict: `{evidence['verdict']}`.",
            "",
            "No correction, observation-epoch restart, paper authority or live authority is permitted.",
            "",
        ]
    )
    (output_dir / "report.md").write_text(report)
    (output_dir / "report.sha256").write_text(
        hashlib.sha256(report.encode()).hexdigest() + "\n"
    )
    return evidence


def run(output_dir: Path) -> dict[str, Any]:
    try:
        return engine.run(output_dir)
    except ValueError as error:
        return write_abort_evidence(output_dir, error)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.output_dir), sort_keys=True, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
