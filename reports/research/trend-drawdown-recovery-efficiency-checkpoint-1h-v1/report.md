# Trend drawdown recovery-efficiency checkpoint — terminal report

```text
family          trend-drawdown-recovery-efficiency-checkpoint-1h-v1
candidate count 1
parameter grid  0
checkpoint      exactly 168H
fee             exactly 5 bps one way
verdict         reject_exact_trend_drawdown_recovery_efficiency_checkpoint_family
```

## Frozen strategy

At each completed daily `00:00 UTC` decision, each instrument independently formed two adjacent 168H return intervals from completed closes: `close_(t-336H)..close_(t-168H)` and `close_(t-168H)..close_t`. For each interval, it measured the maximum log running-peak-to-close drawdown. The latest block used the earliest maximum-drawdown trough and computed:

```text
recovery_fraction = max(0, log(close_t / latest_trough_close)) / latest_max_drawdown
```

Every newly positive 2,160H endpoint trend entered at full exposure. During an already-positive regime, the first decision with a larger latest drawdown than preceding drawdown and `recovery_fraction < 0.5` reduced exposure from `1.0` to `0.5` at the next hourly open. The checkpoint lasted exactly 168 realizable open-to-open returns unless the base trend became non-positive earlier. At expiry, exposure automatically returned to `1.0` when the base remained positive. No second checkpoint was allowed in the regime.

No fitted threshold, parameter grid, exogenous input, entry veto, leverage, shorting, or market-specific treatment was used.

## Immutable data and evaluation

- Public confirmed OKX SPOT BTC-USDT and ETH-USDT 1H candles, evaluated independently.
- Canonical workflow run `30567744552`; BTC artifact `8769605568`; ETH artifact `8769619607`.
- First 43,441 contiguous confirmed rows only, spanning 24 July 2021 through 8 July 2026 UTC.
- Training `[2,880,17,520)`; development OOS `[17,520,43,440)`; full `[2,880,43,440)`.
- Twelve contiguous 2,160H OOS folds and four calendar years.
- 5,000 paired non-circular 168H moving-block resamples, seed `20260731`.
- Completed-bar decisions, next-open execution, and `0.0005 × abs(exposure change)` fees.
- Full/prefix SHA-256, confirmed chronology, future-suffix invariance, state-duration, and return-decomposition identities passed.

## Training

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | -38.18% | -0.811 | -53.36% | 31.5 | 1.57% | -128.80 bps |
| BTC-USDT | Daily B1 | -41.29% | -0.840 | -55.92% | 28.0 | 1.40% | -159.81 bps |
| BTC-USDT | Hourly B0 | -41.02% | -0.831 | -55.56% | 138.0 | 6.90% | -32.09 bps |
| ETH-USDT | Candidate | -37.80% | -0.572 | -51.14% | 28.0 | 1.40% | -127.69 bps |
| ETH-USDT | Daily B1 | -40.59% | -0.584 | -56.95% | 23.0 | 1.15% | -168.77 bps |
| ETH-USDT | Hourly B0 | -46.84% | -0.744 | -57.75% | 88.0 | 4.40% | -56.53 bps |

Both candidates reduced training loss and drawdown relative to B1, but remained negative and added turnover.

## Development OOS

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | +125.42% | 0.999 | -24.39% | 52.5 | 2.62% | 185.43 bps |
| BTC-USDT | Daily B1 | +119.68% | 0.954 | -26.55% | 45.0 | 2.25% | 212.75 bps |
| BTC-USDT | Hourly B0 | +111.64% | 0.917 | -22.68% | 203.0 | 10.15% | 45.31 bps |
| ETH-USDT | Candidate | +91.94% | 0.724 | -45.41% | 34.0 | 1.70% | 274.34 bps |
| ETH-USDT | Daily B1 | +74.52% | 0.646 | -47.77% | 30.0 | 1.50% | 283.58 bps |
| ETH-USDT | Hourly B0 | +68.02% | 0.618 | -47.30% | 139.0 | 6.95% | 58.31 bps |

BTC improved compounded return by 5.73 percentage points, Sharpe by +0.045, and maximum drawdown by 2.16 points. It added 7.5 turnover units and reduced edge per turnover by -27.32 bps.

ETH improved compounded return by 17.42 percentage points, Sharpe by +0.079, and maximum drawdown by 2.36 points. It added 4.0 turnover units and reduced edge per turnover by -9.24 bps.

## Full scored sample

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | +39.36% | 0.384 | -53.36% | 84.0 | 4.20% | 67.59 bps |
| BTC-USDT | Daily B1 | +28.97% | 0.332 | -55.92% | 73.0 | 3.65% | 69.85 bps |
| BTC-USDT | Hourly B0 | +24.82% | 0.310 | -55.56% | 341.0 | 17.05% | 13.98 bps |
| ETH-USDT | Candidate | +19.39% | 0.300 | -51.14% | 62.0 | 3.10% | 92.78 bps |
| ETH-USDT | Daily B1 | +3.68% | 0.233 | -56.95% | 53.0 | 2.65% | 87.28 bps |
| ETH-USDT | Hourly B0 | -10.68% | 0.158 | -57.75% | 227.0 | 11.35% | 13.79 bps |

