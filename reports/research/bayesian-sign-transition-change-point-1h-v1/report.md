# Bayesian return-sign transition change-point — frozen development result

Verdict: `reject_exact_bayesian_sign_transition_change_point_family`

One preregistered own-history-only causal 1H candidate was evaluated independently on BTC-USDT and ETH-USDT using exactly 5 bps one-way exchange fees.

## Transition diagnostics

| Market | Training counts [[--,-+],[+-,++]] | Change p min/med/max | Persist p min/med/max | Next+ p min/med/max | Change>=.80 | Persist>=.90 | Next+>=.55 | Full entries |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | `[[3365, 3930], [3930, 3415]]` | 0.0006/0.0012/0.5676 | 0.0000/0.2379/0.9957 | 0.3261/0.5061/0.6875 | 0 | 25 | 241 | 0 |
| ETH-USDT | `[[3440, 3906], [3906, 3388]]` | 0.0006/0.0012/0.7482 | 0.0002/0.2094/0.9994 | 0.3451/0.5000/0.7308 | 0 | 15 | 204 | 0 |

## Descriptive training

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn | Exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | CANDIDATE | 0.00% | Undefined | 0.00% | 0 | 0.00% | Undefined | 0.00% |
| BTC-USDT | B0 | -40.82% | -0.825 | -55.56% | 138 | 6.90% | -31.85 bps | 40.18% |
| BTC-USDT | B1 | -41.09% | -0.834 | -55.92% | 28 | 1.40% | -158.62 bps | 40.49% |
| ETH-USDT | CANDIDATE | 0.00% | Undefined | 0.00% | 0 | 0.00% | Undefined | 0.00% |
| ETH-USDT | B0 | -46.67% | -0.739 | -57.75% | 88 | 4.40% | -56.17 bps | 45.06% |
| ETH-USDT | B1 | -40.32% | -0.577 | -56.95% | 23 | 1.15% | -166.79 bps | 44.59% |

## Development OOS

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn | Exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | CANDIDATE | 0.00% | Undefined | 0.00% | 0 | 0.00% | Undefined | 0.00% |
| BTC-USDT | B0 | 112.15% | 0.920 | -22.68% | 203 | 10.15% | 45.43 bps | 57.24% |
| BTC-USDT | B1 | 120.22% | 0.956 | -26.55% | 45 | 2.25% | 213.29 bps | 57.31% |
| ETH-USDT | CANDIDATE | 0.00% | Undefined | 0.00% | 0 | 0.00% | Undefined | 0.00% |
| ETH-USDT | B0 | 68.25% | 0.619 | -47.30% | 139 | 6.95% | 58.41 bps | 49.70% |
| ETH-USDT | B1 | 74.52% | 0.646 | -47.77% | 30 | 1.50% | 283.58 bps | 49.72% |

## Full scored

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn | Exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | CANDIDATE | 0.00% | Undefined | 0.00% | 0 | 0.00% | Undefined | 0.00% |
| BTC-USDT | B0 | 25.55% | 0.314 | -55.56% | 341 | 17.05% | 14.15 bps | 51.08% |
| BTC-USDT | B1 | 29.72% | 0.336 | -55.92% | 73 | 3.65% | 70.64 bps | 51.24% |
| ETH-USDT | CANDIDATE | 0.00% | Undefined | 0.00% | 0 | 0.00% | Undefined | 0.00% |
| ETH-USDT | B0 | -10.27% | 0.160 | -57.75% | 227 | 11.35% | 13.99 bps | 48.02% |
| ETH-USDT | B1 | 4.16% | 0.235 | -56.95% | 53 | 2.65% | 88.14 bps | 47.87% |

## OOS breadth and uncertainty

| Market | Entries | Profitable folds | Profitable years | Concentration | Residual Sharpe B0/B1 | Mean delta L95 | Sharpe delta L95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 0 | 0/12 | 0/4 | nan | -0.920/-0.956 | -0.726387 | -2.131346 |
| ETH-USDT | 0 | 0/12 | 0/4 | nan | -0.619/-0.646 | -0.830707 | -1.873481 |

## Failed gates

### BTC-USDT

Failed: `positive_net_return`, `finite_sharpe_and_exceeds_b1`, `edge_per_turnover_exceeds_b1`, `long_entries_at_least_8`, `profitable_folds_at_least_7_of_12`, `profitable_year_segments_at_least_3`, `positive_fold_concentration_at_most_50pct`, `positive_residual_sharpe_vs_b0`, `positive_residual_sharpe_vs_b1`, `bootstrap_mean_delta_lower_bound_positive`, `bootstrap_sharpe_delta_lower_bound_positive`

### ETH-USDT

Failed: `positive_net_return`, `finite_sharpe_and_exceeds_b1`, `edge_per_turnover_exceeds_b1`, `long_entries_at_least_8`, `profitable_folds_at_least_7_of_12`, `profitable_year_segments_at_least_3`, `positive_fold_concentration_at_most_50pct`, `positive_residual_sharpe_vs_b0`, `positive_residual_sharpe_vs_b1`, `bootstrap_mean_delta_lower_bound_positive`, `bootstrap_sharpe_delta_lower_bound_positive`

## Interpretation

The posterior change-point selector did not produce bilateral incremental information: BTC-USDT candidate Sharpe undefined versus B1 0.956, entries 0, with 0/12 profitable folds; ETH-USDT candidate Sharpe undefined versus B1 0.646, entries 0, with 0/12 profitable folds.

The later source suffix was not semantically parsed or scored. No transition window, prior, threshold, trend horizon, cadence, timing, market, fee, bootstrap, sizing or comparator rescue is authorized on this consumed development interval.
