# Bounded recovery re-entry after loss-budget exit — terminal report

## Objective and frozen architecture

Test whether one same-regime recovery re-entry can retain the short-horizon protection of the frozen trend-onset loss-budget exit while repairing its excessive lockout horizon. Candidate count is **1**, parameter-grid count is **0**, decisions use completed daily 00:00 UTC bars, execution is at the next hourly open, and every absolute exposure change pays exactly **5 bps one way**.

```text
slow_positive_t = close_t > close_(t-2160)
loss_budget_t   = sqrt(720) × 1.4826 × MAD(last 720 completed hourly log returns)
failed_t        = log(peak_close_t / close_t) > loss_budget_t
                  and log(close_t / onset_close) <= 0
recovery_t      = close_t > onset_close
                  and log(close_t / close_(t-168)) > 0
```

Enter immediately at each positive-trend onset; take the first loss-budget exit; permit at most one same-regime recovery re-entry; after re-entry hold until the base trend exits. Exposure states are `{0,1}`.

## Immutable data and sample

| Item | Frozen value |
|---|---|
| Provider | Public confirmed OKX SPOT |
| Markets | BTC-USDT and ETH-USDT independently |
| Source artifacts | BTC `8704977298`; ETH `8704978112` |
| Source SHA-256 | BTC `92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9`; ETH `2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726` |
| Parsed immutable prefix | 43,441 confirmed contiguous 1H bars |
| Training | `[2,880,17,520)` |
| Development OOS | `[17,520,43,440)` |
| Full scored | `[2,880,43,440)` |
| Breadth | 12 contiguous 2,160H folds plus calendar years |
| Uncertainty | 5,000 paired non-circular 168H blocks; seed `20260730` |
| Later suffix | Unread and unscored |

## Performance

### Training

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn bps | Mean exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | -37.07% | -0.798 | -48.08% | 29.00 | +1.45% | -134.87 | 37.37% |
| BTC-USDT | Irreversible comparator | -44.52% | -1.486 | -46.90% | 27.00 | +1.35% | -203.06 | 21.80% |
| BTC-USDT | B0 hourly | -41.02% | -0.831 | -55.56% | 138.00 | +6.90% | -32.09 | 40.18% |
| BTC-USDT | B1 daily | -41.29% | -0.840 | -55.92% | 28.00 | +1.40% | -159.81 | 40.49% |
| ETH-USDT | Candidate | -38.16% | -0.625 | -52.85% | 26.00 | +1.30% | -143.64 | 37.70% |
| ETH-USDT | Irreversible comparator | -22.39% | -0.683 | -31.57% | 22.00 | +1.10% | -100.80 | 11.15% |
| ETH-USDT | B0 hourly | -46.84% | -0.744 | -57.75% | 88.00 | +4.40% | -56.53 | 45.06% |
| ETH-USDT | B1 daily | -40.59% | -0.584 | -56.95% | 23.00 | +1.15% | -168.77 | 44.60% |

### Development OOS

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn bps | Mean exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | +143.10% | 1.064 | -22.68% | 47.00 | +2.35% | 224.32 | 55.56% |
| BTC-USDT | Irreversible comparator | +147.74% | 1.088 | -22.68% | 45.00 | +2.25% | 238.01 | 54.54% |
| BTC-USDT | B0 hourly | +111.64% | 0.917 | -22.68% | 203.00 | +10.15% | 45.31 | 57.25% |
| BTC-USDT | B1 daily | +119.68% | 0.954 | -26.55% | 45.00 | +2.25% | 212.75 | 57.32% |
| ETH-USDT | Candidate | +76.46% | 0.658 | -43.57% | 32.00 | +1.60% | 265.77 | 47.22% |
| ETH-USDT | Irreversible comparator | +40.29% | 0.492 | -45.47% | 30.00 | +1.50% | 183.96 | 35.65% |
| ETH-USDT | B0 hourly | +68.02% | 0.618 | -47.30% | 139.00 | +6.95% | 58.31 | 49.70% |
| ETH-USDT | B1 daily | +74.52% | 0.646 | -47.77% | 30.00 | +1.50% | 283.58 | 49.72% |

