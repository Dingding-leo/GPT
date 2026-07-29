# Multi-horizon fractional trend ensemble — terminal research report

## Strategy change

The sole preregistered candidate replaced the binary daily 2,160H long/cash target with a deterministic fractional target equal to the fraction of positive own-instrument endpoint trends at 720H, 1,440H and 2,160H. The only possible targets were `0`, `1/3`, `2/3` and `1`. Decisions used completed 00:00 UTC 1H bars, executed at the next open, and paid exactly 5 bps one way on absolute exposure changes.

```text
family_id              multi-horizon-fractional-trend-ensemble-1h-v1
candidate_count        1
parameter_grid_count   0
issue                  #651
research_parent        5a0fcc97d1a882f8223656c51f5bb8055f534e38
verdict                reject_exact_multi_horizon_fractional_trend_ensemble_family
```

## Immutable data and sample

| Item | Frozen value |
|---|---|
| Provider | Public confirmed OKX SPOT |
| Markets | BTC-USDT and ETH-USDT independently |
| Bar | 1H only |
| Source observations | 43,941 per market |
| Parsed prefix | 43,441 bars |
| Training | `[2,880, 17,520)` — 2021-11-21 to 2023-07-24 UTC |
| Development OOS | `[17,520, 43,440)` — 2023-07-24 to 2026-07-08 UTC |
| Full scored | `[2,880, 43,440)` |
| OOS breadth | 12 contiguous 2,160H folds plus calendar years |
| Uncertainty | 5,000 paired non-circular 168H moving-block resamples |
| Later suffix | Unread and unscored |

The exact source hashes, contiguous hourly chronology, confirmed-bar status, positive OHLC values, non-negative quote volume, next-open timing and fee identity all passed.

## Training

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn (bps) | Mean exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC | CANDIDATE | -24.51% | -0.441 | -48.46% | 35.33 | +1.77% | -59.99 | 40.66% |
| BTC | B1 | -41.29% | -0.840 | -55.92% | 28.00 | +1.40% | -159.81 | 40.49% |
| ETH | CANDIDATE | -25.22% | -0.324 | -39.84% | 38.67 | +1.93% | -48.80 | 45.20% |
| ETH | B1 | -40.59% | -0.584 | -56.95% | 23.00 | +1.15% | -168.77 | 44.60% |

## Development OOS

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn (bps) | Mean exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC | CANDIDATE | +112.04% | 0.975 | -29.31% | 62.33 | +3.12% | 143.37 | 55.99% |
| BTC | B1 | +119.68% | 0.954 | -26.55% | 45.00 | +2.25% | 212.75 | 57.32% |
| ETH | CANDIDATE | +127.51% | 0.904 | -41.56% | 55.33 | +2.77% | 189.73 | 49.01% |
| ETH | B1 | +74.52% | 0.646 | -47.77% | 30.00 | +1.50% | 283.58 | 49.72% |

## Full scored sample

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn (bps) | Mean exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC | CANDIDATE | +60.06% | 0.487 | -48.46% | 97.67 | +4.88% | 69.80 | 50.45% |
| BTC | B1 | +28.97% | 0.332 | -55.92% | 73.00 | +3.65% | 69.85 | 51.25% |
| ETH | CANDIDATE | +70.14% | 0.493 | -41.56% | 94.00 | +4.70% | 91.61 | 47.63% |
| ETH | B1 | +3.68% | 0.233 | -56.95% | 53.00 | +2.65% | 87.28 | 47.87% |

## Benchmark comparison and acceptance

| Market | Profitable folds | Profitable years | Concentration | Residual Sharpe vs B1 | Mean delta L95 | Sharpe delta L95 | Accepted |
|---|---:|---:|---:|---:|---:|---:|---|
| BTC-USDT | 4/12 | 3/4 | 32.10% | -0.183 | -15.12% | -0.372 | No |
| ETH-USDT | 6/12 | 3/4 | 25.46% | +0.351 | -14.23% | -0.240 | No |

BTC improved OOS Sharpe marginally (`0.975` versus `0.954`) but lost compounded return, worsened drawdown, raised turnover and reduced edge per turnover. ETH improved OOS return, Sharpe and drawdown materially, but turnover rose from `30.00` to `55.33`, edge per turnover remained below B1, fold breadth reached only `6/12`, and both dependence-aware lower confidence bounds crossed zero.

## State frequency, drift and return contribution

### BTC-USDT

