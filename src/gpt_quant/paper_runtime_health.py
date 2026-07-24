from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from .paper_execution_reconciliation import PaperExecutionReconciliationEvidence

_SCHEMA_VERSION = 1
_DISABLED = "disabled"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_BLOCKER_ORDER = (
    "reconciliation_unverified",
    "heartbeat_stale",
    "completed_bar_stale",
    "event_loop_lag_exceeded",
    "queue_saturated",
    "account_adapter_not_disabled",
    "order_adapter_not_disabled",
)
_FIELDS = {
    "schema_version",
    "observed_at_utc",
    "last_completed_bar_close_utc",
    "last_heartbeat_utc",
    "event_loop_lag_ms",
    "queue_depth",
    "queue_capacity",
    "maximum_heartbeat_age_ms",
    "maximum_completed_bar_age_ms",
    "maximum_event_loop_lag_ms",
    "reconciliation_id",
    "reconciliation_verified",
    "account_adapter_state",
    "order_adapter_state",
    "heartbeat_age_ms",
    "completed_bar_age_ms",
    "status",
    "blockers",
    "health_id",
}


def _canonical_json(value: Mapping[str, object]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()


def _duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate paper runtime health field {key!r}")
        result[key] = value
    return result


def _utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _timestamp(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be an ISO-8601 timestamp")
    try:
        return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")), name)
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO-8601 timestamp") from exc


def _integer(value: object, name: str, *, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    minimum = 1 if positive else 0
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


def _age_ms(observed: datetime, earlier: datetime) -> int:
    microseconds = int((observed - earlier) / timedelta(microseconds=1))
    if microseconds < 0:
        raise ValueError("runtime evidence timestamp must not be in the future")
    return (microseconds + 999) // 1_000


@dataclass(frozen=True, slots=True)
class PaperRuntimeHealthSnapshot:
    """Read-only fail-closed health evidence; never execution authorization."""

    observed_at_utc: datetime
    last_completed_bar_close_utc: datetime
    last_heartbeat_utc: datetime
    event_loop_lag_ms: int
    queue_depth: int
    queue_capacity: int
    maximum_heartbeat_age_ms: int
    maximum_completed_bar_age_ms: int
    maximum_event_loop_lag_ms: int
    reconciliation_id: str
    reconciliation_verified: bool
    account_adapter_state: str = _DISABLED
    order_adapter_state: str = _DISABLED
    heartbeat_age_ms: int = field(init=False)
    completed_bar_age_ms: int = field(init=False)
    status: str = field(init=False)
    blockers: tuple[str, ...] = field(init=False)
    health_id: str = field(init=False)
    schema_version: int = field(default=_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        observed = _utc(self.observed_at_utc, "observed_at_utc")
        heartbeat = _utc(self.last_heartbeat_utc, "last_heartbeat_utc")
        bar_close = _utc(
            self.last_completed_bar_close_utc,
            "last_completed_bar_close_utc",
        )
        object.__setattr__(self, "observed_at_utc", observed)
        object.__setattr__(self, "last_heartbeat_utc", heartbeat)
        object.__setattr__(self, "last_completed_bar_close_utc", bar_close)
        heartbeat_age = _age_ms(observed, heartbeat)
        bar_age = _age_ms(observed, bar_close)
        object.__setattr__(self, "heartbeat_age_ms", heartbeat_age)
        object.__setattr__(self, "completed_bar_age_ms", bar_age)

        for name in ("event_loop_lag_ms", "queue_depth"):
            _integer(getattr(self, name), name)
        for name in (
            "queue_capacity",
            "maximum_heartbeat_age_ms",
            "maximum_completed_bar_age_ms",
            "maximum_event_loop_lag_ms",
        ):
            _integer(getattr(self, name), name, positive=True)
        if not isinstance(self.reconciliation_verified, bool):
            raise ValueError("reconciliation_verified must be a boolean")
        if not isinstance(self.reconciliation_id, str) or not _SHA256.fullmatch(
            self.reconciliation_id
        ):
            raise ValueError("reconciliation_id must be a lowercase SHA-256")

        blockers: list[str] = []
        checks = (
            (not self.reconciliation_verified, "reconciliation_unverified"),
            (heartbeat_age > self.maximum_heartbeat_age_ms, "heartbeat_stale"),
            (bar_age > self.maximum_completed_bar_age_ms, "completed_bar_stale"),
            (
                self.event_loop_lag_ms > self.maximum_event_loop_lag_ms,
                "event_loop_lag_exceeded",
            ),
            (self.queue_depth >= self.queue_capacity, "queue_saturated"),
            (self.account_adapter_state != _DISABLED, "account_adapter_not_disabled"),
            (self.order_adapter_state != _DISABLED, "order_adapter_not_disabled"),
        )
        blockers.extend(label for failed, label in checks if failed)
        ordered = tuple(label for label in _BLOCKER_ORDER if label in blockers)
        object.__setattr__(self, "blockers", ordered)
        object.__setattr__(self, "status", "healthy" if not ordered else "blocked")
        object.__setattr__(
            self,
            "health_id",
            hashlib.sha256(_canonical_json(self._payload())).hexdigest(),
        )

    @property
    def runtime_healthy(self) -> bool:
        return self.status == "healthy"

    def _payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "observed_at_utc": self.observed_at_utc.isoformat(),
            "last_completed_bar_close_utc": self.last_completed_bar_close_utc.isoformat(),
            "last_heartbeat_utc": self.last_heartbeat_utc.isoformat(),
            "event_loop_lag_ms": self.event_loop_lag_ms,
            "queue_depth": self.queue_depth,
            "queue_capacity": self.queue_capacity,
            "maximum_heartbeat_age_ms": self.maximum_heartbeat_age_ms,
            "maximum_completed_bar_age_ms": self.maximum_completed_bar_age_ms,
            "maximum_event_loop_lag_ms": self.maximum_event_loop_lag_ms,
            "reconciliation_id": self.reconciliation_id,
            "reconciliation_verified": self.reconciliation_verified,
            "account_adapter_state": self.account_adapter_state,
            "order_adapter_state": self.order_adapter_state,
            "heartbeat_age_ms": self.heartbeat_age_ms,
            "completed_bar_age_ms": self.completed_bar_age_ms,
            "status": self.status,
            "blockers": list(self.blockers),
        }

    def to_json_bytes(self) -> bytes:
        return _canonical_json({**self._payload(), "health_id": self.health_id})

    @classmethod
    def from_json_bytes(cls, value: bytes) -> PaperRuntimeHealthSnapshot:
        try:
            payload = json.loads(value, object_pairs_hook=_duplicates)
        except (TypeError, ValueError) as exc:
            raise ValueError("paper runtime health JSON is unreadable") from exc
        if not isinstance(payload, dict) or set(payload) != _FIELDS:
            raise ValueError("paper runtime health fields do not match schema")
        if payload["schema_version"] != _SCHEMA_VERSION:
            raise ValueError("unsupported paper runtime health schema")
        snapshot = cls(
            observed_at_utc=_timestamp(payload["observed_at_utc"], "observed_at_utc"),
            last_completed_bar_close_utc=_timestamp(
                payload["last_completed_bar_close_utc"],
                "last_completed_bar_close_utc",
            ),
            last_heartbeat_utc=_timestamp(
                payload["last_heartbeat_utc"],
                "last_heartbeat_utc",
            ),
            event_loop_lag_ms=payload["event_loop_lag_ms"],
            queue_depth=payload["queue_depth"],
            queue_capacity=payload["queue_capacity"],
            maximum_heartbeat_age_ms=payload["maximum_heartbeat_age_ms"],
            maximum_completed_bar_age_ms=payload["maximum_completed_bar_age_ms"],
            maximum_event_loop_lag_ms=payload["maximum_event_loop_lag_ms"],
            reconciliation_id=payload["reconciliation_id"],
            reconciliation_verified=payload["reconciliation_verified"],
            account_adapter_state=payload["account_adapter_state"],
            order_adapter_state=payload["order_adapter_state"],
        )
        expected = {**snapshot._payload(), "health_id": snapshot.health_id}
        if payload != expected or snapshot.to_json_bytes() != value:
            raise ValueError("paper runtime health does not match measured evidence")
        return snapshot


def evaluate_paper_runtime_health(
    *,
    observed_at_utc: datetime,
    last_completed_bar_close_utc: datetime,
    last_heartbeat_utc: datetime,
    event_loop_lag_ms: int,
    queue_depth: int,
    queue_capacity: int,
    maximum_heartbeat_age_ms: int,
    maximum_completed_bar_age_ms: int,
    maximum_event_loop_lag_ms: int,
    reconciliation: PaperExecutionReconciliationEvidence,
    reconciliation_verified: bool,
    account_adapter_state: str = _DISABLED,
    order_adapter_state: str = _DISABLED,
) -> PaperRuntimeHealthSnapshot:
    if not isinstance(reconciliation, PaperExecutionReconciliationEvidence):
        raise TypeError("reconciliation must be PaperExecutionReconciliationEvidence")
    return PaperRuntimeHealthSnapshot(
        observed_at_utc=observed_at_utc,
        last_completed_bar_close_utc=last_completed_bar_close_utc,
        last_heartbeat_utc=last_heartbeat_utc,
        event_loop_lag_ms=event_loop_lag_ms,
        queue_depth=queue_depth,
        queue_capacity=queue_capacity,
        maximum_heartbeat_age_ms=maximum_heartbeat_age_ms,
        maximum_completed_bar_age_ms=maximum_completed_bar_age_ms,
        maximum_event_loop_lag_ms=maximum_event_loop_lag_ms,
        reconciliation_id=reconciliation.reconciliation_id,
        reconciliation_verified=reconciliation_verified,
        account_adapter_state=account_adapter_state,
        order_adapter_state=order_adapter_state,
    )
