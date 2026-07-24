# Lagged Drawdown-State Regime Consistency

## Hypothesis

BTC-USDT and ETH-USDT net rolling out-of-sample returns have positive annualized arithmetic means both when the prior close is at its prior 60-session high and when it is below that high.

**Verdict: rejected.** Exactly one predeclared candidate was tested; zero passed and one was rejected.

## Economic rationale

The strategy combines trend and reversal signals. A credible composite should not require only breakout/high-water-mark sessions or only underwater sessions to produce positive net returns.

## Fixed specification

- Regime statistic: prior close divided by the maximum of the prior 60 closes, minus one.
- The current close and current return are excluded from their own regime labels.
- At-high regime: lagged drawdown equals zero.
- Underwater regime: lagged drawdown is below zero.
- Metric: conditional arithmetic mean of persisted net strategy returns, annualized by 365.
- Uncertainty: 2,000 paired non-circular 20-session moving-block resamples.
- Acceptance: all four 95% lower confidence bounds must be strictly positive.

## Results

| Market | Regime | Observations | Annualized mean | 95% interval | P(mean > 0) | Pass |
|---|---|---:|---:|---:|---:|---:|
| BTC-USDT | at prior high | 227 | 61.3892% | -57.3978% to 178.2003% | 84.3500% | no |
| BTC-USDT | underwater | 2113 | 12.4184% | -3.4030% to 32.8538% | 93.8000% | no |
| ETH-USDT | at prior high | 224 | 66.2091% | -23.6968% to 153.6956% | 92.0000% | no |
| ETH-USDT | underwater | 2116 | 8.1459% | -10.6123% to 28.9316% | 80.0000% | no |

All four confidence intervals crossed zero. No drawdown-state filter or strategy improvement is claimed.

## Leakage controls

- Every regime label uses only closes available before the evaluated strategy return.
- The current close and current strategy return cannot determine their own regime.
- Observed timestamps, regime labels, and net strategy returns remain paired during resampling.
- BTC-USDT and ETH-USDT remain development markets, not untouched holdouts.

## Provenance

- Provider: OKX spot; timeframe: `1Dutc`.
- Source workflow: `29908375375`.
- Source artifact: `8524820348` (`quant-research-source-821-attempt-1`).
- Artifact SHA-256: `a3afb910142939e7d17d92c947957ea0b965b9411f057d96854fdccb96779401`.
- Source code commit: `513cdf4051f504ea7f833713911cd55ff7754881`.
- OOS observations: 2,340 per market, 2020-01-11 through 2026-06-07 UTC.

## Candidate accounting

Canonical signature:

```text
lagged-drawdown-state-consistency-v1|markets=BTC-USDT,ETH-USDT|source=persisted-net-rolling-oos-returns-and-OKX-close|regime-statistic=prior-60-session-close-drawdown-from-prior-60-session-high|current-session-excluded=true|threshold=zero|regimes=at-prior-60-session-high,underwater|metric=conditional-annualized-arithmetic-mean-net-return|annualization=365|resampling=paired-noncircular-moving-block-over-observed-regime-return-rows|block=20|resamples=2000|confidence=0.95|seeds=BTC:20260722,ETH:20260723|candidate_count=1
```

No alternate lookback, threshold, drawdown definition, block length, seed, market subset, fee, execution delay, or acceptance rule was selected after observing the result.

## Limitations

- BTC-USDT and ETH-USDT are development markets, not untouched holdouts.
- At-high observations are substantially fewer than underwater observations, widening uncertainty.
- Observed regime labels are treated as fixed during resampling.
- Moving-block concatenation introduces artificial joins between observed blocks.
- Spread, impact, capacity, latency, and partial fills are not modeled.

Reproduction:

```bash
python reports/research/lagged-drawdown-regimes/analysis.py \
  --artifact-dir /path/to/extracted/quant-research-source-821-attempt-1 \
  --output /tmp/lagged-drawdown-regimes.json
```
