# Canonical 5 bps execution-delay and all-in-cost stress

## Hypothesis

The frozen canonical 5 bps selected path remains reliably profitable and risk-controlled in BTC-USDT and ETH-USDT under total execution delays of two and three daily bars and fixed all-in costs of 5, 7.5, 10, and 15 bps.

The frozen architecture passes only if every two-bar and three-bar total-delay scenario at 5, 7.5, 10, and 15 bps has positive point total return and Sharpe, maximum drawdown no worse than -40%, and positive 95% moving-block-bootstrap lower bounds for annualized arithmetic mean and Sharpe in both development markets.

Canonical signature:

```text
canonical-5bps-execution-delay-cost-stress-v1|markets=BTC-USDT,ETH-USDT|source=PR308-artifact-8566608828|baseline=full-reselection-5bps-one-bar-delay|stress=total-delay-2,3-bars|all-in-costs-bps=5,7.5,10,15|position-path=frozen-persisted-selected-path-shifted-by-extra-delay|resampling=paired-noncircular-moving-block-bootstrap|block-length=20|resamples=2000|confidence=0.95|pass=all-stress-scenarios-positive-point-return-and-sharpe,max-drawdown-at-least-minus-40pct,and-positive-bootstrap-lower-bounds-for-annualized-mean-and-sharpe-in-both-markets|candidate_count=1
```

Exactly one frozen strategy candidate was evaluated. The delay/cost combinations are disclosed stress scenarios, not separately selected strategy candidates.

## Exact 5 bps baseline

| Market | Total return | CAGR | Ann. mean | Sharpe | Max DD | Ann. turnover |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | +142.09% | 14.49% | 16.13% | 0.707 | -28.41% | 16.43 |
| ETH-USDT | +110.57% | 12.07% | 14.55% | 0.579 | -29.18% | 17.30 |

## Live-critical delay and cost scenarios

| Market | Total delay | All-in cost | Total return | Sharpe | Max DD | Mean 95% lower | Sharpe 95% lower | Gate |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| BTC-USDT | 2 bars | 5 bps | +113.53% | 0.613 | -39.41% | -5.61% | -0.260 | fail |
| BTC-USDT | 2 bars | 7.5 bps | +107.87% | 0.595 | -39.76% | -5.98% | -0.282 | fail |
| BTC-USDT | 2 bars | 10 bps | +102.37% | 0.578 | -40.11% | -6.40% | -0.303 | fail |
| BTC-USDT | 2 bars | 15 bps | +91.80% | 0.543 | -40.80% | -7.28% | -0.341 | fail |
| BTC-USDT | 3 bars | 5 bps | +116.33% | 0.623 | -31.77% | -4.86% | -0.224 | fail |
| BTC-USDT | 3 bars | 7.5 bps | +110.60% | 0.605 | -32.21% | -5.33% | -0.243 | fail |
| BTC-USDT | 3 bars | 10 bps | +105.02% | 0.587 | -32.65% | -5.80% | -0.262 | fail |
| BTC-USDT | 3 bars | 15 bps | +94.31% | 0.552 | -33.52% | -6.63% | -0.298 | fail |
| ETH-USDT | 2 bars | 5 bps | +145.57% | 0.673 | -35.82% | -1.41% | -0.057 | fail |
| ETH-USDT | 2 bars | 7.5 bps | +138.74% | 0.656 | -36.08% | -1.88% | -0.073 | fail |
| ETH-USDT | 2 bars | 10 bps | +132.09% | 0.639 | -36.34% | -2.28% | -0.088 | fail |
| ETH-USDT | 2 bars | 15 bps | +119.35% | 0.605 | -36.87% | -3.19% | -0.120 | fail |
| ETH-USDT | 3 bars | 5 bps | +183.44% | 0.753 | -27.60% | +1.70% | +0.068 | pass |
| ETH-USDT | 3 bars | 7.5 bps | +175.55% | 0.736 | -27.90% | +1.29% | +0.052 | pass |
| ETH-USDT | 3 bars | 10 bps | +167.88% | 0.719 | -28.20% | +0.86% | +0.035 | pass |
| ETH-USDT | 3 bars | 15 bps | +153.17% | 0.685 | -28.78% | +0.04% | +0.002 | pass |

## Verdict: rejected

```text
Strategy candidates searched: 1
Passed:                       0
Rejected:                     1
Execution-delay gate:         fail
Live eligible:                false
```

BTC-USDT fails the bootstrap profitability and Sharpe lower-bound requirements in every two-bar and three-bar stress scenario. Its two-bar path also breaches the -40% drawdown floor at 10 and 15 bps. ETH-USDT passes all three-bar scenarios, including 15 bps, but fails the bootstrap lower-bound requirements for every two-bar scenario. The joint execution-delay gate therefore fails.

The all-in cost totals do not separate fee, spread, slippage, market impact, and latency. Those component-level gates remain blocked rather than being inferred from total bps. Benchmark-relative risk-adjusted evidence, fold/year stability, capacity, untouched-market validation, and prospective forward validation also remain non-passing, so the candidate is not paper/live eligible.

## Provenance

- Source workflow: `30014704624`.
- Source artifact: `8566608828`, `quant-research-source-2037-attempt-1`.
- Source artifact SHA-256: `ab0846180ff5b9397de26de8ca8d728ad237be00bdb92ba1612ef6ba243fc149`.
- Source head: `0d9c098f6408f4510bbefb95633e3d695f30dde3`.
- Provider: OKX spot.
- Markets: BTC-USDT and ETH-USDT.
- Timeframe: `1Dutc`.
- Evaluation period: 2020-01-11 through 2026-07-22 UTC.
- Observations: 2,385 per market.
- Baseline: full candidate reselection at 5 bps; delay experiments freeze the selected OOS position path and add one or two daily rows of latency.

## Limitations

- BTC-USDT and ETH-USDT are development markets, not untouched holdouts.
- The delayed paths shift observed daily positions; they are not executable next-open fills.
- The 7.5/10/15 bps scenarios are all-in totals and do not identify separate friction components.
- Moving-block concatenation creates artificial joins and preserves dependence only within blocks.
- Capacity, partial fills, rejected orders, and prospective paper evidence remain untested.

No account, credential, order, leverage, or fund access was used.
