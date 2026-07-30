# Slow-trend drawdown-budget sizing — terminal report

## Objective and frozen architecture

Test one own-history-only continuous position-sizing architecture that preserves the daily 2,160H slow-trend direction while scaling exposure by the current trend margin relative to trailing realised volatility. Candidate count was **1** with **zero parameter-grid variants**. Decisions used completed 00:00 UTC bars, execution occurred at the next hourly open, and every absolute fractional exposure change paid exactly **5 bps one way**.

```text
family_id       slow-trend-drawdown-budget-sizing-1h-v1
issue           #664
research_parent 5a0fcc97d1a882f8223656c51f5bb8055f534e38
bar             1H
fee             5 bps one way
```

## Immutable data and sample

| Item | Frozen value |
|---|---|
| Provider | Public confirmed OKX SPOT |
| Targets | BTC-USDT and ETH-USDT independently |
| Exogenous series | None |
| Source observations | 43,941 per market |
| Parsed immutable prefix | 43,441 bars |
| Training | `[2,880, 17,520)` |
| Development OOS | `[17,520, 43,440)` |
| Full scored | `[2,880, 43,440)` |
| OOS folds | 12 × 2,160H |
| Uncertainty | 5,000 paired non-circular 168H blocks, seed 20260730 |
| Later suffix | Unread and unscored |

BTC source SHA-256: `92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9` (artifact `8704977298`).  
ETH source SHA-256: `2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726` (artifact `8704978112`).

## Frozen signal and sizing rule

```text
slow_margin_t      = log(close_t / close_(t-2160))
rv720_t            = sqrt(sum of squared 720 completed hourly log returns)
scaled_2160_vol_t  = sqrt(3) × rv720_t
raw_target_t       = clip(max(slow_margin_t, 0) / scaled_2160_vol_t, 0, 1)
```

On a positive base trend, the target changed only when the absolute difference from the current target was at least 0.10. A non-positive 2,160H trend forced immediate zero exposure and could not be delayed by the band.

## Performance

### Training

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn (bps) | Mean exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | -10.02% | -0.157 | -25.90% | 18.11 | +0.91% | -33.51 | 25.60% |
| BTC-USDT | B1 | -41.29% | -0.840 | -55.92% | 28.00 | +1.40% | -159.81 | 40.49% |
| ETH-USDT | Candidate | -36.63% | -0.883 | -47.38% | 26.23 | +1.31% | -150.89 | 26.94% |
| ETH-USDT | B1 | -40.59% | -0.584 | -56.95% | 23.00 | +1.15% | -168.77 | 44.60% |

### Development OOS

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn (bps) | Mean exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | +104.38% | 0.965 | -22.68% | 29.79 | +1.49% | 283.39 | 42.96% |
| BTC-USDT | B1 | +119.68% | 0.954 | -26.55% | 45.00 | +2.25% | 212.75 | 57.32% |
| ETH-USDT | Candidate | +60.46% | 0.628 | -41.84% | 29.08 | +1.45% | 226.74 | 36.49% |
| ETH-USDT | B1 | +74.52% | 0.646 | -47.77% | 30.00 | +1.50% | 283.58 | 49.72% |

### Full scored sample

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn (bps) | Mean exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | +83.90% | 0.617 | -26.17% | 47.90 | +2.40% | 163.58 | 36.70% |
| BTC-USDT | B1 | +28.97% | 0.332 | -55.92% | 73.00 | +3.65% | 69.85 | 51.25% |
| ETH-USDT | Candidate | +1.68% | 0.174 | -47.38% | 55.32 | +2.77% | 47.66 | 33.04% |
| ETH-USDT | B1 | +3.68% | 0.233 | -56.95% | 53.00 | +2.65% | 87.28 | 47.87% |

## Breadth and uncertainty

| Market | Profitable folds | Profitable years | Concentration | Residual Sharpe vs B1 | Mean Δ L95 | Sharpe Δ L95 |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 6/12 | 3/4 | 39.26% | -0.324 | -19.44% | -0.425 |
| ETH-USDT | 4/12 | 3/4 | 36.81% | -0.361 | -32.72% | -0.572 |

Neither market reached the required 7/12 profitable folds. Both residual Sharpes were negative, and all dependence-aware lower confidence bounds crossed zero.

## Failure mechanism

### BTC-USDT