### Full scored

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn bps | Mean exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | +52.98% | 0.447 | -48.08% | 76.00 | +3.80% | 87.26 | 48.99% |
| BTC-USDT | Irreversible comparator | +37.45% | 0.380 | -52.68% | 72.00 | +3.60% | 72.61 | 42.72% |
| BTC-USDT | B0 hourly | +24.82% | 0.310 | -55.56% | 341.00 | +17.05% | 13.98 | 51.08% |
| BTC-USDT | B1 daily | +28.97% | 0.332 | -55.92% | 73.00 | +3.65% | 69.85 | 51.25% |
| ETH-USDT | Candidate | +9.13% | 0.251 | -52.85% | 58.00 | +2.90% | 82.24 | 43.79% |
| ETH-USDT | Irreversible comparator | +8.88% | 0.219 | -45.47% | 52.00 | +2.60% | 63.49 | 26.80% |
| ETH-USDT | B0 hourly | -10.68% | 0.158 | -57.75% | 227.00 | +11.35% | 13.79 | 48.03% |
| ETH-USDT | B1 daily | +3.68% | 0.233 | -56.95% | 53.00 | +2.65% | 87.28 | 47.87% |

## Breadth and uncertainty

| Market | Profitable folds | Profitable years | Folds improved vs B1 | Years improved vs B1 | Concentration | Residual Sharpe | Mean Δ 95% | Sharpe Δ 95% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 5/12 | 3/4 | 2/12 | 2/4 | 34.10% | +0.607 | [-5.02%, +13.78%] | [-0.137, +0.431] |
| ETH-USDT | 6/12 | 2/4 | 1/12 | 1/4 | 22.11% | -0.001 | [-7.11%, +6.57%] | [-0.142, +0.170] |

Neither market passed the frozen bilateral scorecard. BTC failed turnover, fold breadth and both uncertainty lower-bound gates. ETH additionally failed calendar-year breadth, edge per turnover, residual Sharpe and both uncertainty gates.

## Failure mechanism

### BTC-USDT

- Four OOS loss-budget exits occurred, but only one recovery re-entry occurred.
- The candidate omitted 456 B1 exposure hours carrying **−9.79%** arithmetic market return, which was beneficial.
- The sole re-entry restored 264 hours carrying **−1.57%** market return and added **0.10%** in fees relative to the irreversible comparator.
- Candidate versus irreversible arithmetic net delta was **−1.67%**; OOS compounded return fell from **+147.74%** to **+143.10%**.
- Only 5/12 folds were profitable, only 2/12 improved versus B1, and both confidence lower bounds remained negative.

### ETH-USDT

- Two OOS loss-budget exits occurred, with one recovery re-entry.
- The re-entry restored 3,000 hours carrying **+29.96%** arithmetic market return and repaired nearly all irreversible lockout damage.
- The candidate reached **+76.46%** OOS compounded return versus **+74.52%** for B1, with higher Sharpe and better drawdown.
- It nevertheless incurred turnover `32` versus B1 `30`, edge per turnover `265.77` versus `283.58` bps, only 6/12 profitable folds, only 2 profitable years, and only one fold/year improvement versus B1.
- Candidate-minus-B1 arithmetic net delta was **−0.03%** despite the higher compounded endpoint; the path-dependent advantage lacked breadth and resampling support.

### Event-support concentration

All restored OOS exposure in each market came from a **single** re-entry event, so largest-event concentration was **100%** in both markets. The BTC event was harmful while the ETH event was strongly beneficial. The architecture did not establish a repeatable cross-market recovery relationship.

## Diagnostic repair

The initial diagnostic pooled feature-state distributions across training and development OOS, obscuring temporal transportability. The terminal version partitions feature and phase summaries by frozen sample, attributes restored exposure at event level, and compares every fold and calendar year with B1. The full experiment reran twice with byte-identical `result.json`. No feature, state transition, position, fee, return, benchmark, bootstrap result, acceptance gate or verdict changed.

## Verdict

```text
reject_exact_bounded_recovery_reentry_loss_budget_family
```

No same-interval change to the recovery inequality, 168H horizon, volatility estimator, loss-budget rule, re-entry count, cadence, fee, sample, market-specific treatment or uncertainty specification is authorised. No G1 nomination, paper promotion or live-trading authorisation results.

**Remaining blocker:** bounded re-entry repaired a large ETH lockout loss but depended on one event, harmed BTC, increased turnover in both markets and failed breadth and uncertainty requirements.

**Next experiment:** preregister one own-history-only signed-volume-flow persistence risk-state architecture. Within the unchanged 2,160H positive trend, use scale-free 168H quote-volume-weighted return-sign balance and its change from the preceding 168H block; enter a 50% risk state only when balance is negative and deteriorating, return to full exposure only when balance is positive and improving, and otherwise retain state. One candidate, fixed two-state hysteresis, no fitted threshold, no grid and no market-specific rule.
