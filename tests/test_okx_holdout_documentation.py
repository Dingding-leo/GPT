from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_FIXTURE_METADATA_PATH = (
    _REPOSITORY_ROOT
    / "tests"
    / "fixtures"
    / "okx"
    / "btc-usdt-1dutc-20180111-20200628"
    / "metadata.json"
)


def _load_json(path: str | Path) -> dict[str, object]:
    source = Path(path)
    if not source.is_absolute():
        source = _REPOSITORY_ROOT / source
    return json.loads(source.read_text(encoding="utf-8"))


def test_okx_holdout_config_matches_daily_okx_market_assumptions() -> None:
    rolling = _load_json("config/okx_research.json")
    holdout = _load_json("config/okx_holdout.json")

    assert holdout["strategy"] == rolling["strategy"]
    for key in ("momentum_lookbacks", "reversal_lookbacks", "trend_weights"):
        assert holdout["search"][key] == rolling["search"][key]

    assert holdout["strategy"]["annualization"] == 365
    assert holdout["strategy"]["transaction_cost_bps"] == 10.0
    assert holdout["search"]["validation_fraction"] == 0.2
    assert holdout["search"]["holdout_fraction"] == 0.2
    assert holdout["search"]["top_candidates"] == 10


def test_manifest_backed_okx_examples_use_the_compatible_holdout_config() -> None:
    readme = (_REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
    reproduction = (_REPOSITORY_ROOT / "docs/REPRODUCTION.md").read_text(encoding="utf-8")

    expected = "--config config/okx_holdout.json"
    assert readme.count(expected) == 1
    assert reproduction.count(expected) == 2
    assert "--config config/research.json" not in readme
    assert "--config config/research.json" not in reproduction
    assert "okx_holdout_config=verified" in reproduction


def test_reproduction_guide_uses_manifest_helper_in_bash_and_powershell() -> None:
    reproduction = (_REPOSITORY_ROOT / "docs/REPRODUCTION.md").read_text(encoding="utf-8")
    section = reproduction.split(
        "### 从本仓库生成的 OKX 快照创建 manifest", maxsplit=1
    )[1].split("BTC-USDT `1Dutc`", maxsplit=1)[0]

    helper = "python scripts/create_verified_snapshot_manifest.py"
    assert section.count(helper) == 2
    assert section.count("```bash") == 1
    assert section.count("```powershell") == 1
    for argument in ("--metadata", "--csv", "--output"):
        assert section.count(argument) == 2
    for path in (
        "reports/okx/BTC-USDT/snapshot/okx-BTC-USDT-1Dutc.metadata.json",
        "reports/okx/BTC-USDT/snapshot/okx-BTC-USDT-1Dutc.csv",
        "reports/okx/BTC-USDT/snapshot/verified-snapshot.json",
    ):
        assert section.count(path) == 2
    assert section.count("VERIFIED_SNAPSHOT_MANIFEST.md") == 1
    assert 'python -c "import csv,hashlib,json,pathlib' not in reproduction
    assert "PowerShell 可直接运行同一条 `python -c` 命令" not in reproduction


def test_documented_okx_manifest_and_holdout_commands_run_on_verified_real_fixture(
    tmp_path: Path,
    btc_usdt_prices: pd.Series,
) -> None:
    snapshot_dir = tmp_path / "snapshot"
    snapshot_dir.mkdir()
    csv_path = snapshot_dir / "okx-BTC-USDT-1Dutc.csv"
    pd.DataFrame(
        {
            "timestamp": [timestamp.isoformat() for timestamp in btc_usdt_prices.index],
            "close": btc_usdt_prices.to_numpy(),
        }
    ).to_csv(csv_path, index=False, lineterminator="\n")

    source = _load_json(_FIXTURE_METADATA_PATH)
    metadata = dict(source)
    metadata["normalized_csv_sha256"] = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    metadata_path = snapshot_dir / "okx-BTC-USDT-1Dutc.metadata.json"
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    manifest_path = snapshot_dir / "verified-snapshot.json"
    manifest_completed = subprocess.run(
        [
            sys.executable,
            "scripts/create_verified_snapshot_manifest.py",
            "--metadata",
            str(metadata_path),
            "--csv",
            str(csv_path),
            "--output",
            str(manifest_path),
        ],
        cwd=_REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert manifest_completed.returncode == 0, manifest_completed.stdout + manifest_completed.stderr
    manifest = _load_json(manifest_path)
    assert manifest["provider"] == source["provider"]
    assert manifest["instrument_id"] == source["instrument_id"]
    assert manifest["timeframe"] == source["bar"]
    assert manifest["observations"] == len(btc_usdt_prices)
    assert manifest["data_sha256"] == metadata["normalized_csv_sha256"]
    assert manifest["provenance"]["source_workflow_run_id"] == source["source_workflow_run_id"]

    output_dir = tmp_path / "holdout"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_research.py",
            "--snapshot-manifest",
            str(manifest_path),
            "--config",
            "config/okx_holdout.json",
            "--output-dir",
            str(output_dir),
        ],
        cwd=_REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = _load_json(output_dir / "latest.json")
    assert report["data_summary"]["observations"] == len(btc_usdt_prices)
    assert report["candidates_tested"] == 27
    assert report["selected_parameters"]["annualization"] == 365
    assert report["selected_parameters"]["transaction_cost_bps"] == 10.0
    assert (output_dir / "latest.md").is_file()
