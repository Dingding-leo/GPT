# Four-phase daily trend ensemble — cross-market replication

## Verdict

```text
reject_cross_market_transportability_of_four_phase_ensemble
```

One exact, preregistered cross-market replication of the consumed four-phase daily trend ensemble was completed. The rule was not changed from the BTC/ETH development experiment: fixed `00:00`, `06:00`, `12:00`, and `18:00 UTC` phase states, a 2,160H own-instrument endpoint trend in each phase, fractional exposure equal to the fraction of positive states, next-open execution, and exactly 5 bps one way.

```text
family_id             four-phase-daily-trend-ensemble-cross-market-replication-1h-v1
source_family         four-phase-daily-trend-ensemble-1h-v1
issue                  #717
candidate_count        1
parameter_grid_count   0
research_parent        5a0fcc97d1a882f8223656c51f5bb8055f534e38
markets passing gates  0/4
```

## Frozen rule

For each instrument independently, only the matching phase state updates at each completed phase candle:

```text
state_h(t) = 1 when close_t > close_(t-2160), otherwise 0
exposure   = (state_00 + state_06 + state_12 + state_18) / 4
           in {0, 0.25, 0.50, 0.75, 1.00}
```

The completed decision affects the next hourly open-to-open return. Fees equal `0.0005 × abs(change in exposure)`. B0 is the hourly 2,160H endpoint trend and B1 is the daily `00:00 UTC` version.

## Immutable public data and sample

| Item | Frozen specification |
|---|---|
| Provider | Public confirmed OKX SPOT |
| Markets | SOL-USDT, XRP-USDT, LTC-USDT, DOGE-USDT independently |
| Bar | Exactly 1H |
| Source artifact | Workflow `30364475418`, artifact `8691110722` |
| Artifact SHA-256 | `d9d686f4abd2c740044079b287802ef3e8c4f032c316035a95a2bb40ae2b7822` |
| Source rows | 28,081 per market |
| Source span | 25 April 2023 00:00 through 8 July 2026 00:00 UTC |
| Warm-up | `[0,2160)` |
| Replication / full scored | `[2160,28080)`; 25,920 returns |
| Breadth | 12 contiguous 2,160H folds and four calendar years |
| Uncertainty | 5,000 paired non-circular 168H blocks, seed `20260730` |
| State continuity | No fold or year resets |

Training metrics are not applicable: the exact rule was frozen on already consumed BTC/ETH development evidence and no replication-market fitting or selection occurred.

## Replication performance

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn | Mean exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| SOL | Candidate | +201.43% | 0.885 | -58.81% | 50.5 | +2.53% | 358.94 bps | 0.586 |
| SOL | B1 daily | +172.03% | 0.834 | -58.40% | 54.0 | +2.70% | 318.04 bps | 0.585 |
| SOL | B0 hourly | +210.69% | 0.898 | -54.97% | 200.0 | +10.00% | 92.62 bps | 0.587 |
| XRP | Candidate | -5.44% | 0.277 | -67.92% | 68.0 | +3.40% | 74.25 bps | 0.489 |
| XRP | B1 daily | -26.68% | 0.143 | -69.17% | 62.0 | +3.10% | 42.38 bps | 0.483 |
| XRP | B0 hourly | -3.52% | 0.294 | -67.16% | 324.0 | +16.20% | 16.79 bps | 0.489 |
| LTC | Candidate | +45.46% | 0.509 | -39.52% | 40.5 | +2.03% | 211.29 bps | 0.409 |
| LTC | B1 daily | +45.95% | 0.511 | -39.52% | 40.0 | +2.00% | 215.71 bps | 0.412 |
| LTC | B0 hourly | +3.35% | 0.306 | -41.80% | 244.0 | +12.20% | 21.11 bps | 0.409 |
| DOGE | Candidate | +57.80% | 0.573 | -70.09% | 54.5 | +2.73% | 222.49 bps | 0.450 |
| DOGE | B1 daily | +70.67% | 0.611 | -71.78% | 50.0 | +2.50% | 260.21 bps | 0.456 |
| DOGE | B0 hourly | +20.63% | 0.447 | -67.55% | 250.0 | +12.50% | 38.04 bps | 0.450 |

The replication and full-scored spans are identical. All four candidate paths beat the high-turnover hourly B0 on edge per turnover. Relative to the relevant daily B1 benchmark, only SOL and XRP improved aggregate return and Sharpe; XRP nevertheless remained loss-making, LTC was slightly worse, and DOGE deteriorated materially.

## Breadth and uncertainty

| Market | Profitable folds | Profitable years | Positive-fold concentration | Residual Sharpe | Mean delta 95% | Sharpe delta 95% |
|---|---:|---:|---:|---:|---:|---:|
| SOL-USDT | 6/12 | 2/4 | 74.64% | 0.436 | [-4.29%, +9.61%] | [-0.060, +0.143] |
| XRP-USDT | 4/12 | 1/4 | 92.10% | 0.735 | [-6.41%, +23.75%] | [-0.102, +0.384] |
| LTC-USDT | 7/12 | 2/4 | 42.29% | -0.047 | [-5.31%, +3.18%] | [-0.095, +0.055] |
| DOGE-USDT | 2/12 | 1/4 | 62.86% | -0.334 | [-13.14%, +5.88%] | [-0.182, +0.089] |

Cross-market common-index block inference:

```text
Median annualised mean-return delta  point +1.49%
                                      95% [-3.53%, +4.98%]
Median Sharpe delta                  point +0.024
                                      95% [-0.053, +0.076]
```

