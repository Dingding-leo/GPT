"""GPT Quant Lab: reproducible quantitative-research primitives."""

from .backtest import BacktestResult, run_backtest
from .config import StrategyConfig
from .data import generate_regime_prices, load_price_csv, validate_prices
from .metrics import performance_metrics
from .okx import (
    OKXCandleSnapshot,
    fetch_okx_history_candles,
    parse_okx_candle_rows,
    write_okx_snapshot,
)
from .research import ResearchResult, run_holdout_research, write_research_report
from .walk_forward import WalkForwardResult, run_walk_forward_research
from .walk_forward_report import write_walk_forward_report

__all__ = [
    "BacktestResult",
    "OKXCandleSnapshot",
    "ResearchResult",
    "StrategyConfig",
    "WalkForwardResult",
    "fetch_okx_history_candles",
    "generate_regime_prices",
    "load_price_csv",
    "parse_okx_candle_rows",
    "performance_metrics",
    "run_backtest",
    "run_holdout_research",
    "run_walk_forward_research",
    "validate_prices",
    "write_okx_snapshot",
    "write_research_report",
    "write_walk_forward_report",
]
