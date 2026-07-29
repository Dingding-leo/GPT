# Variance-ratio persistence state — frozen development result

Verdict: `reject_exact_variance_ratio_persistence_family`

One predeclared own-history-only causal 1H candidate was evaluated independently on BTC-USDT and ETH-USDT using exactly 5 bps one-way exchange fees. No parameter grid, market subset, cross-sectional selection, synthetic data, credentials, private endpoints, orders, leverage, 15m data, or untouched OOS was used.

## Thresholds and sample

| Market | Training daily VR rows | Entry VR p60 | Exit VR p40 | Training | Development OOS |
|---|---:|---:|---:|---|---|
| BTC-USDT | 610 | 1.048062 | 1.007016 | 2021-11-21T00:00:00+00:00 to 2023-07-23T23:00:00+00:00 | 2023-07-24T00:00:00+00:00 to 2026-07-07T23:00:00+00:00 |
| ETH-USDT | 610 | 1.054361 | 1.023654 | 2021-11-21T00:00:00+00:00 to 2023-07-23T23:00:00+00:00 | 2023-07-24T00:00:00+00:00 to 2026-07-07T23:00:00+00:00 |

## Train, OOS and full scored metrics

### Descriptive training

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn | Exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | CANDIDATE | -23.33% | -0.402 | -31.98% | 36 | 1.80% | -54.21 bps | 26.72% |
| BTC-USDT | D0 | -51.75% | -0.778 | -68.42% | 82 | 4.10% | -69.36 bps | 60.82% |
| BTC-USDT | B0 | -40.82% | -0.825 | -55.56% | 138 | 6.90% | -31.85 bps | 40.18% |
| BTC-USDT | B1 | -41.09% | -0.834 | -55.92% | 28 | 1.40% | -158.62 bps | 40.49% |
| ETH-USDT | CANDIDATE | -31.72% | -0.531 | -48.01% | 40 | 2.00% | -72.83 bps | 30.98% |
| ETH-USDT | D0 | -53.28% | -0.579 | -68.04% | 76 | 3.80% | -68.36 bps | 60.82% |
| ETH-USDT | B0 | -46.67% | -0.739 | -57.75% | 88 | 4.40% | -56.17 bps | 45.06% |
| ETH-USDT | B1 | -40.32% | -0.577 | -56.95% | 23 | 1.15% | -166.79 bps | 44.59% |

### Development OOS

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn | Exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | CANDIDATE | 24.91% | 0.544 | -14.77% | 26 | 1.30% | 100.58 bps | 12.13% |
| BTC-USDT | D0 | 45.44% | 0.527 | -43.36% | 127 | 6.35% | 45.53 bps | 65.19% |
| BTC-USDT | B0 | 112.15% | 0.920 | -22.68% | 203 | 10.15% | 45.43 bps | 57.24% |
| BTC-USDT | B1 | 120.22% | 0.956 | -26.55% | 45 | 2.25% | 213.29 bps | 57.31% |
| ETH-USDT | CANDIDATE | -25.99% | -0.162 | -50.63% | 56 | 2.80% | -27.09 bps | 25.28% |
| ETH-USDT | D0 | 15.00% | 0.339 | -58.47% | 135 | 6.75% | 35.60 bps | 61.85% |
| ETH-USDT | B0 | 68.25% | 0.619 | -47.30% | 139 | 6.95% | 58.41 bps | 49.70% |
| ETH-USDT | B1 | 74.52% | 0.646 | -47.77% | 30 | 1.50% | 283.58 bps | 49.72% |

### Full scored

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn | Exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | CANDIDATE | -4.23% | 0.066 | -32.71% | 62 | 3.10% | 10.70 bps | 17.40% |
| BTC-USDT | D0 | -29.82% | 0.005 | -68.42% | 209 | 10.45% | 0.45 bps | 63.61% |
| BTC-USDT | B0 | 25.55% | 0.314 | -55.56% | 341 | 17.05% | 14.15 bps | 51.08% |
| BTC-USDT | B1 | 29.72% | 0.336 | -55.92% | 73 | 3.65% | 70.64 bps | 51.24% |
| ETH-USDT | CANDIDATE | -49.47% | -0.298 | -66.48% | 96 | 4.80% | -46.15 bps | 27.34% |
| ETH-USDT | D0 | -46.27% | -0.017 | -68.04% | 211 | 10.55% | -1.84 bps | 61.48% |
| ETH-USDT | B0 | -10.27% | 0.160 | -57.75% | 227 | 11.35% | 13.99 bps | 48.02% |
| ETH-USDT | B1 | 4.16% | 0.235 | -56.95% | 53 | 2.65% | 88.14 bps | 47.87% |

## OOS breadth, information increment and uncertainty

| Market | Entries | Median completed hold | Profitable folds | Fold concentration | Profitable years | Residual Sharpe vs D0 | Residual Sharpe vs B0 | Mean-delta L95 vs D0 | Sharpe-delta L95 vs D0 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 13 | 168H | 3/12 | 54.49% | 3/4 | -0.316 | -0.664 | -0.503003 | -1.130434 |
| ETH-USDT | 28 | 168H | 2/12 | 72.73% | 1/4 | -0.572 | -0.683 | -0.681528 | -1.535650 |

## Gate failures

### BTC-USDT

Failed: `profitable_folds_at_least_7_of_12`, `positive_fold_concentration_at_most_50pct`, `positive_residual_sharpe_vs_d0`, `positive_residual_sharpe_vs_b0`, `bootstrap_mean_delta_lower_bound_positive`, `bootstrap_sharpe_delta_lower_bound_positive`.

### ETH-USDT

Failed: `positive_net_return`, `positive_sharpe`, `positive_edge_per_turnover`, `profitable_folds_at_least_7_of_12`, `profitable_year_segments_at_least_3`, `positive_fold_concentration_at_most_50pct`, `sharpe_exceeds_d0`, `edge_per_turnover_exceeds_d0`, `positive_residual_sharpe_vs_d0`, `positive_residual_sharpe_vs_b0`, `bootstrap_mean_delta_lower_bound_positive`, `bootstrap_sharpe_delta_lower_bound_positive`.

## Interpretation

BTC reduced turnover and drawdown versus D0 and had positive OOS net performance, but the variance-ratio condition did not create broad or statistically supported incremental information: only 3/12 folds were profitable, positive-return concentration exceeded 50%, residual Sharpe was negative versus both D0 and B0, and both paired lower bounds crossed below zero.

ETH directly rejected the hypothesis: net return, Sharpe and edge per turnover were negative; only 2/12 folds and 1/4 calendar-year segments were profitable; and all incremental-information gates failed.

The exact family is rejected because every frozen gate had to pass in both development markets. No horizon, quantile, cadence, holding period, estimator, direction, sizing, entry, exit or feature rescue may be tested on this consumed interval. No paper or live trading is authorized.
