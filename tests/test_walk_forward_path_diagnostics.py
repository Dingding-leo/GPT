from __future__ import annotations

import calendar
import json
from pathlib import Path

import pandas as pd
import pytest

from gpt_quant import StrategyConfig, run_walk_forward_research
from gpt_quant.walk_forward_diagnostics import walk_forward_path_diagnostics
from gpt_quant.walk_forward_report import write_walk_forward_report


def _real_okx_result(prices: pd.Series):
    return run_walk_forward_research(
        prices.iloc[:500],
        base_config=StrategyConfig(
            min_position=0.0,
            transaction_cost_bps=5.0,
            annualization=365,
        ),
        momentum_lookbacks=[21],
        reversal_lookbacks=[3],
        trend_weights=[0.7],
        selection_bars=300,
        test_bars=100,
        cost_multipliers=[1.0, 1.5, 2.0, 3.0],
        provenance={
            "provider": "OKX",
            "instrument_id": "BTC-USDT",
            "bar": "1Dutc",
        },
    )


def _path_diagnostics(frame: pd.DataFrame) -> dict[str, object]:
    return walk_forward_path_diagnostics(
        frame,
        annualization=365,
        minimum_position=0.0,
        maximum_absolute_position=1.0,
    )


def _assert_diagnostics_equal(actual: object, expected: object) -> None:
    if isinstance(expected, dict):
        assert isinstance(actual, dict)
        assert actual.keys() == expected.keys()
        for key, expected_value in expected.items():
            _assert_diagnostics_equal(actual[key], expected_value)
    elif isinstance(expected, list):
        assert isinstance(actual, list)
        assert len(actual) == len(expected)
        for actual_value, expected_value in zip(actual, expected, strict=True):
            _assert_diagnostics_equal(actual_value, expected_value)
    elif isinstance(expected, float):
        assert actual == pytest.approx(expected, abs=1e-12)
    else:
        assert actual == expected


def _independent_calendar_records(
    frame: pd.DataFrame,
    *,
    period: str,
) -> list[dict[str, object]]:
    index = frame.index.tz_convert("UTC")
    labels = index.strftime("%Y-%m" if period == "month" else "%Y")
    records: list[dict[str, object]] = []
    for label in dict.fromkeys(labels):
        mask = labels == label
        observed = index[mask]
        returns = frame.loc[mask, "strategy_return"]
        if period == "month":
            year, month = (int(part) for part in label.split("-"))
            start = pd.Timestamp(year=year, month=month, day=1, tz="UTC")
            end = pd.Timestamp(
                year=year,
                month=month,
                day=calendar.monthrange(year, month)[1],
                tz="UTC",
            )
        else:
            year = int(label)
            start = pd.Timestamp(year=year, month=1, day=1, tz="UTC")
            end = pd.Timestamp(year=year, month=12, day=31, tz="UTC")
        complete = (
            len(observed) == int((end - start).days) + 1
            and observed.equals(observed.normalize())
            and observed[0] == start
            and observed[-1] == end
            and observed.to_series().diff().dropna().eq(pd.Timedelta(days=1)).all()
        )
        net_total_return = float((1.0 + returns).prod() - 1.0)
        if net_total_return > 1e-12:
            classification = "profitable"
        elif net_total_return < -1e-12:
            classification = "losing"
        else:
            classification = "flat"
        records.append(
            {
                "period": label,
                "coverage": "complete" if complete else "partial",
                "observations": len(observed),
                "evaluation_start": observed[0].isoformat(),
                "evaluation_end": observed[-1].isoformat(),
                "net_total_return": net_total_return,
                "classification": classification,
            }
        )
    return records


