# Portfolio Expected-Shortfall Diversification

## Hypothesis

The fixed-initial-weight 50/50 no-rebalancing BTC-USDT/ETH-USDT portfolio has less severe 5% expected shortfall than each individual sleeve, with both 95% paired moving-block-bootstrap lower bounds for expected-shortfall reduction above zero.

## Predeclared specification

- Canonical signature: `paired-portfolio-expected-shortfall-diversification-v1|markets=BTC-USDT,ETH-USDT|portfolio=fixed-initial-weights-50-50-no-rebalancing|metric=expected-shortfall-5pct-reduction-vs-each-sleeve|tail_fraction=0.05|resampling=paired-noncircular-moving-block|block=20|resamples=2000|confidence=0.95|seed=20260722|candidate_count=1`
- Candidate count: 1
- Portfolio: 50/50 initial BTC-USDT and ETH-USDT weights, no rebalancing
- Tail metric: mean of the worst `ceil(5% × observations)` net returns
- Resampling: paired non-circular 20-day moving blocks
- Resamples: 2,000
- Confidence: 95%
- Seed: 20260722

## Result

- Verdict: **rejected**
- Observations: 2340
- Tail observations: 117
- Portfolio 5% expected shortfall: -2.881963%

| Sleeve comparison | Sleeve ES | Portfolio minus sleeve ES | 95% interval | P(reduction > 0) |
|---|---:|---:|---:|---:|
| BTC-USDT | -2.935777% | 0.053814% | [-0.169018%, 0.216238%] | 68.50% |
| ETH-USDT | -3.387683% | 0.505720% | [0.248575%, 0.792254%] | 100.00% |

The joint hypothesis requires both lower confidence bounds to be positive. Failure on either comparison rejects the claim.

## Failure accounting

- portfolio expected-shortfall reduction versus BTC-USDT lower confidence bound is not positive

## Evidence boundary

This is one predeclared paired-block-bootstrap diagnostic on BTC-USDT and ETH-USDT development evidence. The portfolio uses fixed 50/50 initial weights and no rebalancing, matching the repository portfolio construction. Expected shortfall is the arithmetic mean of the worst ceil(5%) observed net returns. The experiment does not optimize weights, retune signals, alter fees or execution timing, or create a new holdout. It is not a liquidity, capacity, spread, impact, or live-fill model.

BTC-USDT and ETH-USDT are development markets, not untouched holdouts.
