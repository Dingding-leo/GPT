# Volatility-state expert switch v1

## Verdict

`rejected_exact_family_cooldown`

This development-only diagnostic tested one causal per-instrument volatility-regime mixture. During `rv24 > rv168`, the policy used the frozen 2,160-hour simple-trend long/cash target; otherwise it used the unchanged canonical walk-forward target. The policy used one-hour delayed execution and exactly 5 bps one-way fees.

The candidate improved BTC return, Sharpe, drawdown and fold breadth versus the canonical baseline, but it did not beat simple trend and its edge per turnover deteriorated. On ETH it reduced return, Sharpe, fold/year breadth and tail performance versus the canonical baseline. The exact state/expert mapping is rejected and cannot be retuned on the same BTC/ETH development window.

## Immutable evidence

- main base: `fccf70844adae76c1ca4bc8a225b64a9cc236d34`
- issue: `#554`
- BTC artifact: `8685574446`
- BTC ZIP SHA-256: `d36b151d0279e552f0f561403647ca8495febf6bd7c87c0b85cf0e7ad3df6119`
- ETH artifact: `8685572234`
- ETH ZIP SHA-256: `e32884abe83663b36bc52ce4f4b3cc60b03bb2f4f2948853134dc6831706a9bb`
- sample: 25,920 OOS 1H rows per market, 12 folds, 2023-07-24 through 2026-07-07 UTC
- fee: exactly 5 bps one-way on absolute turnover
- candidate count: 1
- policy-fold evaluations: 48
- untouched markets/OOS consumed: none

Each ZIP digest matched the declared GitHub artifact digest. All 13 files in each artifact passed the embedded SHA-256 manifest. Canonical asset returns, baseline strategy returns and the simple-trend benchmark were independently reconstructed with maximum hourly errors below `1e-12`.

## Frozen policy

For completed hour `t`:

```text
r_t         = log(close_t / close_{t-1})
rv24_t      = std(r_{t-23:t}, ddof=0)
rv168_t     = std(r_{t-167:t}, ddof=0)
expansion_t = rv24_t > rv168_t
trend_t     = 1[close_t / close_{t-2160} - 1 > 0]
```

```text
E0 target = canonical walk-forward target
E1 target = trend_t if expansion_t else E0 target
```

Missing state or trend history forces cash. A target computed after hour `t` first earns return in `t+1`. At selector fold boundaries, the candidate preserves the canonical new-fold pre-window target semantics.

## Results

| Market | Policy | Net return | Sharpe | Calmar | Max drawdown | Annual turnover | Edge/turnover | Profitable folds | Profitable years |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC | E0 | 43.59% | 0.637 | 0.485 | -26.84% | 45.23 | 33.18 bps | 4/12 | 3/4 |
| BTC | E1 | 85.05% | 0.848 | 1.014 | -22.81% | 144.12 | 17.51 bps | 6/12 | 3/4 |
| BTC | Simple trend | 111.72% | 0.917 | 1.273 | -22.67% | 68.94 | 45.11 bps | — | — |
| ETH | E0 | 16.31% | 0.342 | 0.180 | -29.03% | 62.38 | 12.05 bps | 5/12 | 3/4 |
| ETH | E1 | 3.94% | 0.216 | 0.030 | -43.47% | 174.21 | 4.41 bps | 4/12 | 2/4 |
| ETH | Simple trend | 67.92% | 0.617 | 0.405 | -47.31% | 47.31 | 57.86 bps | — | — |

E1 expansion occupancy was 38.81% for BTC and 37.43% for ETH. The policy generated 932 and 928 state transitions, respectively.

## Failure mechanism

The state switch had some gross directional value but was not a realizable improvement:

```text
BTC annualized gross mean delta vs E0   +15.18 percentage points
BTC annualized fee delta vs E0           +4.94 percentage points
BTC annualized net mean delta vs E0     +10.23 percentage points

ETH annualized gross mean delta vs E0    +5.76 percentage points
ETH annualized fee delta vs E0           +5.59 percentage points
ETH annualized net mean delta vs E0      +0.17 percentage points
```

The two experts disagreed in approximately 67% of OOS hours. Rows immediately following a volatility-state transition accounted for 63.14% of BTC E1 turnover and 69.64% of ETH E1 turnover. E1 reduced the count of tiny adjustments but replaced them with large binary expert switches, increasing modeled fee sums from `0.0669` to `0.2132` for BTC and from `0.0923` to `0.2577` for ETH.

BTC benefited from using slow trend during expansion, but simple trend still dominated E1 on Sharpe and edge per turnover. ETH did not replicate the relationship: E1 underperformed E0 and suffered materially worse drawdown and tail losses.

## Uncertainty

Paired, non-circular 168-hour moving blocks were resampled within each fold. Every boundary row was preserved exactly once. The same indices were used for E0, E1 and simple trend.

```text
resamples  5,000
seed       20260728
family     2 markets × 2 baselines × 2 endpoints
correction Holm across 8 one-sided tests
```

All Holm-adjusted p-values were `1.0`.

Selected one-sided 95% lower bounds:

```text
BTC E1-E0 Sharpe       -0.0272
BTC E1-E0 edge         -45.38 bps
BTC E1-trend Sharpe    -0.3549
BTC E1-trend edge      -57.46 bps

ETH E1-E0 Sharpe       -0.8748
ETH E1-E0 edge         -34.37 bps
ETH E1-trend Sharpe    -0.8679
ETH E1-trend edge     -123.22 bps
```

## Validation and repair

- exact artifact ZIP digest verification: pass
- embedded manifest verification: 13/13 files per market
- continuous confirmed 1H source grid: pass
- baseline target/position/turnover/fee reconstruction: pass
- simple-trend hourly benchmark parity: pass
- future-suffix invariance: pass
- deterministic full rerun: byte-identical

The initial result artifact did not explicitly bind the downloaded ZIP digest or quantify state-transition turnover. Those omissions were repaired before publication, and the full experiment was rerun. The verdict was unchanged.

## Cooldown and next experiment

Cooldown signature:

```text
rv24_gt_rv168_switch_to_2160h_simple_trend_else_canonical
| 1h delay | 5bps | BTC/ETH consumed development
```

Do not rescue this family by reversing the mapping, adding blend weights, smoothing the state, changing 24/168/2,160-hour windows, adding minimum duration or adding hysteresis on the same development window.

The next non-duplicative liquidity experiment should use prospectively captured public spread/depth and individual-trade data to estimate actual resilience or state transition costs. It should not construct another OHLCV regime switch or cash overlay.