## Breadth and uncertainty

| Market | Profitable folds | Profitable years | Improved folds/years | Concentration | Residual Sharpe | Mean Δ 95% | Sharpe Δ 95% |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 5/12 | 3/4 | 5/12; 3/4 | 35.24% | +0.117 | [-3.22%, +5.81%] | [-0.063, +0.191] |
| ETH-USDT | 6/12 | 3/4 | 4/12; 4/4 | 23.12% | +0.511 | [-2.79%, +7.67%] | [-0.052, +0.190] |

Neither market reached the required seven profitable folds. Both residual Sharpes were positive, but every dependence-aware lower confidence bound remained below zero.

## Failure mechanism

### BTC-USDT — positive point estimates did not pay for checkpoint turnover

```text
OOS checkpoint starts                 10
Inherited overlapping checkpoints      1
Half-state hours                       1,585
Full-equivalent exposure removed       792.5H
Market arithmetic return in state      -3.973%
Gross timing contribution vs B1        +1.987%
Incremental turnover                    +7.5
Incremental fee contribution            -0.375%
Arithmetic candidate-minus-B1           +1.612%
```

Mean returns after OOS trigger starts:

```text
Next 24H     -0.59%   positive share 50.0%
Next 168H    +0.61%   positive share 40.0%
Next 720H    +5.99%   positive share 40.0%
```

BTC produced a small positive arithmetic timing residual, but mandatory intra-regime reductions and restorations added 7.5 turnover units and 37.5 bps of fees. A November 2024 checkpoint alone removed approximately 4.75 percentage points of arithmetic return during a sharp continuation rally. The result therefore improved compounded return and risk but failed the frozen turnover, edge-per-turnover, fold-breadth, and uncertainty gates.

### ETH-USDT — stronger timing edge remained sparse and fee-inefficient

```text
OOS checkpoint starts                 7
Inherited overlapping checkpoints      0
Half-state hours                       840
Full-equivalent exposure removed       420.0H
Market arithmetic return in state      -16.801%
Gross timing contribution vs B1        +8.401%
Incremental turnover                    +4.0
Incremental fee contribution            -0.200%
Arithmetic candidate-minus-B1           +8.201%
```

Mean returns after OOS trigger starts:

```text
Next 24H     -0.73%   positive share 57.1%
Next 168H    -5.30%   positive share 14.3%
Next 720H    -5.19%   positive share 28.6%
```

ETH supplied materially stronger deterioration information: seven OOS starts removed 16.80% of arithmetic market carry and added 8.40 points of gross timing benefit. Two July 2024 and May 2026 events generated most of that protection, while a November 2024 checkpoint removed 4.28 points during recovery. The aggregate improvement remained event-sparse, added four turnover units, and did not produce positive confidence lower bounds.

### Diagnostic repair

The initial diagnostic counted every checkpoint overlapping a scored span as a trigger belonging to that span and included its post-trigger returns. BTC development OOS inherited one checkpoint that began 95 hours before the OOS boundary and overlapped the first 49 OOS hours. The terminal reproducer separates overlapping checkpoints, starts inside the span, and inherited state; post-trigger summaries now use only starts inside the scored span while exposure and return decomposition retain the inherited overlap.

No source, signal, exposure, fee, performance metric, breadth result, bootstrap draw, acceptance gate, or verdict changed. Two complete terminal executions were byte-identical.

```text
result.json SHA-256       1b49785cc041dfc4bdd9ee50d8cd3d8b4a7ba6f426380b35256dcafed120d0c7
canonical payload SHA-256 4e2e20c26277b1e076fb4375ea8b7e30b29fbb30687dae6eac1e07d820b95f11
```

## Verdict

```text
reject_exact_trend_drawdown_recovery_efficiency_checkpoint_family
```

Both markets passed aggregate OOS return, Sharpe, drawdown, profitable-year, residual-Sharpe, concentration, and full-positive gates. Both failed turnover, edge per turnover, profitable-fold breadth, and both strict uncertainty gates.

No same-interval block-horizon, recovery threshold, checkpoint-duration, exposure-fraction, cadence, fee, or market-specific rescue is authorised. There is no G1, paper, or live-trading nomination.

**Remaining blocker:** path-dependent drawdown and incomplete recovery contain more bilateral deterioration information than the preceding endpoint-margin and spectral states, but a reversible intra-regime half checkpoint necessarily adds round trips. The observed gross timing edge is too sparse to offset that structural turnover penalty with dependence-aware confidence.

**Next strategy experiment:** one own-history-only **drawdown-conditioned base-exit bridge**. Preserve full exposure throughout every positive 2,160H regime. At the first non-positive base decision, retain a single 0.5 bridge for at most 168H only when the latest 168H drawdown is no larger than the preceding drawdown or recovery exceeds half; otherwise exit directly. Restore full exposure only on base recross. This moves the path feature to a transition where it can suppress mechanical exit/re-entry turnover instead of creating a new intra-regime round trip. One candidate, no grid, unchanged bilateral gates.
