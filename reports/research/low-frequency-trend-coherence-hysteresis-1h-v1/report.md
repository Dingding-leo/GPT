# Low-frequency trend-coherence hysteresis — terminal research report

## Objective and frozen rule

Test whether a causal projection of each instrument's trailing 2,160-hour log-price path can distinguish a coherent slow trend from a curved or reversing path more robustly than the two-endpoint daily 2,160H trend comparator.

The sole candidate was frozen in issue #634 before development-OOS performance inspection:

```text
family_id              low-frequency-trend-coherence-hysteresis-1h-v1
candidate_count        1
parameter_grid_count   0
canonical_fee          exactly 5 bps one-way
cadence                daily 00:00 UTC
execution              completed bar t -> open[t+1]
verdict                reject_exact_low_frequency_trend_coherence_hysteresis_family
```

For each instrument independently, the trailing 2,160 completed hourly log closes were demeaned and projected onto a fixed discrete orthonormal Legendre basis P1:P4. P1 is the oriented linear trend component; P2:P4 are fixed low-frequency curvature components.

```text
coherence_t = coef(P1)^2 / sum(coef(P1:P4)^2)

cash -> long  when slope_t > 0 and coherence_t >= training-positive-slope q70
long -> cash  when slope_t <= 0 or coherence_t <= training-positive-slope q45
otherwise     retain prior target
```

State carries across folds and sample boundaries. No return metric selected a boundary, and no threshold, basis, horizon, market, cadence or fee variant was evaluated.

## Immutable data and sample

| Market | Source artifact | Artifact ZIP SHA-256 | CSV SHA-256 | Source observations | Loaded prefix |
|---|---:|---|---|---:|---:|
| BTC-USDT | 8704977298 | `22d6d0e7f5dbffe4e746f091a5ab2488e3edc7d8440fea393ee2862295cf208c` | `92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9` | 43,941 | 43,441 |
| ETH-USDT | 8704978112 | `e7107f83a4eb5059ada0bb2097aeb5ded976dc9c037f564538f5cf5b4a7dffe3` | `2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726` | 43,941 | 43,441 |

```text
source workflow       30401519824
warm-up               [0, 2,880)
training              [2,880, 17,520)
development OOS       [17,520, 43,440)
full scored           [2,880, 43,440)
OOS folds             12 x 2,160H
later suffix          unread and unscored
```

Both markets passed exact source-hash, confirmed-bar, continuity, uniqueness, positivity, fixed-basis, chronology, next-open and exact fee-accounting checks.

## Training-only boundaries

| Market | Positive-slope decisions | Entry q70 | Exit q45 | Entries / exits | Daily target exposure |
|---|---:|---:|---:|---:|---:|
| BTC-USDT | 227 / 610 | 0.7579595283 | 0.5839852314 | 2 / 3 | 19.18% |
| ETH-USDT | 280 / 610 | 0.6968985404 | 0.5474091765 | 3 / 3 | 21.64% |

The BTC exit count and exposure above include state inherited from the eligible pretraining history. A freeze-time diagnostic initially reset state at the training boundary and reported 2/2 transitions and 16.89% exposure. That accounting was repaired before publication. No feature, position, return, fee, comparator, acceptance gate, bootstrap result, OOS access boundary or verdict changed.

## Training performance

| Market | Policy | Net return | Sharpe | Max DD | Turnover | Fees | Edge/turn | Exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC | Candidate | -0.02% | 0.121 | -27.18% | 5 | +0.25% | +98.12 bps | 19.19% |
| BTC | B1 daily trend | -41.29% | -0.840 | -55.92% | 28 | +1.40% | -159.81 bps | 40.49% |
| ETH | Candidate | -15.11% | -0.197 | -40.48% | 6 | +0.30% | -157.32 bps | 21.64% |
| ETH | B1 daily trend | -40.59% | -0.584 | -56.95% | 23 | +1.15% | -168.77 bps | 44.60% |

The candidate materially reduced training losses and drawdown versus B1, but ETH remained negative and BTC compounded approximately flat.

## Development-OOS performance

| Market | Policy | Net return | Sharpe | Max DD | Turnover | Fees | Edge/turn | Exposure | Entries |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC | Candidate | +23.19% | 0.403 | -30.48% | 10 | +0.50% | +305.44 bps | 30.93% | 5 |
| BTC | B1 daily trend | +119.68% | 0.954 | -26.55% | 45 | +2.25% | +212.75 bps | 57.32% | 22 |
| ETH | Candidate | **+133.85%** | **0.999** | **-30.99%** | 8 | +0.40% | **+1285.80 bps** | 31.30% | 4 |
| ETH | B1 daily trend | +74.52% | 0.646 | -47.77% | 30 | +1.50% | +283.58 bps | 49.72% | 15 |

