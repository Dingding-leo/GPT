# Robust close-location pressure trend confirmation — terminal research report

## Strategy change

The sole preregistered candidate retained the daily 2,160H endpoint trend as the base long/cash state and introduced a robust own-instrument OHLC entry confirmation. For every completed hourly bar it measured close location within the bar range. At each completed 00:00 UTC decision, it split the trailing 720 hours into thirty 24-hour blocks, took the median close-location value within each block, then took the median across blocks. An instrument-local q60 threshold was frozen from training decisions where the 2,160H base trend was positive. The pressure signal could delay or skip entry, but once long the candidate ignored pressure and exited only when the base trend became non-positive. Every target change executed at the next open and paid exactly 5 bps one way.

```text
family_id              robust-close-location-pressure-entry-1h-v1
candidate_count        1
parameter_grid_count   0
issue                  #655
research_parent        5a0fcc97d1a882f8223656c51f5bb8055f534e38
verdict                reject_exact_robust_close_location_pressure_entry_family
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

The exact source hashes, contiguous hourly chronology, confirmed-bar status, positive OHLC values, non-negative quote volume, next-open timing, candidate-subset-of-B1 identity and exact fee identity passed.

## Training-only thresholds

| Market | Positive-trend training decisions | Pressure q60 | Training exceedance |
|---|---:|---:|---:|
| BTC-USDT | 247 | 0.040000323 | 40.08% |
| ETH-USDT | 272 | 0.042231915 | 39.71% |

## Training

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn (bps) | Mean exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | CANDIDATE | -27.87% | -0.545 | -42.03% | 14.00 | +0.70% | -184.92 | 32.62% |
| BTC-USDT | B0 | -41.02% | -0.831 | -55.56% | 138.00 | +6.90% | -32.09 | 40.18% |
| BTC-USDT | B1 | -41.29% | -0.840 | -55.92% | 28.00 | +1.40% | -159.81 | 40.49% |
| ETH-USDT | CANDIDATE | -39.36% | -0.766 | -49.45% | 16.00 | +0.80% | -258.04 | 32.95% |
| ETH-USDT | B0 | -46.84% | -0.744 | -57.75% | 88.00 | +4.40% | -56.53 | 45.06% |
| ETH-USDT | B1 | -40.59% | -0.584 | -56.95% | 23.00 | +1.15% | -168.77 | 44.60% |

## Development OOS

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn (bps) | Mean exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | CANDIDATE | +64.83% | 0.694 | -26.23% | 23.00 | +1.15% | +281.20 | 49.82% |
| BTC-USDT | B0 | +111.64% | 0.917 | -22.68% | 203.00 | +10.15% | +45.31 | 57.25% |
| BTC-USDT | B1 | +119.68% | 0.954 | -26.55% | 45.00 | +2.25% | +212.75 | 57.32% |
| ETH-USDT | CANDIDATE | +39.11% | 0.475 | -44.90% | 16.00 | +0.80% | +374.25 | 44.54% |
| ETH-USDT | B0 | +68.02% | 0.618 | -47.30% | 139.00 | +6.95% | +58.31 | 49.70% |
| ETH-USDT | B1 | +74.52% | 0.646 | -47.77% | 30.00 | +1.50% | +283.58 | 49.72% |

## Full scored sample

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn (bps) | Mean exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | CANDIDATE | +18.89% | 0.275 | -42.03% | 37.00 | +1.85% | +104.83 | 43.61% |
| BTC-USDT | B0 | +24.82% | 0.310 | -55.56% | 341.00 | +17.05% | +13.98 | 51.08% |
| BTC-USDT | B1 | +28.97% | 0.332 | -55.92% | 73.00 | +3.65% | +69.85 | 51.25% |
| ETH-USDT | CANDIDATE | -15.64% | 0.103 | -49.45% | 32.00 | +1.60% | +58.10 | 40.36% |
| ETH-USDT | B0 | -10.68% | 0.158 | -57.75% | 227.00 | +11.35% | +13.79 | 48.03% |
| ETH-USDT | B1 | +3.68% | 0.233 | -56.95% | 53.00 | +2.65% | +87.28 | 47.87% |

## Breadth, residual information and uncertainty

| Market | Profitable folds | Profitable years | Concentration | Residual Sharpe vs B1 | Mean delta L95 | Sharpe delta L95 | Accepted |
|---|---:|---:|---:|---:|---:|---:|---|
| BTC-USDT | 6/12 | 3/4 | 50.04% | -0.835 | -30.88% | -0.834 | No |
| ETH-USDT | 5/12 | 3/4 | 28.75% | -0.652 | -31.11% | -0.665 | No |

Both markets were profitable in development OOS and reduced turnover, but neither preserved B1 return or Sharpe. Both residual Sharpes were negative, both markets missed the required 7/12 profitable folds, and all dependence-aware lower confidence bounds were below zero. BTC also narrowly failed the positive-fold concentration cap at 50.04%. ETH failed the positive full-scored return gate.

## Selector diagnosis

| Market | Pressure exceedance train → OOS | Drift | B1-only hours | Return in omitted exposure | Fee saving | B1 regimes entered / total | Never entered | Improved folds |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 40.08% → 61.71% | +21.63 pp | 1,944 | +32.16% | +1.10% | 12 / 23 | 11 | 4/12 |
| ETH-USDT | 39.71% → 59.22% | +19.51 pp | 1,344 | +25.90% | +0.70% | 8 / 15 | 7 | 3/12 |

The pressure distribution shifted upward OOS, so feature activation did not disappear. The selector exceeded its training q60 on 61.71% of BTC and 59.22% of ETH positive-trend decisions. Nevertheless, its exclusions were economically mistimed. It removed 1,944 BTC hours carrying +32.16% arithmetic market return and 1,344 ETH hours carrying +25.90%, while saving only 1.10% and 0.70% in modeled fees. Candidate-only exposure was exactly zero, so the complete candidate-minus-B1 arithmetic difference reconstructs as the negative of omitted market return plus fee savings.

The regime-level mechanism was asymmetric but still inadequate. The filter correctly rejected several losing regimes, yet the profitable continuation omitted from regimes that eventually qualified was larger. BTC entered 12 of 23 OOS B1 regimes and ETH entered 8 of 15. Median entry delay among entered regimes was zero because most qualifying regimes passed immediately; the architecture therefore acted mainly as a whole-regime veto rather than a calibrated delay. It improved arithmetic performance in only 4/12 BTC folds and 3/12 ETH folds.

Hourly loss clustering was not improved: the longest exposed loss cluster remained 13 hours for BTC and 9 hours for ETH, identical to B1. The exposed-hour loss rate was also nearly unchanged. This indicates that close-location pressure reduced exposure quantity without identifying the local loss process.

## Repaired discrepancy

The first complete execution reached result serialization and failed because NumPy integer scalars from breadth and regime diagnostics are not accepted by the standard JSON encoder. The serializer was repaired to convert NumPy scalars to native values, and the entire experiment was rerun twice. Both result files were byte-identical. No feature, threshold, position, return, comparator, fee, bootstrap sample, acceptance gate or verdict changed.

```text
result_sha256     bc5f756637709aa75d220da8c26f8778efe2243f0ff574e86940d7d5c35bf89a
reproducer_sha256 63e4246e324817a749b3dc02e75444909da8fcc35abe2592021af98779913396
protocol_sha256   38bb7c7be4782eae49a1009b470582b1863d6fc5c00b8869a6eba9ccb775a6b0
```

## Verdict

```text
reject_exact_robust_close_location_pressure_entry_family
```

The exact robust close-location pressure entry family is rejected. No q-level, pressure window, block size, aggregation rule, zero-range handling, entry/exit variation, cadence, holding overlay, fee, or market-specific rescue may be evaluated on this consumed development interval. There is no G1 nomination, prospective-paper promotion or live-trading authorisation.

## Remaining blocker and next experiment

No statistically eligible frozen causal 1H strategy exists. The specific blocker exposed here is not signal frequency but calibration: a binary entry veto can skip entire profitable slow-trend regimes even when its feature remains active and stable.

Next, preregister one materially orthogonal **lagged market-liquidity stress recovery** architecture using a fixed, public, lagged BTC exogenous series for both markets: one 168H robust Amihud-style return-per-quote-volume stress measure, one 168H recovery slope, the unchanged 2,160H own-instrument base trend, daily decisions, one candidate, no parameter grid, no cross-sectional ranking, and no forced minimum hold. The hypothesis should test whether broad market liquidity stress has cleared before slow-trend entry, rather than applying another own-bar OHLC pressure threshold.
