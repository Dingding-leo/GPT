from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_GUIDE_PATH = _REPOSITORY_ROOT / "docs" / "OKX_INTERVALS.md"
_SOURCE_PATH = _REPOSITORY_ROOT / "src" / "gpt_quant" / "okx.py"
_RESEARCH_SCRIPT_PATH = _REPOSITORY_ROOT / "scripts" / "run_okx_research.py"


def test_okx_interval_guide_matches_fail_closed_pagination_chronology() -> None:
    guide = _GUIDE_PATH.read_text(encoding="utf-8")
    source = _SOURCE_PATH.read_text(encoding="utf-8")

    runtime_messages = (
        "must be strictly newest-to-oldest",
        "OKX pagination returned rows newer than the requested cursor",
        "conflicts with an earlier row for timestamp",
        "OKX pagination did not move backward in time",
    )
    for message in runtime_messages:
        assert message in guide
        assert message in source

    raw_rows_acceptance = source.index("raw_rows.extend(page_data)")
    for message in runtime_messages:
        assert source.index(message) < raw_rows_acceptance

    assert "精确重复的游标边界行可以跨页重叠" in guide
    assert "tests/test_okx_cadence.py" in guide
    assert "tests/test_okx_raw_page_integrity.py" in guide
    assert "tests/test_okx_interval_documentation.py" in guide


def test_okx_interval_guide_matches_downloader_and_cli_end_coverage_gates() -> None:
    guide = _GUIDE_PATH.read_text(encoding="utf-8")
    source = _SOURCE_PATH.read_text(encoding="utf-8")
    research_script = _RESEARCH_SCRIPT_PATH.read_text(encoding="utf-8")

    downloader_messages = (
        "OKX download contains a completed candle after the requested end",
        "OKX download does not cover the requested end boundary",
    )
    for message in downloader_messages:
        assert message in guide
        assert message in source

    end_filter = source.index("candles = candles.loc[candles.index <= end_timestamp]")
    downloader_coverage_call = source.index(
        "    _validate_requested_end_coverage(\n        candles,"
    )
    snapshot_return = source.index("return OKXCandleSnapshot(")
    assert end_filter < downloader_coverage_call < snapshot_return

    cli_messages = (
        "requested end must be a valid timestamp",
        "OKX snapshot is missing a valid expected bar cadence",
        "OKX snapshot contains a completed candle after the requested end",
        "OKX download does not cover the requested end boundary",
    )
    for message in cli_messages:
        assert message in guide
        assert message in research_script

    cli_coverage_call = research_script.index(
        "_validate_requested_end_coverage(snapshot, requested_end=end)"
    )
    snapshot_write = research_script.index('write_okx_snapshot(snapshot, output / "snapshot")')
    assert cli_coverage_call < snapshot_write

    assert "显式结束边界由下载器强制" in guide
    assert "任何直接调用" in guide
    assert "防御性复核" in guide
    assert "end - latest" in guide
    assert "严格小于一个声明周期" in guide
    assert "requested_start_reached=false" in guide
    assert "tests/test_okx_end_coverage.py" in guide
    assert "tests/test_run_okx_research_end_coverage.py" in guide


def test_okx_interval_guide_matches_open_ended_freshness_gate() -> None:
    guide = _GUIDE_PATH.read_text(encoding="utf-8")
    source = _SOURCE_PATH.read_text(encoding="utf-8")

    runtime_messages = (
        "OKX download contains a completed candle after the freshness reference",
        "OKX open-ended download is stale",
        "as_of is only valid with an injected get_json",
    )
    for message in runtime_messages:
        assert message in guide
        assert message in source

    assert "_OPEN_ENDED_FRESHNESS_GRACE_SECONDS = 5 * 60" in source
    assert (
        "max_age_seconds = 2 * expected_step_seconds "
        "+ _OPEN_ENDED_FRESHNESS_GRACE_SECONDS"
        in source
    )

    live_reference = source.index("as_of_timestamp = _current_utc_timestamp()")
    getter_assignment = source.index("getter = get_json or _default_json_getter")
    parsed_rows = source.index("parsed = parse_okx_candle_rows(raw_rows)")
    freshness_call = source.index(
        "    freshness_age_seconds, freshness_max_age_seconds = "
        "_validate_open_ended_freshness("
    )
    snapshot_return = source.index("return OKXCandleSnapshot(")
    assert live_reference < getter_assignment < parsed_rows < freshness_call < snapshot_return

    for metadata_field in (
        "freshness_checked_at_utc",
        "freshness_age_seconds",
        "freshness_max_age_seconds",
    ):
        assert metadata_field in guide
        assert metadata_field in source

    assert "省略 `end`" in guide
    assert "`2 × expected_step_seconds + 5 分钟`" in guide
    assert "`48 小时 5 分钟`" in guide
    assert "网络下载开始前采样 UTC 参考时刻" in guide
    assert "PR #226" in guide
    assert "tests/test_okx_open_ended_freshness.py" in guide
