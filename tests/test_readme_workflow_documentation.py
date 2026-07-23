from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_README_PATH = _REPOSITORY_ROOT / "README.md"
_WORKFLOW_PATH = _REPOSITORY_ROOT / ".github" / "workflows" / "hourly-research.yml"
_PORTFOLIO_SCRIPT_PATH = _REPOSITORY_ROOT / "scripts" / "run_portfolio_risk.py"
_PORTFOLIO_MODULE_PATH = _REPOSITORY_ROOT / "src" / "gpt_quant" / "portfolio.py"
_PORTFOLIO_RECOVERY_TEST_PATH = (
    _REPOSITORY_ROOT / "tests" / "test_portfolio_report_failure_recovery.py"
)


def test_readme_matches_hourly_portfolio_artifact_pipeline() -> None:
    readme = _README_PATH.read_text(encoding="utf-8")
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")
    portfolio_script = _PORTFOLIO_SCRIPT_PATH.read_text(encoding="utf-8")
    portfolio_module = _PORTFOLIO_MODULE_PATH.read_text(encoding="utf-8")
    recovery_test = _PORTFOLIO_RECOVERY_TEST_PATH.read_text(encoding="utf-8")

    source_pattern = "quant-research-source-<run-number>-attempt-<run-attempt>"
    portfolio_pattern = "quant-portfolio-risk-<run-number>-attempt-<run-attempt>"
    assert readme.count(source_pattern) == 1
    assert readme.count(portfolio_pattern) == 1

    source_declaration = (
        'SOURCE_ARTIFACT_NAME: "quant-research-source-${{ github.run_number }}-'
        'attempt-${{ github.run_attempt }}"'
    )
    portfolio_declaration = (
        'PORTFOLIO_ARTIFACT_NAME: "quant-portfolio-risk-${{ github.run_number }}-'
        'attempt-${{ github.run_attempt }}"'
    )
    assert source_declaration in workflow
    assert portfolio_declaration in workflow

    for output in (
        "portfolio_risk.json",
        "portfolio_risk.md",
        "portfolio_returns.csv",
    ):
        assert output in readme

    research_step = workflow.index("- name: Run OKX rolling out-of-sample research")
    source_upload = workflow.index("- name: Upload immutable sleeve research source")
    portfolio_step = workflow.index("- name: Generate verified portfolio risk report")
    portfolio_upload = workflow.index("- name: Upload verified portfolio risk artifact")
    assert research_step < source_upload < portfolio_step < portfolio_upload

    variance_declaration = 'MAX_VARIANCE_CONTRIBUTION: "0.75"'
    variance_argument = '--max-variance-contribution "$MAX_VARIANCE_CONTRIBUTION"'
    correlation_declaration = 'MAX_PAIRWISE_CORRELATION: "0.90"'
    correlation_argument = '--max-pairwise-correlation "$MAX_PAIRWISE_CORRELATION"'
    assert variance_declaration in workflow
    assert variance_argument in workflow
    assert correlation_declaration in workflow
    assert correlation_argument in workflow
    assert workflow.index(variance_declaration) < portfolio_step
    assert workflow.index(correlation_declaration) < portfolio_step
    assert workflow.index(variance_argument) > portfolio_step
    assert workflow.index(correlation_argument) > portfolio_step

    fail_closed_argument = "--fail-on-reject"
    rejected_report_upload_guard = (
        "if: ${{ always() && hashFiles('reports/portfolio/portfolio_risk.json') != '' }}"
    )
    portfolio_block = workflow[portfolio_step:portfolio_upload]
    upload_block = workflow[portfolio_upload:]
    assert workflow.count(fail_closed_argument) == 1
    assert fail_closed_argument in portfolio_block
    assert workflow.count(rejected_report_upload_guard) == 1
    assert rejected_report_upload_guard in upload_block

    assert 'parser.add_argument("--max-sleeve-weight", type=float, default=0.75)' in (
        portfolio_script
    )
    assert (
        'parser.add_argument("--max-variance-contribution", type=float, default=0.75)'
        in portfolio_script
    )
    assert (
        'parser.add_argument("--max-pairwise-correlation", type=float, default=0.90)'
        in portfolio_script
    )
    assert '"--fail-on-reject"' in portfolio_script
    report_write = portfolio_script.index("paths = write_portfolio_risk_report(")
    gate_return = portfolio_script.index(
        "return 1 if args.fail_on_reject and not risk_gate_passes else 0"
    )
    assert report_write < gate_return
    assert 'print(f"risk_gate_passes={str(risk_gate_passes).lower()}")' in portfolio_script

    assert "value > max_pairwise_correlation" in portfolio_module
    assert (
        "correlation_control_passes = not correlation_breaches and not "
        "unavailable_correlation_pairs"
    ) in portfolio_module
    for claim in (
        "`MAX_VARIANCE_CONTRIBUTION=0.75`",
        "`MAX_PAIRWISE_CORRELATION=0.90`",
        "默认最大 sleeve weight 为 75%",
        "单一 sleeve 的最大方差贡献同样为 75%",
        "任意可计算 sleeve pair 的收益相关系数上限为 90%",
        "相关系数严格高于上限",
        "因零方差等原因不可计算",
        "都会标记为 `reject`",
        "固定初始权重与 development-return covariance",
        "按对齐的 development-return observations 计算",
        "不是新的优化权重或 untouched-holdout 证据",
        "启用 `--fail-on-reject`",
        "聚合 `concentration.passes=false`",
        "打印 `risk_gate_passes=false`",
        "返回非零状态",
        "`always()` 与 `portfolio_risk.json` file-exists guard",
        "reject 证据仍会上传",
        "report-only 兼容模式",
    ):
        assert claim in readme
    assert "两项约束都通过时才标记为 `pass`" not in readme

    publisher_start = portfolio_module.index("def _publish_portfolio_report_payloads(")
    report_writer_start = portfolio_module.index("def write_portfolio_risk_report(")
    publisher = portfolio_module[publisher_start:report_writer_start]
    staging = 'with TemporaryDirectory(prefix=".portfolio-risk-", dir=output)'
    commit_loop = 'for name in ("json", "returns", "markdown"):'
    commit_replace = "os.replace(staged_paths[name], paths[name])"
    rollback_loop = "for name in reversed(replaced):"
    remove_new_file = "destination.unlink(missing_ok=True)"
    restore_file = "os.replace(restore_path, destination)"
    rollback_failure = "portfolio report commit failed and rollback was incomplete"
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

    assert '@pytest.mark.parametrize("existing_report", [False, True])' in recovery_test
    assert "assert not output_dir.exists()" in recovery_test
    assert "== original_bytes" in recovery_test
    for claim in (
        "事务式发布完整提交三个 report 文件",
        "临时 staging 目录完整生成",
        "JSON、returns、Markdown 顺序",
        "已替换文件会按逆序回滚",
        "不会留下新建的部分 report 目录",
        "恢复原有三个文件的精确字节",
        "rollback 自身也失败",
        "`portfolio report commit failed and rollback was incomplete`",
        "不能把该目录当作一致证据",
    ):
        assert claim in readme

    duplicate_source_error = "portfolio sleeves must use distinct verified return source columns"
    cli_duplicate_hash_error = (
        "BTC-USDT and ETH-USDT return files must have distinct SHA-256 digests"
    )
    assert duplicate_source_error in portfolio_module
    assert cli_duplicate_hash_error in portfolio_script
    binding_check = portfolio_module.index("bindings = _validate_return_source_bindings(")
    metric_calculation = portfolio_module.index("portfolio_metrics = performance_metrics(")
    assert binding_check < metric_calculation
    for claim in (
        "用已记录的 SHA-256 重新读取每个 return source",
        "逐字节对应已验证来源",
        "`(文件 SHA-256, timestamp 列, return 列, 所选时间戳)`",
        "把同一个已验证 return 列改名成 BTC 与 ETH 两个 sleeve",
        "两份 return 文件的 SHA-256 本身不同",
    ):
        assert claim in readme

    assert "path: reports/okx/" in workflow
    assert "path: reports/portfolio/" in workflow
    assert workflow.count("retention-days: 14") == 2
    assert "报告和原始数据快照作为 GitHub Actions artifact 保存 14 天。" not in readme


