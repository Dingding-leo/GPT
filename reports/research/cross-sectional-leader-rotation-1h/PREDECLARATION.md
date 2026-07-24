# Predeclaration: Cross-Sectional Leader Rotation 1h

## Falsifiable hypothesis

A fixed BTC-USDT/ETH-USDT cross-sectional `1H` leader-rotation architecture clears every retrospective architecture-freeze gate at exactly **5 bps one-way exchange fee** and is therefore eligible for prospective post-only paper evaluation.

Exactly one architecture candidate is tested. BTC-USDT and ETH-USDT are development markets. The result is retained as a rejection if any mandatory gate fails. No spread, slippage, market impact, latency, or alternate cost path is added to PnL.

Canonical signature:

`cross-sectional-leader-rotation-1h-v1|markets=BTC-USDT,ETH-USDT|provider=OKX-spot|bar=1H|source=immutable-common-1h-coverage-artifact-8587664816|architecture=equal-weight-720h-market-regime-plus-168h-relative-strength-leader|decision-cadence=6h-UTC|position-size=50pct-annual-vol-target-from-prior-168h|max-gross=1|fee=5bps-one-way|execution=one-complete-bar-delay|evaluation=2023-07-01T00:00Z..2026-06-14T23:00Z|fold=2160h|benchmarks=equal-weight-buy-hold,equal-weight-vol-target,equal-weight-720h-trend|bootstrap=paired-noncircular-168h-blocks-2000-resamples-95pct|neighbourhood=momentum120,momentum240,cadence3,cadence12|capacity=USD100000-at-0.10pct-prior-720h-median-hourly-quote-volume|architecture-candidate-count=1`

## Economic rationale

BTC and ETH frequently alternate leadership. A cross-sectional process may avoid holding the weaker asset while preserving a broad crypto regime filter. Restricting decisions to four fixed UTC times per day reduces continuous target jitter and is compatible with future bounded post-only submission attempts. The position is sized only from prior hourly volatility and becomes executable after one complete bar.

## Fixed causal architecture

For each completed hourly bar `t`:

1. Compute each asset's trailing 168-hour close return.
2. Compute the mean of the two trailing 720-hour returns as the broad market regime.
3. At UTC hours `00`, `06`, `12`, and `18`, hold cash unless the broad regime is positive and at least one asset has positive 168-hour momentum.
4. Otherwise select only the asset with the higher 168-hour momentum.
5. Size that sleeve as `min(1, 0.50 / prior_168h_annualized_volatility)`.
6. Carry the target unchanged between decision times.
7. A target calculated from bar `t` becomes the executed position on bar `t+1`.
8. Net return equals sleeve close-to-close return minus `0.0005 × total absolute sleeve position change`.

Maker fill quality, no-fill, partial fill, timeout, adverse selection, and latency remain separate prospective diagnostics. This retrospective analysis assumes no maker fill.

## Data and inference

- Immutable common-window public OKX BTC-USDT and ETH-USDT `1H` coverage from workflow `30069656422`, artifact `8587664816`.
- Strict evaluation interval: `2023-07-01 00:00 UTC` through `2026-06-14 23:00 UTC`.
- Twelve non-overlapping 2,160-hour folds.
- Same-window 5 bps benchmarks: equal-weight buy-and-hold, equal-weight volatility-targeted long, and equal-weight 720-hour trend long/cash.
- Paired non-circular 168-hour moving blocks, 2,000 resamples, 95% confidence.
- Four one-axis neighbourhood paths are robustness checks, not searched candidates: 120-hour momentum, 240-hour momentum, 3-hour cadence, and 12-hour cadence.

## Mandatory retrospective gates

The joint hypothesis passes only when all of the following pass:

1. Positive net total return and Sharpe at exactly 5 bps one-way.
2. Strictly positive 95% lower bounds for Sharpe and Calmar deltas against all three benchmarks.
3. At least 7 of 12 profitable folds and no more than 50% of positive-fold return from one fold.
4. At least 18 of 35 profitable complete months and both complete calendar years profitable.
5. Annual turnover from 12 to 150, at least 24 completed exposure episodes per year, median holding period from 4 to 168 hours, and completed-episode profit factor above 1.
6. Every neighbourhood path has positive net return and Sharpe above 0.50.
7. Strategy 5% expected shortfall is less severe than equal-weight volatility-targeted long.
8. Every USD 100,000 sleeve adjustment remains at or below 0.10% of strictly lagged 720-hour median hourly quote volume.

Passing retrospective gates would only authorize a frozen prospective maker-paper protocol. It would not establish live eligibility without forward fill, no-fill, partial-fill, timeout, adverse-selection, latency, state-recovery, and paper-performance evidence.
