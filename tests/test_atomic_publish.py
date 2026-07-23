from __future__ import annotations

import os
from pathlib import Path

import pytest

from gpt_quant._atomic_publish import (
    publish_payloads_atomically,
    publish_staged_paths_atomically,
)


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


def test_atomic_publisher_rejects_symlink_destination_before_staging(tmp_path: Path) -> None:
    output = tmp_path / "artifacts"
    output.mkdir()
    external_json = tmp_path / "operator-result.json"
    external_json.write_bytes(b"operator-owned\n")
    json_destination = output / "result.json"
    json_destination.symlink_to(external_json)
    markdown_destination = output / "result.md"
    markdown_destination.write_bytes(b"old-markdown\n")

    with pytest.raises(ValueError, match="destinations must not be symbolic links"):
        publish_payloads_atomically(
            output,
            {"json": json_destination, "markdown": markdown_destination},
            {"json": b"new-json\n", "markdown": b"new-markdown\n"},
            commit_order=("json", "markdown"),
            staging_prefix=".atomic-test-",
            error_label="test artifact",
        )

    assert json_destination.is_symlink()
    assert json_destination.read_bytes() == b"operator-owned\n"
    assert external_json.read_bytes() == b"operator-owned\n"
    assert markdown_destination.read_bytes() == b"old-markdown\n"
    assert {path.name for path in output.iterdir()} == {"result.json", "result.md"}


@pytest.mark.parametrize(
    ("case", "expected_error"),
    (
        ("outside", "staged paths must be direct children of the staging directory"),
        ("duplicate", "staged paths must be unique"),
        ("missing", "staged paths must be regular files"),
        ("directory", "staged paths must be regular files"),
        ("symlink", "staged paths must be regular files"),
    ),
)
def test_atomic_publisher_rejects_invalid_staged_paths_before_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    expected_error: str,
) -> None:
    output = tmp_path / "artifacts"
    outside_source = tmp_path / "operator-notes.txt"
    outside_source.write_bytes(b"caller-owned\n")
    paths = {"json": output / "result.json", "markdown": output / "result.md"}

    def stage_invalid_paths(staging: Path) -> dict[str, Path]:
        first_staged_path = staging / "first.tmp"
        second_staged_path = staging / "second.tmp"
        first_staged_path.write_bytes(b"first\n")
        second_staged_path.write_bytes(b"second\n")
        if case == "outside":
            return {"json": outside_source, "markdown": second_staged_path}
        if case == "duplicate":
            return {"json": first_staged_path, "markdown": first_staged_path}
        if case == "missing":
            return {"json": staging / "missing.tmp", "markdown": second_staged_path}
        if case == "directory":
            directory_source = staging / "directory.tmp"
            directory_source.mkdir()
            return {"json": directory_source, "markdown": second_staged_path}
        symlink_source = staging / "symlink.tmp"
        symlink_source.symlink_to(outside_source)
        return {"json": symlink_source, "markdown": second_staged_path}

    def unexpected_replace(_source: str | Path, _destination: str | Path) -> None:
        raise AssertionError("invalid staged paths must fail before destination replacement")

    monkeypatch.setattr(os, "replace", unexpected_replace)

    with pytest.raises(ValueError, match=expected_error):
        publish_staged_paths_atomically(
            output,
            paths,
            stage_paths=stage_invalid_paths,
            commit_order=("json", "markdown"),
            staging_prefix=".atomic-test-",
            error_label="test artifact",
        )

    assert outside_source.read_bytes() == b"caller-owned\n"
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
