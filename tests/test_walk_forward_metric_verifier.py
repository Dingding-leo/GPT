from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from gpt_quant.metrics import performance_metrics

_REPOSITORY_ROOT = Path(__file__).parents[1]
_VERIFIER = _REPOSITORY_ROOT / "scripts" / "verify_walk_forward_metrics.py"
_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "okx" / "btc-usdt-1dutc"
_CANDLES = _FIXTURE_ROOT / "candles.csv"
_METADATA = _FIXTURE_ROOT / "metadata.json"
_SELECTION_BARS = 1


def _real_fixture_frames() -> tuple[dict[str, object], pd.DataFrame, pd.DataFrame]:
    metadata = json.loads(_METADATA.read_text(encoding="utf-8"))
    candles = pd.read_csv(_CANDLES)
    timestamps = pd.to_datetime(candles["timestamp"], utc=True, errors="raise")
    close = pd.to_numeric(candles["close"], errors="raise").astype(float)
    asset_return = close.pct_change().fillna(0.0)
    position = (asset_return.shift(1).fillna(0.0) > 0.0).astype(float)
    turnover = position.diff().abs().fillna(position.abs())
    trading_cost = turnover * 10.0 / 10_000.0
    strategy_return = position * asset_return - trading_cost
    full_frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "asset_return": asset_return,
            "position": position,
            "turnover": turnover,
            "trading_cost": trading_cost,
            "strategy_return": strategy_return,
            "nav": (1.0 + strategy_return).cumprod(),
        }
    )
    evaluation_frame = full_frame.iloc[_SELECTION_BARS:].copy()
    return metadata, full_frame, evaluation_frame


def _persist_real_fixture_result(tmp_path: Path) -> tuple[Path, Path]:
    metadata, full_frame, frame = _real_fixture_frames()
    timestamps = pd.to_datetime(full_frame["timestamp"], utc=True, errors="raise")
    evaluation_timestamps = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
    metrics = performance_metrics(frame, annualization=365)
    report = {
        "settings": {
            "selection_bars": _SELECTION_BARS,
            "base_config": {"annualization": 365},
        },
        "data_summary": {
            "observations": len(full_frame),
            "start": timestamps.iloc[0].isoformat(),
            "end": timestamps.iloc[-1].isoformat(),
            "evaluation_start": evaluation_timestamps.iloc[0].isoformat(),
            "evaluation_end": evaluation_timestamps.iloc[-1].isoformat(),
            "unscored_tail_bars": 0,
            "provenance": {
                "provider": metadata["provider"],
                "instrument_id": metadata["instrument_id"],
                "bar": metadata["bar"],
                "normalized_csv_sha256": metadata["fixture_normalized_csv_sha256"],
            },
        },
        "aggregate_metrics": metrics,
    }
    report_path = tmp_path / "walk_forward.json"
    returns_path = tmp_path / "walk_forward_returns.csv"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    frame.to_csv(returns_path, index=False)
    return report_path, returns_path


def _persist_cash_only_real_fixture_result(tmp_path: Path) -> tuple[Path, pd.DataFrame]:
    candles = pd.read_csv(_CANDLES)
    timestamps = pd.to_datetime(candles["timestamp"], utc=True, errors="raise")
    close = pd.to_numeric(candles["close"], errors="raise").astype(float)
    asset_return = close.pct_change().fillna(0.0)
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "asset_return": asset_return,
            "position": 0.0,
            "turnover": 0.0,
            "trading_cost": 0.0,
            "strategy_return": 0.0,
            "nav": 1.0,
        }
    )
    report = {
        "settings": {"base_config": {"annualization": 365}},
        "data_summary": {
            "evaluation_start": timestamps.iloc[0].isoformat(),
            "evaluation_end": timestamps.iloc[-1].isoformat(),
        },
        "aggregate_metrics": performance_metrics(frame, annualization=365),
    }
    report_path = tmp_path / "walk_forward.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report_path, frame


def _run_verifier(report_path: Path, returns_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(_VERIFIER),
            "--report-json",
            str(report_path),
            "--returns-csv",
            str(returns_path),
        ],
        cwd=_REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_verifier_recomputes_metrics_and_equity_curve_from_real_okx_fixture(
    tmp_path: Path,
) -> None:
    report_path, returns_path = _persist_real_fixture_result(tmp_path)

    completed = _run_verifier(report_path, returns_path)

    assert completed.returncode == 0, completed.stderr
    assert "observations=4" in completed.stdout
    assert "aggregate_metrics=verified" in completed.stdout
    assert "equity_curve=verified" in completed.stdout


