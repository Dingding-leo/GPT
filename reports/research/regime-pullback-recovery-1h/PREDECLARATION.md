# Predeclaration: Regime-Conditioned Pullback Recovery 1h

## Falsifiable hypothesis

A fixed, maker-compatible `1H` pullback-recovery architecture clears every retrospective architecture-freeze gate in both BTC-USDT and ETH-USDT at exactly **5 bps one-way exchange fee**, and is therefore eligible to enter prospective post-only paper evaluation.

Exactly one architecture candidate is tested. BTC-USDT and ETH-USDT are development markets. No sealed market is read or used. The result is retained as rejection if any mandatory gate fails.

Canonical signature:

`regime-pullback-recovery-1h-v1|markets=BTC-USDT,ETH-USDT|provider=OKX-spot|bar=1H|source=portable-canonical-1h-artifacts|architecture=720h-positive-regime-plus-24h-log-price-zscore-pullback-state-machine|entry-z=-1.5|exit-z=-0.25|max-hold=48h|episode-size=frozen-at-entry-50pct-vol-target-using-168h-realized-vol|max-position=1|fee=5bps-one-way|execution=one-complete-bar-delay|evaluation=2023-07-01T00:00Z..2026-06-14T23:00Z|fold=2160h|bootstrap=paired-noncircular-168h-blocks-2000-resamples-95pct|architecture-candidate-count=1`

## Economic rationale

Crypto spot trends over long horizons but often experiences short-lived hourly pullbacks. A passive implementation can attempt to join a positive long-horizon regime only after a statistically unusual 24-hour pullback, then exit after recovery, regime failure, or a fixed timeout. Freezing position size at entry avoids continuous hourly target jitter and creates discrete, auditable maker-order episodes.

## Fixed causal architecture

For each completed hourly bar `t`:

1. `regime_t = close_t / close_(t-720) - 1`.
2. `z_t` is the z-score of `log(close_t)` over the latest 24 completed closes, using population standard deviation.
3. Realized volatility is the population standard deviation of the latest 168 completed hourly log returns, annualized by `sqrt(24 * 365)`.
4. When flat, enter a long target if `regime_t > 0` and `z_t <= -1.5`.
5. Entry size is `min(1, 0.50 / realized_vol_t)` and remains frozen for the episode.
6. When long, exit if `regime_t <= 0`, `z_t >= -0.25`, or the target has been long for 48 completed bars.
7. A target computed from bar `t` becomes the executed position only on bar `t+1`.
8. Net return is executed position times close-to-close asset return minus `0.0005 * absolute position change`.

No spread, slippage, impact, latency, or alternate-cost path is included in PnL. Maker fill quality, no-fill, partial fill, timeout, adverse selection, and latency remain separate prospective diagnostics. No fill is assumed by this retrospective test.

## Data and evaluation

- Immutable portable canonical BTC-USDT and ETH-USDT public-OKX `1H` artifacts from PR #475.
- Exact evaluation interval: 2023-07-01 00:00 UTC through 2026-06-14 23:00 UTC.
- Non-overlapping 2,160-hour folds.
- Benchmarks are the persisted same-timestamp buy-and-hold, volatility-targeted-long, and simple-trend-long/cash paths.
- Benchmark inference uses paired non-circular 168-hour moving blocks, 2,000 resamples, 95% confidence, seeds `20260724141` for BTC and `20260724142` for ETH.

## Mandatory retrospective gates

The joint hypothesis passes only if both markets pass all of the following:

1. **Net viability:** net total return and Sharpe are positive at exactly 5 bps one-way.
2. **Benchmark-relative evidence:** 95% lower confidence bounds for both Sharpe and Calmar deltas are strictly positive against every declared benchmark.
3. **Fold breadth:** at least 7 of 12 folds are profitable and the largest positive-fold contribution is at most 50%.
4. **Calendar breadth:** at least 18 of 35 complete months are profitable; both complete calendar years are profitable.
5. **Activity:** annual turnover is between 12 and 150; at least 24 completed episodes per year; median completed holding period is between 4 and 48 hours; completed-episode profit factor exceeds 1.
6. **Neighbourhood stability:** four one-axis robustness paths—entry z `-1.25`, entry z `-1.75`, max hold `36h`, and max hold `60h`—must each have positive net return and Sharpe above 0.50 in both markets. They are not searched alternatives.
7. **Tail risk:** strategy 5% expected shortfall is less severe than volatility-targeted long.
8. **Capacity:** every entry/exit adjustment for a USD 1,000,000 initial account must remain at or below 0.10% of the strictly lagged 720-hour median hourly quote volume.

Prospective post-only fill/no-fill/partial-fill/timeout, adverse-selection, latency, and forward-performance evidence remain required before paper/live eligibility. Passing this retrospective hypothesis would only authorize a frozen prospective paper protocol.
