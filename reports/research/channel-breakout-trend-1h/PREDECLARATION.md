# Predeclaration — 1h Channel Breakout Trend Architecture

## Hypothesis

A fixed long/cash `1H` channel-breakout architecture clears every retrospective architecture-freeze gate in both BTC-USDT and ETH-USDT at exactly 5 bps one-way and is eligible for prospective post-only paper evaluation.

Canonical signature:

`channel-breakout-trend-1h-v1|markets=BTC-USDT,ETH-USDT|provider=OKX-spot|bar=1H|source=portable-canonical-1h-artifacts|architecture=24h-donchian-breakout-with-168h-positive-trend-regime|entry=close-above-prior-24h-high-and-168h-log-return-positive|exit=close-below-prior-24h-low-or-regime-nonpositive|size=50pct-annualized-vol-target-using-168h-realized-vol|max-position=1|fee=5bps-one-way|execution=one-complete-bar-delay|evaluation=2023-07-01T00:00Z..2026-06-14T23:00Z|fold=2160h|bootstrap=paired-noncircular-168h-blocks-2000-resamples-95pct|architecture-candidate-count=1`

## Economic rationale

A causal price-channel breakout seeks persistent intraday trends only after price proves strength beyond the previous day’s range. The 168-hour positive-return regime filters countertrend breakouts, while volatility targeting limits exposure during unstable periods. The architecture is materially different from the rejected fold-local trend/reversal selector, dual-horizon trend confirmation, and pullback-recovery state machine. It is long/cash and can later be evaluated with a post-only entry workflow without embedding maker fills, spread, slippage, impact, latency, no-fill, partial-fill, timeout, or adverse-selection assumptions in PnL.

## Fixed implementation

- Data: completed public OKX spot `1H` candles from the portable canonical BTC-USDT and ETH-USDT artifacts.
- Evaluation: the existing strict OOS window of 25,920 hours, 2023-07-01 00:00 UTC through 2026-06-14 23:00 UTC.
- Entry signal at close `t`: `close_t` is strictly above the maximum high over bars `t-24` through `t-1`, and the 168-hour close-to-close log return is positive.
- Exit signal at close `t`: `close_t` is strictly below the minimum low over bars `t-24` through `t-1`, or the 168-hour log return is non-positive.
- State: remain long between entry and exit signals; otherwise cash.
- Position size: while long, `clip(0.50 / annualized_realized_vol_168h, 0, 1)`, using hourly log-return sample volatility annualized by `sqrt(8760)`.
- Causality: target computed at close `t` becomes executed position for return `t+1`; the first OOS observation starts from cash.
- Economics: exactly 5 bps per unit absolute position turnover. No other friction is included in PnL.
- Candidate count: exactly one architecture candidate.

## Predeclared robustness paths

The following are neighbourhood checks only and are not searched candidates:

1. 12-hour channel, 168-hour regime.
2. 36-hour channel, 168-hour regime.
3. 24-hour channel, 120-hour regime and volatility window.
4. 24-hour channel, 240-hour regime and volatility window.

## Retrospective pass gates

The architecture passes only if all conditions hold in both markets:

1. Net total return is positive and Sharpe is at least 0.50.
2. Paired 168-hour moving-block-bootstrap lower bounds for Sharpe and Calmar deltas versus buy-and-hold, volatility-targeted long, and simple-trend long/cash are strictly positive.
3. At least 7 of 12 folds are profitable and no single positive fold contributes more than 50% of total positive-fold return.
4. At least 18 of 35 complete months are profitable; both complete calendar years are profitable.
5. Annualized turnover is positive and at most 100; at least 20 completed exposure episodes per year; median completed holding period is between 1 and 168 hours; completed-episode profit factor exceeds 1.
6. Every predeclared neighbourhood path has positive net return and positive Sharpe in both markets.
7. The strategy’s 5% expected shortfall is less severe than volatility-targeted long in both markets.

Capacity and prospective maker fill/no-fill/partial-fill/timeout, adverse-selection, latency, and paper-performance evidence remain separate mandatory deployment gates and cannot be inferred from this retrospective test.

## Candidate accounting and discipline

- Architecture candidates searched: 1.
- No threshold, window, market subset, benchmark, fee, delay, or acceptance rule may be changed after viewing results.
- BTC-USDT and ETH-USDT are development markets.
- SOL-USDT is a consumed holdout and must not be read or used.
- 15-minute research remains blocked.
