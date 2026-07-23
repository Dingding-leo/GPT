# Volatility-Matched Expected Shortfall Versus Buy-and-Hold

## Hypothesis

BTC-USDT and ETH-USDT net rolling out-of-sample strategy returns have less severe 5% expected shortfall than buy-and-hold after buy-and-hold is scaled to the strategy's sample volatility.

This is a fixed follow-up to the raw expected-shortfall comparison in PR #212. The economic question is whether the observed tail-loss reduction reflects a better return-distribution shape, rather than only the strategy's lower market exposure and lower volatility.

## Fixed design

- Provider: OKX spot.
- Markets: BTC-USDT and ETH-USDT development evidence.
- Timeframe: `1Dutc`.
- Observations: 2,385 persisted net rolling OOS rows per market, January 11, 2020 through July 22, 2026 UTC.
- Strategy and buy-and-hold returns remain aligned on identical timestamps.
- Expected shortfall is the mean of the worst `ceil(5% × n)` returns.
- Buy-and-hold is multiplied by `sample_std(strategy) / sample_std(buy_and_hold)`, using `ddof=1`.
- The scale is recomputed inside every paired bootstrap resample; it is not fixed from the observed sample.
- Paired non-circular moving-block bootstrap: 20-session blocks, 2,000 resamples, 95% confidence.
- Exactly one joint candidate was tested.

Positive delta means the strategy expected shortfall is less negative than the volatility-matched benchmark.

## Result

| Market | Volatility scale | Strategy ES | Matched buy-and-hold ES | Delta | 95% interval | P(delta > 0) |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 0.386134 | -2.901984% | -2.765471% | -0.136512% | -0.396816% to +0.151357% | 17.80% |
| ETH-USDT | 0.310461 | -3.348469% | -2.935044% | -0.413425% | -0.665937% to -0.125863% | 0.30% |

## Verdict: rejected

Both point estimates favor volatility-matched buy-and-hold, not the adaptive strategy. BTC-USDT's confidence interval crosses zero. ETH-USDT's complete interval is negative.

Candidate accounting:

- searched: 1;
- passed: 0;
- rejected: 1.

The raw expected-shortfall reduction versus unscaled buy-and-hold is therefore not shown to survive simple sample-volatility matching. This does not prove the strategy lacks all risk-control value; it rejects the narrower tail-shape advantage under this fixed normalization and inference design.

## Provenance

- Source workflow: `29976177263`.
- Source artifact: `8551491583`, `quant-research-source-1580-attempt-1`.
- Source artifact SHA-256: `dc86c60ecff638ca3d9b6419e3d562391462588daec7466f64445168781c95ea`.
- Source code commit: `d9591ce1ba4d378f60cfc52e645ca8bd94442738`.
- Source main base: `2baa7cd6418184ca42fe7802f9e34b809476db1b`.
- BTC return SHA-256: `ebf2e4cc63e6b21a2d89420e2c2dd5b3517179baacfd12931f75fb0d99bdd2ce`.
- ETH return SHA-256: `bd4fbc471d506069c01b86b39f7726b1bd05752bfd64e75b7d677d2d7f473047`.

The executable verifies both return-file digests before parsing or calculation.

## Limitations

BTC-USDT and ETH-USDT are development markets, not untouched holdouts. Sample-volatility matching is a descriptive normalization, not a tradable ex ante leverage rule. Recomputing the scale in each resample propagates normalization uncertainty, but moving-block concatenation still creates artificial joins. Expected shortfall remains sensitive to the fixed 5% convention. Nonlinear impact, capacity, latency, changing spreads, and partial fills remain unmodelled beyond persisted linear transaction costs.
