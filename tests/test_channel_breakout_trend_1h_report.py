from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_ROOT = Path(__file__).parents[1]
_ARCHITECTURE_PATH = (
    _ROOT / "reports" / "research" / "channel-breakout-trend-1h" / "architecture.py"
)
_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "okx_1h" / "BTC-USDT" / "okx-BTC-USDT-1H.csv"


def _load_architecture():
    spec = importlib.util.spec_from_file_location(
        "channel_breakout_architecture",
        _ARCHITECTURE_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_fixture(architecture) -> pd.DataFrame:
    frame = pd.read_csv(_FIXTURE_PATH)
    frame.index = architecture.hourly_index(frame.pop("timestamp"))
    return frame


def _real_fixture_artifact(tmp_path: Path) -> tuple[Path, bytes, set[str]]:
    root = tmp_path / "artifact"
    snapshot = _FIXTURE_PATH.read_bytes()
    paths = {
        "effective_config.json",
        "walk_forward.json",
        "walk_forward_returns.csv",
        "snapshot/okx-BTC-USDT-1H.csv",
    }
    for relative in paths:
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(snapshot)
    manifest = "".join(
        f"{hashlib.sha256((root / relative).read_bytes()).hexdigest()}  {relative}\n"
        for relative in sorted(paths)
    ).encode()
    return root, manifest, paths


def test_real_okx_channel_target_is_causal_and_bounded() -> None:
    architecture = _load_architecture()
    candles = _load_fixture(architecture)
    original = architecture.target_path(candles, channel=2, regime=2, volatility=2)
    altered = candles.copy()
    altered.iloc[-1, altered.columns.get_loc("high")] *= 1.20
    altered.iloc[-1, altered.columns.get_loc("low")] *= 0.80
    altered.iloc[-1, altered.columns.get_loc("close")] *= 1.10
    changed = architecture.target_path(altered, channel=2, regime=2, volatility=2)

    pd.testing.assert_series_equal(original.iloc[:-1], changed.iloc[:-1])
    assert original.between(0.0, 1.0).all()
    assert changed.between(0.0, 1.0).all()


def test_exact_five_bps_accounting_starts_from_cash() -> None:
    architecture = _load_architecture()
    candles = _load_fixture(architecture)
    target = pd.Series([0.5, 0.25, 0.0], index=candles.index)
    frame = architecture.return_frame(candles, target, candles.index)

    assert frame["position"].iloc[0] == 0.0
    np.testing.assert_allclose(frame["trading_cost"], frame["turnover"] * 0.0005)
    np.testing.assert_allclose(
        frame["strategy_return"],
        frame["gross_strategy_return"] - frame["trading_cost"],
    )


def test_manifest_verification_binds_required_real_artifact_bytes(tmp_path: Path) -> None:
    architecture = _load_architecture()
    root, manifest, required = _real_fixture_artifact(tmp_path)

    verified = architecture.verify_manifested_artifact_bytes(root, manifest, required)
    assert verified["walk_forward_returns.csv"] == _FIXTURE_PATH.read_bytes()

    returns_path = root / "walk_forward_returns.csv"
    returns_path.write_bytes(returns_path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="artifact manifest hash mismatch"):
        architecture.verify_manifested_artifact_bytes(root, manifest, required)


def test_manifest_verification_rejects_missing_required_entry(tmp_path: Path) -> None:
    architecture = _load_architecture()
    root, manifest, required = _real_fixture_artifact(tmp_path)
    missing_line = next(
        line for line in manifest.splitlines() if line.endswith(b"  walk_forward_returns.csv")
    )
    manifest = manifest.replace(missing_line + b"\n", b"")

    with pytest.raises(ValueError, match="required artifact missing from manifest"):
        architecture.verify_manifested_artifact_bytes(root, manifest, required)


def test_persisted_result_records_single_rejected_candidate() -> None:
    result = json.loads(
        (_ROOT / "reports" / "research" / "channel-breakout-trend-1h" / "result.json").read_text()
    )
    accounting = result["candidate_accounting"]
    assert accounting["architecture_candidates_searched"] == 1
    assert accounting["architecture_candidates_passed"] == 0
    assert accounting["architecture_candidates_rejected"] == 1
    assert set(result["markets"]) == {"BTC-USDT", "ETH-USDT"}
    assert result["verdict"] == "rejected"
    assert result["paper_testable"] is False
    assert result["live_eligible"] is False
    assert result["fixed_architecture"]["transaction_cost_bps_one_way"] == 5.0
    assert result["fixed_architecture"]["modeled_cost_paths"] == ["5bps_one_way_only"]
