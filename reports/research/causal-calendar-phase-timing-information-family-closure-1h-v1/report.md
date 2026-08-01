# Causal calendar-phase timing information family closure

## Frozen closure

```text
family                 causal-calendar-phase-timing-information-family-closure-1h-v1
architecture groups    2
new candidates         0
parameter grid         0
new OOS consumed       0
new market data        0
bar                    1H
fee                    exactly 5 bps one way in executable sources
verdict                reject_causal_calendar_phase_timing_information_family
```

The closure reads only two content-addressed terminal records. It does not recompute a source strategy, read a candle, generate a return path, consume new OOS, or choose a favourable market.

## Architecture support audit

| Group | Source valid | Positive OOS in every market | Beats E2160 net + Sharpe | Positive dependence L95 | Breadth | Calendar transport | Delay | Supportive |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Weekly phase-conditioned carry | Pass | Fail | Fail | Fail | Fail | Fail | N/A | Fail |
| Week-phase deseasonalized E2160 | Pass | Fail | Fail | Fail | Fail | Fail | Fail | Fail |

## Group A — weekly phase-conditioned trend carry

### Train / OOS / full candidate performance

| Market | Segment | Candidate net | Sharpe | Max DD | Turnover | Edge/turn | E2160 net / Sharpe |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | training | -21.7631% | -0.3151 | -39.2740% | 18 | -91.15 bp | -41.0940% / -0.8341 |
| BTC-USDT | oos | +98.2466% | +0.8650 | -25.1400% | 23 | +367.90 bp | +120.2156% / +0.9562 |
| BTC-USDT | full | +55.1019% | +0.4549 | -39.2740% | 41 | +166.36 bp | +29.7203% / +0.3355 |
| ETH-USDT | training | -38.1200% | -0.5300 | -53.9800% | 16 | -218.43 bp | -40.3200% / -0.5770 |
| ETH-USDT | oos | -1.0460% | +0.2250 | -57.3000% | 23 | +134.57 bp | +74.5160% / +0.6460 |
| ETH-USDT | full | -38.7600% | -0.0200 | -57.3000% | 39 | -10.25 bp | +4.1600% / +0.2350 |

| Market | Profitable folds | Profitable years | Positive-fold concentration | Mean delta L95 | Sharpe delta L95 | Frozen/OOS top-two overlap | Phase persistence |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 6/12 | 3/4 | 40.89% | -0.169754 annualised | -0.458219 | 0/2 | Pearson +0.367; Spearman +0.071 |
| ETH-USDT | 6/12 | 3/4 | 25.76% | -0.406476 annualised | -0.898653 | 0/2 | Pearson -0.156; Spearman -0.107 |

Group A reduced turnover but did not transport its fitted weekday leaders. BTC underperformed E2160 on OOS net and Sharpe; ETH produced negative OOS net return and materially underperformed E2160. Both dependence-aware lower bounds were negative.

## Group B — week-phase deseasonalized endpoint trend

### Train / OOS / full candidate performance

| Market | Segment | Candidate net | Sharpe | Max DD | Turnover | Edge/turn | E2160 net / Sharpe |
|---|---|---:|---:|---:|---:|---:|---:|
| CRV-USDT | training | -19.8201% | -0.1151 | -38.1691% | 8 | -2.4775% | -19.8201% / -0.1151 |
| CRV-USDT | oos | -56.8127% | +0.0240 | -82.1318% | 42 | -1.3527% | -56.8792% / +0.0243 |
| CRV-USDT | full | -65.3725% | -0.0019 | -82.1318% | 50 | -1.3074% | -65.4258% / -0.0016 |
| SUSHI-USDT | training | -63.4703% | -1.6166 | -65.9056% | 30 | -2.1157% | -64.6589% / -1.6631 |
| SUSHI-USDT | oos | -41.6741% | +0.1677 | -83.2682% | 56 | -0.7442% | -38.4121% / +0.1959 |
| SUSHI-USDT | full | -78.6937% | -0.1552 | -83.2682% | 86 | -0.9150% | -78.2341% / -0.1403 |

| Market | Positive relative folds | Positive candidate+relative years | Concentration | Mean-delta CI (bp/h) | Sharpe-delta CI | Profile corr / CI | 1H-delay net / Sharpe |
|---|---:|---:|---:|---:|---:|---:|---:|
| CRV-USDT | 1/12 | 0/4 | 100.00% | [-0.0453, +0.0436] | [-0.0526, +0.0500] | +0.0479 [-0.1960, +0.2637] | -61.7771% / -0.0287 |
| SUSHI-USDT | 3/12 | 0/4 | 81.61% | [-0.1618, +0.1192] | [-0.1810, +0.1316] | +0.0486 [-0.1994, +0.2611] | -32.3300% / +0.2298 |

Group B changed only 8 of 1,080 SUSHI decisions and 5 of 1,080 CRV decisions. The frozen profile correlation was approximately +0.048 in both markets, with negative lower bounds. Both candidates had negative OOS net returns and failed breadth, uncertainty, transport, and delayed economics.

## Family gates

| Gate | Result |
|---|---:|
| `both_groups_source_valid` | Pass |
| `at_least_one_group_bilateral_positive_absolute_oos` | Fail |
| `at_least_one_group_bilateral_benchmark_superiority` | Fail |
| `at_least_one_group_bilateral_positive_dependence_bounds` | Fail |
| `at_least_one_group_bilateral_temporal_breadth` | Fail |
| `at_least_one_group_bilateral_calendar_transport` | Fail |
| `leave_one_group_out_support_survives` | Fail |

Leave-one-group-out support is zero after either omission. Neither architecture is supportive independently, so the conclusion is not driven by one weak group.

## Exact source identities

```text
weekly_phase_conditioned_trend_carry           944e288f9837183e672d821fbe61cfa034371c0b13d177ada3542f1d02f6f8e6
week_phase_deseasonalized_endpoint_trend       9cce7939e8c7755032dcbc388eda214621fe86f5906df012dbd0c5272b466832
```

## Verdict

`reject_causal_calendar_phase_timing_information_family`

The evidence rejects deterministic UTC calendar timing as a productive incremental information family on these consumed cohorts. Alternate weekday choices, Fourier orders, binning, smoothing, demeaning, phase-gated exits, phase sizing, sign reversal, market subsets, fees, delays and horizons are closed as same-family rescue.

## Remaining blocker and next experiment

No deterministic UTC calendar partition has demonstrated bilateral, dependence-supported incremental timing over the low-turnover 2160H endpoint trend. The programme still lacks a transportable exogenous state that changes future long/cash utility without destroying edge per turnover.

Next: preregister `lagged-btc-market-impulse-veto-trend-carry-1h-v1`. Use each target's own positive 2,160H trend as the base rule and one fixed, strictly lagged BTC-USDT downside-impulse state only to delay entries during broad risk-off impulses. Preserve exits and in-position holding, use one candidate, no parameter grid, exactly 5 bps one way, and require bilateral residual, turnover-efficiency, fold/year, delay and dependence-aware support.
