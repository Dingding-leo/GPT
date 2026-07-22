from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

import gpt_quant.portfolio as portfolio
from gpt_quant.portfolio import (
    build_buy_and_hold_sleeve_portfolio,
    load_verified_return_csv,
    write_portfolio_risk_report,
)
from gpt_quant.reproducibility import file_sha256

_SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "run_portfolio_risk.py"
_SCRIPT_SPEC = importlib.util.spec_from_file_location("run_portfolio_risk", _SCRIPT_PATH)
if _SCRIPT_SPEC is None or _SCRIPT_SPEC.loader is None:
    raise RuntimeError(f"unable to load portfolio risk CLI from {_SCRIPT_PATH}")
run_portfolio_risk = importlib.util.module_from_spec(_SCRIPT_SPEC)
_SCRIPT_SPEC.loader.exec_module(run_portfolio_risk)

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "okx" / "btc_eth_oos_20200111_20200219"


def _load_fixture_returns() -> tuple[pd.Series, pd.Series, dict[str, object]]:
    metadata = json.loads((_FIXTURE_DIR / "metadata.json").read_text(encoding="utf-8"))
    instruments = metadata["instruments"]
    btc = load_verified_return_csv(
        _FIXTURE_DIR / "btc_usdt_returns.csv",
        expected_sha256=instruments["BTC-USDT"]["fixture_sha256"],
    )
    eth = load_verified_return_csv(
        _FIXTURE_DIR / "eth_usdt_returns.csv",
        expected_sha256=instruments["ETH-USDT"]["fixture_sha256"],
    )
    return btc, eth, metadata


def _fixture_provenance(metadata: dict[str, object]) -> dict[str, object]:
    instruments = metadata["instruments"]
    return {
        "provider": metadata["provider"],
        "market_type": metadata["market_type"],
        "timeframe": metadata["timeframe"],
        "source_workflow_run_id": metadata["source_workflow_run_id"],
        "source_artifact_id": metadata["source_artifact_id"],
        "source_artifact_name": metadata["source_artifact_name"],
        "source_artifact_sha256": metadata["source_artifact_sha256"],
        "source_head_sha": metadata["source_head_sha"],
        "return_file_sha256": {
            name: details["fixture_sha256"] for name, details in instruments.items()
        },
    }


def test_verified_real_return_fixture_has_expected_provenance() -> None:
    btc, eth, metadata = _load_fixture_returns()

    assert metadata["provider"] == "OKX"
    assert metadata["timeframe"] == "1Dutc"
    assert len(btc) == len(eth) == 40
    assert btc.index.equals(eth.index)
    assert btc.index[0] == pd.Timestamp("2020-01-11T00:00:00Z")
    assert btc.index[-1] == pd.Timestamp("2020-02-19T00:00:00Z")


def test_buy_and_hold_sleeve_portfolio_reconciles_returns_and_weights(tmp_path) -> None:
    btc, eth, metadata = _load_fixture_returns()
    result = build_buy_and_hold_sleeve_portfolio(
        {"BTC-USDT": btc, "ETH-USDT": eth},
        initial_weights={"BTC-USDT": 0.5, "ETH-USDT": 0.5},
        max_sleeve_weight=0.75,
        provenance=_fixture_provenance(metadata),
    )

    contributions = result.frame[
        ["BTC-USDT_return_contribution", "ETH-USDT_return_contribution"]
    ].sum(axis=1)
    pd.testing.assert_series_equal(
        contributions,
        result.frame["strategy_return"],
        check_names=False,
        atol=1e-12,
        rtol=0.0,
    )
    end_weight_sum = result.frame[["BTC-USDT_end_weight", "ETH-USDT_end_weight"]].sum(axis=1)
    assert end_weight_sum.to_numpy() == pytest.approx(1.0)
    assert sum(result.risk_contributions.values()) == pytest.approx(1.0)
    assert result.data_summary["provenance"]["source_artifact_id"] == 8499721759
    assert result.portfolio_metrics["average_abs_exposure"] == pytest.approx(1.0)

    paths = write_portfolio_risk_report(result, tmp_path)
    assert all(path.exists() for path in paths.values())
    saved = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert saved["risk_status"] == result.risk_status
    assert "frame" not in saved


