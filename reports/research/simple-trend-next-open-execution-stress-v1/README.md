# Simple-trend next-open execution stress v1

Issue: #561

## Frozen objective

Stress the fixed 2,160H per-instrument simple-trend long/cash benchmark under executable next-open returns and one extra hour of latency. Every position is binary long/cash, uses only the instrument's lagged confirmed 1H closes, and pays exactly 5 bps one-way on absolute position change.

## Data

- Public immutable OKX confirmed 1H artifacts from workflow `30347175588`.
- BTC artifact `8685574446`, ZIP SHA-256 `d36b151d0279e552f0f561403647ca8495febf6bd7c87c0b85cf0e7ad3df6119`.
- ETH artifact `8685572234`, ZIP SHA-256 `e32884abe83663b36bc52ce4f4b3cc60b03bb2f4f2948853134dc6831706a9bb`.
- 43,930 contiguous confirmed rows per market, 2021-07-24 00:00 UTC through 2026-07-28 09:00 UTC.
- Development evaluation: 25,920 rows per market, 2023-07-24 through 2026-07-07.
- Fresh temporal extension: 489 rows per market, 2026-07-08 00:00 through 2026-07-28 08:00 UTC.

## Paths

- `C0`: canonical close-to-close benchmark parity path.
- `C1`: same target, filled at the next observed hourly open and evaluated open-to-next-open.
- `C2`: same observed open-to-open return, with one additional complete hour of signal latency.

## Development results

| Market | Path | Net return | Sharpe | Max drawdown | Ann. turnover | Edge/turnover | Transitions | Profitable folds | Profitable years |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | C0 | 111.72% | 0.917 | -22.67% | 68.94 | 45.11 bps | 204 | 5/12 | 3/4 |
| BTC-USDT | C1 | 111.53% | 0.917 | -22.68% | 68.94 | 45.06 bps | 204 | 5/12 | 3/4 |
| BTC-USDT | C2 | 114.16% | 0.928 | -23.52% | 68.94 | 45.71 bps | 204 | 4/12 | 3/4 |
| ETH-USDT | C0 | 67.92% | 0.617 | -47.31% | 47.31 | 57.86 bps | 140 | 6/12 | 3/4 |
| ETH-USDT | C1 | 67.94% | 0.617 | -47.30% | 47.31 | 57.86 bps | 140 | 6/12 | 3/4 |
| ETH-USDT | C2 | 78.55% | 0.664 | -45.22% | 47.31 | 62.24 bps | 140 | 6/12 | 3/4 |

Next-open alignment is economically immaterial: BTC C1 minus C0 is -0.19 percentage points of total return and -0.00076 Sharpe; ETH is +0.01 percentage points and +0.00010 Sharpe. Turnover, fees, exposure and signal transitions are unchanged because only the observed return endpoints change.

The extra-hour path did not trigger the frozen latency blocker. C2 increased full-period Sharpe by 0.011 in BTC and 0.047 in ETH versus C1, although BTC profitable-fold breadth fell from 5/12 to 4/12. These positive point changes are not statistically established and must not be interpreted as a reason to add delay.

## Regime and concentration diagnostics

- **BTC-USDT:** C1 expansion Sharpe `1.163` at `38.9%` occupancy; compression Sharpe `0.722` at `61.1%` occupancy. Minimum leave-one-fold-out Sharpe `0.544`; minimum leave-one-year-out Sharpe `0.218`; largest positive-fold share `35.2%`.
- **ETH-USDT:** C1 expansion Sharpe `0.427` at `37.4%` occupancy; compression Sharpe `0.784` at `62.6%` occupancy. Minimum leave-one-fold-out Sharpe `0.418`; minimum leave-one-year-out Sharpe `0.096`; largest positive-fold share `23.5%`.

Both markets lose money in calendar 2026 through 2026-07-07, but full-period C1 remains positive after deleting any single fold or calendar year. BTC performs better in volatility expansion; ETH performs better in compression, so the benchmark is not supported by one universal volatility-state premium.

## Bar-timing diagnostics

- **BTC-USDT:** mean absolute prior-close to next-open gap `0.148` bps; maximum `11.836` bps; non-zero gaps `27,139` of 43,929 transitions.
- **ETH-USDT:** mean absolute prior-close to next-open gap `0.343` bps; maximum `11.675` bps; non-zero gaps `31,239` of 43,929 transitions.

Despite frequent decimal-level gaps, replacing close-to-close returns with observed next-open-to-next-open returns does not explain the benchmark profitability.

## Uncertainty

5,000 paired non-circular 168H moving-block resamples were run within each of the 12 folds, preserving each fold-boundary row once and using seed `20260728`. Holm adjustment covered eight endpoints.

- `BTC-USDT:C1_next_open_executable_minus_C0_canonical_close_to_close:sharpe`: observed `-0.000756`, basic 95% interval `[-0.002078, +0.000421]`, one-sided lower bound `-0.001882`, Holm p `1.0000`.
- `BTC-USDT:C2_extra_1h_latency_minus_C1_next_open_executable:sharpe`: observed `+0.010948`, basic 95% interval `[-0.111247, +0.137960]`, one-sided lower bound `-0.089749`, Holm p `1.0000`.
- `ETH-USDT:C1_next_open_executable_minus_C0_canonical_close_to_close:sharpe`: observed `+0.000097`, basic 95% interval `[-0.001074, +0.001275]`, one-sided lower bound `-0.000863`, Holm p `1.0000`.
- `ETH-USDT:C2_extra_1h_latency_minus_C1_next_open_executable:sharpe`: observed `+0.046712`, basic 95% interval `[-0.054467, +0.120794]`, one-sided lower bound `-0.037841`, Holm p `1.0000`.

No C1/C0 or C2/C1 difference is statistically established. The stress supports invariance, not an execution-based performance improvement.

## Fresh extension

The 489-hour post-canonical extension produced no trade in either market under C0, C1 or C2: the frozen 2,160H momentum state remained cash throughout. Return, turnover and fee were all zero. This is a valid prospective no-trade observation but provides no fresh payoff evidence.

## Causal and reconstruction evidence

- Canonical C0 hourly return parity error was below `1.12e-16` in both markets.
- ZIP and all 13 internal manifest files per market verified by SHA-256.
- Unique, increasing, contiguous and confirmed 1H bars enforced fail closed.
- Gapped, shuffled, duplicated and unconfirmed structural copies were rejected before any metrics.
- A future-suffix mutation left every earlier C0/C1/C2 position unchanged.
- Two complete runs produced byte-identical JSON.

An initial private run omitted explicit suffix-mutation and malformed-bar execution. These checks were added before publication and the entire experiment was rerun; performance metrics were unchanged.

## Verdict

```text
retain_fixed_development_benchmark_pending_independent_confirmation
```

The fixed 2,160H simple-trend rule survives the next-open and extra-hour timing attacks and remains materially superior to rejected S0 on development BTC and ETH. It is retained only as a fixed development benchmark, not promoted to paper or live use. It still has weak fold breadth, negative 2026 performance, substantial ETH drawdown, and no non-cash payoff observations in the short fresh extension.

No lookback, threshold, smoothing, exposure, latency or market filter may be tuned from this result. The next non-duplicative stress is independent-instrument replication of the unchanged rule on a pre-performance liquidity-qualified universe, or a materially longer prospective epoch.
