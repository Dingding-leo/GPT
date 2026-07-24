# Prior-Fold Performance Regime Consistency

## Hypothesis

For both BTC-USDT and ETH-USDT, persisted net rolling out-of-sample returns have a positive annualized arithmetic mean after both a positive and a non-positive immediately preceding OOS fold. The joint hypothesis passes only if all four 95% moving-block-bootstrap lower bounds are above zero.

## Economic rationale

A credible adaptive research process should not require exclusively favorable or unfavorable immediately preceding OOS performance. The previous fold is fully observed before the current fold begins, so this is a prior-only operating-regime diagnostic rather than a same-fold conditioning rule.

## Fixed specification

- OKX spot BTC-USDT and ETH-USDT, `1Dutc` development evidence.
- Persisted net strategy returns with the repository's one-bar delay and 10-bps transaction cost.
- Twenty-six non-overlapping 90-day OOS folds per market; fold 1 is excluded because it has no prior OOS fold.
- Previous-fold regime: compounded net return strictly above zero versus non-positive.
- Current-fold metric: conditional arithmetic mean of daily net returns multiplied by 365.
- Non-circular moving blocks of three complete folds, 2,000 resamples, 95% confidence.
- Previous-fold labels are recomputed after every bootstrap block concatenation.
- Exactly one candidate specification; no alternative lookback, threshold, block length, seed, market subset, fee, execution delay, or acceptance threshold was searched.

## Results

| Market | Previous-fold regime | Current folds | Observations | Annualized mean | 95% interval | P(mean > 0) |
|---|---|---:|---:|---:|---:|---:|
| BTC-USDT | Positive | 12 | 1,080 | 32.338822% | -13.335551% to 74.898964% | 86.65% |
| BTC-USDT | Non-positive | 13 | 1,170 | 12.601205% | -7.466936% to 59.885156% | 89.40% |
| ETH-USDT | Positive | 16 | 1,440 | 17.476437% | -18.531027% to 48.137435% | 83.50% |
| ETH-USDT | Non-positive | 9 | 810 | 17.478002% | -5.738637% to 52.357904% | 93.50% |

## Verdict

**Rejected.** All four point estimates are positive, but every lower confidence bound is non-positive. No prior-fold-conditioned trading rule, strategy improvement, or alpha claim is supported.

Candidate accounting: one searched, zero passed, one rejected. `result.json` records all four failure reasons.

## Real-data provenance

- Source workflow: `29902829833`, attempt 1.
- Source artifact: `8522613577`, `quant-research-source-755-attempt-1`.
- Artifact SHA-256: `9955cfa0f2faefeddf8cb63e3fcf4765e0ccbd32c4c866824733c93ed4160e9c`.
- Source head: `ef8f0f88df3aa38dfa9992028ba8a75f404f120a`.
- Tested base: `aa594f8cca0769aa7004ac14593025d007d7a537`.
- BTC-USDT returns SHA-256: `539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73`.
- ETH-USDT returns SHA-256: `027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6`.
- Period: 2020-01-11 through 2026-06-07 UTC; 2,340 observations per market.

## Limitations

BTC-USDT and ETH-USDT are development markets, not untouched holdouts. Only 25 current folds per market have a prior fold. Moving-block concatenation creates artificial fold joins, although the regime label is recomputed after each join. The experiment does not model spread, order-book impact, liquidity, capacity, latency, or partial fills.
