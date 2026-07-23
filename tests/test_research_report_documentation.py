from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_POLICY_PATH = _REPOSITORY_ROOT / "docs" / "REAL_DATA_POLICY.md"
_REPORT_MODULE_PATH = _REPOSITORY_ROOT / "src" / "gpt_quant" / "research_report.py"
_RECOVERY_TEST_PATH = _REPOSITORY_ROOT / "tests" / "test_research_report_failure_recovery.py"


def test_real_data_policy_matches_holdout_report_publication() -> None:
    policy = _POLICY_PATH.read_text(encoding="utf-8")
    report_module = _REPORT_MODULE_PATH.read_text(encoding="utf-8")
    recovery_test = _RECOVERY_TEST_PATH.read_text(encoding="utf-8")

    publisher_start = report_module.index("def _publish_research_report_payloads(")
    writer_start = report_module.index("def write_research_report(")
    publisher = report_module[publisher_start:writer_start]
    writer = report_module[writer_start:]

    staging = 'with TemporaryDirectory(prefix=".research-report-", dir=output)'
    commit_loop = 'for name in ("json", "markdown"):'
    commit_replace = "os.replace(staged_paths[name], paths[name])"
    rollback_loop = "for name in reversed(replaced):"
    remove_new_file = "destination.unlink(missing_ok=True)"
    restore_file = "os.replace(restore_path, destination)"
    rollback_failure = "research report commit failed and rollback was incomplete"

    for implementation_claim in (
        staging,
        commit_loop,
        commit_replace,
        rollback_loop,
        remove_new_file,
        restore_file,
        rollback_failure,
    ):
        assert implementation_claim in publisher

    assert publisher.index(staging) < publisher.index(commit_loop)
    assert publisher.index(commit_replace) < publisher.index(rollback_loop)
    assert publisher.index(rollback_loop) < publisher.index(rollback_failure)
    assert writer.index("json_payload =") < writer.index("markdown_payload =")
    assert writer.index("markdown_payload =") < writer.index(
        "return _publish_research_report_payloads("
    )

    for documentation_claim in (
        "## Sealed holdout report publication and recovery",
        "renders `latest.json` and `latest.md` completely in memory",
        "publishes JSON first and Markdown second with `os.replace`",
        "rolls completed replacements back in reverse order",
        "leaves no partial report files",
        "restores the prior JSON and Markdown bytes exactly",
        "`research report commit failed and rollback was incomplete`",
        "indeterminate sealed-holdout report generation",
        "not atomic two-file visibility",
        "immutable real OKX BTC-USDT `1Dutc` fixture",
        "does not generate or alter market observations",
        "pytest tests/test_research_report_failure_recovery.py",
    ):
        assert documentation_claim in policy

    assert '@pytest.mark.parametrize("existing_report", [False, True])' in recovery_test
    assert '@pytest.mark.parametrize("failure_point", ["staging", "commit"])' in recovery_test
    assert "run_holdout_research(" in recovery_test
    assert "btc_usdt_prices" in recovery_test
    assert "assert not output_dir.exists()" in recovery_test
    assert "== original_bytes" in recovery_test
