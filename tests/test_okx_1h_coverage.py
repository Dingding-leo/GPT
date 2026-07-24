from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from gpt_quant.okx_1h import (
    derive_okx_one_hour_page_budget,
    fetch_okx_one_hour_candles,
    replay_persisted_okx_one_hour_snapshot,
)

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "okx_1h" / "BTC-USDT"


def test_five_year_one_hour_budget_exceeds_daily_default_without_network() -> None:
    pages = derive_okx_one_hour_page_budget(
        start="2021-07-24T00:00:00Z",
        end="2026-07-23T23:00:00Z",
    )

    assert pages == 441
    assert pages > 40


def test_one_hour_fetch_rejects_unaligned_boundaries_before_network() -> None:
    def unexpected_getter(url: str, timeout: float) -> dict[str, object]:
        pytest.fail(f"unaligned 1H request reached network: {url=} {timeout=}")

    with pytest.raises(ValueError, match="start must align to an exact UTC hour"):
        fetch_okx_one_hour_candles(
            inst_id="BTC-USDT",
            start="2021-07-24T00:30:00Z",
            end="2026-07-23T23:00:00Z",
            get_json=unexpected_getter,
        )


def test_immutable_real_okx_one_hour_fixture_replays_exactly() -> None:
    source = json.loads((_FIXTURE_DIR / "SOURCE.json").read_text(encoding="utf-8"))
    for evidence in source["fixture_files"].values():
        path = Path(evidence["path"])
        assert hashlib.sha256(path.read_bytes()).hexdigest() == evidence["sha256"]

    snapshot = replay_persisted_okx_one_hour_snapshot(
        _FIXTURE_DIR,
        inst_id="BTC-USDT",
    )

    assert len(snapshot.candles) == source["observations"] == 3
    assert snapshot.metadata["raw_pages_sha256"] == source["fixture_files"]["raw"]["sha256"]
    assert snapshot.metadata["missing_intervals"] == 0
    assert snapshot.metadata["incomplete_rows_removed"] == 1
    assert snapshot.candles["confirm"].eq("1").all()
    deltas = snapshot.candles.index.to_series().diff().dropna().dt.total_seconds()
    assert deltas.eq(3_600).all()


def test_one_hour_replay_rejects_tampered_source_bytes(tmp_path: Path) -> None:
    copied = tmp_path / "BTC-USDT"
    shutil.copytree(_FIXTURE_DIR, copied)
    raw_path = copied / "okx-BTC-USDT-1H.raw.json"
    raw_path.write_bytes(raw_path.read_bytes() + b" ")

    with pytest.raises(ValueError, match="raw-pages hash mismatch"):
        replay_persisted_okx_one_hour_snapshot(copied, inst_id="BTC-USDT")
