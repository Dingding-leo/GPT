from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

try:
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - non-POSIX only
    _fcntl = None

from .execution_intent import TargetPositionIntent
from .target_intent_journal import load_target_position_intent_journal

_SCHEMA_VERSION = 1
_SHA256 = re.compile(r"[0-9a-f]{64}")
_TOKEN = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
_DECIMAL = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")
_ERROR = "paper order decision"
_FIELDS = {
    "schema_version",
    "target_intent_id",
    "instrument_id",
    "decided_at_utc",
    "market_observed_at_utc",
    "outcome",
    "reason_code",
    "order_type",
    "side",
    "base_quantity",
    "instrument_snapshot_sha256",
    "market_snapshot_sha256",
    "portfolio_state_before_sha256",
    "risk_state_before_sha256",
    "exchange_fee_bps",
    "spread_bps",
    "slippage_bps",
    "market_impact_bps",
    "latency_ms",
}
_SERIALIZED_FIELDS = _FIELDS | {"decision_id"}


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"{name} must be a non-empty trimmed string")
    if any(ord(character) < 32 for character in value):
        raise ValueError(f"{name} must not contain control characters")
    return value


def _digest(value: object, name: str) -> str:
    parsed = _text(value, name)
    if _SHA256.fullmatch(parsed) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return parsed


def _token(value: object, name: str) -> str:
    parsed = _text(value, name)
    if _TOKEN.fullmatch(parsed) is None:
        raise ValueError(f"{name} must be a lowercase machine token")
    return parsed


def _utc(value: object, name: str) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{name} must be a timezone-aware timestamp") from exc
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise ValueError(f"{name} must be a timezone-aware timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware timestamp")
    return parsed.astimezone(UTC)


def _decimal(value: object, name: str) -> str:
    if not isinstance(value, str) or _DECIMAL.fullmatch(value) is None:
        raise ValueError(f"{name} must be a canonical non-negative ASCII decimal string")
    canonical = format(Decimal(value), "f")
    if "." in canonical:
        canonical = canonical.rstrip("0").rstrip(".")
    if (canonical or "0") != value:
        raise ValueError(f"{name} must use canonical decimal encoding")
    return value


