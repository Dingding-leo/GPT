# Payoff-aligned expanding exit selector replication

```text
Family          payoff-aligned-expanding-exit-selector-replication-1h-v1
Candidate count 1
Parameter grid  0
Issue           #742
Fee             exactly 5 bps one way
Result SHA-256 cb806298a84aa5bdc6d4dfbc6c1dc34c3c2f9d41bcdfcf91f9eb90f1746da550
Verdict         reject_cross_market_transportability_of_payoff_aligned_expanding_exit_selector
```

## Strategy change

At every positive-to-non-positive completed daily 2,160H endpoint-trend exit, the candidate estimated the exact hypothetical net arithmetic contribution of retaining a 0.5 sleeve until the first daily base recross or a fixed 168H expiry. The expanding ridge model used only that instrument's prior completed exit episodes and the frozen exit features: endpoint-margin depth, latest 24H return, and hourly negative-state age. A sleeve was selected only when predicted contribution was strictly positive.

The continuous target included half of realised open-to-open market carry during the hypothetical sleeve plus the exact 5 bps round-trip fee saving when a recross occurred. All historical hypothetical outcomes entered the training set after completion, regardless of the live selector decision. There was no cross-market pooling, fitted threshold, grid, leverage, shorting, or market-specific rule.

## Immutable data and sample

| Item | Frozen specification |
|---|---|
| Provider | Public confirmed OKX SPOT |
| Markets | SOL-USDT, XRP-USDT, LTC-USDT, DOGE-USDT independently |
| Artifact | Workflow 30364475418; artifact 8691110722 |
| Artifact SHA-256 | `d9d686f4abd2c740044079b287802ef3e8c4f032c316035a95a2bb40ae2b7822` |
| Rows | 28,081 contiguous confirmed 1H bars per market |
| Source span | 25 April 2023 through 8 July 2026 UTC |
| Descriptive training | `[2160,10800)`; four 2,160H folds |
| Development OOS | `[10800,28080)`; eight 2,160H folds |
| Full scored | `[2160,28080)`; twelve 2,160H folds |
| Execution | Completed decision to next hourly open |
| Fees | `0.0005 × absolute exposure change` |
| Uncertainty | 5,000 paired non-circular 168H moving blocks; seed 20260731 |

## Descriptive training

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| SOL-USDT | CANDIDATE | +392.62% | 2.209 | -42.32% | 15.0 | 0.75% | 1344.21 bps |
| SOL-USDT | B1 | +377.52% | 2.180 | -42.32% | 17.0 | 0.85% | 1165.91 bps |
| SOL-USDT | B0 | +387.98% | 2.204 | -42.32% | 41.0 | 2.05% | 488.72 bps |
| XRP-USDT | CANDIDATE | -50.45% | -1.099 | -63.43% | 26.0 | 1.30% | -217.64 bps |
| XRP-USDT | B1 | -55.21% | -1.371 | -66.54% | 33.0 | 1.65% | -205.32 bps |
| XRP-USDT | B0 | -48.08% | -1.029 | -60.86% | 157.0 | 7.85% | -33.33 bps |
| LTC-USDT | CANDIDATE | -18.68% | -0.125 | -34.59% | 18.0 | 0.90% | -36.43 bps |
| LTC-USDT | B1 | -7.03% | 0.123 | -34.59% | 20.0 | 1.00% | 32.01 bps |
| LTC-USDT | B0 | -22.75% | -0.236 | -34.59% | 112.0 | 5.60% | -10.91 bps |
| DOGE-USDT | CANDIDATE | +52.28% | 0.927 | -46.75% | 14.0 | 0.70% | 541.29 bps |
| DOGE-USDT | B1 | +76.28% | 1.108 | -46.75% | 16.0 | 0.80% | 562.60 bps |
| DOGE-USDT | B0 | +32.09% | 0.753 | -46.75% | 84.0 | 4.20% | 73.38 bps |

