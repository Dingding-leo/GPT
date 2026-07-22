from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

from gpt_quant.metrics import performance_metrics

_REPOSITORY_ROOT = Path(__file__).parents[1]
_VERIFIER = _REPOSITORY_ROOT / "scripts" / "verify_walk_forward_metrics.py"
_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "okx" / "btc-usdt-1dutc"
_CANDLES = _FIXTURE_ROOT / "candles.csv"


def test_verifier_rejects_persisted_nav_drift_from_real_okx_returns(
    tmp_path: Path,
) -> None:
    candles = pd.read_csv(_CANDLES)
    timestamps = pd.to_datetime(candles["timestamp"], utc=True, errors="raise")
    close = pd.to_numeric(candles["close"], errors="raise").astype(float)
    asset_return = close.pct_change().fillna(0.0)
    position = (asset_return.shift(1).fillna(0.0) > 0.0).astype(float)
    turnover = position.diff().abs().fillna(position.abs())
    trading_cost = turnover * 10.0 / 10_000.0
    strategy_return = position * asset_return - trading_cost
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "position": position,
            "turnover": turnover,
            "trading_cost": trading_cost,
            "strategy_return": strategy_return,
            "nav": (1.0 + strategy_return).cumprod(),
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
    returns_path = tmp_path / "walk_forward_returns.csv"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    altered = frame.copy()
    altered.loc[altered.index[-1], "nav"] += 0.01
    altered.to_csv(returns_path, index=False)

    completed = subprocess.run(
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

    assert completed.returncode == 1
    assert "persisted nav does not match compounded strategy_return" in completed.stderr
