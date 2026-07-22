# Lagged Cross-Market Correlation Regime Consistency

## Hypothesis

BTC-USDT and ETH-USDT persisted net rolling out-of-sample returns retain a positive
annualized arithmetic mean both when prior 60-session BTC/ETH market-return correlation is
above its prior expanding median and when it is below that median.

The economic rationale is that a robust strategy should not depend on one level of cross-market
coupling. High relative correlation can indicate common risk-factor dominance, while low relative
correlation can indicate more idiosyncratic market behavior.

## Predeclared candidate

Exactly one candidate was tested:

- markets: BTC-USDT and ETH-USDT;
- input: persisted net rolling OOS strategy returns and contemporaneous market returns;
- correlation: Pearson correlation of both asset-return series after shifting them by one session;
- lookback: 60 sessions;
- threshold: expanding median of earlier lagged 60-session correlations, requiring 60 prior
  correlation observations and shifted by one correlation observation;
- regimes: at or above the prior median, and below the prior median;
- statistic: conditional arithmetic mean of net strategy returns, annualized by 365;
- uncertainty: paired four-column non-circular 20-session moving blocks, with correlation regimes
  recomputed inside each resample;
- resamples: 2,000;
- confidence: 95%;
- seed: 20260722.

No alternate lookback, threshold, correlation statistic, block length, confidence level, or seed was
searched after observing results.

## Results

| Market | Regime | Observations | Annualized mean | 95% interval | P(mean > 0) |
|---|---|---:|---:|---:|---:|
| BTC-USDT | At/above prior median | 1,248 | 2.27% | -11.75% to 43.60% | 83.75% |
| BTC-USDT | Below prior median | 972 | 48.19% | -8.02% to 57.82% | 92.00% |
| ETH-USDT | At/above prior median | 1,248 | 13.48% | -16.63% to 35.41% | 74.45% |
| ETH-USDT | Below prior median | 972 | 22.20% | -13.85% to 51.90% | 86.30% |

## Verdict

**Rejected.** Every lower confidence bound is non-positive. The point estimates do not establish
that either strategy has reliably positive returns in both relative-correlation regimes. No
correlation-conditioned trading rule, strategy improvement, or alpha claim is supported.

## Leakage and validity controls

- Both asset-return inputs are shifted by one session before each rolling correlation.
- The threshold at a timestamp is computed only from earlier rolling-correlation observations.
- BTC and ETH asset and strategy returns remain paired during resampling.
- Regime labels are recomputed after moving-block resampling rather than copied from the original
  sample.
- The inputs retain the repository's one-bar execution delay, 10-bps transaction costs, 730/90
  rolling split, and complete 27-candidate development search.

## Real-data provenance

- Provider: OKX spot.
- Timeframe: `1Dutc`.
- Development markets: BTC-USDT and ETH-USDT.
- Evaluation period: 2020-01-11 through 2026-06-07 UTC.
- Observations: 2,340 per market; 2,220 eligible and 120 warmup observations.
- Source workflow: `29898899644`.
- Source artifact: `8521103926` (`quant-research-source-705-attempt-1`).
- Source artifact SHA-256:
  `d67057e47b8c466d2e3628283779785e662636cc4d631bb140be86cb5cf4c6ae`.
- Source checkout SHA: `cadd23dde47d235d549056b5459c51ea4cdf8e9f`.
- BTC return-file SHA-256:
  `539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73`.
- ETH return-file SHA-256:
  `027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6`.

## Limitations

BTC-USDT and ETH-USDT remain development markets, not untouched holdouts. Moving-block
concatenation creates artificial joins, although all correlation regimes are recomputed afterward.
The experiment does not model spread, market impact, liquidity, capacity, latency, or partial
fills.