The 10-point band suppressed **248** daily target changes totalling 12.77 of intended exposure, but the strategy still accepted **152** changes and generated 29.79 turnover. It underweighted B1 on **8,809 hours**, equivalent to 3721.70 full-exposure hours.

The underweight exposure removed +12.07% of arithmetic market return while fee savings were only +0.76%. The exact candidate-minus-B1 arithmetic delta was -11.31% and reconstructed identically from exposure and fee differences.

| Exposure state | Hours | Market contribution | Fees | Net contribution |
|---|---:|---:|---:|---:|
| [0,0.25) | 1,488 | -0.87% | +0.29% | -1.16% |
| [0.25,0.50) | 1,608 | -3.44% | +0.36% | -3.80% |
| [0.50,0.75) | 1,585 | +7.16% | +0.34% | +6.82% |
| [0.75,1) | 3,744 | +17.30% | +0.24% | +17.06% |
| one | 6,048 | +65.76% | +0.11% | +65.65% |

Increase turnover was 14.64; decrease turnover was 15.15. Immediate base exits contributed 2.92 turnover, while positive-trend band updates contributed 26.87.

### ETH-USDT

The 10-point band suppressed **217** daily target changes totalling 9.72 of intended exposure, but the strategy still accepted **156** changes and generated 29.08 turnover. It underweighted B1 on **8,304 hours**, equivalent to 3428.73 full-exposure hours.

The underweight exposure removed +19.18% of arithmetic market return while fee savings were only +0.05%. The exact candidate-minus-B1 arithmetic delta was -19.13% and reconstructed identically from exposure and fee differences.

| Exposure state | Hours | Market contribution | Fees | Net contribution |
|---|---:|---:|---:|---:|
| [0,0.25) | 1,392 | +8.12% | +0.31% | +7.80% |
| [0.25,0.50) | 1,608 | -5.99% | +0.33% | -6.31% |
| [0.50,0.75) | 1,728 | +9.51% | +0.37% | +9.14% |
| [0.75,1) | 3,360 | -10.91% | +0.33% | -11.24% |
| one | 4,584 | +66.66% | +0.04% | +66.62% |

Increase turnover was 14.54; decrease turnover was 14.54. Immediate base exits contributed 1.39 turnover, while positive-trend band updates contributed 27.70.

The signal-to-noise ratio was not monotonically calibrated to forward edge. Full exposure carried most of the profitable continuation, while several fractional states were negative—especially BTC below 0.50 exposure and ETH in the 0.75-to-1.00 state. Scaling therefore reduced drawdown but systematically diluted the strongest slow-trend episodes.

## Repaired diagnostic discrepancy

The initial output attributed fees only to the resulting exposure bucket. That obscured whether turnover came from positive-trend reallocations or forced slow-trend exits. The terminal reproducer adds exact transition attribution by increase/decrease and by `band_update` versus `immediate_base_exit`, and asserts that attributed transition turnover exactly reconstructs candidate turnover. No signal, target, position, fee, performance metric, bootstrap result, acceptance gate or verdict changed.

## Verdict

```text
reject_exact_slow_trend_drawdown_budget_sizing_family
```

BTC passed positive return, Sharpe, drawdown, turnover, edge-per-turnover, year breadth, concentration and full-sample return gates, but failed benchmark return, fold breadth, residual Sharpe and both uncertainty gates. ETH additionally failed benchmark Sharpe and edge-per-turnover. Both markets therefore reject the exact family.

No realised-volatility definition, scaling factor, target mapping, cap, no-trade band, exit priority, cadence, fee, market-specific treatment or uncertainty rescue is authorised on this consumed interval. There is no G1 nomination, prospective-paper promotion or live-trading authorisation.

## Remaining blocker and next experiment

**Remaining blocker:** exposure calibration is non-monotonic. A symmetric total-volatility denominator suppresses profitable continuation together with genuine risk, so lower drawdown does not translate into benchmark-relative return or robust fold breadth.

**Next experiment:** preregister one materially distinct own-history-only downside-semivariance persistence architecture. Retain the unchanged daily 2,160H trend and full unlevered exposure, but permit one fixed 50% risk state only when trailing 720H downside semivariance exceeds upside semivariance and the most recent 168H downside share is still increasing. Use one fixed two-state hysteresis rule, one candidate, no fitted threshold, no market-specific treatment, exactly 5 bps one way and the same bilateral breadth and moving-block uncertainty gates.
