# Sign-transition entropy persistence overlay — terminal report

## Objective

Test whether lower empirical return-sign transition entropy, combined with a negative 168H return, identifies persistent weak phases inside the unchanged daily 2,160H long/cash trend without vetoing any trend onset. Every newly positive trend entered at full exposure; the candidate could reversibly move between `1.0` and `0.5` while the base trend remained positive.

```text
family_id       sign-transition-entropy-persistence-overlay-1h-v1
issue           #705
candidate_count 1
parameter_grid  0
fee             exactly 5 bps one way
execution       completed daily decision -> next hourly open
verdict         reject_exact_sign_transition_entropy_persistence_overlay_family
```

## Frozen signal

For each 720-sign block, the feature is the row-frequency-weighted conditional entropy of the empirical binary sign-transition matrix. At each completed 00:00 UTC decision, the candidate compares the latest 720H block with the immediately preceding non-overlapping 720H block.

```text
base trend  = close_t > close_(t-2160H)
risk state  = H_latest < H_prior and return_168H < 0  -> exposure 0.5
recovery    = H_latest < H_prior and return_168H > 0  -> exposure 1.0
ambiguous   = retain prior exposure
base exit   = exposure 0.0
```

No fitted transition law, smoothing constant, calibrated threshold, parameter grid, exogenous input, cross-sectional information, leverage, credentials, private endpoints, accounts or orders were used.

## Immutable data and sample

| Item | Specification |
|---|---|
| Provider | Public confirmed OKX SPOT |
| Markets | BTC-USDT and ETH-USDT independently |
| Source rows | 43,941 per market |
| Scored prefix | First 43,441 contiguous confirmed 1H bars |
| Training | `[2,880,17,520)` |
| Development OOS | `[17,520,43,440)` |
| Full scored | `[2,880,43,440)` |
| OOS breadth | 12 contiguous 2,160H folds and four calendar years |
| Uncertainty | 5,000 paired non-circular 168H moving-block resamples; seed 20260730 |
| Later suffix | Unread and unscored |

BTC CSV SHA-256: `92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9`  
ETH CSV SHA-256: `2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726`

## Training

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC | Candidate | -46.87% | -1.363 | -51.18% | 42.5 | +2.12% | -136.09 bps |
| BTC | B1 daily | -41.29% | -0.840 | -55.92% | 28.0 | +1.40% | -159.81 bps |
| BTC | B0 hourly | -41.02% | -0.831 | -55.56% | 138.0 | +6.90% | -32.09 bps |
| ETH | Candidate | -30.57% | -0.444 | -47.86% | 31.0 | +1.55% | -84.22 bps |
| ETH | B1 daily | -40.59% | -0.584 | -56.95% | 23.0 | +1.15% | -168.77 bps |
| ETH | B0 hourly | -46.84% | -0.744 | -57.75% | 88.0 | +4.40% | -56.53 bps |

## Development OOS

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC | Candidate | +115.05% | 1.009 | -21.73% | 67.0 | +3.35% | 134.39 bps |
| BTC | B1 daily | +119.68% | 0.954 | -26.55% | 45.0 | +2.25% | 212.75 bps |
| BTC | B0 hourly | +111.64% | 0.917 | -22.68% | 203.0 | +10.15% | 45.31 bps |
| ETH | Candidate | +41.46% | 0.514 | -41.54% | 51.0 | +2.55% | 102.00 bps |
| ETH | B1 daily | +74.52% | 0.646 | -47.77% | 30.0 | +1.50% | 283.58 bps |
| ETH | B0 hourly | +68.02% | 0.618 | -47.30% | 139.0 | +6.95% | 58.31 bps |

## Full scored sample

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC | Candidate | +14.25% | 0.244 | -55.08% | 109.5 | +5.47% | 29.41 bps |
| BTC | B1 daily | +28.97% | 0.332 | -55.92% | 73.0 | +3.65% | 69.85 bps |
| BTC | B0 hourly | +24.82% | 0.310 | -55.56% | 341.0 | +17.05% | 13.98 bps |
| ETH | Candidate | -1.79% | 0.162 | -47.86% | 82.0 | +4.10% | 31.60 bps |
| ETH | B1 daily | +3.68% | 0.233 | -56.95% | 53.0 | +2.65% | 87.28 bps |
| ETH | B0 hourly | -10.68% | 0.158 | -57.75% | 227.0 | +11.35% | 13.79 bps |

## Breadth and uncertainty

| Market | Profitable folds | Profitable years | Improved folds/years vs B1 | Residual Sharpe | Annualised mean Δ 95% | Sharpe Δ 95% |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 5/12 | 3/4 | 4/12; 3/4 | -0.215 | [-11.88%, +8.11%] | [-0.220, 0.353] |
| ETH-USDT | 6/12 | 2/4 | 5/12; 1/4 | -0.679 | [-29.71%, +6.08%] | [-0.513, 0.236] |

