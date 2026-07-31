# Reference-uplift exit bridge rejected

```text
Family          reference-uplift-exit-bridge-1h-v1
Candidate count 1
Parameter grid  0
Fee             exactly 5 bps one way
Markets         BCH-USDT and LINK-USDT independently
Verdict         reject_reference_uplift_exit_bridge_family
```

## Strategy change

At the first completed daily 00:00 UTC transition from a positive to a non-positive 2,160H endpoint trend, the candidate decomposed the margin crossing into the instrument’s latest 24H current-close change and the simultaneous 24H change in the lagged reference close. It retained 0.5 exposure only when the current close was non-declining while the lagged reference was rising. A selected bridge ended at the first positive daily recross at or before 168H or at exact expiry. All decisions executed at the next hourly open.

## Immutable data and sample

| Item | Frozen specification |
|---|---|
| Provider | Public confirmed OKX SPOT |
| Markets | BCH-USDT and LINK-USDT independently |
| Source workflow | `30605099932` |
| Evidence artifact | `8783389248` |
| Artifact SHA-256 | `f606d4da3234e25bcf799d48404b68ebba8839ade69d9ce494c8d7740e69255d` |
| Rows | 43,996 contiguous confirmed 1H rows per market |
| Source span | 24 July 2021–31 July 2026 03:00 UTC |
| Frozen prefix | First 43,441 rows through 8 July 2026 00:00 UTC |
| Training | `[2,880,17,520)` |
| Development OOS | `[17,520,43,440)` |
| Full scored | `[2,880,43,440)` |
| Breadth | 12 contiguous 2,160H folds and four calendar years |
| Uncertainty | 5,000 paired non-circular 168H blocks, seed `20260731` |

## Training

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BCH | Candidate | +17.85% | +0.440 | -39.84% | 23.00 | 1.15% | 151.49 bps |
| BCH | Daily B1 | +17.85% | +0.440 | -39.84% | 23.00 | 1.15% | 151.49 bps |
| BCH | Hourly B0 | +16.33% | +0.424 | -43.50% | 95.00 | 4.75% | 35.64 bps |
| LINK | Candidate | -70.83% | -1.481 | -71.62% | 52.00 | 2.60% | -206.52 bps |
| LINK | Daily B1 | -73.72% | -1.649 | -74.43% | 55.00 | 2.75% | -214.89 bps |
| LINK | Hourly B0 | -74.95% | -1.790 | -75.66% | 250.00 | 12.50% | -49.61 bps |

## Development OOS

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BCH | Candidate | -26.48% | +0.150 | -63.02% | 49.00 | 2.45% | 57.13 bps |
| BCH | Daily B1 | -25.01% | +0.159 | -62.52% | 53.00 | 2.65% | 55.70 bps |
| BCH | Hourly B0 | -47.20% | -0.031 | -71.23% | 285.00 | 14.25% | -2.03 bps |
| LINK | Candidate | +34.43% | +0.485 | -61.62% | 32.00 | 1.60% | 300.71 bps |
| LINK | Daily B1 | +20.65% | +0.431 | -61.62% | 33.00 | 1.65% | 258.57 bps |
| LINK | Hourly B0 | +90.79% | +0.662 | -52.93% | 129.00 | 6.45% | 100.53 bps |

## Full scored sample

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BCH | Candidate | -13.36% | +0.234 | -63.02% | 72.00 | 3.60% | 87.28 bps |
| BCH | Daily B1 | -11.62% | +0.241 | -62.52% | 76.00 | 3.80% | 84.69 bps |
| BCH | Hourly B0 | -38.57% | +0.105 | -71.23% | 380.00 | 19.00% | 7.39 bps |
| LINK | Candidate | -60.79% | -0.040 | -80.00% | 84.00 | 4.20% | -13.29 bps |
| LINK | Daily B1 | -68.29% | -0.119 | -81.98% | 88.00 | 4.40% | -37.34 bps |
| LINK | Hourly B0 | -52.20% | +0.021 | -82.41% | 379.00 | 18.95% | 1.49 bps |

## Breadth and uncertainty

| Market | Profitable folds | Improved folds | Profitable years | Concentration | Residual Sharpe | Mean Δ 95% | Sharpe Δ 95% |
|---|---:|---:|---:|---:|---:|---:|---:|
| BCH | 4/12 | 2/12 | 1/4 | 61.92% | -0.093 | [-4.91%, +4.59%] | [-0.078, +0.074] |
| LINK | 3/12 | 2/12 | 2/4 | 47.41% | +1.542 | [-0.00%, +11.58%] | [-0.000, +0.178] |

Common-index inference:

```text
Median annualised mean-return delta  +1.58%
95% CI                              [-1.81%, +6.27%]
Median Sharpe delta                  +0.023
95% CI                              [-0.028, +0.093]
Markets passing all gates           0/2
```

## Failure mechanism and diagnostic repair

**BCH:** six OOS exits were selected. Their exact arithmetic contribution was `−1.5275%`; only 2/6 selected episodes were positive, while 13/21 rejected episodes were positive and the rejected target sum was `+13.6455%`. The selector therefore inverted the useful exit-payoff ordering on BCH. Candidate OOS turnover fell from 53 to 49, but return declined by 1.47 percentage points, Sharpe fell by 0.009, and drawdown worsened by 0.51 points.

**LINK:** only one of 17 completed OOS exits qualified. The 19 October 2023 bridge contributed `+10.9000%` arithmetically and generated the entire `+10.9000%` candidate-minus-B1 OOS residual. This was useful timing but maximally sparse: one event produced all strategy differentiation, only 3/12 folds were profitable, and both per-market confidence lower bounds remained non-positive.

The initial machine report exposed aggregate selected/rejected totals but not the event-level concentration that determines robustness. The repaired terminal diagnostic identifies the selected timestamps, target signs, and exact contribution concentration. No signal, exposure, return, fee, bootstrap draw, metric, gate, or verdict changed. A local rerun from the downloaded CSVs and acquisition record produced a byte-identical `result.json`.

## Verdict

```text
reject_reference_uplift_exit_bridge_family
```

BCH failed absolute and benchmark-relative OOS return, Sharpe, drawdown, fold/year breadth, concentration, residual Sharpe, both uncertainty gates, and full-positive return. LINK improved OOS point estimates and turnover but failed fold/year breadth, both uncertainty gates, and full-positive return. No same-cohort threshold, bridge size, horizon, lookback, cadence, fee, or market-specific rescue is authorised.

**Remaining blocker:** the crossing-cause decomposition is not a stable selector. On BCH it selected the worse payoff subset; on LINK its apparent edge came from one isolated rebound and did not repair the weak full-sample base architecture.

**Next strategy experiment:** stop adding post-exit sleeves to the unconditional 2,160H base. On a new predeclared cohort, test one own-history-only entry-side trend-quality gate that requires positive long-horizon trend plus broad agreement across fixed nested temporal horizons, while preserving daily cadence and using a single hysteretic state to reduce rather than add turnover.
