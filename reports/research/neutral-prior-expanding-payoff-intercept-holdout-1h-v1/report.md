# Neutral-prior expanding payoff intercept holdout — terminal report

```text
Family          neutral-prior-expanding-payoff-intercept-holdout-1h-v1
Candidate count 1
Parameter grid  0
Issue           #745
Fee             exactly 5 bps one way
Result SHA-256 f496324c5a070d4ba0a6618923add5409ee6a756bbc2e9371ca7d7cc23c40a15
Verdict         reject_holdout_transportability_of_neutral_prior_expanding_payoff_intercept
```

## Strategy change

At each positive-to-non-positive completed daily 2,160H endpoint-trend exit, the candidate used only that instrument’s prior completed exit episodes. Each prior episode supplied the exact hypothetical net arithmetic payoff of retaining a 0.5 sleeve until daily trend recross or exact 168H expiry. The fixed expanding prediction was:

```text
prediction = sum(prior completed episode targets) / (episode_count + 2)
select sleeve only when prediction > 0
```

The denominator includes one fixed zero-payoff observation and a fixed ridge penalty of one on the intercept. No exit features, cross-market pooling, fitted threshold, grid, market-specific treatment, entry veto, leverage, shorting, or exogenous data were used. Decisions executed at the next hourly open.

## Immutable data and sample

| Item | Frozen specification |
|---|---|
| Provider | Public confirmed OKX SPOT |
| Markets | CFX-USDT and FIL-USDT independently |
| Artifact | Workflow 30364475418; artifact 8691110722 |
| Artifact SHA-256 | `d9d686f4abd2c740044079b287802ef3e8c4f032c316035a95a2bb40ae2b7822` |
| Rows | 28,081 contiguous confirmed 1H bars per market |
| Span | 25 April 2023 through 8 July 2026 UTC |
| Training | `[2160,10800)`; four 2,160H folds |
| Development OOS | `[10800,28080)`; eight 2,160H folds |
| Full scored | `[2160,28080)`; twelve 2,160H folds |
| Fees | `0.0005 × absolute exposure change` |
| Uncertainty | 5,000 paired non-circular 168H blocks; seed 20260731 |

## Descriptive training

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| CFX-USDT | CANDIDATE | +34.69% | 0.779 | -62.50% | 8.0 | +0.40% | 827.57 bps |
| CFX-USDT | B1 | +34.69% | 0.779 | -62.50% | 8.0 | +0.40% | 827.57 bps |
| CFX-USDT | B0 | +13.18% | 0.575 | -62.50% | 42.0 | +2.10% | 116.32 bps |
| FIL-USDT | CANDIDATE | +25.52% | 0.689 | -58.51% | 4.0 | +0.20% | 1349.41 bps |
| FIL-USDT | B1 | +16.29% | 0.591 | -58.53% | 4.0 | +0.20% | 1154.42 bps |
| FIL-USDT | B0 | -3.13% | 0.353 | -62.68% | 44.0 | +2.20% | 61.96 bps |

## Development OOS

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| CFX-USDT | CANDIDATE | -48.56% | -0.044 | -72.10% | 26.0 | +1.30% | -26.04 bps |
| CFX-USDT | B1 | -55.12% | -0.153 | -72.77% | 38.0 | +1.90% | -60.69 bps |
| CFX-USDT | B0 | -53.75% | -0.140 | -72.36% | 142.0 | +7.10% | -14.81 bps |
| FIL-USDT | CANDIDATE | -50.37% | -0.350 | -79.79% | 24.0 | +1.20% | -161.42 bps |
| FIL-USDT | B1 | -40.01% | -0.217 | -75.47% | 30.0 | +1.50% | -76.18 bps |
| FIL-USDT | B0 | -59.74% | -0.570 | -79.65% | 168.0 | +8.40% | -36.56 bps |

## Full scored sample

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| CFX-USDT | CANDIDATE | -30.71% | 0.248 | -81.51% | 34.0 | +1.70% | 174.81 bps |
| CFX-USDT | B1 | -39.55% | 0.183 | -82.77% | 46.0 | +2.30% | 93.79 bps |
| CFX-USDT | B0 | -47.65% | 0.118 | -84.01% | 184.0 | +9.20% | 15.12 bps |
| FIL-USDT | CANDIDATE | -37.71% | 0.079 | -79.79% | 28.0 | +1.40% | 54.41 bps |
| FIL-USDT | B1 | -30.24% | 0.125 | -76.09% | 34.0 | +1.70% | 68.60 bps |
| FIL-USDT | B0 | -61.00% | -0.182 | -84.90% | 212.0 | +10.60% | -16.11 bps |

