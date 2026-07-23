# Conditional drawdown versus volatility-targeted benchmark

## Hypothesis

BTC-USDT and ETH-USDT net rolling out-of-sample strategy returns each have less severe 5% conditional drawdown than the persisted volatility-targeted-long benchmark. The joint hypothesis passes only if both 95% paired moving-block-bootstrap lower bounds for the strategy-minus-benchmark conditional-drawdown delta are strictly positive.

Canonical signature:

`conditional-drawdown-vs-volatility-benchmark-v1|markets=BTC-USDT,ETH-USDT|source=persisted-net-rolling-oos-returns|benchmark=volatility-targeted-long|drawdown=nav-with-initial-one-over-running-peak-minus-one|metric=mean-deepest-ceil-5pct-drawdown-observations|tail-fraction=0.05|claim=strategy-minus-benchmark-conditional-drawdown>0-in-both-markets|resampling=paired-noncircular-moving-block-bootstrap-recompute-nav-and-drawdown|block-length=20-sessions|resamples=2000|confidence=0.95|seeds=BTC-USDT:2026072319,ETH-USDT:2026072320|candidate_count=1`

## Economic rationale

Maximum drawdown depends on one worst peak-to-trough event, while Ulcer Index averages the complete drawdown path. Conditional drawdown at risk instead isolates the deepest 5% of underwater observations. A defensive long/cash process should reduce this persistent severe-underwater state relative to its volatility-targeted benchmark, not merely improve one maximum drawdown.

## Fixed specification

- Real OKX spot BTC-USDT and ETH-USDT `1Dutc` returns.
- Persisted net rolling OOS strategy and volatility-targeted-long benchmark returns on identical timestamps.
- NAV starts at 1.0; drawdown is `NAV / running_peak - 1`.
- Conditional drawdown is the mean of the deepest `ceil(5% × n)` drawdown observations.
- Paired non-circular moving-block bootstrap, 20-session blocks, 2,000 resamples, 95% confidence.
- NAV and drawdown are recomputed after each paired return resample.
- Exactly one candidate was searched; no threshold, benchmark, block length, market subset, or acceptance rule was changed after observing results.

## Results

| Market | Strategy conditional drawdown | Benchmark conditional drawdown | Reduction | 95% interval | P(reduction > 0) |
|---|---:|---:|---:|---:|---:|
| BTC-USDT | -25.755593% | -68.643142% | +42.887549% | +5.499141% to +53.432902% | 99.40% |
| ETH-USDT | -27.339676% | -62.362074% | +35.022397% | -1.705687% to +48.405795% | 96.20% |

Candidate accounting:

```text
searched: 1
passed:   0
rejected: 1
```

## Verdict

**Rejected.** BTC-USDT passed, but ETH-USDT's lower confidence bound was non-positive. The joint claim therefore fails. No strategy improvement or deployable rule is claimed.

## Provenance

- Source workflow: `29980035904`.
- Source artifact: `8552853195`, `quant-research-source-1633-attempt-1`.
- Source artifact SHA-256: `462f6ea87ea0501916645e936282eeaecef9ed004723e6ec61a1ad63ced6c9e5`.
- Source code head: `a76d802ad92e63ab2dadadd95a1890a15f16e7cb`.
- BTC returns SHA-256: `ebf2e4cc63e6b21a2d89420e2c2dd5b3517179baacfd12931f75fb0d99bdd2ce`.
- ETH returns SHA-256: `bd4fbc471d506069c01b86b39f7726b1bd05752bfd64e75b7d677d2d7f473047`.
- Period: 2020-01-11 through 2026-07-22 UTC.
- Observations: 2,385 per market; deepest-tail observations: 120 per market.

## Limitations

BTC and ETH remain development markets rather than untouched holdouts. Conditional drawdown is path-dependent, so moving-block concatenation creates artificial joins even though paired rows and within-block order are preserved and NAV is recomputed. The comparison is not volatility matched. Nonlinear impact, capacity, changing spreads, latency, and partial fills remain unmodelled beyond persisted linear costs.