## Development OOS

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| SOL-USDT | CANDIDATE | -35.14% | -0.112 | -57.31% | 25.5 | 1.28% | -48.64 bps |
| SOL-USDT | B1 | -43.03% | -0.244 | -58.40% | 37.0 | 1.85% | -71.51 bps |
| SOL-USDT | B0 | -36.33% | -0.139 | -54.97% | 159.0 | 7.95% | -9.52 bps |
| XRP-USDT | CANDIDATE | +77.53% | 0.767 | -64.55% | 24.0 | 1.20% | 433.65 bps |
| XRP-USDT | B1 | +63.69% | 0.708 | -63.83% | 29.0 | 1.45% | 324.25 bps |
| XRP-USDT | B0 | +85.83% | 0.802 | -67.16% | 167.0 | 8.35% | 63.91 bps |
| LTC-USDT | CANDIDATE | +56.22% | 0.680 | -39.52% | 19.0 | 0.95% | 418.73 bps |
| LTC-USDT | B1 | +56.98% | 0.684 | -39.52% | 20.0 | 1.00% | 399.41 bps |
| LTC-USDT | B0 | +33.78% | 0.547 | -39.52% | 132.0 | 6.60% | 48.29 bps |
| DOGE-USDT | CANDIDATE | -3.58% | 0.306 | -72.71% | 33.0 | 1.65% | 121.96 bps |
| DOGE-USDT | B1 | -3.18% | 0.307 | -71.78% | 34.0 | 1.70% | 117.90 bps |
| DOGE-USDT | B0 | -8.67% | 0.259 | -67.55% | 166.0 | 8.30% | 20.16 bps |

## Full scored

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| SOL-USDT | CANDIDATE | +219.51% | 0.910 | -57.31% | 40.5 | 2.02% | 467.23 bps |
| SOL-USDT | B1 | +172.03% | 0.834 | -58.40% | 54.0 | 2.70% | 318.04 bps |
| SOL-USDT | B0 | +210.69% | 0.898 | -54.97% | 200.0 | 10.00% | 92.62 bps |
| XRP-USDT | CANDIDATE | -12.03% | 0.252 | -64.55% | 50.0 | 2.50% | 94.98 bps |
| XRP-USDT | B1 | -26.68% | 0.143 | -69.17% | 62.0 | 3.10% | 42.38 bps |
| XRP-USDT | B0 | -3.52% | 0.294 | -67.16% | 324.0 | 16.20% | 16.79 bps |
| LTC-USDT | CANDIDATE | +27.03% | 0.430 | -39.52% | 37.0 | 1.85% | 197.30 bps |
| LTC-USDT | B1 | +45.95% | 0.511 | -39.52% | 40.0 | 2.00% | 215.71 bps |
| LTC-USDT | B0 | +3.35% | 0.306 | -41.80% | 244.0 | 12.20% | 21.11 bps |
| DOGE-USDT | CANDIDATE | +46.82% | 0.541 | -72.71% | 47.0 | 2.35% | 246.87 bps |
| DOGE-USDT | B1 | +70.67% | 0.611 | -71.78% | 50.0 | 2.50% | 260.21 bps |
| DOGE-USDT | B0 | +20.63% | 0.447 | -67.55% | 250.0 | 12.50% | 38.04 bps |

## Breadth and uncertainty

| Market | Profitable folds | Improved folds | Profitable years | Concentration | Residual Sharpe | Mean delta 95% | Sharpe delta 95% |
|---|---:|---:|---:|---:|---:|---:|---:|
| SOL-USDT | 3/8 | 5/8 | 0/3 | 45.37% | +0.680 | [-9.17%, +22.41%] | [-0.164, +0.413] |
| XRP-USDT | 2/8 | 3/8 | 1/3 | 96.66% | +0.364 | [-7.29%, +19.33%] | [-0.127, +0.286] |
| LTC-USDT | 5/8 | 1/8 | 2/3 | 46.98% | -0.040 | [-4.22%, +3.61%] | [-0.073, +0.060] |
| DOGE-USDT | 1/8 | 2/8 | 1/3 | 100.00% | +0.011 | [-7.62%, +7.17%] | [-0.118, +0.107] |

Every market had a negative lower confidence bound for both benchmark-relative mean return and Sharpe. No market passed all frozen gates.

## Failure mechanism and non-selectable intercept shadow

The fixed exit features did not improve payoff prediction. In every market, the feature model's expanding out-of-episode mean-squared error exceeded the intercept-only expanding payoff prior. The intercept shadow is diagnostic only and was not eligible for selection or promotion.

