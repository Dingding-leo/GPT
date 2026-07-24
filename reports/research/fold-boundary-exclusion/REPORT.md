# Fold-Boundary Exclusion Consistency

## Hypothesis

Net rolling out-of-sample strategy returns retain a positive annualized arithmetic mean in both BTC-USDT and ETH-USDT after excluding the first observation of every 90-bar test fold. Both 95% confidence-interval lower bounds must be positive for the joint hypothesis to pass.

## Economic rationale

The first test observation after each parameter-selection window is the point most sensitive to parameter reselection, carried position state, turnover, and transaction-cost accounting. A credible return process should persist through the interiors of the OOS folds rather than depend on those 26 one-day boundaries.

## Predeclared specification

- Canonical signature: `fold-boundary-exclusion-consistency-v1|markets=BTC-USDT,ETH-USDT|source=persisted-net-rolling-oos-returns|stress=exclude-first-observation-each-fold|metric=annualized-arithmetic-mean-net-return|annualization=365|resampling=within-fold-noncircular-moving-block|block=20|resamples=2000|confidence=0.95|seeds=BTC-USDT:20260722,ETH-USDT:20260723|candidate_count=1`
- Candidate count: 1
- Development markets: BTC-USDT and ETH-USDT
- OOS folds: 26 non-overlapping folds of 90 observations
- Stress: remove exactly the first observation from each fold
- Remaining observations: 2,314 per market
- Metric: annualized arithmetic mean of persisted net strategy returns
- Resampling: separate non-circular moving blocks inside each 89-observation fold interior
- Block length: 20 observations
- Resamples: 2,000
- Confidence: 95%
- Seeds: BTC-USDT `20260722`; ETH-USDT `20260723`

No alternative exclusion width, fold subset, block length, seed, confidence level, fee, execution delay, signal parameter, market subset, or pass threshold was searched after observing the result.

## Result

**Verdict: rejected.**

| Market | Full annualized mean | Fold-interior annualized mean | 95% interval | P(mean > 0) | Pass |
|---|---:|---:|---:|---:|---:|
| BTC-USDT | 17.168957% | 15.174726% | [0.249153%, 34.118880%] | 97.70% | Yes |
| ETH-USDT | 13.704095% | 12.090729% | [-3.698835%, 32.418143%] | 93.30% | No |

BTC-USDT retained a positive lower confidence bound after removing all fold-boundary observations. ETH-USDT did not. Because the joint hypothesis requires both markets to pass, the candidate is rejected.

## Failure accounting

- Candidates searched: 1
- Candidates passed: 0
- Candidates rejected: 1
- Rejection reason: ETH-USDT fold-interior annualized mean lower confidence bound is not positive.

## Data provenance

- Provider: OKX public spot candles
- Instruments: BTC-USDT and ETH-USDT
- Timeframe: `1Dutc`
- Source workflow: `29886881484`
- Source artifact: `8516824262` (`quant-research-484`)
- Source artifact SHA-256: `b1f271e4267cc1c1007bbccd11c53c1a59d3f1e3fe3f1e3f07423c6907b83605`
- Source head: `cfc0a08048ac584a375f15e4ed146c00266e2e17`
- Evaluation period: 2020-01-11 through 2026-06-07 UTC
- Observations before exclusion: 2,340 per market
- Persisted assumptions: one-bar execution delay, 10 bps transaction cost, 730-bar selection windows, 90-bar non-overlapping OOS folds, and the complete 27-candidate grid

## Evidence boundary

BTC-USDT and ETH-USDT are development markets, not untouched holdouts. This diagnostic does not alter selection, fees, execution timing, sealed-holdout rules, or strategy parameters. The resampling draws only from observed real net returns and keeps blocks inside their original fold interiors; it does not create artificial market-price paths.

The test covers only the immediate one-observation boundary. It does not model liquidity, spread, market impact, capacity, latency, or partial fills.
