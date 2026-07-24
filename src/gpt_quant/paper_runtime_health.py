from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from .paper_execution_reconciliation import PaperExecutionReconciliationEvidence

_SCHEMA_VERSION = 1
_DISABLED = "disabled"
_STATUS_HEALTHY = "healthy"
_STATUS_BLOCKED = "blocked"
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
    "heartbeat_age_ms",
    "completed_bar_age_ms",
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
    "status",
    "blockers",
}
_SERIALIZED_FIELDS = _FIELDS | {"health_id"}


def _canonical_json_bytes(value: Mapping[str, object]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"paper runtime health JSON contains duplicate field {key!r}")
        result[key] = value
    return result


def _utc(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{field_name} must be a timezone-aware datetime")
    return value.astimezone(UTC)


def _non_negative_int(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _positive_int(value: object, *, field_name: str) -> int:
    parsed = _non_negative_int(value, field_name=field_name)
    if parsed == 0:
        raise ValueError(f"{field_name} must be positive")
    return parsed


def _ceil_milliseconds(delta: timedelta) -> int:
    total_microseconds = (
        delta.days * 86_400_000_000 + delta.seconds * 1_000_000 + delta.microseconds
    )
    if total_microseconds < 0:
        raise ValueError("runtime evidence timestamp must not be in the future")
    return (total_microseconds + 999) // 1_000


def _timestamp(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be an ISO-8601 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO-8601 UTC timestamp") from exc
    return _utc(parsed, field_name=field_name)


@dataclass(frozen=True, slots=True)
class PaperRuntimeHealthSnapshot:
    """Content-addressed, read-only health evidence for an offline paper runtime.

    This record does not authorize paper or live execution. It reports whether a
    disabled-by-default runtime is inside its declared operating envelope and binds
    that result to an already content-addressed reconciliation record.
    """

    observed_at_utc: datetime
    last_completed_bar_close_utc: datetime
    last_heartbeat_utc: datetime
    heartbeat_age_ms: int
    completed_bar_age_ms: int
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
    status: str = field(init=False)
    blockers: tuple[str, ...] = field(init=False)
    schema_version: int = field(default=_SCHEMA_VERSION, init=False)
    health_id: str = field(init=False)

    def __post_init__(self) -> None:
        for name in (
            "observed_at_utc",
            "last_completed_bar_close_utc",
            "last_heartbeat_utc",
        ):
            object.__setattr__(self, name, _utc(getattr(self, name), field_name=name))
        for name in (
            "heartbeat_age_ms",
            "completed_bar_age_ms",
            "event_loop_lag_ms",
            "queue_depth",
        ):
            object.__setattr__(
                self,
                name,
                _non_negative_int(getattr(self, name), field_name=name),
            )
        for name in (
            "queue_capacity",
            "maximum_heartbeat_age_ms",
            "maximum_completed_bar_age_ms",
            "maximum_event_loop_lag_ms",
        ):
            object.__setattr__(
                self,
                name,
                _positive_int(getattr(self, name), field_name=name),
            )
        if not isinstance(self.reconciliation_verified, bool):
            raise ValueError("reconciliation_verified must be a boolean")
        if not isinstance(self.reconciliation_id, str) or len(self.reconciliation_id) != 64:
            raise ValueError("reconciliation_id must be a lowercase SHA-256 digest")
        try:
            int(self.reconciliation_id, 16)
        except ValueError as exc:
            raise ValueError("reconciliation_id must be a lowercase SHA-256 digest") from exc
        if self.reconciliation_id != self.reconciliation_id.lower():
            raise ValueError("reconciliation_id must be a lowercase SHA-256 digest")
        if not isinstance(self.account_adapter_state, str) or not self.account_adapter_state:
            raise ValueError("account_adapter_state must be a non-empty string")
        if not isinstance(self.order_adapter_state, str) or not self.order_adapter_state:
            raise ValueError("order_adapter_state must be a non-empty string")

        expected_heartbeat_age = _ceil_milliseconds(
            self.observed_at_utc - self.last_heartbeat_utc
        )
        expected_bar_age = _ceil_milliseconds(
            self.observed_at_utc - self.last_completed_bar_close_utc
        )
        if self.heartbeat_age_ms != expected_heartbeat_age:
            raise ValueError("heartbeat_age_ms does not match runtime timestamps")
        if self.completed_bar_age_ms != expected_bar_age:
            raise ValueError("completed_bar_age_ms does not match runtime timestamps")

        blockers: list[str] = []
        if not self.reconciliation_verified:
            blockers.append("reconciliation_unverified")
        if self.heartbeat_age_ms > self.maximum_heartbeat_age_ms:
            blockers.append("heartbeat_stale")
        if self.completed_bar_age_ms > self.maximum_completed_bar_age_ms:
            blockers.append("completed_bar_stale")
        if self.event_loop_lag_ms > self.maximum_event_loop_lag_ms:
            blockers.append("event_loop_lag_exceeded")
        if self.queue_depth >= self.queue_capacity:
            blockers.append("queue_saturated")
        if self.account_adapter_state != _DISABLED:
            blockers.append("account_adapter_not_disabled")
        if self.order_adapter_state != _DISABLED:
            blockers.append("order_adapter_not_disabled")
        ordered = tuple(item for item in _BLOCKER_ORDER if item in blockers)
        object.__setattr__(self, "blockers", ordered)
        object.__setattr__(self, "status", _STATUS_HEALTHY if not ordered else _STATUS_BLOCKED)
        object.__setattr__(self, "health_id", hashlib.sha256(_canonical_json_bytes(self._payload())).hexdigest())

    @property
    def runtime_healthy(self) -> bool:
        return self.status == _STATUS_HEALTHY

    def _payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "observed_at_utc": self.observed_at_utc.isoformat(),
            "last_completed_bar_close_utc": self.last_completed_bar_close_utc.isoformat(),
            "last_heartbeat_utc": self.last_heartbeat_utc.isoformat(),
            "heartbeat_age_ms": self.heartbeat_age_ms,
            "completed_bar_age_ms": self.completed_bar_age_ms,
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
            "status": self.status,
            "blockers": list(self.blockers),
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "health_id": self.health_id}

    def to_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())

    @classmethod
    def from_mapping(cls, value: object) -> PaperRuntimeHealthSnapshot:
        if not isinstance(value, Mapping):
            raise ValueError("paper runtime health must be a mapping")
        keys = set(value)
        if keys != _SERIALIZED_FIELDS:
            missing = sorted(_SERIALIZED_FIELDS - keys)
            unexpected = sorted(repr(key) for key in keys - _SERIALIZED_FIELDS)
            raise ValueError(
                "paper runtime health fields do not match schema; "
                f"missing={missing}, unexpected={unexpected}"
            )
        if value["schema_version"] != _SCHEMA_VERSION:
            raise ValueError(f"unsupported paper runtime health schema {value['schema_version']!r}")
        blockers = value["blockers"]
        if not isinstance(blockers, list) or any(not isinstance(item, str) for item in blockers):
            raise ValueError("paper runtime health blockers must be a list of strings")
        snapshot = cls(
            observed_at_utc=_timestamp(value["observed_at_utc"], field_name="observed_at_utc"),
            last_completed_bar_close_utc=_timestamp(
                value["last_completed_bar_close_utc"],
                field_name="last_completed_bar_close_utc",
            ),
            last_heartbeat_utc=_timestamp(
                value["last_heartbeat_utc"], field_name="last_heartbeat_utc"
            ),
            heartbeat_age_ms=value["heartbeat_age_ms"],
            completed_bar_age_ms=value["completed_bar_age_ms"],
            event_loop_lag_ms=value["event_loop_lag_ms"],
            queue_depth=value["queue_depth"],
            queue_capacity=value["queue_capacity"],
            maximum_heartbeat_age_ms=value["maximum_heartbeat_age_ms"],
            maximum_completed_bar_age_ms=value["maximum_completed_bar_age_ms"],
            maximum_event_loop_lag_ms=value["maximum_event_loop_lag_ms"],
            reconciliation_id=value["reconciliation_id"],
            reconciliation_verified=value["reconciliation_verified"],
            account_adapter_state=value["account_adapter_state"],
            order_adapter_state=value["order_adapter_state"],
        )
        if value["status"] != snapshot.status or tuple(blockers) != snapshot.blockers:
            raise ValueError("paper runtime health status does not match measured evidence")
        if value["health_id"] != snapshot.health_id:
            raise ValueError("paper runtime health ID does not match canonical payload")
        return snapshot

    @classmethod
    def from_json_bytes(cls, value: bytes | str) -> PaperRuntimeHealthSnapshot:
        if isinstance(value, bytes):
            try:
                serialized = value.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError("paper runtime health JSON is unreadable") from exc
        elif isinstance(value, str):
            serialized = value
        else:
            raise ValueError("paper runtime health JSON is unreadable")
        try:
            payload = json.loads(serialized, object_pairs_hook=_reject_duplicates)
        except (TypeError, ValueError) as exc:
            raise ValueError("paper runtime health JSON is unreadable") from exc
        snapshot = cls.from_mapping(payload)
        if snapshot.to_json_bytes() != serialized.encode("utf-8"):
            raise ValueError("paper runtime health JSON must use canonical encoding")
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
    """Measure a fail-closed runtime envelope without authorizing connectivity."""

    if not isinstance(reconciliation, PaperExecutionReconciliationEvidence):
        raise TypeError("reconciliation must be PaperExecutionReconciliationEvidence")
    observed = _utc(observed_at_utc, field_name="observed_at_utc")
    heartbeat = _utc(last_heartbeat_utc, field_name="last_heartbeat_utc")
    bar_close = _utc(
        last_completed_bar_close_utc,
        field_name="last_completed_bar_close_utc",
    )
    return PaperRuntimeHealthSnapshot(
        observed_at_utc=observed,
        last_completed_bar_close_utc=bar_close,
        last_heartbeat_utc=heartbeat,
        heartbeat_age_ms=_ceil_milliseconds(observed - heartbeat),
        completed_bar_age_ms=_ceil_milliseconds(observed - bar_close),
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
