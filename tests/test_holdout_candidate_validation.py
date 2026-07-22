from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import gpt_quant.research as research
from gpt_quant import StrategyConfig, run_holdout_research

_SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "run_research.py"
_SCRIPT_SPEC = importlib.util.spec_from_file_location("run_research", _SCRIPT_PATH)
if _SCRIPT_SPEC is None or _SCRIPT_SPEC.loader is None:
    raise RuntimeError(f"unable to load holdout research CLI from {_SCRIPT_PATH}")
run_research = importlib.util.module_from_spec(_SCRIPT_SPEC)
_SCRIPT_SPEC.loader.exec_module(run_research)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("momentum_lookbacks", 21.5, "momentum lookback candidates must be integers"),
        ("momentum_lookbacks", True, "momentum lookback candidates must be integers"),
        ("momentum_lookbacks", "21", "momentum lookback candidates must be integers"),
        ("momentum_lookbacks", 1, "momentum lookback candidates must be at least 2"),
        ("reversal_lookbacks", 3.5, "reversal lookback candidates must be integers"),
        ("reversal_lookbacks", False, "reversal lookback candidates must be integers"),
        ("reversal_lookbacks", "3", "reversal lookback candidates must be integers"),
        ("reversal_lookbacks", 0, "reversal lookback candidates must be at least 1"),
        ("trend_weights", "0.7", "trend weight candidates must be finite real numbers"),
        ("trend_weights", True, "trend weight candidates must be finite real numbers"),
        ("trend_weights", float("nan"), "trend weight candidates must be finite real numbers"),
        ("trend_weights", float("inf"), "trend weight candidates must be finite real numbers"),
        ("trend_weights", -0.1, "trend weights must be in \\[0, 1\\]"),
        ("trend_weights", 1.1, "trend weights must be in \\[0, 1\\]"),
    ],
)
def test_holdout_rejects_coerced_candidates_before_any_backtest(
    btc_usdt_prices: pd.Series,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
    message: str,
) -> None:
    def unexpected_backtest(*args: object, **kwargs: object) -> None:
        pytest.fail("candidate validation must finish before any backtest")

    monkeypatch.setattr(research, "run_backtest", unexpected_backtest)
    candidate_grid: dict[str, list[object]] = {
        "momentum_lookbacks": [21],
        "reversal_lookbacks": [3],
        "trend_weights": [0.7],
    }
    candidate_grid[field] = [candidate_grid[field][0], value]

    with pytest.raises(ValueError, match=message):
        run_holdout_research(
            btc_usdt_prices.iloc[:600],
            base_config=StrategyConfig(
                min_position=0.0,
                transaction_cost_bps=10.0,
                annualization=365,
            ),
            top_candidates=2,
            **candidate_grid,
        )


@pytest.mark.parametrize(
    "empty_field",
    ["momentum_lookbacks", "reversal_lookbacks", "trend_weights"],
)
def test_holdout_rejects_an_empty_candidate_dimension_before_any_backtest(
    btc_usdt_prices: pd.Series,
    monkeypatch: pytest.MonkeyPatch,
    empty_field: str,
) -> None:
    def unexpected_backtest(*args: object, **kwargs: object) -> None:
        pytest.fail("empty candidate validation must run before any backtest")

    monkeypatch.setattr(research, "run_backtest", unexpected_backtest)
    candidate_grid: dict[str, list[object]] = {
        "momentum_lookbacks": [21],
        "reversal_lookbacks": [3],
        "trend_weights": [0.7],
    }
    candidate_grid[empty_field] = []

    with pytest.raises(ValueError, match="candidate grid cannot be empty"):
        run_holdout_research(
            btc_usdt_prices.iloc[:600],
            base_config=StrategyConfig(
                min_position=0.0,
                transaction_cost_bps=10.0,
                annualization=365,
            ),
            top_candidates=1,
            **candidate_grid,
        )


@pytest.mark.parametrize("top_candidates", [0, -1, 1.5, True, "2"])
def test_holdout_rejects_invalid_top_candidate_count_before_any_backtest(
    btc_usdt_prices: pd.Series,
    monkeypatch: pytest.MonkeyPatch,
    top_candidates: object,
) -> None:
    def unexpected_backtest(*args: object, **kwargs: object) -> None:
        pytest.fail("top_candidates validation must run before any backtest")

    monkeypatch.setattr(research, "run_backtest", unexpected_backtest)

    with pytest.raises(ValueError, match="top_candidates must be a positive integer"):
        run_holdout_research(
            btc_usdt_prices.iloc[:600],
            base_config=StrategyConfig(
                min_position=0.0,
                transaction_cost_bps=10.0,
                annualization=365,
            ),
            momentum_lookbacks=[21],
            reversal_lookbacks=[3],
            trend_weights=[0.7],
            top_candidates=top_candidates,
        )


