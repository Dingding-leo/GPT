from __future__ import annotations

import importlib.util
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

MODULE_PATH = Path(__file__).with_name("run_negative_e2160_margin_recovery.py")
spec = importlib.util.spec_from_file_location("margin_recovery_core", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("unable to load frozen margin-recovery core")
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, np.generic):
        return _clean(value.item())
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return value


def main() -> None:
    core.OUTPUT.mkdir(parents=True, exist_ok=True)
    protocol = core._protocol()
    protocol_bytes = core._json_bytes(protocol)
    (core.OUTPUT / "protocol.json").write_bytes(protocol_bytes)

    source_evidence: list[dict[str, object]] = []
    frames: dict[str, object] = {}
    source_failure: str | None = None
    for inst_id in core.TARGETS:
        try:
            frame, source = core._acquire(inst_id)
            frames[inst_id] = frame
            source_evidence.append(source)
        except Exception as exc:
            source_failure = f"{inst_id}: {type(exc).__name__}: {exc}"
            break

    generated_at = datetime.now(UTC).isoformat()
    if source_failure is not None or len(frames) != len(core.TARGETS):
        evidence: dict[str, object] = {
            "schema_version": "negative-e2160-margin-recovery-evidence-v1",
            "generated_at": generated_at,
            "family_id": core.FAMILY_ID,
            "protocol_sha256": core._sha256(protocol_bytes),
            "source_contract_passed": False,
            "source_failure": source_failure,
            "sources": source_evidence,
            "candidate_count": 0,
            "parameter_grid_count": 0,
            "target_returns_accessed": False,
            "strategy_performance_accessed": False,
            "sealed_oos_accessed": False,
            "canonical_mutation": False,
            "correction_authority": False,
            "paper_trading_authorized": False,
            "live_trading_authorized": False,
            "targets": [],
            "targets_passing": 0,
            "bilateral_information_pass": False,
            "strategy_metrics": {
                "training_return": None,
                "oos_return": None,
                "full_return": None,
                "sharpe": None,
                "turnover": None,
                "fees": None,
                "maximum_drawdown": None,
                "edge_per_turnover_bps": None,
            },
            "verdict": "reject_causal_own_price_negative_e2160_margin_recovery_source_contract_1h_v1",
        }
    else:
        targets = [core._analyze(inst_id, frames[inst_id]) for inst_id in core.TARGETS]
        targets_passing = sum(bool(target["pass_all_gates"]) for target in targets)
        bilateral = targets_passing == len(core.TARGETS)
        evidence = {
            "schema_version": "negative-e2160-margin-recovery-evidence-v1",
            "generated_at": generated_at,
            "family_id": core.FAMILY_ID,
            "protocol_sha256": core._sha256(protocol_bytes),
            "source_contract_passed": True,
            "source_failure": None,
            "sources": source_evidence,
            "candidate_count": 0,
            "parameter_grid_count": 0,
            "target_returns_accessed": True,
            "strategy_performance_accessed": False,
            "sealed_oos_accessed": False,
            "canonical_mutation": False,
            "correction_authority": False,
            "paper_trading_authorized": False,
            "live_trading_authorized": False,
            "targets": targets,
            "targets_passing": targets_passing,
            "bilateral_information_pass": bilateral,
            "strategy_metrics": {
                "training_return": None,
                "oos_return": None,
                "full_return": None,
                "sharpe": None,
                "turnover": None,
                "fees": None,
                "maximum_drawdown": None,
                "edge_per_turnover_bps": None,
            },
            "verdict": (
                "accept_causal_own_price_negative_e2160_margin_recovery_information_premise_1h_v1"
                if bilateral
                else "reject_causal_own_price_negative_e2160_margin_recovery_information_premise_1h_v1"
            ),
        }

    clean = _clean(evidence)
    core._write_report(clean)
    payload = json.dumps(
        clean,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ) + "\n"
    data = payload.encode()
    (core.OUTPUT / "evidence.json").write_bytes(data)
    (core.OUTPUT / "evidence.sha256").write_text(
        core._sha256(data) + "\n", encoding="utf-8"
    )
    print(json.dumps(clean, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
