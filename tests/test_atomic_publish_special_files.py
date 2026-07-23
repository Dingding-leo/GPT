from __future__ import annotations

import os
from pathlib import Path

import pytest

from gpt_quant._atomic_publish import publish_payloads_atomically


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX FIFO support is required")
def test_atomic_publisher_rejects_fifo_destination_before_read_or_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "artifacts"
    output.mkdir()
    fifo_destination = output / "result.json"
    os.mkfifo(fifo_destination)
    markdown_destination = output / "result.md"
    markdown_destination.write_bytes(b"operator-owned\n")

    real_read_bytes = Path.read_bytes

    def reject_fifo_read(path: Path) -> bytes:
        if path == fifo_destination:
            raise AssertionError("special-file destinations must fail before payload reads")
        return real_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", reject_fifo_read)

    with pytest.raises(ValueError, match="destinations must be regular files"):
        publish_payloads_atomically(
            output,
            {"json": fifo_destination, "markdown": markdown_destination},
            {"json": b"new-json\n", "markdown": b"new-markdown\n"},
            commit_order=("json", "markdown"),
            staging_prefix=".atomic-test-",
            error_label="test artifact",
        )

    assert fifo_destination.exists()
    assert not fifo_destination.is_file()
    assert markdown_destination.read_bytes() == b"operator-owned\n"
    assert {path.name for path in output.iterdir()} == {"result.json", "result.md"}
