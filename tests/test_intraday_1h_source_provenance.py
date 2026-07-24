from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from gpt_quant.intraday_1h_source_provenance import (
    verify_intraday_1h_source_provenance,
    write_intraday_1h_source_provenance,
)

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "okx_1h" / "BTC-USDT"


def _output_with_snapshot(tmp_path: Path) -> Path:
    output = tmp_path / "research"
    shutil.copytree(_FIXTURE_DIR, output / "snapshot")
    return output


def test_exact_byte_source_provenance_reconstructs_from_immutable_okx_fixture(
    tmp_path: Path,
) -> None:
    source = json.loads((_FIXTURE_DIR / "SOURCE.json").read_text(encoding="utf-8"))
    for evidence in source["fixture_files"].values():
        path = Path(evidence["path"])
        assert hashlib.sha256(path.read_bytes()).hexdigest() == evidence["sha256"]

    output = _output_with_snapshot(tmp_path)
    path, digest = write_intraday_1h_source_provenance(output, inst_id="BTC-USDT")
    payload = verify_intraday_1h_source_provenance(output, inst_id="BTC-USDT")

    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    assert payload["offline_replay_verified"] is True
    assert payload["source_transport"] == "trusted_okx_https_bounded_exact_bytes"
    assert payload["source_response_sha256"] == [source["raw_response_extract_sha256"]]
    assert payload["normalized_csv_sha256"] == source["fixture_files"]["candles"]["sha256"]
    assert payload["raw_pages_sha256"] == source["fixture_files"]["raw"]["sha256"]
    assert payload["economic_boundary"]["modeled_fee_bps_one_way"] == 5.0
    assert payload["safety"]["orders_placed"] is False


def test_source_provenance_rejects_self_consistent_persisted_tampering(tmp_path: Path) -> None:
    output = _output_with_snapshot(tmp_path)
    path, _digest = write_intraday_1h_source_provenance(output, inst_id="BTC-USDT")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["offline_replay_verified"] = False
    path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")

    with pytest.raises(ValueError, match="does not reconstruct exactly"):
        verify_intraday_1h_source_provenance(output, inst_id="BTC-USDT")
