# Expected-shortfall comparison with buy-and-hold

## Hypothesis

BTC-USDT and ETH-USDT net rolling out-of-sample strategy returns each have less severe
5% expected shortfall than persisted net buy-and-hold returns. The joint hypothesis passes
only if both 95% paired moving-block-bootstrap lower bounds for
`strategy expected shortfall - buy-and-hold expected shortfall` are strictly positive.

Economic rationale: a long/cash risk-control process should reduce the average severity of
its worst realised sessions relative to continuously invested market exposure, not merely
reduce one path-dependent maximum drawdown.

## Fixed specification

- Provider and market type: OKX spot.
- Development markets: BTC-USDT and ETH-USDT.
- Timeframe: `1Dutc`.
- Source: persisted net rolling OOS strategy and buy-and-hold returns on identical rows.
- Expected shortfall: arithmetic mean of the worst `ceil(5% × n)` observed returns.
- Positive delta means the strategy tail mean is less negative than buy-and-hold.
- Paired non-circular moving-block bootstrap over observed strategy/benchmark rows.
- Block length: 20 sessions.
- Resamples: 2,000.
- Confidence: 95%.
- Candidate count: one joint hypothesis.
- No alternative benchmark, tail fraction, quantile convention, block length, seed,
  market subset, fee, execution delay, fold definition, or pass threshold was selected after
  observing the result.

Canonical signature:

```text
expected-shortfall-vs-buy-and-hold-v1|markets=BTC-USDT,ETH-USDT|source=persisted-net-rolling-oos-returns|benchmark=buy-and-hold|metric=mean-worst-ceil-5pct-returns|tail-fraction=0.05|claim=strategy-minus-benchmark-expected-shortfall>0-in-both-markets|resampling=paired-noncircular-moving-block-bootstrap|block-length=20-sessions|resamples=2000|confidence=0.95|seeds=BTC-USDT:2026072313,ETH-USDT:2026072314|candidate_count=1
```

## Results

| Market | Strategy ES | Buy-and-hold ES | Reduction | 95% interval | P(reduction > 0) |
|---|---:|---:|---:|---:|---:|
| BTC-USDT | -2.901984% | -7.161942% | +4.259958% | +3.440215% to +5.181492% | 100.00% |
| ETH-USDT | -3.348469% | -9.453811% | +6.105342% | +5.055792% to +7.228965% | 100.00% |

Each market contributes 2,385 daily observations from January 11, 2020 through July 22,
2026 UTC. The expected-shortfall tail contains 120 observations per market.

## Verdict

**Supported for this fixed development-market diagnostic.** Both lower confidence bounds are
strictly positive. Candidate accounting is `searched=1`, `passed=1`, `rejected=0`.

The result supports the limited claim that the persisted long/cash strategy has less severe
5% daily expected shortfall than continuously invested buy-and-hold in both development
markets under the fixed specification. It does not establish alpha, benchmark-relative return
superiority, an untouched-holdout result, or a deployable strategy improvement.

## Provenance

- Source workflow: `29973627370`.
- Source artifact: `8550634027`, `quant-research-source-1553-attempt-1`.
- Source artifact SHA-256:
  `60eeccc96a8baee381cde8e49c519543ce274bfcb48af4fa6bcb016ebc93aaf2`.
- Source workflow head: `3375a17230726d8587f3a07398841c6dd861c2cf`.
- Source main base: `7282c22dffc8006d844dcb3095935f0e3e0ea70f`.
- BTC return SHA-256:
  `ebf2e4cc63e6b21a2d89420e2c2dd5b3517179baacfd12931f75fb0d99bdd2ce`.
- ETH return SHA-256:
  `bd4fbc471d506069c01b86b39f7726b1bd05752bfd64e75b7d677d2d7f473047`.
- The executable verifies both return-file digests before CSV parsing, resampling, or output
  directory creation; mismatched bytes fail closed and cannot produce performance evidence.

## Limitations

BTC-USDT and ETH-USDT remain development markets rather than untouched holdouts. Expected
shortfall is sensitive to the fixed 5% tail convention. Moving-block concatenation introduces
artificial joins while preserving paired rows and within-block ordering. The comparison to
buy-and-hold partly reflects lower market exposure. Nonlinear impact, capacity, latency,
spread variation, and partial fills remain unmodelled beyond persisted transaction costs.
