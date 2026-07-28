# Independent replication verdict — frozen 2160H simple trend

## Verdict

`rejected_as_next_active_architecture`

The unchanged per-instrument 2,160-hour binary long/cash rule was independently run on the complete pre-performance, current-live, liquidity-qualified replication universe. No market was removed after performance inspection.

- policy SHA-256: `56c237a06be11bbedaba46161604934ee5af7aad93fa7b163c45dc971bb4c58d`
- universe SHA-256: `cbf73f83b5ada0716a221504acf620af6d6b2ce21f0a99a39cec0c38494eb152`
- artifact SHA-256: `dc6da3988a80f7b8854062f23785327848bbf4ff53bb0a12183906bec280b1b4`
- evaluation: 25,920 confirmed 1H observations per market, 2023-07-24 through 2026-07-07 UTC
- fee: exactly 5 bps one-way
- frozen universe: `CFX-USDT`, `DOGE-USDT`, `FIL-USDT`, `LTC-USDT`, `SOL-USDT`, `XRP-USDT`

| Market | Net return | Sharpe | Max drawdown | Annual turnover | Edge/turnover | Profitable folds | Residual Sharpe vs buy-and-hold | Largest positive-fold share |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| CFX-USDT | -47.40% | 0.122 | -83.93% | 62.19 | 15.62 bps | 4/12 | -0.022 | 57.6% |
| DOGE-USDT | +20.79% | 0.448 | -67.58% | 84.49 | 38.13 bps | 2/12 | -0.195 | 61.7% |
| FIL-USDT | -60.49% | -0.174 | -84.68% | 71.65 | -15.45 bps | 2/12 | +0.020 | 51.2% |
| LTC-USDT | +3.88% | 0.309 | -41.90% | 82.46 | 21.36 bps | 5/12 | +0.289 | 44.0% |
| SOL-USDT | +210.70% | 0.898 | -54.94% | 67.59 | 92.62 bps | 6/12 | -0.287 | 72.8% |
| XRP-USDT | -3.79% | 0.292 | -67.23% | 109.50 | 16.74 bps | 3/12 | -0.552 | 90.5% |

Only 3/6 markets had positive net return. Median net return was +0.05%, median Sharpe 0.301 and median edge/turnover 19.05 bps, but median buy-and-hold residual Sharpe was -0.108. FIL was the worst market at -60.49%, far below the frozen -15% floor.

The diagnostic equal-weight series returned +31.72% with Sharpe 0.437, but it was concentrated: SOL supplied 44.6% of all positive cross-market annualized arithmetic mean. The pooled path had only 6/12 profitable folds, 2/4 profitable years and a 54.0% largest-positive-fold share.

The 5,000-resample, 168H within-fold bootstrap reproduced exactly. The one-sided 95% lower bound for cross-market median annualized mean was -26.84%, so the uncertainty gate failed.

A pre-result supplemental own-market lagged-168H volatility diagnostic found that the strategy had positive conditional mean in all six markets in the highest-volatility quartile, but only one of six had positive residual Sharpe versus buy-and-hold there. The apparent high-volatility strength is therefore market participation, not robust incremental timing alpha.

Artifact manifest, policy hash, universe, every hourly strategy row, all market metrics, bootstrap output and future-suffix invariance were independently reconstructed. Maximum hourly absolute error was below `1.0e-16`.

The acquisition defect that originally yielded a zero universe was repaired before any strategy return was calculated by anchoring the first historical page at the frozen end boundary. The repaired run is the sole performance comparison.

No parameter or market refinement is authorized from these replication outcomes. The 2,160H rule must not be rescued by changing its lookback, threshold, universe or execution timing on this evidence.