def test_report_serializes_undefined_correlation_as_strict_json(tmp_path) -> None:
    btc, eth, metadata = _load_fixture_returns()
    btc = btc.iloc[:20]
    eth = eth.iloc[:20]
    assert eth.eq(0.0).all()

    result = build_buy_and_hold_sleeve_portfolio(
        {"BTC-USDT": btc, "ETH-USDT": eth},
        initial_weights={"BTC-USDT": 0.5, "ETH-USDT": 0.5},
        max_sleeve_weight=0.75,
        provenance=_fixture_provenance(metadata),
    )

    assert result.dependence["return_correlation"]["BTC-USDT"]["ETH-USDT"] is None
    paths = write_portfolio_risk_report(result, tmp_path)
    payload = paths["json"].read_text(encoding="utf-8")

    def reject_nonstandard_constant(value: str) -> None:
        raise AssertionError(f"non-standard JSON constant: {value}")

    saved = json.loads(payload, parse_constant=reject_nonstandard_constant)
    assert saved["dependence"]["return_correlation"]["BTC-USDT"]["ETH-USDT"] is None
    assert "NaN" not in payload
    assert "unavailable (zero variance)" in paths["markdown"].read_text(encoding="utf-8")


def test_programmatic_builder_rejects_missing_provenance_before_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    btc, eth, _ = _load_fixture_returns()

    def unexpected_metrics(*args: object, **kwargs: object) -> None:
        pytest.fail("portfolio metrics ran before provenance validation")

    monkeypatch.setattr(portfolio, "performance_metrics", unexpected_metrics)

    with pytest.raises(ValueError, match="missing required fields"):
        portfolio.build_buy_and_hold_sleeve_portfolio(
            {"BTC-USDT": btc, "ETH-USDT": eth},
            initial_weights={"BTC-USDT": 0.5, "ETH-USDT": 0.5},
            provenance={},
        )


def test_report_rejects_removed_provenance_before_creating_files(tmp_path) -> None:
    btc, eth, metadata = _load_fixture_returns()
    result = build_buy_and_hold_sleeve_portfolio(
        {"BTC-USDT": btc, "ETH-USDT": eth},
        initial_weights={"BTC-USDT": 0.5, "ETH-USDT": 0.5},
        provenance=_fixture_provenance(metadata),
    )
    result.data_summary["provenance"] = {}
    output_dir = tmp_path / "report"

    with pytest.raises(ValueError, match="missing required fields"):
        write_portfolio_risk_report(result, output_dir)

    assert not output_dir.exists()


def test_portfolio_rejects_implicit_timestamp_alignment() -> None:
    btc, eth, metadata = _load_fixture_returns()

    with pytest.raises(ValueError, match="indexes must match exactly"):
        build_buy_and_hold_sleeve_portfolio(
            {"BTC-USDT": btc, "ETH-USDT": eth.iloc[1:]},
            initial_weights={"BTC-USDT": 0.5, "ETH-USDT": 0.5},
            provenance=_fixture_provenance(metadata),
        )


def test_portfolio_rejects_shared_missing_daily_bar() -> None:
    btc, eth, metadata = _load_fixture_returns()
    missing_timestamp = btc.index[20]

    with pytest.raises(ValueError, match="exact daily cadence"):
        build_buy_and_hold_sleeve_portfolio(
            {
                "BTC-USDT": btc.drop(index=missing_timestamp),
                "ETH-USDT": eth.drop(index=missing_timestamp),
            },
            initial_weights={"BTC-USDT": 0.5, "ETH-USDT": 0.5},
            provenance=_fixture_provenance(metadata),
        )


