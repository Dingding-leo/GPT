# Base-exit margin-source bridge — terminal report

## Verdict

```text
reject_exact_base_exit_margin_source_bridge_family
```

One preregistered own-history-only candidate was tested with no parameter grid. The candidate preserved full exposure throughout every positive daily 2,160H endpoint trend. At the first non-positive daily base decision, it retained a half sleeve for exactly 168H only when the latest 24H current-price leg was non-negative and the positive 24H lag-endpoint leg entering the comparison mechanically drove the endpoint margin through zero. It restored full exposure on a base recross before or at expiry; otherwise it exited. Execution was at the next hourly open with exactly 5 bps one way.

```text
family_id            base-exit-margin-source-bridge-1h-v1
issue                 #715
candidate_count       1
parameter_grid_count  0
research_parent       5a0fcc97d1a882f8223656c51f5bb8055f534e38
```

## Frozen temporal rule

For each instrument independently at completed daily `00:00 UTC` decisions:

```text
base_t        = close_t > close_(t-2160)
previous_base = close_(t-24) > close_(t-2184)
exit_crossing = (not base_t) and previous_base

current_leg_t = log(close_t / close_(t-24))
lag_leg_t     = log(close_(t-2160) / close_(t-2184))

mechanical_exit_t = exit_crossing
                    and current_leg_t >= 0
                    and lag_leg_t > 0
```

The identity

```text
margin_t - margin_(t-24) = current_leg_t - lag_leg_t
```

was checked at every eligible daily decision. A mechanical exit therefore meant the latest price did not decline over 24H, while a sufficiently stronger positive historical leg entered the lag endpoint and pushed the 2,160H comparison through zero.

## Immutable public data and sample

| Item | Frozen specification |
|---|---|
| Provider | Public confirmed OKX SPOT |
| Markets | BTC-USDT and ETH-USDT independently |
| Bar | Exactly 1H |
| Source observations | 43,941 per market |
| Immutable prefix read | First 43,441 confirmed contiguous bars |
| Training | `[2,880,17,520)` |
| Development OOS | `[17,520,43,440)` |
| Full scored | `[2,880,43,440)` |
| OOS breadth | 12 contiguous non-overlapping 2,160H folds and four calendar years |
| Uncertainty | 5,000 paired non-circular 168H moving-block resamples, seed `20260730` |
| Execution | Completed daily decision to next hourly open |
| Fee | Exactly 5 bps per absolute exposure change |
| Later suffix | `[43,440,end)` unread and unscored |

```text
BTC artifact     8704977298
BTC ZIP SHA-256  22d6d0e7f5dbffe4e746f091a5ab2488e3edc7d8440fea393ee2862295cf208c
BTC CSV SHA-256  92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9

ETH artifact     8704978112
ETH ZIP SHA-256  e7107f83a4eb5059ada0bb2097aeb5ded976dc9c037f564538f5cf5b4a7dffe3
ETH CSV SHA-256  2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726
```

## Training performance

| Market | Policy | Gross | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | -41.49% | -42.27% | -0.857 | -58.98% | 27.0 | 1.35% | -171.16 bps |
| BTC-USDT | B1 daily | -40.46% | -41.29% | -0.840 | -55.92% | 28.0 | 1.40% | -159.81 bps |
| BTC-USDT | B0 hourly | -36.80% | -41.02% | -0.831 | -55.56% | 138.0 | 6.90% | -32.09 bps |
| ETH-USDT | Candidate | -40.10% | -40.76% | -0.587 | -56.95% | 22.0 | 1.10% | -177.52 bps |
| ETH-USDT | B1 daily | -39.90% | -40.59% | -0.584 | -56.95% | 23.0 | 1.15% | -168.77 bps |
| ETH-USDT | B0 hourly | -44.45% | -46.84% | -0.744 | -57.75% | 88.0 | 4.40% | -56.53 bps |

The bridge reduced turnover by one unit in each training market, but both candidate paths remained deeply negative and slightly underperformed B1 on return, Sharpe and edge per turnover. BTC drawdown worsened materially.

## Development-OOS performance

