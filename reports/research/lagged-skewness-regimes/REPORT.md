# Lagged Asset-Return Skewness Regime Consistency

## Hypothesis

BTC-USDT and ETH-USDT net rolling out-of-sample returns have positive annualized arithmetic means both when the prior 60-session asset-return distribution has positive adjusted sample skewness and when it has non-positive skewness.

**Verdict: rejected.** Exactly one predeclared candidate was tested; zero passed and one was rejected.

## Economic rationale

The strategy combines trend and reversal signals. A credible composite should not require exclusively upside-skewed recent markets or exclusively symmetric/downside-skewed recent markets to produce positive net returns.

## Fixed specification

- Regime statistic: Fisher-Pearson adjusted sample skewness of the prior 60 daily asset returns.
- The current session's asset return and strategy return are excluded from their own regime label.
- Positive regime: lagged skewness above zero.
- Non-positive regime: lagged skewness at or below zero.
- Metric: conditional arithmetic mean of persisted net strategy returns, annualized by 365.
- Uncertainty: 2,000 paired non-circular 20-session moving-block resamples of observed regime/return rows.
- Acceptance: all four 95% lower confidence bounds must be strictly positive.

## Results

| Market | Regime | Observations | Annualized mean | 95% interval | P(mean > 0) | Pass |
|---|---|---:|---:|---:|---:|---:|
| BTC-USDT | positive skewness | 1,438 | 21.1186% | -6.1759% to 55.5262% | 93.9000% | no |
| BTC-USDT | non-positive skewness | 902 | 10.8723% | -11.0963% to 35.3887% | 81.4000% | no |
| ETH-USDT | positive skewness | 1,334 | 15.6079% | -9.9823% to 45.0498% | 87.1000% | no |
| ETH-USDT | non-positive skewness | 1,006 | 11.1795% | -13.0907% to 37.0537% | 80.2000% | no |

All four confidence intervals crossed zero. No skewness filter or strategy improvement is claimed.

## Leakage controls

- Each skewness label uses only asset returns available before the evaluated session.
- The current close, current asset return, and current strategy return cannot determine their own regime.
- Observed timestamps, regime labels, and net strategy returns remain paired during resampling.
- The existing one-bar execution delay, 10-bps cost, 730/90 fold structure, and complete 27-candidate grid are unchanged.
- BTC-USDT and ETH-USDT remain development markets, not untouched holdouts.

## Provenance

- Provider: OKX spot; timeframe: `1Dutc`.
- Source workflow: `29910622011`.
- Source artifact: `8525728688` (`quant-research-source-875-attempt-1`).
- Artifact SHA-256: `cc313c8d00910bcaea869c75c32ce4c4c62794b4d2362d9ac01c5dff63fb6327`.
- Source code commit: `b0de1618e26855228789ea7af15a7ef0e62d522f`.
- OOS observations: 2,340 per market, 2020-01-11 through 2026-06-07 UTC.

## Candidate accounting

Canonical signature:

```text
lagged-asset-return-skewness-regime-consistency-v1|markets=BTC-USDT,ETH-USDT|source=persisted-net-rolling-oos-returns-and-OKX-close|regime-statistic=fisher-pearson-adjusted-skewness-of-prior-60-asset-returns|current-session-excluded=true|threshold=zero|regimes=positive,nonpositive|metric=conditional-annualized-arithmetic-mean-net-return|annualization=365|resampling=paired-noncircular-moving-block-over-observed-regime-return-rows|block=20|resamples=2000|confidence=0.95|seeds=BTC:20260722,ETH:20260723|candidate_count=1
```

No alternate lookback, threshold, skewness estimator, block length, seed, market subset, fee, execution delay, or acceptance rule was selected after observing the result.

## Limitations

- BTC-USDT and ETH-USDT are development markets, not untouched holdouts.
- Observed regime labels are treated as fixed during resampling.
- Moving-block concatenation introduces artificial joins between observed blocks.
- The zero threshold is a descriptive split, not a deployable rule validated on a fresh market.
- Spread, impact, capacity, latency, and partial fills are not modeled.

Reproduction:

```bash
python reports/research/lagged-skewness-regimes/analysis.py \
  --artifact-dir /path/to/extracted/quant-research-source-875-attempt-1 \
  --output /tmp/lagged-skewness-regimes.json
```
