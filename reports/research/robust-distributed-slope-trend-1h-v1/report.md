# Robust distributed-slope trend estimator — terminal research report

## Objective

Test whether replacing the fragile two-endpoint 2,160H trend sign with the median of twelve contiguous non-overlapping 180H log-return slopes improves causal 1H long/cash performance and robustness without adding a fitted selector, post-entry veto, holding overlay or parameter search.

```text
family_id              robust-distributed-slope-trend-1h-v1
candidate_count        1
parameter_grid_count   0
canonical_fee          exactly 5 bps one-way
decision cadence       daily 00:00 UTC
execution              completed bar t -> open[t+1]
verdict                reject_exact_robust_distributed_slope_trend_family
```

## Frozen temporal rule

At each daily decision, thirteen lagged boundary closes define twelve adjacent 180H return intervals spanning exactly 2,160H. Each block slope is `log(close_end / close_start) / 180`. The candidate is long only when the NumPy median of the twelve slopes is strictly positive; otherwise it is cash. There is no minimum hold, hysteresis, risk veto, threshold fit, market-specific variation or OOS repair.

## Immutable data and sample

| Market | Source artifact | CSV SHA-256 | Loaded bars |
|---|---:|---|---:|
| BTC-USDT | 8704977298 | `92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9` | 43,441 |
| ETH-USDT | 8704978112 | `2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726` | 43,441 |

```text
source workflow       30401519824
warm-up               [0, 2,880)
training              [2,880, 17,520)  2021-11-21 through 2023-07-23 UTC
development OOS       [17,520, 43,440) 2023-07-24 through 2026-07-07 UTC
full scored           [2,880, 43,440)
OOS folds             12 x 2,160H
later suffix          unread and unscored
```

## Training

| Market | Policy | Net return | Sharpe | Max DD | Turnover | Fees | Edge/turn (bps) | Exposure | Entries |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | candidate | -42.18% | -0.895 | -55.95% | 155 | 7.75% | -30.09 | 40.33% | 77 |
| BTC-USDT | b0 | -41.02% | -0.831 | -55.56% | 138 | 6.90% | -32.09 | 40.18% | 69 |
| BTC-USDT | b1 | -41.29% | -0.840 | -55.92% | 28 | 1.40% | -159.81 | 40.49% | 14 |
| ETH-USDT | candidate | -52.52% | -0.860 | -58.52% | 157 | 7.85% | -38.17 | 46.24% | 78 |
| ETH-USDT | b0 | -46.84% | -0.744 | -57.75% | 88 | 4.40% | -56.53 | 45.06% | 44 |
| ETH-USDT | b1 | -40.59% | -0.584 | -56.95% | 23 | 1.15% | -168.77 | 44.60% | 11 |

## Development OOS

| Market | Policy | Net return | Sharpe | Max DD | Turnover | Fees | Edge/turn (bps) | Exposure | Entries |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | candidate | +192.29% | 1.209 | -33.22% | 143 | 7.15% | +87.72 | 58.05% | 72 |
| BTC-USDT | b0 | +111.64% | 0.917 | -22.68% | 203 | 10.15% | +45.31 | 57.25% | 101 |
| BTC-USDT | b1 | +119.68% | 0.954 | -26.55% | 45 | 2.25% | +212.75 | 57.32% | 22 |
| ETH-USDT | candidate | +35.10% | 0.451 | -54.79% | 180 | 9.00% | +32.94 | 47.96% | 90 |
| ETH-USDT | b0 | +68.02% | 0.618 | -47.30% | 139 | 6.95% | +58.31 | 49.70% | 69 |
| ETH-USDT | b1 | +74.52% | 0.646 | -47.77% | 30 | 1.50% | +283.58 | 49.72% | 15 |

## Full scored sample

