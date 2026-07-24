# Canonical ETH-USDT 1h Cross-Market Replication

## Hypothesis

The frozen canonical ETH-USDT `1H` full-reselection replication clears every minimum
source, exact-fee-profile, strict walk-forward/OOS, benchmark-relative, fold/month/year
stability, activity, parameter-neighbourhood, tail-risk, capacity, maker-execution, and
prospective paper gate at exactly **5 bps one-way exchange fee**.

Exactly one architecture candidate was evaluated. The fold-local selector disclosed all 27
declared parameter combinations in each of 12 non-overlapping OOS folds, for 324 candidate
evaluations. No spread, slippage, market impact, latency, or alternative all-in cost was added
to the canonical PnL claim.

## Economic rationale

The first BTC-USDT hourly result produced materially more adjustments and exposure episodes
than the daily system but failed benchmark and stability gates. ETH-USDT is the required
cross-market replication test for that frozen architecture. A genuinely useful hourly design
should preserve its 5 bps edge across markets rather than relying on BTC-specific path luck.

## Source and design

- Provider: public OKX spot candles.
- Instrument: ETH-USDT.
- Bar: `1H`.
- Source workflow: `30063491425`.
- Source artifact: `8585425240`.
- Source artifact SHA-256:
  `5770a6f850d81614734d45fe988ba83bc25263a31137877e371e0ee4a75ec46d`.
- Source head: `1d1da8d6f0cfb1cbd99e5533c693da139572bdc3`.
- Source range: July 1, 2021 through July 24, 2026 UTC.
- OOS range: July 1, 2023 through June 14, 2026 UTC.
- OOS observations: 25,920.
- Selection/test windows: 17,520 / 2,160 hourly bars.
- Internal grid: 27 candidates per fold.
- Execution model: one-bar-delayed close-to-close research return.
- Canonical modeled cost: exactly 5 bps one way.

The source has 44,379 completed hourly candles, no duplicate or missing intervals, and one
unconfirmed row removed. Persisted verification reconstructed all 12 folds, 25,920 position
rows, and 324 candidate evaluations from the immutable normalized OKX source.

## Exact 5 bps result

| Metric | ETH-USDT 1h |
|---|---:|
| Gross total return | +31.817076% |
| Net total return | **+21.375687%** |
| Net CAGR | +6.766105% |
| Annualized arithmetic mean | +9.371057% |
| Sharpe | 0.394513 |
| Sortino | 0.550796 |
| Calmar | 0.211795 |
| Maximum drawdown | -31.946417% |
| Annualized turnover | 55.779779 |
| Average absolute exposure | 24.001747% |
| Exchange-fee sum | 8.252351% |

## Benchmark comparison

| Same-window path | Net total return | Sharpe | Calmar | Maximum drawdown |
|---|---:|---:|---:|---:|
| Strategy | +21.375687% | 0.394513 | 0.211795 | -31.946417% |
| Buy and hold | -10.798637% | 0.256304 | -0.054786 | -69.149428% |
| Volatility-targeted long | +3.996922% | 0.274553 | 0.020569 | -64.822696% |
| Simple trend long/cash | +51.722887% | 0.539554 | 0.319779 | -47.313904% |

The strategy beats buy-and-hold and volatility-targeted long on Sharpe and Calmar, but trails
the simple-trend long/cash benchmark on both. The predeclared all-benchmark risk-adjusted gate
therefore fails.

## Stability and activity

- Profitable folds: **4 / 12**; fold-stability gate failed.
- Best fold: +22.713040%; worst fold: -16.714840%.
- Complete months: 35; profitable complete months: **9 / 35**; month gate failed.
- Complete years: two; only 2025 was profitable. The minimum three-year gate failed.
- Position-adjustment observations: 13,867, annualized to 4,686.53.
- Exposure episodes: 175, annualized to 59.14.
- Median holding period: 5 hours; mean 78.24 hours; maximum 4,361 hours.
- Turnover-equivalent round trips: 27.89 per year.
- All four declared parameter-neighbourhood paths remained profitable with positive Sharpe.
- Hourly 5% expected shortfall was -0.642434%, versus -1.276662% for volatility-targeted long.

The activity, neighbourhood, and tail-risk gates pass. Higher turnover still does not deliver
broad fold/month/year stability or the required benchmark-relative edge.

## Exact-cost-profile defect

The source profile declared `cost_multipliers: [1.0]`, but the executed configuration and
report persisted `[1.0, 2.0]` because the engine injected an undeclared doubled-cost diagnostic.
The 5 bps aggregate path is internally reconciled and is the only PnL result reported here;
the undeclared 10 bps diagnostic is excluded from all claims. Nevertheless, exact profile
fidelity fails until the correction in PR #464 is integrated and the artifact is regenerated.

## Gate result

| Gate | Status |
|---|---|
| Immutable source and full reselection verification | Pass |
| Exact 5 bps-only profile fidelity | **Fail** |
| Positive 5 bps OOS path | Pass |
| Benchmark-relative risk-adjusted evidence | **Fail** |
| Fold stability | **Fail** |
| Month stability | **Fail** |
| Year stability | **Fail** |
| Turnover, holding-period, and episode sufficiency | Pass |
| Parameter-neighbourhood stability | Pass |
| Tail risk | Pass |
| Cross-market replication | **Fail** |
| Point-in-time hourly capacity | Blocked |
| Maker fill/no-fill/partial/timeout/adverse-selection/latency diagnostics | Blocked |
| Prospective maker paper evidence | Blocked |
| Paper-testable | **False** |
| Live-eligible | **False** |

## Verdict: rejected

ETH-USDT confirms that the hourly architecture can produce a positive 5 bps OOS path with
substantially more activity than the daily system. It does not replicate a live-eligible edge:
it trails the simple-trend benchmark, only 4 of 12 folds and 9 of 35 complete months are
profitable, complete-year evidence is insufficient, and execution/capacity/prospective gates
remain absent. The source artifact also fails exact 5 bps-only profile fidelity.

This is a frozen-architecture rejection, not permission to tune small BTC/ETH variants. The
next architecture must be materially different and predeclared before another full OOS test.
