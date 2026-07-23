# Prior-Fold Volatility-Matched Expected Shortfall Versus Volatility-Targeted Long

## Hypothesis

BTC-USDT and ETH-USDT net rolling out-of-sample strategy returns have less severe 5% expected shortfall than volatility-targeted long when the benchmark used in each current 90-session fold is scaled using only the immediately preceding complete fold's realised strategy-to-benchmark volatility ratio.

The economic question is whether the previously observed tail-loss reduction survives a strictly lagged, operationally available volatility normalization rather than a descriptive full-sample or same-resample scale.

## Fixed design

- Provider: OKX spot.
- Markets: BTC-USDT and ETH-USDT development evidence.
- Timeframe: `1Dutc`.
- Source observations: 2,385 persisted net rolling OOS rows per market, January 11, 2020 through July 22, 2026 UTC.
- Complete folds: 26 folds of 90 sessions; trailing 45-session fold excluded.
- Fold 1 is used only to estimate the scale for fold 2.
- Evaluation: folds 2 through 26, 2,250 observations per market.
- In fold `t`, benchmark returns are multiplied by `std(strategy in t-1, ddof=1) / std(benchmark in t-1, ddof=1)`.
- Expected shortfall is the mean of the worst `ceil(5% × n)` evaluation returns.
- Non-circular moving-block bootstrap over observed complete evaluation folds: three-fold blocks, 2,000 resamples, 95% confidence.
- Exactly one joint candidate was tested.

Positive delta means strategy expected shortfall is less negative than the prior-fold-scaled volatility-targeted-long benchmark.

## Results

| Market | Mean prior-fold scale | Strategy ES | Scaled benchmark ES | Delta | 95% interval | P(delta > 0) |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 0.423511 | -2.809026% | -2.996787% | +0.187760% | -0.413672% to +0.783614% | 73.40% |
| ETH-USDT | 0.426252 | -3.291334% | -3.024863% | -0.266471% | -0.754208% to +0.347942% | 20.80% |

## Verdict: rejected

Both 95% lower confidence bounds are non-positive, and ETH-USDT's point estimate favors the lagged volatility-matched benchmark.

Candidate accounting:

- searched: 1;
- passed: 0;
- rejected: 1.

This rejects the fixed claim that the strategy has superior daily 5% tail shape after a strictly lagged prior-fold volatility normalization. It does not establish that the benchmark is deployable, nor does it negate the strategy's raw lower-exposure drawdown control.

## Provenance

- Source workflow: `29994613190`.
- Source artifact: `8558445273`, `quant-research-source-1826-attempt-1`.
- Source artifact SHA-256: `8c89b8ecc4904cba018ac95079305c46e25d92199242b95d3aeffaad1bc0799c`.
- Source code head: `348cfd30df9a0665b5b129fba32edaafc8a2428e`.
- BTC return SHA-256: `ebf2e4cc63e6b21a2d89420e2c2dd5b3517179baacfd12931f75fb0d99bdd2ce`.
- ETH return SHA-256: `bd4fbc471d506069c01b86b39f7726b1bd05752bfd64e75b7d677d2d7f473047`.

The executable verifies both complete return-file digests before parsing or calculation.

## Limitations

BTC-USDT and ETH-USDT remain development markets rather than untouched holdouts. Prior-fold sample volatility is noisy, and a zero-volatility strategy fold produces a zero benchmark scale in the following fold. Scaling persisted net benchmark returns linearly is a diagnostic approximation rather than a complete position-and-cost reconstruction. Three-fold block resampling introduces artificial joins and preserves dependence only within sampled blocks. Nonlinear impact, capacity, latency, changing spreads, and partial fills remain unmodelled beyond persisted linear transaction costs.
