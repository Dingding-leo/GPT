# Volatility-Matched Expected Shortfall Versus Volatility-Targeted Long

## Hypothesis

BTC-USDT and ETH-USDT net rolling out-of-sample strategy returns have less severe 5% expected shortfall than the persisted volatility-targeted-long benchmark after that benchmark is scaled to the strategy's sample volatility.

The economic question is whether the previously observed tail-loss reduction versus volatility-targeted long reflects a better return-distribution shape rather than only lower realised volatility or exposure.

## Fixed design

- Provider: OKX spot.
- Markets: BTC-USDT and ETH-USDT development evidence.
- Timeframe: `1Dutc`.
- Observations: 2,385 persisted net rolling OOS rows per market, January 11, 2020 through July 22, 2026 UTC.
- Strategy and benchmark returns are aligned on identical timestamps.
- Expected shortfall is the mean of the worst `ceil(5% × n)` returns.
- The volatility-targeted-long benchmark is multiplied by `sample_std(strategy, ddof=1) / sample_std(benchmark, ddof=1)`.
- The scale is recomputed inside every paired bootstrap resample.
- Paired non-circular moving-block bootstrap: 20-session blocks, 2,000 resamples, 95% confidence.
- Exactly one joint candidate was tested.

Positive delta means the strategy expected shortfall is less negative than the volatility-matched benchmark.

## Result

| Market | Volatility scale | Strategy ES | Matched benchmark ES | Delta | 95% interval | P(delta > 0) |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 0.473946 | -2.901984% | -2.806480% | -0.095504% | -0.331327% to +0.156858% | 22.60% |
| ETH-USDT | 0.472248 | -3.348469% | -2.930493% | -0.417977% | -0.659017% to -0.144822% | 0.10% |

## Verdict: rejected

Both point estimates favor the volatility-matched benchmark, not the adaptive strategy. BTC-USDT's confidence interval crosses zero; ETH-USDT's complete interval is negative.

Candidate accounting:

- searched: 1;
- passed: 0;
- rejected: 1.

The unscaled expected-shortfall advantage versus volatility-targeted long is not shown to survive simple sample-volatility matching. This does not prove the strategy lacks all risk-control value; it rejects only the fixed tail-shape advantage tested here.

## Provenance

- Source workflow: `29996094865`.
- Source artifact: `8559031387`, `quant-research-source-1839-attempt-1`.
- Source artifact SHA-256: `9d7f5c91ac46c8a3d5a3b0d34f569936bd70bc4197161ae5d977c2c6730e0c04`.
- Source code commit: `d2d569ee2e20d4fc4172e5339a2aa06862d66ea8`.
- Source main base: `d1433f4e423861b953736f812f76cf24ac00de89`.
- Merged main commit: `7928c12f53d0d4f8149ed9d5c4205eaa2ba072f5`.
- BTC return SHA-256: `ebf2e4cc63e6b21a2d89420e2c2dd5b3517179baacfd12931f75fb0d99bdd2ce`.
- ETH return SHA-256: `bd4fbc471d506069c01b86b39f7726b1bd05752bfd64e75b7d677d2d7f473047`.

The executable verifies both full return-file digests before parsing or metric calculation. Tests use a 40-row unchanged real OKX BTC-USDT extract with source artifact and SHA-256 provenance.

## Limitations

BTC-USDT and ETH-USDT remain development markets rather than untouched holdouts. Sample-volatility matching is descriptive and is not a tradable ex ante scaling rule. Moving-block concatenation introduces artificial joins. Expected shortfall remains sensitive to the fixed 5% convention. Nonlinear impact, capacity, latency, changing spreads, and partial fills remain unmodelled beyond persisted linear transaction costs.
