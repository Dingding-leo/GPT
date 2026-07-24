# Canonical BTC-USDT 1h Paper-Gate Audit

## Hypothesis

The canonical BTC-USDT `1H` full-reselection strategy clears every minimum source, strict
walk-forward/OOS, benchmark-relative, fold/month/year stability, turnover, holding-period,
trade-count, parameter-neighbourhood, tail-risk, capacity, cross-market, maker-execution,
and prospective paper gate at exactly **5 bps one-way exchange fee**.

Exactly one architecture candidate was evaluated. The fold-local selector disclosed and
searched all 27 declared parameter combinations in each of 12 non-overlapping OOS folds. No
spread, slippage, impact, latency, or alternative all-in cost was added to PnL.

## Economic rationale

Moving from daily to hourly bars should produce materially more adjustment and holding
episodes, allowing evidence to accumulate faster. That increased activity is useful only if
it retains a net 5 bps OOS edge and remains stable across folds, months, years, neighbouring
parameters, and markets. A profitable path that loses to simple same-window benchmarks or
concentrates its gains in a minority of periods is churn rather than live-eligible evidence.

## Source and fixed design

- Provider: public OKX spot candles.
- Instrument: BTC-USDT.
- Bar: `1H`.
- Source workflow: `30062329424`.
- Source artifact: `8585012784`.
- Source head: `0f76d9671a009cb8b397ad4ef64c5a311ff35b7b`.
- OOS window: 2023-07-01 00:00 UTC through 2026-06-14 23:00 UTC.
- OOS observations: 25,920.
- Selection/test windows: 17,520 / 2,160 hourly bars.
- Internal candidate grid: 27 combinations.
- Execution: one-bar-delayed close-to-close research return.
- Modeled cost: exactly 5 bps one-way exchange fee.

The downloaded source has 44,378 completed hourly bars from July 1, 2021 through July 24,
2026, with zero missing intervals and no conflicting duplicates. The final 938 bars were not
used because they did not complete another 2,160-bar OOS fold.

## Exact 5 bps OOS metrics

| Metric | BTC-USDT 1h strategy |
|---|---:|
| Net total return | +24.349120% |
| Net CAGR | +7.642985% |
| Annualized arithmetic mean | +9.651856% |
| Sharpe | 0.451522 |
| Sortino | 0.630578 |
| Calmar | 0.278783 |
| Maximum drawdown | -27.415541% |
| Annualized turnover | 52.958205 |
| Average absolute exposure | 29.224036% |
| Exchange-fee sum | 7.834912% |

## Benchmark-relative result

| Same-window 1h path | Net total return | Sharpe | Calmar | Max drawdown |
|---|---:|---:|---:|---:|
| Strategy | +24.349120% | 0.451522 | 0.278783 | -27.415541% |
| Buy and hold | +115.619855% | 0.791293 | 0.560892 | -52.863290% |
| Volatility-targeted long | +113.232642% | 0.803233 | 0.548765 | -53.144214% |
| Simple trend long/cash | +97.358726% | 0.843921 | 0.880335 | -29.341593% |

The strategy has lower drawdown than the continuous-exposure benchmarks, but it does not
beat any tested benchmark on Sharpe or Calmar. The benchmark-relative risk-adjusted gate
therefore fails on point estimates before stronger uncertainty evidence is considered.

## Stability and activity inventory

- Profitable folds: **5 / 12**; fold-stability gate failed.
- Best fold: +28.364620%; worst fold: -11.236308%.
- Complete months: 35; profitable complete months: **13 / 35**; month-stability gate failed.
- Complete years: only 2024 and 2025; the minimum three-year evidence gate failed.
- Position-adjustment observations: 14,397, annualized to 4,865.65.
- Exposure episodes: 170, annualized to 57.45.
- Median holding period: 3 hours; mean: 83.69 hours; maximum: 4,738 hours.
- Effective turnover-equivalent round trips: 26.48 per year.
- All four declared parameter perturbations remained net profitable with positive Sharpe.
- Daily-equivalent 5% hourly expected shortfall was -0.578019%, versus -1.136076% for
  volatility-targeted long.

The activity and tail-risk diagnostics pass their minimum evidence rules, but the higher
turnover does not deliver benchmark-relative edge or broad period stability.

## Separate maker and execution diagnostics

The following diagnostics are explicitly **not** added to PnL and are currently unavailable:

- maker/post-only fill quality;
- no-fill frequency;
- partial fills;
- timeout/requote outcomes;
- adverse selection after accepted fills;
- signal-to-intent and intent-to-quote latency.

Capacity is also blocked because no frozen point-in-time hourly participation protocol has
been persisted. ETH-USDT hourly replication and prospective maker paper evidence are absent.

## Gate result

| Gate | Status |
|---|---|
| Source-complete and reproducible BTC 1h evidence | Pass |
| Positive 5 bps OOS path | Pass |
| Benchmark-relative risk-adjusted evidence | **Fail** |
| Fold stability | **Fail** |
| Month stability | **Fail** |
| Year stability | **Fail** |
| Turnover, holding-period, and trade-count sufficiency | Pass |
| Parameter-neighbourhood stability | Pass |
| Tail risk | Pass |
| ETH-USDT cross-market replication | Blocked |
| Hourly capacity | Blocked |
| Maker execution diagnostics | Blocked |
| Prospective paper evidence | Blocked |
| Paper-testable | **False** |
| Live-eligible | **False** |

## Verdict: rejected

The first canonical hourly path is genuinely net profitable after the exact 5 bps fee and
produces much more activity than the daily strategy. It is nevertheless rejected because
its Sharpe and Calmar trail all same-window benchmarks, only 5 of 12 folds and 13 of 35
complete months are profitable, complete-year evidence is too short, and the ETH, capacity,
maker-execution, and prospective-paper gates are absent.

This result is a baseline rejection, not permission to tune small BTC-only variants. The
hourly source pipeline should first become common-window complete for BTC and ETH, after
which one materially justified architecture can be frozen and tested under the same gate.