| Market | Policy | Gross | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | +121.09% | +116.82% | 0.939 | **-25.75%** | **39.0** | 1.95% | **242.32 bps** |
| BTC-USDT | B1 daily | **+124.68%** | **+119.68%** | **0.954** | -26.55% | 45.0 | 2.25% | 212.75 bps |
| BTC-USDT | B0 hourly | +134.25% | +111.64% | 0.917 | **-22.68%** | 203.0 | 10.15% | 45.31 bps |
| ETH-USDT | Candidate | +70.92% | +68.63% | 0.619 | **-47.29%** | **27.0** | 1.35% | **303.08 bps** |
| ETH-USDT | B1 daily | **+77.16%** | **+74.52%** | **0.646** | -47.77% | 30.0 | 1.50% | 283.58 bps |
| ETH-USDT | B0 hourly | +80.12% | +68.02% | 0.618 | -47.30% | 139.0 | 6.95% | 58.31 bps |

### BTC-USDT versus B1

```text
Compounded net-return delta      -2.86 percentage points
Sharpe delta                     -0.014
Maximum-drawdown improvement     +0.80 percentage points
Turnover reduction               -6.0
Fee saving                       +0.30 percentage points
Edge-per-turn improvement        +29.57 bps
```

The bridge improved drawdown and efficiency because rapid recrosses required only `1.0 -> 0.5 -> 1.0`, but added exposure after the exits had negative carry. Fee savings did not recover the lost return.

### ETH-USDT versus B1

```text
Compounded net-return delta      -5.89 percentage points
Sharpe delta                     -0.027
Maximum-drawdown improvement     +0.48 percentage points
Turnover reduction               -3.0
Fee saving                       +0.15 percentage points
Edge-per-turn improvement        +19.49 bps
```

ETH displayed the same trade-off more strongly: slightly lower drawdown and better turnover efficiency, but materially lower return and Sharpe.

## Full scored sample

| Market | Policy | Gross | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | +29.36% | +25.16% | 0.312 | -58.98% | 66.0 | 3.30% | 73.17 bps |
| BTC-USDT | B1 daily | **+33.77%** | **+28.97%** | **0.332** | **-55.92%** | 73.0 | 3.65% | 69.85 bps |
| ETH-USDT | Candidate | +2.38% | **-0.10%** | 0.215 | -56.95% | 49.0 | 2.45% | 87.30 bps |
| ETH-USDT | B1 daily | +6.47% | **+3.68%** | **0.233** | -56.95% | 53.0 | 2.65% | 87.28 bps |

BTC remained profitable but underperformed B1 and worsened full-sample drawdown. ETH converted a positive B1 full-sample result into a slightly negative candidate result. The positive edge-per-turnover differences were produced by lower turnover, not superior total economics.

## Breadth and dependence-aware uncertainty

| Market | Profitable folds | Profitable years | Improved vs B1 | Positive-fold concentration | Residual Sharpe | Annualised mean delta 95% | Sharpe delta 95% |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 5/12 | 3/4 | 2/12 folds; 2/4 years | 34.65% | -0.180 | [-2.41%, +1.05%] | [-0.075, +0.030] |
| ETH-USDT | 6/12 | 3/4 | 1/12 folds; 1/4 years | 21.58% | -0.306 | [-4.83%, +1.86%] | [-0.111, +0.040] |

Neither market reached the required 7/12 profitable-fold threshold. Both residual Sharpes were negative, and every dependence-aware lower confidence bound was below zero.

## Failure mechanism

### BTC-USDT

```text
Base-exit crossings                    23
Mechanical-source bridge starts         6
Direct exits                            17
Restorations / expiries                 6 / 0
Bridge exposure hours                  384
Full-equivalent hours added            192
Full-market arithmetic carry          -3.07%
Candidate timing contribution         -1.53%
Fee saving versus B1                  +0.30%
Arithmetic candidate-minus-B1         -1.23%
Positive / negative bridge episodes    3 / 3
Largest absolute event share          56.30%
```

Mean market returns after mechanical exits were:

```text
Next 24H      +0.50%
Next 168H     -1.28%
Next 720H    -10.10%
```

