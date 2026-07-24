# Expected Shortfall Versus Volatility-Targeted Long

## Hypothesis

BTC-USDT and ETH-USDT net rolling out-of-sample strategy returns have less severe 5% expected shortfall than the persisted volatility-targeted-long benchmark.

The economic question is whether the adaptive long/cash process reduces average losses in the worst realised sessions relative to the repository's existing defensive benchmark, not only relative to continuous buy-and-hold.

## Fixed design

- Provider: OKX spot.
- Markets: BTC-USDT and ETH-USDT development evidence.
- Timeframe: `1Dutc`.
- Observations: 2,385 persisted net rolling OOS rows per market, January 11, 2020 through July 22, 2026 UTC.
- Strategy and benchmark returns remain aligned on identical timestamps.
- Expected shortfall is the mean of the worst `ceil(5% × n)` returns.
- Paired non-circular moving-block bootstrap: 20-session blocks, 2,000 resamples, 95% confidence.
- Exactly one joint candidate was tested.

Positive delta means the strategy expected shortfall is less negative than the volatility-targeted-long benchmark.

## Result

| Market | Strategy ES | Benchmark ES | Reduction | 95% interval | P(reduction > 0) |
|---|---:|---:|---:|---:|---:|
| BTC-USDT | -2.901984% | -5.921516% | +3.019532% | +2.368885% to +3.762780% | 100.00% |
| ETH-USDT | -3.348469% | -6.205407% | +2.856938% | +2.275673% to +3.502403% | 100.00% |

## Verdict: supported, narrowly scoped

Both paired moving-block-bootstrap lower bounds are strictly positive.

Candidate accounting:

- searched: 1;
- passed: 1;
- rejected: 0.

The result supports only the fixed claim that the adaptive strategy's daily 5% expected shortfall was less severe than the persisted volatility-targeted-long benchmark in both development markets. It does not establish alpha, higher aggregate return, untouched-holdout validity, or a deployable improvement. The comparison is not volatility matched, so lower realised exposure or volatility may explain part of the difference.

## Provenance

- Source workflow: `29977584146`.
- Source artifact: `8552001681`, `quant-research-source-218-final`.
- Source artifact SHA-256: `e875970e048fdb6eb1a946330a8229ac445378a165c196de5e88abdde4b14576`.
- Source code commit: `0aeb79ba909be8b8be8e07f4c11b1f2b0fd32cec`.
- Source main base: `1396124ff04da6dc28d7020945d315e0c61a7a82`.
- BTC return SHA-256: `ebf2e4cc63e6b21a2d89420e2c2dd5b3517179baacfd12931f75fb0d99bdd2ce`.
- ETH return SHA-256: `bd4fbc471d506069c01b86b39f7726b1bd05752bfd64e75b7d677d2d7f473047`.

The executable verifies both return-file digests before parsing or calculation.

## Limitations

BTC-USDT and ETH-USDT are development markets, not untouched holdouts. Moving-block concatenation introduces artificial joins. Expected shortfall depends on the fixed 5% convention. The volatility-targeted-long benchmark has higher realised tail losses in this sample, but the analysis does not isolate whether that difference comes from exposure, volatility, timing, or distribution shape. Nonlinear impact, capacity, latency, changing spreads, and partial fills remain unmodelled beyond persisted linear transaction costs.
