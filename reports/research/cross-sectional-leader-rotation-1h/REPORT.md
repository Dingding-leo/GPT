# Cross-Sectional Leader Rotation 1h

## Hypothesis

A fixed BTC-USDT/ETH-USDT cross-sectional hourly leader-rotation architecture clears every retrospective architecture-freeze gate at exactly 5 bps one-way and is eligible for prospective post-only paper evaluation.

Exactly one architecture candidate was tested. Four one-axis neighbourhood paths were fixed robustness checks, not searched alternatives.

## Result: rejected

```text
architecture candidates searched: 1
passed: 0
rejected: 1
paper testable: false
live eligible: false
```

## Exact 5 bps portfolio metrics

| Metric | Result |
|---|---:|
| Gross total return | +89.071885% |
| Net total return | **+51.221464%** |
| CAGR | +15.001284% |
| Annualized arithmetic mean | +18.213438% |
| Sharpe | 0.625606 |
| Sortino | 0.891922 |
| Calmar | 0.352087 |
| Maximum drawdown | -42.606767% |
| Annual turnover | 150.933336 |
| Average gross exposure | +36.658759% |
| Exchange-fee sum | +22.329863% |

The architecture is net profitable after the exact 5 bps one-way fee, but it fails the stronger benchmark, stability, neighbourhood, activity-quality, and capacity requirements. No additional execution cost is included in PnL.

## Same-window benchmarks

| Path | Net return | Sharpe | Calmar | Maximum drawdown | Annual turnover |
|---|---:|---:|---:|---:|---:|
| equal_weight_buy_and_hold | +46.038886% | 0.506504 | 0.225993 | -60.417302% | 0.000000 |
| equal_weight_volatility_targeted_long | +32.024791% | 0.433564 | 0.176559 | -55.755898% | 14.102442 |
| equal_weight_simple_trend_long_cash | +108.893635% | 0.916270 | 0.768338 | -36.792868% | 141.944444 |

The strategy trails equal-weight simple trend long/cash on return, Sharpe, and Calmar. It has favorable point deltas against the other two benchmarks, but dependence-aware confidence intervals do not exclude zero.

## Benchmark-relative moving-block inference

| Benchmark | Sharpe delta (95% interval) | Calmar delta (95% interval) |
|---|---:|---:|
| equal_weight_buy_and_hold | 0.119102 [-0.939159, 1.265793] | 0.126094 [-1.401803, 1.883495] |
| equal_weight_volatility_targeted_long | 0.192042 [-0.846496, 1.310793] | 0.175528 [-1.104691, 1.909779] |
| equal_weight_simple_trend_long_cash | -0.290663 [-1.032395, 0.490039] | -0.416251 [-1.873056, 0.723894] |

All six required lower confidence bounds are negative.

## Stability and activity

| Diagnostic | Result | Required |
|---|---:|---:|
| Profitable folds | 6/12 | at least 7/12 |
| Largest positive-fold contribution | +29.303408% | at most 50% |
| Profitable complete months | 10/35 | at least 18/35 |
| Profitable complete years | 2/2 | 2/2 |
| Annual turnover | 150.933336 | 12 to 150 |
| Completed exposure episodes/year | 45.625000 | at least 24 |
| Median holding period | 18.000000 hours | 4 to 168 hours |
| Completed-episode profit factor | 1.405083 | above 1 |

The system creates faster evidence than the daily strategy, but turnover is slightly above the fixed ceiling and positive performance is too sparse across folds and months.

## Parameter neighbourhoods

| Robustness path | Net return | Sharpe | Annual turnover |
|---|---:|---:|---:|
| momentum_120h | +90.234853% | 0.883111 | 186.099684 |
| momentum_240h | +4.119325% | 0.196811 | 147.169335 |
| decision_cadence_3h | +12.527076% | 0.282480 | 219.212429 |
| decision_cadence_12h | +35.749774% | 0.500367 | 112.512359 |

The 240-hour momentum and 3-hour cadence paths fail the required Sharpe-above-0.50 rule. The family is therefore not neighbourhood-stable.

## Tail risk and capacity

- Strategy 5% expected shortfall: `-0.801473%`.
- Equal-weight volatility-targeted 5% expected shortfall: `-1.141316%`.
- Tail-risk gate: `pass`.
- USD 100,000 adjustment components: `1272`.
- Capacity breaches above 0.10% participation: `488` (+38.364780%).
- Maximum observed participation: `+3.622222%`.
- Implied maximum initial capital at the strict limit: `USD 2760.74`.

The strictly lagged hourly quote-volume proxy rejects the proposed USD 100,000 scale. It is still not executable depth or queue evidence.

## Gate status

| Gate | Status |
|---|---|
| Exact 5 bps net viability | **pass** |
| Benchmark-relative risk-adjusted evidence | **fail** |
| Fold stability | **fail** |
| Month stability | **fail** |
| Year stability | **pass** |
| Turnover/holding/trade sufficiency | **fail** |
| Parameter-neighbourhood stability | **fail** |
| Tail risk | **pass** |
| USD 100k capacity | **fail** |
| Retrospective architecture freeze | **fail** |
| Maker fill/m4T4 