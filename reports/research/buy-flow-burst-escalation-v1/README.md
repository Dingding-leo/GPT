# Buy-flow burst escalation feature diagnostic
## Hypothesis
Positive taker-flow imbalance delivered in increasingly clustered one-minute trade bursts may represent information-driven buying and predict next-hour continuation.
## Frozen policy
```text
imbalance_h = sum(sign(side) * price * base_size) / sum(price * base_size)
fano_h = population variance of 60 one-minute trade counts / their mean
delta_h = log(fano_h) - log(fano_{h-1})
long next hour iff imbalance_h > 0 and delta_h > 0; otherwise cash
execution: completed hour h -> observed open h+1 -> open h+2
fee: exactly 5 bps one-way on every position change, including terminal liquidation
```
The positive-flow sign rule is an attribution control, not a second candidate. The fixed 2,160H simple-trend benchmark is unchanged.
## Data and timing
- **BTC-USDT:** 367,392 individual trades; 24 complete feature hours; 22 next-open intervals; missing feature/execution boundaries `0/0`.
- **ETH-USDT:** 261,544 individual trades; 24 complete feature hours; 22 next-open intervals; missing feature/execution boundaries `0/0`.

Only public, unauthenticated, immutable OKX artifacts were used. The decision for hour h is computed after h completes and cannot affect any earlier decision. Exact-byte rerun, suffix mutation, equal-timestamp permutation, instrument identity, complete-grid, and canonical-open tests passed.
## Results
| Market | Policy | Net return | Sharpe* | Max DD | Turnover | Edge/turnover | Long hours | Fee burden |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Burst candidate | -0.900% | -21.62 | -1.526% | 12.0 | -7.51 bps | 8/22 | 0.600% |
| BTC-USDT | Positive-flow control | -0.458% | -8.15 | -1.445% | 10.0 | -4.53 bps | 15/22 | 0.500% |
| BTC-USDT | Simple trend | 0.000% | 0.00 | 0.000% | 0.0 | undefined | 0/22 | 0.000% |
| ETH-USDT | Burst candidate | -0.673% | -14.09 | -1.075% | 8.0 | -8.39 bps | 5/22 | 0.400% |
| ETH-USDT | Positive-flow control | -0.865% | -16.40 | -1.075% | 10.0 | -8.64 bps | 8/22 | 0.500% |
| ETH-USDT | Simple trend | 0.000% | 0.00 | 0.000% | 0.0 | undefined | 0/22 | 0.000% |

*Annualized Sharpe is mechanical on a 22-hour sample and is not promotion-grade.
## Incremental attribution
### BTC-USDT
- Candidate minus simple-trend net arithmetic return: `-0.901%`.
- Candidate minus positive-flow control: `-0.448%`; Sharpe delta `-13.466`.
- Retained burst-confirmed hours averaged `-3.76` gross bps; removed positive-flow hours averaged `4.98` gross bps.
- Profitable complete 4H blocks: `1/5`; positive-block concentration `100.0%`.
- compression: occupancy `13/22`, candidate net arithmetic `-0.718%`.
- expansion: occupancy `9/22`, candidate net arithmetic `-0.183%`.
### ETH-USDT
- Candidate minus simple-trend net arithmetic return: `-0.671%`.
- Candidate minus positive-flow control: `0.193%`; Sharpe delta `2.315`.
- Retained burst-confirmed hours averaged `-5.42` gross bps; removed positive-flow hours averaged `-3.09` gross bps.
- Profitable complete 4H blocks: `1/5`; positive-block concentration `100.0%`.
- compression: occupancy `13/22`, candidate net arithmetic `-0.893%`.
- expansion: occupancy `9/22`, candidate net arithmetic `0.222%`.
## Uncertainty
A 5,000-resample paired common-calendar non-circular 4H moving-block bootstrap compared the candidate with the positive-flow control. Holm adjustment covered both mean and Sharpe endpoints in both markets.

| Market | Endpoint | Observed | One-sided 95% lower bound | Holm p |
|---|---|---:|---:|---:|
| BTC-USDT | mean_delta | -1.7852 | -6.6229 | 1.0000 |
| BTC-USDT | sharpe_delta | -13.4655 | -40.0452 | 1.0000 |
| ETH-USDT | mean_delta | 0.7670 | -2.4943 | 1.0000 |
| ETH-USDT | sharpe_delta | 2.3148 | -19.5946 | 1.0000 |

Initial uncertainty code sampled BTC and ETH independently. Final inference uses identical calendar block indices across markets to preserve contemporaneous dependence; point metrics are unchanged.
## Verdict
```text
rejected_by_bounded_real_data_feature_diagnostic
```
Both markets lost money after the exact fee, produced negative edge per turnover, and achieved only `1/5` profitable complete 4H blocks. BTC also materially underperformed the positive-flow control. ETH saved some turnover relative to the control, but remained negative and its adjusted lower bounds were below zero.

The exact sign-and-rising-burst rule is in cooldown on this evidence. This does not reject or modify the frozen #537 V1/V2 family. The next non-duplicative feature test is the authorized 720H V2 flow-response residual after the development-stage gate opens.

## Reproduction hashes
```text
script SHA-256  60cea6d042c5217b99ec0df92c5f98c9c8875809f9b30cbd82cf74d561b425a7
result SHA-256  78577fc83d04e5caaf293c000f76328b4a90c8cfdae7d13a8edbbd814f833057
byte-identical full rerun  PASS
```
