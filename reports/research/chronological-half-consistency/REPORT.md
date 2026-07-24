# Chronological half-sample return consistency

## Hypothesis

For both BTC-USDT and ETH-USDT, the existing strategy's net out-of-sample returns have a positive
annualized arithmetic mean in both equal chronological halves. The joint hypothesis passes only if
all four 95% moving-block-bootstrap lower bounds are above zero.

Canonical signature:

```text
chronological-half-return-consistency-v1|markets=BTC-USDT,ETH-USDT|split=equal-observation-halves-first1170-second1170|metric=annualized-arithmetic-mean-net-return|annualization=365|block=20|resamples=2000|confidence=0.95|seeds=BTC-USDT:first:20260722,second:20260724;ETH-USDT:first:20260723,second:20260725|candidate_count=1
```

## Economic rationale

A credible development-market return process should not depend entirely on one portion of the OOS
history. Splitting each market at the exact observation midpoint tests temporal persistence without
selecting a favorable calendar date. The first and second halves are evaluated separately, and
serial dependence is preserved with contiguous moving blocks inside each half.

This is a diagnostic rather than a new strategy rule. It does not change signals, parameter
selection, execution delay, transaction costs, folds, or sealed-holdout rules.

## Candidate accounting

Exactly one specification was tested:

- split: first 1,170 OOS observations versus final 1,170 OOS observations;
- metric: annualized arithmetic mean of net strategy returns;
- moving blocks: 20 observations without circular wrapping, applied independently within each half;
- resamples: 2,000 per market and half;
- confidence: 95%;
- deterministic seeds: 20260722/20260724 for BTC and 20260723/20260725 for ETH.

No alternative split date, number of segments, return metric, block length, seed, market subgroup,
strategy parameter, fee, execution delay, or holdout rule was searched after observing the result.

## Results

| Market | Half | Dates | Annualized mean | 95% interval | P(mean > 0) |
|---|---|---|---:|---:|---:|
| BTC-USDT | First | 2020-01-11 to 2023-03-25 | 19.6445% | [-14.2788%, 52.1180%] | 87.00% |
| BTC-USDT | Second | 2023-03-26 to 2026-06-07 | 14.6934% | [-8.4905%, 45.3262%] | 87.90% |
| ETH-USDT | First | 2020-01-11 to 2023-03-25 | 22.2180% | [-8.6639%, 52.9949%] | 92.35% |
| ETH-USDT | Second | 2023-03-26 to 2026-06-07 | 5.1902% | [-21.9750%, 30.8930%] | 62.65% |

## Verdict: rejected

All four point estimates are positive, but every lower confidence bound is negative. The evidence
does not establish a reliably positive mean in both chronological halves of both development
markets. The weakest segment is ETH-USDT's second half, where the point estimate falls to 5.19% and
the probability of a positive bootstrap mean is 62.65%.

This result does not prove the strategy has no temporal persistence. It shows that the fixed
half-sample requirement is not supported at the predeclared 95% confidence level.

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

The analysis validates the exact report and return hashes, declared fees and execution settings,
timezone-aware strict daily chronology, and finite returns greater than -1 before computing the
split or bootstrap.

## Claim boundary

BTC-USDT and ETH-USDT are development markets. The observation midpoint is not a fresh holdout. This
is a descriptive temporal-stability diagnostic, not a causal result, alpha claim, tradable regime
switch, live-execution model, or evidence about spread, impact, liquidity, capacity, latency, or
partial fills.
