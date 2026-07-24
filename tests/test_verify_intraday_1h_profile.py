from __future__ import annotations

import importlib.util
import json
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT_PATH = _REPOSITORY_ROOT / "scripts" / "verify_intraday_1h_profile.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verify_intraday_1h_profile", _SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_evidence(output: Path) -> None:
    output.mkdir(parents=True)
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
    }
    (output / "effective_config.json").write_text(
        json.dumps(effective), encoding="utf-8"
    )
    (output / "walk_forward.json").write_text(json.dumps(report), encoding="utf-8")


def test_verifier_accepts_exact_persisted_five_bps_only_profile(tmp_path: Path) -> None:
    module = _load_module()
    output = tmp_path / "BTC-USDT"
    _write_evidence(output)

    summary = module.verify_intraday_1h_profile(output)

    assert summary == {
        "instrument_id": "BTC-USDT",
        "bar": "1H",
        "transaction_cost_bps": 5.0,
        "cost_multipliers": [1.0],
        "candidate_count": 27,
    }


@pytest.mark.parametrize(
    ("artifact", "mutate", "message"),
    [
        (
            "effective_config.json",
            lambda payload: payload["robustness"].update(cost_multipliers=[1.0, 2.0]),
            "effective_config.robustness.cost_multipliers must equal",
        ),
        (
            "walk_forward.json",
            lambda payload: payload["settings"].update(cost_multipliers=[1.0, 2.0]),
            "walk_forward.settings.cost_multipliers must equal",
        ),
        (
            "walk_forward.json",
            lambda payload: payload["cost_stress_metrics"].update(
                {"2x": payload["aggregate_metrics"].copy()}
            ),
            "cost_stress_metrics must contain exactly the 1x path",
        ),
        (
            "walk_forward.json",
            lambda payload: payload["cost_stress_metrics"]["1x"].update(
                net_total_return=0.1
            ),
            "1x metric net_total_return does not match aggregate metrics",
        ),
    ],
)
def test_verifier_rejects_persisted_profile_drift(
    tmp_path: Path,
    artifact: str,
    mutate: Callable[[dict[str, object]], None],
    message: str,
) -> None:
    module = _load_module()
    output = tmp_path / "BTC-USDT"
    _write_evidence(output)
    path = output / artifact
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        module.verify_intraday_1h_profile(output)
