# Return-skewness comparison with volatility-targeted long

## Hypothesis

BTC-USDT and ETH-USDT net rolling out-of-sample strategy returns each have higher
Fisher–Pearson adjusted sample skewness than the persisted volatility-targeted-long
benchmark. The joint hypothesis passes only if both 95% paired moving-block-bootstrap
lower bounds for `strategy skewness - benchmark skewness` are strictly positive.

Economic rationale: a defensive long/cash process should improve the asymmetry of realised
returns, not merely reduce their scale. A more positive return distribution would indicate that
large favourable observations dominate large adverse observations more strongly than in the
existing volatility-control benchmark.

## Fixed specification

- Provider and market type: OKX spot.
- Development markets: BTC-USDT and ETH-USDT.
- Timeframe: `1Dutc`.
- Source: persisted net rolling OOS strategy and volatility-targeted-long returns.
- Skewness: Fisher–Pearson adjusted sample skewness,
  `sqrt(n(n-1))/(n-2) × m3 / m2^(3/2)`.
- Paired non-circular moving-block bootstrap over observed strategy/benchmark rows.
- Block length: 20 sessions.
- Resamples: 2,000.
- Confidence: 95%.
- Candidate count: one joint hypothesis.
- No alternative benchmark, skewness estimator, block length, seed, market subset, fee,
  execution delay, fold definition, or pass threshold was selected after observing the result.

Canonical signature:

```text
return-skewness-vs-volatility-benchmark-v1|markets=BTC-USDT,ETH-USDT|source=persisted-net-rolling-oos-returns|benchmark=volatility-targeted-long|metric=fisher-pearson-adjusted-sample-skewness|claim=strategy-minus-benchmark-skewness>0-in-both-markets|resampling=paired-noncircular-moving-block-bootstrap|block-length=20-sessions|resamples=2000|confidence=0.95|seeds=BTC-USDT:2026072311,ETH-USDT:2026072312|candidate_count=1
```

## Results

| Market | Strategy skewness | Benchmark skewness | Delta | 95% interval | P(delta > 0) |
|---|---:|---:|---:|---:|---:|
| BTC-USDT | 0.600122 | -0.818171 | +1.418293 | +0.515833 to +2.151757 | 99.75% |
| ETH-USDT | 0.387066 | 0.128850 | +0.258217 | -0.622671 to +1.242984 | 69.20% |

## Verdict

**Rejected.** BTC-USDT passed the predeclared lower-bound criterion, but ETH-USDT did not.
The joint candidate therefore failed. Candidate accounting is `searched=1`, `passed=0`,
`rejected=1`.

The point estimates are more positively skewed than volatility-targeted long in both markets,
but the ETH uncertainty interval crosses zero. This does not establish a robust distributional
advantage, alpha, or deployable strategy improvement.

## Provenance

- Source workflow: `29972290952`.
- Source artifact: `8550139614`, `quant-research-source-1535-attempt-1`.
- Source artifact SHA-256:
  `e528db2a672d5880a9374c371df2250f51c89a4951b55fe3f2edde34a8db8662`.
- Source code commit recorded in the artifact manifest:
  `a0ccd28e2f3a2cbe9e05077147cc70a506f68de2`.
- BTC return SHA-256:
  `ebf2e4cc63e6b21a2d89420e2c2dd5b3517179baacfd12931f75fb0d99bdd2ce`.
- ETH return SHA-256:
  `bd4fbc471d506069c01b86b39f7726b1bd05752bfd64e75b7d677d2d7f473047`.
- Observations: 2,385 per market, January 11, 2020 through July 22, 2026 UTC.

## Limitations

BTC-USDT and ETH-USDT remain development markets rather than untouched holdouts. Sample
skewness is sensitive to extreme observations, and moving-block concatenation introduces
artificial joins even though row pairing and within-block order are preserved. The analysis
does not model nonlinear market impact, capacity, latency, spread variation, or partial fills
beyond the persisted transaction-cost model.
