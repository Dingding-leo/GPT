# Prospective frozen-strategy checkpoint — 2026-08-08 11:15 UTC

Advance the immutable `simple_trend_long_cash_2160h_next_open` policy through the next fully completed anonymous public OKX SPOT 1H payoff endpoint using the inherited frozen runner and workflow unchanged from the immediately preceding evidence head.

Hard boundary remains unchanged:

- BTC-USDT and ETH-USDT are evaluated independently using only each instrument's own lagged completed 1H history;
- signal rule is unchanged: 2,160H endpoint trend, long/cash only, next-open execution;
- exactly 5 bps one-way modeled fees on position transitions;
- no cross-sectional ranking or selection, current relative rank, top-N rotation, pairs/spreads, cointegration/statistical arbitrage, market-neutral long-short construction, or post-hoc market filtering;
- no credentials, private endpoints, accounts, balances, orders, enabled adapters, leverage, funds, synthetic data, non-1H inputs, or 15m;
- no threshold, horizon, cadence, sizing, hysteresis, or other policy mutation without completed preregistered training authority;
- paper/live authority remains false.

This branch changes no strategy logic. The pull-request workflow must publish fresh prospective strategy evidence, update the immutable scorecard, diagnose the predeclared E2160-margin drift discrepancy, and emit a machine-readable verdict. Evidence-only; close without merge after exact-head artifact inspection.
