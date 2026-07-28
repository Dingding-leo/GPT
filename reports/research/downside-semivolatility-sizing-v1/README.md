# Downside-Semivolatility Sizing v1

## Verdict

`reject_exact_family_cooldown`

The single predeclared candidate in issue #546 materially improves tail-risk metrics, but it reduces net return, Sharpe, Calmar, and edge per turnover in both development markets. It also increases turnover because the hourly risk multiplier changes continuously. The exact 24H/720H inverse-semivolatility rule is rejected and may not be rescued on this BTC/ETH window by changing windows, floors, smoothing, or thresholds.

## Frozen policy

- D0: unchanged canonical target.
- D1: `q_t * min(1, downside_semivol_720h / downside_semivol_24h)`.
- Downside semivolatility is `sqrt(mean(min(r, 0)^2))`.
- Windows use completed target-instrument returns through close `t`; the sized target first affects the next 1H return.
- Missing or zero short-window downside risk falls back to the canonical target.
- Exposure can only be reduced, never increased.
- State and position carry across folds; fold-start positions are sized from the risk multiplier known at the preceding close.
- Fee remains exactly 5 bps one-way on absolute position adjustment.

## Immutable evidence

Workflow run `30347175588`, source head `d7cc15839755484b682d6e9094298b8a32f70230`. Each market uses 25,920 OOS hours from 2023-07-24 00:00 UTC through 2026-07-07 23:00 UTC, plus immutable pre-OOS snapshot history only for the causal downside-risk windows.

| Market | Returns CSV SHA-256 | Snapshot CSV SHA-256 |
|---|---|---|
| BTC-USDT | `72b34a405914057a71d6d47fa60251a591060d9d5220c717fbcf179b7073f1a6` | `cea7c085aead0f901c7634b116f6a0253bf5d8fe5b8595f99398badb8733f1c9` |
| ETH-USDT | `e243fc10586536d83a416d6241ad8b3061d5bb0bb5b2493a1a23e539fcba9d1d` | `939f9e64a5f94347d3bfa9f3026deefdb1b72c8dada9121bcb3772cc3b2c75c2` |

All artifact-manifest entries, baseline position/turnover/fee/return identities, canonical summary metrics, and snapshot-to-OOS returns were independently reconstructed within `1e-11`.

## Strategy metrics

### BTC-USDT

| Metric | D0 | D1 | Change |
|---|---:|---:|---:|
| Net total return | 43.5898% | 22.8353% | -20.7545 pp |
| Sharpe | 0.6369 | 0.4445 | -0.1923 |
| CAGR | 13.0061% | 7.1983% | -5.8078 pp |
| Calmar | 0.4845 | 0.2931 | -0.1915 |
| Max drawdown | -26.8428% | -24.5624% | +2.2804 pp |
| 1% expected shortfall | -1.2503% | -1.0486% | +0.2017 pp |
| Worst 24H | -12.8674% | -6.7437% | +6.1237 pp |
| Worst 168H | -21.0904% | -14.7171% | +6.3733 pp |
| Annualized turnover | 45.2257 | 66.4297 | +21.2040 |
| Exchange-fee sum | 6.6909% | 9.8280% | +3.1370 pp |
| Net edge / turnover | 33.18 bps | 13.55 bps | -19.63 bps |
| Average absolute exposure | 35.9580% | 32.9065% | -3.0515 pp |

Profitable folds: 4/12 → 4/12. Residual Sharpe versus simple trend: -0.8180 → -1.0543.

The multiplier is below one in 32.14% of hours, with mean 0.9167 and minimum 0.2333.

### ETH-USDT

| Metric | D0 | D1 | Change |
|---|---:|---:|---:|
| Net total return | 16.3126% | 2.9289% | -13.3837 pp |
| Sharpe | 0.3425 | 0.1462 | -0.1963 |
| CAGR | 5.2397% | 0.9804% | -4.2592 pp |
| Calmar | 0.1805 | 0.0381 | -0.1424 |
| Max drawdown | -29.0291% | -25.7447% | +3.2844 pp |
| 1% expected shortfall | -1.1721% | -0.9932% | +0.1788 pp |
| Worst 24H | -9.8338% | -5.2437% | +4.5901 pp |
| Worst 168H | -16.6010% | -12.9831% | +3.6179 pp |
| Annualized turnover | 62.3810 | 72.5408 | +10.1598 |
| Exchange-fee sum | 9.2290% | 10.7321% | +1.5031 pp |
| Net edge / turnover | 12.05 bps | 3.82 bps | -8.23 bps |
| Average absolute exposure | 23.3487% | 21.3274% | -2.0214 pp |

Profitable folds: 5/12 → 4/12. Residual Sharpe versus simple trend: -0.5867 → -0.7100.

The multiplier is below one in 32.24% of hours, with mean 0.9170 and minimum 0.2224.

## Statistical result

Paired resampling uses 168-hour non-circular blocks within each fold, 5,000 resamples, seed `20260728`. The confirmatory family contains BTC/ETH Sharpe improvement and BTC/ETH 1% expected-shortfall improvement; Holm correction covers four tests.

| Market | Sharpe difference | Basic one-sided 95% lower bound | Holm p | ES improvement | Basic one-sided 95% lower bound | Holm p |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | -0.1923 | -0.4248 | 1.000000 | +0.2017 pp | +0.1195 pp | 0.001200 |
| ETH-USDT | -0.1963 | -0.3937 | 1.000000 | +0.1788 pp | +0.1224 pp | 0.000800 |

Tail protection is statistically supported, but Sharpe deterioration is decisive. The family fails the frozen joint acceptance rule in both markets.

## Economic diagnosis

- The rule reduces exposure during the most severe downside-risk expansions and sharply improves worst-24H, worst-168H, maximum drawdown, and 1% expected shortfall.
- However, the multiplier changes every hour. Annualized turnover rises from 45.23 to 66.43 in BTC and from 62.38 to 72.54 in ETH, increasing the modeled fee burden.
- Mild and moderate downside-risk expansions are not reliable avoid states. The sizing rule cuts exposure through many hours that subsequently contribute positive recovery returns, while only the rare severe-below-0.5 regime shows a positive D1-minus-D0 conditional mean.
- BTC net return falls from 43.59% to 22.84%; ETH falls from 16.31% to 2.93%. Edge per turnover falls by 19.63 bps and 8.23 bps respectively.
- The candidate does not improve the rejected base strategy relative to simple trend; residual Sharpe becomes more negative in both markets.

## Capacity diagnostics

At USD 1,000,000, D1 implies approximately USD 66.43M annual adjustment notional and USD 33,215 modeled exchange fees for BTC, and USD 72.54M / USD 36,270 for ETH. Public spread, depth, impact, latency, and fill evidence are not modeled, so USD 1M remains a scaling blocker. The candidate is rejected at all rungs on strategy economics before liquidity capacity is considered.

## Experiment accounting

- New architecture families: 1.
- New candidate policies: 1.
- New candidate-market evaluations: 2.
- Untouched replication consumed: false.
- Prospective evidence consumed: false.
- Machine-readable result SHA-256: `017c07d8f3e765260ffc236755fcab6a7d291b4466b14761686cc6ce55ee8178`.

## Next strategy-facing experiment

Do not rescue this continuous inverse-semivolatility family. A genuinely different follow-up would use a discrete, causally detected downside-risk state transition with persistence and recovery confirmation, so exposure changes only at onset or exit rather than every hour. That architecture must be separately predeclared and should be evaluated only after the selector dependency is resolved.
