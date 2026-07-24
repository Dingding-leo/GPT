# High-Turnover Concentrated-Slippage Stress

## Hypothesis

For both BTC-USDT and ETH-USDT, persisted net rolling out-of-sample returns retain a
positive annualized arithmetic mean after charging an additional **20 bps per unit of
turnover** on the highest-turnover **10%** of observations. The joint hypothesis passes
only if both 95% paired moving-block-bootstrap lower bounds are above zero.

## Economic rationale

Large position changes are the observations most exposed to spread widening, slippage,
and nonlinear market impact. A robust result should not require optimistic execution
costs on its highest-turnover sessions. This is a fixed diagnostic rather than a fitted
impact model.

## Predeclared specification

- Markets: BTC-USDT and ETH-USDT, OKX spot `1Dutc`.
- Source: persisted net rolling OOS `turnover` and `strategy_return` columns.
- Existing baseline fee: 10 bps per unit turnover, already included in persisted returns.
- Added stress: 20 bps per unit turnover on exactly `ceil(10% × n)` highest-turnover rows.
- Ranking: recomputed inside the observed sample and every bootstrap resample; stable
  source-row order breaks exact turnover ties.
- Resampling: paired non-circular 20-day moving blocks of turnover and return rows.
- Resamples: 2,000 per market.
- Confidence: 95%.
- Candidate count: exactly one.

Canonical signature:

```text
high-turnover-concentrated-slippage-v1|markets=BTC-USDT,ETH-USDT|source=persisted-net-rolling-oos-turnover-and-returns|stress=extra-20bps-per-unit-turnover-on-ceil-top-10pct-turnover-rows-per-sample|metric=annualized-arithmetic-mean-stressed-net-return|annualization=365|resampling=turnover-return-paired-noncircular-moving-block|block=20|resamples=2000|confidence=0.95|seeds=BTC:20260722,ETH:20260723|candidate_count=1
```

## Result

| Market | Baseline annualized mean | Stressed annualized mean | 95% interval | P(mean > 0) |
|---|---:|---:|---:|---:|
| BTC-USDT | 17.168957% | 15.491012% | -3.504282% to 40.111674% | 94.15% |
| ETH-USDT | 13.704095% | 12.080737% | -7.315259% to 32.143988% | 89.25% |

Both point estimates remain positive, but both lower confidence bounds are negative.
The joint hypothesis is therefore **rejected**. No execution-robustness improvement is
claimed.

## Provenance

- Source workflow: `29894309496`, attempt 2.
- Source artifact: `8519440629`, `quant-research-source-631-attempt-2`.
- Artifact SHA-256:
  `73991c41492bd0ffe101f3ea86149e67751b15724854a73bc9dbb6762fd7c0b4`.
- Executed source head: `a944956c4859dafc59a7364c3b98d0e26b9d0e96`.
- BTC return-file SHA-256:
  `539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73`.
- ETH return-file SHA-256:
  `027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6`.
- Observations: 2,340 per market, 2020-01-11 through 2026-06-07 UTC.

## Limitations

BTC-USDT and ETH-USDT are development markets, not untouched holdouts. The additional
20-bps charge is a predeclared stress, not an empirically calibrated order-book impact
model. The analysis does not estimate capacity, latency, partial fills, or venue-specific
spread dynamics.
