# Multi-horizon directional-consensus calibration — frozen development result

Verdict: `reject_exact_multi_horizon_directional_consensus_calibration_family`

One preregistered own-history-only causal 1H candidate was evaluated independently on BTC-USDT and ETH-USDT using exactly 5 bps one-way exchange fees. The exact state was the sign pattern of 24H, 168H, 720H and 2160H returns. Training-only next-168H calibration used overlap-adjusted Student-t lower bounds and a 168H minimum hold.

## Signal result

| Market | Training anchors | Eligible states | Best lower 90% | Entry-qualified states | OOS decisions | Eligible-state decisions | Full entries |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 603 | 2 | -2.99% | 0 | 1080 | 211 | 0 |
| ETH-USDT | 603 | 3 | -2.80% | 0 | 1080 | 399 | 0 |

No exact state in either instrument cleared the frozen +10 bps complete entry-plus-exit fee hurdle. The candidate therefore remained in cash throughout training, development OOS and the full scored interval.

## Descriptive training

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn | Exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | +0.00% | Undefined | +0.00% | 0 | +0.00% | Undefined | 0.00% |
| BTC-USDT | B0 hourly trend | -40.82% | -0.825 | -55.56% | 138 | +6.90% | -31.85 bps | 40.18% |
| BTC-USDT | B1 daily trend | -41.09% | -0.834 | -55.92% | 28 | +1.40% | -158.62 bps | 40.49% |
| ETH-USDT | Candidate | +0.00% | Undefined | +0.00% | 0 | +0.00% | Undefined | 0.00% |
| ETH-USDT | B0 hourly trend | -46.67% | -0.739 | -57.75% | 88 | +4.40% | -56.17 bps | 45.06% |
| ETH-USDT | B1 daily trend | -40.32% | -0.577 | -56.95% | 23 | +1.15% | -166.79 bps | 44.59% |

## Development OOS

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn | Exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | +0.00% | Undefined | +0.00% | 0 | +0.00% | Undefined | 0.00% |
| BTC-USDT | B0 hourly trend | +112.15% | 0.920 | -22.68% | 203 | +10.15% | +45.43 bps | 57.24% |
| BTC-USDT | B1 daily trend | +120.22% | 0.956 | -26.55% | 45 | +2.25% | +213.29 bps | 57.31% |
| ETH-USDT | Candidate | +0.00% | Undefined | +0.00% | 0 | +0.00% | Undefined | 0.00% |
| ETH-USDT | B0 hourly trend | +68.25% | 0.619 | -47.30% | 139 | +6.95% | +58.41 bps | 49.70% |
| ETH-USDT | B1 daily trend | +74.52% | 0.646 | -47.77% | 30 | +1.50% | +283.58 bps | 49.72% |

## Full scored

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn | Exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | +0.00% | Undefined | +0.00% | 0 | +0.00% | Undefined | 0.00% |
| BTC-USDT | B0 hourly trend | +25.55% | 0.314 | -55.56% | 341 | +17.05% | +14.15 bps | 51.08% |
| BTC-USDT | B1 daily trend | +29.72% | 0.336 | -55.92% | 73 | +3.65% | +70.64 bps | 51.24% |
| ETH-USDT | Candidate | +0.00% | Undefined | +0.00% | 0 | +0.00% | Undefined | 0.00% |
| ETH-USDT | B0 hourly trend | -10.27% | 0.160 | -57.75% | 227 | +11.35% | +13.99 bps | 48.02% |
| ETH-USDT | B1 daily trend | +4.16% | 0.235 | -56.95% | 53 | +2.65% | +88.14 bps | 47.87% |

## Eligible-state calibration drift

| Market | State bits 24/168/720/2160 | Train support | Train mean | Lower 90% | OOS occurrences | OOS mean | OOS−train |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | `0000` | 97 | -1.21% | -4.83% | 131 | -0.36% | +0.85% |
| BTC-USDT | `1000` | 68 | +0.40% | -2.99% | 78 | -0.75% | -1.15% |
| ETH-USDT | `0000` | 83 | -1.31% | -7.51% | 155 | -0.54% | +0.77% |
| ETH-USDT | `1000` | 56 | +2.85% | -2.81% | 100 | -0.42% | -3.26% |
| ETH-USDT | `1111` | 57 | +0.73% | -2.80% | 142 | +1.98% | +1.25% |

The eligible-state lower bounds were all materially negative. Multiple conditional means also changed sign from training to OOS, indicating calibration instability rather than a marginal fee-threshold miss.

## OOS breadth and uncertainty

| Market | Entries | Profitable folds | Profitable years | Residual Sharpe B0/B1 | Mean Δ L95 | Sharpe Δ L95 |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 0 | 0/12 | 0/4 | -0.920 / -0.956 | -0.726387 | -2.131346 |
| ETH-USDT | 0 | 0/12 | 0/4 | -0.619 / -0.646 | -0.830707 | -1.873481 |

Zero drawdown and zero fees are mechanical no-trade outcomes, not evidence of risk-adjusted alpha.

## Failed gates

### BTC-USDT

`bootstrap_mean_delta_lower_bound_positive`, `bootstrap_sharpe_delta_lower_bound_positive`, `edge_per_turnover_exceeds_b1`, `finite_sharpe_and_exceeds_b1`, `long_entries_at_least_8`, `positive_fold_concentration_at_most_50pct`, `positive_net_return`, `positive_residual_sharpe_vs_b0`, `positive_residual_sharpe_vs_b1`, `profitable_folds_at_least_7_of_12`, `profitable_year_segments_at_least_3`

### ETH-USDT

`bootstrap_mean_delta_lower_bound_positive`, `bootstrap_sharpe_delta_lower_bound_positive`, `edge_per_turnover_exceeds_b1`, `finite_sharpe_and_exceeds_b1`, `long_entries_at_least_8`, `positive_fold_concentration_at_most_50pct`, `positive_net_return`, `positive_residual_sharpe_vs_b0`, `positive_residual_sharpe_vs_b1`, `profitable_folds_at_least_7_of_12`, `profitable_year_segments_at_least_3`

## Repaired discrepancy

The first local implementation allowed a training target endpoint exactly at row 17,520. The frozen contract requires the complete target strictly inside training, so the boundary was corrected from `<= OOS` to `< OOS` and the experiment was rerun before publication. No 00:00 UTC anchor existed at that excluded endpoint; all calibration counts, positions, metrics and the verdict were unchanged.

## Verdict

`reject_exact_multi_horizon_directional_consensus_calibration_family`

No horizon set, support threshold, overlap adjustment, credible level, fee hurdle, target horizon, state pooling, hold period, exit rule, cadence, timing, market, sizing, comparator or bootstrap rescue is authorized on this consumed development interval. No untouched replication, G1 nomination, prospective-paper promotion or live authorization results.

## Next strategy experiment

Preregister one materially orthogonal own-history-only **trend-break recovery with path-shape confirmation** architecture: one fixed drawdown-from-rolling-high state, one fixed multi-day recovery-slope/close-location confirmation, one fixed minimum hold and a low-turnover daily rule. It must use one candidate, no parameter grid, bilateral breadth, edge-per-turnover and moving-block uncertainty gates, and must not reuse a single-bar OHLCV shock proxy.
