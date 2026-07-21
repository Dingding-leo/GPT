"""GPT Quant Lab: reproducible quantitative-research primitives."""

from .backtest import BacktestResult, run_backtest
from .config import StrategyConfig
from .data import generate_regime_prices, load_price_csv, validate_prices
from .metrics import performance_metrics
from .research import ResearchResult, run_holdout_research, write_research_report

__all__ = [
    "BacktestResult",
    "ResearchResult",
    "StrategyConfig",
    "generate_regime_prices",
    "load_price_csv",
    "performance_metrics",
    "run_backtest",
    "run_holdout_research",
    "validate_prices",
    "write_research_report",
]
