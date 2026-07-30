# Trend-onset margin-source attribution selector — terminal rejection

## Frozen architecture

Issue #702 tested one own-history-only 1H candidate with no parameter grid. At each instrument's newly positive daily 2,160H endpoint-trend onset:

```text
current_leg   = log(close_t / close_(t-24H))
lag_leg       = log(close_(t-2160H) / close_(t-2184H))
stale_release = max(0, -lag_leg)

enter only when current_leg > stale_release
```

An accepted onset entered at the next hourly open and remained fully long until the unchanged base trend became non-positive. A rejected onset remained cash for the complete positive-trend regime. Exactly 5 bps one way was charged on absolute position turnover.

```text
family             trend-onset-margin-source-attribution-selector-1h-v1
candidate count    1
parameter grid     0
bar                1H
markets            BTC-USDT and ETH-USDT independently
execution          completed daily decision -> next hourly open
fee                exactly 5 bps one way
verdict             reject_exact_trend_onset_margin_source_attribution_selector_family
```

## Immutable real-data sample

| Item | Frozen specification |
|---|---|
| Provider | Public confirmed OKX SPOT |
| BTC artifact / SHA-256 | `8704977298` / `92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9` |
| ETH artifact / SHA-256 | `8704978112` / `2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726` |
| Source rows | 43,941 per market |
| Scored prefix | First 43,441 contiguous confirmed 1H rows |
| Training | `[2,880, 17,520)` |
| Development OOS | `[17,520, 43,440)` |
| Full scored | `[2,880, 43,440)` |
| OOS breadth | 12 contiguous 2,160H folds plus four calendar years |
| Uncertainty | 5,000 paired non-circular 168H moving-block resamples; seed `20260730` |

The 500 rows after the scored prefix were excluded from every feature, position, return, gate and diagnostic.

## Performance

### Training

| Market | Policy | Net return | Sharpe | Max DD | Turnover | Edge/turn |
|---|---|---:|---:|---:|---:|---:|
| BTC | Candidate | -7.56% | -0.040 | -31.88% | 12 | -14.96 bps |
| BTC | B1 | -41.29% | -0.840 | -55.92% | 28 | -159.81 bps |
| ETH | Candidate | -0.22% | 0.020 | -7.68% | 6 | 4.30 bps |
| ETH | B1 | -40.59% | -0.584 | -56.95% | 23 | -168.77 bps |

The selector substantially reduced training losses and drawdowns by spending most positive-trend time in cash. Neither training candidate demonstrated a durable positive-return architecture.

### Development OOS

| Market | Policy | Net return | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC | Candidate | **-1.07%** | 0.050 | **-15.13%** | **14** | 0.70% | 15.53 bps |
| BTC | B1 | **+119.68%** | **0.954** | -26.55% | 45 | 2.25% | **212.75 bps** |
| ETH | Candidate | +66.59% | **0.765** | **-29.63%** | **10** | 0.50% | **622.07 bps** |
| ETH | B1 | **+74.52%** | 0.646 | -47.77% | 30 | 1.50% | 283.58 bps |

BTC failed decisively. The selector converted a strong benchmark into a slightly losing strategy by rejecting most long-lived profitable regimes.

ETH improved Sharpe, drawdown, turnover and edge per turnover, but sacrificed 7.93 percentage points of compounded return and failed the frozen breadth, residual and uncertainty gates.

### Full scored sample

| Market | Policy | Net return | Sharpe | Max DD | Turnover | Edge/turn |
|---|---|---:|---:|---:|---:|---:|
| BTC | Candidate | -8.55% | 0.004 | -31.88% | 26 | 1.46 bps |
| BTC | B1 | **+28.97%** | **0.332** | -55.92% | 73 | **69.85 bps** |
| ETH | Candidate | **+66.21%** | **0.601** | **-29.63%** | **16** | **390.41 bps** |
| ETH | B1 | +3.68% | 0.233 | -56.95% | 53 | 87.28 bps |

The strong ETH full-sample point estimate was not accepted because the preregistered development-OOS return, fold/year breadth, benchmark-residual and dependence-aware requirements failed.

## Breadth and uncertainty

| Market | Profitable folds | Improved folds vs B1 | Profitable years | Positive-fold concentration | Residual Sharpe | Annualised mean delta 95% | Sharpe delta 95% |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC | 1/12 | 4/12 | 1/4 | 100.00% | -1.036 | [-69.06%, +0.57%] | [-2.172, +0.257] |
| ETH | 3/12 | 5/12 | 2/4 | 41.34% | -0.221 | [-50.91%, +31.60%] | [-0.936, +1.086] |

