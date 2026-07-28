from __future__ import annotations

import hashlib
import itertools
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from gpt_quant.config import StrategyConfig
from gpt_quant.selector_evidence import (
    FOLD_COUNT,
    SELECTION_BARS,
    TEST_BARS,
    build_training_candidate_table,
    reconstruct_training_candidate_table,
    serialize_training_candidate_table,
    validate_training_candidate_table_sequence,
)
from gpt_quant.walk_forward import _score

SHA = "1" * 64
HOUR = timedelta(hours=1)
ORIGIN = datetime(2020, 1, 1, tzinfo=UTC)


def _records(
    prior_by_order: dict[int, list[float]] | None = None,
) -> list[dict[str, object]]:
    records = []
    grid = itertools.product((720, 2160, 4320), (48, 120, 240), (0.55, 0.70, 0.85))
    for index, (momentum, reversal, weight) in enumerate(grid):
        positive = index % 4 != 0
        metrics = {
            "total_return": 0.1 if positive else -0.1,
            "cagr": 0.1 if positive else -0.1,
            "sharpe": 2.0 - 0.05 * index,
            "calmar": 0.5,
            "max_drawdown": -0.2,
            "annualized_turnover": 5.0 + index,
        }
        records.append(
            {
                "config": StrategyConfig(
                    momentum_lookback=momentum,
                    reversal_lookback=reversal,
                    volatility_lookback=720,
                    target_volatility=0.5,
                    max_abs_position=1.0,
                    min_position=0.0,
                    trend_weight=weight,
                    reversal_weight=round(1.0 - weight, 10),
                    transaction_cost_bps=5.0,
                    annualization=8760,
                ),
                "training_score": _score(metrics),
                "training_metrics": metrics,
                "first_causal_oos_target_position": index / 100,
                "prior_percentile_ranks": ([] if prior_by_order is None else prior_by_order[index]),
            }
        )
    return records


def _times(fold: int) -> dict[str, str]:
    start = ORIGIN + HOUR * TEST_BARS * (fold - 1)
    selection_end = start + HOUR * (SELECTION_BARS - 1)
    test_start = selection_end + HOUR
    test_end = test_start + HOUR * (TEST_BARS - 1)
    return {
        "selection_start": start.isoformat(),
        "selection_end": selection_end.isoformat(),
        "test_start": test_start.isoformat(),
        "test_end": test_end.isoformat(),
    }


def _build(
    records=None,
    *,
    fold: int = 1,
    market: str = "BTC-USDT",
    previous_s4_candidate_id: str | None = None,
    previous_table_id: str | None = None,
    hashes: dict[str, str] | None = None,
):
    digests = {
        "data_sha256": SHA,
        "code_sha256": SHA,
        "research_config_sha256": SHA,
        "fee_config_sha256": SHA,
    }
    if hashes is not None:
        digests.update(hashes)
    return build_training_candidate_table(
        market=market,
        fold=fold,
        **_times(fold),
        candidate_records=_records() if records is None else records,
        previous_s4_candidate_id=previous_s4_candidate_id,
        previous_table_id=previous_table_id,
        **digests,
    )


def _rehash(payload: dict[str, object]) -> bytes:
    body = deepcopy(payload)
    body.pop("table_id")
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n"
    payload["table_id"] = hashlib.sha256(canonical.encode()).hexdigest()
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    return serialized.encode()


def _rank_history(table: dict[str, object]) -> dict[int, list[float]]:
    return {row["candidate_order_index"]: [row["percentile_rank"]] for row in table["records"]}


def _extend_history(
    history: dict[int, list[float]],
    table: dict[str, object],
) -> None:
    for row in table["records"]:
        history[row["candidate_order_index"]].append(row["percentile_rank"])


def _s4_after(table: dict[str, object], previous: str | None) -> str:
    if previous is None:
        return table["winner_candidate_id"]
    previous_record = next(row for row in table["records"] if row["candidate_id"] == previous)
    if previous_record["score_rank"] <= 2:
        return previous
    return table["winner_candidate_id"]


def _sequence(count: int = FOLD_COUNT) -> list[dict[str, object]]:
    tables = []
    history: dict[int, list[float]] | None = None
    previous_s4 = None
    previous_table = None
    for fold in range(1, count + 1):
        records = _records(history)
        table = _build(
            records,
            fold=fold,
            previous_s4_candidate_id=previous_s4,
            previous_table_id=previous_table,
        )
        tables.append(table)
        if history is None:
            history = _rank_history(table)
        else:
            _extend_history(history, table)
        previous_s4 = _s4_after(table, previous_s4)
        previous_table = table["table_id"]
    return tables


def test_table_is_deterministic_and_reconstructable():
    payload = _build()
    raw = serialize_training_candidate_table(payload)
    assert raw == serialize_training_candidate_table(_build())
    assert reconstruct_training_candidate_table(raw) == payload
    winner = next(
        row for row in payload["records"] if row["candidate_id"] == payload["winner_candidate_id"]
    )
    assert winner["score_rank"] == 1
    assert winner["runner_up_score_gap"] == pytest.approx(0.06)


