from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from numbers import Integral, Real
from typing import Any

from .config import StrategyConfig
from .walk_forward import _score

SCHEMA_VERSION = 3
CANDIDATE_COUNT = 27
FOLD_COUNT = 12
SELECTION_BARS = 17_520
TEST_BARS = 2_160
BAR_DELTA = timedelta(hours=1)
FAMILY_ID = "selector-protocol-v1|1h|frozen-27-grid|6-policies|btc-eth-development"
DEVELOPMENT_MARKETS = ("BTC-USDT", "ETH-USDT")
MOMENTUM_GRID = (720, 2160, 4320)
REVERSAL_GRID = (48, 120, 240)
TREND_WEIGHT_GRID = (0.55, 0.70, 0.85)
SCORE_TIE_BREAK = "canonical_candidate_order"
S2_GEOMETRY = "coordinate_mismatch_count_lte_1"
METRICS = (
    "total_return",
    "cagr",
    "sharpe",
    "calmar",
    "max_drawdown",
    "annualized_turnover",
)
CANDIDATE_INPUT_KEYS = {
    "config",
    "training_score",
    "training_metrics",
    "first_causal_oos_target_position",
    "prior_percentile_ranks",
}
FORBIDDEN_FIELDS = {
    "test_metrics",
    "oos_metrics",
    "next_fold_return",
    "next_fold_sharpe",
    "benchmark_residual",
    "policy_return",
}
FEE = {
    "component": "exchange_fee",
    "one_way_bps": "5",
    "applied_to": "absolute_turnover",
}
HASH_KEYS = {
    "data_sha256",
    "code_sha256",
    "research_config_sha256",
    "fee_config_sha256",
}
RECORD_KEYS = {
    "candidate_id",
    "candidate_order_index",
    "configuration",
    "configuration_sha256",
    "training_score",
    "training_metrics",
    "first_causal_oos_target_position",
    "score_rank",
    "percentile_rank",
    "prior_percentile_ranks",
    "prior_fold_rank_count",
    "prior_fold_mean_percentile_rank",
    "mean_percentile_rank_through_fold",
    "runner_up_score_gap",
    "s2_geometric_neighbourhood_member",
    "s5_positive_evidence_member",
    "previous_s4_candidate",
}
TABLE_KEYS = {
    "schema_version",
    "family_id",
    "bar",
    "market",
    "fold",
    "fold_count",
    "selection_bars",
    "test_bars",
    "selection_start",
    "selection_end",
    "test_start",
    "test_end",
    "score_tie_break",
    "s2_geometry",
    "candidate_count",
    "modeled_fee",
    "hashes",
    "winner_candidate_id",
    "previous_s4_candidate_id",
    "previous_table_id",
    "records",
    "table_id",
}


def _frozen_candidate_configs() -> tuple[dict[str, Any], ...]:
    configs: list[dict[str, Any]] = []
    for momentum in MOMENTUM_GRID:
        for reversal in REVERSAL_GRID:
            for trend_weight in TREND_WEIGHT_GRID:
                configs.append(
                    StrategyConfig(
                        momentum_lookback=momentum,
                        reversal_lookback=reversal,
                        volatility_lookback=720,
                        target_volatility=0.5,
                        max_abs_position=1.0,
                        min_position=0.0,
                        trend_weight=trend_weight,
                        reversal_weight=round(1.0 - trend_weight, 10),
                        transaction_cost_bps=5.0,
                        annualization=8760,
                    ).to_dict()
                )
    if len(configs) != CANDIDATE_COUNT:
        raise RuntimeError("frozen selector grid does not contain 27 candidates")
    return tuple(configs)


FROZEN_CANDIDATE_CONFIGS = _frozen_candidate_configs()


def canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    text = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return f"{text}\n".encode()


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha(value: object, label: str) -> str:
    valid = (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
    if not valid:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{label} must be finite")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"{label} must be finite")
    return parsed


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be a boolean")
    return value


def _utc_hour(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an ISO-8601 UTC hour")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO-8601 UTC hour") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError(f"{label} must be an ISO-8601 UTC hour")
    if parsed.minute or parsed.second or parsed.microsecond:
        raise ValueError(f"{label} must be aligned to a complete UTC hour")
    return parsed


def _validate_window(
    selection_start: object,
    selection_end: object,
    test_start: object,
    test_end: object,
) -> tuple[str, str, str, str]:
    start = _utc_hour(selection_start, "selection_start")
    end = _utc_hour(selection_end, "selection_end")
    test = _utc_hour(test_start, "test_start")
    finish = _utc_hour(test_end, "test_end")
    if end - start != BAR_DELTA * (SELECTION_BARS - 1):
        raise ValueError("selection window does not contain the frozen 17,520 hourly bars")
    if test - end != BAR_DELTA:
        raise ValueError("test window must begin exactly one hour after selection")
    if finish - test != BAR_DELTA * (TEST_BARS - 1):
        raise ValueError("test window does not contain the frozen 2,160 hourly bars")
    return start.isoformat(), end.isoformat(), test.isoformat(), finish.isoformat()


def _config(value: object) -> dict[str, Any]:
    if isinstance(value, StrategyConfig):
        config = value
    elif isinstance(value, Mapping):
        config = StrategyConfig(**dict(value))
    else:
        raise ValueError("config must be a StrategyConfig or mapping")
    if config.transaction_cost_bps != 5.0:
        raise ValueError("selector evidence requires exactly 5 bps one-way fee")
    return config.to_dict()


def _frozen_config(value: object, *, order: int) -> dict[str, Any]:
    if not 0 <= order < CANDIDATE_COUNT:
        raise ValueError("candidate order is outside the frozen grid")
    config = _config(value)
    if config != FROZEN_CANDIDATE_CONFIGS[order]:
        raise ValueError("candidate configuration does not match the frozen 1H grid")
    return config


def _metrics(value: object) -> dict[str, float]:
    if not isinstance(value, Mapping) or set(value) != set(METRICS):
        raise ValueError("training_metrics must contain exactly the required metrics")
    return {name: _finite(value[name], f"training_metrics.{name}") for name in METRICS}


def _validated_training_score(value: object, metrics: Mapping[str, float]) -> float:
    score = _finite(value, "training_score")
    expected = float(_score(metrics))
    if not math.isclose(score, expected, rel_tol=0.0, abs_tol=1e-15):
        raise ValueError("training_score does not match the canonical selector score")
    return score


def _prior_ranks(value: object, *, fold: int) -> list[float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError("prior_percentile_ranks must be a sequence")
    ranks = [_finite(item, "prior_percentile_rank") for item in value]
    if len(ranks) != fold - 1:
        raise ValueError("prior_percentile_ranks must contain every earlier fold rank")
    if any(not 0.0 <= rank <= 1.0 for rank in ranks):
        raise ValueError("prior_percentile_ranks must lie in [0, 1]")
    return ranks


def _identity(config: Mapping[str, Any]) -> tuple[int, int, float]:
    return (
        int(config["momentum_lookback"]),
        int(config["reversal_lookback"]),
        float(config["trend_weight"]),
    )


def _s2_member(config: Mapping[str, Any], winner: Mapping[str, Any]) -> bool:
    mismatches = sum(
        left != right for left, right in zip(_identity(config), _identity(winner), strict=True)
    )
    return mismatches <= 1


def _validate_predecessor(
    *,
    fold: int,
    previous_s4_candidate_id: str | None,
    previous_table_id: str | None,
) -> None:
    if fold == 1:
        if previous_s4_candidate_id is not None or previous_table_id is not None:
            raise ValueError("fold 1 cannot bind predecessor selector evidence")
        return
    if previous_s4_candidate_id is None or previous_table_id is None:
        raise ValueError("later folds require previous S4 candidate and table IDs")
    _sha(previous_s4_candidate_id, "previous_s4_candidate_id")
    _sha(previous_table_id, "previous_table_id")


def build_training_candidate_table(
    *,
    market: str,
    fold: int,
    selection_start: str,
    selection_end: str,
    test_start: str,
    test_end: str,
    candidate_records: Iterable[Mapping[str, Any]],
    previous_s4_candidate_id: str | None,
    previous_table_id: str | None,
    data_sha256: str,
    code_sha256: str,
    research_config_sha256: str,
    fee_config_sha256: str,
) -> dict[str, Any]:
    if market not in DEVELOPMENT_MARKETS:
        raise ValueError("market must be a frozen BTC-USDT or ETH-USDT development market")
    if isinstance(fold, bool) or not isinstance(fold, Integral) or not 1 <= fold <= FOLD_COUNT:
        raise ValueError("fold must be an integer from 1 through 12")
    fold_number = int(fold)
    start, end, test, finish = _validate_window(
        selection_start,
        selection_end,
        test_start,
        test_end,
    )
    _validate_predecessor(
        fold=fold_number,
        previous_s4_candidate_id=previous_s4_candidate_id,
        previous_table_id=previous_table_id,
    )

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for order, source in enumerate(candidate_records):
        if not isinstance(source, Mapping):
            raise ValueError("candidate record must be a mapping")
        forbidden = set(source) & FORBIDDEN_FIELDS
        if forbidden:
            raise ValueError(f"candidate contains forbidden OOS fields: {sorted(forbidden)}")
        if set(source) != CANDIDATE_INPUT_KEYS:
            raise ValueError("candidate input fields do not match the frozen schema")
        config = _frozen_config(source["config"], order=order)
        candidate_id = _sha256(canonical_json_bytes(config))
        if candidate_id in seen:
            raise ValueError("duplicate candidate configuration")
        seen.add(candidate_id)
        metrics = _metrics(source["training_metrics"])
        score = _validated_training_score(source["training_score"], metrics)
        position = _finite(
            source["first_causal_oos_target_position"],
            "first_causal_oos_target_position",
        )
        if not config["min_position"] <= position <= config["max_abs_position"]:
            raise ValueError("first causal OOS target position violates configuration bounds")
        rows.append(
            {
                "candidate_id": candidate_id,
                "candidate_order_index": order,
                "configuration": config,
                "configuration_sha256": candidate_id,
                "training_score": score,
                "training_metrics": metrics,
                "first_causal_oos_target_position": position,
                "prior_percentile_ranks": _prior_ranks(
                    source["prior_percentile_ranks"],
                    fold=fold_number,
                ),
            }
        )
    if len(rows) != CANDIDATE_COUNT:
        raise ValueError("candidate table must contain exactly 27 candidates")
    if previous_s4_candidate_id is not None and previous_s4_candidate_id not in seen:
        raise ValueError("previous_s4_candidate_id is not present in the candidate table")

    ranked = sorted(
        rows,
        key=lambda row: (-row["training_score"], row["candidate_order_index"]),
    )
    winner = ranked[0]
    rank_by_id = {row["candidate_id"]: rank for rank, row in enumerate(ranked, 1)}
    runner_up_gap = winner["training_score"] - ranked[1]["training_score"]

    records: list[dict[str, Any]] = []
    for row in rows:
        rank = rank_by_id[row["candidate_id"]]
        percentile = (CANDIDATE_COUNT - rank) / (CANDIDATE_COUNT - 1)
        prior = row["prior_percentile_ranks"]
        prior_mean = sum(prior) / len(prior) if prior else None
        metrics = row["training_metrics"]
        row.update(
            {
                "score_rank": rank,
                "percentile_rank": percentile,
                "prior_fold_rank_count": len(prior),
                "prior_fold_mean_percentile_rank": prior_mean,
                "mean_percentile_rank_through_fold": (sum(prior) + percentile) / (len(prior) + 1),
                "runner_up_score_gap": (
                    runner_up_gap if row["candidate_id"] == winner["candidate_id"] else None
                ),
                "s2_geometric_neighbourhood_member": _s2_member(
                    row["configuration"],
                    winner["configuration"],
                ),
                "s5_positive_evidence_member": (
                    metrics["total_return"] > 0.0 and metrics["sharpe"] > 0.0
                ),
                "previous_s4_candidate": row["candidate_id"] == previous_s4_candidate_id,
            }
        )
        records.append(row)

    body = {
        "schema_version": SCHEMA_VERSION,
        "family_id": FAMILY_ID,
        "bar": "1H",
        "market": market,
        "fold": fold_number,
        "fold_count": FOLD_COUNT,
        "selection_bars": SELECTION_BARS,
        "test_bars": TEST_BARS,
        "selection_start": start,
        "selection_end": end,
        "test_start": test,
        "test_end": finish,
        "score_tie_break": SCORE_TIE_BREAK,
        "s2_geometry": S2_GEOMETRY,
        "candidate_count": CANDIDATE_COUNT,
        "modeled_fee": FEE,
        "hashes": {
            "data_sha256": _sha(data_sha256, "data_sha256"),
            "code_sha256": _sha(code_sha256, "code_sha256"),
            "research_config_sha256": _sha(
                research_config_sha256,
                "research_config_sha256",
            ),
            "fee_config_sha256": _sha(fee_config_sha256, "fee_config_sha256"),
        },
        "winner_candidate_id": winner["candidate_id"],
        "previous_s4_candidate_id": previous_s4_candidate_id,
        "previous_table_id": previous_table_id,
        "records": records,
    }
    return {**body, "table_id": _sha256(canonical_json_bytes(body))}


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError(f"duplicate JSON field: {key}")
        payload[key] = value
    return payload


def reconstruct_training_candidate_table(raw: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw, object_pairs_hook=_reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("selector evidence must be valid UTF-8 JSON") from exc
    if not isinstance(payload, Mapping) or canonical_json_bytes(payload) != raw:
        raise ValueError("selector evidence must be a canonical JSON object")
    if set(payload) != TABLE_KEYS:
        raise ValueError("selector evidence top-level fields do not match schema")
    if payload["schema_version"] != SCHEMA_VERSION:
        raise ValueError("unsupported selector evidence schema")
    if payload["family_id"] != FAMILY_ID or payload["bar"] != "1H":
        raise ValueError("unsupported selector evidence identity")
    if payload["market"] not in DEVELOPMENT_MARKETS:
        raise ValueError("selector evidence market is not a frozen development market")
    fold = payload["fold"]
    if isinstance(fold, bool) or not isinstance(fold, Integral) or not 1 <= fold <= FOLD_COUNT:
        raise ValueError("fold must be an integer from 1 through 12")
    fold_number = int(fold)
    if payload["fold_count"] != FOLD_COUNT:
        raise ValueError("selector evidence fold count is not canonical")
    if payload["selection_bars"] != SELECTION_BARS or payload["test_bars"] != TEST_BARS:
        raise ValueError("selector evidence window sizes are not canonical")
    _validate_window(
        payload["selection_start"],
        payload["selection_end"],
        payload["test_start"],
        payload["test_end"],
    )
    if payload["score_tie_break"] != SCORE_TIE_BREAK:
        raise ValueError("selector evidence score tie-break is not canonical")
    if payload["s2_geometry"] != S2_GEOMETRY:
        raise ValueError("selector evidence S2 geometry is not canonical")
    if payload["candidate_count"] != CANDIDATE_COUNT:
        raise ValueError("selector evidence must contain the frozen 27-candidate grid")
    if payload["modeled_fee"] != FEE:
        raise ValueError("selector evidence fee is not canonical 5 bps")
    hashes = payload["hashes"]
    if not isinstance(hashes, Mapping) or set(hashes) != HASH_KEYS:
        raise ValueError("selector evidence hashes do not match schema")
    for label, value in hashes.items():
        _sha(value, label)
    winner_id = _sha(payload["winner_candidate_id"], "winner_candidate_id")
    previous_id = payload["previous_s4_candidate_id"]
    previous_table_id = payload["previous_table_id"]
    _validate_predecessor(
        fold=fold_number,
        previous_s4_candidate_id=previous_id,
        previous_table_id=previous_table_id,
    )
    records = payload["records"]
    if not isinstance(records, list) or len(records) != CANDIDATE_COUNT:
        raise ValueError("selector evidence records are incomplete")

    validated: list[tuple[Mapping[str, Any], float]] = []
    ids: list[str] = []
    ranks: list[int] = []
    orders: list[int] = []
    previous_flags = 0
    for record in records:
        if not isinstance(record, Mapping) or set(record) != RECORD_KEYS:
            raise ValueError("selector evidence candidate fields do not match schema")
        order = record["candidate_order_index"]
        if isinstance(order, bool) or not isinstance(order, Integral):
            raise ValueError("candidate_order_index must be an integer")
        order_number = int(order)
        config = _frozen_config(record["configuration"], order=order_number)
        candidate_id = _sha(record["candidate_id"], "candidate_id")
        config_hash = _sha256(canonical_json_bytes(config))
        if candidate_id != config_hash or record["configuration_sha256"] != config_hash:
            raise ValueError("candidate identity does not match configuration")
        metrics = _metrics(record["training_metrics"])
        score = _validated_training_score(record["training_score"], metrics)
        position = _finite(
            record["first_causal_oos_target_position"],
            "first_causal_oos_target_position",
        )
        if not config["min_position"] <= position <= config["max_abs_position"]:
            raise ValueError("first causal OOS target position violates configuration bounds")
        expected_s5 = metrics["total_return"] > 0.0 and metrics["sharpe"] > 0.0
        if (
            _boolean(
                record["s5_positive_evidence_member"],
                "s5_positive_evidence_member",
            )
            != expected_s5
        ):
            raise ValueError("S5 membership does not match training metrics")
        rank = record["score_rank"]
        if isinstance(rank, bool) or not isinstance(rank, Integral):
            raise ValueError("score_rank must be an integer")
        if not 1 <= rank <= CANDIDATE_COUNT:
            raise ValueError("score_rank is outside the frozen candidate grid")
        expected_percentile = (CANDIDATE_COUNT - rank) / (CANDIDATE_COUNT - 1)
        if record["percentile_rank"] != expected_percentile:
            raise ValueError("percentile rank does not match score rank")
        prior = _prior_ranks(record["prior_percentile_ranks"], fold=fold_number)
        if record["prior_fold_rank_count"] != len(prior):
            raise ValueError("prior fold rank count does not match rank history")
        expected_prior_mean = sum(prior) / len(prior) if prior else None
        if record["prior_fold_mean_percentile_rank"] != expected_prior_mean:
            raise ValueError("prior fold rank mean does not match rank history")
        expected_mean = (sum(prior) + expected_percentile) / (len(prior) + 1)
        actual_mean = _finite(
            record["mean_percentile_rank_through_fold"],
            "mean_percentile_rank_through_fold",
        )
        if not math.isclose(actual_mean, expected_mean, rel_tol=0.0, abs_tol=1e-15):
            raise ValueError("mean percentile rank is not reconstructable")
        expected_previous = candidate_id == previous_id
        if (
            _boolean(
                record["previous_s4_candidate"],
                "previous_s4_candidate",
            )
            != expected_previous
        ):
            raise ValueError("previous S4 candidate binding is inconsistent")
        previous_flags += int(expected_previous)
        ids.append(candidate_id)
        ranks.append(int(rank))
        orders.append(order_number)
        validated.append((record, score))

    if previous_flags != (0 if previous_id is None else 1):
        raise ValueError("previous S4 candidate must bind exactly one record")
    if len(set(ids)) != CANDIDATE_COUNT:
        raise ValueError("candidate identities must be unique")
    if sorted(ranks) != list(range(1, CANDIDATE_COUNT + 1)):
        raise ValueError("score ranks must cover 1 through 27")
    if sorted(orders) != list(range(CANDIDATE_COUNT)):
        raise ValueError("candidate order must cover the canonical grid")

    expected = sorted(
        validated,
        key=lambda item: (-item[1], item[0]["candidate_order_index"]),
    )
    actual = sorted(validated, key=lambda item: item[0]["score_rank"])
    if [record["candidate_id"] for record, _ in expected] != [
        record["candidate_id"] for record, _ in actual
    ]:
        raise ValueError("score ranks do not match training scores")
    winner = actual[0][0]
    if winner["candidate_id"] != winner_id:
        raise ValueError("winner_candidate_id does not match score rank 1")
    runner_gap = winner["training_score"] - actual[1][0]["training_score"]
    gap = _finite(winner["runner_up_score_gap"], "runner_up_score_gap")
    if not math.isclose(gap, runner_gap, rel_tol=0.0, abs_tol=1e-15):
        raise ValueError("runner-up gap does not match ranked scores")

    for record, _ in validated:
        expected_s2 = _s2_member(record["configuration"], winner["configuration"])
        if (
            _boolean(
                record["s2_geometric_neighbourhood_member"],
                "s2_geometric_neighbourhood_member",
            )
            != expected_s2
        ):
            raise ValueError("S2 membership does not match frozen geometry")
        if record["candidate_id"] != winner_id and record["runner_up_score_gap"] is not None:
            raise ValueError("runner-up gap may appear only on the winner")

    body = deepcopy(dict(payload))
    table_id = _sha(body.pop("table_id"), "table_id")
    if _sha256(canonical_json_bytes(body)) != table_id:
        raise ValueError("selector evidence table_id does not match canonical contents")
    return deepcopy(dict(payload))


def serialize_training_candidate_table(payload: Mapping[str, Any]) -> bytes:
    raw = canonical_json_bytes(payload)
    reconstruct_training_candidate_table(raw)
    return raw


def validate_training_candidate_table_sequence(
    tables: Sequence[Mapping[str, Any]],
    *,
    require_complete: bool = True,
) -> None:
    expected_count = FOLD_COUNT if require_complete else None
    if not tables or (expected_count is not None and len(tables) != expected_count):
        message = "selector evidence sequence must contain all 12 folds"
        if not tables and not require_complete:
            message = "selector evidence sequence cannot be empty"
        raise ValueError(message)

    first = reconstruct_training_candidate_table(canonical_json_bytes(tables[0]))
    first_market = first["market"]
    canonical_hashes = first["hashes"]
    candidate_order: list[str] | None = None
    rank_history: dict[str, list[float]] = {}
    expected_previous_s4: str | None = None
    previous_table_id: str | None = None
    previous_times: tuple[datetime, datetime, datetime, datetime] | None = None

    for expected_fold, table in enumerate(tables, start=1):
        payload = reconstruct_training_candidate_table(canonical_json_bytes(table))
        if payload["market"] != first_market:
            raise ValueError("selector evidence sequence cannot mix markets")
        if payload["fold"] != expected_fold:
            raise ValueError("selector evidence folds must be consecutive from one")
        if payload["hashes"] != canonical_hashes:
            raise ValueError("selector evidence hashes changed between folds")
        if payload["previous_table_id"] != previous_table_id:
            raise ValueError("selector evidence predecessor table chain is broken")
        if payload["previous_s4_candidate_id"] != expected_previous_s4:
            raise ValueError("selector evidence previous S4 state is not reconstructable")

        times = (
            _utc_hour(payload["selection_start"], "selection_start"),
            _utc_hour(payload["selection_end"], "selection_end"),
            _utc_hour(payload["test_start"], "test_start"),
            _utc_hour(payload["test_end"], "test_end"),
        )
        if previous_times is not None:
            expected_times = tuple(value + BAR_DELTA * TEST_BARS for value in previous_times)
            if times != expected_times:
                raise ValueError("selector evidence fold chronology is not canonical")
        previous_times = times

        ordered = sorted(
            payload["records"],
            key=lambda row: row["candidate_order_index"],
        )
        current_order = [row["candidate_id"] for row in ordered]
        if candidate_order is None:
            candidate_order = current_order
            rank_history = {candidate_id: [] for candidate_id in current_order}
        elif current_order != candidate_order:
            raise ValueError("selector evidence candidate grid changed between folds")

        for record in ordered:
            candidate_id = record["candidate_id"]
            if record["prior_percentile_ranks"] != rank_history[candidate_id]:
                raise ValueError("selector evidence prior ranks do not match earlier tables")
            rank_history[candidate_id].append(record["percentile_rank"])

        if expected_previous_s4 is None:
            current_s4 = payload["winner_candidate_id"]
        else:
            previous_record = next(
                row for row in payload["records"] if row["candidate_id"] == expected_previous_s4
            )
            current_s4 = (
                expected_previous_s4
                if previous_record["score_rank"] <= 2
                else payload["winner_candidate_id"]
            )
        expected_previous_s4 = current_s4
        previous_table_id = payload["table_id"]
