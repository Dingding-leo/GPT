from __future__ import annotations

import os
from pathlib import Path

import pytest

from gpt_quant._atomic_publish import publish_payloads_atomically


def test_atomic_publisher_rejects_invalid_contract_before_touching_filesystem(
    tmp_path: Path,
) -> None:
    output = tmp_path / "artifacts"
    shared_destination = output / "shared.json"

    with pytest.raises(ValueError, match="commit order must exactly match"):
        publish_payloads_atomically(
            output,
            {"json": output / "result.json", "markdown": output / "result.md"},
            {"json": b"{}\n", "markdown": b"# Result\n"},
            commit_order=("json", "json"),
            staging_prefix=".atomic-test-",
            error_label="test artifact",
        )
    assert not output.exists()

    with pytest.raises(ValueError, match="destination paths must be unique"):
        publish_payloads_atomically(
            output,
            {"json": shared_destination, "markdown": shared_destination},
            {"json": b"{}\n", "markdown": b"# Result\n"},
            commit_order=("json", "markdown"),
            staging_prefix=".atomic-test-",
            error_label="test artifact",
        )
    assert not output.exists()


def test_atomic_publisher_rolls_back_mixed_prior_state_in_reverse_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "artifacts"
    output.mkdir()
    paths = {
        "json": output / "result.json",
        "returns": output / "returns.csv",
        "markdown": output / "result.md",
    }
    paths["json"].write_bytes(b"old-json\n")
    paths["markdown"].write_bytes(b"old-markdown\n")
    original_files = {path.name: path.read_bytes() for path in output.iterdir()}

    real_replace = os.replace
    final_commits = 0
    rollback_destinations: list[str] = []

    def fail_third_commit(source: str | Path, destination: str | Path) -> None:
        nonlocal final_commits
        source_path = Path(source)
        destination_path = Path(destination)
        if destination_path.parent == output and not source_path.name.startswith("restore-"):
            final_commits += 1
            if final_commits == 3:
                raise OSError("simulated third commit failure")
        elif source_path.name.startswith("restore-"):
            rollback_destinations.append(destination_path.name)
        real_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_third_commit)

    with pytest.raises(OSError, match="simulated third commit failure"):
        publish_payloads_atomically(
            output,
            paths,
            {
                "json": b"new-json\n",
                "returns": b"new-returns\n",
                "markdown": b"new-markdown\n",
            },
            commit_order=("json", "returns", "markdown"),
            staging_prefix=".atomic-test-",
            error_label="test artifact",
        )

    assert final_commits == 3
    assert rollback_destinations == ["result.json"]
    assert {path.name: path.read_bytes() for path in output.iterdir()} == original_files
