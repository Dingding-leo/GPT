# Immediate-entry / failed-continuation exit — terminal report
## Objective and frozen architecture

Enter every new positive daily 2,160H trend immediately, grant a fixed 168H grace period, and then exit to cash only when both return since onset is non-positive and the latest 168H return is negative. After a failed exit, remain locked out until a distinct later positive-trend onset. Candidate count is **1**, with **zero parameter-grid variants**, daily next-open execution and exactly **5 bps one way**.
## Immutable data and sample

| Item | Frozen value |
|---|---|
| Provider | Public confirmed OKX SPOT |
| Markets | BTC-USDT and ETH-USDT independently |
| Source rows | 43,941 per market |
| Parsed immutable prefix | 43,441 bars |
| Training | `[2,880,17,520)` |
| Development OOS | `[17,520,43,440)` |
| Full scored | `[2,880,43,440)` |
| OOS folds | 12 × 2,160H |
| Uncertainty | 5,000 paired non-circular 168H blocks |
| Later suffix | Unread and unscored |
## Training

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn bps | Mean exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | CANDIDATE | -42.48% | -1.409 | -44.95% | 27.00 | +1.35% | -190.09 | 21.14% |
| BTC-USDT | B0 | -41.02% | -0.831 | -55.56% | 138.00 | +6.90% | -32.09 | 40.18% |
| BTC-USDT | B1 | -41.29% | -0.840 | -55.92% | 28.00 | +1.40% | -159.81 | 40.49% |
| ETH-USDT | CANDIDATE | -20.08% | -0.600 | -30.13% | 22.00 | +1.10% | -87.76 | 10.82% |
| ETH-USDT | B0 | -46.84% | -0.744 | -57.75% | 88.00 | +4.40% | -56.53 | 45.06% |
| ETH-USDT | B1 | -40.59% | -0.584 | -56.95% | 23.00 | +1.15% | -168.77 | 44.60% |

## Development Oos

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn bps | Mean exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | CANDIDATE | +169.80% | 1.190 | -22.68% | 45.00 | +2.25% | 255.68 | 50.74% |
| BTC-USDT | B0 | +111.64% | 0.917 | -22.68% | 203.00 | +10.15% | 45.31 | 57.25% |
| BTC-USDT | B1 | +119.68% | 0.954 | -26.55% | 45.00 | +2.25% | 212.75 | 57.32% |
| ETH-USDT | CANDIDATE | +60.90% | 0.621 | -39.96% | 30.00 | +1.50% | 225.71 | 33.33% |
| ETH-USDT | B0 | +68.02% | 0.618 | -47.30% | 139.00 | +6.95% | 58.31 | 49.70% |
| ETH-USDT | B1 | +74.52% | 0.646 | -47.77% | 30.00 | +1.50% | 283.58 | 49.72% |

## Full Scored

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn bps | Mean exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | CANDIDATE | +55.19% | 0.471 | -50.94% | 72.00 | +3.60% | 88.52 | 40.06% |
| BTC-USDT | B0 | +24.82% | 0.310 | -55.56% | 341.00 | +17.05% | 13.98 | 51.08% |
| BTC-USDT | B1 | +28.97% | 0.332 | -55.92% | 73.00 | +3.65% | 69.85 | 51.25% |
| ETH-USDT | CANDIDATE | +28.59% | 0.330 | -39.96% | 52.00 | +2.60% | 93.08 | 25.21% |
| ETH-USDT | B0 | -10.68% | 0.158 | -57.75% | 227.00 | +11.35% | 13.79 | 48.03% |
| ETH-USDT | B1 | +3.68% | 0.233 | -56.95% | 53.00 | +2.65% | 87.28 | 47.87% |

## Breadth and uncertainty

| Market | Profitable folds | Profitable years | Concentration | Residual Sharpe | Mean delta 95% | Sharpe delta 95% |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 5/12 | 3/4 | 34.10% | +0.717 | [-6.13%, +19.88%] | [-0.138, +0.645] |
| ETH-USDT | 4/12 | 2/4 | 30.37% | -0.235 | [-38.80%, +24.67%] | [-0.772, +0.728] |

## Failure mechanism and diagnostics

### BTC-USDT

- OOS failed-continuation exits: **4**.
- B1-only lockout exposure: **1704H**, carrying **-19.32%** arithmetic market return.
- Incremental fees candidate minus B1: **+0.00%**.
- OOS regimes: **22 started**, **23 overlapping**; all-regime outcomes versus B1 **2 improved / 19 tied / 2 worse**.
- Failed-exit regime outcomes: **2 improved / 0 tied / 2 worse**.
- Post-exit 24H mean: **-0.86%**; 168H mean: **-1.93%**.

### ETH-USDT

- OOS failed-continuation exits: **3**.
- B1-only lockout exposure: **4248H**, carrying **+17.36%** arithmetic market return.
- Incremental fees candidate minus B1: **+0.00%**.
- OOS regimes: **15 started**, **15 overlapping**; all-regime outcomes versus B1 **2 improved / 12 tied / 1 worse**.
- Failed-exit regime outcomes: **2 improved / 0 tied / 1 worse**.
- Post-exit 24H mean: **-0.19%**; 168H mean: **-6.78%**.

## Diagnostic repair

The initial regime diagnostic reported only a strict-improvement count over all OOS-overlapping regimes, which conflated tied regimes with failures and did not distinguish the one BTC regime that began before OOS. The terminal diagnostic now reports started versus overlapping regimes and improved/tied/worse outcomes for all regimes and failed-exit regimes separately. No signal, position, fee, performance metric, uncertainty result, gate or verdict changed.

## Verdict

```text
reject_exact_immediate_entry_failed_continuation_exit_family
```

No same-interval grace-period, inequality, onset-reference, re-entry, cadence, fee or market-specific rescue is authorised. No G1 nomination, paper promotion or live authorisation results.

**Remaining blocker:** the joint failed-continuation condition does not yet show bilateral fold breadth and uncertainty-supported improvement over immediate slow-trend participation.

**Next strategy experiment:** Preregister one own-history-only trend-onset loss-budget architecture that enters immediately, never delays entry, and permits one irreversible same-regime exit only when cumulative adverse excursion from the highest completed daily close since onset exceeds the trailing 720H robust volatility scale while regime return is non-positive; one candidate, no grid and no re-entry until a new onset.