BTC improved turnover efficiency but sacrificed 96.50 percentage points of compounded return, 0.550 Sharpe and 3.94 percentage points of drawdown versus B1. ETH improved every headline point estimate: +59.34 percentage points of return, +0.354 Sharpe, 16.78 percentage points of drawdown, 22 fewer one-way changes and +1,002.22 bps edge per turnover.

## Full scored sample

| Market | Policy | Net return | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC | Candidate | +23.16% | 0.305 | -30.48% | 15 | +0.75% | +236.33 bps |
| BTC | B1 | +28.97% | 0.332 | -55.92% | 73 | +3.65% | +69.85 bps |
| ETH | Candidate | +98.53% | 0.616 | -40.48% | 14 | +0.70% | +667.32 bps |
| ETH | B1 | +3.68% | 0.233 | -56.95% | 53 | +2.65% | +87.28 bps |

## Breadth, residuals and uncertainty

| Market | Profitable folds | Profitable years | Positive-fold concentration | Residual Sharpe vs B0 / B1 | Mean delta L95 vs B1 | Sharpe delta L95 vs B1 |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 4/12 | 3/4 | 45.28% | -0.929 / -0.987 | -52.89% | -1.485 |
| ETH-USDT | 7/12 | 3/4 | 26.83% | +0.267 / +0.215 | -29.40% | -0.460 |

BTC failed breadth, drawdown, return, Sharpe, residual and both uncertainty gates. ETH passed every point-estimate and breadth gate, but its paired-bootstrap lower bounds were not strictly positive:

```text
ETH annualized mean delta vs B1   +6.01%
95% interval                      [-29.40%, +36.54%]

ETH Sharpe delta vs B1            +0.354
95% interval                      [-0.460, +1.102]
```

## Failure mechanism

The same selector produced opposite economic effects across markets.

| Diagnostic | BTC-USDT | ETH-USDT |
|---|---:|---:|
| OOS candidate entries / exits | 5 / 5 | 4 / 4 |
| Median episode duration | 1992H | 2004H |
| Profitable episode ratio | 60.0% | 75.0% |
| Candidate-only hours vs B1 | 24 | 24 |
| Candidate-only market gross sum | +2.06% | +1.75% |
| B1-only hours omitted | 6,865 | 4,800 |
| Omitted market gross sum | +69.00% | -14.94% |
| Post-entry positive next-168H ratio | 80.0% | 75.0% |
| Post-exit negative next-168H ratio | 40.0% | 75.0% |

For BTC, the high-coherence gate omitted 6,865 B1-long hours that gained +69.00% arithmetically. Exit calibration was weak: only 40% of exits were followed by a negative next 168 hours. The architecture was therefore too selective and exited profitable continuing trends.

For ETH, the gate omitted 4,800 B1-long hours that lost -14.94% arithmetically, generating strong point-estimate improvement. However, the evidence came from only four OOS entries and four long episodes, with two large winning episodes. Dependence-aware resampling could not establish a strictly positive incremental mean or Sharpe. The ETH result is promising descriptive evidence, not a statistically eligible bilateral strategy.

Feature-state frequencies also drifted. Positive-slope entry-boundary exceedance rose from 30.0% in training to 45.6% OOS for BTC and 48.6% for ETH; the frozen threshold therefore became less selective, but this frequency shift did not create cross-market-consistent economic calibration.

## Verdict

```text
reject_exact_low_frequency_trend_coherence_hysteresis_family
```

No basis-order, coherence-boundary, window, hysteresis, market-specific, cadence, fee or execution rescue is authorised on this consumed development interval. There is no G1 nomination, prospective-paper promotion or live-trading authorisation.

## Reproducibility hashes

```text
script SHA-256    9066cf6226c03bad8e4e861e430449653937af2199a9091566c59bf38b917e2d
protocol SHA-256  b0d72067286dfbe0e002f531ea35b6b6042923450c1be6fbb88f1c8e99800f3e
result SHA-256    22a1f131e22d514cc0c937a5b256a58598aa6de4121a61f3ce8773dc26559260
```

## Next strategy experiment

Preregister one own-history-only **robust block-slope breadth trend** architecture. Partition the trailing 2,160H log-price path into twelve fixed non-overlapping 180H blocks; use the median block slope and the count of positive block slopes as a temporal breadth signal; freeze one hysteretic long/cash rule from training-only feature distributions; use one candidate, no grid, daily next-open execution, exactly 5 bps one-way fees and the same bilateral breadth, drawdown, residual and paired-block uncertainty gates. This tests distributed trend persistence rather than another path-energy threshold.
