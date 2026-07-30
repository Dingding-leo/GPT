# Drawdown-conditioned base-exit bridge — terminal report

```text
family          drawdown-conditioned-base-exit-bridge-1h-v1
candidate count 1
parameter grid  0
bridge          0.5 exposure, at most 168H
fee             exactly 5 bps one way
verdict         reject_exact_drawdown_conditioned_base_exit_bridge_family
```

## Frozen strategy

Every positive daily 2,160H endpoint trend held full exposure. At the first non-positive base decision, the candidate retained a half sleeve only when the latest 168H maximum log drawdown was no larger than the preceding 168H drawdown or recovery from the latest maximum-drawdown trough was at least one half. The bridge restored full exposure on base recross and otherwise expired after exactly 168H. There was one candidate, no grid, no fitted threshold, no market-specific rule, and next-open execution.

## Immutable data

Public confirmed OKX SPOT BTC-USDT and ETH-USDT 1H candles from workflow run `30567744552`, scored on the first 43,441 contiguous rows only. Training `[2880,17520)`, development OOS `[17520,43440)`, full `[2880,43440)`. Twelve 2,160H folds, four calendar years, and 5,000 paired non-circular 168H moving-block resamples used seed `20260731`.

## Training

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | candidate | -40.52% | -0.813 | -55.34% | 25.0 | 1.25% | -173.58 bps |
| BTC-USDT | B1 | -41.29% | -0.840 | -55.92% | 28.0 | 1.40% | -159.81 bps |
| BTC-USDT | B0 | -41.02% | -0.831 | -55.56% | 138.0 | 6.90% | -32.09 bps |
| ETH-USDT | candidate | -41.49% | -0.599 | -58.01% | 20.5 | 1.03% | -195.69 bps |
| ETH-USDT | B1 | -40.59% | -0.584 | -56.95% | 23.0 | 1.15% | -168.77 bps |
| ETH-USDT | B0 | -46.84% | -0.744 | -57.75% | 88.0 | 4.40% | -56.53 bps |

## Development OOS

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | candidate | +124.67% | +0.970 | -25.42% | 35.0 | 1.75% | 280.85 bps |
| BTC-USDT | B1 | +119.68% | +0.954 | -26.55% | 45.0 | 2.25% | 212.75 bps |
| BTC-USDT | B0 | +111.64% | +0.917 | -22.68% | 203.0 | 10.15% | 45.31 bps |
| ETH-USDT | candidate | +69.17% | +0.621 | -47.29% | 24.5 | 1.23% | 335.63 bps |
| ETH-USDT | B1 | +74.52% | +0.646 | -47.77% | 30.0 | 1.50% | 283.58 bps |
| ETH-USDT | B0 | +68.02% | +0.618 | -47.30% | 139.0 | 6.95% | 58.31 bps |

## Full scored sample

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | candidate | +33.64% | +0.355 | -55.34% | 60.0 | 3.00% | 91.51 bps |
| BTC-USDT | B1 | +28.97% | +0.332 | -55.92% | 73.0 | 3.65% | 69.85 bps |
| BTC-USDT | B0 | +24.82% | +0.310 | -55.56% | 341.0 | 17.05% | 13.98 bps |
| ETH-USDT | candidate | -1.02% | +0.211 | -58.01% | 45.0 | 2.25% | 93.58 bps |
| ETH-USDT | B1 | +3.68% | +0.233 | -56.95% | 53.0 | 2.65% | 87.28 bps |
| ETH-USDT | B0 | -10.68% | +0.158 | -57.75% | 227.0 | 11.35% | 13.79 bps |

## Breadth and uncertainty

| Market | Profitable folds | Profitable years | Concentration | Residual Sharpe | Mean delta 95% | Sharpe delta 95% |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 4/12 | 3/4 | 35.01% | +0.187 | [-3.15%, +4.91%] | [-0.104, +0.132] |
| ETH-USDT | 6/12 | 3/4 | 23.42% | -0.227 | [-5.75%, +2.74%] | [-0.134, +0.060] |

## Failure mechanism

### BTC-USDT

```text
Bridge starts                         13
Candidate-only exposure hours         1080
Full-equivalent exposure added         540.0H
Gross timing contribution             +2.06%
Fee contribution                      +0.50%
Arithmetic candidate-minus-B1         +2.56%
```

```text
Mean next-24H return   +1.10%
Mean next-168H return  -0.24%
Mean next-720H return  -1.41%
```

### ETH-USDT

```text
Bridge starts                         8
Candidate-only exposure hours         913
Full-equivalent exposure added         456.5H
Gross timing contribution             -3.12%
Fee contribution                      +0.27%
Arithmetic candidate-minus-B1         -2.85%
```

```text
Mean next-24H return   -0.33%
Mean next-168H return  +0.20%
Mean next-720H return  -6.18%
```

### Mechanism interpretation

BTC generated 13 OOS bridges: 10 restored on base recross and 3 expired. The transition relocation reduced turnover by 10.0 units versus B1 and saved 0.50% of fees while adding a positive 2.06% gross arithmetic timing contribution. However, only 4/12 folds were profitable and both paired-block lower bounds remained negative. The aggregate improvement therefore lacked temporal breadth and dependence-aware support.

ETH generated 8 OOS starts plus one inherited bridge hour at the OOS boundary. Five bridges restored and three expired. Turnover fell by 5.5 units and fees by 0.275%, but added half exposure lost 3.12% gross arithmetic return. The two events satisfying both trigger clauses contributed -4.80% gross, overwhelming the drawdown-only (+0.88%) and recovery-only (+0.87%) subsets. The exact frozen OR interaction was not bilaterally transportable.

## Diagnostic repair

The first diagnostic counted only bridge starts inside each scored sample. ETH OOS inherited a bridge started at 2023-07-23 00:00 UTC, one day before the OOS boundary, and carried 0.5 exposure through the first OOS return before restoring. The terminal reproducer separates in-sample starts from inherited overlap, while retaining the inherited exposure and boundary turnover in all performance and fee calculations. No signal, position, return, fee, bootstrap draw, acceptance gate, or verdict changed.

Two complete terminal executions produced byte-identical protocol, result, and report files.

## Verdict

```text
reject_exact_drawdown_conditioned_base_exit_bridge_family
```

Acceptance required every frozen gate to pass independently in both markets. Same-interval rescue, retuning, market selection, paper promotion, and live trading are not authorised.

## Reproducibility

Canonical result SHA-256: `2c99c6bf983ee212c3429f9d55a0c7ba56d93ecadf26bb9518d93f49d8dc35b9`.
