# Trend-break path-recovery 1H experiment

## Frozen strategy change

Deep rolling-high break (training q20) + positive 72H OLS log-close slope + 72H close location >= 0.75 + positive 2160H trend; daily next-open long/cash, 168H minimum hold, exactly 5 bps one-way.

Candidate count: 1; grid: 0; preregistration: #611; parent: `5a0fcc97d1a882f8223656c51f5bb8055f534e38`.

## Thresholds and inactivity diagnosis

| Market | q20 break | Train break | Train break+trend | OOS break | OOS break+trend | Recovery geometry without trend (train/OOS) | Entries |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | -39.88% | 122 | 0 | 7 | 0 | 27 / 1 | 0 |
| ETH-USDT | -45.38% | 124 | 0 | 95 | 0 | 31 / 21 | 0 |

The deep-break and positive-2160H-trend conditions never overlapped in either market in training or development OOS. Recovery geometry existed only while the slow trend was non-positive. This is the direct no-trade mechanism, not a chronology or fee defect.

## Training metrics

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn | Exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | candidate | 0.00% | undefined | 0.00% | 0 | 0.00% | undefined bps | 0.00% |
| BTC-USDT | b0 | -40.82% | -0.825 | -55.56% | 138 | 6.90% | -31.848 bps | 40.18% |
| BTC-USDT | b1 | -41.09% | -0.834 | -55.92% | 28 | 1.40% | -158.619 bps | 40.49% |
| ETH-USDT | candidate | 0.00% | undefined | 0.00% | 0 | 0.00% | undefined bps | 0.00% |
| ETH-USDT | b0 | -46.67% | -0.739 | -57.75% | 88 | 4.40% | -56.171 bps | 45.06% |
| ETH-USDT | b1 | -40.32% | -0.577 | -56.95% | 23 | 1.15% | -166.788 bps | 44.59% |

## Development OOS metrics

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn | Exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | candidate | 0.00% | undefined | 0.00% | 0 | 0.00% | undefined bps | 0.00% |
| BTC-USDT | b0 | 112.15% | 0.920 | -22.68% | 203 | 10.15% | 45.425 bps | 57.24% |
| BTC-USDT | b1 | 120.22% | 0.956 | -26.55% | 45 | 2.25% | 213.290 bps | 57.31% |
| ETH-USDT | candidate | 0.00% | undefined | 0.00% | 0 | 0.00% | undefined bps | 0.00% |
| ETH-USDT | b0 | 68.25% | 0.619 | -47.30% | 139 | 6.95% | 58.406 bps | 49.70% |
| ETH-USDT | b1 | 74.52% | 0.646 | -47.77% | 30 | 1.50% | 283.584 bps | 49.72% |

## Full scored metrics

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn | Exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | candidate | 0.00% | undefined | 0.00% | 0 | 0.00% | undefined bps | 0.00% |
| BTC-USDT | b0 | 25.55% | 0.314 | -55.56% | 341 | 17.05% | 14.154 bps | 51.08% |
| BTC-USDT | b1 | 29.72% | 0.336 | -55.92% | 73 | 3.65% | 70.640 bps | 51.24% |
| ETH-USDT | candidate | 0.00% | undefined | 0.00% | 0 | 0.00% | undefined bps | 0.00% |
| ETH-USDT | b0 | -10.27% | 0.160 | -57.75% | 227 | 11.35% | 13.988 bps | 48.02% |
| ETH-USDT | b1 | 4.16% | 0.235 | -56.95% | 53 | 2.65% | 88.140 bps | 47.87% |

## Breadth and uncertainty

| Market | Folds | Years | Concentration | Residual Sharpe B0/B1 | Mean delta L95 | Sharpe delta L95 |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 0/12 | 0/4 | undefined | -0.920/-0.956 | -0.726387 | -2.131346 |
| ETH-USDT | 0/12 | 0/4 | undefined | -0.619/-0.646 | -0.830707 | -1.873481 |

## Verdict

`reject_exact_trend_break_path_recovery_family`

No G1 nomination, prospective paper promotion, or live authorization results. No threshold, horizon, hold, exit, cadence, timing, fee, market, sizing, comparator, or bootstrap rescue is permitted on this consumed development interval.
