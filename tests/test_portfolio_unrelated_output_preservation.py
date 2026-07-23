from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from gpt_quant.portfolio import (
    build_buy_and_hold_sleeve_portfolio,
    load_verified_return_csv,
    write_portfolio_risk_report,
)

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "okx" / "btc_eth_oos_20200111_20200219"
_SOURCE_FILENAMES = {
    "BTC-USDT": "btc_usdt_returns.csv",
    "ETH-USDT": "eth_usdt_returns.csv",
}
_REPORT_FILENAMES = frozenset(
    {"portfolio_risk.json", "portfolio_risk.md", "portfolio_returns.csv"}
)


def _build_verified_portfolio_result():
    metadata = json.loads((_FIXTURE_DIR / "metadata.json").read_text(encoding="utf-8"))
    instruments = metadata["instruments"]
    sleeve_returns = {
        instrument: load_verified_return_csv(
            _FIXTURE_DIR / filename,
            expected_sha256=instruments[instrument]["fixture_sha256"],
        )
        for instrument, filename in _SOURCE_FILENAMES.items()
    }
    provenance = {
        "provider": metadata["provider"],
        "market_type": metadata["market_type"],
        "timeframe": metadata["timeframe"],
        "source_workflow_run_id": metadata["source_workflow_run_id"],
        "source_artifact_id": metadata["source_artifact_id"],
        "source_artifact_name": metadata["source_artifact_name"],
        "source_artifact_sha256": metadata["source_artifact_sha256"],
        "source_head_sha": metadata["source_head_sha"],
        "return_file_sha256": {
            instrument: details["fixture_sha256"]
            for instrument, details in instruments.items()
        },
    }
    return build_buy_and_hold_sleeve_portfolio(
        sleeve_returns,
        initial_weights={"BTC-USDT": 0.5, "ETH-USDT": 0.5},
        provenance=provenance,
    )


@pytest.mark.parametrize("failure_kind", ["staging", "commit"])
@pytest.mark.parametrize("failure_position", [1, 2, 3])
def test_publication_failure_preserves_unrelated_output_contents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
    failure_position: int,
) -> None:
    result = _build_verified_portfolio_result()
    output_dir = tmp_path / "portfolio-report"
    output_dir.mkdir()
    sentinel = output_dir / "operator-notes.txt"
    sentinel_payload = b"retain this caller-owned file\n"
    sentinel.write_bytes(sentinel_payload)

    observed_operations = 0
    error_message = f"simulated portfolio {failure_kind} failure"

    if failure_kind == "staging":
        real_write_bytes = Path.write_bytes

        def fail_stage(path: Path, data: bytes) -> int:
            nonlocal observed_operations
            if (
                path.name in _REPORT_FILENAMES
                and path.parent.name.startswith(".portfolio-risk-")
                and path.parent.parent == output_dir
            ):
                observed_operations += 1
                if observed_operations == failure_position:
                    raise OSError(error_message)
            return real_write_bytes(path, data)

        monkeypatch.setattr(Path, "write_bytes", fail_stage)
    else:
        real_replace = os.replace

        def fail_commit(source: str | Path, destination: str | Path) -> None:
            nonlocal observed_operations
            source_path = Path(source)
            destination_path = Path(destination)
            if (
                source_path.name in _REPORT_FILENAMES
                and destination_path.parent == output_dir
                and destination_path.name in _REPORT_FILENAMES
            ):
                observed_operations += 1
                if observed_operations == failure_position:
                    raise OSError(error_message)
            real_replace(source, destination)

        monkeypatch.setattr(os, "replace", fail_commit)

    with pytest.raises(OSError, match=error_message):
        write_portfolio_risk_report(result, output_dir)

    assert observed_operations == failure_position
    assert {path.name for path in output_dir.iterdir()} == {sentinel.name}
    assert sentinel.read_bytes() == sentinel_payload
