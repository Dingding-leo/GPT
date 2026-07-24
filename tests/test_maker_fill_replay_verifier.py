from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from gpt_quant.maker_fill_replay import (
    OKXPublicTradeSnapshot,
    simulate_post_only_maker_fill,
)
from gpt_quant.maker_fill_replay_verifier import verify_maker_fill_replay_bytes

_FIXTURE = (
    Path(__file__).parent / "fixtures" / "okx" / "trades-btc-usdt-docs-20220602" / "response.json"
)
_ORDER_INTENT_ID = "a" * 64


def _source_and_replay():
    raw = _FIXTURE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "01438cc23709d9c8e9ea8d9d49d3f64c65978d27d592356a333f7a3da213d563"
    )
    snapshot = OKXPublicTradeSnapshot.from_json_bytes(raw)
    replay = simulate_post_only_maker_fill(
        snapshot,
        order_intent_id=_ORDER_INTENT_ID,
        signal_at_utc=datetime(2022, 6, 2, 9, 0, tzinfo=UTC),
        submitted_at_utc=datetime(2022, 6, 2, 9, 20, 40, tzinfo=UTC),
        expires_at_utc=datetime(2022, 6, 2, 9, 20, 50, tzinfo=UTC),
        side="buy",
        limit_price="29964.1",
        requested_base_quantity="0.000005",
        queue_ahead_base_quantity="0",
    )
    return snapshot, replay


def _canonical_with_recomputed_id(payload: dict[str, object]) -> bytes:
    body = dict(payload)
    body.pop("replay_id", None)
    canonical_body = json.dumps(
        body,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    payload["replay_id"] = hashlib.sha256(canonical_body).hexdigest()
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )


def test_exact_real_okx_replay_reconstructs_byte_for_byte() -> None:
    snapshot, replay = _source_and_replay()

    reconstructed = verify_maker_fill_replay_bytes(snapshot, replay.to_json_bytes())

    assert reconstructed == replay
    assert reconstructed.to_json_bytes() == replay.to_json_bytes()


@pytest.mark.parametrize(
    ("field", "forged_value"),
    [
        ("exchange_fee_quote", "0"),
        ("filled_base_quantity", "0.000004"),
        ("outcome", "cancelled_partial"),
    ],
)
def test_self_rehashed_forged_execution_fields_fail_source_reconstruction(
    field: str,
    forged_value: str,
) -> None:
    snapshot, replay = _source_and_replay()
    payload = json.loads(replay.to_json_bytes())
    payload[field] = forged_value
    forged = _canonical_with_recomputed_id(payload)

    with pytest.raises(ValueError, match="deterministic source reconstruction"):
        verify_maker_fill_replay_bytes(snapshot, forged)


def test_duplicate_persisted_fields_fail_closed_before_reconstruction() -> None:
    snapshot, replay = _source_and_replay()
    duplicated = replay.to_json_bytes().replace(
        b'"outcome":"filled"',
        b'"outcome":"filled","outcome":"cancelled_no_fill"',
        1,
    )

    with pytest.raises(ValueError, match="duplicate field 'outcome'"):
        verify_maker_fill_replay_bytes(snapshot, duplicated)
