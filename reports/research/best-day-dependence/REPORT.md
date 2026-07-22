# Best-day dependence stress

## Hypothesis

For both BTC-USDT and ETH-USDT, the existing strategy's net out-of-sample returns retain a positive
annualized arithmetic mean after removing exactly the largest 1% of strategy-return observations.
The joint hypothesis passes only if both 95% moving-block-bootstrap lower bounds are above zero.

Canonical signature:

```text
best-day-dependence-v1|markets=BTC-USDT,ETH-USDT|stress=remove-ceil-top-1pct-strategy-returns-per-sample|metric=annualized-arithmetic-mean-net-return|annualization=365|block=20|resamples=2000|confidence=0.95|seeds=BTC-USDT:20260722,ETH-USDT:20260723|candidate_count=1
```

## Economic rationale

A credible return process should not require a very small set of exceptional sessions to preserve a
positive mean. Removing the best 1% of realized strategy returns is a deliberately adverse,
predeclared concentration stress. It tests whether the reported positive average is broad or depends
on rare favorable days.

The stress is diagnostic rather than tradable: it removes observations after the fact and does not
change signals, position sizing, fees, execution delay, folds, or candidate selection.

## Candidate accounting

Exactly one specification was tested:

- stress: remove exactly `ceil(observations * 0.01)` largest strategy returns;
- metric: annualized arithmetic mean of retained net strategy returns;
- moving blocks: 20 observations without circular wrapping;
- resamples: 2,000;
- confidence: 95%;
- deterministic seeds: 20260722 for BTC and 20260723 for ETH.

No alternative removal fraction, rounding rule, metric, block length, seed, market subgroup,
strategy parameter, transaction cost, execution delay, or split was searched after observing the
result.

## Results

| Market | Unstressed annualized mean | After removing best 1% | Removed days | 95% interval | P(stressed mean > 0) |
|---|---:|---:|---:|---:|---:|
| BTC-USDT | 17.1690% | -5.9923% | 24 | [-21.9689%, 15.5993%] | 29.30% |
| ETH-USDT | 13.7041% | -9.8409% | 24 | [-27.2346%, 8.7484%] | 16.35% |

The smallest removed return was 4.4138% for BTC-USDT and 4.4780% for ETH-USDT. The largest removed
return was 10.2628% for BTC-USDT and 14.4018% for ETH-USDT.

## Verdict: rejected

Both point estimates become negative after the fixed stress, and both 95% lower confidence bounds
are negative. The evidence therefore does not establish a positive mean independent of the best 1%
of OOS strategy-return days.

This does not prove that the removed observations were invalid or unrepeatable. It shows that the
positive full-sample arithmetic mean is materially concentrated in a small number of favorable
sessions under this one predeclared stress.

## Data and provenance

- provider: OKX public spot market data;
- instruments: BTC-USDT and ETH-USDT;
- bar: `1Dutc`;
- OOS dates: 2020-01-11 through 2026-06-07 UTC;
- observations: 2,340 per market;
- source workflow run: `29877892427`;
- source artifact: `8513672060` (`quant-research-378`);
- source artifact SHA-256: `7902fd0e653a446151188dc426386bfb8406d404a348aaf8be13a7671deb10ec`;
- source tested merge commit: `fd8d2191e30bb0aeb80da0021f2923f3bc9a8377`;
- source persistent head: `e1f49e3ad33fa2cd820de5ca0a6f70231f214a20`;
- source base: `a2f1ab460409113057198ebdd00e3ce4f6c7bf82`;
- BTC returns SHA-256: `539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73`;
- ETH returns SHA-256: `027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6`.

The persisted analysis validates exact source hashes, declared repository settings, timezone-aware
strict daily chronology, and finite returns greater than -1 before computing the stress.

## Claim boundary

BTC-USDT and ETH-USDT are development markets. This result is a descriptive outlier-dependence
stress, not a causal result, alpha claim, untouched-holdout confirmation, trading rule, or
live-execution model. It does not model spread, market impact, liquidity, capacity, latency, or
partial fills.
