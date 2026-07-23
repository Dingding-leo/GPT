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
    assert "不指定 `end`" in guide
    assert "tests/test_okx_end_coverage.py" in guide
    assert "tests/test_run_okx_research_end_coverage.py" in guide
