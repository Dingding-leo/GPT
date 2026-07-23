from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import stat
from collections.abc import Iterator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from secrets import token_hex

try:
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - paper/live state is POSIX-only for now
    _fcntl = None

from .execution_quote import ExecutionQuoteSnapshot

_ERROR_LABEL = "execution quote evidence store"
_LOCK_NAME = ".execution-quote-evidence.lock"
_JSON_NAME = re.compile(r"([0-9a-f]{64})\.json")
_STAGE_NAME = re.compile(r"\.execution-quote-[0-9]+-[0-9a-f]{16}\.tmp")
_EVIDENCE_SCHEMA_VERSION = 1
_EVIDENCE_KEYS = {
    "schema_version",
    "snapshot",
    "source_response_base64",
    "instrument_snapshot_base64",
}


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
            raise ValueError(f"execution quote evidence JSON contains duplicate field {key!r}")
        result[key] = value
    return result


def _required_artifact_bytes(value: object, *, field_name: str) -> bytes:
    if not isinstance(value, bytes) or not value:
        raise ValueError(f"{field_name} must be non-empty immutable bytes")
    return value


@dataclass(frozen=True, slots=True)
class ExecutionQuoteEvidence:
    """One quote plus the exact public bytes needed to reconstruct its provenance."""

    snapshot: ExecutionQuoteSnapshot
    source_response_bytes: bytes
    instrument_snapshot_bytes: bytes
    schema_version: int = _EVIDENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, ExecutionQuoteSnapshot):
            raise TypeError("snapshot must be an ExecutionQuoteSnapshot")
        if self.schema_version != _EVIDENCE_SCHEMA_VERSION:
            raise ValueError(f"unsupported execution quote evidence schema {self.schema_version!r}")
        for field_name in ("source_response_bytes", "instrument_snapshot_bytes"):
            object.__setattr__(
                self,
                field_name,
                _required_artifact_bytes(getattr(self, field_name), field_name=field_name),
            )
        if (
            hashlib.sha256(self.source_response_bytes).hexdigest()
            != self.snapshot.source_response_sha256
        ):
            raise ValueError("source response bytes do not match execution quote hash")
        if (
            hashlib.sha256(self.instrument_snapshot_bytes).hexdigest()
            != self.snapshot.instrument_snapshot_sha256
        ):
            raise ValueError("instrument snapshot bytes do not match execution quote hash")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "snapshot": self.snapshot.to_dict(),
            "source_response_base64": base64.b64encode(self.source_response_bytes).decode("ascii"),
            "instrument_snapshot_base64": base64.b64encode(self.instrument_snapshot_bytes).decode(
                "ascii"
            ),
        }

    def to_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict()) + b"\n"

    @classmethod
    def from_json_bytes(cls, value: bytes | str) -> ExecutionQuoteEvidence:
        if isinstance(value, bytes):
            try:
                serialized = value.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError("execution quote evidence JSON is unreadable") from exc
        elif isinstance(value, str):
            serialized = value
        else:
            raise ValueError("execution quote evidence JSON is unreadable")
        try:
            payload = json.loads(serialized, object_pairs_hook=_reject_duplicate_fields)
        except json.JSONDecodeError as exc:
            raise ValueError("execution quote evidence JSON is unreadable") from exc
        if not isinstance(payload, Mapping) or set(payload) != _EVIDENCE_KEYS:
            raise ValueError("execution quote evidence fields do not match schema")
        if payload["schema_version"] != _EVIDENCE_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported execution quote evidence schema {payload['schema_version']!r}"
            )
        try:
            source_response_bytes = base64.b64decode(
                payload["source_response_base64"], validate=True
            )
            instrument_snapshot_bytes = base64.b64decode(
                payload["instrument_snapshot_base64"], validate=True
            )
        except (binascii.Error, TypeError, ValueError) as exc:
            raise ValueError("execution quote evidence contains invalid base64") from exc
        record = cls(
            snapshot=ExecutionQuoteSnapshot.from_mapping(payload["snapshot"]),
            source_response_bytes=source_response_bytes,
            instrument_snapshot_bytes=instrument_snapshot_bytes,
        )
        if serialized.encode("utf-8") != record.to_json_bytes():
            raise ValueError("execution quote evidence JSON must use canonical encoding")
        return record


