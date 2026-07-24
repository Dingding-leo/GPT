from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from gpt_quant.execution_quote import ExecutionQuoteSnapshot
from gpt_quant.execution_quote_evidence import record_execution_quote_evidence

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_DOCUMENTATION = _REPOSITORY_ROOT / "docs" / "SIGNAL_INTENT_TIMING.md"


def _quote() -> ExecutionQuoteSnapshot:
    return ExecutionQuoteSnapshot(
        provider="okx",
        instrument_id="BTC-USDT",
        observed_at_utc=datetime(2026, 7, 21, 12, 0, 0, 300_000, tzinfo=UTC),
        received_at_utc=datetime(2026, 7, 21, 12, 0, 0, 350_000, tzinfo=UTC),
        bid_price="66113.7",
        bid_quantity="0.5",
        ask_price="66113.9",
        ask_quantity="0.4",
        source_response_sha256=hashlib.sha256(
            b"offline-structural-top-of-book-example-v1\n"
        ).hexdigest(),
        instrument_snapshot_sha256=hashlib.sha256(
            b"offline-structural-instrument-example-v1\n"
        ).hexdigest(),
    )


def _run_verifier(
    store_path: Path,
    *,
    expected_sha256: str,
    expected_count: int,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [
            sys.executable,
            "examples/verify_execution_quote_store.py",
            "--store",
            str(store_path),
            "--expected-sha256",
            expected_sha256,
            "--expected-count",
            str(expected_count),
        ],
        cwd=_REPOSITORY_ROOT,
        check=False,
        capture_output=True,
    )


def test_documented_quote_store_verifier_replays_expected_root(tmp_path: Path) -> None:
    store_path = tmp_path / "execution-quotes"
    store = record_execution_quote_evidence(store_path, _quote())

    completed = _run_verifier(
        store_path,
        expected_sha256=store.sha256,
        expected_count=store.count,
    )

    assert completed.returncode == 0
    assert completed.stderr == b""
    assert json.loads(completed.stdout) == {
        "count": 1,
        "path": store_path.as_posix(),
        "sha256": store.sha256,
        "snapshot_ids": [store.snapshots[0].snapshot_id],
        "status": "verified",
    }


def test_quote_store_verifier_fails_closed_without_expected_identity(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing-store"
    missing = _run_verifier(
        missing_path,
        expected_sha256="0" * 64,
        expected_count=0,
    )
    assert missing.returncode != 0
    assert b"execution quote evidence store does not exist" in missing.stderr
    assert not missing_path.exists()

    store_path = tmp_path / "execution-quotes"
    store = record_execution_quote_evidence(store_path, _quote())

    wrong_count = _run_verifier(
        store_path,
        expected_sha256=store.sha256,
        expected_count=2,
    )
    assert wrong_count.returncode != 0
    assert b"execution quote evidence count mismatch" in wrong_count.stderr

    wrong_root = _run_verifier(
        store_path,
        expected_sha256="0" * 64,
        expected_count=store.count,
    )
    assert wrong_root.returncode != 0
    assert b"execution quote evidence SHA-256 mismatch" in wrong_root.stderr


def test_quote_store_verification_command_is_documented() -> None:
    documentation = _DOCUMENTATION.read_text(encoding="utf-8")

    assert "python examples/verify_execution_quote_store.py" in documentation
    assert "--expected-count 1" in documentation
    assert "4313206599c3d31c7cbd32015df3bd97275f532e20e2f3eb20c276fa22f0907d" in documentation
    assert "does not exist" in documentation
    assert "Do not delete or rename staged files manually" in documentation
