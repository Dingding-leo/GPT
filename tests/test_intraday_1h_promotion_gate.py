from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from types import ModuleType

import pytest

from gpt_quant.intraday_1h_source_provenance import write_intraday_1h_source_provenance

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS_DIR = _REPOSITORY_ROOT / "scripts"
_SCRIPT_PATH = _SCRIPTS_DIR / "build_intraday_1h_promotion_gate.py"
_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "okx_1h" / "BTC-USDT"


def _load_module() -> ModuleType:
    sys.path.insert(0, str(_SCRIPTS_DIR))
    try:
        spec = importlib.util.spec_from_file_location(
            "build_intraday_1h_promotion_gate", _SCRIPT_PATH
        )
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(_SCRIPTS_DIR))


def _write_evidence(
    output: Path,
    *,
    robustness_status: str,
    fold_stability_passes: bool,
    failure_reasons: list[str],
) -> None:
    output.mkdir(parents=True)
    shutil.copytree(_FIXTURE_DIR, output / "snapshot")
    effective = {
        "data": {"inst_id": "BTC-USDT", "bar": "1H"},
        "strategy": {"transaction_cost_bps": 5.0},
        "robustness": {"cost_multipliers": [1.0]},
    }
    aggregate = {
        "observations": 25_920,
        "net_total_return": 0.2434912,
        "annualized_turnover": 52.958205,
        "exchange_fee_sum": 0.07834912,
    }
    report = {
        "settings": {
            "base_config": {"transaction_cost_bps": 5.0},
            "cost_multipliers": [1.0],
            "candidate_count": 27,
        },
        "aggregate_metrics": aggregate,
        "cost_stress_metrics": {"1x": aggregate.copy()},
        "robustness_status": robustness_status,
        "fold_stability": {
            "passes": fold_stability_passes,
            "failure_reasons": failure_reasons,
        },
    }
    (output / "effective_config.json").write_text(json.dumps(effective), encoding="utf-8")
    (output / "walk_forward.json").write_text(json.dumps(report), encoding="utf-8")
    write_intraday_1h_source_provenance(output, inst_id="BTC-USDT")


def test_rejected_1h_candidate_writes_deterministic_fail_closed_summary(tmp_path: Path) -> None:
    module = _load_module()
    output = tmp_path / "BTC-USDT"
    _write_evidence(
        output,
        robustness_status="reject: out-of-sample fold profits are too concentrated",
        fold_stability_passes=False,
        failure_reasons=["fewer than half of out-of-sample folds are profitable"],
    )

    first = module.build_intraday_1h_promotion_gate(output)
    first_bytes = (output / "intraday-promotion-gate.json").read_bytes()
    second = module.build_intraday_1h_promotion_gate(output)

    assert first == second
    assert (output / "intraday-promotion-gate.json").read_bytes() == first_bytes
    assert first["modeled_economics"] == {
        "one_way_exchange_fee_bps": 5.0,
        "cost_multipliers": [1.0],
        "spread": "separate_not_modeled",
        "slippage": "separate_not_modeled",
        "market_impact": "separate_not_modeled",
        "latency": "separate_not_modeled",
    }
    source_path = output / "intraday-1h-source-provenance.json"
    assert first["source_artifacts"]["source_provenance_sha256"] == hashlib.sha256(
        source_path.read_bytes()
    ).hexdigest()
    assert first["source_artifacts"]["source_response_count"] == 1
    assert first["source_artifacts"]["observations"] == 2
    assert first["research_gate"]["research_candidate_eligible"] is False
    assert first["research_gate"]["blockers"] == [
        "research_status_rejected",
        "fold_stability_rejected",
    ]
    assert first["promotion"]["allow_15m_evaluation"] is False
    assert first["promotion"]["allow_paper_promotion"] is False
    assert module.main(["--output-dir", str(output), "--enforce-research-promotion"]) == 1


def test_provisional_1h_candidate_allows_only_further_research(tmp_path: Path) -> None:
    module = _load_module()
    output = tmp_path / "BTC-USDT"
    _write_evidence(
        output,
        robustness_status=(
            "provisional alpha candidate: beats tested benchmarks on return and Sharpe"
        ),
        fold_stability_passes=True,
        failure_reasons=[],
    )

    payload = module.build_intraday_1h_promotion_gate(output)

    assert payload["research_gate"]["research_candidate_eligible"] is True
    assert payload["research_gate"]["blockers"] == []
    assert payload["promotion"]["allow_15m_evaluation"] is True
    assert payload["promotion"]["allow_paper_promotion"] is False
    assert payload["promotion"]["allow_limited_capital"] is False
    assert module.main(["--output-dir", str(output), "--enforce-research-promotion"]) == 0


def test_promotion_gate_rejects_inconsistent_fold_stability(tmp_path: Path) -> None:
    module = _load_module()
    output = tmp_path / "BTC-USDT"
    _write_evidence(
        output,
        robustness_status="reject: out-of-sample fold profits are too concentrated",
        fold_stability_passes=False,
        failure_reasons=[],
    )

    with pytest.raises(ValueError, match="must contain at least one failure reason"):
        module.build_intraday_1h_promotion_gate(output)


def test_promotion_gate_rejects_self_rehashed_source_provenance(tmp_path: Path) -> None:
    module = _load_module()
    output = tmp_path / "BTC-USDT"
    _write_evidence(
        output,
        robustness_status="reject: out-of-sample fold profits are too concentrated",
        fold_stability_passes=False,
        failure_reasons=["fewer than half of out-of-sample folds are profitable"],
    )
    provenance_path = output / "intraday-1h-source-provenance.json"
    forged = json.loads(provenance_path.read_text(encoding="utf-8"))
    forged["offline_replay_verified"] = False
    provenance_path.write_text(
        json.dumps(forged, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="does not reconstruct exactly"):
        module.build_intraday_1h_promotion_gate(output)