The condition correctly identified exits with non-negative immediate price behaviour, but that strength did not persist. One June 2024 bridge lost approximately 4.85% over 120 hours and supplied more than half of absolute event contribution. The remaining events were mixed, so the rule was neither broad nor reliably positive.

### ETH-USDT

```text
Base-exit crossings                    15
Mechanical-source bridge starts         5
Direct exits                            10
Restorations / expiries                 3 / 2
Bridge exposure hours                  552
Full-equivalent hours added            276
Full-market arithmetic carry          -6.79%
Candidate timing contribution         -3.39%
Fee saving versus B1                  +0.15%
Arithmetic candidate-minus-B1         -3.24%
Positive / negative bridge episodes    2 / 3
Largest absolute event share          61.83%
```

Mean market returns after mechanical exits were:

```text
Next 24H      +0.03%
Next 168H     -2.48%
Next 720H    -14.92%
```

The June 2024 expiry lost approximately 8.56% compounded over 168 hours and dominated the negative contribution. Unlike the preceding renewal bridge, which had two favourable ETH recrosses, the algebraic margin-source condition admitted additional durable breakdowns.

### Mechanical versus non-mechanical exits

Mechanical-source exits did not improve one-week separation:

```text
BTC mean next-168H return
  mechanical       -1.28%
  non-mechanical   -1.28%

ETH mean next-168H return
  mechanical       -2.48%
  non-mechanical   -3.90%
```

The feature distinguished immediate price direction, but not enough of the future path to justify extended exposure after the base signal had failed.

## Strategy-facing repair and reproducibility

The first execution failed before producing any performance output because the earliest eligible 2,160H daily decision has no fully defined prior 24H endpoint comparison. A naive identity check referenced `t-2,184` at `t=2,160`, which would wrap to the future suffix under NumPy indexing.

The reproducer was repaired to:

- treat the first 2,160H decision as state initialization only;
- require `t >= 2,184` before evaluating the previous-base and 24H leg decomposition;
- fail closed on every later daily base-state or margin-decomposition mismatch;
- add candidate-versus-B1 fold/year breadth and event-contribution concentration after the aggregate point estimates proved misleading.

No result existed before the boundary repair. Two complete post-repair executions produced byte-identical output:

```text
Full result SHA-256
700041250809070880b26d5778bfc48e5d1029d5d43bd7e6614c9cb940745d62
```

The script passed Python bytecode compilation. Data hashes, contiguous chronology, completed-bar status, position domain, candidate-above-B1 state identity, next-open timing, 5-bps fee accounting and candidate-minus-B1 arithmetic decomposition all passed.

## Acceptance decision

```text
reject_exact_base_exit_margin_source_bridge_family
```

BTC failed OOS return, Sharpe, profitable-fold breadth, residual Sharpe and both strict uncertainty gates.

ETH failed OOS return, Sharpe, profitable-fold breadth, residual Sharpe, both strict uncertainty gates and positive full-scored return.

No same-interval change to the 24H leg definition, inequalities, half sleeve, bridge duration, base horizon, decision cadence, execution timing, fee, market treatment or bootstrap is authorised. There is no G1 nomination, paper promotion or live-trading authorisation.

## Remaining blocker

The base exit itself contains more reliable medium-horizon information than the tested bridge selectors. Recent renewal and algebraic margin-source rules can identify rapid recrosses and reduce turnover, but the added exposure still carries negative bilateral one-week return and is too event-sparse for confidence-supported superiority. Continued same-market bridge feature churn has low expected value.

## Next strategy experiment

Use the next run for **exact-hash cross-market replication of the four-phase daily trend ensemble**, not another exit-bridge rescue. Freeze the already tested `00:00/06:00/12:00/18:00 UTC` four-state exposure mapping without any parameter change, then evaluate it on a preregistered fixed panel of `SOL-USDT`, `XRP-USDT`, `LTC-USDT` and `DOGE-USDT` using a common immutable public OKX 1H interval, exactly 5 bps one way, and no market substitution or filtering if any panel member lacks the required history. The experiment should test whether timestamp-smoothing generalises beyond BTC/ETH; it cannot retroactively rescue the consumed BTC/ETH result.
