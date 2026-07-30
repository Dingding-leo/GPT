# Downside-semivariance persistence risk-state sizing — terminal report

## Objective and frozen architecture

Test one own-history-only partial-risk architecture. Under a positive daily 2,160H trend, exposure is normally 1.0 and falls to 0.5 only when trailing 720H downside squared-return energy exceeds upside energy while the latest 168H downside-energy share is still increasing versus the prior 168H. Return to 1.0 requires both inequalities to clear. Candidate count was **1**, with **zero parameter-grid variants**, daily next-open execution and exactly **5 bps one way** on every absolute exposure change.

```text
family_id       downside-semivariance-persistence-risk-state-1h-v1
issue           #667
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

## Performance

### Training

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn (bps) | Mean exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | CANDIDATE | -37.12% | -0.950 | -50.35% | 28.00 | +1.40% | -145.88 | 30.49% |
| BTC-USDT | B0 | -41.02% | -0.831 | -55.56% | 138.00 | +6.90% | -32.09 | 40.18% |
| BTC-USDT | B1 | -41.29% | -0.840 | -55.92% | 28.00 | +1.40% | -159.81 | 40.49% |
| ETH-USDT | CANDIDATE | -26.05% | -0.543 | -38.31% | 24.00 | +1.20% | -100.93 | 28.86% |
| ETH-USDT | B0 | -46.84% | -0.744 | -57.75% | 88.00 | +4.40% | -56.53 | 45.06% |
| ETH-USDT | B1 | -40.59% | -0.584 | -56.95% | 23.00 | +1.15% | -168.77 | 44.60% |

### Development OOS

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn (bps) | Mean exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | CANDIDATE | +117.29% | 1.065 | -24.94% | 52.00 | +2.60% | 172.23 | 45.93% |
| BTC-USDT | B0 | +111.64% | 0.917 | -22.68% | 203.00 | +10.15% | 45.31 | 57.25% |
| BTC-USDT | B1 | +119.68% | 0.954 | -26.55% | 45.00 | +2.25% | 212.75 | 57.32% |
| ETH-USDT | CANDIDATE | +98.70% | 0.848 | -38.12% | 34.00 | +1.70% | 253.24 | 37.64% |
| ETH-USDT | B0 | +68.02% | 0.618 | -47.30% | 139.00 | +6.95% | 58.31 | 49.70% |
| ETH-USDT | B1 | +74.52% | 0.646 | -47.77% | 30.00 | +1.50% | 283.58 | 49.72% |

### Full scored

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn (bps) | Mean exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | CANDIDATE | +36.63% | 0.383 | -50.35% | 80.00 | +4.00% | 60.89 | 40.36% |
| BTC-USDT | B0 | +24.82% | 0.310 | -55.56% | 341.00 | +17.05% | 13.98 | 51.08% |
| BTC-USDT | B1 | +28.97% | 0.332 | -55.92% | 73.00 | +3.65% | 69.85 | 51.25% |
| ETH-USDT | CANDIDATE | +46.93% | 0.421 | -38.31% | 58.00 | +2.90% | 106.69 | 34.47% |
| ETH-USDT | B0 | -10.68% | 0.158 | -57.75% | 227.00 | +11.35% | 13.79 | 48.03% |
| ETH-USDT | B1 | +3.68% | 0.233 | -56.95% | 53.00 | +2.65% | 87.28 | 47.87% |

## Breadth and uncertainty

| Market | Profitable folds | Profitable years | Concentration | Residual Sharpe vs B1 | Mean Δ 95% interval | Sharpe Δ 95% interval |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 5/12 | 3/4 | +33.81% | -0.195 | [-13.78%, +9.13%] | [-0.208, 0.437] |
| ETH-USDT | 6/12 | 3/4 | +23.99% | 0.021 | [-17.84%, +18.09%] | [-0.171, 0.550] |

## State and failure diagnostics

### BTC-USDT

- Training trigger rate: **30.98%**; development OOS: **26.67%**.
- OOS half-exposure hours: **5,904**; full-exposure hours: **8,953**.
- Candidate-less exposure versus B1: **2,952.0 exposure-hours**; market contribution delta **-5.83%**; incremental fees **+0.35%**.
- OOS folds with improved arithmetic net versus B1: **4/12**.

### ETH-USDT

- Training trigger rate: **31.15%**; development OOS: **29.81%**.
- OOS half-exposure hours: **6,264**; full-exposure hours: **6,624**.
- Candidate-less exposure versus B1: **3,132.0 exposure-hours**; market contribution delta **+1.23%**; incremental fees **+0.20%**.
- OOS folds with improved arithmetic net versus B1: **5/12**.

## Failure mechanism

The same fixed downside-asymmetry state had opposite economics across the two development markets.

- **BTC:** the candidate reduced B1 exposure by 2,952 full-exposure-equivalent hours. Risk-trigger decisions were followed by positive mean market returns over both 24H and 168H horizons, so the half-risk state removed **5.83%** of arithmetic market return and added **0.35%** of incremental fees. OOS return remained below B1, turnover rose from 45 to 52, edge per turnover fell from 212.75 to 172.23 bps, residual Sharpe was negative, and only 4/12 folds improved versus B1.
- **ETH:** the half-risk state avoided approximately **1.23%** of arithmetic market loss and materially improved OOS return, Sharpe and drawdown. However, turnover rose from 30 to 34, edge per turnover fell from 283.58 to 253.24 bps, only 5/12 folds improved versus B1, and both paired moving-block lower confidence bounds remained negative.

The feature frequency was stable rather than disappearing: trigger rates moved from 30.98% to 26.67% for BTC and from 31.15% to 29.81% for ETH. The rejection is therefore economic and cross-market, not a feature-activation failure. A fixed downside-energy state did not transport reliably enough to support bilateral qualification.

## Repaired discrepancy

The first diagnostic version attributed turnover transitions using the decision-bar index, while fees are incurred at the following next-open execution bar. Transition attribution was repaired to use the stored execution index `t+1`, and exact turnover reconstruction was asserted against the backtest ledger. The complete experiment was rerun twice with byte-identical protocol, result and report outputs. No signal, exposure, fee, metric, bootstrap result, acceptance gate or verdict changed.

## Verdict

```text
reject_exact_downside_semivariance_persistence_risk_state_family
```

No window, exposure fraction, inequality, hysteresis, cadence, fee, market-specific or uncertainty rescue is authorised on this consumed interval.

## Remaining blocker and next experiment

The downside-asymmetry state is not economically transportable across the two development markets: it removed profitable BTC carry, while ETH point estimates improved but remained too narrow and uncertain to qualify.

**Next experiment:** Preregister one own-history-only bipower-jump-concentration trend-carry architecture: retain the 2,160H base trend, estimate fixed 720H realized variance and bipower variation, and use a partial risk state only when the latest 168H jump-variation share is both above its preceding 168H value and accompanied by a negative 168H return; one candidate, no fitted threshold, no market-specific rule and no forced hold.
