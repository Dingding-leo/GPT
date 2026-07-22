# One-Additional-Bar Execution-Delay Stress

## Hypothesis

For both BTC-USDT and ETH-USDT, the existing net rolling out-of-sample strategy returns retain a positive annualized arithmetic mean when the **persisted executed position** is delayed by one additional `1Dutc` bar. The joint hypothesis passes only if both 95% moving-block-bootstrap lower bounds are above zero.

Canonical signature:

```text
extra-execution-delay-resilience-v1|markets=BTC-USDT,ETH-USDT|source=persisted-walk-forward-oos-executed-position|stress=shift-executed-position-by-one-additional-bar-from-cash|turnover=absolute-change-in-delayed-position|transaction_cost_bps=10|metric=annualized-arithmetic-mean-net-return|annualization=365|block=20|resamples=2000|confidence=0.95|seeds=BTC-USDT:20260722,ETH-USDT:20260723|candidate_count=1
```

## Economic rationale

The repository already enforces one-bar execution delay. A signal whose development evidence disappears after one additional daily bar may depend on immediate next-session price response and may be fragile to operational latency, delayed data availability, or slower execution. This fixed stress does not retune the strategy. It shifts the already executed OOS position by one more bar, begins from cash, and recomputes turnover and the declared 10 bps transaction cost.

## Fixed specification

- Provider and market: OKX spot `BTC-USDT` and `ETH-USDT`.
- Bar: `1Dutc`.
- Evidence status: development markets, not untouched holdouts.
- Source: persisted non-overlapping rolling OOS results.
- Stress: `delayed_position[t] = persisted_position[t-1]`, with the first delayed position equal to cash.
- Turnover: absolute change in the delayed executed position.
- Cost: 10 bps per unit turnover.
- Metric: annualized arithmetic mean of delayed net returns.
- Uncertainty: non-circular 20-day moving-block bootstrap, 2,000 resamples, 95% interval.
- Candidate count: exactly one.

No alternative delay, cost, block length, seed, market subset, signal parameter, fold, or threshold was searched after observing the result.

## Results

| Market | Original annualized mean | Extra-delay annualized mean | 95% interval | P(mean > 0) | Extra-delay total return |
|---|---:|---:|---:|---:|---:|
| BTC-USDT | 17.17% | 15.68% | -3.01% to 40.38% | 94.70% | 126.61% |
| ETH-USDT | 13.70% | 16.78% | -1.48% to 36.67% | 96.15% | 137.52% |

## Verdict: rejected

Both delayed point estimates and total returns remain positive, but both 95% lower confidence bounds are below zero. The joint hypothesis is therefore rejected. The evidence does not establish that the positive mean survives an additional daily execution delay with the repository's required confidence standard.

This rejection does not imply that one extra bar necessarily makes the strategy unprofitable. It means the available BTC/ETH development evidence is not strong enough to support that latency-resilience claim under the single predeclared block-bootstrap specification.

## Provenance

- Source workflow: `29883451981`.
- Source artifact: `8515639605` (`quant-research-426`).
- Artifact SHA-256: `396903281f1ef4ec71edbe0dded7c091c4c3545ffbaa7a502cc15bda4880b478`.
- Tested merge commit: `8b1003c8b680664f5e96ff6818694c9d30fe1b7f`.
- Persistent source head: `43d4f8b10d8f654b5fbcf974793493a967e125e4`.
- BTC returns SHA-256: `539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73`.
- ETH returns SHA-256: `027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6`.
- Observations: 2,340 daily OOS rows per market, January 11, 2020 through June 7, 2026 UTC.

## Limitations

This is a deterministic delay stress on persisted daily positions. It is not an order-book, spread, market-impact, partial-fill, capacity, exchange-outage, or live-execution model. BTC and ETH were already used as development markets, and no stronger holdout claim is made.