@pytest.mark.parametrize("missing_column", ["turnover", "position", "trading_cost"])
def test_verifier_requires_every_metric_input_even_when_reported_value_is_zero(
    tmp_path: Path,
    missing_column: str,
) -> None:
    report_path, frame = _persist_cash_only_real_fixture_result(tmp_path)
    returns_path = tmp_path / "walk_forward_returns.csv"
    frame.drop(columns=missing_column).to_csv(returns_path, index=False)

    completed = _run_verifier(report_path, returns_path)

    assert completed.returncode == 1
    assert "returns CSV is missing required columns" in completed.stderr
    assert missing_column in completed.stderr


def test_verifier_rejects_duplicate_metric_column_names(tmp_path: Path) -> None:
    report_path, returns_path = _persist_real_fixture_result(tmp_path)
    frame = pd.read_csv(returns_path)
    duplicated = pd.concat([frame, frame[["strategy_return"]]], axis=1)
    duplicated.to_csv(returns_path, index=False)

    completed = _run_verifier(report_path, returns_path)

    assert completed.returncode == 1
    assert "returns CSV contains duplicate column names: ['strategy_return']" in completed.stderr


def test_verifier_rejects_timezone_naive_return_timestamps(tmp_path: Path) -> None:
    report_path, returns_path = _persist_real_fixture_result(tmp_path)
    frame = pd.read_csv(returns_path)
    timestamps = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
    frame["timestamp"] = timestamps.dt.strftime("%Y-%m-%d %H:%M:%S")
    frame.to_csv(returns_path, index=False)

    completed = _run_verifier(report_path, returns_path)

    assert completed.returncode == 1
    assert "timestamps must contain explicit timezone information" in completed.stderr


def test_verifier_rejects_missing_declared_1dutc_interval(tmp_path: Path) -> None:
    report_path, returns_path = _persist_real_fixture_result(tmp_path)
    frame = pd.read_csv(returns_path)
    frame.drop(index=2).to_csv(returns_path, index=False)

    completed = _run_verifier(report_path, returns_path)

    assert completed.returncode == 1
    assert "timestamps must have exact 1Dutc cadence" in completed.stderr


def test_verifier_rejects_inconsistent_declared_source_coverage(tmp_path: Path) -> None:
    report_path, returns_path = _persist_real_fixture_result(tmp_path)
    valid_report = json.loads(report_path.read_text(encoding="utf-8"))
    mutations = {
        "observation-count": (
            "data_summary.observations does not match selection, evaluation, and tail bars",
            lambda report: report["data_summary"].__setitem__(
                "observations", report["data_summary"]["observations"] + 1
            ),
        ),
        "source-start": (
            "data_summary source boundaries do not match declared 1Dutc coverage",
            lambda report: report["data_summary"].__setitem__(
                "start", report["data_summary"]["evaluation_start"]
            ),
        ),
        "unscored-tail": (
            "data_summary.observations does not match selection, evaluation, and tail bars",
            lambda report: report["data_summary"].__setitem__("unscored_tail_bars", 1),
        ),
    }

    for name, (expected_error, mutate) in mutations.items():
        report = json.loads(json.dumps(valid_report))
        mutate(report)
        mutated_path = tmp_path / f"walk_forward-{name}.json"
        mutated_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        completed = _run_verifier(mutated_path, returns_path)

        assert completed.returncode == 1
        assert expected_error in completed.stderr


def test_verifier_rejects_persisted_metric_drift(tmp_path: Path) -> None:
    report_path, returns_path = _persist_real_fixture_result(tmp_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["aggregate_metrics"]["sharpe"] += 0.01
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    completed = _run_verifier(report_path, returns_path)

    assert completed.returncode == 1
    assert "aggregate_metrics.sharpe mismatch" in completed.stderr


@pytest.mark.parametrize("invalid_value", [False, "0.0"])
def test_verifier_rejects_coerced_aggregate_metric_scalars(
    tmp_path: Path,
    invalid_value: object,
) -> None:
    report_path, frame = _persist_cash_only_real_fixture_result(tmp_path)
    returns_path = tmp_path / "walk_forward_returns.csv"
    frame.to_csv(returns_path, index=False)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["aggregate_metrics"]["sharpe"] = invalid_value
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    completed = _run_verifier(report_path, returns_path)

    assert completed.returncode == 1
    assert "aggregate_metrics.sharpe must be a JSON number" in completed.stderr