def test_report_persists_recomputable_position_path_diagnostics(
    btc_usdt_prices: pd.Series,
    tmp_path: Path,
) -> None:
    result = _real_okx_result(btc_usdt_prices)
    expected = _path_diagnostics(result.combined_frame)

    paths = write_walk_forward_report(result, tmp_path)
    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    _assert_diagnostics_equal(payload["path_diagnostics"], expected)

    persisted = pd.read_csv(paths["returns"], parse_dates=["timestamp"]).set_index("timestamp")
    recomputed = _path_diagnostics(persisted)
    _assert_diagnostics_equal(recomputed, expected)

    assert expected["observations"] == len(result.combined_frame)
    assert expected["position_limit_passes"] is True
    assert expected["declared_minimum_position"] == 0.0
    assert expected["declared_maximum_absolute_position"] == 1.0
    assert expected["total_absolute_turnover"] == pytest.approx(
        result.combined_frame["turnover"].sum(),
        abs=1e-12,
    )
    assert expected["position_adjustment_count"] == int(
        (result.combined_frame["turnover"] > 1e-12).sum()
    )
    assert expected["current_absolute_exposure"] == pytest.approx(
        abs(result.combined_frame["position"].iloc[-1]),
        abs=1e-12,
    )
    assert (
        expected["completed_holding_episode_count"] + expected["open_holding_episode_count"]
        == expected["holding_episode_count"]
    )

    expected_months = _independent_calendar_records(result.combined_frame, period="month")
    expected_years = _independent_calendar_records(result.combined_frame, period="year")
    _assert_diagnostics_equal(expected["calendar_months"], expected_months)
    _assert_diagnostics_equal(expected["calendar_years"], expected_years)
    assert expected["profitable_month_count"] + expected["losing_month_count"] + expected[
        "flat_month_count"
    ] == len(expected_months)
    assert expected["profitable_year_count"] + expected["losing_year_count"] + expected[
        "flat_year_count"
    ] == len(expected_years)
    assert expected["partial_month_labels"] == [
        record["period"] for record in expected_months if record["coverage"] == "partial"
    ]
    assert expected["partial_year_labels"] == [
        record["period"] for record in expected_years if record["coverage"] == "partial"
    ]

    markdown = paths["markdown"].read_text(encoding="utf-8")
    assert "## Position-path diagnostics" in markdown
    assert "Configured position limits pass" in markdown
    assert "Profitable / losing / flat UTC calendar months" in markdown
    assert "Partial UTC calendar years" in markdown
    assert "not exchange orders or fills" in markdown


def test_report_normalizes_previously_valid_naive_price_index_to_utc(
    btc_usdt_prices: pd.Series,
    tmp_path: Path,
) -> None:
    prices = btc_usdt_prices.copy()
    prices.index = prices.index.tz_localize(None)

    result = _real_okx_result(prices)
    paths = write_walk_forward_report(result, tmp_path)
    payload = json.loads(paths["json"].read_text(encoding="utf-8"))

    assert str(result.combined_frame.index.tz) == "UTC"
    assert payload["path_diagnostics"]["evaluation_start"].endswith("+00:00")
    assert payload["path_diagnostics"]["evaluation_end"].endswith("+00:00")


def test_position_path_diagnostics_reject_turnover_not_derived_from_position(
    btc_usdt_prices: pd.Series,
) -> None:
    result = _real_okx_result(btc_usdt_prices)
    corrupted = result.combined_frame.copy()
    corrupted.iloc[10, corrupted.columns.get_loc("turnover")] += 0.1

    with pytest.raises(ValueError, match="absolute position changes"):
        _path_diagnostics(corrupted)


@pytest.mark.parametrize("breaching_position", [1.05, -0.05])
def test_position_path_diagnostics_reject_configured_position_limit_breach(
    btc_usdt_prices: pd.Series,
    breaching_position: float,
) -> None:
    result = _real_okx_result(btc_usdt_prices)
    corrupted = result.combined_frame.copy()
    corrupted.iloc[10, corrupted.columns.get_loc("position")] = breaching_position
    corrupted["turnover"] = (
        corrupted["position"] - corrupted["position"].shift(1, fill_value=0.0)
    ).abs()

    with pytest.raises(ValueError, match="configured position limits"):
        _path_diagnostics(corrupted)
