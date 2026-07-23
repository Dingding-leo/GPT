from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from numbers import Real

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_REVISION_PATTERN = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_SCHEMA_VERSION = 1
_PAYLOAD_KEYS = {
    "schema_version",
    "instrument_id",
    "bar",
    "strategy_id",
    "strategy_revision",
    "source_data_sha256",
    "config_sha256",
    "signal_bar_open_utc",
    "signal_bar_close_utc",
    "decision_not_before_utc",
    "expires_at_utc",
    "target_position",
    "minimum_position",
    "maximum_position",
}
_SERIALIZED_KEYS = _PAYLOAD_KEYS | {"intent_id"}


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"{field_name} must be a non-empty trimmed string")
    if any(ord(character) < 32 for character in value):
        raise ValueError(f"{field_name} must not contain control characters")
    return value


def _required_hash(value: object, *, field_name: str) -> str:
    parsed = _required_text(value, field_name=field_name)
    if _SHA256_PATTERN.fullmatch(parsed) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return parsed


def _required_revision(value: object) -> str:
    parsed = _required_text(value, field_name="strategy_revision")
    if _REVISION_PATTERN.fullmatch(parsed) is None:
        raise ValueError("strategy_revision must be a lowercase 40- or 64-character commit digest")
    return parsed


def _required_utc_datetime(value: object, *, field_name: str) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field_name} must be a timezone-aware timestamp") from exc
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise ValueError(f"{field_name} must be a timezone-aware timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be a timezone-aware timestamp")
    return parsed.astimezone(UTC)


