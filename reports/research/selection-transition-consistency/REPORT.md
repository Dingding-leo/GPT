# Selected-Parameter Transition Regime Consistency

## Hypothesis

For both BTC-USDT and ETH-USDT, persisted net rolling out-of-sample returns have a
positive annualized arithmetic mean in folds where the selected parameter tuple changed
from the previous fold and in folds where it remained unchanged. The joint hypothesis
passes only if all four 95% moving-block-bootstrap lower bounds are above zero.

## Economic rationale

A credible adaptive research process should not require either continuous parameter churn
or prolonged parameter stasis to generate returns. Conditioning on observed selection
transitions tests whether performance survives both operating states without changing the
candidate grid, fees, execution timing, or strategy rules.

## Predeclared specification

- Markets: BTC-USDT and ETH-USDT, OKX spot `1Dutc` development evidence.
- Selection tuple: momentum lookback, reversal lookback, and trend weight.
- Regimes: tuple changed from the immediately prior fold versus tuple unchanged.
- Fold 1: excluded because no prior selected tuple exists.
- Classified sample: 25 complete 90-day folds per market.
- Resampling: paired non-circular moving blocks over whole observed fold records.
- Block length: three folds, preserving roughly nine months of local dependence.
- Resamples: 2,000 per market; confidence: 95%.
- Metric: conditional daily net-return arithmetic mean multiplied by 365.
- Candidate count: exactly one.

Canonical signature:

```text
selection-transition-regime-consistency-v1|markets=BTC-USDT,ETH-USDT|source=persisted-net-rolling-oos-returns-and-selected-parameters|regimes=selected-parameter-tuple-changed-vs-unchanged-from-prior-fold|exclude=fold1-no-prior-selection|metric=conditional-annualized-arithmetic-mean-net-return|annualization=365|resampling=paired-noncircular-moving-block-over-whole-fold-records|fold-block=3|resamples=2000|confidence=0.95|seeds=BTC:20260722,ETH:20260723|candidate_count=1
```

## Result

| Market | Selection regime | Folds | Annualized mean | 95% interval | P(mean > 0) |
|---|---|---:|---:|---:|---:|
| BTC-USDT | Changed | 13 | 20.677187% | 2.881253% to 42.188916% | 98.85% |
| BTC-USDT | Unchanged | 12 | 23.589842% | -13.937782% to 102.350364% | 86.45% |
| ETH-USDT | Changed | 13 | 31.077974% | 9.359033% to 71.708691% | 99.90% |
| ETH-USDT | Unchanged | 12 | 2.742612% | -30.775451% to 35.725920% | 60.35% |

The changed-parameter regime passed in both markets. The unchanged-parameter regime had
positive point estimates but negative lower confidence bounds in both markets. The joint
hypothesis is therefore **rejected**. This does not establish that changing parameters
causes returns; it shows only that positive-return evidence is not reliable in both
observed selection-transition states.

## Provenance

- Source workflow: `29895819965`, attempt 1.
- Source artifact: `8519944587`, `quant-research-source-648-attempt-1`.
- Artifact SHA-256:
  `f755ee85017c881e7fcfde1dc1fcd5c3f0fadbcb67197f1f3a466f1178b3895f`.
- Source head: `09a6be919bd3733b01f86bfcf8710377ce462455`.
- Tested base: `18ba522be8a7bf3941392a8acfc7f5100172fc91`.
- BTC return-file SHA-256:
  `539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73`.
- ETH return-file SHA-256:
  `027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6`.
- Observations: 2,340 per market, 2020-01-11 through 2026-06-07 UTC.
- Existing assumptions: one-bar execution delay, 10-bps turnover cost, 730/90 folds,
  27 candidates per selection window.

## Limitations

BTC-USDT and ETH-USDT are development markets, not untouched holdouts. Only 25 folds per
market have a transition label. The observed changed/unchanged label remains attached to
its original fold during resampling and is not recomputed across bootstrap block
boundaries. The analysis does not model capacity, order-book depth, latency, or partial
fills and does not propose a parameter-switching trading rule.
