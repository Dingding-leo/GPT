# Discounted payoff-sign evidence sizing result

```text
family          discounted-payoff-sign-evidence-sizing-1h-v1
candidate count 1
parameter grid  0
fee             exactly 5 bps one way
main            5a0fcc97d1a882f8223656c51f5bb8055f534e38
verdict         reject_discounted_payoff_sign_evidence_sizing_family
```

## Strategy

At each completed daily 2,160H trend exit, the candidate used only prior completed same-instrument hypothetical half-sleeve targets. Positive and non-positive target counts decayed by 0.5; signed evidence was `(positive-negative)/(positive+negative+2)` and exposure was `0.5*max(0,evidence)`. The sleeve ended on a daily base recross or exact 168H expiry. Execution was at the next hourly open.

## Data and sample

| Market | Rows | Fixed span | Candle SHA-256 | Raw-page SHA-256 |
|---|---:|---|---|---|
| ADA-USDT | 28081 | 2023-04-25T00:00:00+00:00 to 2026-07-08T00:00:00+00:00 | `b64529696fd537b72f594be216c575cb1e911377c001ddf036fde37c90923ed7` | `97ca98e95181806ec5e416ef35fe22c0d4246ab30f5a78d8d9176b811240aa11` |
| AVAX-USDT | 28081 | 2023-04-25T00:00:00+00:00 to 2026-07-08T00:00:00+00:00 | `c5cbacb62f38f8258477e33e2f733cd11356a63eb370084ead9e22127bd21495` | `8c2a59e5b79282fd6ffccd80fe91447f20c17dd3f71a1484326816ad3c388c42` |

Training `[2160,10800)`, development OOS `[10800,28080)`, and full scored `[2160,28080)` use completed-bar decisions, next-open execution, and `0.0005 × abs(exposure change)` fees.

## Training

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| ADA-USDT | candidate | +52.88% | 1.004 | -41.06% | 6.000 | +0.30% | 1028.45 bps |
| ADA-USDT | B0 | +31.84% | 0.766 | -50.14% | 54.000 | +2.70% | 84.96 bps |
| ADA-USDT | B1 | +52.88% | 1.004 | -41.06% | 6.000 | +0.30% | 1028.45 bps |
| AVAX-USDT | candidate | +94.46% | 1.220 | -60.82% | 11.467 | +0.57% | 886.84 bps |
| AVAX-USDT | B0 | +103.29% | 1.281 | -58.63% | 50.000 | +2.50% | 209.53 bps |
| AVAX-USDT | B1 | +96.24% | 1.231 | -60.46% | 12.000 | +0.60% | 854.77 bps |

## Development OOS

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| ADA-USDT | candidate | +61.34% | 0.702 | -56.12% | 29.422 | +1.47% | 298.91 bps |
| ADA-USDT | B0 | +36.30% | 0.567 | -60.19% | 128.000 | +6.40% | 55.31 bps |
| ADA-USDT | B1 | +62.44% | 0.707 | -56.45% | 30.000 | +1.50% | 295.18 bps |
| AVAX-USDT | candidate | -49.14% | -0.292 | -73.59% | 41.962 | +2.10% | -80.17 bps |
| AVAX-USDT | B0 | -55.24% | -0.409 | -74.24% | 168.000 | +8.40% | -27.91 bps |
| AVAX-USDT | B1 | -50.50% | -0.316 | -74.29% | 44.000 | +2.20% | -82.80 bps |

## Full scored

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| ADA-USDT | candidate | +146.66% | 0.801 | -56.12% | 35.422 | +1.77% | 422.48 bps |
| ADA-USDT | B0 | +79.70% | 0.631 | -60.19% | 182.000 | +9.10% | 64.11 bps |
| ADA-USDT | B1 | +148.33% | 0.805 | -56.45% | 36.000 | +1.80% | 417.39 bps |
| AVAX-USDT | candidate | -1.10% | 0.337 | -80.66% | 53.429 | +2.67% | 127.37 bps |
| AVAX-USDT | B0 | -9.00% | 0.290 | -81.37% | 218.000 | +10.90% | 26.55 bps |
| AVAX-USDT | B1 | -2.85% | 0.328 | -81.00% | 56.000 | +2.80% | 118.11 bps |

## Breadth and uncertainty

| Market | Profitable folds | Profitable years | Concentration | Residual Sharpe | Mean delta 95% | Sharpe delta 95% |
|---|---:|---:|---:|---:|---:|---:|
| ADA-USDT | 3/8 | 1/3 | 98.32% | -0.117 | [-3.04%, +2.38%] | [-0.051, +0.037] |
| AVAX-USDT | 1/8 | 1/3 | 100.00% | +0.463 | [-2.32%, +5.46%] | [-0.040, +0.094] |

```text
Common median annualised mean delta  +0.55% [-2.30%, +3.44%]
Common median Sharpe delta           +0.010 [-0.039, +0.055]
Markets passing every gate           0/2
```

## Failure mechanism / diagnostic

### ADA-USDT

```text
OOS episodes                         15
Nonzero / zero sleeves               8 / 7
Restorations / expiries              9 / 6
Mean nonzero / maximum exposure      0.0995 / 0.2003
Exposure-weighted episode target     -0.61%
Gross timing contribution            -0.64%
Fee saving versus B1                 +0.03%
Arithmetic candidate-minus-B1        -0.61%
```

### AVAX-USDT

```text
OOS episodes                         22
Nonzero / zero sleeves               11 / 11
Restorations / expiries              16 / 6
Mean nonzero / maximum exposure      0.1310 / 0.2444
Exposure-weighted episode target     +2.79%
Gross timing contribution            +2.69%
Fee saving versus B1                 +0.10%
Arithmetic candidate-minus-B1        +2.79%
```

The terminal diagnostic separately reports hypothetical fixed-half episode payoff and exposure-weighted payoff. This prevents a favourable unweighted episode sign balance from being mistaken for candidate economics when the soft state assigns different sleeve sizes. The decomposition identity is enforced to `1e-12`.

## Verdict

```text
reject_discounted_payoff_sign_evidence_sizing_family
```

Both markets pass every preregistered gate: `False`. No parameter change, market substitution, paper promotion, or live-trading authorisation follows from this result.
