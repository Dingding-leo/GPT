from __future__ import annotations

import os
from pathlib import Path

import pytest

from gpt_quant._atomic_publish import (
    publish_payloads_atomically,
    publish_staged_paths_atomically,
)


def test_atomic_publisher_rejects_hardlinked_destination_before_staging(tmp_path: Path) -> None:
    output = tmp_path / "artifacts"
    output.mkdir()
    external_json = tmp_path / "operator-result.json"
    external_json.write_bytes(b"operator-owned\n")
    json_destination = output / "result.json"
    os.link(external_json, json_destination)
    markdown_destination = output / "result.md"
    markdown_destination.write_bytes(b"old-markdown\n")

    with pytest.raises(ValueError, match="destinations must not be hard-linked files"):
        publish_payloads_atomically(
            output,
            {"json": json_destination, "markdown": markdown_destination},
            {"json": b"new-json\n", "markdown": b"new-markdown\n"},
            commit_order=("json", "markdown"),
            staging_prefix=".atomic-test-",
            error_label="test artifact",
        )

    assert json_destination.samefile(external_json)
    assert json_destination.read_bytes() == b"operator-owned\n"
    assert external_json.read_bytes() == b"operator-owned\n"
    assert json_destination.stat().st_nlink == 2
    assert markdown_destination.read_bytes() == b"old-markdown\n"
    assert {path.name for path in output.iterdir()} == {"result.json", "result.md"}


def test_atomic_publisher_rejects_hardlinked_staged_file_before_commit(tmp_path: Path) -> None:
    output = tmp_path / "artifacts"
    external_json = tmp_path / "operator-result.json"
    external_json.write_bytes(b"operator-owned\n")
    destinations = {
        "json": output / "result.json",
        "markdown": output / "result.md",
    }

    def stage_paths(staging: Path) -> dict[str, Path]:
        staged_json = staging / "result.json"
        os.link(external_json, staged_json)
        staged_markdown = staging / "result.md"
        staged_markdown.write_bytes(b"new-markdown\n")
        return {"json": staged_json, "markdown": staged_markdown}

    with pytest.raises(ValueError, match="staged paths must not be hard-linked files"):
        publish_staged_paths_atomically(
            output,
            destinations,
            stage_paths=stage_paths,
            commit_order=("json", "markdown"),
            staging_prefix=".atomic-test-",
            error_label="test artifact",
        )

    assert not output.exists()
    assert external_json.read_bytes() == b"operator-owned\n"
    assert external_json.stat().st_nlink == 1
    assert all(not destination.exists() for destination in destinations.values())
