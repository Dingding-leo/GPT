# Lagged Asset-Autocorrelation Regime Consistency

## Hypothesis

BTC-USDT and ETH-USDT net rolling out-of-sample returns have positive annualized arithmetic means in both positive and non-positive prior asset-return autocorrelation regimes.

**Verdict: rejected.** Exactly one predeclared candidate was tested; zero passed and one was rejected.

## Economic rationale

The strategy combines trend and reversal signals. A credible composite should not require only persistent or only mean-reverting recent market dynamics to produce positive net returns.

## Fixed specification

- Regime statistic: Pearson lag-1 autocorrelation within the prior 60 daily asset returns.
- The current session is excluded before the statistic is calculated.
- Positive regime: lagged autocorrelation greater than zero.
- Non-positive regime: lagged autocorrelation less than or equal to zero.
- Metric: conditional arithmetic mean of persisted net strategy returns, annualized by 365.
- Uncertainty: 2,000 paired non-circular 20-session moving-block resamples.
- Acceptance: all four 95% lower confidence bounds must be strictly positive.

## Results

| Market | Regime | Observations | Annualized mean | 95% interval | P(mean > 0) | Pass |
|---|---|---:|---:|---:|---:|---:|
| BTC-USDT | positive | 745 | 16.2514% | -7.0749% to 56.5429% | 92.00% | no |
| BTC-USDT | non-positive | 1535 | 21.5041% | -0.6472% to 50.3113% | 96.90% | no |
| ETH-USDT | positive | 657 | 4.7096% | -30.5102% to 50.5525% | 70.85% | no |
| ETH-USDT | non-positive | 1623 | 19.8417% | 0.0688% to 41.7848% | 97.60% | yes |

Only ETH-USDT in the non-positive-autocorrelation regime passed. Both BTC-USDT intervals and the ETH-USDT positive-autocorrelation interval crossed zero. The joint hypothesis therefore fails; no autocorrelation filter or strategy improvement is claimed.

## Leakage controls

- Every regime label uses only the 60 asset returns preceding the evaluated strategy return.
- The current asset return and current strategy return cannot determine their own regime.
- Observed timestamps, regime labels, and net strategy returns remain paired during resampling.
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
lagged-asset-autocorrelation-regime-consistency-v1|markets=BTC-USDT,ETH-USDT|source=persisted-net-rolling-oos-asset-and-strategy-returns|regime-statistic=lag1-pearson-autocorrelation-of-prior-60-asset-returns|current-session-excluded=true|threshold=zero|regimes=positive,nonpositive|metric=conditional-annualized-arithmetic-mean-net-return|annualization=365|resampling=paired-noncircular-moving-block-over-observed-regime-return-rows|block=20|resamples=2000|confidence=0.95|seeds=BTC:20260722,ETH:20260723|candidate_count=1
```

No alternate lookback, threshold, autocorrelation estimator, block length, seed, market subset, fee, execution delay, or acceptance rule was selected after observing the result.

## Limitations

- BTC-USDT and ETH-USDT are development markets, not untouched holdouts.
- Observed regime labels are treated as fixed during resampling, so regime-estimation uncertainty is not separately modeled.
- Moving-block concatenation introduces artificial joins between observed blocks.
- Spread, impact, capacity, latency, and partial fills are not modeled.

Reproduction:

```bash
python reports/research/lagged-autocorrelation-regimes/analysis.py \
  --artifact-dir /path/to/extracted/quant-research-source-780-attempt-1 \
  --output /tmp/lagged-autocorrelation-regimes.json
```
