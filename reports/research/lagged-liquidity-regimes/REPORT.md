# Lagged Liquidity-Regime Consistency

## Hypothesis

BTC-USDT and ETH-USDT net rolling out-of-sample returns have positive annualized arithmetic means in both high and low prior OKX quote-volume regimes.

**Verdict: rejected.** Exactly one predeclared candidate was tested; zero passed and one was rejected.

## Economic rationale

A credible daily long/cash process should not require only high-participation sessions or only quiet sessions. Each fold threshold is fixed from the preceding 730-session selection window, so no test-fold volume determines its own threshold.

## Fixed specification

- Liquidity statistic: median `volume_quote` over the prior 30 confirmed `1Dutc` sessions.
- Fold threshold: median of that lagged statistic in the preceding 730-session selection window.
- High regime: statistic at or above the precomputed fold threshold; low regime: below it.
- Metric: conditional arithmetic mean of persisted net strategy returns, annualized by 365.
- Uncertainty: 2,000 paired non-circular 20-session moving-block resamples.
- Acceptance: all four 95% lower confidence bounds must be strictly positive.

## Results

| Market | Regime | Observations | Annualized mean | 95% interval | P(mean > 0) | Pass |
|---|---|---:|---:|---:|---:|---:|
| BTC-USDT | high | 1509 | 31.9935% | 3.3423% to 65.9366% | 98.60% | yes |
| BTC-USDT | low | 831 | -9.7507% | -25.4984% to 9.3803% | 18.25% | no |
| ETH-USDT | high | 1731 | 20.5844% | -4.7792% to 47.3934% | 94.40% | no |
| ETH-USDT | low | 609 | -5.8522% | -23.5410% to 10.7574% | 23.55% | no |

BTC-USDT passed only in the high-liquidity regime. BTC-USDT low-liquidity returns had a negative point estimate, and both ETH-USDT regime intervals crossed zero. The joint hypothesis therefore fails; no liquidity filter or strategy improvement is claimed.

## Leakage controls

- The current session volume is excluded with a one-session shift.
- Each threshold uses only the fold's prior selection window.
- Strategy returns, regime labels, and timestamps remain paired during resampling.
- BTC-USDT and ETH-USDT remain development markets, not untouched holdouts.

## Provenance

- Provider: OKX spot; timeframe: `1Dutc`.
- Source workflow: `29904635219`.
- Source artifact: `8523312240` (`quant-research-source-780-attempt-1`).
- Artifact SHA-256: `5e8578dcc2aed7edbbc30b02b25cdb62ef7c01614305afeb09a940184c8d70a4`.
- Source code commit: `b383df39c2df12f5f11f059b8a2a2c463061f8e3`.
- OOS observations: 2,340 per market, 2020-01-11 through 2026-06-07 UTC.

## Candidate accounting

Canonical signature:

```text
selection-window-lagged-liquidity-regime-consistency-v1|markets=BTC-USDT,ETH-USDT|source=persisted-net-rolling-oos-returns-and-OKX-volume_quote|liquidity=prior-30-session-median-volume_quote|threshold=median-of-lagged-liquidity-in-each-prior-730-session-selection-window|regimes=at-or-above-threshold,below-threshold|metric=conditional-annualized-arithmetic-mean-net-return|annualization=365|resampling=paired-noncircular-moving-block-over-regime-return-rows|block=20|resamples=2000|confidence=0.95|seeds=BTC:20260722,ETH:20260723|candidate_count=1
```

No alternate lookback, liquidity field, threshold, block length, seed, market subset, fee, execution delay, or acceptance rule was selected after observing the result.

## Limitations

- Quote volume is exchange-specific and partly reflects price level as well as trading activity.
- Moving-block concatenation introduces artificial joins.
- Spread, impact, capacity, latency, and partial fills are not modeled.

Reproduction:

```bash
python reports/research/lagged-liquidity-regimes/analysis.py \
  --artifact-dir /path/to/extracted/quant-research-source-780-attempt-1 \
  --output /tmp/lagged-liquidity-regimes.json
```
