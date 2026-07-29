# Robust block-slope breadth hysteresis — terminal research report

## Objective and frozen rule

The experiment tested whether directional breadth across twelve non-overlapping 180-hour segments could repair the state instability of the rejected median-only distributed-slope family. The architecture was preregistered in issue #637 before development-OOS inspection.

```text
family_id              robust-block-slope-breadth-hysteresis-1h-v1
candidate_count        1
parameter_grid_count   0
canonical fee          exactly 5 bps one-way
decision cadence       daily 00:00 UTC
execution              completed bar t -> open[t+1]
verdict                reject_exact_robust_block_slope_breadth_hysteresis_family
```

At each decision, thirteen boundary closes spanning 2,160 hours formed twelve adjacent 180H log-return slopes. The candidate combined the NumPy median slope with the count of strictly positive slopes:

```text
cash -> long   median_slope > 0 and positive_breadth >= training q70 (method=higher)
long -> cash   median_slope < 0 and positive_breadth <= training q30 (method=lower)
otherwise      carry prior target
```

The quantile probabilities and methods were fixed before OOS inspection. Boundaries used feature distributions only, never training PnL or benchmark performance.

## Immutable data and sample

| Market | Artifact | Artifact ZIP SHA-256 | CSV SHA-256 | Source observations | Parsed prefix |
|---|---:|---|---|---:|---:|
| BTC-USDT | 8704977298 | `22d6d0e7f5dbffe4e746f091a5ab2488e3edc7d8440fea393ee2862295cf208c` | `92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9` | 43,941 | 43,441 |
| ETH-USDT | 8704978112 | `e7107f83a4eb5059ada0bb2097aeb5ded976dc9c037f564538f5cf5b4a7dffe3` | `2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726` | 43,941 | 43,441 |

Both downloaded archives passed every entry in their embedded SHA-256 manifests. Both CSVs passed hash, uniqueness, contiguous hourly chronology, confirmed-bar, finite-positive OHLC and high/low consistency checks.

```text
source workflow       30401519824
warm-up               [0, 2,880)
training              [2,880, 17,520)  2021-11-21 through 2023-07-23 UTC
development OOS       [17,520, 43,440) 2023-07-24 through 2026-07-07 UTC
full scored           [2,880, 43,440)
OOS folds             12 x 2,160H
later suffix          unread and unscored
```

## Training-only boundaries

| Market | Decisions | Breadth mean | Breadth median | Entry q70-higher | Exit q30-lower | Positive-median rate |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 610 | 5.610 | 6.0 | 6 | 5 | 40.33% |
| ETH-USDT | 610 | 5.723 | 6.0 | 7 | 5 | 46.23% |

## Performance

### Training

| Market | Policy | Net return | Sharpe | Max DD | Turnover | Fees | Edge/turn (bps) | Exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | -32.23% | -0.474 | -58.79% | 115 | +5.75% | -24.57 | +50.33% |
| BTC-USDT | B0 hourly trend | -41.02% | -0.831 | -55.56% | 138 | +6.90% | -32.09 | +40.18% |
| BTC-USDT | B1 daily trend | -41.29% | -0.840 | -55.92% | 28 | +1.40% | -159.81 | +40.49% |
| ETH-USDT | Candidate | -41.18% | -0.562 | -57.91% | 99 | +4.95% | -39.16 | +46.73% |
| ETH-USDT | B0 hourly trend | -46.84% | -0.744 | -57.75% | 88 | +4.40% | -56.53 | +45.06% |
| ETH-USDT | B1 daily trend | -40.59% | -0.584 | -56.95% | 23 | +1.15% | -168.77 | +44.60% |

### Development OOS

| Market | Policy | Net return | Sharpe | Max DD | Turnover | Fees | Edge/turn (bps) | Exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | +146.74% | 1.026 | -35.50% | 113 | +5.65% | +96.99 | +61.85% |
| BTC-USDT | B0 hourly trend | +111.64% | 0.917 | -22.68% | 203 | +10.15% | +45.31 | +57.25% |
| BTC-USDT | B1 daily trend | +119.68% | 0.954 | -26.55% | 45 | +2.25% | +212.75 | +57.32% |
| ETH-USDT | Candidate | +25.63% | 0.396 | -57.59% | 90 | +4.50% | +57.89 | +48.24% |
| ETH-USDT | B0 hourly trend | +68.02% | 0.618 | -47.30% | 139 | +6.95% | +58.31 | +49.70% |
| ETH-USDT | B1 daily trend | +74.52% | 0.646 | -47.77% | 30 | +1.50% | +283.58 | +49.72% |

### Full scored sample

