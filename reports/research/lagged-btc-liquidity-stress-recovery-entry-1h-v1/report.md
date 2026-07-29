# Lagged BTC liquidity-stress recovery entry — terminal research report

## Strategy change

The sole preregistered candidate retained each target instrument’s daily 2,160H endpoint trend as the base long/cash state and introduced one lagged public BTC-USDT liquidity-recovery entry condition. BTC hourly stress was defined as absolute close-to-close log return divided by one plus quote volume. At each completed 00:00 UTC decision, the trailing 168 hours were split into seven 24H blocks; the median stress in each block formed a robust weekly stress level and a Sen median recovery slope. One common BTC-only training median was frozen. Entry required an above-median recent stress week, a negative recovery slope, and latest-day stress below the weekly median. Once long, the candidate ignored the exogenous state and exited only when its own 2,160H trend became non-positive. Every target change executed at the next open and paid exactly 5 bps one way.

```text
family_id              lagged-btc-liquidity-stress-recovery-entry-1h-v1
candidate_count        1
parameter_grid_count   0
issue                  #658
research_parent        5a0fcc97d1a882f8223656c51f5bb8055f534e38
verdict                reject_exact_lagged_btc_liquidity_stress_recovery_entry_family
```

For BTC-USDT, the BTC feature is own-history-only. For ETH-USDT, it is a frozen lagged public exogenous series. The feature never compares markets, ranks instruments, selects among assets, or creates a relative-value position.

## Immutable data and sample

| Item | Frozen value |
|---|---|
| Provider | Public confirmed OKX SPOT |
| Targets | BTC-USDT and ETH-USDT independently |
| Exogenous series | Lagged public BTC-USDT only |
| Bar | 1H only |
| Source observations | 43,941 per market |
| Parsed prefix | 43,441 bars |
| Training | `[2,880, 17,520)` — 2021-11-21 00:00 through 2023-07-23 23:00 UTC |
| Development OOS | `[17,520, 43,440)` — 2023-07-24 00:00 through 2026-07-07 23:00 UTC |
| Full scored | `[2,880, 43,440)` |
| OOS breadth | 12 contiguous 2,160H folds plus calendar years |
| Uncertainty | 5,000 paired non-circular 168H moving-block resamples |
| Later suffix | Unread and unscored |

The exact source hashes, aligned timestamp grids, contiguous chronology, confirmed-bar status, positive OHLC values, non-negative quote volume, next-open timing, candidate-subset-of-B1 identity and exact fee identity passed.

## BTC-only training calibration

| Quantity | Frozen result |
|---|---:|
| Eligible daily training decisions | 610 |
| Common weekly-stress median `S50` | 3.469378007521e-10 |
| Above-threshold frequency | 49.51% |
| Complete recovery-state frequency | 16.56% |

No target-market return, Sharpe, drawdown or PnL entered calibration.

## Training

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn (bps) | Mean exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | CANDIDATE | +19.69% | 0.561 | -21.73% | 4.00 | +0.20% | 575.95 | +25.41% |
| BTC-USDT | B1 | -41.29% | -0.840 | -55.92% | 28.00 | +1.40% | -159.81 | +40.49% |
| ETH-USDT | CANDIDATE | -15.82% | -0.169 | -32.41% | 10.00 | +0.50% | -89.07 | +30.16% |
| ETH-USDT | B1 | -40.59% | -0.584 | -56.95% | 23.00 | +1.15% | -168.77 | +44.60% |

## Development OOS

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn (bps) | Mean exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | CANDIDATE | +0.00% | — | +0.00% | 0.00 | +0.00% | — | +0.00% |
| BTC-USDT | B0 | +111.64% | 0.917 | -22.68% | 203.00 | +10.15% | 45.31 | +57.25% |
| BTC-USDT | B1 | +119.68% | 0.954 | -26.55% | 45.00 | +2.25% | 212.75 | +57.32% |
| ETH-USDT | CANDIDATE | +0.00% | — | +0.00% | 0.00 | +0.00% | — | +0.00% |
| ETH-USDT | B0 | +68.02% | 0.618 | -47.30% | 139.00 | +6.95% | 58.31 | +49.70% |
| ETH-USDT | B1 | +74.52% | 0.646 | -47.77% | 30.00 | +1.50% | 283.58 | +49.72% |

## Full scored sample

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn (bps) | Mean exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | CANDIDATE | +19.69% | 0.337 | -21.73% | 4.00 | +0.20% | 575.95 | +9.17% |
| BTC-USDT | B1 | +28.97% | 0.332 | -55.92% | 73.00 | +3.65% | 69.85 | +51.25% |
| ETH-USDT | CANDIDATE | -15.82% | -0.102 | -32.41% | 10.00 | +0.50% | -89.07 | +10.89% |
| ETH-USDT | B1 | +3.68% | 0.233 | -56.95% | 53.00 | +2.65% | 87.28 | +47.87% |

