# Path-efficiency hysteresis 1H development result

## Frozen objective

Test one own-history-only, causal long/cash architecture that enters a positive 2,160-hour trend only when its signed 720-hour path efficiency exceeds its own causal trailing 60th percentile, exits below the 40th percentile or when slow momentum becomes non-positive, and changes target only at 00:00 UTC.

- Markets: BTC-USDT and ETH-USDT independently.
- Data: immutable confirmed public OKX SPOT 1H candles.
- Execution: completed signal bar `t`, position from `open[t+1]`, payoff `open[t+1] -> open[t+2]`.
- Cost: exactly 5 bps one-way on actual position change.
- Candidate count: 1; no parameter grid.
- Development OOS: 25,920 hours, 2023-07-24 00:00 through 2026-07-07 23:00 UTC.
- Comparators: hourly and daily-at-00UTC 2,160H simple trend.

## Development OOS

| Market / policy | Net return | Sharpe | Max DD | Turnover | Fees | Net edge / turnover |
|---|---:|---:|---:|---:|---:|---:|
| BTC candidate | +118.59% | 1.202 | -24.74% | 37 | 1.85% | 235.30 bps |
| BTC daily trend | +120.22% | 0.956 | -26.55% | 45 | 2.25% | 213.29 bps |
| BTC hourly trend | +112.15% | 0.920 | -22.68% | 203 | 10.15% | 45.43 bps |
| ETH candidate | +94.26% | 0.918 | -28.81% | 24 | 1.20% | 328.71 bps |
| ETH daily trend | +74.52% | 0.646 | -47.77% | 30 | 1.50% | 283.58 bps |
| ETH hourly trend | +68.25% | 0.619 | -47.30% | 139 | 6.95% | 58.41 bps |

The candidate strongly reduced turnover and modeled fee drag. Aggregate Sharpe exceeded both trend comparators in each market. That apparent improvement did not satisfy the frozen robustness gates.

## Breadth and uncertainty

- Profitable folds: BTC 4/12; ETH 4/12. Required: at least 7/12.
- Profitable calendar segments: BTC 2/4; ETH 3/4. Both markets lost in 2026.
- Residual Sharpe versus hourly trend: BTC -0.073; ETH -0.023.
- Positive-fold return concentration: BTC 34.89%; ETH 40.70%.
- BTC candidate-minus-daily annualized mean delta 95% interval: [-26.71%, +20.70%].
- BTC candidate-minus-daily Sharpe delta 95% interval: [-0.520, +1.043].
- ETH candidate-minus-daily annualized mean delta 95% interval: [-41.35%, +35.54%].
- ETH candidate-minus-daily Sharpe delta 95% interval: [-0.735, +1.251].

The point Sharpe improvement is uncertain, while the annualized mean-delta point estimate is slightly negative in both markets. Sparse positive folds and negative residual Sharpe indicate that most benefit came from lower exposure and cadence rather than stable incremental timing information.

## Verdict

```text
reject_exact_path_efficiency_hysteresis_family
```

No threshold, horizon, cadence, quantile, sizing, entry, exit or feature rescue may be tested on this consumed development interval. Untouched OOS remains unread. The result does not authorize paper or live trading.

The next architecture should be materially orthogonal and test own-history serial-dependence information rather than another trend threshold or turnover overlay—for example, a single frozen variance-ratio persistence state with an ex-ante holding budget.