@pytest.mark.parametrize("field", ["validation_fraction", "holdout_fraction"])
@pytest.mark.parametrize(
    ("value", "message"),
    [
        (True, "must be a finite real number"),
        ("0.2", "must be a finite real number"),
        (float("nan"), "must be a finite real number"),
        (float("inf"), "must be a finite real number"),
        (0.049, "must be in \\[0.05, 0.40\\]"),
        (0.401, "must be in \\[0.05, 0.40\\]"),
    ],
)
def test_holdout_rejects_invalid_split_fraction_before_price_validation(
    btc_usdt_prices: pd.Series,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
    message: str,
) -> None:
    def unexpected_price_validation(*args: object, **kwargs: object) -> None:
        pytest.fail("split-fraction validation must run before price validation")

    monkeypatch.setattr(research, "validate_prices", unexpected_price_validation)
    fractions: dict[str, object] = {
        "validation_fraction": 0.20,
        "holdout_fraction": 0.20,
    }
    fractions[field] = value

    with pytest.raises(ValueError, match=rf"{field} {message}"):
        run_holdout_research(
            btc_usdt_prices.iloc[:600],
            base_config=StrategyConfig(
                min_position=0.0,
                transaction_cost_bps=10.0,
                annualization=365,
            ),
            momentum_lookbacks=[21],
            reversal_lookbacks=[3],
            trend_weights=[0.7],
            top_candidates=1,
            **fractions,
        )


def test_holdout_rejects_excessive_combined_split_before_price_validation(
    btc_usdt_prices: pd.Series,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_price_validation(*args: object, **kwargs: object) -> None:
        pytest.fail("combined split validation must run before price validation")

    monkeypatch.setattr(research, "validate_prices", unexpected_price_validation)

    with pytest.raises(ValueError, match="fractions leave too little history"):
        run_holdout_research(
            btc_usdt_prices.iloc[:600],
            base_config=StrategyConfig(
                min_position=0.0,
                transaction_cost_bps=10.0,
                annualization=365,
            ),
            momentum_lookbacks=[21],
            reversal_lookbacks=[3],
            trend_weights=[0.7],
            validation_fraction=0.40,
            holdout_fraction=0.40,
            top_candidates=1,
        )


def _cli_snapshot(btc_usdt_prices: pd.Series, tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        prices=btc_usdt_prices.iloc[:600],
        provider="OKX",
        market_type="spot",
        instrument_id="BTC-USDT",
        timeframe="1Dutc",
        manifest_path=tmp_path / "snapshot.json",
        data_sha256="0" * 64,
    )


def test_holdout_cli_does_not_coerce_top_candidate_count(
    btc_usdt_prices: pd.Series,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    snapshot = _cli_snapshot(btc_usdt_prices, tmp_path)
    monkeypatch.setattr(run_research, "load_verified_price_snapshot", lambda _: snapshot)
    monkeypatch.setattr(
        run_research,
        "load_json",
        lambda _: {
            "strategy": {
                "min_position": 0.0,
                "transaction_cost_bps": 10.0,
                "annualization": 365,
            },
            "search": {
                "momentum_lookbacks": [21],
                "reversal_lookbacks": [3],
                "trend_weights": [0.7],
                "top_candidates": "2",
            },
        },
    )

    def unexpected_price_validation(*args: object, **kwargs: object) -> None:
        pytest.fail("CLI control validation must run before price validation")

    monkeypatch.setattr(research, "validate_prices", unexpected_price_validation)
    output_dir = tmp_path / "report"

    with pytest.raises(ValueError, match="top_candidates must be a positive integer"):
        run_research.main(
            [
                "--snapshot-manifest",
                "unused-snapshot.json",
                "--config",
                "unused-config.json",
                "--output-dir",
                str(output_dir),
            ]
        )

    assert not output_dir.exists()


@pytest.mark.parametrize("field", ["validation_fraction", "holdout_fraction"])
def test_holdout_cli_does_not_coerce_split_fractions(
    btc_usdt_prices: pd.Series,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field: str,
) -> None:
    snapshot = _cli_snapshot(btc_usdt_prices, tmp_path)
    monkeypatch.setattr(run_research, "load_verified_price_snapshot", lambda _: snapshot)
    search: dict[str, object] = {
        "momentum_lookbacks": [21],
        "reversal_lookbacks": [3],
        "trend_weights": [0.7],
        "validation_fraction": 0.20,
        "holdout_fraction": 0.20,
        "top_candidates": 1,
    }
    search[field] = "0.2"
    monkeypatch.setattr(
        run_research,
        "load_json",
        lambda _: {
            "strategy": {
                "min_position": 0.0,
                "transaction_cost_bps": 10.0,
                "annualization": 365,
            },
            "search": search,
        },
    )

    def unexpected_price_validation(*args: object, **kwargs: object) -> None:
        pytest.fail("CLI split validation must run before price validation")

    monkeypatch.setattr(research, "validate_prices", unexpected_price_validation)
    output_dir = tmp_path / "report"

    with pytest.raises(ValueError, match=rf"{field} must be a finite real number"):
        run_research.main(
            [
                "--snapshot-manifest",
                "unused-snapshot.json",
                "--config",
                "unused-config.json",
                "--output-dir",
                str(output_dir),
            ]
        )

    assert not output_dir.exists()


def test_holdout_preserves_distinct_valid_trend_weights(
    btc_usdt_prices: pd.Series,
) -> None:
    declared_weights = [0.7, 0.70000000001]
    result = run_holdout_research(
        btc_usdt_prices.iloc[:600],
        base_config=StrategyConfig(
            min_position=0.0,
            transaction_cost_bps=10.0,
            annualization=365,
        ),
        momentum_lookbacks=[21],
        reversal_lookbacks=[3],
        trend_weights=declared_weights,
        top_candidates=2,
    )

    executed_weights = [entry["parameters"]["trend_weight"] for entry in result.candidate_ranking]
    assert result.candidates_tested == 2
    assert set(executed_weights) == set(declared_weights)
