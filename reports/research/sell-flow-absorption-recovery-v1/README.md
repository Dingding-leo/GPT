# Sell-flow absorption next-hour recovery — bounded prospective diagnostic

## Classification

This is a one-candidate, 24-hour prospective falsification diagnostic. It does not alter the two frozen V1/V2 candidates in issue #537 and does not authorize full development acquisition or untouched-evidence use.

## Frozen hypothesis

For each target instrument and each completed UTC hour, sort all verified individual trades by `(timestamp_ms, numeric_trade_id)` and calculate:

- `flow = signed taker quote notional / total quote notional`;
- `impact_return = log(last_trade_price / first_trade_price)`.

The candidate is long for the next executable hour only when `flow < 0` and `impact_return >= 0`, interpreting aggressive selling with nonnegative price response as passive-liquidity absorption. Otherwise it remains in cash.

The target formed from hour `h` is applied at the open of `h+1`; PnL is observed open-to-next-open. Every absolute position change costs exactly 5 bps one way. A terminal 5-bps liquidation is charged to close the bounded diagnostic symmetrically.

## Immutable data

- Trade-flow checkpoint workflow `30367844773`, artifact `8691619707`, ZIP SHA-256 `275dd35af6ab74c42b8aac2e272af274dbe9256cca3609345ee8dfa76d524932`.
- Repaired source-checkpoint workflow `30369985594`, artifact `8692496533`, ZIP SHA-256 `f14b9f75f27d149364eb099932f9a74391fcad9eda1e72eeda399a0c80b6730b`. Its BTC and ETH archive CSV bytes are identical to the primary diagnostic input, so the strategy metrics are unchanged.
- Canonical BTC artifact `8685574446`, ZIP SHA-256 `d36b151d0279e552f0f561403647ca8495febf6bd7c87c0b85cf0e7ad3df6119`.
- Canonical ETH artifact `8685572234`, ZIP SHA-256 `e32884abe83663b36bc52ce4f4b3cc60b03bb2f4f2948853134dc6831706a9bb`.
- Feature window: 2026-07-23 16:00 through 2026-07-24 15:00 UTC.
- Executable return window: 2026-07-23 17:00 through 2026-07-24 17:00 UTC.
- 24 complete feature hours and 24 executable 1H returns per market; missing hours: zero.

## Results

| Market | Signal hours | Net return | Gross return | Sharpe* | Max drawdown | Turnover | Edge/turnover | Fee burden |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 1/24 | -0.0621% | +0.0379% | -23.29 | -0.0621% | 2.0 | -3.10 bps | 0.10% |
| ETH-USDT | 4/24 | -1.4091% | -1.0133% | -43.46 | -1.4091% | 8.0 | -17.71 bps | 0.40% |

`*` Annualised Sharpe is reported mechanically but is not promotion-grade with only 24 observations.

The fixed 2,160H simple-trend benchmark remained cash in both markets, returning zero. BTC produced one gross-positive absorption hour, but entry and exit fees converted it to a net loss. ETH absorption hours averaged -25.42 bps before fees and lost in both volatility regimes.

### Causal volatility regimes

- BTC: the only signal occurred in compression and lost -0.0621% net; no expansion signal occurred.
- ETH: two signals occurred in compression and two in expansion. Net returns were -0.7645% and -0.6495%, respectively; edge per turnover was negative in both states.

No market had a profitable 6-hour block. Positive-block concentration is therefore undefined and fails closed.

## Uncertainty

The diagnostic used 5,000 paired non-circular 6-hour moving-block resamples over the 24 hourly observations, seed `20260728`, with Holm correction across BTC and ETH candidate-minus-simple-trend annualised-mean endpoints.

- BTC one-sided 95% lower bound: -45.33 percentage points annualised; Holm-adjusted p = 1.0.
- ETH one-sided 95% lower bound: -799.70 percentage points annualised; Holm-adjusted p = 1.0.

The annualised scale is unstable on a one-day sample; the relevant conclusion is that neither market provides positive bounded evidence and ETH is strongly adverse. DSR was not calculated because the deduplicated global family count is unavailable. PBO is inapplicable to one fixed diagnostic without candidate selection.

## Methodological repair

The first private draft aligned the simple-trend benchmark to the execution-hour close, which is unavailable at the execution open. The final run uses the completed feature-hour close and keeps benchmark formation one full hour behind its PnL return. The correction changed no metric because simple trend was cash throughout.

Additional checks passed:

- strict instrument identity;
- exactly 24 consecutive archive hours;
- canonical `(timestamp_ms, numeric_trade_id)` ordering;
- no trade-ID/time inversion;
- one-hour feature-to-execution delay;
- future-suffix mutation left all 23 prior feature hours unchanged;
- two complete reruns produced byte-identical JSON.

## Verdict

`sell_flow_absorption_recovery_rejected_by_bounded_prospective_diagnostic`

Cooldown signature:

`flow<0_and_impact>=0_one-hour-long_cash_5bps_forced-terminal-exit_BTC-ETH_2026-07-23T16_to_2026-07-24T16_feature_window`

Do not rescue this sign-only rule by adding thresholds, extending the hold, changing the flow or impact signs, removing the terminal cost, conditioning on one observed regime, or selecting ETH/BTC after inspection. The next valid trade-flow test remains the already frozen V2 720H flow-response residual after issue #537 passes its source checkpoint and development acquisition is explicitly authorised.
