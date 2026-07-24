# Regime-Conditioned Pullback Recovery 1h

## Hypothesis

A fixed 1H regime-conditioned pullback-recovery architecture clears every retrospective architecture-freeze gate in BTC-USDT and ETH-USDT at exactly 5 bps one-way and is eligible for prospective post-only paper evaluation.

The architecture was predeclared before the BTC/ETH development artifacts were evaluated. Exactly one architecture candidate was tested; four one-axis parameter paths are robustness checks, not searched alternatives.

## Fixed architecture

- Provider: OKX public spot `1H` candles.
- Long-horizon regime: trailing 720-hour return must be positive.
- Pullback trigger: 24-hour log-price z-score at or below `-1.5`.
- Exit: z-score at or above `-0.25`, regime failure, or 48-hour timeout.
- Episode size: frozen at entry using a causal 168-hour realised-volatility target of 50%, capped at 1.0.
- Execution: one complete hourly bar delay.
- Modeled PnL cost: exactly 5 bps one-way exchange fee.
- Spread, slippage, impact, latency and maker-fill outcomes are not included in PnL.

## Result: rejected

```text
architecture candidates searched: 1
passed: 0
rejected: 1
paper testable: false
live eligible: false
```

### Exact 5 bps metrics

| Market | Net return | CAGR | Sharpe | Sortino | Calmar | Max drawdown | Annual turnover | Episodes/year | Median hold |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | -5.750657% | -1.981731% | -0.045551 | -0.062336 | -0.072160 | -27.462851% | 237.399239 | 123.02 | 9h |
| ETH-USDT | -14.387394% | -5.114413% | -0.209284 | -0.273926 | -0.190468 | -26.851857% | 168.923107 | 98.01 | 8h |

Gross returns were positive, but 5 bps one-way fees converted both paths to negative net results. The architecture therefore fails before any maker-paper promotion.

### Benchmark-relative inference

#### BTC-USDT

| Benchmark | Sharpe delta (95% interval) | Calmar delta (95% interval) |
|---|---:|---:|
| buy_and_hold | -0.836843 [-1.939722, +0.357719] | -0.633052 [-3.129994, +0.491270] |
| volatility_targeted_long | -0.848784 [-1.962983, +0.345490] | -0.620925 [-3.147069, +0.488107] |
| simple_trend_long_cash | -0.889472 [-2.036862, +0.381218] | -0.952496 [-3.327787, +0.424885] |

#### ETH-USDT

| Benchmark | Sharpe delta (95% interval) | Calmar delta (95% interval) |
|---|---:|---:|
| buy_and_hold | -0.465588 [-1.732923, +0.830901] | -0.135682 [-1.787912, +0.787761] |
| volatility_targeted_long | -0.483837 [-1.739276, +0.832802] | -0.211037 [-1.763435, +0.692114] |
| simple_trend_long_cash | -0.748838 [-2.085404, +0.589621] | -0.510247 [-2.522959, +0.515605] |

Every benchmark-relative Sharpe and Calmar lower confidence bound is negative.

### Stability, activity, and capacity

| Market | Profitable folds | Profitable complete months | Profitable complete years | Episode profit factor | Capacity breaches | Maximum supported initial capital |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 6/12 | 16/35 | 1/2 | 0.977924 | 727/727 | USD 3,529.53 |
| ETH-USDT | 5/12 | 14/35 | 1/2 | 0.933716 | 580/580 | USD 2,438.17 |

The mechanism produced many short episodes, but this was loss-making churn: turnover exceeded the predeclared ceiling in both markets and completed-episode profit factors were below one. Every USD 1 million adjustment breached the 0.10% lagged-volume participation limit.

### Parameter neighbourhoods

| Market | Variant | Net return | Sharpe |
|---|---|---:|---:|
| BTC-USDT | deeper_entry | -5.963589% | -0.058428 |
| BTC-USDT | longer_timeout | -4.674302% | -0.021433 |
| BTC-USDT | shallower_entry | -5.824219% | -0.041082 |
| BTC-USDT | shorter_timeout | -4.669073% | -0.021431 |
| ETH-USDT | deeper_entry | +0.821527% | 0.100116 |
| ETH-USDT | longer_timeout | -13.614865% | -0.191796 |
| ETH-USDT | shallower_entry | -9.982793% | -0.097487 |
| ETH-USDT | shorter_timeout | -9.698096% | -0.110391 |

No neighbourhood path met the predeclared positive-return and Sharpe-above-0.50 condition in both markets.

### Tail risk

| Market | Strategy 5% ES | Volatility-targeted-long 5% ES | Pass |
|---|---:|---:|---|
| BTC-USDT | -0.421392% | -1.136076% | true |
| ETH-USDT | -0.447209% | -1.276662% | true |

Tail severity was lower largely because average exposure was low. This isolated pass does not offset negative net performance, weak breadth, excessive turnover, or failed capacity.

## Provenance

- BTC-USDT: artifact `8586473477`, ZIP SHA-256 `44ef21be41117768f34422bff2458ef3daf1709b6335387c8ddc9d23077ebed7`, manifest SHA-256 `16548b4abd0f2508a4c6646c30a04117fec7686e92b9a95028d142a2f0532216`, snapshot SHA-256 `bbba1e9b36e17b03ff6aed237a4de949b4a39b1d17eaf1b4979627794acb909c`, 44,380 completed hourly bars from `2021-07-01T00:00:00+00:00` through `2026-07-24T03:00:00+00:00`.
- ETH-USDT: artifact `8586463176`, ZIP SHA-256 `fa13b5333b4bdfae02fc653351ea25f203e953315dd70d318cb47a82341c528d`, manifest SHA-256 `95d9535f9e4badd736844f3a31e8d43e067032e32b44e406affa0932dc190aa8`, snapshot SHA-256 `37f33ce7a55786a10f4c8e0f7ff1c870f331792b6ba1712229008480498ea236`, 44,380 completed hourly bars from `2021-07-01T00:00:00+00:00` through `2026-07-24T03:00:00+00:00`.

Both portable artifact manifests and every contained file were independently hash-verified before evaluation.

## Reproduction

```bash
python reports/research/regime-pullback-recovery-1h/generate_result.py \
  --btc-artifact-dir /path/to/canonical-BTC-USDT-1h-475 \
  --eth-artifact-dir /path/to/canonical-ETH-USDT-1h-475 \
  --output /tmp/recomputed-pullback-recovery.json

cmp -s \
  /tmp/recomputed-pullback-recovery.json \
  reports/research/regime-pullback-recovery-1h/result.json

pytest -q tests/test_regime_pullback_recovery_1h_report.py
```

## Deployment status

- Retrospective architecture-freeze gate: **failed**.
- Prospective post-only paper gate: **not authorized**.
- Maker fill quality, no-fill, partial fill, timeout, adverse selection, latency, and prospective performance: **blocked and kept outside modeled PnL**.
- Overall live eligibility: **false**.

## Limitations and disposition

BTC-USDT and ETH-USDT are development markets. The close-return model does not claim post-only fills. The USD 1 million capacity calculation uses a strictly lagged hourly quote-volume proxy rather than executable depth. No same-family retuning is justified: the point estimate, fee economics, breadth, neighbourhoods, and capacity all fail materially.

**Next task:** stop tuning this pullback family. Advance prospective maker diagnostics only for a different frozen architecture that first clears the retrospective BTC/ETH gates, or improve the evidence pipeline without presenting another nearby threshold variation.