Neither market approached the required 7/12 profitable folds. Both residual Sharpes were negative and every dependence-aware lower confidence bound was below zero.

## Failure mechanism

### BTC — stale-release attribution rejected the main return engines

The candidate accepted only 7 of 22 OOS onsets and skipped 15. It omitted 10,321 benchmark hours carrying **+95.11% arithmetic market return**. Lower turnover saved 1.55% in fees, leaving a candidate-minus-B1 arithmetic delta of **-93.56%**.

Two skipped regimes contained most of the lost opportunity:

- the 23 October 2023 onset lasted 5,376 hours and compounded **+125.17%**;
- the 28 October 2024 onset lasted 2,760 hours and compounded **+42.73%**.

Skipped BTC onsets had a mean next-168H return of +0.89%, above the accepted set's +0.41%. The lag-leg comparison therefore did not identify low-quality onsets. It disproportionately removed the benchmark's longest and most profitable persistence episodes.

### ETH — useful risk concentration, insufficient return breadth

The candidate accepted 5 of 15 OOS onsets and skipped 10. It omitted 7,344 benchmark hours carrying **+23.87% arithmetic market return** while saving 1.00% in fees, for an arithmetic delta of **-22.87%**.

One accepted 5,112-hour regime compounded +106.37%, producing the candidate's favourable aggregate risk-adjusted result. That concentration did not generalise: only three folds and two calendar years were profitable, and the benchmark-residual Sharpe remained negative.

### Repaired diagnostics

The first implementation attempted to write a final next-open position beyond the available return boundary. This failed before any performance output and was repaired by enforcing the exact `t+1 < n-1` execution boundary.

After performance inspection, event attribution was also repaired to distinguish onsets beginning inside a scored span from inherited skipped regimes already active at its boundary. BTC OOS began inside one skipped regime, accounting for 49 inherited B1-only hours; event-started skipped regimes accounted for the remaining 10,272 hours. ETH had no inherited omission. The repair changed no position, fee, return, bootstrap result, gate or verdict.

Two complete executions then produced byte-identical evidence.

## Non-selectable attribution shadow

A diagnostic shadow accepted an onset whenever `current_leg > 0`, ignoring the lag-leg stale-release comparison. It was not a preregistered candidate and cannot be promoted.

| Market | Shadow OOS net | Sharpe | Max DD | Turnover | Difference hours vs candidate |
|---|---:|---:|---:|---:|---:|
| BTC | +166.48% | 1.156 | -26.55% | 30 | 9,672H |
| ETH | +87.20% | 0.699 | -44.90% | 26 | 7,272H |

The shadow demonstrates that the rejected component was specifically the magnitude comparison against stale lag-leg release. On BTC it suppressed nearly all profitable trend participation. On ETH it improved drawdown and efficiency but still concentrated returns in a small number of regimes. This is explanatory only; no price-only rescue is authorised on the consumed interval.

## Verdict

```text
reject_exact_trend_onset_margin_source_attribution_selector_family
```

The architecture failed bilateral OOS return, fold/year breadth, residual-Sharpe and dependence-aware uncertainty requirements. No same-interval change to the leg horizon, strict inequality, onset definition, whole-regime lockout, execution timing, fee or market-specific treatment is authorised.

There is no G1 nomination, paper promotion or live-trading authorisation.

## Remaining blocker and next experiment

**Remaining blocker:** binary onset rejection remains too destructive because the strongest 2,160H trend profits are generated by a few long-duration regimes whose initial crossing mechanics are weakly related to their eventual persistence. Current-leg versus lag-leg attribution improves capital protection in some samples but cannot reliably identify those long winners before entry.

**Next strategy experiment:** test one own-history-only **trend-state sign-entropy persistence overlay** that does not veto onsets. Enter every positive 2,160H trend immediately. At completed daily decisions, compute the fixed 720H first-order transition entropy of hourly return signs and compare it with the preceding non-overlapping 720H block. Permit a reversible 50% exposure state only when current entropy is higher, the latest 168H return is negative and the 2,160H trend remains positive; restore full exposure only when entropy falls and the latest 168H return is positive. Use one candidate, no fitted threshold, no grid and the unchanged bilateral efficiency, breadth and dependence-aware gates. Before activation, the ledger must confirm that no prior sign-entropy family consumed this exact architecture.
