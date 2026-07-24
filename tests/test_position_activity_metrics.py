from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from gpt_quant.metrics import performance_metrics

_FIXTURE_DIR = (
    Path(__file__).parent
    / "fixtures"
    / "okx"
    / "btc-usdt-1h-position-activity-20230712-20230718"
)
_RETURNS_PATH = _FIXTURE_DIR / "returns.csv"
_METADATA_PATH = _FIXTURE_DIR / "metadata.json"


def _load_real_okx_frame() -> pd.DataFrame:
    metadata = json.loads(_METADATA_PATH.read_text(encoding="utf-8"))
    assert metadata["provider"] == "OKX"
    assert metadata["instrument_id"] == "BTC-USDT"
    assert metadata["bar"] == "1H"
    assert metadata["source_workflow_run_id"] == 30064074036
    assert metadata["source_artifact_id"] == 8585638085
    assert metadata["source_head_sha"] == "09baca05803bfcee8f0083b88c002925131d795e"
    assert (
        hashlib.sha256(_RETURNS_PATH.read_bytes()).hexdigest()
        == metadata["fixture_sha256"]
    )

    frame = pd.read_csv(_RETURNS_PATH)
    timestamps = pd.to_datetime(frame.pop("timestamp"), utc=True, errors="raise")
    frame.index = pd.DatetimeIndex(timestamps, name="timestamp")
    assert len(frame) == metadata["observations"]
    assert frame.index[0].isoformat() == metadata["start"]
    assert frame.index[-1].isoformat() == metadata["end"]
    assert frame.index.to_series().diff().iloc[1:].eq(pd.Timedelta(hours=1)).all()
    return frame


def test_real_okx_position_path_exposes_rebalances_episodes_and_holding_periods(
) -> None:
    metrics = performance_metrics(_load_real_okx_frame(), annualization=8760)

    assert metrics["target_position_turnover_sum"] == pytest.approx(0.9569747341067639)
    assert metrics["target_position_rebalance_count"] == 87
    assert metrics["annualized_target_position_rebalance_count"] == pytest.approx(
        6048.571428571428
    )
    assert metrics["position_entry_count"] == 10
    assert metrics["position_exit_count"] == 10
    assert metrics["position_episode_count"] == 10
    assert metrics["annualized_position_episode_count"] == pytest.approx(
        695.2380952380952
    )
    assert metrics["completed_position_episode_count"] == 10
    assert metrics["open_position_episode_count"] == 0
    assert metrics["active_bar_count"] == 77
    assert metrics["active_bar_ratio"] == pytest.approx(77 / 126)
    assert metrics["mean_completed_holding_bars"] == pytest.approx(7.7)
    assert metrics["median_completed_holding_bars"] == pytest.approx(3.0)
    assert metrics["max_completed_holding_bars"] == 46
    assert metrics["current_holding_bars"] == 0
    assert metrics["completed_episode_win_count"] == 2
    assert metrics["completed_episode_loss_count"] == 8
    assert metrics["completed_episode_flat_count"] == 0
    assert metrics["completed_episode_hit_rate"] == pytest.approx(0.2)
    assert metrics["completed_episode_profit_factor"] == pytest.approx(
        0.1685676470610419
    )
    assert metrics["completed_episode_profit_factor_defined"] == 1
    assert metrics["bar_hit_rate"] == pytest.approx(0.38961038961038963)
    assert metrics["hit_rate"] == pytest.approx(0.3448275862068966)
    assert metrics["average_turnover_per_rebalance"] == pytest.approx(
        0.010999709587434068
    )
    assert metrics["exchange_fee_per_rebalance"] == pytest.approx(
        5.499854793717057e-06
    )


def test_real_okx_open_episode_is_reported_without_claiming_a_completed_trade() -> None:
    frame = _load_real_okx_frame().iloc[:-4]
    metrics = performance_metrics(frame, annualization=8760)

    assert metrics["position_episode_count"] == 10
    assert metrics["completed_position_episode_count"] == 9
    assert metrics["open_position_episode_count"] == 1
    assert metrics["position_exit_count"] == 9
    assert metrics["current_holding_bars"] == 46


def test_real_okx_activity_metrics_reject_negative_fee_only_diagnostics() -> None:
    frame = _load_real_okx_frame().drop(columns=["asset_return", "gross_strategy_return"])
    positive_fees = frame["trading_cost"] > 0.0
    first_fee_timestamp = positive_fees[positive_fees].index[0]
    frame.loc[first_fee_timestamp, "trading_cost"] *= -1.0

    with pytest.raises(ValueError, match="trading_cost must be non-negative"):
        performance_metrics(frame, annualization=8760)


def test_walk_forward_report_persists_activity_diagnostics_from_real_okx_prices(
    tmp_path: Path,
) -> None:
    from gpt_quant import StrategyConfig, run_walk_forward_research
    from gpt_quant.walk_forward_report import write_walk_forward_report
    from gpt_quant.walk_forward_verify import verify_walk_forward_report

    prices = _load_real_okx_frame()["close"]
    result = run_walk_forward_research(
        prices,
        base_config=StrategyConfig(
            momentum_lookback=24,
            reversal_lookback=3,
            volatility_lookback=12,
            target_volatility=0.5,
            min_position=0.0,
            transaction_cost_bps=5.0,
            annualization=8760,
        ),
        momentum_lookbacks=[24],
        reversal_lookbacks=[3],
        trend_weights=[0.7],
        selection_bars=100,
        test_bars=20,
        cost_multipliers=[1.0],
        provenance={
            "provider": "OKX",
            "instrument_id": "BTC-USDT",
            "bar": "1H",
            "source_artifact_id": 8585638085,
        },
    )

    paths = write_walk_forward_report(result, tmp_path)
    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    markdown = paths["markdown"].read_text(encoding="utf-8")

    assert payload["settings"]["cost_multipliers"] == [1.0]
    assert set(payload["cost_stress_metrics"]) == {"1x"}
    for key in (
        "target_position_turnover_sum",
        "target_position_rebalance_count",
        "annualized_target_position_rebalance_count",
        "position_episode_count",
        "annualized_position_episode_count",
        "completed_position_episode_count",
        "mean_completed_holding_bars",
        "completed_episode_hit_rate",
        "completed_episode_profit_factor",
        "average_turnover_per_rebalance",
    ):
        assert payload["aggregate_metrics"][key] == result.aggregate_metrics[key]
    assert "## Target-position activity diagnostics" in markdown
    assert "not submitted-order or fill counts" in markdown
    assert (
        "not broker order, queue, cancellation, partial-fill or fill counts" in markdown
    )

    verification = verify_walk_forward_report(tmp_path, tolerance=1e-10)
    assert verification["status"] == "passed"
    assert verification["transaction_cost_bps"] == 5.0
