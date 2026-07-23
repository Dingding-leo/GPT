from pathlib import Path

import pytest

from gpt_quant import live_readiness


def test_cli_requires_explicit_tested_revision_even_in_report_only_mode(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "live-readiness"

    with pytest.raises(SystemExit) as exc_info:
        live_readiness.main(
            [
                "--repo-root",
                str(tmp_path),
                "--head-sha",
                "a" * 40,
                "--ci-status-json",
                "{}",
                "--output-dir",
                str(output_dir),
                "--report-only",
            ]
        )

    assert exc_info.value.code == 2
    assert not output_dir.exists()


def test_cli_requires_explicit_ci_outcomes_even_in_report_only_mode(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "live-readiness"

    with pytest.raises(SystemExit) as exc_info:
        live_readiness.main(
            [
                "--repo-root",
                str(tmp_path),
                "--head-sha",
                "a" * 40,
                "--tested-sha",
                "a" * 40,
                "--output-dir",
                str(output_dir),
                "--report-only",
            ]
        )

    assert exc_info.value.code == 2
    assert not output_dir.exists()
