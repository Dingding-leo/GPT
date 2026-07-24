# Lagged Market-Trend Regime Consistency

## Hypothesis

For both BTC-USDT and ETH-USDT, persisted net rolling OOS returns have a positive annualized arithmetic mean when the prior 90-session compounded asset return is positive and when it is non-positive. Every 95% paired moving-block-bootstrap lower bound must be above zero.

## Economic rationale

A credible long/cash strategy should not depend exclusively on an established rising market or exclusively on a flat/falling market. The regime is calculated only from asset returns available before each evaluated session.

## Fixed specification

- OKX spot BTC-USDT and ETH-USDT, `1Dutc` development evidence.
- Prior-trend signal: compounded asset return over the previous 90 sessions, excluding the current session.
- Regimes: positive prior trend versus non-positive prior trend.
- Metric: conditional arithmetic mean of persisted net strategy returns, annualized by 365.
- Paired non-circular 20-session moving blocks over observed asset/strategy return rows.
- Trend labels recomputed inside every resample.
- 2,000 resamples, 95% confidence, deterministic market-specific seeds.
- Candidate count: 1. No alternate lookback, threshold, block, seed, market subset, fee, or acceptance rule was searched.

## Result

**Verdict: rejected.**

| Market | Regime | Observations | Annualized mean | 95% interval | P(mean > 0) |
|---|---|---:|---:|---:|---:|
| BTC-USDT | Positive prior trend | 1320 | 40.157175% | -7.762731% to 49.454631% | 91.85% |
| BTC-USDT | Non-positive prior trend | 930 | -3.589390% | -15.888668% to 48.957527% | 80.95% |
| ETH-USDT | Positive prior trend | 1333 | 27.782791% | -13.341089% to 40.283896% | 85.25% |
| ETH-USDT | Non-positive prior trend | 917 | 2.495956% | -14.780570% to 49.050173% | 80.80% |

All four lower confidence bounds are non-positive. BTC-USDT also has a negative point estimate in the non-positive-trend regime. The joint hypothesis fails, so no strategy improvement or deployable regime rule is claimed.

## Provenance

- Source workflow: `29897472573`.
- Source artifact: `8520542295` (`quant-research-source-668-attempt-1`).
- Artifact SHA-256: `9dd429dfab4e7644b7b7e1113ea1dcd7dfbcde5968974ed64e3ef176597dd73d`.
- Source head: `019823ff335d53247589ba8345298db4a93307d1`.
- Merged main source: `fc2100fa5ae4f815828960326405e7d171d59891`.
- Return-file SHA-256 values are persisted in `result.json`.
- 2,340 observations per market, 2020-01-11 through 2026-06-07 UTC.

## Limitations

- BTC-USDT and ETH-USDT are development markets, not untouched holdouts.
- The trend split is descriptive and is not a new trading rule.
- Moving-block concatenation introduces artificial joins; the lagged trend is recomputed after resampling to avoid retaining stale labels.
- Spread, market impact, capacity, latency, and partial fills are not modeled.