| Market | Policy | Net return | Sharpe | Max DD | Turnover | Fees | Edge/turn (bps) | Exposure | Entries |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | candidate | +68.99% | 0.505 | -55.95% | 298 | 14.90% | +26.44 | 51.66% | 149 |
| BTC-USDT | b0 | +24.82% | 0.310 | -55.56% | 341 | 17.05% | +13.98 | 51.08% | 170 |
| BTC-USDT | b1 | +28.97% | 0.332 | -55.92% | 73 | 3.65% | +69.85 | 51.25% | 36 |
| ETH-USDT | candidate | -35.86% | -0.003 | -62.09% | 337 | 16.85% | -0.19 | 47.34% | 168 |
| ETH-USDT | b0 | -10.68% | 0.158 | -57.75% | 227 | 11.35% | +13.79 | 48.03% | 113 |
| ETH-USDT | b1 | +3.68% | 0.233 | -56.95% | 53 | 2.65% | +87.28 | 47.87% | 26 |

## Breadth, residuals and uncertainty

| Market | Profitable folds | Profitable years | Positive-fold concentration | Residual Sharpe vs B0 | Residual Sharpe vs B1 | Mean Δ L95 vs B1 | Sharpe Δ L95 vs B1 |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 6/12 | 3/4 | 30.93% | +0.690 | +0.610 | -0.097248 | -0.316425 |
| ETH-USDT | 6/12 | 3/4 | 29.00% | -0.306 | -0.372 | -0.384490 | -0.853610 |

Neither market passed the required 7/12 profitable-fold gate. BTC had positive point-estimate residual Sharpe, but both paired-bootstrap lower bounds crossed below zero. ETH underperformed B1 directly and had negative residual Sharpe and decisively negative uncertainty lower bounds.

## Failure mechanism

| Market | Candidate OOS changes | B1 OOS changes | Median candidate run | OOS disagreement | Candidate-only hours | Candidate-only gross sum | B1-only hours | B1-only gross sum |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 143 | 45 | 2.5 days | 15.37% | 2087 | +21.10% | 1897 | -13.50% |
| ETH-USDT | 180 | 29 | 2.0 days | 14.72% | 1680 | -10.48% | 2136 | +7.80% |

The robust aggregation did not reduce temporal instability. Repartitioning the trailing window every day moved all twelve 180H boundaries, and the median order statistic repeatedly crossed zero. BTC changed state 143 times versus 45 for B1; ETH changed 180 times versus 29. Median candidate runs were only 2.5 and 2.0 days. This increased fees and destroyed edge per turnover.

BTC’s disagreement state was directionally useful in point estimates: candidate-only exposure contributed +21.10% arithmetic gross return while B1-only exposure contributed -13.50%. That produced +192.29% OOS net return and Sharpe 1.209. However, the gain came with -33.22% drawdown, 143 turnover, only 6/12 profitable folds and uncertainty intervals that included zero. It therefore failed robustness and efficiency gates.

ETH did not replicate the relation. Candidate-only exposure contributed -10.48% arithmetic gross return and omitted B1-only exposure contributed +7.80%. The candidate delivered only +35.10% OOS net return versus +74.52% for B1, with worse drawdown, six-fold higher turnover, negative residual Sharpe and a negative full-scored return.

## Discrepancy inspected and repaired

The first diagnostic pass labelled all post-transition windows as fixed 168H windows but truncated the final BTC entry window at the OOS boundary. The reproducer was corrected to exclude any event lacking a complete OOS-contained 168H forward window. One BTC entry window was excluded; no ETH window was affected. Feature values, positions, fees, all strategy/comparator metrics, breadth, bootstrap results, acceptance gates and verdict were unchanged. The correction does not read the untouched suffix.

## Acceptance verdict

```text
reject_exact_robust_distributed_slope_trend_family
```

The exact family is rejected bilaterally. No block length, block count, median definition, threshold, hysteresis, holding period, endpoint blend or market-specific rescue is authorised on this consumed development interval. There is no G1 nomination, prospective-paper promotion or live-trading authorisation.

## Reproduction

```bash
python scripts/run_robust_distributed_slope_trend.py \
  --btc-csv snapshot/okx-BTC-USDT-1H.csv \
  --eth-csv snapshot/okx-ETH-USDT-1H.csv \
  --output reports/research/robust-distributed-slope-trend-1h-v1/result.json
```
