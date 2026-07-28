from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from numbers import Integral, Real
from typing import Any

_CANDIDATE_COUNT = 27
_FEE_BPS = 5.0
_FAMILY_ID = "selector-protocol-v1"
_TABLE_KEYS = {
    "bar",
    "candidate_count",
    "candidate_iteration_order",
    "code_commit_sha",
    "data_csv_sha256",
    "fee_config_sha256",
    "fold",
    "market",
    "one_way_fee_bps",
    "research_config_sha256",
    "rows",
    "s0_candidate_id",
    "s1_candidate_id",
    "s2_member_ids",
    "s3_candidate_id",
    "s4_candidate_id",
    "s5_member_ids",
    "schema_version",
    "selection_end",
    "selection_start",
    "source_workflow_head",
    "table_id",
    "test_end",
    "test_start",
}
_ROW_KEYS = {
    "candidate_id",
    "candidate_order",
    "config",
    "config_sha256",
    "current_percentile_rank",
    "first_causal_oos_target_position",
    "first_causal_oos_target_source_timestamp",
    "previous_s4_candidate_id",
    "prior_fold_mean_percentile_rank",
    "runner_up_score_gap",
    "s2_member",
    "s5_member",
    "shrunk_percentile_rank",
    "training_metrics",
    "training_rank",
    "training_score",
}
_ARTIFACT_KEYS = {"artifact_id", "family_id", "market", "schema_version", "tables"}
_HEX = frozenset("0123456789abcdef")


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_json(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _is_sha256(value: object) -> bool:
    normalized = str(value).lower()
    return len(normalized) == 64 and set(normalized) <= _HEX


def _is_commit_sha(value: object) -> bool:
    normalized = str(value).lower()
    return len(normalized) == 40 and set(normalized) <= _HEX


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _finite_real(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{label} must be a finite real number")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"{label} must be a finite real number")
    return parsed


def _integer(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise ValueError(f"{label} must be an integer")
    return int(value)


def candidate_id(config: Mapping[str, Any]) -> str:
    return _sha256_json(dict(config))


def _score(metrics: Mapping[str, Any]) -> float:
    required = {"annualized_turnover", "calmar", "max_drawdown", "sharpe"}
    _require(required <= set(metrics), "training metrics are missing score inputs")
    return (
        _finite_real(metrics["sharpe"], label="training sharpe")
        + 0.20 * _finite_real(metrics["calmar"], label="training calmar")
        - 0.50 * abs(_finite_real(metrics["max_drawdown"], label="training drawdown"))
        - 0.01
        * _finite_real(metrics["annualized_turnover"], label="training turnover")
    )


def _coordinates(row: Mapping[str, Any]) -> tuple[int, int, float]:
    config = row["config"]
    _require(isinstance(config, Mapping), "candidate config must be a mapping")
    return (
        _integer(config.get("momentum_lookback"), label="momentum_lookback"),
        _integer(config.get("reversal_lookback"), label="reversal_lookback"),
        _finite_real(config.get("trend_weight"), label="trend_weight"),
    )


def _percentile(rank: int) -> float:
    return (_CANDIDATE_COUNT - rank) / (_CANDIDATE_COUNT - 1)


def _body_without_id(table: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in table.items() if key != "table_id"}


def validate_candidate_table(
    table: Mapping[str, Any],
    *,
    prior_tables: Sequence[Mapping[str, Any]] = (),
) -> None:
    _require(set(table) == _TABLE_KEYS, "candidate table schema mismatch")
    _require(table["schema_version"] == 1, "unsupported candidate table schema")
    _require(table["bar"] == "1H", "selector evidence must use 1H bars")
    _require(table["candidate_count"] == _CANDIDATE_COUNT, "candidate count must equal 27")
    _require(table["one_way_fee_bps"] == _FEE_BPS, "fee must equal 5 bps one-way")
    for key in ("data_csv_sha256", "fee_config_sha256", "research_config_sha256"):
        _require(_is_sha256(table[key]), f"{key} must be SHA-256")
    for key in ("code_commit_sha", "source_workflow_head"):
        _require(_is_commit_sha(table[key]), f"{key} must be a commit SHA")
    _require(
        table["table_id"] == _sha256_json(_body_without_id(table)),
        "candidate table content hash mismatch",
    )

    rows = table["rows"]
    order = table["candidate_iteration_order"]
    _require(isinstance(rows, list) and len(rows) == _CANDIDATE_COUNT, "table needs 27 rows")
    _require(isinstance(order, list) and len(order) == _CANDIDATE_COUNT, "bad order")
    _require(len(set(order)) == _CANDIDATE_COUNT, "candidate order contains duplicates")

    by_id: dict[str, Mapping[str, Any]] = {}
    scores: list[tuple[float, int, str]] = []
    for row in rows:
        _require(isinstance(row, Mapping), "candidate row must be a mapping")
        _require(set(row) == _ROW_KEYS, "candidate row schema mismatch")
        cid = str(row["candidate_id"])
        _require(cid not in by_id, "duplicate candidate identity")
        _require(_is_sha256(cid), "candidate identity must be SHA-256")
        _require(row["config_sha256"] == cid, "config hash and candidate identity differ")
        config = row["config"]
        _require(isinstance(config, Mapping), "candidate config must be a mapping")
        _require(candidate_id(config) == cid, "candidate config hash mismatch")
        _require(config.get("transaction_cost_bps") == _FEE_BPS, "candidate fee must be 5 bps")
        candidate_order = _integer(row["candidate_order"], label="candidate_order")
        _require(0 <= candidate_order < _CANDIDATE_COUNT, "candidate order is out of range")
        _require(order[candidate_order] == cid, "candidate order does not match iteration order")
        rank = _integer(row["training_rank"], label="training_rank")
        _require(1 <= rank <= _CANDIDATE_COUNT, "training rank is out of range")
        score = _finite_real(row["training_score"], label="training_score")
        metrics = row["training_metrics"]
        _require(isinstance(metrics, Mapping), "training metrics must be a mapping")
        _require(math.isclose(score, _score(metrics), rel_tol=0.0, abs_tol=1e-12), "bad score")
        _require(
            math.isclose(
                _finite_real(row["current_percentile_rank"], label="percentile"),
                _percentile(rank),
                rel_tol=0.0,
                abs_tol=1e-15,
            ),
            "current percentile rank is inconsistent",
        )
        position = _finite_real(
            row["first_causal_oos_target_position"],
            label="first causal OOS position",
        )
        minimum = _finite_real(config.get("min_position"), label="min_position")
        maximum = _finite_real(config.get("max_abs_position"), label="max_abs_position")
        _require(minimum <= position <= maximum, "first causal OOS position violates bounds")
        _require(
            row["first_causal_oos_target_source_timestamp"] == table["selection_end"],
            "first OOS position must be sourced from the training-window close",
        )
        by_id[cid] = row
        scores.append((score, candidate_order, cid))

    _require(set(by_id) == set(order), "candidate rows do not match iteration order")
    expected_order = [item[2] for item in sorted(scores, key=lambda item: -item[0])]
    ranked_rows = sorted(rows, key=lambda row: row["training_rank"])
    actual_order = [row["candidate_id"] for row in ranked_rows]
    _require(actual_order == expected_order, "training ranks do not reconstruct score ordering")
    _require(table["s0_candidate_id"] == expected_order[0], "S0 is not the training argmax")
    gap = scores_by_id(by_id)[expected_order[0]] - scores_by_id(by_id)[expected_order[1]]
    for cid, row in by_id.items():
        expected_gap = gap if cid == expected_order[0] else None
        _require(row["runner_up_score_gap"] == expected_gap, "runner-up gap is inconsistent")

    center = [
        cid
        for cid, row in by_id.items()
        if _coordinates(row) == (2160, 120, 0.70)
    ]
    _require(center == [table["s1_candidate_id"]], "S1 centre candidate is invalid")

    s0_coordinates = _coordinates(by_id[str(table["s0_candidate_id"])])
    expected_s2 = [
        cid
        for cid in order
        if sum(left == right for left, right in zip(_coordinates(by_id[cid]), s0_coordinates)) >= 2
    ]
    _require(table["s2_member_ids"] == expected_s2, "S2 neighbourhood is inconsistent")

    expected_s5 = [
        cid
        for cid in expected_order
        if _finite_real(by_id[cid]["training_metrics"]["total_return"], label="return") > 0.0
        and _finite_real(by_id[cid]["training_metrics"]["sharpe"], label="sharpe") > 0.0
    ]
    _require(table["s5_member_ids"] == expected_s5, "S5 membership is inconsistent")
    for cid, row in by_id.items():
        _require(row["s2_member"] == (cid in expected_s2), "S2 row membership is wrong")
        _require(row["s5_member"] == (cid in expected_s5), "S5 row membership is wrong")

    previous_rows = [
        {str(row["candidate_id"]): row for row in prior["rows"]}
        for prior in prior_tables
    ]
    shrunk: dict[str, float] = {}
    for cid, row in by_id.items():
        history = [
            _finite_real(prior[cid]["current_percentile_rank"], label="prior percentile")
            for prior in previous_rows
        ]
        prior_mean = float(sum(history) / len(history)) if history else None
        actual_prior_mean = row["prior_fold_mean_percentile_rank"]
        if prior_mean is None:
            _require(actual_prior_mean is None, "prior-fold mean percentile is inconsistent")
        else:
            _require(
                math.isclose(
                    _finite_real(actual_prior_mean, label="prior-fold mean percentile"),
                    prior_mean,
                    rel_tol=0.0,
                    abs_tol=1e-15,
                ),
                "prior-fold mean percentile is inconsistent",
            )
        values = [*history, _finite_real(row["current_percentile_rank"], label="percentile")]
        shrunk[cid] = float(sum(values) / len(values))
        _require(
            math.isclose(
                _finite_real(row["shrunk_percentile_rank"], label="shrunk percentile"),
                shrunk[cid],
                rel_tol=0.0,
                abs_tol=1e-15,
            ),
            "shrunk percentile is inconsistent",
        )

    maximum_shrunk = max(shrunk.values())
    s3 = [cid for cid in order if shrunk[cid] == maximum_shrunk]
    _require(len(s3) == 1, "S3 is not uniquely identified")
    _require(table["s3_candidate_id"] == s3[0], "S3 candidate is inconsistent")

    previous_s4 = prior_tables[-1]["s4_candidate_id"] if prior_tables else None
    for row in rows:
        _require(row["previous_s4_candidate_id"] == previous_s4, "previous S4 identity differs")
    rank_by_id = {str(row["candidate_id"]): int(row["training_rank"]) for row in rows}
    expected_s4 = (
        table["s0_candidate_id"]
        if previous_s4 is None or rank_by_id[str(previous_s4)] > 2
        else previous_s4
    )
    _require(table["s4_candidate_id"] == expected_s4, "S4 candidate is inconsistent")


def scores_by_id(rows: Mapping[str, Mapping[str, Any]]) -> dict[str, float]:
    return {
        cid: _finite_real(row["training_score"], label="training_score")
        for cid, row in rows.items()
    }


def load_training_artifact_bytes(payload: bytes) -> dict[str, Any]:
    if not payload.endswith(b"\n") or payload.count(b"\n") != 1:
        raise ValueError("selector artifact must be one canonical JSON line")
    parsed = json.loads(payload, object_pairs_hook=_pairs_no_duplicates)
    _require(isinstance(parsed, dict), "selector artifact must be a JSON object")
    _require(set(parsed) == _ARTIFACT_KEYS, "selector artifact schema mismatch")
    _require(parsed["schema_version"] == 1, "unsupported selector artifact schema")
    _require(parsed["family_id"] == _FAMILY_ID, "selector family identity mismatch")
    body = {key: value for key, value in parsed.items() if key != "artifact_id"}
    _require(parsed["artifact_id"] == _sha256_json(body), "selector artifact hash mismatch")
    _require(payload == canonical_json_bytes(parsed) + b"\n", "selector artifact is noncanonical")
    tables = parsed["tables"]
    _require(isinstance(tables, list) and tables, "selector artifact needs candidate tables")
    prior: list[Mapping[str, Any]] = []
    for expected_fold, table in enumerate(tables, start=1):
        _require(isinstance(table, Mapping), "candidate table must be a mapping")
        _require(table["market"] == parsed["market"], "mixed markets in selector artifact")
        _require(table["fold"] == expected_fold, "selector folds must be consecutive")
        validate_candidate_table(table, prior_tables=prior)
        prior.append(table)
    return parsed
