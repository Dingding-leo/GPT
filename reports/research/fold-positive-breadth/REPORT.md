# Positive OOS Fold Breadth

## Hypothesis

BTC-USDT and ETH-USDT should each produce a positive compounded net return in more than half of their 26 non-overlapping 90-session rolling out-of-sample folds. The hypothesis passes only if the 95% moving-block-bootstrap lower bound for the positive-fold share is strictly above 50% in both development markets.

Economic rationale: a credible adaptive process should work across a broad majority of deployment windows rather than depend on a minority of unusually profitable folds.

## Predeclared design

- one joint candidate;
- persisted net rolling OOS returns from OKX spot BTC-USDT and ETH-USDT `1Dutc`;
- 26 complete 90-session folds per market;
- fold success means compounded net strategy return is greater than zero;
- non-circular moving-block bootstrap over consecutive fold returns;
- block length of three folds, 2,000 resamples, 95% confidence;
- fixed seeds `2026072301` for BTC and `2026072302` for ETH;
- pass only when both lower confidence bounds exceed 0.5.

Canonical signature:

`positive-fold-breadth-v1|markets=BTC-USDT,ETH-USDT|source=persisted-net-rolling-oos-returns|folds=26x90-nonoverlapping|fold-metric=compounded-net-return|success=fold-return>0|claim=positive-fold-share>0.5-in-both-markets|resampling=noncircular-moving-block-bootstrap-over-consecutive-folds|block-length=3-folds|resamples=2000|confidence=0.95|seeds=BTC-USDT:2026072301,ETH-USDT:2026072302`

No alternative fold length, block length, success threshold, seed, market subset, fee, execution delay, or acceptance rule was selected after observing the result.

## Results

| Market | Positive folds | Positive-fold share | Median fold return | 95% interval | P(share > 50%) |
|---|---:|---:|---:|---:|---:|
| BTC-USDT | 12 / 26 | 46.1538% | -0.0802% | 30.7692% to 69.2308% | 42.20% |
| ETH-USDT | 16 / 26 | 61.5385% | 2.4270% | 46.1538% to 80.7692% | 91.90% |

## Verdict

**Rejected.** BTC had fewer than half of folds positive. ETH had a positive point share, but its 95% lower bound remained below 50%. One candidate was searched, zero passed, and one was rejected.

This is a breadth diagnostic, not a new trading rule. It does not modify parameters, signals, costs, execution timing, or holdout boundaries.

## Provenance

- provider: OKX spot;
- timeframe: `1Dutc`;
- development period: 2020-01-11 through 2026-06-07 UTC;
- source workflow: `29931682704`;
- source artifact: `8534337020` (`quant-research-source-1112-attempt-1`);
- archive SHA-256: `d0e890b3aeefbff8420f6f8dbfcb7be6cf332839b206bde5b64566ac1b1600af`;
- source head: `07b2baf4a1112767ec45c865fbf0381b28ba69b7`;
- BTC return-file SHA-256: `539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73`;
- ETH return-file SHA-256: `027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6`.

## Limitations

BTC and ETH are development markets, not untouched holdouts. Three-fold blocks preserve complete 90-session paths and short-range ordering but treat sampled block joins as valid and cannot capture dependence beyond three folds. Spread, market impact, liquidity, capacity, latency, and partial fills remain unmodelled beyond persisted transaction costs.