## Breadth, residual information and uncertainty

| Market | Profitable folds | Profitable years | Concentration | Residual Sharpe vs B1 | Mean delta L95 | Sharpe delta L95 | Accepted |
|---|---:|---:|---:|---:|---:|---:|---|
| BTC-USDT | 0/12 | 0/4 | — | -0.954 | -74.09% | -2.144 | No |
| ETH-USDT | 0/12 | 0/4 | — | -0.646 | -84.10% | -1.865 | No |

The candidate was inactive throughout development OOS, so it had zero return, zero turnover, undefined Sharpe and zero profitable folds in both markets. It failed every positive-return, benchmark-relative, breadth, residual-information and uncertainty requirement. The lower drawdown and turnover comparisons were mechanical consequences of holding cash and do not constitute risk-adjusted evidence.

## Failure mechanism: absolute liquidity scale was not transportable

| BTC exogenous quantity | Training | Development OOS | OOS / train |
|---|---:|---:|---:|
| Median hourly quote volume | 7,007,757.84 | 16,711,290.55 | 2.385× |
| Median absolute hourly log return | 0.002290 | 0.002055 | 0.897× |
| Median hourly Amihud-style stress | 3.321611607429e-10 | 1.282956040554e-10 | 0.386× |
| Median weekly robust stress | 3.469378007521e-10 | 1.276019494807e-10 | 0.368× |
| Daily stress above frozen `S50` | 302/610 | 1/1080 | — |

BTC median quote volume was 2.385 times its training level while median absolute hourly return was 10.3% lower. Their ratio pushed median hourly stress to 38.6% of training and median weekly stress to 36.8% of training. The frozen absolute stress threshold therefore almost never activated OOS.

There was exactly one OOS daily stress-level exceedance, at `2023-09-18T00:00:00+00:00`. It was not a recovery state: the Sen slope was positive (`+0.086665`), and latest-day stress (`5.458755120960e-10`) exceeded the weekly level (`3.471808989916e-10`). Thus the candidate made no OOS entries in either target.

## Exposure decomposition

| Market | B1-only hours | Return during omitted exposure | Fee saving | Candidate OOS entries | B1 regimes skipped | Improved arithmetic folds |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 14,857 | +97.99% | +2.25% | 0 | 23/23 | 6/12 |
| ETH-USDT | 12,888 | +86.58% | +1.50% | 0 | 15/15 | 5/12 |

Candidate-only exposure was exactly zero. Because the candidate stayed in cash, the candidate-minus-B1 arithmetic difference reconstructs exactly as the negative of all B1 market exposure plus fee savings. The candidate can appear better than B1 in folds where B1 lost money, but it generated no positive folds and no evidence of a repeatable conditional edge.

## Repaired discrepancy

The first complete execution exposed a fail-closed scorecard defect: an inactive candidate has undefined Sharpe and edge per turnover, but the acceptance comparator attempted numeric ordering and raised TypeError. The gates were repaired to treat undefined candidate statistics as failed, and the complete frozen experiment was rerun. No feature, threshold, position, fee, return, benchmark, uncertainty specification, or economic verdict changed.

The complete frozen experiment was rerun twice after the repair; the two result files were byte-identical.

```text
result_sha256     a2c744ce5452cf2518bf0822af2e1fd4943f0c43ccf9a664b4780d9f3e3d2923
reproducer_sha256 078309e452ce078f17b40f2e8dc0420aad76154fe529c98341b0b9ff4ddf9816
protocol_sha256   a7c9d1df07161a8dcbcc3979d505c189c90ae5aaf44650f9d8f1d4293ea83d7f
```

## Verdict

```text
reject_exact_lagged_btc_liquidity_stress_recovery_entry_family
```

The exact lagged BTC liquidity-stress recovery entry family is rejected. No change to the stress window, block size, absolute-return/volume formula, denominator, threshold quantile, normalization, slope estimator, recovery-state logic, cadence, exit, fee, sample, market-specific treatment or uncertainty specification may be evaluated as a same-interval rescue. There is no G1 nomination, prospective-paper promotion or live-trading authorisation.

## Remaining blocker and next experiment

No statistically eligible frozen causal 1H strategy exists. The specific blocker exposed here is feature transportability: an absolute return-per-quote-volume level encoded a secular quote-volume scale shift rather than a stable liquidity regime. A conservative static training threshold can therefore deactivate even though the temporal recovery logic itself remains well-defined.

Next, preregister one materially distinct **lagged BTC downside-shock absorption** architecture. Define shock events causally from BTC returns relative to a rolling robust volatility scale, then measure only the completed post-shock response of BTC price and lower-wick absorption before allowing entry into the unchanged own-instrument 2,160H trend. Use one event-support rule, one candidate, no static volume-level threshold, no forced hold, no parameter grid and no cross-sectional selection. This tests whether the market absorbs adverse information, rather than attempting another calibration of the rejected absolute liquidity-level family.