| Target | Training frequency | OOS frequency | Drift | OOS hours | OOS net arithmetic contribution |
|---|---:|---:|---:|---:|---:|
| 0 | 37.54% | 25.37% | -12.17 pp | 6,576 | -0.58% |
| 1/3 | 25.25% | 16.85% | -8.39 pp | 4,367 | -3.82% |
| 2/3 | 14.92% | 22.22% | +7.30 pp | 5,761 | +7.10% |
| 1 | 22.30% | 35.56% | +13.26 pp | 9,216 | +86.67% |

### ETH-USDT

| Target | Training frequency | OOS frequency | Drift | OOS hours | OOS net arithmetic contribution |
|---|---:|---:|---:|---:|---:|
| 0 | 30.82% | 32.87% | +2.05 pp | 8,520 | -0.53% |
| 1/3 | 24.10% | 16.76% | -7.34 pp | 4,344 | -12.06% |
| 2/3 | 23.77% | 20.83% | -2.94 pp | 5,400 | +26.39% |
| 1 | 21.31% | 29.54% | +8.23 pp | 7,656 | +91.18% |

BTC shifted strongly toward full exposure OOS, but the intermediate `1/3` state lost money and scaling below B1 removed profitable continuation. ETH benefited from both full exposure and the `2/3` state, while the `1/3` state was materially loss-making.

## Exact discrepancy decomposition

| Market | Different-exposure hours | Candidate-more gross contribution | B1-more contribution to candidate delta | Extra fee | Candidate − B1 arithmetic net | Improved folds |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 10,128 | +4.71% | -10.21% | +0.87% | -6.37% | 3/12 |
| ETH-USDT | 9,744 | +5.46% | +15.71% | +1.27% | +19.91% | 6/12 |

For BTC, shorter-horizon agreement added `+4.71%` gross arithmetic contribution outside or above B1 exposure, but scaling below B1 forfeited `10.21%` of weighted gross return and added `0.87%` fees. For ETH, reduced exposure during B1-long periods contributed `+15.71%` to the candidate delta and extra exposure contributed another `+5.46%`; this was economically favourable but not sufficiently broad or certain.

## Turnover failure and repaired diagnostic

### BTC-USDT

The candidate made **177** OOS exposure changes, generating **62.33** turnover units and **3.12%** fees. Largest transition families:

| Transition | Count | Turnover units | Fees |
|---|---:|---:|---:|
| 2/3->1 | 33 | 11.00 | 0.550% |
| 1->2/3 | 32 | 10.67 | 0.533% |
| 0->1/3 | 31 | 10.33 | 0.517% |
| 1/3->0 | 30 | 10.00 | 0.500% |
| 1/3->2/3 | 21 | 7.00 | 0.350% |
| 2/3->1/3 | 21 | 7.00 | 0.350% |

### ETH-USDT

The candidate made **154** OOS exposure changes, generating **55.33** turnover units and **2.77%** fees. Largest transition families:

| Transition | Count | Turnover units | Fees |
|---|---:|---:|---:|
| 0->1/3 | 26 | 8.67 | 0.433% |
| 1/3->0 | 26 | 8.67 | 0.433% |
| 1/3->2/3 | 25 | 8.33 | 0.417% |
| 2/3->1/3 | 24 | 8.00 | 0.400% |
| 1->2/3 | 21 | 7.00 | 0.350% |
| 2/3->1 | 21 | 7.00 | 0.350% |

The first report grouped fees by the post-change target state, which obscured their causal source. The diagnostic was repaired to attribute every fee to its exact `from -> to` transition and to assert exact turnover and fee reconstruction. No target, return, benchmark, gate or verdict changed.

The dominant failure was not large jumps but repeated adjacent-state churn as individual horizons crossed zero at different times. BTC made `177` OOS changes versus B1's `45`; ETH made `154` versus B1's `30`. Fractional step size reduced each trade, but not enough to offset the much higher transition count.

## Verdict

```text
reject_exact_multi_horizon_fractional_trend_ensemble_family
```

The exact family fails bilateral benchmark, turnover-efficiency, fold-breadth and uncertainty requirements. No horizon, weight, cadence, smoothing, hysteresis, threshold, market-specific or fee rescue is authorised on this consumed development interval. There is no G1 nomination, prospective-paper promotion or live-trading authorisation.

**Remaining blocker:** no statistically eligible frozen causal 1H strategy exists.

**Next strategy experiment:** preregister one own-history-only **OHLC close-location pressure trend-confirmation** architecture. Preserve the daily 2,160H trend exit, and test whether a fixed 720H robust aggregate of `(2×close−high−low)/(high−low)` identifies sustained within-bar buying pressure that can improve entry quality without using volume, cross-sectional information or another transformation of endpoint-trend signs.
