# Causal range-breakout hysteresis trend — terminal research report

## Objective

Test whether an instrument-local price-range state machine can encode persistent trend with materially lower turnover than the daily 2,160H endpoint trend benchmark. A strict break above the prior 2,160 completed-hour high establishes long exposure; only a strict break below the prior 720 completed-hour low returns the strategy to cash.

```text
family_id              causal-range-breakout-hysteresis-trend-1h-v1
candidate_count        1
parameter_grid_count   0
canonical_fee          exactly 5 bps one-way
decision cadence       daily 00:00 UTC
execution              completed bar t -> open[t+1]
verdict                reject_exact_causal_range_breakout_hysteresis_trend_family
```

## Frozen temporal rule

At each daily 00:00 UTC completed decision bar `t`, the entry level is `max(high[t-2160:t])` and the exit level is `min(low[t-720:t])`. The current bar is excluded from both levels. A cash state becomes long only when `close_t` is strictly above the entry level. A long state becomes cash only when `close_t` is strictly below the exit level. Equality does not trigger. State carries across folds and sample boundaries. There is no fitted threshold, trend gate, volatility filter, minimum hold, market-specific rule or parameter search.

## Immutable data and sample

| Market | Source artifact | CSV SHA-256 | Source observations | Parsed prefix |
|---|---:|---|---:|---:|
| BTC-USDT | 8704977298 | `92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9` | 43,941 | 43,441 |
| ETH-USDT | 8704978112 | `2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726` | 43,941 | 43,441 |

```text
source workflow       30401519824
warm-up               [0, 2,880)
training              [2,880, 17,520)
development OOS       [17,520, 43,440)
full scored           [2,880, 43,440)
OOS folds             12 x 2,160H
later suffix          unread and unscored
```

All source hashes, confirmed flags, one-hour continuity, OHLC validity, strict lag construction, daily decision timing, next-open position timing and exact fee accounting passed deterministic checks.

## Training

| Market | Policy | Net return | Sharpe | Max DD | Turnover | Fees | Edge/turn | Exposure | Entries |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | candidate | +24.29% | 0.652 | -21.73% | 1 | +0.05% | 2681.64 bps | +28.19% | 1 |
| BTC-USDT | b0 | -41.02% | -0.831 | -55.56% | 138 | +6.90% | -32.09 bps | +40.18% | 69 |
| BTC-USDT | b1 | -41.29% | -0.840 | -55.92% | 28 | +1.40% | -159.81 bps | +40.49% | 14 |
| ETH-USDT | candidate | -27.81% | -0.179 | -54.18% | 2 | +0.10% | -701.93 bps | +53.61% | 1 |
| ETH-USDT | b0 | -46.84% | -0.744 | -57.75% | 88 | +4.40% | -56.53 bps | +45.06% | 44 |
| ETH-USDT | b1 | -40.59% | -0.584 | -56.95% | 23 | +1.15% | -168.77 bps | +44.60% | 11 |

BTC produced a positive training result from one persistent holding state, whereas ETH lost money despite only two position changes. Training metrics were diagnostic only and did not alter the frozen architecture.

## Development OOS

| Market | Policy | Net return | Sharpe | Max DD | Turnover | Fees | Edge/turn | Exposure | Entries |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | candidate | +116.58% | 0.937 | -39.25% | 3 | +0.15% | 3148.67 bps | +54.54% | 1 |
| BTC-USDT | b0 | +111.64% | 0.917 | -22.68% | 203 | +10.15% | 45.31 bps | +57.25% | 101 |
| BTC-USDT | b1 | +119.68% | 0.954 | -26.55% | 45 | +2.25% | 212.75 bps | +57.32% | 22 |
| ETH-USDT | candidate | -41.43% | -0.012 | -70.50% | 4 | +0.20% | -53.50 bps | +78.80% | 2 |
| ETH-USDT | b0 | +68.02% | 0.618 | -47.30% | 139 | +6.95% | 58.31 bps | +49.70% | 69 |
| ETH-USDT | b1 | +74.52% | 0.646 | -47.77% | 30 | +1.50% | 283.58 bps | +49.72% | 15 |

BTC nearly matched B1 return and Sharpe with only three transitions, but its maximum drawdown deteriorated by 12.70 percentage points and it passed only 3 of 12 folds. ETH was a decisive cross-market rejection: negative return and Sharpe, a 70.50% maximum drawdown, negative edge per turnover, and severe underperformance versus both trend comparators.

## Full scored sample

