from __future__ import annotations

import json
import re
from collections.abc import Mapping

from gpt_quant.maker_fill_replay import (
    MakerFillReplay,
    OKXPublicTradeSnapshot,
    simulate_post_only_maker_fill,
)

_SHA256 = re.compile(r"[0-9a-f]{64}")
_REQUIRED_INPUT_FIELDS = {
    "order_intent_id",
    "signal_at_utc",
    "submitted_at_utc",
    "expires_at_utc",
    "side",
    "limit_price",
    "requested_base_quantity",
    "queue_ahead_base_quantity",
    "replay_id",
}


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"maker fill replay contains duplicate field {key!r}")
        result[key] = value
    return result


def verify_maker_fill_replay_bytes(
    snapshot: OKXPublicTradeSnapshot,
    value: bytes,
) -> MakerFillReplay:
    """Reconstruct one persisted maker replay from its exact public-trade source.

    Verification is intentionally stronger than checking ``replay_id`` alone. The
    canonical record is regenerated through the execution model, then every byte
    must match the persisted record. This rejects a forged but self-consistently
    rehashed fee, fill outcome, quantity, timestamp, queue, or source identity.
    """

    if not isinstance(value, bytes):
        raise TypeError("value must be bytes")
    try:
        payload = json.loads(value.decode("utf-8"), object_pairs_hook=_reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("maker fill replay JSON is unreadable") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("maker fill replay must be a JSON object")
    missing = _REQUIRED_INPUT_FIELDS.difference(payload)
    if missing:
        raise ValueError(f"maker fill replay is missing required fields: {sorted(missing)!r}")
    replay_id = payload["replay_id"]
    if not isinstance(replay_id, str) or _SHA256.fullmatch(replay_id) is None:
        raise ValueError("replay_id must be a lowercase SHA-256 digest")

    reconstructed = simulate_post_only_maker_fill(
        snapshot,
        order_intent_id=payload["order_intent_id"],
        signal_at_utc=payload["signal_at_utc"],
        submitted_at_utc=payload["submitted_at_utc"],
        expires_at_utc=payload["expires_at_utc"],
        side=payload["side"],
        limit_price=payload["limit_price"],
        requested_base_quantity=payload["requested_base_quantity"],
        queue_ahead_base_quantity=payload["queue_ahead_base_quantity"],
    )
    if reconstructed.to_json_bytes() != value:
        raise ValueError("maker fill replay does not match deterministic source reconstruction")
    return reconstructed
