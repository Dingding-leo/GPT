# Three-estimator slow-trend consensus — terminal research report

## Frozen objective and rule

The sole preregistered candidate in issue #639 combined three causal estimates of each instrument's trailing 2,160H trend: endpoint slope, full-path OLS slope and the median of twelve contiguous 180H block slopes. The target was long when the median of the three estimates was positive and cash otherwise. Decisions occurred daily at 00:00 UTC, execution was next-open, and fees were exactly 5 bps one-way.

```text
family_id              three-estimator-slow-trend-consensus-1h-v1
candidate_count        1
parameter_grid_count   0
canonical fee          exactly 5 bps one-way
verdict                reject_exact_three_estimator_slow_trend_consensus_family
```

## Immutable data and sample

| Market | Artifact | CSV SHA-256 | Source observations | Loaded prefix |
|---|---:|---|---:|---:|
| BTC-USDT | 8704977298 | `92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9` | 43,941 | 43,441 |
| ETH-USDT | 8704978112 | `2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726` | 43,941 | 43,441 |

```text
warm-up             [0, 2,880)
training            [2,880, 17,520)
development OOS     [17,520, 43,440)
full scored         [2,880, 43,440)
OOS folds           12 x 2,160H
later suffix        unread and unscored
```

## Training

| Market | Policy | Net return | Sharpe | Max DD | Turnover | Fees | Edge/turn | Exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | -48.09% | -1.083 | -58.10% | 50 | +2.50% | -114.38 bps | +38.85% |
| BTC-USDT | B0 hourly endpoint | -41.02% | -0.831 | -55.56% | 138 | +6.90% | -32.09 bps | +40.18% |
| BTC-USDT | B1 daily endpoint | -41.29% | -0.840 | -55.92% | 28 | +1.40% | -159.81 bps | +40.49% |
| ETH-USDT | Candidate | -36.99% | -0.491 | -49.37% | 43 | +2.15% | -76.30 bps | +44.43% |
| ETH-USDT | B0 hourly endpoint | -46.84% | -0.744 | -57.75% | 88 | +4.40% | -56.53 bps | +45.06% |
| ETH-USDT | B1 daily endpoint | -40.59% | -0.584 | -56.95% | 23 | +1.15% | -168.77 bps | +44.60% |

## Development OOS

| Market | Policy | Net return | Sharpe | Max DD | Turnover | Fees | Edge/turn | Exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | +71.51% | +0.709 | -32.46% | 67 | +3.35% | +105.74 bps | +55.84% |
| BTC-USDT | B0 hourly endpoint | +111.64% | +0.917 | -22.68% | 203 | +10.15% | +45.31 bps | +57.25% |
| BTC-USDT | B1 daily endpoint | +119.68% | +0.954 | -26.55% | 45 | +2.25% | +212.75 bps | +57.32% |
| ETH-USDT | Candidate | +54.67% | +0.555 | -49.31% | 58 | +2.90% | +125.42 bps | +49.72% |
| ETH-USDT | B0 hourly endpoint | +68.02% | +0.618 | -47.30% | 139 | +6.95% | +58.31 bps | +49.70% |
| ETH-USDT | B1 daily endpoint | +74.52% | +0.646 | -47.77% | 30 | +1.50% | +283.58 bps | +49.72% |

## Full scored sample

| Market | Policy | Net return | Sharpe | Max DD | Turnover | Fees | Edge/turn | Exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | -10.96% | +0.089 | -58.10% | 117 | +5.85% | +11.67 bps | +49.71% |
| BTC-USDT | B0 hourly endpoint | +24.82% | +0.310 | -55.56% | 341 | +17.05% | +13.98 bps | +51.08% |
| BTC-USDT | B1 daily endpoint | +28.97% | +0.332 | -55.92% | 73 | +3.65% | +69.85 bps | +51.25% |
| ETH-USDT | Candidate | -2.55% | +0.201 | -49.79% | 101 | +5.05% | +39.54 bps | +47.81% |
| ETH-USDT | B0 hourly endpoint | -10.68% | +0.158 | -57.75% | 227 | +11.35% | +13.79 bps | +48.03% |
| ETH-USDT | B1 daily endpoint | +3.68% | +0.233 | -56.95% | 53 | +2.65% | +87.28 bps | +47.87% |

## Breadth, residuals and uncertainty

| Market | Profitable folds | Profitable years | Concentration | Residual Sharpe vs B0/B1 | Mean delta L95 | Sharpe delta L95 |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 4/12 | 3/4 | 36.26% | -0.704 / -0.978 | -18.64% | -0.557 |
| ETH-USDT | 6/12 | 3/4 | 23.79% | -0.229 / -0.404 | -13.57% | -0.313 |

## Estimator disagreement and benchmark discrepancy

| Market | Agreement train -> OOS | Endpoint/block disagreement train -> OOS | Candidate-only hours / return | B1-only hours / return | Incremental fees | Arithmetic delta | Median OOS run |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 71.31% -> 76.48% | 20.82% -> 15.37% | 432 / -12.54% | 816 / +11.25% | +1.10% | -24.89% | 48.0H |
| ETH-USDT | 67.70% -> 78.89% | 21.64% -> 14.72% | 360 / -11.74% | 360 / -0.81% | +1.40% | -12.33% | 48.0H |

The first diagnostic draft reported only candidate-only and B1-only raw market sums. The final artifact repairs that omission by reconstructing the exact candidate-minus-B1 arithmetic net delta from both exposure terms and incremental fees, asserting equality to the observed net-return difference within 1e-12. No signal, position, fee, strategy metric, comparator metric, gate or verdict changed.

## Acceptance and verdict

- **BTC-USDT:** FAIL; failed gates: fold_breadth, drawdown_vs_b1, turnover_vs_b1, edge_per_turnover_vs_b1, return_and_sharpe_vs_b1, positive_residual_sharpe_vs_b1, bootstrap_mean_lower_positive, bootstrap_sharpe_lower_positive.
- **ETH-USDT:** FAIL; failed gates: fold_breadth, turnover_vs_b1, edge_per_turnover_vs_b1, return_and_sharpe_vs_b1, positive_residual_sharpe_vs_b1, bootstrap_mean_lower_positive, bootstrap_sharpe_lower_positive.

```text
reject_exact_three_estimator_slow_trend_consensus_family
```

No estimator weight, window, block layout, regression variant, threshold, hysteresis, holding rule, cadence, execution, fee or market-specific rescue is authorised on this consumed development interval. No G1 nomination, prospective-paper promotion or live authorisation results.
