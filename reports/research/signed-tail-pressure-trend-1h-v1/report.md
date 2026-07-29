# Signed-tail-pressure trend — frozen development result

Verdict: `reject_exact_signed_tail_pressure_trend_family`

One preregistered own-history-only causal 1H candidate was evaluated independently on BTC-USDT and ETH-USDT using exactly 5 bps one-way exchange fees.

## Feature diagnostics

| Market | +tail train | -tail train | +tail OOS | -tail OOS | OOS balance min/median/max | unavailable decisions |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 476 | 487 | 726 | 792 | -12/0.0/10 | 0 |
| ETH-USDT | 425 | 460 | 698 | 795 | -11/-1.0/9 | 0 |

## Descriptive training

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn | Exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | CANDIDATE | -16.51% | -0.333 | -42.02% | 48 | 2.40% | -27.66 bps | 22.62% |
| BTC-USDT | B0 | -40.82% | -0.825 | -55.56% | 138 | 6.90% | -31.85 bps | 40.18% |
| BTC-USDT | B1 | -41.09% | -0.834 | -55.92% | 28 | 1.40% | -158.62 bps | 40.49% |
| ETH-USDT | CANDIDATE | -17.05% | -0.332 | -36.06% | 42 | 2.10% | -32.49 bps | 19.18% |
| ETH-USDT | B0 | -46.67% | -0.739 | -57.75% | 88 | 4.40% | -56.17 bps | 45.06% |
| ETH-USDT | B1 | -40.32% | -0.577 | -56.95% | 23 | 1.15% | -166.79 bps | 44.59% |

## Development OOS

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn | Exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | CANDIDATE | 52.89% | 0.733 | -26.81% | 76 | 3.80% | 66.42 bps | 26.30% |
| BTC-USDT | B0 | 112.15% | 0.920 | -22.68% | 203 | 10.15% | 45.43 bps | 57.24% |
| BTC-USDT | B1 | 120.22% | 0.956 | -26.55% | 45 | 2.25% | 213.29 bps | 57.31% |
| ETH-USDT | CANDIDATE | 138.55% | 1.171 | -31.73% | 60 | 3.00% | 165.02 bps | 22.41% |
| ETH-USDT | B0 | 68.25% | 0.619 | -47.30% | 139 | 6.95% | 58.41 bps | 49.70% |
| ETH-USDT | B1 | 74.52% | 0.646 | -47.77% | 30 | 1.50% | 283.58 bps | 49.72% |

## Full scored

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn | Exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | CANDIDATE | 27.65% | 0.342 | -42.02% | 124 | 6.20% | 30.00 bps | 24.97% |
| BTC-USDT | B0 | 25.55% | 0.314 | -55.56% | 341 | 17.05% | 14.15 bps | 51.08% |
| BTC-USDT | B1 | 29.72% | 0.336 | -55.92% | 73 | 3.65% | 70.64 bps | 51.24% |
| ETH-USDT | CANDIDATE | 97.88% | 0.678 | -36.06% | 102 | 5.10% | 83.69 bps | 21.24% |
| ETH-USDT | B0 | -10.27% | 0.160 | -57.75% | 227 | 11.35% | 13.99 bps | 48.02% |
| ETH-USDT | B1 | 4.16% | 0.235 | -56.95% | 53 | 2.65% | 88.14 bps | 47.87% |

## OOS breadth and uncertainty

| Market | Entries | Profitable folds | Profitable years | Concentration | Residual R B0/B1 | Residual S B0/B1 | Mean Δ L95 | Sharpe Δ L95 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 38 | 6/12 | 4/4 | 0.518 | -39.87%/-42.02% | -0.567/-0.623 | -0.420510 | -1.119897 |
| ETH-USDT | 30 | 7/12 | 4/4 | 0.263 | 0.71%/-3.22% | 0.177/0.138 | -0.337596 | -0.449611 |

## Failed gates

### BTC-USDT

Failed: `profitable_folds_at_least_7_of_12`, `positive_fold_concentration_at_most_50pct`, `sharpe_exceeds_b1`, `edge_per_turnover_exceeds_b1`, `positive_residual_sharpe_vs_b0`, `positive_residual_sharpe_vs_b1`, `max_drawdown_no_worse_than_b1`, `bootstrap_mean_delta_lower_bound_positive`, `bootstrap_sharpe_delta_lower_bound_positive`

### ETH-USDT

Failed: `edge_per_turnover_exceeds_b1`, `bootstrap_mean_delta_lower_bound_positive`, `bootstrap_sharpe_delta_lower_bound_positive`

## Interpretation

The tail-arrival asymmetry did not produce bilateral incremental trend information: BTC-USDT candidate Sharpe 0.733 versus B1 0.956, edge/turn 66.42 versus 213.29 bps, with 6/12 profitable folds; ETH-USDT candidate Sharpe 1.171 versus B1 0.646, edge/turn 165.02 versus 283.58 bps, with 7/12 profitable folds.

The later source suffix was not semantically parsed or scored. No threshold, window, hysteresis, cadence, timing, market, fee or sizing rescue is authorized on this consumed development interval.