No market passed every original gate. All four failed both strict uncertainty lower-bound gates. No market reached three profitable calendar years; only LTC reached seven profitable folds, while SOL, XRP and DOGE failed positive-fold concentration.

## Failure mechanism

### SOL-USDT

```text
Candidate net / B1 net              +201.43% / +172.03%
Candidate Sharpe / B1 Sharpe        0.885 / 0.834
Candidate turnover / B1 turnover    50.5 / 54.0
Arithmetic candidate-minus-B1       +9.52%
Exposure-timing contribution         +9.35%
Incremental fees                     -0.18%
Fractional-state hours               1320 (5.09%)
```

When the ensemble held **more** exposure than B1, it contributed +10.97% over 279.0 full-equivalent hours. When it held **less**, the signed contribution was -1.62% over 267.0 full-equivalent hours.

SOL produced the strongest positive point estimate: the ensemble added exposure during profitable phase-leading intervals and saved turnover. The gain was not broad—only 6/12 folds and 2/4 years were profitable, 74.64% of positive-fold return came from one fold, drawdown was slightly worse, and both confidence lower bounds were negative.

### XRP-USDT

```text
Candidate net / B1 net              -5.44% / -26.68%
Candidate Sharpe / B1 Sharpe        0.277 / 0.143
Candidate turnover / B1 turnover    68.0 / 62.0
Arithmetic candidate-minus-B1       +24.22%
Exposure-timing contribution         +24.52%
Incremental fees                     +0.30%
Fractional-state hours               1788 (6.90%)
```

When the ensemble held **more** exposure than B1, it contributed +15.88% over 432.0 full-equivalent hours. When it held **less**, the signed contribution was +8.63% over 288.0 full-equivalent hours.

XRP showed useful timing separation, including extra exposure during positive returns and reduced exposure during negative returns. The improvement was insufficient because both candidate and B1 lost money; only 4/12 folds and 1/4 years were profitable, and 92.10% of positive-fold return came from one fold.

### LTC-USDT

```text
Candidate net / B1 net              +45.46% / +45.95%
Candidate Sharpe / B1 Sharpe        0.509 / 0.511
Candidate turnover / B1 turnover    40.5 / 40.0
Arithmetic candidate-minus-B1       -0.71%
Exposure-timing contribution         -0.68%
Incremental fees                     +0.03%
Fractional-state hours               1068 (4.12%)
```

When the ensemble held **more** exposure than B1, it contributed -0.29% over 180.0 full-equivalent hours. When it held **less**, the signed contribution was -0.39% over 258.0 full-equivalent hours.

LTC was economically almost identical to B1. Fractional phase disagreements added a small negative timing contribution and slightly more turnover. The candidate reached 7/12 profitable folds but only 2/4 profitable years, with negative residual Sharpe and unsupported uncertainty.

### DOGE-USDT

```text
Candidate net / B1 net              +57.80% / +70.67%
Candidate Sharpe / B1 Sharpe        0.573 / 0.611
Candidate turnover / B1 turnover    54.5 / 50.0
Arithmetic candidate-minus-B1       -8.85%
Exposure-timing contribution         -8.62%
Incremental fees                     +0.23%
Fractional-state hours               1506 (5.81%)
```

When the ensemble held **more** exposure than B1, it contributed -17.40% over 240.0 full-equivalent hours. When it held **less**, the signed contribution was +8.78% over 372.0 full-equivalent hours.

DOGE exposed the transportability failure most clearly. Extra phase exposure occurred during negative carry and cost 17.40 arithmetic percentage points, while reduced exposure avoided only 8.78 points. The candidate therefore lost return, Sharpe and efficiency while increasing turnover.

## Diagnostic repair and reproducibility

The initial diagnostic pooled all fractional disagreements even though `candidate > B1` and `candidate < B1` have opposite economic meanings. The terminal reproducer separates those states, reports full-equivalent hours and exposure-weighted return contribution for each, and retains event concentration. No phase state, target, fee, return, benchmark metric, breadth result, bootstrap draw, gate or verdict changed.

Two complete terminal executions reproduced byte-identically:

```text
result.json SHA-256   c5daaebc92a158191617d7c348195fda51467678651ebeba7e14c3d9de2f76a1
protocol.json SHA-256 28717bb409387ce8fd634c422fb429f1a2d5f40fc124bdf003e33621483178f6
```

Validated identities include source hashes, exact contiguous confirmed chronology, allowed exposure states, independent four-phase reconstruction, next-open timing, fee accounting, turnover attribution and candidate-minus-B1 return decomposition.

## Rejection

```text
reject_cross_market_transportability_of_four_phase_ensemble
```

The four-phase temporal ensemble does not transport robustly. It generated favourable aggregate timing in SOL and XRP but not LTC or DOGE, and none of the four markets passed the original full gate. The cross-market median point deltas were positive but dependence-aware intervals crossed zero.

No phase-hour, phase-count, trend-horizon, exposure-map, cadence, fee, market subset or market-specific rescue is authorised on this consumed cohort. The result cannot overturn the BTC/ETH rejection and creates no G1, paper or live nomination.

**Remaining blocker:** intraday phase smoothing is a weak, crossing-local perturbation rather than an independent return state. Its sign varies by instrument and its gains remain concentrated in a few folds.

**Next strategy experiment:** activate the already-frozen archive-backed own-instrument trade-flow resilience architecture after a de-duplication and checkpoint audit. Main now contains the causal source-ordering and equal-millisecond chronology proofs; the next strategy-facing run should acquire the frozen BTC/ETH archive window and execute the fixed signed-flow comparator versus flow-response-residual policy exactly once, without threshold or model search.