def _required_real(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{field_name} must be a finite real number")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"{field_name} must be a finite real number")
    return 0.0 if parsed == 0.0 else parsed


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical_json_bytes(payload: Mapping[str, object]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _reject_duplicate_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"target-position intent JSON contains duplicate field {key!r}")
        result[key] = value
    return result


@dataclass(frozen=True, slots=True)
class TargetPositionIntent:
    """Immutable, replayable strategy target awaiting execution translation.

    This object is deliberately not an exchange order. It binds a target position to
    the exact completed signal bar, source/config hashes, strategy revision, and valid
    decision window. A later execution adapter must translate it into lot-rounded order
    instructions using current portfolio state and separately versioned spread, slippage,
    impact, and latency assumptions.
    """

    instrument_id: str
    bar: str
    strategy_id: str
    strategy_revision: str
    source_data_sha256: str
    config_sha256: str
    signal_bar_open_utc: datetime
    signal_bar_close_utc: datetime
    decision_not_before_utc: datetime
    expires_at_utc: datetime
    target_position: float
    minimum_position: float
    maximum_position: float
    schema_version: int = field(default=_SCHEMA_VERSION, init=False)
    intent_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "instrument_id",
            _required_text(self.instrument_id, field_name="instrument_id"),
        )
        object.__setattr__(self, "bar", _required_text(self.bar, field_name="bar"))
        object.__setattr__(
            self,
            "strategy_id",
            _required_text(self.strategy_id, field_name="strategy_id"),
        )
        object.__setattr__(self, "strategy_revision", _required_revision(self.strategy_revision))
        object.__setattr__(
            self,
            "source_data_sha256",
            _required_hash(self.source_data_sha256, field_name="source_data_sha256"),
        )
        object.__setattr__(
            self,
            "config_sha256",
            _required_hash(self.config_sha256, field_name="config_sha256"),
        )

        for field_name in (
            "signal_bar_open_utc",
            "signal_bar_close_utc",
            "decision_not_before_utc",
            "expires_at_utc",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_utc_datetime(getattr(self, field_name), field_name=field_name),
            )

        minimum_position = _required_real(
            self.minimum_position,
            field_name="minimum_position",
        )
        maximum_position = _required_real(
            self.maximum_position,
            field_name="maximum_position",
        )
        target_position = _required_real(self.target_position, field_name="target_position")
        if minimum_position >= maximum_position:
            raise ValueError("minimum_position must be less than maximum_position")
        if not minimum_position <= target_position <= maximum_position:
            raise ValueError("target_position must lie within the declared position limits")
        object.__setattr__(self, "minimum_position", minimum_position)
        object.__setattr__(self, "maximum_position", maximum_position)
        object.__setattr__(self, "target_position", target_position)

        if self.signal_bar_close_utc <= self.signal_bar_open_utc:
            raise ValueError("signal_bar_close_utc must be after signal_bar_open_utc")
        if self.decision_not_before_utc < self.signal_bar_close_utc:
            raise ValueError("decision_not_before_utc cannot precede the signal bar close")
        if self.expires_at_utc <= self.decision_not_before_utc:
            raise ValueError("expires_at_utc must be after decision_not_before_utc")

        object.__setattr__(
            self,
            "intent_id",
            hashlib.sha256(_canonical_json_bytes(self._payload())).hexdigest(),
        )

    def _payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "instrument_id": self.instrument_id,
            "bar": self.bar,
            "strategy_id": self.strategy_id,
            "strategy_revision": self.strategy_revision,
            "source_data_sha256": self.source_data_sha256,
            "config_sha256": self.config_sha256,
            "signal_bar_open_utc": _format_utc(self.signal_bar_open_utc),
            "signal_bar_close_utc": _format_utc(self.signal_bar_close_utc),
            "decision_not_before_utc": _format_utc(self.decision_not_before_utc),
            "expires_at_utc": _format_utc(self.expires_at_utc),
            "target_position": self.target_position,
            "minimum_position": self.minimum_position,
            "maximum_position": self.maximum_position,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "intent_id": self.intent_id}

    def to_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict()) + b"\n"

    def assert_active_at(self, value: datetime | str) -> None:
        """Fail closed when the intent is early or stale for execution translation."""

        observed_at = _required_utc_datetime(value, field_name="observed_at_utc")
        if observed_at < self.decision_not_before_utc:
            raise ValueError("target-position intent is not active yet")
        if observed_at >= self.expires_at_utc:
            raise ValueError("target-position intent has expired")

    @classmethod
    def from_mapping(cls, value: object) -> TargetPositionIntent:
        if not isinstance(value, Mapping):
            raise ValueError("target-position intent must be a mapping")
        keys = set(value)
        if keys != _SERIALIZED_KEYS:
            missing = sorted(_SERIALIZED_KEYS - keys)
            unexpected = sorted(repr(key) for key in keys - _SERIALIZED_KEYS)
            raise ValueError(
                "target-position intent fields do not match schema; "
                f"missing={missing}, unexpected={unexpected}"
            )
        schema_version = value["schema_version"]
        if (
            isinstance(schema_version, bool)
            or not isinstance(schema_version, int)
            or schema_version != _SCHEMA_VERSION
        ):
            raise ValueError(f"unsupported target-position intent schema {schema_version!r}")

        intent = cls(
            instrument_id=value["instrument_id"],
            bar=value["bar"],
            strategy_id=value["strategy_id"],
            strategy_revision=value["strategy_revision"],
            source_data_sha256=value["source_data_sha256"],
            config_sha256=value["config_sha256"],
            signal_bar_open_utc=value["signal_bar_open_utc"],
            signal_bar_close_utc=value["signal_bar_close_utc"],
            decision_not_before_utc=value["decision_not_before_utc"],
            expires_at_utc=value["expires_at_utc"],
            target_position=value["target_position"],
            minimum_position=value["minimum_position"],
            maximum_position=value["maximum_position"],
        )
        serialized_id = value["intent_id"]
        if not isinstance(serialized_id, str) or serialized_id != intent.intent_id:
            raise ValueError("target-position intent ID does not match its canonical payload")
        return intent

    @classmethod
    def from_json_bytes(cls, value: bytes | str) -> TargetPositionIntent:
        if isinstance(value, bytes):
            try:
                serialized = value.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError("target-position intent JSON is unreadable") from exc
        elif isinstance(value, str):
            serialized = value
        else:
            raise ValueError("target-position intent JSON is unreadable")

        try:
            payload = json.loads(serialized, object_pairs_hook=_reject_duplicate_fields)
        except ValueError as exc:
            raise ValueError("target-position intent JSON is unreadable") from exc

        intent = cls.from_mapping(payload)
        if serialized.encode("utf-8") != intent.to_json_bytes():
            raise ValueError("target-position intent JSON must use canonical encoding")
        return intent
