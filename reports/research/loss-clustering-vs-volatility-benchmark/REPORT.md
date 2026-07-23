# Loss clustering versus volatility-targeted long

## Hypothesis

BTC-USDT and ETH-USDT net rolling out-of-sample strategy returns each have a lower probability of a loss immediately following a loss than the persisted volatility-targeted-long benchmark.

The fixed metric is `P(return_t < 0 | return_{t-1} < 0)`. The paired delta is benchmark probability minus strategy probability, so a positive value indicates that the strategy interrupts loss sequences more often. The joint claim passes only if both 95% paired moving-block-bootstrap lower bounds are strictly positive.

## Economic rationale

A defensive long/cash process should do more than scale individual losses. If its signals interrupt adverse persistence, consecutive losses should cluster less strongly than under the existing volatility-control benchmark. This diagnostic isolates loss-sequence dependence rather than return magnitude, maximum drawdown, expected shortfall, or average downside deviation.

## Fixed method

- Real OKX spot BTC-USDT and ETH-USDT `1Dutc` data.
- Persisted net rolling OOS strategy and volatility-targeted-long returns on identical timestamps.
- A loss is a net return strictly below zero; zero-return cash sessions are not losses.
- Loss clustering is the count of loss-to-loss transitions divided by the count of prior-loss observations.
- Paired non-circular moving-block bootstrap with 20-session blocks, 2,000 resamples, 95% confidence, and fixed market-specific seeds.
- Transitions across sampled block joins are excluded so artificial joins cannot create or break loss sequences.
- A one-observation remainder is redistributed across the final two sampled blocks, preventing singleton blocks that cannot contain a transition.
- Exactly one joint candidate was tested. No alternate sign threshold, transition definition, benchmark, block length, resample count, seed, market subset, fee, delay, fold rule, or acceptance threshold was selected after observing the result.

## Results

| Market | Strategy probability | Benchmark probability | Benchmark minus strategy | 95% interval | P(delta > 0) |
|---|---:|---:|---:|---:|---:|
| BTC-USDT | 46.618705% | 45.858241% | -0.760464 pp | -2.964201 to +2.198372 pp | 34.00% |
| ETH-USDT | 42.955801% | 45.343777% | +2.387976 pp | -0.135664 to +5.159892 pp | 97.05% |

BTC-USDT's point estimate is adverse: strategy losses were slightly more likely than benchmark losses to be followed by another loss. ETH-USDT's point estimate favors the strategy, but its lower confidence bound remains negative. Both markets therefore fail the predeclared joint rule.

## Verdict

**Rejected.** Candidate accounting: searched `1`, passed `0`, rejected `1`.

No loss-clustering advantage, alpha, aggregate-return superiority, or deployable strategy improvement is claimed. The result is recorded because reporting only favorable risk diagnostics would bias the research record.

## Provenance

- Source workflow: `29987295837`.
- Source artifact: `8555542657`, `quant-research-source-1737-attempt-1`.
- Source archive SHA-256: `4dbb277373d818c84487f021a2c02f268e95714c8aaf6c70672f3cd068f3c7c3`.
- Source code/merge-ref commit: `f25d1cb2a8068dc49c0e5e6c83c522a445f3ef28`.
- Current branch base: `d1ecd2c00ad0d1f4347af1f49f97569a36cc6331`.
- BTC return SHA-256: `ebf2e4cc63e6b21a2d89420e2c2dd5b3517179baacfd12931f75fb0d99bdd2ce`.
- ETH return SHA-256: `bd4fbc471d506069c01b86b39f7726b1bd05752bfd64e75b7d677d2d7f473047`.
- Period: 2020-01-11 through 2026-07-22 UTC.
- Observations: 2,385 per market.

## Limitations

BTC-USDT and ETH-USDT remain development markets, not untouched holdouts. The binary loss indicator discards loss magnitude and treats exact zero as non-loss. Moving blocks preserve within-block ordering but omit transitions at sampled joins and dependence beyond 20 sessions. The comparison does not isolate exposure, volatility, or timing effects. Nonlinear impact, capacity, changing spreads, latency, and partial fills remain unmodelled beyond persisted linear costs.
