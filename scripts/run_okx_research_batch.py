#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

_INSTRUMENT_PATTERN = re.compile(r"[A-Z0-9]+(?:-[A-Z0-9]+)+")
_DEFAULT_INSTRUMENTS = ("BTC-USDT", "ETH-USDT")
_POLL_SECONDS = 0.01


@dataclass(frozen=True, slots=True)
class _Job:
    instrument_id: str
    command: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _CompletedJob:
    instrument_id: str
    stdout: str
    stderr: str


@dataclass(frozen=True, slots=True)
class _BatchProcessMetrics:
    elapsed_seconds: float
    peak_child_rss_bytes: int | None


def _instrument_id(value: str) -> str:
    if _INSTRUMENT_PATTERN.fullmatch(value) is None:
        raise argparse.ArgumentTypeError(
            "instrument IDs must be uppercase dash-separated alphanumeric tokens"
        )
    return value


def _resident_bytes(pid: int) -> int | None:
    try:
        status = Path(f"/proc/{pid}/status").read_text(encoding="utf-8")
    except OSError:
        return None
    for line in status.splitlines():
        if line.startswith("VmRSS:"):
            fields = line.split()
            if len(fields) == 3 and fields[2] == "kB" and fields[1].isdigit():
                return int(fields[1]) * 1024
            return None
    return None


