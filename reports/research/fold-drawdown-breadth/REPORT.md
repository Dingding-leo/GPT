# Fold-Level Maximum-Drawdown Breadth

## Hypothesis

BTC-USDT and ETH-USDT each have a positive mean 90-session fold maximum-drawdown
reduction versus volatility-targeted long. The joint hypothesis passes only if both
95% moving-block-bootstrap lower confidence bounds are strictly above zero.

The fold reduction is:

```text
strategy maximum drawdown - volatility-targeted-long maximum drawdown
```

Because maximum drawdown is non-positive, a positive reduction means the strategy's
fold drawdown was shallower.

## Economic rationale

The aggregate and calendar-year evidence suggests a defensive effect, but a risk-control
claim is more credible when the reduction recurs across the repository's actual
90-session deployment folds. This fixed diagnostic measures the average fold-level
reduction while preserving short-range ordering between consecutive folds.

Exactly one joint candidate was evaluated. No alternative benchmark, fold length,
metric, block length, resample count, seed, market subset, fee, execution delay, or
acceptance rule was selected after viewing the result.

## Fixed design

- Provider and markets: OKX spot BTC-USDT and ETH-USDT.
- Timeframe: `1Dutc`.
- Evidence: persisted net rolling OOS returns.
- Folds: 26 complete non-overlapping folds of 90 observations.
- Comparator: persisted volatility-targeted-long benchmark returns.
- Fold metric: maximum drawdown from equity 1.0 at the fold start.
- Resampling: non-circular moving blocks over consecutive fold reductions.
- Block length: three folds.
- Resamples: 2,000.
- Confidence: 95%.
- Acceptance: both mean-reduction lower bounds strictly above zero.

## Results

| Market | Positive folds | Mean reduction | Median reduction | 95% interval | P(mean > 0) |
|---|---:|---:|---:|---:|---:|
| BTC-USDT | 26 / 26 | 13.3166% | 11.6786% | 8.2591% to 18.0230% | 100.00% |
| ETH-USDT | 26 / 26 | 14.0231% | 10.6595% | 8.9336% to 18.6226% | 100.00% |

## Verdict

**Supported as an unscaled development-market risk-control breadth effect.** Both lower
confidence bounds are positive, and the strategy's maximum drawdown was shallower in
all 26 folds in both markets.

Candidate accounting: one searched, one passed, zero rejected.

This is not evidence of alpha, higher Sharpe or Calmar, volatility-normalized superiority,
or untouched-holdout generalization. Prior volatility-matched analysis did not establish
a drawdown advantage after equalizing realized volatility.

## Real-data provenance

- Source workflow: `29940617808`.
- Source artifact: `8538033369`, `quant-research-source-1198-attempt-1`.
- Artifact SHA-256: `30523ece44c47c7c3317f7a5f5e6273eb5886cccb213dae2cc177b86dce007df`.
- Source head: `1f6e5a133cb012be1b8222b0e655b18f675fdb1e`.
- BTC return-file SHA-256: `539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73`.
- ETH return-file SHA-256: `027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6`.
- OOS period: 2020-01-11 through 2026-06-07 UTC.
- Observations: 2,340 per market.

## Limitations

BTC and ETH remain development markets rather than untouched holdouts. Fold-start
normalization measures drawdown within each reporting window rather than continuous
capital drawdown across fold boundaries. Three-fold blocks preserve short-range fold
ordering but create artificial joins and do not preserve dependence beyond three folds.
The comparison is not volatility matched. Spread, nonlinear impact, capacity, latency,
and partial fills remain unmodeled beyond persisted costs.
