# Exposure-Matched Timing Diagnostic

## Hypothesis

For both BTC-USDT and ETH-USDT, the existing long/cash strategy has a positive annualized
arithmetic mean **net-return delta** versus a passive constant-exposure buy-and-hold benchmark
whose exposure equals the strategy's average executed out-of-sample position. The joint
hypothesis passes only if the 95% paired moving-block-bootstrap lower bound is positive in both
development markets.

Canonical signature:

```text
exposure-matched-timing-v1|markets=BTC-USDT,ETH-USDT|benchmark=ex-post-constant-exposure-buy-and-hold|exposure=mean-executed-oos-position|metric=annualized-arithmetic-mean-net-return-delta|entry-cost=10bps-pro-rata|block=20|resamples=2000|confidence=0.95|seeds=BTC-USDT:20260722,ETH-USDT:20260723|candidate_count=1
```

## Economic rationale

The strategy can reduce drawdown simply by holding less market exposure. A positive return
delta against a passive benchmark with the same average exposure would provide evidence that
dynamic exposure timing adds value beyond this first-order de-risking effect. Rejection means
the existing defensive evidence should not be promoted into a timing-alpha claim.

The benchmark is deliberately **ex post**: its fixed exposure is the arithmetic mean of the
strategy's persisted executed OOS position. It is a mechanism diagnostic, not an independently
tradable strategy or untouched holdout.

## Fixed specification

- Provider: OKX spot.
- Markets: BTC-USDT and ETH-USDT development markets.
- Bar: `1Dutc`.
- OOS window: 2,340 daily observations from 2020-01-11 through 2026-06-07 UTC.
- Strategy returns: persisted net returns with the repository's one-bar execution delay and
  transaction costs.
- Matched benchmark: `mean(position) * asset_return` with one pro-rata 10 bps entry charge.
- Primary metric: annualized arithmetic mean strategy return minus matched-benchmark return.
- Inference: paired 20-day moving-block bootstrap without circular wrapping.
- Resamples: 2,000 per market.
- Confidence: 95%.
- Seeds: 20260722 for BTC-USDT and 20260723 for ETH-USDT.
- Candidate count: exactly one metric and benchmark construction.

No alternative exposure definition, metric, entry-cost convention, benchmark, block length,
seed, market subgroup, strategy parameter, fee, split, or holdout rule was searched after the
result was observed.

## Results

| Market | Average exposure | Strategy annualized mean | Matched annualized mean | Delta | 95% interval | P(delta > 0) |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 27.3815% | 17.1690% | 13.9492% | +3.2198 pp | [-11.2761, +19.9724] pp | 66.90% |
| ETH-USDT | 21.7063% | 13.7041% | 15.7262% | -2.0221 pp | [-16.6895, +11.7249] pp | 40.90% |

Descriptive full-path total returns were 151.4134% for the BTC strategy versus 123.4742% for its
matched benchmark, and 95.6030% for the ETH strategy versus 147.5739% for its matched benchmark.
These path-dependent totals were not additional searched candidates or acceptance criteria.

## Verdict: rejected

BTC's point estimate is positive, but its lower confidence bound is negative. ETH's point
estimate is negative and its confidence interval also crosses zero. The joint hypothesis fails
in both the required statistical sense and, for ETH, at the point-estimate level.

This result does not negate prior lower-drawdown evidence. It narrows the claim: the current
repository evidence does not establish that dynamic timing improves mean net returns relative
to simply holding the same average exposure.

## Real-data provenance

- Source workflow run: `29870506091`.
- Source artifact: `8510950190` (`quant-research-328`).
- Artifact SHA-256:
  `d997b795dffcb255c919f972d3364d2d8492b3bdd58f6e8ad7733f6ea5b0517a`.
- Source base commit: `5a76277db73c156f248d276f8722f18ad18eef57`.
- Source persistent head: `0e55db97fa397b2a1bc5aec63e19403251ced926`.
- Source tested merge commit: `d74842a43ff4b4eab3906a0dd2b09417378bec10`.
- BTC returns SHA-256:
  `539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73`.
- ETH returns SHA-256:
  `027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6`.
- BTC walk-forward report SHA-256:
  `78b0f635114bad273054167ed7d552c32e707c019cd28fde04a268a131765a3f`.
- ETH walk-forward report SHA-256:
  `dd2d2d870f302f893a752f8db9b1d5cdfdca41f39e824fa6299d5d95eab04b76`.

## Limitations

The exposure match is estimated from the same development sample, so this is not independent
confirmation. Arithmetic mean return is a narrow timing diagnostic and does not establish
causality, deployability, capacity, or live execution quality. Moving-block concatenation also
creates artificial joins, although it resamples only observed real return/position records and
preserves within-block dependence.