def test_return_loader_rejects_hash_mismatch() -> None:
    with pytest.raises(ValueError, match="return file hash mismatch"):
        load_verified_return_csv(
            _FIXTURE_DIR / "btc_usdt_returns.csv",
            expected_sha256="0" * 64,
        )


def test_return_loader_rejects_timezone_naive_timestamp(tmp_path) -> None:
    source = _FIXTURE_DIR / "btc_usdt_returns.csv"
    altered = tmp_path / source.name
    contents = source.read_text(encoding="utf-8")
    altered.write_text(
        contents.replace("2020-01-11 00:00:00+00:00", "2020-01-11 00:00:00", 1),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="explicit timezone information"):
        load_verified_return_csv(altered, expected_sha256=file_sha256(altered))


def test_return_loader_rejects_daily_rows_not_anchored_to_midnight_utc(tmp_path) -> None:
    source = _FIXTURE_DIR / "btc_usdt_returns.csv"
    altered = tmp_path / source.name
    altered.write_text(
        source.read_text(encoding="utf-8").replace("+00:00", "-05:00"),
        encoding="utf-8",
    )
    shifted = pd.DatetimeIndex(pd.to_datetime(pd.read_csv(altered)["timestamp"], utc=True))
    assert shifted[0].hour == 5
    assert bool(((shifted[1:] - shifted[:-1]) == pd.Timedelta(days=1)).all())

    with pytest.raises(ValueError, match="midnight UTC"):
        load_verified_return_csv(altered, expected_sha256=file_sha256(altered))


def test_real_sleeve_drift_can_fail_a_tighter_concentration_limit() -> None:
    btc, eth, metadata = _load_fixture_returns()
    result = build_buy_and_hold_sleeve_portfolio(
        {"BTC-USDT": btc, "ETH-USDT": eth},
        initial_weights={"BTC-USDT": 0.5, "ETH-USDT": 0.5},
        max_sleeve_weight=0.505,
        provenance=_fixture_provenance(metadata),
    )

    assert result.concentration["breach_observations"] > 0
    assert result.concentration["passes"] is False
    assert result.risk_status.startswith("reject:")


def test_cli_rejects_missing_provenance_before_loading_returns(monkeypatch) -> None:
    def unexpected_load(*args: object, **kwargs: object) -> pd.Series:
        pytest.fail("return files must not be loaded before provenance validation")

    monkeypatch.setattr(run_portfolio_risk, "load_verified_return_csv", unexpected_load)

    with pytest.raises(SystemExit) as error:
        run_portfolio_risk.main(
            [
                "--btc-returns",
                "missing-btc.csv",
                "--eth-returns",
                "missing-eth.csv",
                "--btc-sha256",
                "1" * 64,
                "--eth-sha256",
                "2" * 64,
            ]
        )

    assert error.value.code == 2


def test_cli_rejects_malformed_provenance_before_loading_returns(monkeypatch) -> None:
    def unexpected_load(*args: object, **kwargs: object) -> pd.Series:
        pytest.fail("return files must not be loaded before provenance validation")

    monkeypatch.setattr(run_portfolio_risk, "load_verified_return_csv", unexpected_load)

    with pytest.raises(SystemExit) as error:
        run_portfolio_risk.main(
            [
                "--btc-returns",
                "missing-btc.csv",
                "--eth-returns",
                "missing-eth.csv",
                "--btc-sha256",
                "1" * 64,
                "--eth-sha256",
                "2" * 64,
                "--provider",
                "OKX",
                "--market-type",
                "spot",
                "--timeframe",
                "1Dutc",
                "--source-workflow-run",
                "29841895366",
                "--source-artifact-id",
                "8499721759",
                "--source-artifact-name",
                "quant-research-51",
                "--source-artifact-sha256",
                "not-a-sha256",
                "--source-head-sha",
                "4c02eccac3d6d81139c73d0b64bb5067756dac93",
            ]
        )

    assert error.value.code == 2
