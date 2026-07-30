# Two-loss payoff change-point reset selector rejected

This evidence completes issue #748. The sole candidate replaced the rejected lifetime payoff prior with a fixed causal reset after two consecutive non-positive completed post-exit sleeve payoffs. It used each instrument independently, immutable public OKX SPOT 1H data, next-open execution, and exactly 5 bps one way.

```text
family          two-loss-payoff-change-point-reset-selector-1h-v1
candidate count 1
parameter grid  0
fee             exactly 5 bps one way
main            5a0fcc97d1a882f8223656c51f5bb8055f534e38
verdict         reject_two_loss_payoff_change_point_reset_selector_family
result payload  348b1613d9e42a3fbc588b09f44bbd5f872a3f7f7cf27be1585bd33c2822eed4
result file     595ac50ebe25928e007d29a7b078ecdbc4cf1e9d3006d1a9afc6fc0941428e21
```

## Strategy change

At every positive-to-non-positive completed daily 2,160H endpoint-trend exit, the candidate predicted the exact net arithmetic payoff of a hypothetical 0.5 sleeve using only prior completed same-instrument episodes:

```text
prediction = sum(current-segment episode targets) / (segment_count + 2)
select sleeve only when prediction > 0

episode target = 0.5 * open-to-open carry
               + 0.0005 when the sleeve restores on a daily base recross
```

A completed strictly positive episode reset the loss count. A completed non-positive episode incremented it. On the second consecutive non-positive target, the entire segment was discarded and the estimator returned to its neutral zero state. The sleeve ended at the first daily recross at or before 168H or at exact 168H expiry. No threshold grid, fitted feature, cross-market pooling, market-specific treatment, shorting, or leverage was used.

## Immutable data and sample

| Item | Frozen value |
|---|---|
| Provider | Public confirmed OKX SPOT |
| Markets | BTC-USDT and ETH-USDT independently |
| Workflow | `30567744552` |
| Artifacts | BTC `8769605568`; ETH `8769619607` |
| Source rows | 43,985 per market |
| Frozen prefix | First 43,441 contiguous confirmed 1H rows |
| Prefix span | 24 July 2021 00:00 UTC through 8 July 2026 00:00 UTC |
| Training | `[2880,17520)` |
| Development OOS | `[17520,43440)` |
| Full scored | `[2880,43440)` |
| Breadth | 12 contiguous 2,160H OOS folds and four calendar years |
| Uncertainty | 5,000 paired non-circular 168H moving blocks; seed `20260731` |

Source SHA-256:

```text
BTC 40c7ba3dbf64b8b31c634a79e1a2d5e2fa9d60b024c1fd62848d37ed967c13a0
ETH 0164a5cc1730f70ad9817980d67d6350cf71013cdb759c1a153a66890127d6f8
```

## Performance

### Training

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC | Candidate | -43.84% | -0.879 | -60.76% | 22.0 | +1.10% | -220.67 bps |
| BTC | Hourly B0 | -41.02% | -0.831 | -55.56% | 138.0 | +6.90% | -32.09 bps |
| BTC | Daily B1 | -41.29% | -0.840 | -55.92% | 28.0 | +1.40% | -159.81 bps |
| ETH | Candidate | -40.59% | -0.584 | -56.95% | 23.0 | +1.15% | -168.77 bps |
| ETH | Hourly B0 | -46.84% | -0.744 | -57.75% | 88.0 | +4.40% | -56.53 bps |
| ETH | Daily B1 | -40.59% | -0.584 | -56.95% | 23.0 | +1.15% | -168.77 bps |

### Development OOS

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC | Candidate | +102.39% | 0.865 | -28.37% | 34.0 | +1.70% | 258.92 bps |
| BTC | Hourly B0 | +111.64% | 0.917 | -22.68% | 203.0 | +10.15% | 45.31 bps |
| BTC | Daily B1 | +119.68% | 0.954 | -26.55% | 45.0 | +2.25% | 212.75 bps |
| ETH | Candidate | +57.78% | 0.569 | -52.37% | 28.0 | +1.40% | 268.69 bps |
| ETH | Hourly B0 | +68.02% | 0.618 | -47.30% | 139.0 | +6.95% | 58.31 bps |
| ETH | Daily B1 | +74.52% | 0.646 | -47.77% | 30.0 | +1.50% | 283.58 bps |

### Full scored

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC | Candidate | +13.67% | 0.251 | -60.76% | 56.0 | +2.80% | 70.51 bps |
| BTC | Hourly B0 | +24.82% | 0.310 | -55.56% | 341.0 | +17.05% | 13.98 bps |
| BTC | Daily B1 | +28.97% | 0.332 | -55.92% | 73.0 | +3.65% | 69.85 bps |
| ETH | Candidate | -6.26% | 0.183 | -56.95% | 51.0 | +2.55% | 71.41 bps |
| ETH | Hourly B0 | -10.68% | 0.158 | -57.75% | 227.0 | +11.35% | 13.79 bps |
| ETH | Daily B1 | +3.68% | 0.233 | -56.95% | 53.0 | +2.65% | 87.28 bps |

