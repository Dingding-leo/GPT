# Exposure Efficiency Versus Volatility-Targeted Long

## Hypothesis

BTC-USDT and ETH-USDT net rolling out-of-sample strategy returns have higher annualized net arithmetic return per executed exposure-day than the persisted volatility-targeted-long benchmark.

The economic question is whether adaptive timing earns more net return for each unit of capital actually committed, rather than appearing defensive mainly because it spends less time invested.

## Fixed design

- Provider: OKX spot; timeframe: `1Dutc`.
- Development markets: BTC-USDT and ETH-USDT.
- Observations: 2,385 aligned rolling OOS rows per market from 2020-01-11 through 2026-07-22 UTC.
- Strategy returns and executed positions are read from the persisted rolling OOS outputs.
- Volatility-targeted-long positions are independently reconstructed from immutable snapshots using a 30-session volatility estimate, 50% annual target, long/cash cap 1, one-session delay, 10-bps turnover cost, and cash entry at the OOS boundary.
- Reconstructed benchmark returns must match the persisted benchmark-return column within `5e-15`.
- Exposure efficiency is `365 * sum(net daily arithmetic returns) / sum(executed position)`.
- Paired non-circular moving-block bootstrap: 20-session blocks, 2,000 resamples, 95% confidence.
- Exactly one joint candidate was tested.

## Result

| Market | Strategy average exposure | Benchmark average exposure | Strategy efficiency | Benchmark efficiency | Delta | 95% interval | P(delta > 0) |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 0.268649 | 0.871030 | 0.626944 | 0.419048 | +0.207896 | -0.301230 to +0.754327 | 77.25% |
| ETH-USDT | 0.215729 | 0.730844 | 0.649832 | 0.674422 | -0.024591 | -0.676648 to +0.646293 | 49.10% |

## Verdict: rejected

Both markets fail the predeclared joint rule because neither 95% lower confidence bound is positive. BTC has a favorable point estimate but substantial uncertainty; ETH has a slightly negative point estimate. Candidate accounting is `searched=1`, `passed=0`, `rejected=1`.

No alpha, capital-efficiency, or deployable strategy improvement is claimed. The result says only that the adaptive process has not demonstrated reliably higher net arithmetic return per exposure-day than the existing defensive benchmark.

## Provenance

- Source workflow: `30006567781`.
- Source artifact: `8563252094`, `quant-research-source-1960-attempt-1`.
- Source artifact SHA-256: `e42b2b125328c945ace98c41c48a84d6b10d1876da03e20ee8fc3f25335e04e8`.
- Workflow head: `8d5ca1d00aee75c3ef2303d62784d9c6fcfe5888`.
- Manifest code commit: `72144e9f22dfeceda744d33222d3e0512e489a9d`.

Complete return and snapshot hashes are persisted in `result.json` and verified before parsing.

## Limitations

- BTC-USDT and ETH-USDT are development markets, not untouched holdouts.
- Exposure efficiency uses summed arithmetic returns and exposure-days; it is not a continuous-capital or margin-usage attribution.
- Moving-block concatenation creates artificial joins and preserves dependence only within 20-session blocks.
- The benchmark reconstruction assumes close-price execution, fixed linear costs, and no spread variation, nonlinear impact, capacity, latency, or partial fills.
