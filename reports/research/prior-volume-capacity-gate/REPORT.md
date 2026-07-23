# Prior-Volume Capacity Gate for the Canonical 5 bps Strategy

## Hypothesis

A USD 1,000,000 account following the canonical 5 bps BTC-USDT and ETH-USDT walk-forward paths can execute every observed position adjustment at no more than 0.10% of the strictly lagged 30-session median daily quote volume.

The economic rationale is that a live candidate needs an explicit account-size capacity bound before spread, slippage, impact, or paper execution can be interpreted. The estimator is deliberately ex ante at each adjustment: only quote volume observed through the previous completed daily bar enters the 30-session median.

Exactly one account-size candidate was tested. No alternate capital, participation threshold, lookback, market subset, fee, delay, or acceptance rule was selected after the result was observed.

## Verdict: rejected

```text
searched: 1
passed:   0
rejected: 1
capacity gate: fail
live eligible: false
```

## Exact canonical 5 bps metrics

| Market | Net return | CAGR | Annualized mean | Sharpe | Sortino | Calmar | Max drawdown | Annual turnover | Profitable folds |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | +142.091668% | 14.489118% | 16.130522% | 0.706720 | 1.086817 | 0.510060 | -28.406668% | 16.425319 | 12/27 |
| ETH-USDT | +110.570789% | 12.070883% | 14.545921% | 0.579467 | 0.851835 | 0.413662 | -29.180568% | 17.301475 | 17/27 |

The fixed selected paths remain viable under the repository's aggregate 7.5, 10, and 15 bps repricings, but those scenarios do not separately measure spread, slippage, market impact, or latency.

## Fixed capacity method

- Initial account capital: USD 1,000,000.
- Trade notional: absolute position turnover × prior-day NAV multiple × initial capital.
- Liquidity proxy: median OKX daily quote volume over the previous 30 completed sessions, shifted by one session.
- Participation limit: 0.10% of that lagged liquidity proxy.
- Adjustment threshold: absolute turnover greater than `1e-12`.
- Pass rule: zero participation-limit breaches in both development markets.
- Baseline fee: 5 bps one-way exchange fee.
- Data: verified OKX spot BTC-USDT and ETH-USDT `1Dutc`, 2,385 OOS observations per market from January 11, 2020 through July 22, 2026 UTC.

## Capacity results

| Market | Adjustment days | Breach days | Breach share | Median participation | 95th percentile | Maximum participation | Implied max initial capital |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 1,316 | 133 | 10.1064% | 0.0201% | 0.1679% | 0.7774% | USD 128,640.83 |
| ETH-USDT | 1,416 | 307 | 21.6808% | 0.0361% | 0.2459% | 0.8894% | USD 112,440.02 |

BTC's worst participation occurred on January 19, 2023. ETH's worst occurred on August 28, 2023. The USD 1,000,000 candidate therefore breaches the fixed 0.10% limit in both markets and fails the joint capacity gate.

The implied maximum initial-capital figures are the most restrictive observed account sizes that would have kept every historical adjustment at or below the same participation limit, after allowing the account equity path to grow or shrink. They are descriptive development-market bounds, not deployment recommendations.

## Source and provenance

- Source workflow: `30052415258`.
- Source artifact: `8581531945`, `quant-research-source-392-attempt-1`.
- Source archive SHA-256: `1ccdf6ad90250df0f4cc4cd2d8261f47ff29949b36fe78ab037db94910874cf0`.
- BTC snapshot SHA-256: `407aeba3d1ad4c8e8682a6a689c1c6327139f42bc7587aaae75c77fce047dec1`.
- BTC returns SHA-256: `04a0a5257d1e20f1eb88c70b8a0b010d21f0dc35ccb657ba39f14189e9f20790`.
- ETH snapshot SHA-256: `842b4bbbb0ad7afbe2a1c9ee375443671d818a799266d5dc25cc6a548571ad7f`.
- ETH returns SHA-256: `4b69db4a44644a5f830e1518aca93356c0eeacf502dc00ba990bd992b9bd387f`.

## Live-gate status

| Gate | Status |
|---|---|
| Corrected 5 bps full walk-forward | pass |
| Benchmark-relative risk-adjusted evidence | fail |
| Fold stability | fail |
| Year stability | fail |
| 5/7.5/10/15 bps fixed-path viability | pass |
| Parameter-neighbourhood stability | pass |
| Tail risk | pass |
| Execution-delay robustness | fail |
| Capacity at USD 1,000,000 and 0.10% participation | **fail** |
| Separate spread/slippage/impact/latency | blocked |
| Untouched-market validation | fail |
| Prospective forward validation | blocked |
| Overall live eligibility | **false** |

## Limitations

Daily quote volume is not order-book depth and does not prove a fill can be obtained near the close, next open, or touch. The proxy does not model intraday volume concentration, spread, slippage, nonlinear impact, partial fills, rejection, or latency. BTC and ETH remain development markets; the consumed SOL holdout was not used.