@dataclass(frozen=True, slots=True)
class ExecutionQuoteEvidenceStore:
    """Replay-verified immutable execution quotes and their deterministic root."""

    records: tuple[ExecutionQuoteEvidence, ...]
    sha256: str

    @property
    def snapshots(self) -> tuple[ExecutionQuoteSnapshot, ...]:
        return tuple(record.snapshot for record in self.records)

    @property
    def count(self) -> int:
        return len(self.records)

    def to_bytes(self) -> bytes:
        return b"".join(record.to_json_bytes() for record in self.records)


def _sort_key(record: ExecutionQuoteEvidence) -> tuple[object, ...]:
    snapshot = record.snapshot
    return (
        snapshot.received_at_utc,
        snapshot.observed_at_utc,
        snapshot.provider,
        snapshot.instrument_id,
        snapshot.snapshot_id,
    )


def _store_from_records(
    records: tuple[ExecutionQuoteEvidence, ...],
) -> ExecutionQuoteEvidenceStore:
    ordered = tuple(sorted(records, key=_sort_key))
    seen_ids: set[str] = set()
    for record in ordered:
        snapshot_id = record.snapshot.snapshot_id
        if snapshot_id in seen_ids:
            raise ValueError(f"{_ERROR_LABEL} contains duplicate snapshot ID {snapshot_id}")
        seen_ids.add(snapshot_id)
    payload = b"".join(record.to_json_bytes() for record in ordered)
    return ExecutionQuoteEvidenceStore(
        records=ordered,
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def _validate_directory_descriptor(descriptor: int) -> os.stat_result:
    directory_stat = os.fstat(descriptor)
    if not stat.S_ISDIR(directory_stat.st_mode):
        raise ValueError(f"{_ERROR_LABEL} path must be a directory")
    if hasattr(os, "geteuid") and directory_stat.st_uid != os.geteuid():
        raise ValueError(f"{_ERROR_LABEL} directory must be owned by the current user")
    if stat.S_IMODE(directory_stat.st_mode) != 0o700:
        raise ValueError(f"{_ERROR_LABEL} directory must use mode 0700")
    return directory_stat


def _open_private_directory(path: Path) -> tuple[int, os.stat_result]:
    if not path.name or path.name in {".", ".."}:
        raise ValueError(f"{_ERROR_LABEL} path must name one directory")
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    directory_only = getattr(os, "O_DIRECTORY", 0)
    parent_descriptor = os.open(path.parent, os.O_RDONLY | directory_only | no_follow)
    try:
        try:
            os.mkdir(path.name, 0o700, dir_fd=parent_descriptor)
        except FileExistsError:
            created = False
        else:
            created = True
        descriptor = os.open(
            path.name,
            os.O_RDONLY | directory_only | no_follow,
            dir_fd=parent_descriptor,
        )
        try:
            if created:
                os.fchmod(descriptor, 0o700)
            directory_stat = _validate_directory_descriptor(descriptor)
            path_stat = os.stat(
                path.name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            if (
                path_stat.st_dev != directory_stat.st_dev
                or path_stat.st_ino != directory_stat.st_ino
            ):
                raise RuntimeError(f"{_ERROR_LABEL} directory path changed while opening")
            if created:
                os.fsync(descriptor)
                os.fsync(parent_descriptor)
            return descriptor, directory_stat
        except BaseException:
            os.close(descriptor)
            raise
    finally:
        os.close(parent_descriptor)


def _validate_regular_private_file(descriptor: int, *, label: str) -> os.stat_result:
    file_stat = os.fstat(descriptor)
    if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_nlink != 1:
        raise ValueError(f"{label} must be a regular single-link file")
    if hasattr(os, "geteuid") and file_stat.st_uid != os.geteuid():
        raise ValueError(f"{label} must be owned by the current user")
    if stat.S_IMODE(file_stat.st_mode) != 0o600:
        raise ValueError(f"{label} must use mode 0600")
    return file_stat


def _read_snapshot_file(directory_descriptor: int, name: str) -> ExecutionQuoteEvidence:
    match = _JSON_NAME.fullmatch(name)
    if match is None:
        raise ValueError(f"{_ERROR_LABEL} contains unexpected entry {name!r}")
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    nonblock = getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(
        name,
        os.O_RDONLY | no_follow | nonblock,
        dir_fd=directory_descriptor,
    )
    try:
        file_stat = _validate_regular_private_file(
            descriptor,
            label=f"{_ERROR_LABEL} snapshot file",
        )
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after_stat = os.fstat(descriptor)
        path_stat = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
        if (
            after_stat.st_dev != file_stat.st_dev
            or after_stat.st_ino != file_stat.st_ino
            or after_stat.st_size != file_stat.st_size
            or path_stat.st_dev != file_stat.st_dev
            or path_stat.st_ino != file_stat.st_ino
        ):
            raise RuntimeError(f"{_ERROR_LABEL} snapshot changed during replay")
    finally:
        os.close(descriptor)
    record = ExecutionQuoteEvidence.from_json_bytes(b"".join(chunks))
    if record.snapshot.snapshot_id != match.group(1):
        raise ValueError(f"{_ERROR_LABEL} filename does not match canonical snapshot ID")
    return record


def _recover_stale_stages(directory_descriptor: int) -> None:
    recovered = False
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    nonblock = getattr(os, "O_NONBLOCK", 0)
    for name in sorted(os.listdir(directory_descriptor)):
        if _STAGE_NAME.fullmatch(name) is None:
            continue
        descriptor = os.open(
            name,
            os.O_RDONLY | no_follow | nonblock,
            dir_fd=directory_descriptor,
        )
        try:
            staged_stat = os.fstat(descriptor)
            if not stat.S_ISREG(staged_stat.st_mode) or staged_stat.st_nlink not in {1, 2}:
                raise ValueError(
                    f"{_ERROR_LABEL} staged snapshot must be a regular file with one or two links"
                )
            if hasattr(os, "geteuid") and staged_stat.st_uid != os.geteuid():
                raise ValueError(
                    f"{_ERROR_LABEL} staged snapshot must be owned by the current user"
                )
            if stat.S_IMODE(staged_stat.st_mode) != 0o600:
                raise ValueError(f"{_ERROR_LABEL} staged snapshot must use mode 0600")
            path_stat = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
            if path_stat.st_dev != staged_stat.st_dev or path_stat.st_ino != staged_stat.st_ino:
                raise RuntimeError(f"{_ERROR_LABEL} staged snapshot changed during recovery")
            if staged_stat.st_nlink == 2:
                chunks: list[bytes] = []
                while True:
                    chunk = os.read(descriptor, 1024 * 1024)
                    if not chunk:
                        break
                    chunks.append(chunk)
                after_stat = os.fstat(descriptor)
                if (
                    after_stat.st_dev != staged_stat.st_dev
                    or after_stat.st_ino != staged_stat.st_ino
                    or after_stat.st_size != staged_stat.st_size
                ):
                    raise RuntimeError(f"{_ERROR_LABEL} staged snapshot changed during recovery")
                record = ExecutionQuoteEvidence.from_json_bytes(b"".join(chunks))
                destination_name = f"{record.snapshot.snapshot_id}.json"
                try:
                    destination_stat = os.stat(
                        destination_name,
                        dir_fd=directory_descriptor,
                        follow_symlinks=False,
                    )
                except FileNotFoundError as exc:
                    raise ValueError(
                        f"{_ERROR_LABEL} published stage is missing its canonical destination"
                    ) from exc
                if (
                    destination_stat.st_dev != staged_stat.st_dev
                    or destination_stat.st_ino != staged_stat.st_ino
                ):
                    raise ValueError(
                        f"{_ERROR_LABEL} published stage does not link its canonical destination"
                    )
        finally:
            os.close(descriptor)
        os.unlink(name, dir_fd=directory_descriptor)
        recovered = True
    if recovered:
        os.fsync(directory_descriptor)


def _load_from_descriptor(directory_descriptor: int) -> ExecutionQuoteEvidenceStore:
    names = sorted(name for name in os.listdir(directory_descriptor) if name != _LOCK_NAME)
    records = tuple(_read_snapshot_file(directory_descriptor, name) for name in names)
    return _store_from_records(records)


@contextmanager
def _exclusive_store_lock(path: Path) -> Iterator[tuple[int, os.stat_result]]:
    if _fcntl is None:
        raise RuntimeError(f"{_ERROR_LABEL} requires POSIX advisory locking")
    directory_descriptor, directory_stat = _open_private_directory(path)
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(
        _LOCK_NAME,
        os.O_CREAT | os.O_RDWR | no_follow,
        0o600,
        dir_fd=directory_descriptor,
    )
    acquired = False
    lock_stat: os.stat_result | None = None
    try:
        os.fchmod(descriptor, 0o600)
        lock_stat = _validate_regular_private_file(
            descriptor,
            label=f"{_ERROR_LABEL} writer lock",
        )
        try:
            _fcntl.flock(descriptor, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"{_ERROR_LABEL} writer lock is already held") from exc
        acquired = True
        _recover_stale_stages(directory_descriptor)
        yield directory_descriptor, directory_stat
    finally:
        if acquired:
            current_stat = os.stat(
                _LOCK_NAME,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
            if lock_stat is None or (
                current_stat.st_dev != lock_stat.st_dev or current_stat.st_ino != lock_stat.st_ino
            ):
                raise RuntimeError(f"{_ERROR_LABEL} writer lock path changed during use")
            os.unlink(_LOCK_NAME, dir_fd=directory_descriptor)
            os.fsync(directory_descriptor)
            _fcntl.flock(descriptor, _fcntl.LOCK_UN)
        os.close(descriptor)
        current_directory_stat = os.stat(path, follow_symlinks=False)
        if (
            current_directory_stat.st_dev != directory_stat.st_dev
            or current_directory_stat.st_ino != directory_stat.st_ino
        ):
            os.close(directory_descriptor)
            raise RuntimeError(f"{_ERROR_LABEL} directory path changed during use")
        os.close(directory_descriptor)


def load_execution_quote_evidence_store(
    path: str | Path,
) -> ExecutionQuoteEvidenceStore:
    """Replay every persisted quote and return a deterministic content root."""

    store_path = Path(path)
    with _exclusive_store_lock(store_path) as (directory_descriptor, _):
        return _load_from_descriptor(directory_descriptor)


def record_execution_quote_evidence(
    path: str | Path,
    snapshot: ExecutionQuoteSnapshot,
    *,
    source_response_bytes: bytes,
    instrument_snapshot_bytes: bytes,
) -> ExecutionQuoteEvidenceStore:
    """Persist one quote and its exact source artifacts, then replay the store."""

    record = ExecutionQuoteEvidence(
        snapshot=snapshot,
        source_response_bytes=source_response_bytes,
        instrument_snapshot_bytes=instrument_snapshot_bytes,
    )
    store_path = Path(path)
    destination_name = f"{snapshot.snapshot_id}.json"
    payload = record.to_json_bytes()
    with _exclusive_store_lock(store_path) as (directory_descriptor, _):
        try:
            existing = _read_snapshot_file(directory_descriptor, destination_name)
        except FileNotFoundError:
            existing = None
        if existing is not None:
            if existing.to_json_bytes() != payload:
                raise ValueError(f"{_ERROR_LABEL} snapshot ID maps to conflicting evidence")
            return _load_from_descriptor(directory_descriptor)

        temporary_name = f".execution-quote-{os.getpid()}-{token_hex(8)}.tmp"
        no_follow = getattr(os, "O_NOFOLLOW", 0)
        temporary_descriptor = os.open(
            temporary_name,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | no_follow,
            0o600,
            dir_fd=directory_descriptor,
        )
        published = False
        try:
            os.fchmod(temporary_descriptor, 0o600)
            _validate_regular_private_file(
                temporary_descriptor,
                label=f"{_ERROR_LABEL} staged snapshot",
            )
            view = memoryview(payload)
            while view:
                written = os.write(temporary_descriptor, view)
                if written <= 0:
                    raise OSError("failed to write execution quote evidence")
                view = view[written:]
            os.fsync(temporary_descriptor)
            os.link(
                temporary_name,
                destination_name,
                src_dir_fd=directory_descriptor,
                dst_dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
            published = True
        finally:
            os.close(temporary_descriptor)
            with suppress(FileNotFoundError):
                os.unlink(temporary_name, dir_fd=directory_descriptor)
            os.fsync(directory_descriptor)

        if not published:
            raise RuntimeError(f"{_ERROR_LABEL} failed to publish snapshot")
        persisted = _read_snapshot_file(directory_descriptor, destination_name)
        if persisted.to_json_bytes() != payload:
            raise RuntimeError(f"{_ERROR_LABEL} replay differs after publication")
        return _load_from_descriptor(directory_descriptor)