def _terminate(processes: Sequence[subprocess.Popen[str]]) -> None:
    for process in processes:
        if process.poll() is None:
            process.terminate()
    deadline = time.monotonic() + 5.0
    for process in processes:
        if process.poll() is None:
            try:
                process.wait(timeout=max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                process.kill()
    for process in processes:
        if process.poll() is None:
            process.wait()


def _run_processes(
    jobs: Sequence[_Job],
    *,
    max_workers: int,
) -> tuple[dict[str, _CompletedJob], _BatchProcessMetrics]:
    if max_workers < 1:
        raise ValueError("max_workers must be positive")
    if not jobs:
        raise ValueError("at least one research job is required")

    pending = deque(jobs)
    active: dict[subprocess.Popen[str], _Job] = {}
    completed: dict[str, _CompletedJob] = {}
    peak_child_rss_bytes: int | None = 0 if Path("/proc").is_dir() else None
    started = time.perf_counter()
    try:
        while pending or active:
            while pending and len(active) < max_workers:
                job = pending.popleft()
                process = subprocess.Popen(  # noqa: S603
                    job.command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                )
                active[process] = job

            if peak_child_rss_bytes is not None:
                resident_values = [
                    value
                    for process in active
                    if process.poll() is None
                    for value in (_resident_bytes(process.pid),)
                    if value is not None
                ]
                if resident_values:
                    peak_child_rss_bytes = max(
                        peak_child_rss_bytes,
                        sum(resident_values),
                    )

            finished = [process for process in active if process.poll() is not None]
            if not finished:
                time.sleep(_POLL_SECONDS)
                continue
            for process in finished:
                job = active.pop(process)
                stdout, stderr = process.communicate()
                if process.returncode != 0:
                    _terminate(tuple(active))
                    detail = stderr.strip() or stdout.strip() or "no child output"
                    raise RuntimeError(
                        f"OKX research failed for {job.instrument_id} "
                        f"with exit code {process.returncode}: {detail}"
                    )
                completed[job.instrument_id] = _CompletedJob(
                    instrument_id=job.instrument_id,
                    stdout=stdout,
                    stderr=stderr,
                )
    except BaseException:
        _terminate(tuple(active))
        raise

    return completed, _BatchProcessMetrics(
        elapsed_seconds=time.perf_counter() - started,
        peak_child_rss_bytes=peak_child_rss_bytes,
    )


def _manifest_line(path: Path, instrument_id: str) -> bytes:
    lines = path.read_bytes().splitlines()
    if len(lines) != 1 or not lines[0]:
        raise ValueError(f"{instrument_id} child manifest must contain exactly one record")
    try:
        record = json.loads(lines[0])
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{instrument_id} child manifest is unreadable") from exc
    if not isinstance(record, dict) or record.get("instrument_id") != instrument_id:
        raise ValueError(f"{instrument_id} child manifest instrument does not match")
    return lines[0] + b"\n"


def _publish_manifest(
    child_manifests: Sequence[tuple[str, Path]],
    destination: Path,
) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload_parts: list[bytes] = []
    run_ids: set[str] = set()
    for instrument_id, path in child_manifests:
        line = _manifest_line(path, instrument_id)
        record = json.loads(line)
        run_id = record.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            raise ValueError(f"{instrument_id} child manifest is missing run_id")
        if run_id in run_ids:
            raise ValueError(f"duplicate child manifest run_id {run_id!r}")
        run_ids.add(run_id)
        payload_parts.append(line)
    payload = b"".join(payload_parts)

    with TemporaryDirectory(prefix=".okx-batch-manifest-", dir=destination.parent) as name:
        staged = Path(name) / destination.name
        descriptor = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb", closefd=True) as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            with contextlib.suppress(OSError):
                os.close(descriptor)
            raise
        os.replace(staged, destination)
        directory_descriptor = os.open(
            destination.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    return hashlib.sha256(payload).hexdigest()


def _build_command(
    *,
    runner: Path,
    instrument_id: str,
    output_dir: Path,
    manifest_path: Path,
    config: str,
    bar: str | None,
    base_url: str | None,
    start: str | None,
    end: str | None,
    max_pages: int | None,
) -> tuple[str, ...]:
    command = [
        sys.executable,
        str(runner),
        "--config",
        config,
        "--inst-id",
        instrument_id,
        "--output-dir",
        str(output_dir),
        "--manifest-path",
        str(manifest_path),
    ]
    for option, value in (
        ("--bar", bar),
        ("--base-url", base_url),
        ("--start", start),
        ("--end", end),
        ("--max-pages", max_pages),
    ):
        if value is not None:
            command.extend((option, str(value)))
    return tuple(command)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run independent public-OKX research jobs concurrently and merge provenance."
    )
    parser.add_argument("--inst-id", action="append", type=_instrument_id, dest="instruments")
    parser.add_argument("--config", default="config/okx_research.json")
    parser.add_argument("--bar")
    parser.add_argument("--base-url")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--max-pages", type=int)
    parser.add_argument("--output-root", default="reports/okx")
    parser.add_argument("--manifest-path", default="reports/okx/experiment-manifest.jsonl")
    parser.add_argument("--max-workers", type=int, default=2)
    parser.add_argument("--runner", type=Path, default=Path("scripts/run_okx_research.py"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    instruments = tuple(args.instruments or _DEFAULT_INSTRUMENTS)
    if len(set(instruments)) != len(instruments):
        raise ValueError("instrument IDs must be unique")
    if args.max_workers < 1:
        raise ValueError("max-workers must be positive")
    if not args.runner.is_file():
        raise ValueError(f"research runner does not exist: {args.runner}")

    output_root = Path(args.output_root)
    destination_manifest = Path(args.manifest_path)
    output_root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".okx-batch-manifests-", dir=output_root) as name:
        manifest_root = Path(name)
        jobs = tuple(
            _Job(
                instrument_id=instrument_id,
                command=_build_command(
                    runner=args.runner,
                    instrument_id=instrument_id,
                    output_dir=output_root / instrument_id,
                    manifest_path=manifest_root / f"{instrument_id}.jsonl",
                    config=args.config,
                    bar=args.bar,
                    base_url=args.base_url,
                    start=args.start,
                    end=args.end,
                    max_pages=args.max_pages,
                ),
            )
            for instrument_id in instruments
        )
        completed, metrics = _run_processes(
            jobs,
            max_workers=min(args.max_workers, len(jobs)),
        )
        manifest_sha256 = _publish_manifest(
            tuple(
                (instrument_id, manifest_root / f"{instrument_id}.jsonl")
                for instrument_id in instruments
            ),
            destination_manifest,
        )

    for instrument_id in instruments:
        output = completed[instrument_id].stdout
        if output:
            print(output, end="" if output.endswith("\n") else "\n")
    print(f"batch_instruments={','.join(instruments)}")
    print(f"batch_elapsed_seconds={metrics.elapsed_seconds:.6f}")
    if metrics.peak_child_rss_bytes is not None:
        print(f"batch_peak_child_rss_bytes={metrics.peak_child_rss_bytes}")
    print(f"manifest_path={destination_manifest}")
    print(f"manifest_sha256={manifest_sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
