# Volatility-compression trend-acceleration 1H experiment

## Frozen strategy change

Equal-weight continuous score combining low 168H/2160H realised-volatility ratio and positive latest-versus-prior 168H return acceleration; positive 2160H trend and positive latest 168H return gate; daily next-open long/cash, 168H minimum hold, exactly 5 bps one-way.

Candidate count: 1; grid: 0; preregistration: #614; parent: `5a0fcc97d1a882f8223656c51f5bb8055f534e38`.

## Frozen thresholds and signal activity

| Market | Entry q70 | Exit q45 | Training entries | OOS entries | Train full-condition days | OOS full-condition days |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 0.615000 | 0.495123 | 12 | 26 | 34 | 119 |
| ETH-USDT | 0.618279 | 0.501639 | 12 | 22 | 51 | 98 |

## Training metrics

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn | Exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | candidate | -50.11% | -1.876 | -51.13% | 24 | 1.20% | -274.279 bps | 14.75% |
| BTC-USDT | b0 | -40.82% | -0.825 | -55.56% | 138 | 6.90% | -31.848 bps | 40.18% |
| BTC-USDT | b1 | -41.09% | -0.834 | -55.92% | 28 | 1.40% | -158.619 bps | 40.49% |
| ETH-USDT | candidate | -38.01% | -0.943 | -47.07% | 24 | 1.20% | -174.480 bps | 16.56% |
| ETH-USDT | b0 | -46.67% | -0.739 | -57.75% | 88 | 4.40% | -56.171 bps | 45.06% |
| ETH-USDT | b1 | -40.32% | -0.577 | -56.95% | 23 | 1.15% | -166.788 bps | 44.59% |

## Development OOS metrics

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn | Exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | candidate | 22.47% | 0.461 | -22.17% | 52 | 2.60% | 48.871 bps | 20.28% |
| BTC-USDT | b0 | 112.15% | 0.920 | -22.68% | 203 | 10.15% | 45.425 bps | 57.24% |
| BTC-USDT | b1 | 120.22% | 0.956 | -26.55% | 45 | 2.25% | 213.290 bps | 57.31% |
| ETH-USDT | candidate | -31.16% | -0.353 | -50.40% | 44 | 2.20% | -61.889 bps | 16.94% |
| ETH-USDT | b0 | 68.25% | 0.619 | -47.30% | 139 | 6.95% | 58.406 bps | 49.70% |
| ETH-USDT | b1 | 74.52% | 0.646 | -47.77% | 30 | 1.50% | 283.584 bps | 49.72% |

## Full scored metrics

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn | Exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | candidate | -38.89% | -0.447 | -54.14% | 76 | 3.80% | -53.176 bps | 18.28% |
| BTC-USDT | b0 | 25.55% | 0.314 | -55.56% | 341 | 17.05% | 14.154 bps | 51.08% |
| BTC-USDT | b1 | 29.72% | 0.336 | -55.92% | 73 | 3.65% | 70.640 bps | 51.24% |
| ETH-USDT | candidate | -57.32% | -0.569 | -67.51% | 68 | 3.40% | -101.627 bps | 16.80% |
| ETH-USDT | b0 | -10.27% | 0.160 | -57.75% | 227 | 11.35% | 13.988 bps | 48.02% |
| ETH-USDT | b1 | 4.16% | 0.235 | -56.95% | 53 | 2.65% | 88.140 bps | 47.87% |

## Breadth and uncertainty

| Market | Entries | Profitable folds | Profitable years | Positive-fold concentration | Residual Sharpe B0/B1 | Mean delta L95 | Sharpe delta L95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 26 | 7/12 | 4/4 | 32.86% | -0.786/-0.826 | -0.604389 | -1.640093 |
| ETH-USDT | 22 | 3/12 | 0/4 | 78.34% | -0.962/-1.006 | -0.793062 | -2.070847 |

## Feature drift

| Market | Vol-ratio median train/OOS | Acceleration median train/OOS | Score median train/OOS |
|---|---:|---:|---:|
| BTC-USDT | 0.858593 / 0.934617 | 0.001428 / -0.000685 | 0.518852 / 0.483607 |
| ETH-USDT | 0.877836 / 0.939621 | 0.003218 / 0.001256 | 0.523361 / 0.482377 |

## Discrepancy repaired

The initial publication pass failed because the report referenced a training-entry field that had not been persisted, although the candidate path and metrics had already been computed. The final reproducer now stores segment-specific training entry counts from the same deterministic position path and was rerun. No feature, threshold, position, PnL, comparator, uncertainty result or verdict changed.

## Verdict

`reject_exact_volatility_compression_trend_acceleration_family`

No paper or live authorisation results. No frozen feature, threshold, cadence, holding rule, market, fee, comparator or uncertainty rescue is authorised on this consumed development interval if rejected.
