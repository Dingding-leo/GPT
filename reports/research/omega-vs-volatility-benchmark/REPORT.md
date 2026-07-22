# Omega Ratio Versus Volatility-Targeted Benchmark

## Hypothesis

BTC-USDT and ETH-USDT net rolling OOS strategy returns each have a higher zero-threshold Omega
ratio than the persisted volatility-targeted-long benchmark. The joint hypothesis passes only if
both 95% paired moving-block-bootstrap lower bounds for the strategy-minus-benchmark Omega delta
are strictly positive.

## Economic rationale

Sortino evaluates average return against downside deviation, but it does not directly compare the
entire mass of gains with the entire mass of losses. Omega at a zero threshold measures that full
gain-to-loss balance. A long/cash risk-control strategy should justify its complexity through a
reliably better realized gain/loss distribution than the volatility-targeted-long benchmark.

Exactly one joint candidate was evaluated. No alternate benchmark, threshold, Omega convention,
block length, seed, confidence threshold, market subset, fee, execution delay, fold, or candidate
selection rule was chosen after observing the result.

## Fixed design

- Provider and markets: OKX spot BTC-USDT and ETH-USDT.
- Timeframe: `1Dutc`.
- Evidence: persisted net rolling OOS strategy and benchmark returns.
- Benchmark: volatility-targeted long.
- Omega threshold: zero.
- Omega definition: `sum(max(return, 0)) / abs(sum(min(return, 0)))`.
- Resampling: paired non-circular moving blocks over observed strategy/benchmark rows.
- Block length: 20 sessions.
- Resamples: 2,000.
- Confidence: 95%.
- Acceptance: both lower confidence bounds strictly above zero.

## Results

| Market | Strategy Omega | Benchmark Omega | Delta | 95% interval | P(delta > 0) |
|---|---:|---:|---:|---:|---:|
| BTC-USDT | 1.183219 | 1.120161 | +0.063058 | -0.083895 to +0.234717 | 79.60% |
| ETH-USDT | 1.129094 | 1.143133 | -0.014039 | -0.158925 to +0.128184 | 38.70% |

## Verdict

**Rejected.** Both 95% lower confidence bounds are non-positive, and ETH-USDT's point Omega ratio
is below the benchmark. The evidence does not establish a superior full-distribution gain/loss
balance in both development markets. No strategy improvement or deployable rule is claimed.

Candidate accounting: one searched, zero passed, one rejected.

## Real-data provenance

- Source workflow: `29946477873`.
- Source artifact: `8540375016`, `quant-research-source-1276-attempt-1`.
- Artifact SHA-256: `d6434dfc7e03ce664fce6e0a86455fb0f025588f17d14fe8dd27f0b6937bc52f`.
- Source head: `60b68e7f4675f0441dbda723bbf6bf6f35d56f2d`.
- BTC return-file SHA-256: `539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73`.
- ETH return-file SHA-256: `027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6`.
- OOS period: 2020-01-11 through 2026-06-07 UTC.
- Observations: 2,340 per market.

## Limitations

BTC and ETH remain development markets rather than untouched holdouts. Moving-block sampling
preserves observed paired rows and within-block ordering but creates artificial joins and does not
preserve dependence beyond 20 sessions. Zero-threshold Omega is one declared distributional metric
and does not model spread, nonlinear impact, capacity, latency, or partial fills beyond persisted
transaction costs.