Neither market reached seven profitable folds. ETH also failed the three-profitable-year requirement. Both residual Sharpes were negative and all four dependence-aware lower confidence bounds were below zero.

## Failure mechanism

### BTC-USDT

The candidate generated **27 effective risk transitions** and **22 effective recovery transitions** OOS. Raw risk/recovery triggers were `93` / `205`; repeated same-state triggers were `66` / `183`.

```text
Half-state hours                     4,008
Half-state arithmetic market return  +9.19%
Full-equivalent hours removed         2,004.0
Market carry removed                  +4.59%
Incremental fees versus B1            +1.10%
Arithmetic net delta versus B1        -5.69%
Mean next-168H after risk transition  +3.28%
Positive next-168H risk share          62.96%
```

BTC risk transitions were followed by positive mean returns over 24H, 168H and 720H. The half-risk state still carried +9.19% arithmetic market return across 27 episodes, of which 17 were positive. The candidate improved drawdown and Sharpe versus B1, but sacrificed +4.63% compounded return, added 22.0 turnover units and reduced edge per turnover from 212.75 to 134.39 bps.

A diagnostic-only 168H-direction overlay without the entropy condition returned +85.44%, Sharpe 0.873, drawdown -24.79%, and turnover 89.5. Candidate-minus-shadow arithmetic net was +16.21% across 2,881 differing hours. This shadow was not preregistered and is not eligible for rescue or promotion.

### ETH-USDT

The candidate generated **27 effective risk transitions** and **21 effective recovery transitions** OOS. Raw risk/recovery triggers were `83` / `141`; repeated same-state triggers were `56` / `120`.

```text
Half-state hours                     6,312
Half-state arithmetic market return  +64.01%
Full-equivalent hours removed         3,156.0
Market carry removed                  +32.00%
Incremental fees versus B1            +1.05%
Arithmetic net delta versus B1        -33.05%
Mean next-168H after risk transition  -1.30%
Positive next-168H risk share          40.74%
```

ETH risk transitions had negative mean 168H and 720H forward returns, so the trigger contained short-horizon information. The state was nevertheless economically mistimed: its 6,312 half-exposure hours carried +64.01% arithmetic market return, causing +32.00% of removed carry before fees. Candidate OOS return fell from B1's +74.52% to +41.46%, Sharpe fell from 0.646 to 0.514, and turnover rose from 30.0 to 51.0.

A diagnostic-only 168H-direction overlay without the entropy condition returned +69.23%, Sharpe 0.678, drawdown -40.30%, and turnover 71.0. Candidate-minus-shadow arithmetic net was -19.28% across 3,600 differing hours. This shadow was not preregistered and is not eligible for rescue or promotion.

## Repaired evidence defect

The first implementation attempted to assign a next-open position for the final completed bar even though no following open-to-open payoff existed. It failed before producing any performance output. The execution boundary was repaired so the last eligible decision is the last bar with a complete next-open payoff.

After failure inspection, the initial diagnostics could not distinguish incremental entropy information from the already-visible 168H return direction. A diagnostic-only direction overlay was added and the complete experiment was rerun. This changed no candidate signal, position, fee, metric, bootstrap draw, acceptance gate or verdict. Two terminal executions produced byte-identical JSON.

```text
result.json SHA-256 6a17f1c27604f164e59bf1624a7ed4400fd7dd91f6d0722449e626f8c17f13a8
```

## Verdict

```text
reject_exact_sign_transition_entropy_persistence_overlay_family
```

BTC failed benchmark return, turnover, edge per turnover, fold breadth, residual Sharpe and both uncertainty gates. ETH additionally failed benchmark Sharpe and calendar-year breadth. No same-interval change to sign treatment, entropy definition, windows, state retention, exposure fraction, cadence, fee, market-specific treatment or acceptance gates is authorised. There is no G1 nomination, paper promotion or live-trading authorisation.

**Remaining blocker:** recurrent weakness overlays continue to remove positive slow-trend carry. The entropy condition improved BTC relative to a direction-only diagnostic but harmed ETH, and hysteretic recovery left too many profitable hours at half exposure while adding turnover.

**Next strategy experiment:** one own-history-only **two-sleeve trend-onset temporal ensemble**. On every newly positive 2,160H trend, deploy one 0.5 sleeve immediately and a second 0.5 sleeve exactly 168H later only if the base trend remains positive. Each sleeve exits only when the base trend becomes non-positive. This creates no recurrent risk-state churn, preserves partial exposure to every onset, and guarantees total turnover no greater than B1. One candidate, no fitted threshold, no grid and no market-specific rule.
