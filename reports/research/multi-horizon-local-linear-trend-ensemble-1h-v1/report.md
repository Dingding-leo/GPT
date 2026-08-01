# Multi-horizon local-linear trend ensemble 1H evidence

```text
family          multi-horizon-local-linear-trend-ensemble-1h-v1
candidate count 1
parameter grid  0
fee one way     0.0005
accepted        False
verdict         reject_multi_horizon_local_linear_trend_ensemble_architecture_v1
```

## Data and sample

Immutable public Binance SPOT 1H archives from 2023-04-01 through 2025-12-31; 24,144 exact contiguous rows per market.

## Strategy metrics

| Market | Segment | Candidate net | Sharpe | Max DD | Turnover | Trend net | Equal net |
|---|---:|---:|---:|---:|---:|---:|---:|
| XTZUSDT | train | +10.0580% | +0.4476 | -28.7071% | 58 | -4.9430% | +10.9138% |
| XTZUSDT | oos | +9.3391% | +0.4227 | -66.9152% | 78 | +36.5317% | +5.3469% |
| XTZUSDT | full | +20.3364% | +0.4274 | -66.9152% | 136 | +29.7830% | +16.8442% |
| ZECUSDT | train | -33.3151% | -0.5332 | -36.0054% | 52 | -60.4964% | -36.6910% |
| ZECUSDT | oos | +497.4092% | +1.6292 | -61.9892% | 98 | +919.2487% | +537.9989% |
| ZECUSDT | full | +298.3818% | +1.0648 | -61.9892% | 150 | +302.6398% | +303.9109% |

## Frozen weights and forecast evidence

### XTZUSDT

- weights 24H/168H/720H: `0.310447`, `0.342644`, `0.346909`
- weighted OOS RMSE/log score: `0.048929` / `-1.511532`
- equal OOS RMSE/log score: `0.049021` / `-1.509660`
- candidate-minus-trend mean CI, bps/hour: `[-1.030864740852394, 0.5726713254099414]`
- candidate-minus-trend Sharpe CI: `[-1.382599553945707, 0.7494529115632429]`
- delayed OOS net: `+0.0998%`
- failed gates: `return_above_trend_and_equal, sharpe_above_trend_and_equal, drawdown_better_than_trend, edge_per_turnover, breadth, positive_fold_concentration, bootstrap_lower_bounds, turnover_bounded`

### ZECUSDT

- weights 24H/168H/720H: `0.311823`, `0.342154`, `0.346023`
- weighted OOS RMSE/log score: `0.069969` / `-0.661194`
- equal OOS RMSE/log score: `0.070082` / `-0.659554`
- candidate-minus-trend mean CI, bps/hour: `[-1.7165137700942865, 0.6456822816786879]`
- candidate-minus-trend Sharpe CI: `[-1.1443675165481453, 0.6449480910790233]`
- delayed OOS net: `+652.6375%`
- failed gates: `return_above_trend_and_equal, sharpe_above_trend_and_equal, drawdown_better_than_trend, edge_per_turnover, breadth, positive_fold_concentration, bootstrap_lower_bounds, turnover_bounded`

## Disposition

Verdict: `reject_multi_horizon_local_linear_trend_ensemble_architecture_v1`.

No cross-sectional selection, pairs/spreads, shorting, leverage, synthetic data, private endpoint, account, order, enabled adapter, or 15m input was used.