def _format_utc(value: datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _json_bytes(payload: Mapping[str, object]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"{_ERROR} JSON contains duplicate field {key!r}")
        result[key] = value
    return result


@dataclass(frozen=True, slots=True)
class PaperOrderDecision:
    """Immutable pre-trade paper decision; not an exchange order or fill."""

    target_intent_id: str
    instrument_id: str
    decided_at_utc: datetime
    market_observed_at_utc: datetime
    outcome: Literal["planned", "rejected"]
    reason_code: str
    order_type: Literal["market", "none"]
    side: Literal["buy", "sell", "none"]
    base_quantity: str
    instrument_snapshot_sha256: str
    market_snapshot_sha256: str
    portfolio_state_before_sha256: str
    risk_state_before_sha256: str
    exchange_fee_bps: str
    spread_bps: str
    slippage_bps: str
    market_impact_bps: str
    latency_ms: int
    schema_version: int = field(default=_SCHEMA_VERSION, init=False)
    decision_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "target_intent_id", _digest(self.target_intent_id, "target_intent_id")
        )
        object.__setattr__(self, "instrument_id", _text(self.instrument_id, "instrument_id"))
        object.__setattr__(self, "decided_at_utc", _utc(self.decided_at_utc, "decided_at_utc"))
        object.__setattr__(
            self,
            "market_observed_at_utc",
            _utc(self.market_observed_at_utc, "market_observed_at_utc"),
        )
        if self.market_observed_at_utc > self.decided_at_utc:
            raise ValueError("market observation cannot be after the decision")

        outcome = _token(self.outcome, "outcome")
        order_type = _token(self.order_type, "order_type")
        side = _token(self.side, "side")
        object.__setattr__(self, "reason_code", _token(self.reason_code, "reason_code"))
        if outcome not in {"planned", "rejected"}:
            raise ValueError("outcome must be planned or rejected")
        if order_type not in {"market", "none"} or side not in {"buy", "sell", "none"}:
            raise ValueError("invalid paper order type or side")
        object.__setattr__(self, "outcome", outcome)
        object.__setattr__(self, "order_type", order_type)
        object.__setattr__(self, "side", side)

        quantity = _decimal(self.base_quantity, "base_quantity")
        if outcome == "planned":
            if order_type != "market" or side not in {"buy", "sell"} or Decimal(quantity) <= 0:
                raise ValueError("planned decisions require a positive market buy/sell quantity")
        elif (order_type, side, quantity) != ("none", "none", "0"):
            raise ValueError("rejected decisions require zero quantity and no order fields")
        object.__setattr__(self, "base_quantity", quantity)

        for name in (
            "instrument_snapshot_sha256",
            "market_snapshot_sha256",
            "portfolio_state_before_sha256",
            "risk_state_before_sha256",
        ):
            object.__setattr__(self, name, _digest(getattr(self, name), name))
        for name in (
            "exchange_fee_bps",
            "spread_bps",
            "slippage_bps",
            "market_impact_bps",
        ):
            object.__setattr__(self, name, _decimal(getattr(self, name), name))
        if isinstance(self.latency_ms, bool) or not isinstance(self.latency_ms, int):
            raise ValueError("latency_ms must be a non-negative integer")
        if self.latency_ms < 0:
            raise ValueError("latency_ms must be a non-negative integer")
        object.__setattr__(
            self, "decision_id", hashlib.sha256(_json_bytes(self._payload())).hexdigest()
        )

    def _payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "target_intent_id": self.target_intent_id,
            "instrument_id": self.instrument_id,
            "decided_at_utc": _format_utc(self.decided_at_utc),
            "market_observed_at_utc": _format_utc(self.market_observed_at_utc),
            "outcome": self.outcome,
            "reason_code": self.reason_code,
            "order_type": self.order_type,
            "side": self.side,
            "base_quantity": self.base_quantity,
            "instrument_snapshot_sha256": self.instrument_snapshot_sha256,
            "market_snapshot_sha256": self.market_snapshot_sha256,
            "portfolio_state_before_sha256": self.portfolio_state_before_sha256,
            "risk_state_before_sha256": self.risk_state_before_sha256,
            "exchange_fee_bps": self.exchange_fee_bps,
            "spread_bps": self.spread_bps,
            "slippage_bps": self.slippage_bps,
            "market_impact_bps": self.market_impact_bps,
            "latency_ms": self.latency_ms,
        }

    def to_json_bytes(self) -> bytes:
        return _json_bytes({**self._payload(), "decision_id": self.decision_id}) + b"\n"

    @classmethod
    def from_json_bytes(cls, value: bytes) -> PaperOrderDecision:
        try:
            serialized = value.decode("utf-8")
            payload = json.loads(serialized, object_pairs_hook=_reject_duplicates)
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValueError(f"{_ERROR} JSON is unreadable") from exc
        if not isinstance(payload, Mapping) or set(payload) != _SERIALIZED_FIELDS:
            raise ValueError(f"{_ERROR} fields do not match schema")
        if payload["schema_version"] != _SCHEMA_VERSION:
            raise ValueError(f"unsupported {_ERROR} schema")
        decision = cls(**{name: payload[name] for name in _FIELDS - {"schema_version"}})
        if payload["decision_id"] != decision.decision_id:
            raise ValueError(f"{_ERROR} ID does not match its payload")
        if decision.to_json_bytes() != value:
            raise ValueError(f"{_ERROR} JSON must use canonical encoding")
        return decision


@dataclass(frozen=True, slots=True)
class PaperDecisionStoreReplay:
    """Deterministic replay inventory bound to the canonical target journal."""

    decisions: tuple[PaperOrderDecision, ...]
    pending_target_intents: tuple[TargetPositionIntent, ...]
    target_journal_sha256: str
    store_sha256: str


def _validate_private_file(descriptor: int, label: str) -> os.stat_result:
    file_stat = os.fstat(descriptor)
    if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_nlink != 1:
        raise ValueError(f"{label} must be a regular single-link file")
    if hasattr(os, "geteuid") and file_stat.st_uid != os.geteuid():
        raise ValueError(f"{label} must be owned by the current user")
    if stat.S_IMODE(file_stat.st_mode) != 0o600:
        raise ValueError(f"{label} must use owner-only 0600 permissions")
    return file_stat




