# Drawdown-conditioned base-exit bridge — terminal report

```text
family          drawdown-conditioned-base-exit-bridge-1h-v1
candidate count 1
parameter grid  0
bridge          at most 168H at 0.5 exposure
fee             exactly 5 bps one way
verdict         reject_exact_drawdown_conditioned_base_exit_bridge_family
```

## Frozen strategy

Every completed daily 00:00 UTC positive 2,160H endpoint-trend decision targets full exposure at the next hourly open. At the first non-positive base decision after a positive state, the strategy retains a 0.5 bridge only when the latest 168H maximum log drawdown is no larger than the preceding adjacent 168H drawdown, or recovery from the latest maximum-drawdown trough is at least one half. The bridge ends on the first base recross or at exactly 168H. Otherwise the strategy exits directly.

## Immutable evaluation

- Public confirmed OKX SPOT BTC-USDT and ETH-USDT 1H candles, evaluated independently.
- First 43,441 contiguous confirmed rows only; training `[2,880,17,520)`, development OOS `[17,520,43,440)`, full `[2,880,43,440)`.
- Completed-bar decisions, next-open execution, exactly `0.0005 × abs(exposure change)` fees.
- Twelve contiguous 2,160H OOS folds, four calendar years, and 5,000 paired non-circular 168H moving-block resamples.

## Training

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | -40.52% | -0.813 | -55.34% | 25.0 | +1.25% | -173.58 bps |
| BTC-USDT | Daily B1 | -41.29% | -0.840 | -55.92% | 28.0 | +1.40% | -159.81 bps |
| BTC-USDT | Hourly B0 | -41.02% | -0.831 | -55.56% | 138.0 | +6.90% | -32.09 bps |
| ETH-USDT | Candidate | -41.49% | -0.598 | -58.01% | 20.5 | +1.03% | -195.69 bps |
| ETH-USDT | Daily B1 | -40.59% | -0.584 | -56.95% | 23.0 | +1.15% | -168.77 bps |
| ETH-USDT | Hourly B0 | -46.84% | -0.744 | -57.75% | 88.0 | +4.40% | -56.53 bps |

## Oos

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | +124.67% | +0.970 | -25.42% | 35.0 | +1.75% | +280.85 bps |
| BTC-USDT | Daily B1 | +119.68% | +0.954 | -26.55% | 45.0 | +2.25% | +212.75 bps |
| BTC-USDT | Hourly B0 | +111.64% | +0.917 | -22.68% | 203.0 | +10.15% | +45.31 bps |
| ETH-USDT | Candidate | +69.17% | +0.621 | -47.29% | 24.5 | +1.23% | +335.63 bps |
| ETH-USDT | Daily B1 | +74.52% | +0.646 | -47.77% | 30.0 | +1.50% | +283.58 bps |
| ETH-USDT | Hourly B0 | +68.02% | +0.618 | -47.30% | 139.0 | +6.95% | +58.31 bps |

## Full

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | +33.64% | +0.355 | -55.34% | 60.0 | +3.00% | +91.51 bps |
| BTC-USDT | Daily B1 | +28.97% | +0.332 | -55.92% | 73.0 | +3.65% | +69.85 bps |
| BTC-USDT | Hourly B0 | +24.82% | +0.310 | -55.56% | 341.0 | +17.05% | +13.98 bps |
| ETH-USDT | Candidate | -1.02% | +0.211 | -58.01% | 45.0 | +2.25% | +93.58 bps |
| ETH-USDT | Daily B1 | +3.68% | +0.233 | -56.95% | 53.0 | +2.65% | +87.28 bps |
| ETH-USDT | Hourly B0 | -10.68% | +0.158 | -57.75% | 227.0 | +11.35% | +13.79 bps |

## Breadth and uncertainty

| Market | Profitable folds | Profitable years | Improved folds/years | Concentration | Residual Sharpe | Mean Δ 95% | Sharpe Δ 95% |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 4/12 | 3/4 | 4/12; 3/4 | 35.01% | +0.187 | [-3.15%, +4.91%] | [-0.104, +0.132] |
| ETH-USDT | 6/12 | 3/4 | 3/12; 2/4 | 23.42% | -0.227 | [-5.75%, +2.74%] | [-0.134, +0.060] |

## Failure mechanism

### BTC-USDT

```text
OOS bridge starts                 13
Inherited overlapping bridges      0
Bridge hours                        1080
Full-equivalent exposure added      540.0H
Market arithmetic return in bridge  +4.12%
Gross timing contribution vs B1     +2.06%
Incremental turnover                 -10.0
Fee contribution                     +0.50%
Arithmetic candidate-minus-B1        +2.56%
```

### ETH-USDT

```text
OOS bridge starts                 8
Inherited overlapping bridges      1
Bridge hours                        913
Full-equivalent exposure added      456.5H
Market arithmetic return in bridge  -6.24%
Gross timing contribution vs B1     -3.12%
Incremental turnover                 -5.5
Fee contribution                     +0.27%
Arithmetic candidate-minus-B1        -2.85%
```

### Diagnostic repair

The initial span diagnostic would have treated every bridge overlapping development OOS as an OOS trigger. ETH carried one bridge across the training/OOS boundary: it began before index 17,520 and contributed only one half-exposure OOS hour before the base recross. The terminal diagnostic separates starts, inherited overlap, and all overlapping exposure while preserving the exact return and fee decomposition. No position, metric, bootstrap draw, gate, or verdict changed.

### Economic interpretation

BTC benefited because the selected OOS bridge intervals carried +4.12% arithmetic market return, and ten saved exit/re-entry turnover units added another 0.50 percentage point. ETH showed the opposite transport: selected bridge intervals carried -6.24%, so 0.27 point of fee savings could not offset -3.12 points of added half-exposure timing. Two complete ETH expiry bridges in June and July 2024 carried approximately -8.83% and -5.81% arithmetic market returns and dominated the bilateral failure.

The price-path resilience condition therefore does not identify the same latent state across BTC and ETH. A smaller latest drawdown or partial recovery can precede either mechanical recross or continued liquidation; the endpoint-transition context remains under-specified.

## Verdict

```text
reject_exact_drawdown_conditioned_base_exit_bridge_family
```

Failure of either development market rejects the exact family. No same-interval threshold, horizon, sleeve, inequality, cadence, fee, or market-specific rescue is authorised.

**Remaining blocker:** price-only drawdown and recovery states are not bilaterally identifiable at slow-trend exits. Turnover suppression is economically useful, but ETH adverse carry during apparently resilient exits overwhelms the saved fees.

**Next strategy experiment:** one own-history-only expanding base-exit recross-hazard model. Estimate, from only prior completed exit episodes of the same instrument, the probability of a positive 2,160H base recross within 168H using fixed causal features for endpoint-margin depth, latest 24H return, and elapsed negative-state duration. Map the frozen probability directly to a bounded long/cash exit sleeve, with one candidate, no cross-market pooling, no parameter grid, and the same 5-bps bilateral gates. This tests transition-duration information rather than another drawdown threshold or fixed bridge rescue.
