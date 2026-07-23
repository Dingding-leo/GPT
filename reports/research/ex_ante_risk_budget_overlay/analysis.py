from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

MARKETS = ("BTC-USDT", "ETH-USDT")
RISK_BUDGETS = (0.15, 0.20, 0.25)
SELECTION_BARS = 730
ANNUALIZATION = 365
BASELINE_COST_BPS = 5.0
EXPECTED_HASHES = {
    "BTC-USDT": {
        "snapshot": "407aeba3d1ad4c8e8682a6a689c1c6327139f42bc7587aaae75c77fce047dec1",
        "returns": "04a0a5257d1e20f1eb88c70b8a0b010d21f0dc35ccb657ba39f14189e9f20790",
    },
    "ETH-USDT": {
        "snapshot": "842b4bbbb0ad7afbe2a1c9ee375443671d818a799266d5dc25cc6a548571ad7f",
        "returns": "4b69db4a44644a5f830e1518aca93356c0eeacf502dc00ba990bd992b9bd387f",
    },
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def estimate_fold_scale(selection_gross_returns: pd.Series, risk_budget: float) -> dict[str, float]:
    values = selection_gross_returns.to_numpy(dtype=float)
    if len(values) != SELECTION_BARS:
        raise ValueError(f"selection window must contain exactly {SELECTION_BARS} observations")
    if not np.isfinite(values).all():
        raise ValueError("selection gross returns must be finite")
    volatility = float(values.std(ddof=0) * math.sqrt(ANNUALIZATION))
    scale = 1.0 if volatility <= 0.0 else min(1.0, float(risk_budget) / volatility)
    return {
        "estimated_annualized_gross_strategy_volatility": volatility,
        "applied_scale": scale,
    }


def _load_prices(path: Path, expected_sha256: str) -> pd.Series:
    if file_sha256(path) != expected_sha256:
        raise ValueError(f"snapshot SHA-256 mismatch: {path}")
    frame = pd.read_csv(path)
    timestamps = pd.DatetimeIndex(pd.to_datetime(frame["timestamp"], utc=True, errors="raise"))
    close = pd.to_numeric(frame["close"], errors="raise")
    confirm = pd.to_numeric(frame["confirm"], errors="raise")
    if timestamps.has_duplicates or not timestamps.is_monotonic_increasing:
        raise ValueError("snapshot timestamps must be unique and increasing")
    if not bool(confirm.eq(1).all()) or (close <= 0.0).any():
        raise ValueError("snapshot must contain positive confirmed closes")
    return pd.Series(close.to_numpy(dtype=float), index=timestamps, name="close")


def _load_folds(path: Path) -> list[dict[str, Any]]:
    folds = json.loads(path.read_text(encoding="utf-8"))["folds"]
    if not isinstance(folds, list) or not folds:
        raise ValueError("walk-forward report must contain folds")
    return folds


def _selected_config(record: dict[str, Any]) -> Any:
    from gpt_quant import StrategyConfig

    selected = record["selected_parameters"]
    return StrategyConfig(
        momentum_lookback=int(selected["momentum_lookback"]),
        reversal_lookback=int(selected["reversal_lookback"]),
        trend_weight=float(selected["trend_weight"]),
        reversal_weight=1.0 - float(selected["trend_weight"]),
        volatility_lookback=30,
        target_volatility=0.50,
        max_abs_position=1.0,
        min_position=0.0,
        transaction_cost_bps=BASELINE_COST_BPS,
        annualization=ANNUALIZATION,
    )


def reconstruct_path(
    prices: pd.Series,
    folds: list[dict[str, Any]],
    risk_budget: float,
) -> pd.DataFrame:
    from gpt_quant import run_backtest

    pieces: list[pd.DataFrame] = []
    previous_position = 0.0
    for record in folds:
        frame = run_backtest(prices, _selected_config(record)).frame
        selection = frame.loc[record["selection_start"] : record["selection_end"]]
        scale = estimate_fold_scale(selection["gross_strategy_return"], risk_budget)[
            "applied_scale"
        ]
        test = frame.loc[record["test_start"] : record["test_end"]].copy()
        test["position"] = test["position"] * scale
        test["target_position"] = test["target_position"] * scale
        test["turnover"] = test["position"].diff().abs()
        test.iloc[0, test.columns.get_loc("turnover")] = abs(
            float(test["position"].iloc[0]) - previous_position
        )
        test["gross_strategy_return"] = test["position"] * test["asset_return"]
        test["trading_cost"] = test["turnover"] * BASELINE_COST_BPS / 10_000.0
        test["strategy_return"] = test["gross_strategy_return"] - test["trading_cost"]
        test["fold"] = int(record["fold"])
        pieces.append(test)
        previous_position = float(test["position"].iloc[-1])
    result = pd.concat(pieces).sort_index()
    if result.index.has_duplicates:
        raise ValueError("OOS folds must not overlap")
    return result


def _assert_close(observed: float | int, expected: float | int, label: str) -> None:
    if not math.isclose(float(observed), float(expected), rel_tol=0.0, abs_tol=1e-12):
        raise ValueError(f"{label} mismatch: expected {expected}, observed {observed}")


def validate_result(artifact_dir: Path, result: dict[str, Any]) -> None:
    from gpt_quant import performance_metrics

    for market in MARKETS:
        root = artifact_dir / market
        snapshot = root / "snapshot" / f"okx-{market}-1Dutc.csv"
        returns = root / "walk_forward_returns.csv"
        if file_sha256(returns) != EXPECTED_HASHES[market]["returns"]:
            raise ValueError(f"{market} return SHA-256 mismatch")
        prices = _load_prices(snapshot, EXPECTED_HASHES[market]["snapshot"])
        folds = _load_folds(root / "walk_forward.json")
        for budget in RISK_BUDGETS:
            label = f"{int(round(budget * 100))}pct"
            frame = reconstruct_path(prices, folds, budget)
            observed = performance_metrics(frame, annualization=ANNUALIZATION)
            expected = result["candidates"][label]["markets"][market]["metrics_5bps"]
            for metric in (
                "total_return",
                "cagr",
                "annualized_arithmetic_mean",
                "sharpe",
                "sortino",
                "calmar",
                "max_drawdown",
                "annualized_turnover",
                "average_abs_exposure",
                "exchange_fee_sum",
            ):
                _assert_close(observed[metric], expected[metric], f"{label} {market} {metric}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument(
        "--result",
        type=Path,
        default=Path(__file__).with_name("result.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = json.loads(args.result.read_text(encoding="utf-8"))
    validate_result(args.artifact_dir, result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
