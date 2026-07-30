# Spectral trend-quality irreversible downgrade — terminal report

```text
family          spectral-trend-quality-irreversible-downgrade-1h-v1
candidate count 1
parameter grid  0
fee             exactly 5 bps one way
verdict         reject_exact_spectral_trend_quality_irreversible_downgrade_family
```

## Frozen strategy

For each instrument independently, every newly positive daily 2,160H endpoint trend entered at full exposure. At subsequent completed 00:00 UTC decisions, the latest 720 hourly log returns were mean-centred and transformed with a length-720 real FFT. Positive-frequency bins 1–180 and 181–360 formed equal-count low- and high-frequency bands. If `mean(low power) / mean(high power) < 1` while the latest 168H return was negative, exposure was irreversibly reduced from `1.0` to `0.5` for the rest of that positive-trend regime. A base-trend exit forced cash. Execution was at the next hourly open with exactly 5 bps charged per absolute exposure change.

## Immutable data and evaluation

- Public confirmed OKX SPOT BTC-USDT and ETH-USDT 1H candles, evaluated independently.
- First 43,441 contiguous confirmed rows only; later 500-row suffix unread by strategy metrics.
- Training `[2,880,17,520)`, development OOS `[17,520,43,440)`, full `[2,880,43,440)`.
- Twelve contiguous 2,160H OOS folds and four calendar years.
- 5,000 paired non-circular 168H moving-block resamples, seed `20260731`.

## Training

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | candidate | -34.20% | -1.023 | -45.50% | 28.0 | +1.40% | -134.87 bps |
| BTC-USDT | benchmark_b1 | -41.29% | -0.840 | -55.92% | 28.0 | +1.40% | -159.81 bps |
| ETH-USDT | candidate | -28.08% | -0.571 | -46.18% | 22.5 | +1.12% | -117.81 bps |
| ETH-USDT | benchmark_b1 | -40.59% | -0.584 | -56.95% | 23.0 | +1.15% | -168.77 bps |

## Development OOS

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | candidate | +65.89% | 0.941 | -14.58% | 44.5 | +2.23% | 127.55 bps |
| BTC-USDT | benchmark_b1 | +119.68% | 0.954 | -26.55% | 45.0 | +2.25% | 212.75 bps |
| ETH-USDT | candidate | +74.59% | 0.807 | -29.88% | 30.0 | +1.50% | 225.34 bps |
| ETH-USDT | benchmark_b1 | +74.52% | 0.646 | -47.77% | 30.0 | +1.50% | 283.58 bps |

## Full scored

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | candidate | +9.16% | 0.195 | -45.50% | 72.5 | +3.62% | 26.20 bps |
| BTC-USDT | benchmark_b1 | +28.97% | 0.332 | -55.92% | 73.0 | +3.65% | 69.85 bps |
| ETH-USDT | candidate | +25.56% | 0.316 | -46.18% | 52.5 | +2.62% | 78.27 bps |
| ETH-USDT | benchmark_b1 | +3.68% | 0.233 | -56.95% | 53.0 | +2.65% | 87.28 bps |

## OOS benchmark context

| Market | Policy | Net | Sharpe | Max DD | Turnover | Edge/turn |
|---|---|---:|---:|---:|---:|---:|
| BTC-USDT | hourly B0 | +111.64% | 0.917 | -22.68% | 203.0 | 45.31 bps |
| ETH-USDT | hourly B0 | +68.02% | 0.618 | -47.30% | 139.0 | 58.31 bps |

## Breadth and uncertainty

| Market | Profitable folds | Profitable years | Improved folds/years | Concentration | Residual Sharpe | Mean Δ 95% | Sharpe Δ 95% |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 5/12 | 3/4 | 5/12; 1/4 | 33.99% | -0.841 | [-30.07%, +5.61%] | [-0.311, +0.293] |
| ETH-USDT | 6/12 | 3/4 | 6/12; 2/4 | 25.67% | -0.298 | [-28.86%, +16.79%] | [-0.249, +0.548] |

## Failure mechanism

### BTC: high-frequency dominance marked profitable continuation

BTC generated 10 OOS downgrades and then remained half-sized for 11,857 hours. The half-state intervals carried +78.01% arithmetic market return, so the strategy removed 39.00 percentage points of arithmetic return while saving only 0.025 percentage point of fees. Mean market returns after downgrade were +0.30% over 24H, +1.30% over 168H and +7.15% over 720H. Two long half states beginning in November 2023 and November 2024 alone carried +86.46% and +42.39% market returns. The state therefore classified recoverable high-frequency weakness as a permanent quality failure.

### ETH: short-horizon warning, destructive irreversible horizon

ETH generated 7 OOS downgrades and remained half-sized for 9,744 hours. Trigger-time information was directionally useful: mean following returns were −1.13% over 24H, −2.90% over 168H and −3.81% over 720H. However, the irreversible state lasted far beyond the warning horizon. Half-state intervals ultimately carried +34.95% arithmetic market return, removing 17.47 percentage points versus B1. The slightly higher compounded OOS return and much better drawdown were variance/sequence effects; residual Sharpe was negative and edge per turnover fell from 283.58 to 225.34 bps.

### Training/OOS transport

In training, half-state market carry was negative in both markets (BTC −13.97%, ETH −24.57%), so the downgrade improved arithmetic return. OOS, the same state carried strongly positive market return in both markets. Activation frequency remained material (4 training triggers in each market; 10 BTC and 7 ETH OOS), so the failure was a sign reversal rather than feature disappearance.

## Diagnostic repair and integrity

The first evidence writer embedded a hash calculated before adding the hash field to the same JSON file. This did not affect any strategy value, but it made the reported file digest ambiguous. The terminal writer now hashes the canonical result payload without a self-referential field and records that digest in the compact result and report.

- Full and prefix SHA-256 identities passed for both source CSVs.
- Confirmed contiguous 1H chronology passed.
- Independent state reconstruction, position domain, next-open execution, exact fee identity and return decomposition passed.
- Building positions on the full 43,941-row source produced byte-identical positions on the frozen 43,441-row prefix.
- Two complete terminal executions produced byte-identical canonical results.

```text
canonical result SHA-256
abad29e831547bcb541fc471194046a1397d4640cf94d29bd69960e28d3d7b2a
```

## Verdict

```text
reject_exact_spectral_trend_quality_irreversible_downgrade_family
```

BTC failed return, Sharpe, edge per turnover, profitable-fold breadth, residual Sharpe and both uncertainty gates. ETH passed aggregate return, Sharpe, drawdown and turnover point-estimate gates but failed edge per turnover, fold breadth, residual Sharpe and both uncertainty gates. No same-interval spectral band, lookback, threshold, sizing, cadence, fee or market-specific rescue is authorised. No G1, paper or live-trading nomination results.
