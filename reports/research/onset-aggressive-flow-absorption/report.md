# Onset-only aggressive-flow absorption selector — terminal evidence

- Architecture: `onset-aggressive-flow-absorption-selector-1h-v1`
- Candidate count: `1`; parameter grid: `0`
- Market evaluated: `BTC-USDT` first-market falsification
- Data: immutable public OKX SPOT individual-trade features plus confirmed 1H candles
- Fee: exactly `5 bps` one way; next-open execution
- Verdict: `reject_exact_onset_aggressive_flow_absorption_selector_family`

## Performance

| Sample | Policy | Net | Sharpe | Max DD | Turnover | Edge/turn (bps) |
|---|---|---:|---:|---:|---:|---:|
| training | candidate | +58.78% | 1.372 | -22.61% | 16.0 | 338.38 |
| training | benchmark | +40.81% | 1.053 | -31.37% | 22.0 | 193.19 |
| development_oos | candidate | +140.70% | 1.406 | -22.68% | 17.0 | 593.58 |
| development_oos | benchmark | +123.95% | 1.303 | -22.68% | 25.0 | 375.08 |
| full_scored | candidate | +282.18% | 1.392 | -22.68% | 33.0 | 469.85 |
| full_scored | benchmark | +215.35% | 1.211 | -31.37% | 47.0 | 289.94 |

## Breadth and uncertainty

- Profitable OOS folds: `5/8`; improved versus benchmark: `2/8`.
- Profitable OOS calendar years: `2/3`; improved years: `2/3`.
- Positive-fold concentration: `41.04%`.
- Residual Sharpe: `1.352`.
- Annualised mean delta 95% interval: `[0.00%, 9.36%]`.
- Sharpe delta 95% interval: `[0.000, 0.269]`.
- Zero-delta bootstrap share: `4.40%`.

## Failure mechanism

The selector vetoed `4` of `12` OOS trend onsets. All vetoed regimes lasted one day, so the candidate differed from the benchmark for only `96` hours (`0.58%` of OOS). It omitted `-6.74%` arithmetic market carry and saved `0.40%` in fees, producing `+7.14%` arithmetic improvement.

The largest single veto supplied `66.01%` of the total arithmetic improvement. The non-selectable diagnostic price-only shadow was OOS-identical to the candidate: `True`. Therefore the public trade-flow sign added no incremental OOS discrimination beyond the already-observed negative 24H price return.

The aggregate point estimate passed all deterministic benchmark-relative gates, but both preregistered dependence-aware lower bounds were exactly zero because the improvement was confined to four one-day events in two folds. Strictly positive uncertainty support was not established.

## Verdict

Failed gates: `mean_delta_lower_bound_strictly_positive, sharpe_delta_lower_bound_strictly_positive`.

`reject_exact_onset_aggressive_flow_absorption_selector_family`

ETH was not acquired or scored because the frozen first-market gate failed. No same-interval horizon, inequality, onset rule, lockout, fee, timing, or market-specific rescue is authorised.
