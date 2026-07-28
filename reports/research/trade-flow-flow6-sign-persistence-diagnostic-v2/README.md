# Flow6 sign-persistence diagnostic

## Scope

This is a bounded, non-family prospective diagnostic under active family `okx-spot-causal-trade-flow-resilience-v2`. It does not read the frozen 1,080-day development window or 180-day untouched archive window, does not modify V1/V2, and does not authorize parameter changes.

## Frozen hypothesis

For each instrument independently, aggregate all verified public spot trades over six completed UTC hours:

```text
flow6_h = sum(signed taker quote notional over h-5..h)
          / sum(total quote notional over h-5..h)

target_h = 1 if flow6_h > 0 else 0
```

The target becomes available only after hour `h` closes and earns the canonical confirmed candle return from close `h` to close `h+1`. The first five hours remain cash. The diagnostic starts in cash and forces a terminal exit, charging exactly 5 bps one-way on every absolute position change.

## Immutable real-data sample

```text
Trade interval           2026-07-23 16:00 to 2026-07-24 16:00 UTC
Complete trade hours     24 per market
Eligible decisions       19 per market
BTC individual trades    367,392
ETH individual trades    261,544
Markets                  BTC-USDT and ETH-USDT independently
Candidate count          1 diagnostic; frozen V1/V2 budget unchanged
```

The trade bytes come from PR #572's repaired archive/schema checkpoint. PnL uses the immutable confirmed OKX 1H candle snapshots from canonical BTC/ETH artifacts.

## Results

| Market | Net return | Diagnostic Sharpe | Max drawdown | Turnover | Edge/turnover | Time long | Adjustments |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | -1.0924% | -22.595 | -1.5460% | 4.0 | -27.33 bps | 94.74% | 4 |
| ETH-USDT | +0.2562% | +7.101 | -0.4686% | 4.0 | +6.47 bps | 31.58% | 4 |

The fixed 2,160H simple-trend comparator was cash throughout the same 19 decisions in both markets. BTC therefore had negative residual Sharpe and negative edge after fees. ETH was locally positive but did not provide adjusted evidence.

BTC's six-hour flow was positive for 18 of 19 eligible decisions, creating near-continuous exposure during a losing interval. ETH was positive for 6 of 19 decisions.

## Uncertainty repair

The first private calculation bootstrapped each market separately and emphasized annualized values from only 19 hours. The published result repairs this by:

- using identical non-circular 6H moving-block indices across BTC and ETH;
- testing only two worst-market endpoints;
- applying Holm correction across those endpoints;
- labeling annualized Sharpe as diagnostic-only.

```text
Resamples                                      5,000
Worst-market mean residual lower bound         -0.14176% per hour
Worst-market residual Sharpe lower bound       -56.415
Holm-adjusted p-values                          1.0, 1.0
```

## Causal checks

- exact 24-hour trade grid: pass;
- all candles confirmed: pass;
- signal-to-return delay: one complete hour, pass;
- future-suffix mutation leaves prior flow6 values unchanged: pass;
- source instrument identity and immutable source hashes: persisted.

## Verdict

```text
flow6_sign_persistence_premise_rejected_on_bounded_diagnostic
```

This rejects only the unstandardized six-hour directional-persistence premise on this bounded epoch. It neither accepts nor rejects frozen V1/V2. The next permitted family experiment remains the predeclared 720H V2 flow-response residual comparison after PR #572 is merged and issue #14 explicitly authorizes development acquisition.
