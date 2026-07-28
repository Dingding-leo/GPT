import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from gpt_quant.shadow_paper_acceptance import (
    build_shadow_paper_acceptance_evidence,
    load_shadow_paper_acceptance_contract,
    write_shadow_paper_acceptance_evidence,
)

_ROOT = Path(__file__).resolve().parents[1]
_CANONICAL_CONFIG = _ROOT / "config" / "shadow_paper_acceptance.json"


def _payload() -> dict[str, Any]:
    return json.loads(_CANONICAL_CONFIG.read_text(encoding="utf-8"))


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _replace(payload: dict[str, Any], path: tuple[str, ...], value: object) -> None:
    parent: dict[str, Any] = payload
    for key in path[:-1]:
        parent = parent[key]
    parent[path[-1]] = value


def test_builds_deterministic_non_live_acceptance_evidence(tmp_path: Path) -> None:
    contract, contract_hash = load_shadow_paper_acceptance_contract(_CANONICAL_CONFIG)
    evidence = build_shadow_paper_acceptance_evidence(_CANONICAL_CONFIG)
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    first_hash = write_shadow_paper_acceptance_evidence(evidence, first)
    second_hash = write_shadow_paper_acceptance_evidence(evidence, second)

    assert contract["bar"] == "1H"
    assert evidence["contract_sha256"] == contract_hash
    assert evidence["exchange_fee_one_way_bps"] == 5.0
    assert evidence["fee_applied_to"] == "filled_notional"
    assert evidence["live_ready"] is False
    assert evidence["limited_capital_authorization"] is False
    assert first.read_bytes() == second.read_bytes()
    assert first_hash == second_hash == hashlib.sha256(first.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    ("field_path", "weakened_value"),
    [
        (("public_data", "stale_after_seconds"), 5401),
        (("runtime", "maximum_dropped_events"), 1),
        (("risk", "zero_reconciliation_drift_required"), False),
        (("economics", "exchange_fee_one_way_bps"), 4.9),
        (("classification", "operational_pass_may_imply_live_ready"), True),
        (("strategy_boundary", "causal_time_series_only"), False),
    ],
)
def test_rejects_weakened_safety_and_strategy_fields(
    tmp_path: Path,
    field_path: tuple[str, ...],
    weakened_value: object,
) -> None:
    payload = _payload()
    _replace(payload, field_path, weakened_value)
    path = tmp_path / "weakened.json"
    _write(path, payload)

    with pytest.raises(ValueError, match="must remain exactly"):
        load_shadow_paper_acceptance_contract(path)


def test_rejects_removed_cross_sectional_prohibition(tmp_path: Path) -> None:
    payload = _payload()
    payload["strategy_boundary"]["forbidden_methods"].remove("cross_sectional_ranking")
    path = tmp_path / "removed-boundary.json"
    _write(path, payload)

    with pytest.raises(ValueError, match="must contain exactly"):
        load_shadow_paper_acceptance_contract(path)


def test_rejects_unknown_contract_fields(tmp_path: Path) -> None:
    payload = _payload()
    payload["runtime"]["allow_best_effort_recovery"] = True
    path = tmp_path / "unknown.json"
    _write(path, payload)

    with pytest.raises(ValueError, match="contains unknown fields"):
        load_shadow_paper_acceptance_contract(path)


def test_rejects_duplicate_json_fields(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text(
        '{"schema_version":1,"schema_version":1,"mode":"shadow_paper_only"}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate field schema_version"):
        load_shadow_paper_acceptance_contract(path)


def test_rejects_symlinked_contract(tmp_path: Path) -> None:
    source = tmp_path / "contract.json"
    source.write_bytes(_CANONICAL_CONFIG.read_bytes())
    symlink = tmp_path / "contract-link.json"
    symlink.symlink_to(source)

    with pytest.raises(ValueError, match="not a regular file"):
        load_shadow_paper_acceptance_contract(symlink)
