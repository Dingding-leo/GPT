from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_PATH = ROOT / "reports" / "research" / "cscv-pbo-candidate-grid" / "analysis.py"
RESULT_PATH = ROOT / "reports" / "research" / "cscv-pbo-candidate-grid" / "result.json"
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "okx" / "btc_eth_oos_20200111_20200219"
SPEC = importlib.util.spec_from_file_location("cscv_pbo_candidate_grid", ANALYSIS_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"unable to import {ANALYSIS_PATH}")
analysis = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analysis)


def _fixture_frame(name: str, expected_sha256: str) -> pd.DataFrame:
    path = FIXTURE_DIR / name
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected_sha256
    frame = pd.read_csv(path)
    frame.index = pd.DatetimeIndex(pd.to_datetime(frame.pop("timestamp"), utc=True))
    frame["turnover"] = 0.0
    return frame


def test_cscv_reference_example_uses_real_okx_returns() -> None:
    candidates = {
        "BTC-USDT": _fixture_frame(
            "btc_usdt_returns.csv",
            "417ff56ee3e71d8e2e8545ee4eb79091bd6f173bde29c79371aae96b65b12587",
        ),
        "ETH-USDT": _fixture_frame(
            "eth_usdt_returns.csv",
            "552401a2e90368ac675915b067a575287d993b46bd355ff17e8a68ff847d8db8",
        ),
    }

    result = analysis.probability_of_backtest_overfitting(candidates, subsamples=4)

    assert result["observations"] == 40
    assert result["candidate_count"] == 2
    assert result["subsample_length"] == 10
    assert result["cscv_splits"] == 6
    assert result["overfit_splits"] == 2
    assert result["pbo"] == pytest.approx(1.0 / 3.0)
    assert result["selected_candidate_frequencies"] == {"BTC-USDT": 1, "ETH-USDT": 5}


def test_pbo_rejects_invalid_partitions_on_real_returns() -> None:
    frame = _fixture_frame(
        "btc_usdt_returns.csv",
        "417ff56ee3e71d8e2e8545ee4eb79091bd6f173bde29c79371aae96b65b12587",
    )
    with pytest.raises(ValueError, match="even integer"):
        analysis.probability_of_backtest_overfitting({"a": frame, "b": frame}, subsamples=5)
    with pytest.raises(ValueError, match="divide evenly"):
        analysis.probability_of_backtest_overfitting(
            {"a": frame.iloc[:-1], "b": frame.iloc[:-1]},
            subsamples=4,
        )


def test_committed_pbo_report_records_complete_rejection() -> None:
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))

    assert result["canonical_signature"] == analysis.SIGNATURE
    assert result["candidate_accounting"] == {
        "searched": 1,
        "passed": 0,
        "rejected": 1,
        "grid_candidates_per_market": 27,
        "cscv_splits_per_market": 924,
    }
    assert result["verdict"] == "rejected"
    assert result["method"]["transaction_cost_bps"] == 10.0
    assert result["method"]["execution_delay_bars"] == 1
    assert result["provenance"]["source_artifact_sha256"] == analysis.SOURCE_ARTIFACT_SHA256
    assert result["markets"]["BTC-USDT"]["pbo"] == pytest.approx(410 / 924)
    assert result["markets"]["ETH-USDT"]["pbo"] == pytest.approx(316 / 924)
    assert not result["markets"]["BTC-USDT"]["passes"]
    assert not result["markets"]["ETH-USDT"]["passes"]
    assert result["markets"]["BTC-USDT"]["selected_path_reproduction_max_abs_error"] < 1e-15
    assert result["markets"]["ETH-USDT"]["selected_path_reproduction_max_abs_error"] < 1e-15