## Breadth and uncertainty

| Market | Profitable folds | Improved folds | Profitable years | Concentration | Residual Sharpe | Mean Δ 95% | Sharpe Δ 95% |
|---|---:|---:|---:|---:|---:|---:|---:|
| CFX-USDT | 3/8 | 6/8 | 0/3 | 74.28% | +0.507 | [-7.08%, +24.56%] | [-0.090, +0.333] |
| FIL-USDT | 3/8 | 5/8 | 1/3 | 80.04% | -0.467 | [-26.82%, +7.56%] | [-0.442, +0.147] |

Common-block inference across the two independently evaluated markets:

```text
Median annualised mean-return delta  +0.10%  95% [-10.73%, +10.28%]
Median Sharpe delta                  -0.012  95% [-0.175, +0.150]
Markets passing all gates            0/2
```

## Failure mechanism

### CFX-USDT — positive sleeve payoff, but a losing base architecture

```text
OOS exits / selected / rejected      19 / 17 / 2
Selected restorations / expiries     12 / 5
Gross timing contribution            +15.69%
Fee saving versus B1                 +0.60%
Arithmetic candidate-minus-B1        +16.29%
```

The intercept state captured positive exit-sleeve carry and cut turnover from 38.0 to 26.0. It improved OOS compounded return from -55.12% to -48.56%, but both policies lost money. Only 3/8 folds were profitable, no OOS calendar year was profitable, positive-fold concentration was 74.28%, and both dependence-aware lower bounds remained negative. Full-sample compounded return was also negative at -30.71%.

### FIL-USDT — expanding positive prior persisted after payoff reversal

```text
OOS exits / selected / rejected      15 / 11 / 4
Selected restorations / expiries     6 / 5
Gross timing contribution            -16.19%
Fee saving versus B1                 +0.30%
Arithmetic candidate-minus-B1        -15.89%
```

Early completed FIL episodes made the intercept positive, so the candidate selected 11 of 15 OOS exits. Those selected episodes subsequently contributed -15.89% of arithmetic return relative to B1. Candidate OOS return fell from -40.01% to -50.37%, Sharpe declined, drawdown worsened, and edge per turnover fell from -76.18 to -161.42 bps. The prediction eventually turned negative and rejected the final four exits, but only after the adverse regime had already consumed the prior edge.

## Diagnostic repair and reproducibility

The first complete calculation used population standard deviation for performance Sharpe. Calibration against the exact non-selectable intercept-shadow metrics preserved in PR #744 exposed a small deterministic mismatch. The terminal reproducer uses the canonical sample standard deviation (`ddof=1`) for policy Sharpe, residual Sharpe, and bootstrap Sharpe differences. Positions, returns, fees, turnover, drawdown, episode decisions, arithmetic attribution, breadth counts, acceptance gates, and the rejection verdict were unchanged.

Two terminal executions produced byte-identical result files:

```text
d8ee109b375f33bde6e7ad81d1b0df76a8763c270858dc5726eaa80e0af257a9  result.json file SHA-256
f496324c5a070d4ba0a6618923add5409ee6a756bbc2e9371ca7d7cc23c40a15  canonical result-payload SHA-256
```

Source hashes, confirmed contiguous chronology, completed-bar next-open execution, exposure-domain, exact fee, episode-duration, strict prior-availability, target reconstruction, prefix bounding, and arithmetic decomposition identities passed. The frozen artifact ends at the scored return boundary; no later source suffix exists, so the reproducer enforces the exact 28,081-row input bound rather than claiming an unavailable empirical suffix perturbation.

## Verdict

```text
reject_holdout_transportability_of_neutral_prior_expanding_payoff_intercept
```

Neither market passed all gates. CFX showed positive exit-sleeve timing but remained negative across OOS and full samples and lacked breadth or uncertainty support. FIL directly falsified transportability: the expanding intercept was too slow to adapt when exit-sleeve payoff changed sign. No same-cohort prior, penalty, threshold, sleeve, horizon, or market-specific rescue is authorised. There is no G1, paper, or live-trading nomination.

**Remaining blocker:** an instrument-level payoff intercept is more robust than the rejected small-sample feature model, but it is an unconditional, slowly adapting state. It cannot distinguish whether a newly completed exit belongs to the prior payoff regime, and it can remain positive through a prolonged sign reversal.

**Next strategy experiment:** after rejected-family de-duplication, test one own-history-only regime-adaptive payoff prior that resets only on a causal change-point in completed episode payoffs. Use a fixed e-process or one-sided cumulative evidence rule with no tuned threshold, keep the same 168H half-sleeve target and next-open economics, and preregister it on a fresh immutable market cohort before inspection.