def _validate_private_directory(descriptor: int) -> os.stat_result:
    directory_stat = os.fstat(descriptor)
    if not stat.S_ISDIR(directory_stat.st_mode):
        raise ValueError("paper decision directory must be a regular directory")
    if hasattr(os, "geteuid") and directory_stat.st_uid != os.geteuid():
        raise ValueError("paper decision directory must be owned by the current user")
    if stat.S_IMODE(directory_stat.st_mode) & 0o022:
        raise ValueError("paper decision directory must not be group/world writable")
    return directory_stat


def _assert_directory_identity(directory: Path, opened: os.stat_result) -> None:
    current = os.stat(directory, follow_symlinks=False)
    if not stat.S_ISDIR(current.st_mode) or (opened.st_dev, opened.st_ino) != (
        current.st_dev,
        current.st_ino,
    ):
        raise RuntimeError("paper decision directory changed during operation")


@contextmanager
def _private_decision_directory(
    directory: Path,
    *,
    create: bool,
) -> Iterator[tuple[int, os.stat_result] | None]:
    if create:
        if directory.is_symlink():
            raise ValueError("paper decision directory must not be a symbolic link")
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    elif not directory.exists():
        yield None
        return

    descriptor = os.open(
        directory,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        opened = _validate_private_directory(descriptor)
        _assert_directory_identity(directory, opened)
        yield descriptor, opened
        _assert_directory_identity(directory, opened)
    finally:
        os.close(descriptor)


def load_paper_order_decision(path: str | Path) -> PaperOrderDecision:
    decision_path = Path(path)
    descriptor = os.open(
        decision_path,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
    )
    try:
        opened = _validate_private_file(descriptor, _ERROR)
        payload = b""
        while chunk := os.read(descriptor, 1024 * 1024):
            payload += chunk
        current = os.stat(decision_path, follow_symlinks=False)
        if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            raise RuntimeError(f"{_ERROR} path changed during replay")
        return PaperOrderDecision.from_json_bytes(payload)
    finally:
        os.close(descriptor)


@contextmanager
def _decision_lock(path: Path) -> Iterator[None]:
    lock_path = path.with_name(f".{path.name}.lock")
    descriptor = os.open(
        lock_path,
        os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    acquired = False
    lock_stat: os.stat_result | None = None
    try:
        os.fchmod(descriptor, 0o600)
        lock_stat = _validate_private_file(descriptor, f"{_ERROR} lock")
        if _fcntl is None:
            raise RuntimeError("paper decision locking requires POSIX advisory locks")
        try:
            _fcntl.flock(descriptor, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"{_ERROR} lock is held") from exc
        acquired = True
        yield
    finally:
        if acquired:
            current = os.stat(lock_path, follow_symlinks=False)
            if lock_stat is None or (current.st_dev, current.st_ino) != (
                lock_stat.st_dev,
                lock_stat.st_ino,
            ):
                raise RuntimeError(f"{_ERROR} lock path changed")
            lock_path.unlink()
            _fcntl.flock(descriptor, _fcntl.LOCK_UN)
        os.close(descriptor)


def _validate_decision_target(
    target: TargetPositionIntent,
    decision: PaperOrderDecision,
) -> None:
    if target.intent_id != decision.target_intent_id:
        raise ValueError(f"{_ERROR} references an unknown target intent")
    if target.instrument_id != decision.instrument_id:
        raise ValueError(f"{_ERROR} instrument does not match target intent")
    if decision.decided_at_utc < target.decision_not_before_utc:
        raise ValueError(f"{_ERROR} cannot precede target activation")
    if decision.outcome == "planned":
        target.assert_active_at(decision.decided_at_utc)
        if decision.market_observed_at_utc < target.decision_not_before_utc:
            raise ValueError("planned paper decision requires a post-activation market snapshot")


def _find_target(path: str | Path, decision: PaperOrderDecision) -> TargetPositionIntent:
    intents = load_target_position_intent_journal(path).intents
    target = next((item for item in intents if item.intent_id == decision.target_intent_id), None)
    if target is None:
        raise ValueError(f"{_ERROR} references an unknown target intent")
    _validate_decision_target(target, decision)
    return target


def _fsync_directory(
    directory: Path,
    descriptor: int,
    opened: os.stat_result,
) -> None:
    _assert_directory_identity(directory, opened)
    os.fsync(descriptor)
    _assert_directory_identity(directory, opened)


def record_paper_order_decision(
    target_journal_path: str | Path,
    decision_directory: str | Path,
    decision: PaperOrderDecision,
) -> PaperOrderDecision:
    """Atomically consume one target intent into one durable paper decision file."""

    if not isinstance(decision, PaperOrderDecision):
        raise TypeError("decision must be a PaperOrderDecision")
    directory = Path(decision_directory)
    with _private_decision_directory(directory, create=True) as directory_state:
        if directory_state is None:  # pragma: no cover - create=True always opens the directory
            raise RuntimeError("paper decision directory was not created")
        directory_descriptor, opened_directory = directory_state
        path = directory / f"{decision.target_intent_id}.json"
        with _decision_lock(path):
            _find_target(target_journal_path, decision)
            if path.exists():
                existing = load_paper_order_decision(path)
                if existing.to_json_bytes() != decision.to_json_bytes():
                    raise ValueError(f"{_ERROR} conflicts with the consumed target intent")
                return existing

            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".paper-decision-",
                dir=directory,
            )
            temporary = Path(temporary_name)
            try:
                os.fchmod(descriptor, 0o600)
                payload = decision.to_json_bytes()
                written = 0
                while written < len(payload):
                    written += os.write(descriptor, payload[written:])
                os.fsync(descriptor)
                os.close(descriptor)
                descriptor = -1
                _assert_directory_identity(directory, opened_directory)
                os.replace(temporary, path)
                _fsync_directory(directory, directory_descriptor, opened_directory)
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
                temporary.unlink(missing_ok=True)
            replayed = load_paper_order_decision(path)
            if replayed != decision:
                raise RuntimeError(f"{_ERROR} replay differs after publication")
            return replayed


def replay_paper_order_decision_store(
    target_journal_path: str | Path,
    decision_directory: str | Path,
) -> PaperDecisionStoreReplay:
    """Replay every durable decision in target-journal order and hash the result."""

    targets = load_target_position_intent_journal(target_journal_path).intents
    target_by_id = {target.intent_id: target for target in targets}
    decisions_by_target: dict[str, PaperOrderDecision] = {}
    directory = Path(decision_directory)
    with _private_decision_directory(directory, create=False) as directory_state:
        if directory_state is not None:
            for path in sorted(directory.glob("*.json")):
                decision = load_paper_order_decision(path)
                target = target_by_id.get(decision.target_intent_id)
                if target is None or path.name != f"{decision.target_intent_id}.json":
                    raise ValueError(f"{_ERROR} store references an unknown target intent")
                if decision.target_intent_id in decisions_by_target:
                    raise ValueError(f"{_ERROR} store contains a duplicate target decision")
                _validate_decision_target(target, decision)
                decisions_by_target[decision.target_intent_id] = decision

    decisions = tuple(
        decisions_by_target[target.intent_id]
        for target in targets
        if target.intent_id in decisions_by_target
    )
    pending = tuple(target for target in targets if target.intent_id not in decisions_by_target)
    target_journal_sha256 = hashlib.sha256(
        b"".join(target.to_json_bytes() for target in targets)
    ).hexdigest()
    replay_evidence = {
        "schema_version": 1,
        "target_journal_sha256": target_journal_sha256,
        "decision_ids": [decision.decision_id for decision in decisions],
        "pending_target_intent_ids": [target.intent_id for target in pending],
    }
    store_sha256 = hashlib.sha256(_json_bytes(replay_evidence)).hexdigest()
    return PaperDecisionStoreReplay(
        decisions=decisions,
        pending_target_intents=pending,
        target_journal_sha256=target_journal_sha256,
        store_sha256=store_sha256,
    )


def pending_target_position_intents(
    target_journal_path: str | Path,
    decision_directory: str | Path,
) -> tuple[TargetPositionIntent, ...]:
    """Return target intents without a replay-validated durable paper decision file."""

    return replay_paper_order_decision_store(
        target_journal_path,
        decision_directory,
    ).pending_target_intents
