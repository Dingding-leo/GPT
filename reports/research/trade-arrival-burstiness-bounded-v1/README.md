# Trade-arrival burstiness × positive flow — bounded real-data diagnostic

## Frozen hypothesis

Completed-hour aggressive flow should be more informative when transaction arrivals are temporally clustered. For each instrument and UTC hour, sort real public trades by `(timestamp_ms, numeric_trade_id)`, calculate inter-arrival gaps, and define:

```text
B_h = (std(delta_t) - mean(delta_t)) / (std(delta_t) + mean(delta_t))
candidate_position_h = max(0, signed_quote_flow_h) * max(0, B_h)
raw_flow_position_h = max(0, signed_quote_flow_h)
```

The completed hour is used only for the next 1H payoff. Every absolute position change and the bounded terminal exit pay exactly 5 bps one way.

## Immutable inputs

- Workflow run: `30378372866`
- Artifact: `8695917276`
- Artifact SHA-256: `85e51d072bd4fc7388421b411b58fd5d36ec10380b23ad7a179c0a98f153643a`
- Markets: BTC-USDT and ETH-USDT independently
- Feature interval: 2026-07-23 16:00 UTC through 2026-07-24 16:00 UTC
- Candidate count: 1
- Reserved 180-day interval: not read

## Results

| Market | Policy | Net return | Sharpe* | Max drawdown | Turnover | Fees | Edge/turnover | No-trade | 6H blocks |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Burst-weighted flow | -0.0545% | -13.581 | -0.1174% | 1.4692 | 0.0735% | -3.707 bps | 29.17% | 1/4 |
| BTC-USDT | Raw positive flow | -0.0885% | -11.169 | -0.2128% | 3.0119 | 0.1506% | -2.935 bps | 29.17% | 1/4 |
| BTC-USDT | Simple trend | 0.0000% | undefined | 0.0000% | 0.0000 | 0.0000% | undefined | 100.00% | 0/4 |
| ETH-USDT | Burst-weighted flow | -0.1533% | -24.039 | -0.1652% | 1.6949 | 0.0847% | -9.048 bps | 66.67% | 1/4 |
| ETH-USDT | Raw positive flow | -0.2862% | -23.283 | -0.3044% | 3.1885 | 0.1594% | -8.980 bps | 66.67% | 1/4 |
| ETH-USDT | Simple trend | 0.0000% | undefined | 0.0000% | 0.0000 | 0.0000% | undefined | 100.00% | 0/4 |

*Sharpe is a mechanical 24-observation diagnostic and is not promotion-grade.*

- BTC-USDT burstiness range: `0.394390` to `0.615400`, median `0.483574`; mean trades/hour `15308.0`.
- ETH-USDT burstiness range: `0.418304` to `0.622279`, median `0.522711`; mean trades/hour `10897.7`.

## Adjusted uncertainty

The paired non-circular 6H block bootstrap uses 5,000 common-calendar resamples. The sole initial-state row and bounded terminal-exit row are retained exactly once; only the 22 interior hours are resampled. This repairs an initial implementation that could omit or duplicate boundary fees.

| Worst-market endpoint | Observed | One-sided 95% lower bound | Holm p |
|---|---:|---:|---:|
| Burst − raw flow mean/hour | 0.1414 bps | -0.2999 bps | 0.562288 |
| Burst − trend mean/hour | -0.6390 bps | -1.2931 bps | 0.999000 |

## Causal and data checks

- `canonical_timestamp_trade_id_order`: pass
- `complete_24h_grid`: pass
- `future_suffix_invariance`: pass
- `instrument_identity`: pass
- `one_complete_hour_to_next_hour_payoff`: pass
- `symmetric_entry_exit_fee`: pass
- Exact archive and candle SHA-256 checks passed for both markets.
- Missing feature hours: 0/24 in each market.

## Verdict

```text
trade_arrival_burstiness_positive_flow_rejected_on_bounded_diagnostic
```

The candidate reduced turnover and losses relative to raw positive flow, but remained net negative with negative edge per turnover in both markets, underperformed the cash trend benchmark, had only 1/4 profitable six-hour blocks per market, and lacked positive Holm-adjusted evidence. The exact burstiness-weighted positive-flow premise is rejected on this bounded epoch and may not be rescued by changing the burstiness threshold, sign, holding period, market subset, or exponent.

The active #537/#579 V1/V2 family was not modified. No additional feature candidate is authorised until the frozen development comparison reaches a terminal verdict.

Result SHA-256: `0ff15873990be922b034444a0fb76202ff3953675cbdd178318ef71b6b8e6a52`
