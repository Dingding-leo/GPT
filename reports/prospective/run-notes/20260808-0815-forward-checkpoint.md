# Prospective forward checkpoint — 2026-08-08 08:15 UTC

Purpose: advance the immutable `simple_trend_long_cash_2160h_next_open` policy on the next complete anonymous public OKX SPOT 1H observation using the inherited exact frozen runner and workflow.

Hard boundary remains unchanged: BTC-USDT and ETH-USDT independently; own lagged completed 1H sequence only; exactly 5 bps one-way modeled fees; no cross-sectional selection, ranking, rotation, pairs/spreads, statistical arbitrage, market-neutral construction, current relative rank, post-hoc filtering, credentials, private endpoints, accounts, balances, orders, leverage, funds, enabled adapters, synthetic data, non-1H input, paper trading, or live trading.

This commit changes no strategy logic. It exists only to trigger exact-head evidence production for the next complete prospective observation and predeclared scorecard. No policy correction is authorized unless an already-completed preregistered training protocol explicitly permits it.
