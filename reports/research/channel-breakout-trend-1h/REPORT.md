# 1h Channel Breakout Trend Architecture

## Hypothesis

A fixed long/cash `1H` channel-breakout architecture clears every retrospective architecture-freeze gate in both BTC-USDT and ETH-USDT at exactly 5 bps one-way and is eligible for prospective post-only paper evaluation.

## Fixed architecture

- Public OKX spot BTC-USDT and ETH-USDT completed `1H` candles.
- Enter when the closing price is strictly above the previous 24-hour high and the 168-hour log return is positive.
- Exit when the closing price is strictly below the previous 24-hour low or the 168-hour log return is non-positive.
- While long, target 50% annualized volatility using the causal 168-hour realized volatility estimate, capped at one.
- Target position computed at close `t` becomes executable for return `t+1`.
- Evaluation starts from cash.
- PnL includes exactly 5 bps one-way per unit position turnover and no other friction.
- Exactly one architecture candidate was tested.

The economic rationale is that a channel breakout requires observable strength beyond the prior day’s range, while the weekly trend regime filters countertrend entries. This is materially different from the rejected trend/reversal selector, dual-horizon trend confirmation, and pullback-recovery architecture families.

## Exact 5 bps results

| Market | Gross return | Net return | CAGR | Sharpe | Sortino | Calmar | Max drawdown | Annual turnover | Profitable folds | Profitable months |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | +72.4307% | **+41.0817%** | +12.3351% | 0.6069 | 0.8829 | 0.4701 | -26.2382% | 135.6421 | 6/12 | 18/35 |
| ETH-USDT | +22.9408% | **+2.1088%** | +0.7078% | 0.1591 | 0.2319 | 0.0187 | -37.7735% | 125.5015 | 6/12 | 12/35 |

BTC retained positive net performance after fees, but ETH’s small residual return and low Sharpe did not clear the predeclared viability threshold. Both markets had only six profitable folds. BTC lost 7.98% in complete calendar year 2025; ETH lost 0.57% in 2024. Annual turnover exceeded the declared ceiling in both markets.

## Benchmark-relative inference

Paired non-circular 168-hour moving-block bootstrap used 2,000 resamples per market. Every 95% lower bound for the Sharpe and Calmar delta versus buy-and-hold, volatility-targeted long, and simple-trend long/cash was negative. The benchmark-relative gate failed in both markets.

The strategy’s 5% hourly expected shortfall was less severe than volatility-targeted long in both markets, but this isolated tail result did not override the performance, breadth, turnover, capacity, and benchmark-relative failures.

## Activity and implementation diagnostics

| Market | Completed episodes | Episodes/year | Median hold | Profit factor | USD 1m capacity breaches |
|---|---:|---:|---:|---:|---:|
| BTC-USDT | 205 | 69.28 | 26 h | 1.264 | 523 / 2,375 adjustments |
| ETH-USDT | 208 | 70.30 | 22 h | 1.073 | 745 / 5,168 adjustments |

The architecture produced materially more episodes than the daily system, but the additional activity did not create a robust 5 bps OOS edge. The lagged hourly-volume capacity proxy also rejected a USD 1 million account under the fixed 0.10% participation limit.

Maker fill quality, no-fill, partial fill, timeout, adverse selection, latency, and prospective paper performance remain separate blocked diagnostics. None was added to PnL or inferred from candles.

## Candidate accounting

```text
Architecture candidates searched: 1
Passed:                         0
Rejected:                       1
Neighbourhood paths:            4
Bootstrap resamples/market:     2,000
Paper-testable:                 false
Live-eligible:                  false
```

All four predeclared neighbourhood paths remained profitable with positive Sharpe in BTC. ETH’s 120-hour regime/volatility neighbourhood lost money, so the joint neighbourhood gate also failed.

## Verdict: rejected

The architecture is active and BTC-profitable after exact 5 bps fees, but it does not replicate in ETH and fails benchmark-relative confidence, fold/year breadth, turnover, parameter-neighbourhood, and capacity requirements. It is not eligible for prospective paper execution.

## Provenance

Portable canonical `1H` evidence from PR #475:

- BTC artifact `8586473477`; ZIP SHA-256 `44ef21be41117768f34422bff2458ef3daf1709b6335387c8ddc9d23077ebed7`; manifest SHA-256 `16548b4abd0f2508a4c6646c30a04117fec7686e92b9a95028d142a2f0532216`; snapshot SHA-256 `bbba1e9b36e17b03ff6aed237a4de949b4a39b1d17eaf1b4979627794acb909c`.
- ETH artifact `8586463176`; ZIP SHA-256 `fa13b5333b4bdfae02fc653351ea25f203e953315dd70d318cb47a82341c528d`; manifest SHA-256 `95d9535f9e4badd736844f3a31e8d43e067032e32b44e406affa0932dc190aa8`; snapshot SHA-256 `37f33ce7a55786a10f4c8e0f7ff1c870f331792b6ba1712229008480498ea236`.

Both artifacts and every internal manifest entry were hash-verified before calculation. The strict OOS window contains 25,920 observations per market from July 1, 2023 through June 14, 2026 UTC.