def test_reproduction_guide_matches_hourly_portfolio_artifact_pipeline() -> None:
    guide = (_REPOSITORY_ROOT / "docs" / "REPRODUCTION.md").read_text(encoding="utf-8")
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")

    source_pattern = "quant-research-source-<run-number>-attempt-<run-attempt>"
    portfolio_pattern = "quant-portfolio-risk-<run-number>-attempt-<run-attempt>"
    assert guide.count(source_pattern) == 1
    assert guide.count(portfolio_pattern) == 1

    for output in (
        "portfolio_risk.json",
        "portfolio_risk.md",
        "portfolio_returns.csv",
    ):
        assert guide.count(output) == 1

    assert "`reports/okx/`" in guide
    assert "`reports/portfolio/`" in guide
    assert "source artifact 的 ID、名称、下载包 SHA-256 digest" in guide
    assert "portfolio artifact 的 ID、名称、下载包 SHA-256 digest" in guide
    assert "不能把不同 run 或 attempt 的证据拼接在一起" in guide
    assert "上传 `reports/` artifact，保留 14 天" not in guide

    research_step = workflow.index("- name: Run OKX rolling out-of-sample research")
    source_upload = workflow.index("- name: Upload immutable sleeve research source")
    portfolio_step = workflow.index("- name: Generate verified portfolio risk report")
    portfolio_upload = workflow.index("- name: Upload verified portfolio risk artifact")
    assert research_step < source_upload < portfolio_step < portfolio_upload
    assert workflow.count("retention-days: 14") == 2
