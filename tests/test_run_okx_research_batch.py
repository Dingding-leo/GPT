from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_BATCH_RUNNER = Path(__file__).parents[1] / "scripts" / "run_okx_research_batch.py"


def _fake_runner(tmp_path: Path) -> Path:
    runner = tmp_path / "fake_research.py"
    runner.write_text(
        textwrap.dedent(
            """
            from __future__ import annotations

            import argparse
            import json
            import os
            import sys
            import time
            from pathlib import Path

            parser = argparse.ArgumentParser()
            parser.add_argument("--config")
            parser.add_argument("--inst-id", required=True)
            parser.add_argument("--output-dir", required=True)
            parser.add_argument("--manifest-path", required=True)
            parser.add_argument("--bar")
            parser.add_argument("--base-url")
            parser.add_argument("--start")
            parser.add_argument("--end")
            parser.add_argument("--max-pages")
            args = parser.parse_args()
            if args.inst_id == os.environ.get("FAIL_INSTRUMENT"):
                raise SystemExit("requested child failure")

            sync = Path(os.environ["BATCH_SYNC_DIR"])
            sync.mkdir(parents=True, exist_ok=True)
            (sync / f"{args.inst_id}.started").write_text("started", encoding="utf-8")
            deadline = time.monotonic() + 5.0
            while len(list(sync.glob("*.started"))) < 2:
                if time.monotonic() >= deadline:
                    raise SystemExit("children did not overlap")
                time.sleep(0.01)

            output = Path(args.output_dir)
            output.mkdir(parents=True, exist_ok=True)
            (output / "result.json").write_text(
                json.dumps({"instrument_id": args.inst_id}, sort_keys=True) + "\\n",
                encoding="utf-8",
            )
            manifest = Path(args.manifest_path)
            manifest.parent.mkdir(parents=True, exist_ok=True)
            manifest.write_text(
                json.dumps(
                    {
                        "instrument_id": args.inst_id,
                        "run_id": f"run-{args.inst_id}",
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
                + "\\n",
                encoding="utf-8",
            )
            if args.inst_id == "BTC-USDT":
                time.sleep(0.05)
            print(f"instrument_id={args.inst_id}")
            """
        ),
        encoding="utf-8",
    )
    return runner


def _command(tmp_path: Path, runner: Path) -> list[str]:
    return [
        sys.executable,
        str(_BATCH_RUNNER),
        "--runner",
        str(runner),
        "--output-root",
        str(tmp_path / "output"),
        "--manifest-path",
        str(tmp_path / "combined.jsonl"),
        "--max-workers",
        "2",
    ]


def test_batch_runs_children_concurrently_and_merges_manifest_in_requested_order(
    tmp_path: Path,
) -> None:
    runner = _fake_runner(tmp_path)
    environment = {**os.environ, "BATCH_SYNC_DIR": str(tmp_path / "sync")}

    completed = subprocess.run(  # noqa: S603
        _command(tmp_path, runner),
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
    )

    records = [
        json.loads(line)
        for line in (tmp_path / "combined.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [record["instrument_id"] for record in records] == ["BTC-USDT", "ETH-USDT"]
    assert completed.stdout.index("instrument_id=BTC-USDT") < completed.stdout.index(
        "instrument_id=ETH-USDT"
    )
    assert "batch_instruments=BTC-USDT,ETH-USDT" in completed.stdout
    assert "batch_peak_child_rss_bytes=" in completed.stdout
    assert json.loads((tmp_path / "output" / "BTC-USDT" / "result.json").read_text()) == {
        "instrument_id": "BTC-USDT"
    }
    assert json.loads((tmp_path / "output" / "ETH-USDT" / "result.json").read_text()) == {
        "instrument_id": "ETH-USDT"
    }


def test_batch_does_not_publish_combined_manifest_after_child_failure(tmp_path: Path) -> None:
    runner = _fake_runner(tmp_path)
    environment = {
        **os.environ,
        "BATCH_SYNC_DIR": str(tmp_path / "sync"),
        "FAIL_INSTRUMENT": "ETH-USDT",
    }

    completed = subprocess.run(  # noqa: S603
        _command(tmp_path, runner),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
    )

    assert completed.returncode != 0
    assert "OKX research failed for ETH-USDT" in completed.stderr
    assert not (tmp_path / "combined.jsonl").exists()


@pytest.mark.parametrize("instrument", ["btc-usdt", "BTC/USDT", "BTC-USDT;echo"])
def test_batch_rejects_noncanonical_instrument_ids(tmp_path: Path, instrument: str) -> None:
    runner = _fake_runner(tmp_path)
    completed = subprocess.run(  # noqa: S603
        [*_command(tmp_path, runner), "--inst-id", instrument],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "BATCH_SYNC_DIR": str(tmp_path / "sync")},
    )

    assert completed.returncode != 0
    assert "instrument IDs must be uppercase dash-separated" in completed.stderr
