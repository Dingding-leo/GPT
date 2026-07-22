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


def test_documented_okx_holdout_command_runs_on_verified_real_fixture(
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
    manifest = {
        "schema_version": 1,
        "provider": source["provider"],
        "market_type": "spot",
        "instrument_id": source["instrument_id"],
        "timeframe": source["bar"],
        "schema": {
            "columns": ["timestamp", "close"],
            "timestamp_column": "timestamp",
            "close_column": "close",
        },
        "observations": len(btc_usdt_prices),
        "start": btc_usdt_prices.index[0].isoformat(),
        "end": btc_usdt_prices.index[-1].isoformat(),
        "data_path": csv_path.name,
        "data_sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        "provenance": {
            "source_workflow_run_id": source["source_workflow_run_id"],
            "source_artifact_id": source["source_artifact_id"],
            "source_artifact_sha256": source["source_artifact_sha256"],
            "source_head_sha": source["source_head_sha"],
        },
    }
    manifest_path = snapshot_dir / "verified-snapshot.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

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