| Market | Policy | Net return | Sharpe | Max DD | Turnover | Fees | Edge/turn | Exposure | Entries |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | candidate | +169.19% | 0.845 | -39.25% | 4 | +0.20% | 3031.91 bps | +45.03% | 2 |
| BTC-USDT | b0 | +24.82% | 0.310 | -55.56% | 341 | +17.05% | 13.98 bps | +51.08% | 170 |
| BTC-USDT | b1 | +28.97% | 0.332 | -55.92% | 73 | +3.65% | 69.85 bps | +51.25% | 36 |
| ETH-USDT | candidate | -57.72% | -0.064 | -70.50% | 6 | +0.30% | -269.64 bps | +69.70% | 3 |
| ETH-USDT | b0 | -10.68% | 0.158 | -57.75% | 227 | +11.35% | 13.79 bps | +48.03% | 113 |
| ETH-USDT | b1 | +3.68% | 0.233 | -56.95% | 53 | +2.65% | 87.28 bps | +47.87% | 26 |

The full sample remained highly divergent: BTC benefited from two unusually long profitable states, while ETH lost 57.72% with a 70.50% maximum drawdown. The identical architecture therefore did not replicate bilaterally.

## Breadth, residuals and uncertainty

| Market | Profitable folds | Profitable years | Positive-fold concentration | Residual Sharpe vs B0 | Residual Sharpe vs B1 | Mean Δ L95 | Sharpe Δ L95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 3/12 | 3/4 | +39.72% | 0.035 | -0.018 | -0.283873 | -0.808916 |
| ETH-USDT | 6/12 | 1/4 | +54.28% | -0.663 | -0.701 | -0.795515 | -1.579325 |

BTC failed profitable-fold breadth, residual Sharpe versus B1, drawdown and both uncertainty gates. ETH failed nearly every economic and statistical gate. Neither market had a strictly positive paired-bootstrap lower bound.

## Signal frequency and regime drift

| Market | Train entries / exits | OOS entries / exits | Train long target rate | OOS long target rate | OOS episodes | Median duration | Profitable episodes | Worst episode |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 1 / 0 | 1 / 2 | +28.20% | +54.54% | 2 | 294.5 days | +100.00% | +3.41% |
| ETH-USDT | 1 / 1 | 2 / 2 | +53.61% | +78.80% | 3 | 221.0 days | +33.33% | -40.64% |

The architecture achieved very low turnover by making extremely infrequent transitions, but this was not efficient selectivity. It often remained exposed for months after the trend quality had deteriorated. ETH OOS exposure rose to 78.80%, and its final OOS-overlapping episode lasted 14,543 hours and lost 40.64%.

## Failure decomposition and repaired discrepancy

| Market | Candidate-only hours vs B1 | Gross contribution | B1-only hours | Missed gross contribution | Worst 168H | Worst 720H | Arithmetic-minus-log gap |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 3,504 | +21.37% | 4,224 | +24.74% | -19.58% | -23.13% | 17.18 pp |
| ETH-USDT | 8,904 | -44.18% | 1,368 | +44.34% | -35.28% | -44.59% | 51.35 pp |

The first scorecard made ETH's modest arithmetic loss appear less severe than its compounded outcome. The reporting artifact was repaired by persisting log-compounding and rolling-loss diagnostics; no feature, state, position, fee, comparator, metric, acceptance gate or verdict changed.

ETH's arithmetic OOS net sum was only -2.14%, yet its compounded return was -41.43%. The 51.35 percentage-point arithmetic-minus-log gap, a -35.28% worst rolling 168H return and a -44.59% worst rolling 720H return show that long loss clusters and volatility drag overwhelmed the apparent low-turnover advantage. The state machine entered or retained 8,904 hours unavailable to B1 with -44.18% aggregate gross contribution, while omitting 1,368 B1-long hours that contributed +44.34% gross return.

BTC's issue was different: it produced positive long-run carry but accepted substantially deeper drawdowns than B1. Its sparse transitions made point estimates depend on only two OOS-overlapping holding episodes, so the result lacked fold breadth and bootstrap certainty.

## Acceptance verdict

```text
reject_exact_causal_range_breakout_hysteresis_trend_family
```

No entry window, exit window, equality rule, trend gate, volatility gate, holding period, cadence, execution, fee or market-specific rescue is authorised on this consumed development interval. There is no G1 nomination, prospective-paper promotion or live-trading authorisation.

## Remaining blocker and next experiment

The remaining blocker is unchanged: no statistically eligible frozen causal 1H strategy exists.

Before development-performance inspection, preregister one materially orthogonal own-history-only **low-frequency trend-coherence state**. Project the trailing 2,160H demeaned log-price path onto one fixed linear trend basis and one fixed low-frequency residual basis; require a positive causal slope and a training-frozen high trend-energy share for entry, and use one predeclared hysteretic state transition to control turnover. Use one candidate, no parameter grid, daily next-open execution, exactly 5 bps one-way fees, immutable OKX 1H provenance, untouched-suffix protection and the same bilateral return, efficiency, drawdown, breadth, residual and paired-block uncertainty gates.

## Reproducibility

```text
result SHA-256       93524f285b2b1408e95326f9e7908a6bdc1f6d6ebe6999305647b86a4bd4e3f7
reproducer SHA-256   1b2b0248f332ae969f479795395d0a107ca5402ce544d87c1924f6fdc47caa70
```

