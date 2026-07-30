# Bipower-jump-concentration trend-carry sizing — terminal report

## Objective and frozen architecture

Test one own-history-only partial-risk architecture. Under a positive daily 2,160H trend, exposure is 0.5 only when the trailing 720H jump-variation share is positive, the latest 168H jump share exceeds the immediately preceding 168H share, and the latest 168H cumulative return is negative; otherwise exposure is 1. Candidate count is **1**, with **zero parameter-grid variants**, no hysteresis, daily next-open execution and exactly **5 bps one way**.

```text
family_id       bipower-jump-concentration-trend-carry-1h-v1
issue           #670
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
| BTC-USDT | CANDIDATE | -39.96% | -0.910 | -53.07% | 47.50 | +2.38% | -92.64 | 34.35% |
| BTC-USDT | B0 | -41.02% | -0.831 | -55.56% | 138.00 | +6.90% | -32.09 | 40.18% |
| BTC-USDT | B1 | -41.29% | -0.840 | -55.92% | 28.00 | +1.40% | -159.81 | 40.49% |
| ETH-USDT | CANDIDATE | -34.27% | -0.560 | -47.37% | 39.00 | +1.95% | -82.31 | 37.55% |
| ETH-USDT | B0 | -46.84% | -0.744 | -57.75% | 88.00 | +4.40% | -56.53 | 45.06% |
| ETH-USDT | B1 | -40.59% | -0.584 | -56.95% | 23.00 | +1.15% | -168.77 | 44.60% |

### Development OOS

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn (bps) | Mean exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | CANDIDATE | +99.21% | 0.896 | -27.44% | 76.50 | +3.83% | 109.38 | 51.76% |
| BTC-USDT | B0 | +111.64% | 0.917 | -22.68% | 203.00 | +10.15% | 45.31 | 57.25% |
| BTC-USDT | B1 | +119.68% | 0.954 | -26.55% | 45.00 | +2.25% | 212.75 | 57.32% |
| ETH-USDT | CANDIDATE | +58.09% | 0.582 | -42.46% | 57.00 | +2.85% | 124.45 | 44.95% |
| ETH-USDT | B0 | +68.02% | 0.618 | -47.30% | 139.00 | +6.95% | 58.31 | 49.70% |
| ETH-USDT | B1 | +74.52% | 0.646 | -47.77% | 30.00 | +1.50% | 283.58 | 49.72% |

### Full scored

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn (bps) | Mean exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | CANDIDATE | +19.60% | 0.280 | -53.07% | 124.00 | +6.20% | 32.00 | 45.48% |
| BTC-USDT | B0 | +24.82% | 0.310 | -55.56% | 341.00 | +17.05% | 13.98 | 51.08% |
| BTC-USDT | B1 | +28.97% | 0.332 | -55.92% | 73.00 | +3.65% | 69.85 | 51.25% |
| ETH-USDT | CANDIDATE | +3.92% | 0.216 | -47.37% | 96.00 | +4.80% | 40.46 | 42.28% |
| ETH-USDT | B0 | -10.68% | 0.158 | -57.75% | 227.00 | +11.35% | 13.79 | 48.03% |
| ETH-USDT | B1 | +3.68% | 0.233 | -56.95% | 53.00 | +2.65% | 87.28 | 47.87% |

## Breadth and uncertainty

| Market | Profitable folds | Profitable years | Concentration | Residual Sharpe vs B1 | Mean Δ 95% interval | Sharpe Δ 95% interval |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 4/12 | 3/4 | +39.73% | -0.569 | [-14.17%, +5.26%] | [-0.344, 0.214] |
| ETH-USDT | 6/12 | 3/4 | +25.62% | -0.491 | [-15.52%, +4.68%] | [-0.313, 0.161] |

## State diagnostics

### BTC-USDT

- Eligible positive-trend trigger rate: **30.36% training** -> **19.39% OOS**; unconditional daily rate: **21.94% OOS**.
- OOS half-exposure hours: **2,881**; full-exposure hours: **11,976**.
- Candidate-less exposure versus B1: **1,440.5 exposure-hours**; market contribution delta **-10.48%**; incremental fees **+1.58%**.
- Trigger forward 168H: **120** complete decisions, mean **+0.74%**, positive rate **56.67%**.
- OOS folds with improved arithmetic net versus B1: **4/12**.

### ETH-USDT

- Eligible positive-trend trigger rate: **31.62% training** -> **19.18% OOS**; unconditional daily rate: **23.61% OOS**.
- OOS half-exposure hours: **2,472**; full-exposure hours: **10,416**.
- Candidate-less exposure versus B1: **1,236.0 exposure-hours**; market contribution delta **-12.79%**; incremental fees **+1.35%**.
- Trigger forward 168H: **103** complete decisions, mean **-0.92%**, positive rate **48.54%**.
- OOS folds with improved arithmetic net versus B1: **4/12**.

## Failure mechanism

The jump-share state was not a monotonic warning signal. The half-exposure hours carried positive arithmetic market return in both markets, so scaling down removed profitable trend carry. The candidate also increased daily state transitions and fees versus B1. BTC’s event-level forward return was positive; ETH’s overlapping 168H event diagnostic was negative, but the realised half-state hours still earned positive carry and only four folds improved. Activation among eligible positive-trend decisions fell from approximately 30–32% in training to approximately 19% OOS.

## Verdict

```text
reject_exact_bipower_jump_concentration_trend_carry_family
```

Both markets remained profitable, but both lost compounded return and Sharpe versus B1, increased turnover, reduced edge per turnover, missed the 7/12 fold-breadth gate, had negative residual Sharpe and produced negative dependence-aware lower bounds. BTC also worsened maximum drawdown. The exact family is rejected.

No same-interval horizon, fraction, jump estimator, inequality, cadence, fee or market-specific rescue is authorised.

## Repaired discrepancy

The first report displayed trigger frequency over all daily decisions, even though the risk state can affect exposure only while the 2,160H base trend is positive. The terminal report separates unconditional frequency from the eligible positive-trend trigger rate and uses the latter for transport diagnostics. No feature, position, fee, return, benchmark, bootstrap result, gate or verdict changed.

## Remaining blocker and next experiment

Increasing jump-share concentration was not a monotonic warning state. A useful risk state must identify negative conditional carry rather than merely discontinuous recent variation.

**Next experiment:** preregister one own-history-only signed-range compression breakout architecture using a fixed 720H Parkinson range-volatility baseline and a 168H close-to-range efficiency change to identify efficient trend continuation, with one candidate, no fitted threshold, no forced hold and unchanged 2,160H trend exit.
