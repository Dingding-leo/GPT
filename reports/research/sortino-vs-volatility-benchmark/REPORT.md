# Sortino Ratio Versus Volotility-Targeted Benchmark

## Hypothesis

BTC-USDT and ETH-USDT net rolling OOS strategy returns each have a higher annualized
zero-minimum-acceptable-return Sortino ratio than the persisted volatility-targeted-long
benchmark. The joint hypothesis passes only if both 95% paired moving-block-bootstrap lower
bounds for the strategy-minus-benchmark Sortino delta are strictly positive.

## Economic rationale

Sharpe treats upside and downside volatility symmetrically. A long/cash risk-control strategy
should justify its complexity through better return per unit of downside variation, not only a
shallower point maximum drawdown. This fixed comparison tests that downside-risk-adjusted claim
without changing signals, parameters, fees, execution delay, folds, or benchmark construction.

Exactly one joint candidate was evaluated. No alternate benchmark, Sortino convention, minimum
acceptable return, annualization, block length, seed, confidence threshold, market subset, fee,
or delay was selected after observing the result.

## Fixed design

- Provider and markets: OKX spot BTC-USDT and ETH-USDT.
- Timeframe: `1Dutc`.
- Evidence: persisted net rolling OOS strategy and benchmark returns.
- Benchmark: volatility-targeted long.
- Sortino minimum acceptable return: zero.
- Downside deviation: `sqrt(mean(min(return, 0)^2))` over all observations.
- Annualization: `sqrt(365)` applied to the daily mean/downside-deviation ratio.
- Resampling: paired non-circular moving blocks over observed strategy/benchmark rows.
- Block length: 20 sessions.
- Resamples: 2,000.
- Confidence: 95%.
- Acceptance: both lower confidence bounds strictly above zero.

## Results

| Market | Strategy Sortino | Benchmark Sortino | Delta | 95% interval | P(delta > 0) |
|---|---:|---:|---:|---:|---:|
| BTC-USDT | 1.124084 | 1.043537 | +0.080547 | -0.939563 to +1.100210 | 54.90% |
| ETH-USDT | 0.794869 | 1.333570 | -0.538701 | -1.558524 to +0.477356 | 14.55% |

## Verdict

**Rejected.** Both 95% lower confidence bounds are non-positive, and ETH-USDT's point Sortino
is below the benchmark. The evidence does not establish superior downside-risk-adjusted returns
in both development markets. No strategy improvement or deployable rule is claimed.

Candidate accounting: one searched, zero passed, one rejected.

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

BTC and ETH remain development markets rather than untouched holdouts. Moving-block sampling
preserves observed paired rows and within-block ordering but creates artificial joins and does
not preserve dependence beyond 20 sessions. The zero-MAR Sortino convention is one declared
risk-adjusted metric and does not model spread, nonlinear impact, capacity, latency, or partial
fills beyond the persisted transaction costs.
