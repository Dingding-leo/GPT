from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

from gpt_quant.verified_snapshot import load_verified_price_snapshot

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT_PATH = _REPOSITORY_ROOT / "scripts" / "create_verified_snapshot_manifest.py"
_FIXTURE_METADATA_PATH = (
    _REPOSITORY_ROOT
    / "tests"
    / "fixtures"
    / "okx"
    / "btc-usdt-1dutc-20180111-20200628"
    / "metadata.json"
)


def _load_fixture_metadata() -> dict[str, object]:
    return json.loads(_FIXTURE_METADATA_PATH.read_text(encoding="utf-8"))


def _write_snapshot_bundle(
    tmp_path: Path,
    btc_usdt_prices: pd.Series,
) -> tuple[Path, Path, Path]:
    snapshot_dir = tmp_path / "snapshot"
    snapshot_dir.mkdir()
    csv_path = snapshot_dir / "okx-BTC-USDT-1Dutc.csv"
    pd.DataFrame(
        {
            "timestamp": [timestamp.isoformat() for timestamp in btc_usdt_prices.index],
            "close": btc_usdt_prices.to_numpy(),
        }
    ).to_csv(csv_path, index=False, lineterminator="\n")

    source = _load_fixture_metadata()
    metadata = {
        "provider": source["provider"],
        "instrument_id": source["instrument_id"],
        "bar": source["bar"],
        "observations": len(btc_usdt_prices),
        "start": btc_usdt_prices.index[0].isoformat(),
        "end": btc_usdt_prices.index[-1].isoformat(),
        "normalized_csv_sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        "raw_pages_sha256": source["source_raw_pages_sha256"],
        "source_workflow_run_id": source["source_workflow_run_id"],
        "source_artifact_id": source["source_artifact_id"],
        "source_artifact_name": source["source_artifact_name"],
        "source_artifact_sha256": source["source_artifact_sha256"],
        "source_head_sha": source["source_head_sha"],
    }
    metadata_path = snapshot_dir / "okx-BTC-USDT-1Dutc.metadata.json"
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return metadata_path, csv_path, snapshot_dir / "verified-snapshot.json"


def _run_builder(
    metadata_path: Path,
    csv_path: Path,
    output_path: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(_SCRIPT_PATH),
            "--metadata",
            str(metadata_path),
            "--csv",
            str(csv_path),
            "--output",
            str(output_path),
        ],
        cwd=_REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_manifest_builder_creates_loadable_manifest_from_real_okx_fixture(
    tmp_path: Path,
    btc_usdt_prices: pd.Series,
) -> None:
    metadata_path, csv_path, manifest_path = _write_snapshot_bundle(tmp_path, btc_usdt_prices)

    completed = _run_builder(metadata_path, csv_path, manifest_path)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "snapshot_manifest=" in completed.stdout
    snapshot = load_verified_price_snapshot(manifest_path)
    assert snapshot.provider == "OKX"
    assert snapshot.market_type == "spot"
    assert snapshot.instrument_id == "BTC-USDT"
    assert snapshot.timeframe == "1Dutc"
    assert snapshot.observations == len(btc_usdt_prices)
    assert snapshot.prices.equals(btc_usdt_prices)
    assert snapshot.provenance["source_workflow_run_id"] == 29841895366


def test_manifest_builder_rejects_metadata_hash_drift_before_output(
    tmp_path: Path,
    btc_usdt_prices: pd.Series,
) -> None:
    metadata_path, csv_path, manifest_path = _write_snapshot_bundle(tmp_path, btc_usdt_prices)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["normalized_csv_sha256"] = "0" * 64
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    completed = _run_builder(metadata_path, csv_path, manifest_path)

    assert completed.returncode != 0
    assert "normalized_csv_sha256 does not match CSV bytes" in completed.stderr
    assert not manifest_path.exists()


def test_manifest_builder_is_documented_for_bash_and_powershell() -> None:
    readme = (_REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
    guide = (_REPOSITORY_ROOT / "docs/VERIFIED_SNAPSHOT_MANIFEST.md").read_text(encoding="utf-8")

    command = "python scripts/create_verified_snapshot_manifest.py"
    assert command in readme
    assert guide.count(command) == 2
    assert "```bash" in guide
    assert "```powershell" in guide
