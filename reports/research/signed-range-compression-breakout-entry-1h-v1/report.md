# Signed-range compression-breakout entry — terminal report

## Objective and frozen architecture

Test one own-history-only entry architecture. A flat strategy may enter an instrument's positive daily 2,160H trend only after a completed 168H low-range interval, measured against a preceding non-overlapping 720H Parkinson range-volatility baseline, is followed by a positive improvement in 168H signed close-to-range efficiency. After entry, the feature is ignored and the unchanged 2,160H trend controls the exit. Candidate count is **1**, with **zero parameter-grid variants**, daily next-open execution and exactly **5 bps one way**.

```text
family_id       signed-range-compression-breakout-entry-1h-v1
issue           #673
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
| BTC-USDT | CANDIDATE | -22.48% | -0.386 | -40.08% | 13.00 | +0.65% | -142.56 | 31.81% |
| BTC-USDT | B0 | -41.02% | -0.831 | -55.56% | 138.00 | +6.90% | -32.09 | 40.18% |
| BTC-USDT | B1 | -41.29% | -0.840 | -55.92% | 28.00 | +1.40% | -159.81 | 40.49% |
| ETH-USDT | CANDIDATE | -22.73% | -0.250 | -42.60% | 7.00 | +0.35% | -214.19 | 34.76% |
| ETH-USDT | B0 | -46.84% | -0.744 | -57.75% | 88.00 | +4.40% | -56.53 | 45.06% |
| ETH-USDT | B1 | -40.59% | -0.584 | -56.95% | 23.00 | +1.15% | -168.77 | 44.60% |

### Development OOS

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn (bps) | Mean exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | CANDIDATE | +123.60% | 0.990 | -29.54% | 24.00 | +1.20% | 402.22 | 51.94% |
| BTC-USDT | B0 | +111.64% | 0.917 | -22.68% | 203.00 | +10.15% | 45.31 | 57.25% |
| BTC-USDT | B1 | +119.68% | 0.954 | -26.55% | 45.00 | +2.25% | 212.75 | 57.32% |
| ETH-USDT | CANDIDATE | +9.48% | 0.282 | -54.15% | 18.00 | +0.90% | 192.74 | 43.06% |
| ETH-USDT | B0 | +68.02% | 0.618 | -47.30% | 139.00 | +6.95% | 58.31 | 49.70% |
| ETH-USDT | B1 | +74.52% | 0.646 | -47.77% | 30.00 | +1.50% | 283.58 | 49.72% |

### Full scored

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn (bps) | Mean exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | CANDIDATE | +73.34% | 0.535 | -40.08% | 37.00 | +1.85% | 210.81 | 44.68% |
| BTC-USDT | B0 | +24.82% | 0.310 | -55.56% | 341.00 | +17.05% | 13.98 | 51.08% |
| BTC-USDT | B1 | +28.97% | 0.332 | -55.92% | 73.00 | +3.65% | 69.85 | 51.25% |
| ETH-USDT | CANDIDATE | -15.41% | 0.107 | -54.15% | 25.00 | +1.25% | 78.80 | 40.06% |
| ETH-USDT | B0 | -10.68% | 0.158 | -57.75% | 227.00 | +11.35% | 13.79 | 48.03% |
| ETH-USDT | B1 | +3.68% | 0.233 | -56.95% | 53.00 | +2.65% | 87.28 | 47.87% |

## Breadth and uncertainty

| Market | Profitable folds | Profitable years | Concentration | Residual Sharpe vs B1 | Mean Δ 95% interval | Sharpe Δ 95% interval |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 6/12 | 3/4 | +35.30% | +0.033 | [-9.38%, +7.77%] | [-0.248, +0.258] |
| ETH-USDT | 5/12 | 3/4 | +30.35% | -1.068 | [-41.80%, +2.26%] | [-0.913, +0.073] |

## Failure mechanism

The architecture produced a superficially strong BTC point estimate but failed bilateral transportability and robust breadth. BTC exceeded B1 on OOS compounded return, Sharpe, turnover and edge per turnover, yet worsened maximum drawdown, reached only 6/12 profitable folds, and both paired-block lower confidence bounds remained negative. ETH underperformed B1 decisively and finished the full scored sample negative.

### BTC-USDT

- Entry-state frequency among positive-trend decisions: **22.27% training** -> **30.53% OOS**.
- OOS positive-trend regimes starting inside the sample: **12 qualified**, **10 skipped**; median qualified-entry delay **1.0 days**, maximum **17.0 days**.
- B1-only exposure: **1393H**. Delayed entries omitted **1080H** carrying **+18.84%** arithmetic market return; wholly skipped regimes omitted **313H** carrying **-18.59%**.
- Candidate fee saving versus B1: **+1.05%**. Candidate-only exposure was exactly zero, and the candidate-minus-B1 arithmetic result reconstructed exactly from omitted exposure and fee savings.
- Actual candidate entries: 24H forward mean **+1.18%** with 58.33% positive; 168H forward mean **+0.55%** with 50.00% positive.
- Folds with improved arithmetic net versus B1: **4/12**.

### ETH-USDT

- Entry-state frequency among positive-trend decisions: **20.96% training** -> **22.91% OOS**.
- OOS positive-trend regimes starting inside the sample: **9 qualified**, **6 skipped**; median qualified-entry delay **1.0 days**, maximum **32.0 days**.
- B1-only exposure: **1728H**. Delayed entries omitted **1224H** carrying **+61.99%** arithmetic market return; wholly skipped regimes omitted **504H** carrying **-11.00%**.
- Candidate fee saving versus B1: **+0.60%**. Candidate-only exposure was exactly zero, and the candidate-minus-B1 arithmetic result reconstructed exactly from omitted exposure and fee savings.
- Actual candidate entries: 24H forward mean **-1.31%** with 22.22% positive; 168H forward mean **-5.13%** with 11.11% positive.
- Folds with improved arithmetic net versus B1: **3/12**.

The key temporal failure was not feature disappearance. BTC's skipped regimes were loss-making enough to offset profitable delayed exposure, leaving a modest positive point estimate after fees. ETH's delay component alone omitted **+61.99%** arithmetic market return, while skipped regimes avoided only **11.00%** of losses. The rule therefore entered after the most valuable ETH trend acceleration had already occurred and then selected entries whose subsequent 24H and 168H returns were negative.

## Repaired discrepancy

The first terminal diagnostic grouped all B1-only exposure together. That obscured whether performance came from delaying ultimately qualified regimes or vetoing entire regimes. The reproducer was repaired to assign every omitted interval to exactly one underlying positive-trend regime and to split it into `delay` versus `skipped-regime` exposure. An exact mask identity now asserts that the two attribution buckets reconstruct all B1-only exposure. The experiment was rerun twice with byte-identical JSON output. No feature, position, fee, return, benchmark, bootstrap result, acceptance gate or verdict changed.

## Verdict

```text
reject_exact_signed_range_compression_breakout_entry_family
```

BTC failed drawdown, fold-breadth and both lower-confidence-bound gates. ETH additionally failed benchmark return, Sharpe, drawdown, edge per turnover, residual Sharpe and positive full-scored return. No same-interval window, inequality, efficiency normalisation, entry-state, cadence, fee or market-specific rescue is authorised. There is no G1 nomination, prospective-paper promotion or live-trading authorisation.

## Remaining blocker and next experiment

**Remaining blocker:** delayed-confirmation entry rules can avoid some failed regimes, but they also miss the highest-return early continuation, especially in ETH. The information state is not transportable as a gate on initial exposure.

**Next strategy experiment:** preregister one own-history-only **immediate-entry / failed-continuation exit** architecture. Enter immediately with the daily 2,160H base trend, grant a fixed 168H grace period, and thereafter move to cash only when both the trend-regime return since onset is non-positive and the latest 168H close-to-close return is negative; re-enter only on a new 2,160H positive-trend onset. One candidate, no fitted threshold, no fractional sizing, no forced minimum hold beyond the fixed grace period, and the unchanged 5 bps next-open accounting.
