"""GPT Quant Lab: reproducible quantitative-research primitives."""

from .backtest import BacktestResult, run_backtest
from .config import StrategyConfig
from .data import load_price_csv, validate_prices
from .metrics import performance_metrics
from .okx import (
    OKXCandleSnapshot,
    fetch_okx_history_candles,
    parse_okx_candle_rows,
    write_okx_snapshot,
)
from .okx_live import (
    OKXCompletedBarCutoff,
    OKXServerTimeSample,
    build_okx_completed_bar_cutoff,
    sample_okx_server_time,
)
from .portfolio import (
    PortfolioRiskResult,
    build_buy_and_hold_sleeve_portfolio,
    load_verified_return_csv,
    write_portfolio_risk_report,
)
from .reproducibility import (
    append_experiment_manifest,
    build_experiment_manifest_entry,
    canonical_json_sha256,
    file_sha256,
    resolve_git_commit,
)
from .research import ResearchResult, run_holdout_research
from .research_report import write_research_report
from .walk_forward import WalkForwardResult, run_walk_forward_research
from .walk_forward_report import write_walk_forward_report

__all__ = [
    "BacktestResult",
    "OKXCandleSnapshot",
    "OKXCompletedBarCutoff",
    "OKXServerTimeSample",
    "PortfolioRiskResult",
    "ResearchResult",
    "StrategyConfig",
    "WalkForwardResult",
    "append_experiment_manifest",
    "build_buy_and_hold_sleeve_portfolio",
    "build_experiment_manifest_entry",
    "build_okx_completed_bar_cutoff",
    "canonical_json_sha256",
    "fetch_okx_history_candles",
    "file_sha256",
    "load_price_csv",
    "load_verified_return_csv",
    "parse_okx_candle_rows",
    "performance_metrics",
    "resolve_git_commit",
    "run_backtest",
    "run_holdout_research",
    "run_walk_forward_research",
    "sample_okx_server_time",
    "validate_prices",
    "write_okx_snapshot",
    "write_portfolio_risk_report",
    "write_research_report",
    "write_walk_forward_report",
]