def test_s2_matches_frozen_coordinate_mismatch_definition():
    payload = _build()
    by_order = {row["candidate_order_index"]: row for row in payload["records"]}
    assert by_order[0]["s2_geometric_neighbourhood_member"] is True
    assert by_order[2]["s2_geometric_neighbourhood_member"] is True
    assert by_order[9]["s2_geometric_neighbourhood_member"] is True
    assert by_order[10]["s2_geometric_neighbourhood_member"] is False
    assert by_order[0]["s5_positive_evidence_member"] is False


def test_rejects_missing_duplicate_oos_unknown_and_grid_substitution():
    with pytest.raises(ValueError, match="exactly 27"):
        _build(_records()[:-1])
    duplicate = _records()
    duplicate[-1]["config"] = duplicate[0]["config"]
    with pytest.raises(ValueError, match="frozen 1H grid"):
        _build(duplicate)
    forbidden = _records()
    forbidden[0]["next_fold_return"] = 0.5
    with pytest.raises(ValueError, match="forbidden OOS"):
        _build(forbidden)
    unknown = _records()
    unknown[0]["selection_hint"] = "argmax"
    with pytest.raises(ValueError, match="frozen schema"):
        _build(unknown)
    substituted = _records()
    substituted[0]["config"] = substituted[0]["config"].with_overrides(momentum_lookback=721)
    with pytest.raises(ValueError, match="frozen 1H grid"):
        _build(substituted)


def test_rejects_noncanonical_duplicate_and_tampered_json():
    payload = _build()
    raw = serialize_training_candidate_table(payload)
    with pytest.raises(ValueError, match="canonical JSON"):
        reconstruct_training_candidate_table(json.dumps(payload).encode())
    duplicate = raw.replace(b'{"bar":"1H",', b'{"bar":"1H","bar":"1H",', 1)
    with pytest.raises(ValueError, match="duplicate JSON field"):
        reconstruct_training_candidate_table(duplicate)
    tampered = deepcopy(payload)
    tampered["records"][0]["training_score"] = 999.0
    with pytest.raises(ValueError, match="canonical selector score"):
        reconstruct_training_candidate_table(_rehash(tampered))


def test_rejects_score_rank_membership_and_boolean_tampering():
    payload = _build()
    payload["records"][0]["training_metrics"]["sharpe"] += 1.0
    with pytest.raises(ValueError, match="canonical selector score"):
        reconstruct_training_candidate_table(_rehash(payload))

    payload = _build()
    payload["records"][0]["score_rank"] = 2
    payload["records"][1]["score_rank"] = 1
    with pytest.raises(ValueError, match="percentile rank|training scores"):
        reconstruct_training_candidate_table(_rehash(payload))

    payload = _build()
    payload["records"][0]["s2_geometric_neighbourhood_member"] = 1
    with pytest.raises(ValueError, match="must be a boolean"):
        reconstruct_training_candidate_table(_rehash(payload))


def test_rejects_non_five_bps_invalid_market_and_window_drift():
    records = _records()
    records[0]["config"] = records[0]["config"].with_overrides(transaction_cost_bps=4.0)
    with pytest.raises(ValueError, match="exactly 5 bps"):
        _build(records)
    with pytest.raises(ValueError, match="frozen BTC-USDT or ETH-USDT"):
        _build(market="SOL-USDT")

    times = _times(1)
    times["test_start"] = (
        datetime.fromisoformat(times["test_start"]) + timedelta(hours=1)
    ).isoformat()
    with pytest.raises(ValueError, match="exactly one hour"):
        build_training_candidate_table(
            market="BTC-USDT",
            fold=1,
            **times,
            candidate_records=_records(),
            previous_s4_candidate_id=None,
            previous_table_id=None,
            data_sha256=SHA,
            code_sha256=SHA,
            research_config_sha256=SHA,
            fee_config_sha256=SHA,
        )


def test_sequence_reconstructs_all_folds_and_rejects_protocol_drift():
    tables = _sequence()
    validate_training_candidate_table_sequence(tables)

    with pytest.raises(ValueError, match="all 12 folds"):
        validate_training_candidate_table_sequence(tables[:2])

    validate_training_candidate_table_sequence(tables[:2], require_complete=False)

    bad_hash = deepcopy(tables[:2])
    bad_hash[1]["hashes"]["code_sha256"] = "2" * 64
    bad_hash[1] = reconstruct_training_candidate_table(_rehash(bad_hash[1]))
    with pytest.raises(ValueError, match="hashes changed"):
        validate_training_candidate_table_sequence(bad_hash, require_complete=False)

    bad_time = deepcopy(tables[:2])
    for key in ("selection_start", "selection_end", "test_start", "test_end"):
        shifted = datetime.fromisoformat(bad_time[1][key]) + timedelta(hours=1)
        bad_time[1][key] = shifted.isoformat()
    bad_time[1] = reconstruct_training_candidate_table(_rehash(bad_time[1]))
    with pytest.raises(ValueError, match="chronology"):
        validate_training_candidate_table_sequence(bad_time, require_complete=False)
