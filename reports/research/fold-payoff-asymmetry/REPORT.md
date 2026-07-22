# Fold Payoff Asymmetry

## Hypothesis

BTC-USDT and ETH-USDT each have aggregate positive compounded net returns across their 26 non-overlapping 90-session OOS folds that exceed the absolute aggregate negative fold returns. The joint hypothesis passes only if both 95% moving-block-bootstrap lower bounds for the fold payoff ratio are strictly above one.

The fold payoff ratio is:

```text
sum(positive compounded fold returns) / abs(sum(negative compounded fold returns))
```

This is a fold-level payoff-asymmetry diagnostic, not trade-level profit factor.

## Economic rationale

The positive-fold-breadth test found that BTC had fewer than half of folds positive and that ETH's positive-fold share was not statistically above one half. A process can nevertheless have positive expectancy if winning folds are materially larger than losing folds. This fixed test asks whether that payoff asymmetry is reliable after preserving short-range fold ordering.

Exactly one joint candidate was evaluated. No alternative fold size, ratio definition, block length, seed, confidence threshold, fee, delay, market subset, or acceptance rule was selected after viewing the result.

## Fixed design

- Provider and markets: OKX spot BTC-USDT and ETH-USDT.
- Timeframe: `1Dutc`.
- Evidence: persisted net rolling OOS returns.
- Folds: 26 complete non-overlapping folds of 90 observations.
- Fold return: compounded net strategy return.
- Resampling: non-circular moving blocks over consecutive fold returns.
- Block length: three folds.
- Resamples: 2,000.
- Confidence: 95%.
- Acceptance: both lower confidence bounds strictly above one.

## Results

| Market | Positive / negative / zero folds | Total positive folds | Absolute total negative folds | Payoff ratio | 95% interval | P(ratio > 1) |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 12 / 13 / 1 | 234.4051% | 93.2591% | 2.5135 | 0.9066 to 10.3247 | 96.15% |
| ETH-USDT | 16 / 10 / 0 | 185.1586% | 91.6059% | 2.0213 | 0.8408 to 9.3839 | 95.25% |

## Verdict

**Rejected.** Both point ratios exceed one, but both 95% lower bounds are below one. The evidence does not establish reliable fold-level payoff asymmetry in both development markets. No strategy improvement or deployable fold rule is claimed.

Candidate accounting: one searched, zero passed, one rejected.

## Real-data provenance

- Source workflow: `29936458263`.
- Source artifact: `8536340303`, `quant-research-source-1159-attempt-1`.
- Artifact SHA-256: `83eb247b7d848ddc61ebbb914e937268af0352ed1cbb11371877e6d947de1fb3`.
- Source head: `88a8280d3a29153ab9fdd976ffb68899c975a908`.
- BTC return-file SHA-256: `539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73`.
- ETH return-file SHA-256: `027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6`.
- OOS period: 2020-01-11 through 2026-06-07 UTC.
- Observations: 2,340 per market.

## Limitations

BTC and ETH remain development markets rather than untouched holdouts. Three-fold blocks preserve complete fold paths and short-range ordering, but sampled joins are artificial and dependence beyond three folds is not preserved. Summing fold-level percentage returns is a payoff diagnostic rather than a capital-continuous portfolio reconstruction. Spread, nonlinear impact, capacity, latency, and partial fills remain unmodeled beyond persisted costs.
