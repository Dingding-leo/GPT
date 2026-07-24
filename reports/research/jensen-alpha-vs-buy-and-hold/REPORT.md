# Jensen alpha versus buy-and-hold

## Hypothesis

BTC-USDT and ETH-USDT net rolling OOS strategy returns each have positive
annualized Jensen alpha versus persisted net buy-and-hold returns. The joint
hypothesis passes only if both 95% paired moving-block-bootstrap lower bounds
are strictly positive.

Canonical signature:

```text
jensen-alpha-vs-buy-and-hold-v1|markets=BTC-USDT,ETH-USDT|source=persisted-net-rolling-oos-returns|benchmark=buy-and-hold|regression=strategy-return=alpha+beta*benchmark-return|metric=annualized-ols-intercept|annualization=365|claim=alpha>0-in-both-markets|resampling=paired-noncircular-moving-block-bootstrap|block=20|resamples=2000|confidence=0.95|seeds=BTC-USDT:20260723,ETH-USDT:20260724|candidate_count=1
```

## Why this test

The strategy's shallower drawdown may be explained entirely by low market beta
and reduced exposure. A positive regression intercept would support the
stronger claim that the long/cash process adds return beyond its linear
sensitivity to the investable buy-and-hold benchmark.

This test is distinct from information ratio, which evaluates unadjusted active
return, and from exposure-timing diagnostics, which do not estimate a
beta-adjusted intercept.

## Fixed method

- provider: OKX public spot data;
- markets: BTC-USDT and ETH-USDT;
- bar: `1Dutc`;
- persisted net rolling OOS returns: 2,340 daily observations per market;
- regression: `strategy_return = alpha + beta * benchmark_buy_and_hold_return`;
- primary metric: daily OLS intercept multiplied by 365;
- paired non-circular moving-block bootstrap;
- block length: 20 sessions;
- resamples: 2,000;
- confidence: 95%;
- seeds: 20260723 for BTC-USDT and 20260724 for ETH-USDT;
- candidates searched: one joint specification.

No benchmark, regression convention, block length, seed, market subset, fee,
execution delay, fold rule, or acceptance threshold was selected after viewing
the result.

## Result

| Market | Annualized alpha | Beta | Alpha 95% interval | P(alpha > 0) |
|---|---:|---:|---:|---:|
| BTC-USDT | +4.724446% | 0.244279 | -10.030455% to +20.083634% | 73.20% |
| ETH-USDT | -1.370538% | 0.208069 | -15.639520% to +12.962307% | 42.30% |

## Verdict: rejected

Both alpha confidence intervals cross zero, and ETH-USDT's point intercept is
negative. Candidate accounting is `searched=1`, `passed=0`, `rejected=1`.

The low beta estimates are consistent with a defensive long/cash process, but
the current development evidence does not establish positive beta-adjusted
return. No alpha, benchmark-superiority, or deployable strategy improvement is
claimed.

## Provenance

- source workflow: `29964427149`;
- source artifact: `8547282774` (`quant-research-source-193`);
- artifact SHA-256:
  `e5654461e56bd76f7b61133a4eb9b00b7e98974fc8a09449185614250d462344`;
- source head:
  `e09b3588c9491d2139a52edd5bd2a21c619e9b51`;
- merged main commit:
  `2a8b0ada66a5b2271ebaf1a92f520caa211bf619`;
- BTC return SHA-256:
  `539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73`;
- ETH return SHA-256:
  `027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6`.

## Reproduction

```bash
python reports/research/jensen-alpha-vs-buy-and-hold/analysis.py \
  --artifact-dir /path/to/quant-research-source-193 \
  --output /tmp/jensen-alpha.json

cmp /tmp/jensen-alpha.json \
  reports/research/jensen-alpha-vs-buy-and-hold/result.json

pytest -q tests/test_jensen_alpha_vs_buy_and_hold_report.py
```

## Limitations

BTC-USDT and ETH-USDT are development markets, not untouched holdouts. A
one-factor linear regression is descriptive rather than causal. Moving-block
concatenation creates artificial joins, and the evidence does not model
nonlinear market impact, capacity, latency, or partial fills.
