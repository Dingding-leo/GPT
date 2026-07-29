# Weibull duration-hazard continuation — frozen development result

Verdict: `reject_exact_weibull_duration_hazard_family`

One preregistered own-history-only causal 1H candidate was evaluated independently on BTC-USDT and ETH-USDT using exactly 5 bps one-way exchange fees.

## Training duration models

| Market | Spells | Shape | Scale H | Median H | LCB age1 | LCB age168 | Max scored LCB | Eligible ages |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| BTC-USDT | 261 | 0.556698 | 13.117 | 4.0 | 0.0107 | 0.0934 | 0.2093 at 584H | none |
| ETH-USDT | 250 | 0.548752 | 13.462 | 4.0 | 0.0121 | 0.1048 | 0.2832 at 887H | none |

## Descriptive training

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn | Exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | CANDIDATE | 0.00% | undefined | 0.00% | 0 | 0.00% | undefined | 0.00% |
| BTC-USDT | D0 | -51.75% | -0.778 | -68.42% | 82 | 4.10% | -69.36 bps | 60.82% |
| BTC-USDT | B0 | -40.82% | -0.825 | -55.56% | 138 | 6.90% | -31.85 bps | 40.18% |
| BTC-USDT | B1 | -41.09% | -0.834 | -55.92% | 28 | 1.40% | -158.62 bps | 40.49% |
| ETH-USDT | CANDIDATE | 0.00% | undefined | 0.00% | 0 | 0.00% | undefined | 0.00% |
| ETH-USDT | D0 | -53.28% | -0.579 | -68.04% | 76 | 3.80% | -68.36 bps | 60.82% |
| ETH-USDT | B0 | -46.67% | -0.739 | -57.75% | 88 | 4.40% | -56.17 bps | 45.06% |
| ETH-USDT | B1 | -40.32% | -0.577 | -56.95% | 23 | 1.15% | -166.79 bps | 44.59% |

## Development OOS

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn | Exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | CANDIDATE | 0.00% | undefined | 0.00% | 0 | 0.00% | undefined | 0.00% |
| BTC-USDT | D0 | 45.44% | 0.527 | -43.36% | 127 | 6.35% | 45.53 bps | 65.19% |
| BTC-USDT | B0 | 112.15% | 0.920 | -22.68% | 203 | 10.15% | 45.43 bps | 57.24% |
| BTC-USDT | B1 | 120.22% | 0.956 | -26.55% | 45 | 2.25% | 213.29 bps | 57.31% |
| ETH-USDT | CANDIDATE | 0.00% | undefined | 0.00% | 0 | 0.00% | undefined | 0.00% |
| ETH-USDT | D0 | 15.00% | 0.339 | -58.47% | 135 | 6.75% | 35.60 bps | 61.85% |
| ETH-USDT | B0 | 68.25% | 0.619 | -47.30% | 139 | 6.95% | 58.41 bps | 49.70% |
| ETH-USDT | B1 | 74.52% | 0.646 | -47.77% | 30 | 1.50% | 283.58 bps | 49.72% |

## Full scored

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn | Exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | CANDIDATE | 0.00% | undefined | 0.00% | 0 | 0.00% | undefined | 0.00% |
| BTC-USDT | D0 | -29.82% | 0.005 | -68.42% | 209 | 10.45% | 0.45 bps | 63.61% |
| BTC-USDT | B0 | 25.55% | 0.314 | -55.56% | 341 | 17.05% | 14.15 bps | 51.08% |
| BTC-USDT | B1 | 29.72% | 0.336 | -55.92% | 73 | 3.65% | 70.64 bps | 51.24% |
| ETH-USDT | CANDIDATE | 0.00% | undefined | 0.00% | 0 | 0.00% | undefined | 0.00% |
| ETH-USDT | D0 | -46.27% | -0.017 | -68.04% | 211 | 10.55% | -1.84 bps | 61.48% |
| ETH-USDT | B0 | -10.27% | 0.160 | -57.75% | 227 | 11.35% | 13.99 bps | 48.02% |
| ETH-USDT | B1 | 4.16% | 0.235 | -56.95% | 53 | 2.65% | 88.14 bps | 47.87% |

## OOS breadth and uncertainty

| Market | Entries | Profitable folds | Profitable years | Concentration | Residual S D0 | Residual S B0 | Mean L95 | Sharpe L95 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 0 | 0/12 | 0/4 | undefined | -0.527 | -0.920 | -0.626913 | -1.674343 |
| ETH-USDT | 0 | 0/12 | 0/4 | undefined | -0.339 | -0.619 | -0.764247 | -1.598296 |

## Failed gates

### BTC-USDT

Failed: `positive_net_return`, `positive_sharpe`, `positive_edge_per_turnover`, `profitable_folds_at_least_7_of_12`, `profitable_year_segments_at_least_3`, `positive_fold_concentration_at_most_50pct`, `long_entries_at_least_5`, `sharpe_exceeds_d0`, `edge_per_turnover_exceeds_d0`, `positive_residual_sharpe_vs_d0`, `positive_residual_sharpe_vs_b0`, `bootstrap_mean_delta_lower_bound_positive`, `bootstrap_sharpe_delta_lower_bound_positive`

### ETH-USDT

Failed: `positive_net_return`, `positive_sharpe`, `positive_edge_per_turnover`, `profitable_folds_at_least_7_of_12`, `profitable_year_segments_at_least_3`, `positive_fold_concentration_at_most_50pct`, `long_entries_at_least_5`, `sharpe_exceeds_d0`, `edge_per_turnover_exceeds_d0`, `positive_residual_sharpe_vs_d0`, `positive_residual_sharpe_vs_b0`, `bootstrap_mean_delta_lower_bound_positive`, `bootstrap_sharpe_delta_lower_bound_positive`

## Interpretation

The training-fitted 10th-percentile conditional 168H survival never exceeded the frozen 0.50 majority boundary at any scored age in either market. The candidate therefore remained cash and the exact confidence rule is rejected without rescue tuning. The untouched OOS remains unread, and no paper or live trading is authorized.