| Market | Policy | Net return | Sharpe | Max DD | Turnover | Fees | Edge/turn (bps) | Exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | +67.21% | 0.489 | -58.79% | 228 | +11.40% | +35.67 | +57.69% |
| BTC-USDT | B0 hourly trend | +24.82% | 0.310 | -55.56% | 341 | +17.05% | +13.98 | +51.08% |
| BTC-USDT | B1 daily trend | +28.97% | 0.332 | -55.92% | 73 | +3.65% | +69.85 | +51.25% |
| ETH-USDT | Candidate | -26.11% | 0.066 | -57.91% | 189 | +9.45% | +7.05 | +47.69% |
| ETH-USDT | B0 hourly trend | -10.68% | 0.158 | -57.75% | 227 | +11.35% | +13.79 | +48.03% |
| ETH-USDT | B1 daily trend | +3.68% | 0.233 | -56.95% | 53 | +2.65% | +87.28 | +47.87% |

## Breadth, residuals and uncertainty

| Market | Profitable folds | Profitable years | Positive-fold concentration | Residual Sharpe vs B0 | Residual Sharpe vs B1 | Mean Δ L95 vs B1 | Sharpe Δ L95 vs B1 |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 5/12 | 2/4 | 31.77% | +0.347 | +0.272 | -17.04% | -0.546 |
| ETH-USDT | 6/12 | 2/4 | 23.52% | -0.438 | -0.511 | -36.57% | -0.835 |

BTC improved OOS return and Sharpe versus B1 on point estimates, but failed turnover, drawdown, fold/year breadth, edge-per-turnover and both dependence-aware uncertainty gates. ETH failed cross-market replication and underperformed B1 in return, Sharpe, drawdown, turnover efficiency and residual Sharpe.

## Failure mechanism

The breadth hysteresis reduced state changes relative to the rejected median-only family, but did not approach the daily benchmark's turnover:

| Market | Median-only prior turnover | Breadth-hysteresis turnover | Reduction | B1 turnover | Median OOS episode | Profitable episodes |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 143 | 113 | 21.0% | 45 | 96H | 49.1% |
| ETH-USDT | 180 | 90 | 50.0% | 30 | 72H | 33.3% |

Exposure attribution versus B1:

| Market | Candidate-only hours | Candidate-only gross sum | B1-only hours | B1-only gross sum | Post-entry positive 168H | Post-exit negative 168H |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 2,567 | +17.30% | 1,393 | +0.04% | 44.6% | 50.0% |
| ETH-USDT | 1,320 | -36.63% | 1,704 | -6.65% | 24.4% | 68.9% |

BTC's extra exposure was profitable in aggregate, but the candidate entered and exited too frequently and suffered a drawdown 8.95 percentage points worse than B1. Only 5/12 folds and 2/4 years were profitable, so the point-estimate advantage was not temporally broad.

ETH's candidate-only exposure was strongly harmful: 1,320 added hours contributed -36.63% arithmetic market return. Only 24.4% of complete entry windows were positive over the following 168 hours, while the full candidate lost 26.11% over the scored sample. The breadth state therefore did not identify persistent ETH upside.

### Diagnostic repair

The initial feature-drift summary reported unconditional entry and exit-condition rates only. That obscured a discrete-boundary degeneracy in BTC: the training q70-higher entry boundary was six, and every positive-median decision already had breadth of at least six. The entry breadth gate therefore excluded 0% of positive-median decisions in both training and OOS; only delayed exits differentiated the rule from the median sign.

Conditional exclusion/delay rates and an explicit degeneracy flag were added, and the exact experiment was rerun. No feature, threshold, position, return, fee, comparator, gate, bootstrap interval or verdict changed.

| Market | Entry exclusion given positive median, train / OOS | Exit delay given negative median, train / OOS | Entry gate degenerate |
|---|---:|---:|---:|
| BTC-USDT | 0.0% / 0.0% | 26.1% / 23.8% | true |
| ETH-USDT | 27.0% / 18.1% | 24.1% / 22.6% | false |

## Verdict

```text
reject_exact_robust_block_slope_breadth_hysteresis_family
```

The exact family is rejected. No threshold, quantile, block layout, sign condition, hysteresis, holding rule, cadence, endpoint blend or market-specific rescue is authorised on this consumed development interval. There is no G1 nomination, prospective-paper promotion or live-trading authorisation.

## Remaining blocker and next strategy experiment

No statistically eligible frozen causal 1H strategy exists.

The next experiment should be materially orthogonal: preregister one own-history-only **volatility-normalised multi-horizon temporal ensemble** using fixed 720H, 1,440H and 2,160H causal trend scores, a fixed median ensemble and one training-only no-trade confidence boundary. Its purpose is to combine trend information across distinct decay horizons rather than retune block breadth or hysteresis on this consumed family.

## Evidence hashes

- core SHA-256: `8ac6fb135bae68d009e2678c44e0e32577f596cee214123788a9ce6163104236`
- runner SHA-256: `4a94beb4ed348f07d9782c199867a6a4392916ed08756a01ae6800ee189ee38a`
- result SHA-256: `fb280dcfd5b990319863831042d6aa45a951ce0cf234135baa0a695a9b869efd`
