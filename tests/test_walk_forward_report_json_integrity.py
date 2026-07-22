from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

from gpt_quant.metrics import performance_metrics

_REPOSITORY_ROOT = Path(__file__).parents[1]
_VERIFIER = _REPOSITORY_ROOT / "scripts" / "verify_walk_forward_metrics.py"
_FIXTURE = (
    Path(__file__).parent / "fixtures" / "okx" / "btc-usdt-1dutc" / "candles.csv"
)


def test_verifier_rejects_duplicate_report_object_keys(tmp_path: Path) -> None:
    candles = pd.read_csv(_FIXTURE)
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
    canonical = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ambiguous = canonical.replace(
        '"annualization": 365',
        '"annualization": 1,\n        "annualization": 365',
        1,
    )
    assert ambiguous != canonical

    report_path = tmp_path / "walk_forward.json"
    returns_path = tmp_path / "walk_forward_returns.csv"
    report_path.write_text(ambiguous, encoding="utf-8")
    frame.to_csv(returns_path, index=False)

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
    assert "report JSON contains duplicate object key 'annualization'" in completed.stderr