## Breadth and uncertainty

| Market | Profitable folds | Profitable years | Concentration | Residual Sharpe | Mean delta 95% | Sharpe delta 95% |
|---|---:|---:|---:|---:|---:|---:|
| BTC | 5/12 | 3/4 | 34.22% | -0.451 | [-7.20%, +0.87%] | [-0.227, +0.012] |
| ETH | 6/12 | 3/4 | 21.77% | -0.826 | [-9.40%, +0.71%] | [-0.219, +0.015] |

Common-block bilateral inference:

```text
Median annualised mean delta  -2.97%  [-6.89%, -0.04%]
Median Sharpe delta           -0.083  [-0.183, -0.007]
Markets passing all gates     0/2
```

## Failure mechanism

### BTC

```text
OOS exits                          23
Selected / rejected                15 / 8
Resets total / OOS                 6 / 4
Selected target sum                -7.71%
Gross timing contribution          -8.26%
Fee saving versus B1               +0.55%
Arithmetic candidate-minus-B1      -7.71%
Lifetime-shadow selected           4
Reset-only selected                11
Reset-only target sum              -4.94%
First post-reset positive events   3/4
Missed positive post-reset payoff  +4.58%
```

BTC cut turnover from 45 to 34 and raised edge per turnover from 212.75 to 258.92 bps, but selected sleeves lost 7.71% arithmetically. Return fell 17.29 percentage points versus B1, Sharpe declined by 0.089, and drawdown worsened by 1.82 points. Eleven reset-only selections contributed -4.94%; the reset did not remove adverse payoff quickly enough.

### ETH

```text
OOS exits                          15
Selected / rejected                4 / 11
Resets total / OOS                 3 / 3
Selected target sum                -9.84%
Gross timing contribution          -9.94%
Fee saving versus B1               +0.10%
Arithmetic candidate-minus-B1      -9.84%
Lifetime-shadow selected           0
Reset-only selected                4
Reset-only target sum              -9.84%
First post-reset positive events   2/2
Missed positive post-reset payoff  +4.69%
```

ETH cut turnover from 30 to 28, but all four selected sleeves were introduced by the reset and lost 9.84% arithmetically. The lifetime intercept shadow would have selected none. OOS return fell 16.74 percentage points, drawdown worsened by 4.60 points, and the full-sample candidate became negative.

The hard reset produced a structural cold-start asymmetry. Immediately after a reset the prediction is exactly zero, so the first new episode is always rejected. Three of four BTC first-post-reset episodes and both observable ETH first-post-reset episodes were positive, causing missed positive payoff of 4.58% and 4.69%, respectively. After one positive episode entered the empty segment, the estimator could then select subsequent losses until two consecutive non-positive outcomes accumulated. The mechanism therefore rejected rebound evidence first and admitted adverse episodes later.

## Diagnostic repair

The initial completed calculation reported only candidate-versus-B1 episode totals. That was insufficient to distinguish whether the reset repaired or degraded the preceding lifetime prior. The terminal reproducer added two non-selectable diagnostics: an exact lifetime-intercept shadow at every exit, and first-post-reset payoff accounting. No signal, position, fee, return, fold, bootstrap draw, acceptance gate, or verdict changed.

Two complete terminal executions were byte-identical:

```text
result.json SHA-256  595ac50ebe25928e007d29a7b078ecdbc4cf1e9d3006d1a9afc6fc0941428e21
```

## Verdict

```text
reject_two_loss_payoff_change_point_reset_selector_family
```

BTC failed OOS return, Sharpe, drawdown, fold breadth, residual Sharpe, and both uncertainty gates. ETH failed OOS return, Sharpe, drawdown, edge per turnover, fold breadth, residual Sharpe, both uncertainty gates, and full-positive return. Both common-index lower confidence bounds were negative.

No same-sample change to the two-loss threshold, reset contents, neutral prior, sleeve horizon, sleeve size, cadence, fee, or market-specific treatment is authorised. There is no G1 nomination, paper promotion, or live-trading authorisation.

**Remaining blocker:** episode-payoff history is sparse and alternates too quickly for a hard reset. Empty-state resets systematically miss the first rebound episode, while a single positive seed can reopen selection before adverse payoff has been disproven.

**Next strategy experiment:** acquire and freeze a fresh full-history 1H market cohort before testing one episode-level soft-state model. Use a preregistered bounded sign-evidence state that never deletes all history and maps uncertainty to sleeve size, rather than a hard select/reject reset. Do not reuse BTC/ETH or CFX/FIL to choose its evidence threshold or sizing map.
