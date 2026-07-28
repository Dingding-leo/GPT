# S0 development-market replication diagnostic

## Scope

This report independently replays and stress-tests the already-consumed canonical BTC-USDT and ETH-USDT 1H artifacts from workflow run `30094766694`. It does **not** inspect a new market, consume untouched replication, or authorize paper/live trading.

Frozen policy identity:

```text
selector       fold_local_argmax_score_v1
bar            1H
fee            5 bps one-way on absolute turnover
selection      17,520 hours
OOS fold       2,160 hours
candidate grid 3 × 3 × 3 = 27
code commit    8387124b64d3ca4b9f196258a6928cc8d653e2ad
policy hash    26da7a4b8039265cb98626352db3ec18c5987cd4325607e230b4e1a533961bf7
```

Source artifact ZIP digests were independently verified:

```text
BTC-USDT     58c48dfb9128bc05eaae05ae94c333fc7ad5e5e5dcce8befcccb7dad9bde7b9d
ETH-USDT     7d41955af3448cbc4ec20f7867d8254a0c448f2b0ae887b5384fb0f013a028cd
cross-market 3de7d726197aeaa2d399d3437271f138aad25712aace2b93adf1f80df3c6f094
```

All 13 files listed in each market's `artifact-manifest.sha256` were rehashed successfully. The persisted return accounting reconstructed to machine precision under:

```text
strategy_return = position × asset_return - turnover × 0.0005
```

## Canonical results

| Metric | BTC-USDT | ETH-USDT | Worst market |
|---|---:|---:|---:|
| Net total return | 43.59% | 16.31% | 16.31% |
| Net Sharpe | 0.637 | 0.342 | 0.342 |
| Max drawdown | -26.84% | -29.03% | -29.03% |
| Annualized turnover | 45.23 | 62.38 | 62.38 |
| Net edge / turnover | 33.18 bps | 12.05 bps | 12.05 bps |
| Profitable folds | 4 / 12 | 5 / 12 | fail |
| Max positive-fold share | 59.55% | 37.40% | BTC fail |
| Sharpe of return residual versus simple trend | -0.818 | -0.587 | fail |

The equal-weight cross-market series is an inference summary only, not an executable cross-sectional strategy. It returned 30.89% with Sharpe 0.542 and maximum drawdown -26.31%.

## Temporal breadth

The apparent aggregate profit is not stable across calendar periods.

BTC-USDT:

- 2023 partial: +6.57%, Sharpe 0.788
- 2024: +43.93%, Sharpe 1.211
- 2025: +3.09%, Sharpe 0.289
- 2026 partial: -9.20%, Sharpe -2.948

ETH-USDT:

- 2023 partial: -0.27%, Sharpe 0.017
- 2024: -5.28%, Sharpe -0.052
- 2025: +39.33%, Sharpe 1.589
- 2026 partial: -11.63%, Sharpe -2.208

The two markets derive their strongest evidence from different years. Both are negative in the 2026 partial interval, and neither reaches the frozen `6 / 12` profitable-fold threshold.

## Strategy-facing robustness

### One additional hour of latency

The same position sequence was delayed by one further hour and turnover/5-bps fees were recomputed from the delayed positions.

- BTC-USDT: 44.10% return, Sharpe 0.642, 33.45 bps net edge/turnover.
- ETH-USDT: 14.93% return, Sharpe 0.324, 11.40 bps net edge/turnover.

This stress does not destroy the result, but it does not repair fold breadth or benchmark-relative weakness.

### Paired moving-block bootstrap

Using aligned BTC/ETH timestamps, 168-hour blocks, 5,000 resamples and seed `20260728`:

| Statistic | Median | 95% interval | P(>0) |
|---|---:|---:|---:|
| Worst-market canonical Sharpe | 0.271 | [-0.930, 1.442] | 66.84% |
| Worst-market Sharpe with +1H latency | 0.260 | [-0.942, 1.435] | 66.16% |
| Worst-market Sharpe residual versus simple trend | -0.980 | [-2.056, 0.051] | 3.28% |

The canonical worst-market Sharpe is not statistically separated from zero. More importantly, the active selector materially underperforms the simple-trend benchmark on a residual basis in both markets.

## Verdict

```text
reject_current_s0_as_replication_nominee
```

Reasons:

- BTC has only 4/12 profitable folds and one fold contributes 59.55% of positive fold return.
- ETH has only 5/12 profitable folds.
- Strategy-minus-simple-trend residual Sharpe is negative in both markets.
- The worst-market canonical Sharpe 95% bootstrap lower bound is below zero.
- The worst-market simple-trend residual Sharpe 95% interval is overwhelmingly non-positive.
- Repository-wide family counts remain incomplete, so numerical Deflated Sharpe is fail-closed.
- Complete candidate-by-fold returns are absent, so CSCV/PBO is not supportable.

No new-market result was inspected and no untouched replication was consumed. The next strategy-facing step remains completion of issue #536's training-only 27-candidate evidence table and its single frozen S0-S5 comparison. Only a qualifying, content-addressed policy may start the prospective cross-asset cohort.