| Market | Feature MSE | Intercept MSE | Decisions changed | Candidate OOS | Intercept shadow OOS | Candidate minus shadow arithmetic |
|---|---:|---:|---:|---:|---:|---:|
| SOL-USDT | 0.001569 | 0.001424 | 2/19 | -35.14% | -33.66% | -2.83% |
| XRP-USDT | 0.002978 | 0.002328 | 2/15 | +77.53% | +115.12% | -19.74% |
| LTC-USDT | 0.002188 | 0.001576 | 2/10 | +56.22% | +56.98% | -0.32% |
| DOGE-USDT | 0.001838 | 0.001252 | 6/17 | -3.58% | +1.25% | -5.05% |

### SOL-USDT

The candidate selected 17 of 19 OOS exits and added 635.5 full-equivalent hours. Timing plus fee savings improved arithmetic return by +14.06% versus B1, but OOS compounded return remained -35.14%, with only 3/8 profitable folds and 0/3 profitable years.
The two feature-driven rejections omitted hypothetical sleeve targets totalling +2.83%. Consequently the feature model underperformed the intercept shadow by -2.83%.

### XRP-USDT

The candidate improved B1 OOS return from +63.69% to +77.53%, reduced turnover from 29.0 to 24.0, and raised edge per turnover. It nevertheless worsened drawdown, produced only 2/8 profitable folds and 1/3 profitable years, and remained negative over the full scored sample.
The full feature model rejected two exits whose realised hypothetical net sleeve contributions totalled +19.74%. The intercept shadow selected all exits and reached +115.12% OOS with Sharpe 0.907; feature selection cost -19.74% arithmetic return.

### LTC-USDT

The intercept payoff prior selected no OOS sleeves and therefore reproduced B1. The feature model overrode it twice; those selected targets summed to -0.32%. Candidate return and Sharpe were slightly below B1, residual Sharpe was negative, and both uncertainty intervals crossed zero.

### DOGE-USDT

The candidate selected four of 17 exits and ended OOS at -3.58%, slightly below an already negative B1. Rejected hypothetical sleeve targets totalled +17.44%. The intercept shadow selected six exits, remained positive at +1.25%, and exceeded the feature candidate by +5.05% arithmetic return.

## Diagnostic repair and reproducibility

The first terminal diagnostic asserted causal prior availability with a tautological filtered condition. The repaired reproducer persists the exact prior episode exit decisions and terminal executions used at every prediction, reconstructs the expected expanding set independently, and verifies that every terminal execution is strictly earlier than the current exit decision. A non-selectable intercept-only shadow was also added to isolate whether the continuous target or the exit features caused failure. No candidate prediction, sleeve decision, exposure, return, fee, bootstrap draw, gate, or verdict changed.

Two complete terminal executions produced byte-identical protocol, result, report, and digest files.

## Cross-market verdict

```text
Markets passing all gates          0/4
Median annualised mean delta        +2.59%
Median mean-delta 95%               [-3.96%, +9.35%]
Median Sharpe delta                 +0.029
Median Sharpe-delta 95%             [-0.066, +0.144]
Verdict                             reject_cross_market_transportability_of_payoff_aligned_expanding_exit_selector
```

No same-cohort feature, target, ridge, threshold, sleeve, horizon, or market-specific rescue is authorised. There is no G1, paper, or live-trading nomination.

**Remaining blocker:** episode-level payoff is more economically aligned than recross classification, but the three frozen exit features do not transportably explain which exits have positive sleeve carry. Their small-sample ridge increments systematically displaced a stronger instrument-local intercept prior and missed the largest positive XRP and DOGE episodes.

**Next strategy experiment:** freeze the non-feature expanding payoff-prior selector on the untouched CFX-USDT and FIL-USDT full-data cohort from the same immutable artifact, before inspecting their results. Use the identical hypothetical net half-sleeve target, the same neutral-prior ridge intercept prediction above zero, one fixed policy across both markets, no feature model, no grid, exactly 5 bps, and fresh bilateral breadth and common-block uncertainty gates. This tests the selector repair on independent instruments rather than rescuing the consumed four-market interval.
