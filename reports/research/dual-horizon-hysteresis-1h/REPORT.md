# Dual-Horizon Hysteresis 1h Architecture

## Hypothesis

A fixed 168-hour/720-hour trend-confirmation state machine with mixed-state hysteresis and 720-hour volatility targeting passes every retrospective 1h research gate in BTC-USDT and ETH-USDT at exactly 5 bps one-way, and is ready for prospective maker-paper evaluation.

Canonical signature:

`dual-horizon-hysteresis-vol-target-1h-v1|markets=BTC-USDT,ETH-USDT|provider=OKX-spot|bar=1H|source=portable-canonical-1h-artifacts|architecture=fast-and-slow-trend-confirmation-with-mixed-state-hysteresis|fast=168h|slow=720h|volatility=720h|target-volatility=0.50|max-position=1|fee=5bps-one-way|execution=one-bar-delayed-close-return|evaluation=2023-07-01T00:00Z..2026-06-14T23:00Z|fold=2160h|benchmark-inference=paired-noncircular-moving-block-bootstrap-168h|resamples=2000|confidence=0.95|architecture-candidate-count=1`

## Fixed design

- Provider: OKX public spot candles.
- Markets: BTC-USDT and ETH-USDT development evidence.
- Bar: `1H`.
- Exact modeled cost: 5 bps one-way exchange fee only.
- Fast trend: 168-hour trailing return.
- Slow trend: 720-hour trailing return.
- Enter long when both trend returns are positive; exit to cash when both are negative; retain the prior regime when signs disagree.
- Scale the long regime to a 50% annualized-volatility target using a causal 720-hour volatility estimate, capped at 1.0.
- Lag the resulting target by one complete hourly bar before applying returns.
- Evaluate the fixed architecture from 2023-07-01 00:00 UTC through 2026-06-14 23:00 UTC.
- Exactly one architecture candidate was tested. Four predeclared parameter-neighbourhood paths are robustness checks, not selected alternatives.
- Benchmark inference uses paired non-circular 168-hour moving blocks, 2,000 resamples, and 95% confidence.

## Exact 5 bps results

| Market | Net return | CAGR | Sharpe | Sortino | Calmar | Max drawdown | Annual turnover | Exposure |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | +134.868328% | +33.451952% | 1.075792 | 1.540587 | 1.002924 | -33.354438% | 29.169854 | 54.704899% |
| ETH-USDT | +174.329628% | +40.643590% | 1.178202 | 1.710959 | 1.337420 | -30.389549% | 31.365475 | 40.361406% |

Both point-performance paths materially improve on the rejected canonical trend/reversal selector, but predeclared uncertainty, breadth, and capacity gates still fail.

## Benchmark-relative inference

### BTC-USDT

| Benchmark | Sharpe delta (95% interval) | Calmar delta (95% interval) |
|---|---:|---:|
| buy_and_hold | +0.284499 [-0.445205, +1.135758] | +0.442032 [-1.027853, +2.327233] |
| volatility_targeted_long | +0.272559 [-0.473523, +1.138057] | +0.454159 [-1.050173, +2.329803] |
| simple_trend_long_cash | +0.231870 [-0.599069, +1.039664] | +0.122588 [-1.282048, +2.296332] |

### ETH-USDT

| Benchmark | Sharpe delta (95% interval) | Calmar delta (95% interval) |
|---|---:|---:|
| buy_and_hold | +0.921898 [+0.050896, +1.793401] | +1.392206 [+0.082402, +3.812033] |
| volatility_targeted_long | +0.903650 [+0.052958, +1.786818] | +1.316851 [+0.032050, +3.738254] |
| simple_trend_long_cash | +0.638648 [-0.246203, +1.544486] | +1.017640 [-0.462654, +3.453919] |

No market clears the rule requiring both Sharpe and Calmar lower confidence bounds to be positive against every declared benchmark.

## Stability and implementation diagnostics

| Market | Profitable folds | Profitable complete months | Profitable complete years | Episodes/year | Median hold | Capacity breaches | Max supported initial capital |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 5/12 | 16/35 | 2/2 | 15.208333 | 91 h | 128/4005 | USD 3,881.07 |
| ETH-USDT | 6/12 | 12/35 | 2/2 | 17.236111 | 45 h | 323/8899 | USD 2,437.88 |

- BTC fails fold breadth with 5 profitable folds out of 12; ETH reaches 6 of 12.
- Both markets fail complete-month breadth.
- Both complete calendar years are profitable in both markets.
- All four predeclared neighbourhood paths remain profitable with Sharpe above 0.50.
- The strategy 5% expected shortfall is less severe than all three benchmark tails in both markets.
- The USD 1 million, 0.10% lagged hourly-volume participation gate fails in both markets.

## Verdict: rejected

```text
Architecture candidates searched: 1
Passed:                         0
Rejected:                       1
Paper-testable:                 false
Live-eligible:                  false
```

The architecture is economically interesting but not eligible for maker-paper promotion. Its benchmark-relative confidence intervals, calendar breadth, and point-in-time capacity evidence do not pass. No spread, slippage, impact, latency, alternative fee path, account, or order result is included in PnL.

## Provenance

- BTC-USDT: artifact `8586473477`, ZIP SHA-256 `44ef21be41117768f34422bff2458ef3daf1709b6335387c8ddc9d23077ebed7`, manifest SHA-256 `16548b4abd0f2508a4c6646c30a04117fec7686e92b9a95028d142a2f0532216`, snapshot SHA-256 `bbba1e9b36e17b03ff6aed237a4de949b4a39b1d17eaf1b4979627794acb909c`.
- ETH-USDT: artifact `8586463176`, ZIP SHA-256 `fa13b5333b4bdfae02fc653351ea25f203e953315dd70d318cb47a82341c528d`, manifest SHA-256 `95d9535f9e4badd736844f3a31e8d43e067032e32b44e406affa0932dc190aa8`, snapshot SHA-256 `37f33ce7a55786a10f4c8e0f7ff1c870f331792b6ba1712229008480498ea236`.

Both portable manifests were independently verified before analysis. The sources contain completed, hourly, public OKX candles and the exact persisted 5 bps-only benchmark paths.

## Remaining blockers

- Benchmark-relative lower-bound evidence.
- Fold and complete-month stability.
- Point-in-time capacity at the declared USD 1 million scale.
- Prospective maker fill quality, no-fill, partial-fill, timeout, adverse-selection, and latency diagnostics.
- Prospective paper performance.

The next research step should not tune this architecture on the same BTC/ETH window. It should either reject the family or predeclare one materially different mechanism before evaluation.
