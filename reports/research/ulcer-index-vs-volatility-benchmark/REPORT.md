# Ulcer Index versus volatility-targeted long

## Hypothesis

BTC-USDT and ETH-USDT net rolling out-of-sample strategy returns have a lower Ulcer Index than the persisted volatility-targeted-long benchmark. The joint hypothesis passes only if both 95% paired moving-block-bootstrap lower bounds for `benchmark Ulcer Index - strategy Ulcer Index` are strictly positive.

## Economic rationale

Maximum drawdown records only the worst peak-to-trough event, while underwater fraction records only whether equity is below its prior peak. Ulcer Index combines drawdown depth and persistence by taking the root mean square of the complete drawdown path. A long/cash risk-control process should reduce this sustained drawdown burden relative to a volatility-targeted long benchmark, not merely improve one isolated maximum-drawdown observation.

## Fixed design

- Markets: OKX spot BTC-USDT and ETH-USDT `1Dutc`; both are development markets.
- Source: persisted net rolling OOS strategy and volatility-targeted-long returns.
- Ulcer Index: `sqrt(mean((nav / running_peak - 1)^2))`, with NAV beginning at 1.
- Reduction: benchmark Ulcer Index minus strategy Ulcer Index; positive values favor the strategy.
- Paired non-circular moving-block bootstrap over observed strategy/benchmark rows.
- Block length: 20 sessions.
- Resamples: 2,000.
- Confidence: 95%.
- Seeds: BTC-USDT `2026072309`; ETH-USDT `2026072310`.
- Candidate count: one joint hypothesis. No alternate benchmark, drawdown convention, block length, seed, market subset, or acceptance rule was selected after observing the result.

## Results

| Market | Strategy Ulcer Index | Benchmark Ulcer Index | Reduction | 95% interval | P(reduction > 0) |
|---|---:|---:|---:|---:|---:|
| BTC-USDT | 0.137989 | 0.351861 | +0.213872 | +0.003708 to +0.416441 | 97.75% |
| ETH-USDT | 0.157634 | 0.332082 | +0.174448 | -0.065478 to +0.346200 | 91.70% |

BTC-USDT passed this specification, but ETH-USDT did not because its lower confidence bound was negative. The joint hypothesis is therefore **rejected**.

Candidate accounting: searched `1`, passed `0`, rejected `1`.

No deployable strategy improvement is claimed.

## Provenance

- Source workflow: `29952479109`.
- Source artifact: `8542699045`, `quant-research-source-1321-attempt-1`.
- Artifact SHA-256: `edf630f5372209f12ccc770751872f82523624ccafdfd7c849bae1971ab4aefc`.
- Source head: `0945532759010d0d94638c69ea0e5a175c4ae964`.
- OOS period: 2020-01-11 through 2026-06-07 UTC.
- Observations: 2,340 per market.
- BTC returns SHA-256: `539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73`.
- ETH returns SHA-256: `027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6`.

## Limitations

BTC and ETH are development markets, not untouched holdouts. Ulcer Index is path-dependent, and moving-block concatenation creates artificial joins even though it preserves observed paired rows and within-block serial ordering. The analysis retains the repository's persisted transaction costs but does not model nonlinear impact, capacity, latency, or partial fills.
